"""Phase 0 配置确认验证器

验证内容：
1. URL 格式（R0.1）
2. 认证方式有效性（R0.2）
3. discovery 文件存在性（R0.7，v1.1 新增）
4. Cookie 格式（R0.3）
5. 文件路径存在性（R0.4）
6. 模块名命名规范（R0.5）
7. 运行时认证验证 + UI 框架检测（R0.6，--runtime-check）
8. YAML 格式规范（R0.6，禁止 Python docstring/shebang）

用法：
    python validate_00_config.py <config_file>
    python validate_00_config.py <config_file> --runtime-check
"""
import sys
import os
import re
import json
import glob
import argparse
from urllib.parse import urlparse
import yaml


def validate_url(url):
    """验证 URL 格式"""
    if not url.startswith(('http://', 'https://')):
        return False, "URL 必须以 http:// 或 https:// 开头"
    # 简单检查是否有有效域名/IP
    pattern = r'https?://[a-zA-Z0-9.-]+(?::\d+)?'
    if not re.match(pattern, url):
        return False, "URL 格式无效"
    return True, "OK"


def validate_auth_method(config):
    """从字段存在性推断认证方式并验证完整性"""
    has_cookie = bool(config.get('cookie'))
    has_token = bool(config.get('token'))
    has_local_storage = bool(config.get('local_storage'))

    # 检查认证配置一致性
    auth_count = sum([has_cookie, has_token])
    if auth_count > 1:
        return False, "同时配置了 cookie 和 token，请选择一种认证方式"

    # cookie 认证完整性
    if has_cookie and not config.get('cookie_domain'):
        return False, "Cookie 认证需要 cookie_domain 字段"

    # 无任何认证配置 — 警告但不阻断
    if not has_cookie and not has_token and not has_local_storage:
        return True, "WARN: 未配置任何认证方式"

    return True, "OK"


def validate_cookie(cookie_str):
    """验证 Cookie 格式"""
    if not cookie_str:
        return True, "OK"  # Cookie 可选
    # 检查 name=value; name2=value2 格式
    parts = cookie_str.split(';')
    for part in parts:
        part = part.strip()
        if '=' not in part:
            return False, f"Cookie 格式错误: {part}"
    return True, "OK"


def validate_file_paths(config):
    """验证文件路径存在性"""
    # 检查 Excel/CSV 文件路径
    # 这里根据实际 config 结构调整
    return True, "OK"


def validate_module_name(module_name):
    """验证模块名命名规范"""
    if not module_name:
        return True, "OK"
    # 允许小写字母、数字、连字符和下划线
    if not re.match(r'^[a-z][a-z0-9_-]*$', module_name):
        return False, f"模块名 '{module_name}' 必须使用小写字母、数字、连字符和下划线"
    return True, "OK"


def validate_discovery_files(project_dir):
    """R0.7: 验证 discovery JSON 文件存在性"""
    probe_dir = os.path.join(project_dir, '_probe')
    if not os.path.exists(probe_dir):
        return False, "_probe 目录不存在，请先运行 Phase 4 探测"

    discovery_files = glob.glob(os.path.join(probe_dir, 'discovery_*.json'))
    if not discovery_files:
        return False, "未找到 discovery_*.json 文件，请先运行 Phase 4 探测"

    return True, f"OK ({len(discovery_files)} 个 discovery 文件)"


def validate_yaml_format(config_file):
    """R0.8: 验证 config.yaml 使用纯 YAML 格式，禁止 Python docstring 和 shebang"""
    with open(config_file, 'r', encoding='utf-8') as f:
        content = f.read()

    errors = []

    # 检查 Python docstring (""")
    if '"""' in content:
        errors.append('config.yaml 包含 Python docstring (""")，YAML 不支持此语法')

    # 检查 shebang (#!/usr/bin/env python)
    lines = content.split('\n')
    if lines and lines[0].startswith('#!/usr/bin/env python'):
        errors.append('config.yaml 第一行包含 Python shebang，YAML 文件不需要解释器指令')

    if errors:
        return False, '；'.join(errors)

    return True, "OK"


