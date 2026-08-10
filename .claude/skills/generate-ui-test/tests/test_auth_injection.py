"""
测试认证注入点兼容性 — 天枢 vs EcsCloud

覆盖管线中 4 个独立认证注入点，验证每种注入方式在两种系统下是否认证成功。

注入点：
  1. Phase 4 discover_page.py       — root-first 模式（已修复）
  2. Phase 6 verify_orchestrator.py  — init_script 模式（待修复）
  3. Phase 6 detail_links.py         — init_script 模式（待修复）
  4. Runtime auth_keywords.py.tpl    — evaluate-only 模式（待修复）

用法：
  python test_auth_injection.py                  # 运行全部测试
  python test_auth_injection.py --project tianshu  # 仅测天枢
  python test_auth_injection.py --project ecscloud # 仅测 EcsCloud
  python test_auth_injection.py --headed          # 有头模式调试
"""

import argparse
import json
import os
import sys
import time
from urllib.parse import urlparse

# ============================================================
# 项目配置
# ============================================================

PROJECTS = {
    "tianshu": {
        "name": "天枢 (TSManager2)",
        "config_path": "D:/PyProject/TestUiEngineXin/examples/TSManager2/config.yaml",
        "target_url": "http://100.71.19.25:30101",
        "test_url": "http://100.71.19.25:30101/#/question-manage/deliveryIssues-list",
        "needs_localstorage": True,
    },
    "ecscloud": {
        "name": "EcsCloud (ecsCloud2)",
        "config_path": "D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml",
        "target_url": "http://console-estack-intel.cmecloud.cn/",
        "test_url": "http://console-estack-intel.cmecloud.cn/estack/web/ecm-compute-static/vm/list",
        "needs_localstorage": False,
    },
}


def load_config(config_path):
    """加载 config.yaml 并提取认证信息"""
    import yaml
    config_path = os.path.normpath(config_path)
    if not os.path.isfile(config_path):
        print(f"[SKIP] config.yaml 不存在: {config_path}")
        return None
    with open(config_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def parse_cookie(cookie_str, domain):
    """解析 cookie 字符串为列表"""
    if not cookie_str:
        return []
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name, value = name.strip(), value.strip()
        if name:
            cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
    return cookies


TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'accessToken', 'auth_token', 'jwt_token'}


def build_local_storage(cfg, cookies):
    """从 config 构建 localStorage 字典（模拟管线逻辑）"""
    local_storage = {}
    # 1. config.yaml local_storage
    if isinstance(cfg.get('local_storage'), dict):
        for k, v in cfg['local_storage'].items():
            local_storage[str(k)] = str(v)
    # 2. Cookie token keys
    for c in cookies:
        if c['name'] in TOKEN_KEYS:
            local_storage[c['name']] = c['value']
    return local_storage


def check_auth(page, label):
    """检查认证是否成功，返回 (bool, str)"""
    url = page.url
    is_login = '/login' in url or url.rstrip('/').endswith('login')

    # 检查 localStorage
    try:
        ls_keys = page.evaluate("() => Object.keys(localStorage)")
    except Exception:
        ls_keys = []

    # 检查页面是否有实际内容
    try:
        has_content = page.evaluate("""() => {
            const body = document.body;
            if (!body) return false;
            // 检查是否有表格行、卡片、或任何有意义的 DOM 元素
            const rows = document.querySelectorAll('table tbody tr, .el-card, .el-table__row');
            const forms = document.querySelectorAll('input, .el-input, .el-form-item');
            return rows.length > 0 || forms.length > 3;
        }""")
    except Exception:
        has_content = False

    if is_login:
        return False, f"[FAIL] {label}: redirected to login ({url})"
    elif has_content:
        return True, f"[PASS] {label}: auth OK (localStorage={len(ls_keys)} keys, page has content)"
    else:
        return True, f"[WARN] {label}: no login redirect but page sparse (localStorage={len(ls_keys)} keys)"


# ============================================================
# 注入点 1: Phase 4 discover_page.py — root-first 模式（已修复）
# ============================================================

