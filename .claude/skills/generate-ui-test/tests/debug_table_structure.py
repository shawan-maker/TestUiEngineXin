"""诊断表格结构变化"""
import sys
from pathlib import Path
import yaml
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def load_config():
    with open('D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def run():
    config = load_config()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True)

        # Inject cookies
        cookie_str = config.get('cookie', '')
        if cookie_str:
            cookies = []
            for part in cookie_str.split(';'):
                part = part.strip()
                if '=' in part:
                    name, value = part.split('=', 1)
                    cookies.append({
                        'name': name,
                        'value': value,
                        'domain': '.cmecloud.cn',
                        'path': '/'
                    })
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto('http://console-estack-intel.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm', wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)

        print(f"URL: {page.url}")

        # Check all possible table selectors
        result = page.evaluate("""
        (() => {
            const info = {};

            // 1. Check all tables
            info.tables = document.querySelectorAll('table').length;

            // 2. Check el-table components
            info.elTables = document.querySelectorAll('.el-table').length;

            // 3. Check tbody
            info.tbodies = document.querySelectorAll('tbody').length;

            // 4. Check tr
            info.trs = document.querySelectorAll('tr').length;

            // 5. Check el-table__body-wrapper
            info.bodyWrappers = document.querySelectorAll('.el-table__body-wrapper').length;

            // 6. Check el-table__fixed-right
            info.fixedRights = document.querySelectorAll('.el-table__fixed-right').length;

            // 7. Check dropdown-more
            info.dropdownMores = document.querySelectorAll('.dropdown-more').length;

            // 8. Get all el-table__body-wrapper details
            const wrappers = document.querySelectorAll('.el-table__body-wrapper');
            info.wrapperDetails = Array.from(wrappers).map((w, i) => {
                const rows = w.querySelectorAll('tr');
                let ancestorHidden = false;
                let p = w;
                let hiddenReason = '';
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className?.baseVal || '');
                    if (cn.includes('is-hidden')) {
                        ancestorHidden = true;
                        hiddenReason = 'is-hidden class at ' + p.tagName;
                        break;
                    }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none') {
                        ancestorHidden = true;
                        hiddenReason = 'display:none at ' + p.tagName;
                        break;
                    }
                    if (st.visibility === 'hidden') {
                        ancestorHidden = true;
                        hiddenReason = 'visibility:hidden at ' + p.tagName;
                        break;
                    }
                    p = p.parentElement;
                }
                return {
                    index: i,
                    rowCount: rows.length,
                    ancestorHidden,
                    hiddenReason,
                    rect: w.getBoundingClientRect()
                };
            });

            // 9. Get all el-table__fixed-right details
            const fixeds = document.querySelectorAll('.el-table__fixed-right');
            info.fixedDetails = Array.from(fixeds).map((f, i) => {
                const rows = f.querySelectorAll('tbody tr');
                let ancestorHidden = false;
                let p = f;
                let hiddenReason = '';
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className?.baseVal || '');
                    if (cn.includes('is-hidden')) {
                        ancestorHidden = true;
                        hiddenReason = 'is-hidden class at ' + p.tagName;
                        break;
                    }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none') {
                        ancestorHidden = true;
                        hiddenReason = 'display:none at ' + p.tagName;
                        break;
                    }
                    if (st.visibility === 'hidden') {
                        ancestorHidden = true;
                        hiddenReason = 'visibility:hidden at ' + p.tagName;
                        break;
                    }
                    p = p.parentElement;
                }
                return {
                    index: i,
                    rowCount: rows.length,
                    ancestorHidden,
                    hiddenReason,
                    rect: f.getBoundingClientRect()
                };
            });

            // 10. Check if page has error or loading state
            info.hasError = document.querySelector('.el-message--error') !== null;
            info.hasLoading = document.querySelector('.el-loading-mask') !== null;

            // 11. Get page title
            info.title = document.title;

            return info;
        })()
        """)

        print("\n=== 表格结构诊断 ===")
        print(f"Tables: {result['tables']}")
        print(f"El-Tables: {result['elTables']}")
        print(f"Tbodies: {result['tbodies']}")
        print(f"TRs: {result['trs']}")
        print(f"Body Wrappers: {result['bodyWrappers']}")
        print(f"Fixed Rights: {result['fixedRights']}")
        print(f"Dropdown-mores: {result['dropdownMores']}")
        print(f"Has Error: {result['hasError']}")
        print(f"Has Loading: {result['hasLoading']}")
        print(f"Title: {result['title']}")

        print("\n=== Body Wrapper Details ===")
        for w in result['wrapperDetails']:
            vis = "HIDDEN" if w['ancestorHidden'] else "VISIBLE"
            print(f"  [{w['index']}] rows={w['rowCount']} {vis} {w.get('hiddenReason', '')} rect={w['rect']}")

        print("\n=== Fixed-Right Details ===")
        for f in result['fixedDetails']:
            vis = "HIDDEN" if f['ancestorHidden'] else "VISIBLE"
            print(f"  [{f['index']}] rows={f['rowCount']} {vis} {f.get('hiddenReason', '')} rect={f['rect']}")

        browser.close()

if __name__ == '__main__':
    run()