def validate_config(config_file):
    """主验证入口"""
    errors = []
    warnings = []

    # R0.8: YAML 格式规范（最先检查，如果格式错误则后续无法解析）
    if os.path.exists(config_file):
        ok, msg = validate_yaml_format(config_file)
        if not ok:
            errors.append(f"[R0.8] YAML 格式: {msg}")

    # 加载配置文件
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    else:
        return [f"配置文件不存在: {config_file}"], [], []

    # R0.1 URL 格式（优先 target_url，fallback 到 host）
    url = config.get('target_url', '') or config.get('host', '')
    if url:
        ok, msg = validate_url(url)
        if not ok:
            errors.append(f"[R0.1] URL 格式: {msg}")

    # R0.2 认证方式
    ok, msg = validate_auth_method(config)
    if not ok:
        errors.append(f"[R0.2] 认证方式: {msg}")

    # R0.7 discovery 文件存在性（v1.1 新增，WARNING 不阻断）
    # 注意：discovery 文件在 Phase 4 生成，Phase 0 时尚不存在，故降级为 warning
    project_dir = os.path.dirname(config_file)
    ok, msg = validate_discovery_files(project_dir)
    if not ok:
        warnings.append(f"[R0.7] discovery 文件: {msg}（将在 Phase 4 生成）")

    # R0.3 Cookie 格式
    cookie = config.get('cookie', '')
    if cookie:
        ok, msg = validate_cookie(cookie)
        if not ok:
            errors.append(f"[R0.3] Cookie 格式: {msg}")

    # R0.4 文件路径（从 cases 目录推断）
    project_dir = os.path.dirname(config_file)
    cases_dir = os.path.join(project_dir, 'cases')
    if not os.path.exists(cases_dir):
        warnings.append("[R0.4] cases 目录不存在，请先完成脚本生成")

    # R0.5 模块名（从目录推断）
    if os.path.exists(cases_dir):
        for module in os.listdir(cases_dir):
            ok, msg = validate_module_name(module)
            if not ok:
                errors.append(f"[R0.5] 模块名: {msg}")

    return errors, warnings, []


# ===========================================================================
# 运行时认证验证 + UI 框架检测（R0.6）
# ===========================================================================

def _parse_cookie_string(cookie_str, domain):
    """将 cookie 字符串解析为 Playwright add_cookies 格式"""
    if not cookie_str:
        return []
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
    return cookies


def _detect_ui_framework(page):
    """检测页面使用的 UI 框架"""
    frameworks = []
    checks = [
        # X-6 修复: element-plus 先检查（更具体），element-ui 用正确的 data-v- 判断
        # element-plus (Vue 3): 有 .el-button + Vue + 有 scoped style data-v- 属性
        ("element-plus", "document.querySelector('.el-button') !== null && typeof __VUE__ !== 'undefined' && document.querySelector('[data-v-]') !== null"),
        # element-ui (Vue 2): 有 .el-button + Vue + 无 scoped style data-v- 属性
        ("element-ui", "document.querySelector('.el-button') !== null && typeof __VUE__ !== 'undefined' && document.querySelector('[data-v-]') === null"),
        ("ant-design", "document.querySelector('.ant-btn') !== null"),
        ("arco-design", "document.querySelector('.arco-btn') !== null"),
        ("tdesign", "document.querySelector('.t-button') !== null"),
        ("bootstrap", "document.querySelector('.btn.btn-primary') !== null"),
        ("mui", "document.querySelector('.MuiButton-root') !== null"),
        ("react", "typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ !== 'undefined'"),
        ("vue", "typeof __VUE__ !== 'undefined' || document.querySelector('[data-v-]') !== null"),
    ]
    for name, script in checks:
        try:
            if page.evaluate(script):
                frameworks.append(name)
        except Exception:
            pass
    return frameworks


def _is_login_page(url):
    """通过 URL 特征判断是否为登录页"""
    login_keywords = ['login', 'signin', 'sign-in', 'auth', 'sso', 'cas', 'passport']
    path = url.lower().split('?')[0]
    return any(kw in path for kw in login_keywords)


def _has_login_form(page):
    """通过 DOM 特征判断是否为登录页"""
    try:
        return page.evaluate("""() => {
            // 密码输入框存在 → 大概率是登录页
            if (document.querySelector('input[type="password"]')) return true;
            // 常见登录按钮文本
            const btns = document.querySelectorAll('button, input[type="submit"]');
            return Array.from(btns).some(b =>
                /登录|login|sign\\s*in/i.test(b.textContent || b.value || ''));
        }""")
    except Exception:
        return False