def test_injection_point_1(pw, project_key, cfg, headed):
    """
    Phase 4 discover_page.py — root-first 模式

    模拟 discover() 函数中的认证注入逻辑：
    1. context.add_cookies(cookies)
    2. page.goto(root_url)
    3. page.evaluate(localStorage.setItem for each)
    4. page.goto(target_url)
    """
    proj = PROJECTS[project_key]
    label = f"注入点1-Phase4-root-first [{proj['name']}]"
    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"{'='*60}")

    domain = urlparse(proj['target_url']).hostname
    cookie_str = cfg.get('cookie', '')
    cookies = parse_cookie(cookie_str, domain)
    local_storage = build_local_storage(cfg, cookies)
    test_url = proj['test_url']

    browser = pw.chromium.launch(headless=not headed)
    try:
        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)
        page = context.new_page()

        # root-first 模式
        if local_storage:
            parsed = urlparse(test_url)
            root_url = f"{parsed.scheme}://{parsed.netloc}/"
            print(f"  [1] 导航到根 URL: {root_url}")
            try:
                page.goto(root_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"  [WARN] 根 URL 导航异常: {e}")
            # 等待 SPA 初始化完成（关键！）
            page.wait_for_timeout(2000)

            print(f"  [2] 设置 {len(local_storage)} 个 localStorage keys")
            page.evaluate("""(items) => {
                for (let i = 0; i < items.length; i += 2) {
                    localStorage.setItem(items[i], items[i+1]);
                }
            }""", [k for kv in local_storage.items() for k in kv])

        print(f"  [3] 导航到目标 URL: {test_url}")
        page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        success, msg = check_auth(page, label)
        print(f"  {msg}")
        return success, msg
    finally:
        browser.close()


# ============================================================
# 注入点 2: Phase 6 verify_orchestrator.py — init_script 模式（待修复）
# ============================================================

def test_injection_point_2(pw, project_key, cfg, headed):
    """
    Phase 6 verify_orchestrator.py — init_script 模式

    模拟 verify_project() 函数中的认证注入逻辑：
    1. context.add_cookies(cookies)
    2. page.add_init_script(localStorage.setItem for each)
    3. page.goto(target_url)
    """
    proj = PROJECTS[project_key]
    label = f"注入点2-Phase6主验证-init_script [{proj['name']}]"
    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"{'='*60}")

    domain = urlparse(proj['target_url']).hostname
    cookie_str = cfg.get('cookie', '')
    cookies = parse_cookie(cookie_str, domain)
    local_storage = build_local_storage(cfg, cookies)
    test_url = proj['test_url']

    browser = pw.chromium.launch(headless=not headed)
    try:
        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)
        page = context.new_page()

        # init_script 模式（当前 verify_orchestrator.py 的方式）
        if local_storage:
            ls_items = ', '.join(
                f'localStorage.setItem({json.dumps(k)}, {json.dumps(v)})'
                for k, v in local_storage.items()
            )
            print(f"  [1] add_init_script: {len(local_storage)} 个 keys")
            page.add_init_script(f'() => {{ {ls_items} }}')

        print(f"  [2] 直接导航到目标 URL: {test_url}")
        page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        # Belt-and-suspenders（verify_orchestrator.py 的补救逻辑）
        if local_storage:
            for k, v in local_storage.items():
                page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        success, msg = check_auth(page, label)
        print(f"  {msg}")

        # 额外诊断：检查 localStorage 是否被清空
        if not success and local_storage:
            ls_after = page.evaluate("() => Object.keys(localStorage)")
            print(f"  [DIAG] localStorage keys: before={list(local_storage.keys())}, after={ls_after}")

        return success, msg
    finally:
        browser.close()


# ============================================================
# 注入点 3: Phase 6 detail_links.py — init_script 模式（待修复）
# ============================================================

