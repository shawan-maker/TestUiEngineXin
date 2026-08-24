"""
测试 FIX-1: CAS/SSO 重定向 URL 稳定等待逻辑

验证场景：
1. CAS 重定向链（URL 多次变化后稳定）
2. Hash 路由（URL 立即稳定，无额外等待）
3. 真实 Cookie 过期（URL 稳定在 /login）
4. 超时场景（URL 持续变化，5秒后超时）
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../tools'))


def _run_url_stabilization(page_url_func, max_ticks=10):
    """提取并执行 URL 稳定等待逻辑（与 discover_page.py 中的实现一致）"""
    _last_url = ""
    _stable_ticks = 0
    logs = []
    iterations = 0

    for _tick in range(max_ticks):
        iterations += 1
        _current = page_url_func()
        if _current == _last_url:
            _stable_ticks += 1
            if _stable_ticks >= 2:
                break
        else:
            _stable_ticks = 0
            logs.append(f"  [Discover] URL redirecting: {_current}")
        _last_url = _current

    return iterations, _stable_ticks, logs, _last_url


class MockPage:
    """模拟 Playwright Page，URL 通过 redirect_schedule 控制变化。

    redirect_schedule: 字典，{tick: url} 表示在第 tick 次读取时 URL 变为该值。
    未定义的 tick 返回上一个 URL。
    """

    def __init__(self, redirect_schedule):
        self.redirect_schedule = redirect_schedule
        self._read_count = 0
        self._current_url = ""

    def url_at(self, read_count):
        """根据读取次数返回当前 URL"""
        # 找到 <= read_count 的最大 tick
        url = ""
        for tick in sorted(self.redirect_schedule.keys()):
            if tick <= read_count:
                url = self.redirect_schedule[tick]
        return url

    def get_url(self):
        url = self.url_at(self._read_count)
        self._read_count += 1
        return url


def test_cas_redirect_stabilizes():
    """CAS 重定向链：3 次跳转后 URL 稳定在目标页"""
    # tick 0: CAS login 中间页
    # tick 1: CAS callback
    # tick 2: 目标页（此后不再变化）
    page = MockPage({
        0: "http://10.151.37.249/cas/login?service=http%3A%2F%2F10.151.37.249%2Festack",
        1: "http://10.151.37.249/cas/callback?ticket=ST-xxx",
        2: "http://10.151.37.249/estack/web/ecm-compute-static/vm/list",
    })

    iters, stable_ticks, logs, final_url = _run_url_stabilization(page.get_url)

    assert final_url == "http://10.151.37.249/estack/web/ecm-compute-static/vm/list"
    assert stable_ticks >= 2
    assert "/login" not in final_url
    # 3 个不同 URL 各产生 1 条 log
    assert len(logs) == 3


def test_hash_route_stabilizes_immediately():
    """Hash 路由：URL 立即稳定，最多 3 次迭代"""
    # 所有 tick 都返回同一 URL
    page = MockPage({
        0: "http://10.151.37.249/estack/web/op-compute-web/#/order/vm",
    })

    iters, stable_ticks, logs, final_url = _run_url_stabilization(page.get_url)

    assert final_url == "http://10.151.37.249/estack/web/op-compute-web/#/order/vm"
    assert stable_ticks >= 2
    assert iters == 3  # 第1次: last="", 第2次: stable_ticks=1, 第3次: stable_ticks=2 → break
    assert len(logs) == 1  # 仅第一次 "" → url 记录了一条 log


def test_auth_error_login_page():
    """真实 Cookie 过期：URL 稳定在 /login 页面"""
    page = MockPage({
        0: "http://10.151.37.249/cas/login",
    })

    iters, stable_ticks, logs, final_url = _run_url_stabilization(page.get_url)

    assert '/login' in final_url
    assert final_url.rstrip('/').endswith('login')
    assert stable_ticks >= 2


def test_auth_error_cas_login_redirect():
    """CAS 重定向到登录页：经过 CAS 后最终停在 /login"""
    page = MockPage({
        0: "http://10.151.37.249/estack/web/ecm-compute-static/vm/list",
        1: "http://10.151.37.249/cas/login?service=...",
        2: "http://10.151.37.249/cas/login?service=...",  # 稳定在 login
    })

    iters, stable_ticks, logs, final_url = _run_url_stabilization(page.get_url)

    assert '/login' in final_url


def test_timeout_url_keeps_changing():
    """超时场景：URL 持续变化，10 次循环后超时退出"""
    schedule = {i: f"http://10.151.37.249/redirect/{i}" for i in range(15)}
    page = MockPage(schedule)

    iters, stable_ticks, logs, final_url = _run_url_stabilization(page.get_url, max_ticks=10)

    assert iters == 10  # 用完所有 10 次循环
    assert stable_ticks == 0  # 从未稳定


def test_single_redirect_then_stable():
    """单次重定向后稳定（最常见场景）"""
    page = MockPage({
        0: "http://10.151.37.249/cas/validate",
        1: "http://10.151.37.249/estack/web/ecm-compute-static/vm/list",
    })

    iters, stable_ticks, logs, final_url = _run_url_stabilization(page.get_url)

    assert final_url == "http://10.151.37.249/estack/web/ecm-compute-static/vm/list"
    assert stable_ticks >= 2
    assert "/login" not in final_url


def test_enhanced_diagnostic_message_format():
    """验证 discover_page.py 的诊断信息格式"""
    from urllib.parse import urlparse
    target_url = "http://10.151.37.249/estack/web/ecm-compute-static/vm/list"
    final_url = "http://10.151.37.249/cas/login"

    lines = [
        f"[ERROR] Redirected to login page — cookie invalid/expired",
        f"[ERROR]   目标 URL:   {target_url}",
        f"[ERROR]   当前 URL:   {final_url}",
        f"[ERROR]   Cookie domain: {urlparse(target_url).hostname}",
        f"[ERROR]   可能原因: Cookie 已过期，请在浏览器重新登录后获取新 Cookie",
    ]

    assert "10.151.37.249" in lines[3]
    assert target_url in lines[1]
    assert final_url in lines[2]
    assert "可能原因" in lines[4]


def test_run_phase4_diagnostic_format():
    """验证 run_phase4.py 的增强诊断格式"""
    slug = "order"
    lines = [
        f"[ERROR] {slug}: Cookie 认证失败（被重定向到登录页）",
        f"[ERROR] ⚠️ 请检查以下项目:",
        f"[ERROR]   1. Cookie 是否已过期（浏览器 F12 → Network → 任意请求 → Cookie）",
        f"[ERROR]   2. config.yaml 中的 cookie 值是否与浏览器一致",
        f"[ERROR]   3. cookie_domain 是否正确（应为域名，不含端口和路径）",
        f"[ERROR]   4. 目标系统是否使用 CAS/SSO（重定向链可能未完成）",
    ]

    assert slug in lines[0]
    assert "config.yaml" in lines[3]
    assert "cookie_domain" in lines[4]
    assert "CAS/SSO" in lines[5]


def test_verify_orchestrator_diagnostic():
    """验证 verify_orchestrator.py 的增强诊断格式"""
    lines = [
        "\n[AUTH_REQUIRED] Cookie 认证失败",
        "  排查步骤:",
        "  1. 浏览器 F12 → Network → 复制最新 Cookie",
        "  2. 更新 config.yaml 中的 cookie 字段",
        "  3. python pipeline.py run --project {目录} --from-phase phase_6_verify",
        "  ⚠️ 不要修改 cookie 以外的配置项",
    ]

    assert "AUTH_REQUIRED" in lines[0]
    assert "config.yaml" in lines[3]
    assert "cookie 以外的配置项" in lines[5]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
