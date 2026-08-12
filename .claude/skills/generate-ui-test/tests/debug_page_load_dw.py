"""检查新环境页面加载状态"""
import sys
import yaml
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))

def run():
    with open('examples/ecsCloud2/config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    cookie = config.get('cookie', '')
    url = 'https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm'

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # Inject cookie
        cookie_parts = cookie.split(';')
        cookies = []
        for part in cookie_parts:
            part = part.strip()
            if '=' in part:
                name, value = part.split('=', 1)
                cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': 'console-estack.dw.cmecloud.cn',
                    'path': '/'
                })

        context.add_cookies(cookies)
        print(f"Injected {len(cookies)} cookies")

        # Navigate
        print(f"Navigating to {url}...")
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            print(f"Final URL: {page.url}")
        except Exception as e:
            print(f"Navigation error: {e}")
            print(f"Current URL: {page.url}")

        # Wait for potential SPA loading
        page.wait_for_timeout(5000)

        # Check page state
        title = page.title()
        print(f"Page title: {title}")

        # Check if redirected to login
        if 'login' in page.url.lower():
            print("❌ Redirected to login page - cookie expired or invalid")
            browser.close()
            return

        # Check DOM state
        has_table = page.evaluate("""() => {
            return {
                hasTable: !!document.querySelector('.el-table'),
                hasFixedRight: !!document.querySelector('.el-table__fixed-right'),
                tbodyCount: document.querySelectorAll('tbody').length,
                trCount: document.querySelectorAll('tr').length,
                fixedRows: document.querySelectorAll('.el-table__fixed-right tbody tr').length,
                mainRows: document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr').length,
                url: window.location.href
            }
        }""")

        print("\nDOM State:")
        print(f"  URL: {has_table['url']}")
        print(f"  hasTable: {has_table['hasTable']}")
        print(f"  hasFixedRight: {has_table['hasFixedRight']}")
        print(f"  tbodyCount: {has_table['tbodyCount']}")
        print(f"  trCount: {has_table['trCount']}")
        print(f"  fixedRows: {has_table['fixedRows']}")
        print(f"  mainRows: {has_table['mainRows']}")

        # Take screenshot
        page.screenshot(path='tests/debug_page_state_dw.png', full_page=True)
        print("\nScreenshot saved to tests/debug_page_state_dw.png")

        browser.close()

if __name__ == '__main__':
    run()