def test_injection_point_3(pw, project_key, cfg, headed):
    """
    Phase 6 detail_links.py — init_script 模式

    模拟 _try_kb_resolve_detail_links() 函数中的认证注入逻辑：
    与注入点 2 相同，但用于 KB 回退探测场景
    """
    proj = PROJECTS[project_key]
    label = f"注入点3-Phase6-KB探测-init_script [{proj['name']}]"
    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"{'='*60}")

    domain = urlparse(proj['target_url']).hostname
    cookie_str = cfg.get('cookie', '')
    cookies = parse_cookie(cookie_str, domain)
    local_storage = build_local_storage(cfg, cookies)
    test_url = proj['test_url']

    browser = pw.chromium.launch(headless=not headed)
    try:
        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)
        page = context.new_page()

        # init_script 模式（当前 detail_links.py 的方式）
        if local_storage:
            ls_items = ', '.join(
                f'localStorage.setItem({json.dumps(k)}, {json.dumps(v)})'
                for k, v in local_storage.items()
            )
            print(f"  [1] add_init_script: {len(local_storage)} 个 keys")
            page.add_init_script(f'() => {{ {ls_items} }}')

        print(f"  [2] 直接导航到目标 URL: {test_url}")
        page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Belt-and-supertures（detail_links.py 的补救逻辑）
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        success, msg = check_auth(page, label)
        print(f"  {msg}")
        return success, msg
    finally:
        browser.close()


# ============================================================
# 注入点 4: Runtime auth_keywords.py.tpl — evaluate-only 模式（待修复）
# ============================================================

def test_injection_point_4(pw, project_key, cfg, headed):
    """
    Runtime auth_keywords.py.tpl — evaluate-only 模式

    模拟 inject_local_storage() 关键字中的认证注入逻辑：
    1. context.add_cookies(cookies)  [HTTP Cookie 安全网]
    2. page.evaluate(localStorage.setItem for each)  [批量写入]

    注意：运行时场景下页面已经通过 open_url 导航过了，
    所以这里模拟 suite setup_step 的流程
    """
    proj = PROJECTS[project_key]
    label = f"注入点4-运行时-auth_keywords [{proj['name']}]"
    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"{'='*60}")

    domain = urlparse(proj['target_url']).hostname
    cookie_str = cfg.get('cookie', '')
    cookies = parse_cookie(cookie_str, domain)
    local_storage = build_local_storage(cfg, cookies)
    test_url = proj['test_url']

    browser = pw.chromium.launch(headless=not headed)
    try:
        context = browser.new_context(no_viewport=True)

        # 模拟 base_browser._apply_config_cookies()
        if cookies:
            context.add_cookies(cookies)
            print(f"  [0] context.add_cookies: {len(cookies)} 个 cookies")

        page = context.new_page()

        # 模拟 open_url 关键字先导航到目标页面
        print(f"  [1] 模拟 open_url 导航: {test_url}")
        try:
            page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"  [WARN] open_url 导航异常: {e}")
        page.wait_for_timeout(2000)

        # 模拟 inject_local_storage 关键字（当前 auth_keywords.py.tpl 的方式）
        storage_items = dict(cfg.get('local_storage', {}))

        # 自动从 cookie 提取第一个 token 并合并
        if cookie_str:
            for part in cookie_str.split(';'):
                part = part.strip()
                if '=' in part:
                    ck, cv = part.split('=', 1)
                    ck = ck.strip()
                    if 'token' in ck.lower():
                        storage_items.setdefault(ck, cv)
                        break

        if storage_items:
            print(f"  [2] page.evaluate 批量写入 {len(storage_items)} 个 localStorage keys")
            js_items = ', '.join([f"'{k}', '{v}'" for k, v in storage_items.items()])
            js_script = (
                f"var items=[{js_items}]; "
                f"for(var i=0;i<items.length;i+=2)"
                f"{{ localStorage.setItem(items[i], items[i+1]); }}"
            )
            page.evaluate(js_script)

        # 检查认证
        success, msg = check_auth(page, label)
        print(f"  {msg}")

        # 额外：检查 reload 后 localStorage 是否存活
        if local_storage and not success:
            print(f"  [DIAG] 尝试 reload 后重新检查...")
            page.reload(wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            success2, msg2 = check_auth(page, f"{label} (reload后)")
            print(f"  {msg2}")

        return success, msg
    finally:
        browser.close()


# ============================================================
# 统一方案验证：root-first 模式替代 init_script
# ============================================================

def test_unified_root_first(pw, project_key, cfg, headed):
    """
    统一方案验证 — root-first 模式替代所有 init_script

    模拟修复后的 verify_orchestrator.py / detail_links.py 行为
    """
    proj = PROJECTS[project_key]
    label = f"统一方案-root-first替代 [{proj['name']}]"
    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"{'='*60}")

    domain = urlparse(proj['target_url']).hostname
    cookie_str = cfg.get('cookie', '')
    cookies = parse_cookie(cookie_str, domain)
    local_storage = build_local_storage(cfg, cookies)
    test_url = proj['test_url']

    browser = pw.chromium.launch(headless=not headed)
    try:
        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)
        page = context.new_page()

        # 统一 root-first 模式
        if local_storage:
            parsed = urlparse(test_url)
            root_url = f"{parsed.scheme}://{parsed.netloc}/"
            print(f"  [1] 导航到根 URL: {root_url}")
            try:
                page.goto(root_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"  [WARN] 根 URL 导航异常: {e}")

            print(f"  [2] 设置 {len(local_storage)} 个 localStorage keys")
            page.evaluate("""(items) => {
                for (let i = 0; i < items.length; i += 2) {
                    localStorage.setItem(items[i], items[i+1]);
                }
            }""", [k for kv in local_storage.items() for k in kv])

        print(f"  [3] 导航到目标 URL: {test_url}")
        page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        success, msg = check_auth(page, label)
        print(f"  {msg}")
        return success, msg
    finally:
        browser.close()


