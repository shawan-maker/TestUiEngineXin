"""验证 detect_visible_containers 的修复方案"""
import sys
sys.path.insert(0, r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools')

from playwright.sync_api import sync_playwright

def test_wrapper_detection():
    url = "http://10.151.37.249/estack/web/ecm-compute-static/vm/list?productType=vm"
    cookie = "estack_lang=zh-CN; accessToken=69425564-1f76-41fc-8628-3cc1cd42041f; sajssdk_2015_cross_new_user=1; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%7D; __upayegisid=69b36a24-4001-4d63-96de-40afa083657f46"

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080}, ignore_https_errors=True)

    # 设置 cookie
    from urllib.parse import urlparse
    domain = urlparse(url).hostname
    cookies = []
    for item in cookie.split(';'):
        item = item.strip()
        if '=' in item:
            k, v = item.split('=', 1)
            cookies.append({'name': k.strip(), 'value': v.strip(), 'domain': domain, 'path': '/'})
    context.add_cookies(cookies)

    page = context.new_page()

    # 注入 localStorage
    page.goto("http://10.151.37.249/", wait_until='domcontentloaded', timeout=10000)
    page.evaluate("() => { localStorage.setItem('accessToken', '69425564-1f76-41fc-8628-3cc1cd42041f'); }")

    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(5000)

    print("=" * 80)
    print("Test: 检测 wrapper 而非 dialog")
    print("=" * 80)

    # 原始方法：检测 .el-dialog
    original = page.evaluate("""
        (() => {
            const visible = [];
            const dialogs = document.querySelectorAll('.el-dialog');
            for (const dialog of dialogs) {
                const rect = dialog.getBoundingClientRect();
                const style = window.getComputedStyle(dialog);
                if (rect.width > 0 && rect.height > 0 &&
                    style.display !== 'none' && style.visibility !== 'hidden') {
                    visible.push('dialog');
                    break;
                }
            }
            return visible;
        })()
    """)
    print(f"原始方法 (检测 .el-dialog): {original}")

    # 修复方法：检测 .el-dialog__wrapper
    fixed = page.evaluate("""
        (() => {
            const visible = [];
            const wrappers = document.querySelectorAll('.el-dialog__wrapper');
            for (const wrapper of wrappers) {
                const style = window.getComputedStyle(wrapper);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    visible.push('dialog');
                    break;
                }
            }
            return visible;
        })()
    """)
    print(f"修复方法 (检测 .el-dialog__wrapper): {fixed}")

    # 详细对比
    details = page.evaluate("""
        (() => {
            const results = { dialogs: [], wrappers: [] };

            const dialogs = document.querySelectorAll('.el-dialog');
            for (const dialog of dialogs) {
                const rect = dialog.getBoundingClientRect();
                const style = window.getComputedStyle(dialog);
                results.dialogs.push({
                    rect: { width: rect.width, height: rect.height },
                    display: style.display,
                    visibility: style.visibility
                });
            }

            const wrappers = document.querySelectorAll('.el-dialog__wrapper');
            for (const wrapper of wrappers) {
                const style = window.getComputedStyle(wrapper);
                results.wrappers.push({
                    display: style.display,
                    visibility: style.visibility
                });
            }

            return results;
        })()
    """)
    print(f"\n详细对比:")
    print(f"  .el-dialog: {details['dialogs']}")
    print(f"  .el-dialog__wrapper: {details['wrappers']}")

    browser.close()
    pw.stop()

if __name__ == '__main__':
    test_wrapper_detection()