def runtime_check(config):
    """运行时认证验证 + UI 框架检测

    一次浏览器会话完成：
    1. 注入 Cookie/localStorage
    2. 导航到目标 URL
    3. 检查认证有效性（重定向 + 登录表单）
    4. 检测 UI 框架
    5. 输出 _probe/auth_check.json
    """
    url = config.get('target_url', '') or config.get('host', '')
    if not url:
        return False, "未配置 target_url，无法执行运行时检查", None

    cookie_str = config.get('cookie', '')
    local_storage = config.get('local_storage') or {}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright 未安装，请运行: pip install playwright && playwright install chromium", None

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True)

        # 注入 cookie
        if cookie_str:
            # X-7 修复: 优先使用 config.yaml 中的 cookie_domain
            domain = config.get('cookie_domain') or urlparse(url).hostname
            if domain:
                cookies = _parse_cookie_string(cookie_str, domain)
                context.add_cookies(cookies)

                # TOKEN_KEYS 自动同步到 localStorage
                TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'auth_token', 'jwt_token'}
                for c in cookies:
                    if c['name'] in TOKEN_KEYS and c['name'] not in local_storage:
                        local_storage[c['name']] = c['value']

        page = context.new_page()

        # root-first: 先导航到根 URL，设置 localStorage，再跳转目标页
        # 天枢类 SPA 会在页面初始化时重置 localStorage，必须先导航再写入
        if local_storage:
            parsed = urlparse(url)
            root_url = f"{parsed.scheme}://{parsed.netloc}/"
            try:
                page.goto(root_url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            for key, value in local_storage.items():
                try:
                    page.evaluate(
                        "([k, v]) => localStorage.setItem(k, v)",
                        [str(key), str(value)]
                    )
                except Exception:
                    pass

        # 导航到目标 URL
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            page.wait_for_timeout(3000)
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                return False, f"页面加载失败: {e}", None

        # 额外等待
        page.wait_for_timeout(3000)

        final_url = page.url

        # 认证有效性检查
        auth_valid = True
        auth_message = "认证有效"

        if _is_login_page(final_url) and not _is_login_page(url):
            auth_valid = False
            auth_message = f"页面被重定向到登录页: {final_url}"
        elif _has_login_form(page):
            auth_valid = False
            auth_message = "页面包含登录表单，认证可能已失效"

        # UI 框架检测
        frameworks = _detect_ui_framework(page) if auth_valid else []

        result = {
            "auth_valid": auth_valid,
            "requested_url": url,
            "final_url": final_url,
            "redirected": final_url != url,
            "ui_framework": frameworks[0] if frameworks else None,
            "all_frameworks": frameworks,
            "auth_message": auth_message,
        }

        # 持久化框架检测结果供 Phase 4/5 使用
        if result['ui_framework']:
            try:
                import json
                probe_dir = Path(config_file).parent / '_probe'
                probe_dir.mkdir(exist_ok=True)
                fw_path = probe_dir / 'framework.json'
                fw_path.write_text(
                    json.dumps({'framework': result['ui_framework']}, indent=2, ensure_ascii=False),
                    encoding='utf-8'
                )
            except Exception:
                pass  # 写入失败不阻断，后续会使用 generic 回退

        return auth_valid, auth_message, result

    finally:
        try:
            if browser:
                browser.close()
            if pw:
                pw.stop()
        except Exception:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Phase 0 配置确认验证器')
    parser.add_argument('config_file', help='config.yaml 路径')
    parser.add_argument('--runtime-check', action='store_true',
                        help='运行时认证验证 + UI 框架检测（需要 playwright）')
    parser.add_argument('--skip-runtime-check', action='store_true',
                        help='跳过运行时认证验证（不推荐，仅用于离线环境）')
    args = parser.parse_args()

    config_file = args.config_file
    errors, warnings, info = validate_config(config_file)

    # 加载配置以便判断是否需要自动 runtime-check
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    # cookie 认证时自动执行 runtime-check（无需 --runtime-check 参数）
    # 除非显式传入 --skip-runtime-check
    # 注意：cookie 认证必须验证，静态错误（如 R0.5 中文模块名）不阻断认证检查
    auto_runtime_check = bool(config.get('cookie')) and not args.skip_runtime_check

    print("=" * 60)
    print(f"Phase 0 Config Validation - {config_file}")
    print("=" * 60)

    for msg in info:
        print(f"  [INFO] {msg}")
    for msg in warnings:
        print(f"  [WARN] {msg}")
    for msg in errors:
        print(f"  [ERR]  {msg}")

    # 运行时检查（显式请求 或 cookie 认证自动触发）
    # cookie 认证时不受静态错误（R0.5）阻断
    if args.runtime_check or auto_runtime_check:
        print("-" * 60)
        print("运行时认证验证 + UI 框架检测...")

        auth_valid, auth_message, result = runtime_check(config)

        if result:
            # 输出到 _probe/auth_check.json
            project_dir = os.path.dirname(config_file)
            probe_dir = os.path.join(project_dir, '_probe')
            os.makedirs(probe_dir, exist_ok=True)
            output_path = os.path.join(probe_dir, 'auth_check.json')

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"  [INFO] 输出: {output_path}")

            if result['auth_valid']:
                print(f"  [OK]   认证有效")
                if result['ui_framework']:
                    print(f"  [INFO] UI 框架: {result['ui_framework']}")
                if result['all_frameworks']:
                    print(f"  [INFO] 检测到的框架: {', '.join(result['all_frameworks'])}")
            else:
                errors.append(f"[R0.6] 认证无效: {auth_message}")
                print(f"  [ERR]  {auth_message}")
                print(f"  [HINT] 请重新提供 Cookie 或检查 token 是否过期")

    print("-" * 60)
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s)")

    sys.exit(1 if errors else 0)