# ============================================================
# 运行时统一方案验证
# ============================================================

def test_unified_runtime(pw, project_key, cfg, headed):
    """
    运行时统一方案验证 — inject_local_storage 增加 root-first

    模拟修复后的 auth_keywords.py.tpl 行为
    """
    proj = PROJECTS[project_key]
    label = f"运行时统一方案 [{proj['name']}]"
    print(f"\n{'='*60}")
    print(f"[TEST] {label}")
    print(f"{'='*60}")

    domain = urlparse(proj['target_url']).hostname
    cookie_str = cfg.get('cookie', '')
    cookies = parse_cookie(cookie_str, domain)
    test_url = proj['test_url']

    browser = pw.chromium.launch(headless=not headed)
    try:
        context = browser.new_context(no_viewport=True)
        if cookies:
            context.add_cookies(cookies)
        page = context.new_page()

        # 模拟 open_url 先导航
        print(f"  [1] 模拟 open_url 导航: {test_url}")
        try:
            page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # 模拟修复后的 inject_local_storage
        storage_items = dict(cfg.get('local_storage', {}))
        if cookie_str:
            for part in cookie_str.split(';'):
                part = part.strip()
                if '=' in part:
                    ck, cv = part.split('=', 1)
                    ck = ck.strip()
                    if 'token' in ck.lower():
                        storage_items.setdefault(ck, cv)
                        break

        if not storage_items:
            print(f"  [SKIP] 无 local_storage 配置（cookie-only 项目无需注入）")
            success, msg = check_auth(page, label)
            print(f"  {msg}")
            return success, msg

        # 修复方案：先导航到根 URL
        target_url = cfg.get('target_url', '')
        if target_url:
            parsed = urlparse(target_url)
            root_url = f"{parsed.scheme}://{parsed.netloc}/"
            print(f"  [2] 导航到根 URL: {root_url}")
            try:
                page.goto(root_url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass

        # 批量写入
        print(f"  [3] 写入 {len(storage_items)} 个 localStorage keys")
        js_items = ', '.join([f"'{k}', '{v}'" for k, v in storage_items.items()])
        js_script = (
            f"var items=[{js_items}]; "
            f"for(var i=0;i<items.length;i+=2)"
            f"{{ localStorage.setItem(items[i], items[i+1]); }}"
        )
        page.evaluate(js_script)

        # 修复方案：reload 让 SPA 重新读取 localStorage
        print(f"  [4] reload 页面")
        page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        success, msg = check_auth(page, label)
        print(f"  {msg}")
        return success, msg
    finally:
        browser.close()


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="测试认证注入点兼容性")
    parser.add_argument('--project', choices=['tianshu', 'ecscloud', 'all'],
                        default='all', help='测试项目 (默认 all)')
    parser.add_argument('--headed', action='store_true', help='有头模式调试')
    parser.add_argument('--injection-point', type=int, choices=[1, 2, 3, 4, 5, 6],
                        help='仅测试指定注入点 (1-4=现有, 5=统一方案, 6=运行时统一)')
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    projects = []
    if args.project == 'all':
        projects = ['tianshu', 'ecscloud']
    else:
        projects = [args.project]

    # 加载配置
    configs = {}
    for pk in projects:
        cfg = load_config(PROJECTS[pk]['config_path'])
        if cfg is None:
            print(f"[ERROR] 无法加载 {pk} 的 config.yaml")
            continue
        configs[pk] = cfg

    if not configs:
        print("[ERROR] 没有可用的项目配置")
        sys.exit(1)

    # 定义测试矩阵
    injection_points = {
        1: ("Phase 4 discover_page.py (root-first)", test_injection_point_1),
        2: ("Phase 6 verify_orchestrator.py (init_script)", test_injection_point_2),
        3: ("Phase 6 detail_links.py (init_script)", test_injection_point_3),
        4: ("Runtime auth_keywords.py.tpl (evaluate-only)", test_injection_point_4),
        5: ("统一方案: root-first 替代 init_script", test_unified_root_first),
        6: ("运行时统一方案: root-first + reload", test_unified_runtime),
    }

    if args.injection_point:
        test_points = {args.injection_point: injection_points[args.injection_point]}
    else:
        test_points = injection_points

    # 运行测试
    pw = sync_playwright().start()
    results = []

    try:
        for ip_id, (ip_name, ip_func) in test_points.items():
            for pk in projects:
                cfg = configs[pk]
                try:
                    success, msg = ip_func(pw, pk, cfg, args.headed)
                    results.append({
                        'injection_point': ip_id,
                        'injection_point_name': ip_name,
                        'project': pk,
                        'project_name': PROJECTS[pk]['name'],
                        'success': success,
                        'message': msg,
                    })
                except Exception as e:
                    results.append({
                        'injection_point': ip_id,
                        'injection_point_name': ip_name,
                        'project': pk,
                        'project_name': PROJECTS[pk]['name'],
                        'success': False,
                        'message': f"❌ 异常: {e}",
                    })
    finally:
        pw.stop()

    # 输出汇总报告
    print(f"\n\n{'='*70}")
    print(f"认证注入点兼容性测试报告")
    print(f"{'='*70}")
    print(f"{'注入点':<45} {'项目':<15} {'结果':<6}")
    print(f"{'-'*45} {'-'*15} {'-'*6}")

    pass_count = 0
    fail_count = 0
    for r in results:
        status = "PASS" if r['success'] else "FAIL"
        if r['success']:
            pass_count += 1
        else:
            fail_count += 1
        print(f"{r['injection_point_name']:<45} {r['project_name']:<15} {status}")

    print(f"\n{'='*70}")
    print(f"总计: {pass_count} 通过, {fail_count} 失败 / {len(results)} 个测试")

    if fail_count > 0:
        print(f"\n失败的测试（需要修复）:")
        for r in results:
            if not r['success']:
                print(f"  - 注入点{r['injection_point']}: {r['injection_point_name']} [{r['project_name']}]")
                print(f"    {r['message']}")

    print(f"{'='*70}")

    sys.exit(0 if fail_count == 0 else 1)


if __name__ == '__main__':
    main()
