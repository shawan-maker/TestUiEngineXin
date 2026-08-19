"""验证"更改安全组"点击后的容器类型 — 修复版"""
import sys
import json as _json
import io
sys.path.insert(0, r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright

COOKIE = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; accessToken=7818c272-7932-4517-bfc7-8218c6c43e79; JSESSIONID=9B8492CFC6668BFF87733AA9051E3DC4; estack_lang=zh-CN"
TARGET_URL = "http://10.151.37.249/estack/web/ecm-compute-static/vm/list?productType=vm"

def run():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
    context = browser.new_context(viewport={'width': 1920, 'height': 1080}, ignore_https_errors=True)

    from urllib.parse import urlparse
    domain = urlparse(TARGET_URL).hostname
    cookies = []
    for item in COOKIE.split(';'):
        item = item.strip()
        if '=' in item:
            k, v = item.split('=', 1)
            cookies.append({'name': k.strip(), 'value': v.strip(), 'domain': domain, 'path': '/'})
    context.add_cookies(cookies)

    page = context.new_page()

    # Navigate to root, inject localStorage
    print("[1] Navigate and authenticate...")
    page.goto("http://10.151.37.249/", wait_until='domcontentloaded', timeout=15000)
    page.evaluate("() => { localStorage.setItem('accessToken', '7818c272-7932-4517-bfc7-8218c6c43e79'); }")
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(5000)
    print(f"    URL: {page.url}")

    if '/login' in page.url or 'no_permission' in page.url:
        print("[ERROR] Auth failed")
        browser.close(); pw.stop(); return

    # Hover first row
    print("[2] Hover first table row...")
    page.evaluate("""(() => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const mainRows = document.querySelectorAll('.el-table__body-wrapper tbody tr');
        if (mainRows.length > 0) {
            mainRows[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            mainRows[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        }
        if (fixedRows.length > 0) {
            fixedRows[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            fixedRows[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        }
    })()""")
    page.wait_for_timeout(500)

    # Click "更多" dropdown link
    print("[3] Click '更多' dropdown link...")
    more_result = page.evaluate("""(() => {
        const triggers = document.querySelectorAll('.el-dropdown-link');
        for (const t of triggers) {
            const text = (t.textContent || '').trim();
            const rect = t.getBoundingClientRect();
            if (text === '更多' && rect.width > 0 && rect.height > 0) {
                t.click();
                return { clicked: true, text };
            }
        }
        return { clicked: false, count: triggers.length };
    })()""")
    print(f"    {more_result}")
    page.wait_for_timeout(1000)

    # Check what dropdown appeared
    print("[4] Check visible dropdown/popover content...")
    dropdown_info = page.evaluate("""(() => {
        // Find all visible popovers with x-placement
        const popovers = document.querySelectorAll('div[x-placement]');
        const visible = [];
        for (const p of popovers) {
            const rect = p.getBoundingClientRect();
            const style = window.getComputedStyle(p);
            if (style.display === 'none' || rect.width <= 0) continue;

            // Get all text items inside
            const items = [];
            p.querySelectorAll('li, .el-dropdown-menu__item, .clickClass, div[style*="cursor"]').forEach(el => {
                const t = (el.textContent || '').trim();
                if (t && t.length < 50) items.push(t);
            });
            visible.push({
                tag: p.tagName,
                class: p.className.slice(0, 80),
                placement: p.getAttribute('x-placement'),
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                itemCount: items.length,
                items: items.slice(0, 30)
            });
        }
        return visible;
    })()""")
    print(f"    Found {len(dropdown_info)} visible dropdowns:")
    for d in dropdown_info:
        print(f"      placement={d['placement']}, items={d['itemCount']}: {d['items'][:10]}")

    # Find and click "更改安全组" in dropdown
    print("[5] Click '更改安全组'...")
    sg_result = page.evaluate("""(() => {
        // Search in all visible popovers and dropdown menus
        const allItems = document.querySelectorAll(
            'div[x-placement] li, div[x-placement] .clickClass, ' +
            '.el-dropdown-menu li, .el-dropdown-menu__item, ' +
            '.el-popover li, .el-popover .clickClass'
        );
        for (const item of allItems) {
            const text = (item.textContent || '').trim();
            if (text === '更改安全组') {
                const rect = item.getBoundingClientRect();
                const style = window.getComputedStyle(item);
                const info = {
                    text, tag: item.tagName,
                    class: (typeof item.className === 'string') ? item.className.slice(0, 80) : '',
                    rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                    display: style.display,
                    visibility: style.visibility
                };
                if (rect.width > 0 && rect.height > 0) {
                    item.click();
                    return { clicked: true, info };
                }
                return { clicked: false, reason: 'not visible', info };
            }
        }
        return { clicked: false, reason: 'not found', searchedCount: allItems.length };
    })()""")
    print(f"    {_json.dumps(sg_result, ensure_ascii=False, indent=4)}")

    if not sg_result.get('clicked'):
        # Try broader search
        print("[5b] Broader search for '更改安全组'...")
        broad = page.evaluate("""(() => {
            // Search ALL elements with this text
            const xpath = "//*[contains(text(),'更改安全组')]";
            const results = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            const found = [];
            for (let i = 0; i < results.snapshotLength; i++) {
                const el = results.snapshotItem(i);
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                // Find parent chain
                let parents = [];
                let p = el.parentElement;
                for (let j = 0; j < 5 && p; j++) {
                    parents.push({
                        tag: p.tagName,
                        class: (typeof p.className === 'string') ? p.className.slice(0, 50) : '',
                        xPlacement: p.getAttribute('x-placement') || ''
                    });
                    p = p.parentElement;
                }
                found.push({
                    text: (el.textContent || '').trim().slice(0, 30),
                    tag: el.tagName,
                    class: (typeof el.className === 'string') ? el.className.slice(0, 60) : '',
                    rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                    display: style.display,
                    parents: parents
                });
            }
            return found;
        })()""")
        print(f"    Found {len(broad)} elements:")
        for f in broad:
            print(f"      tag={f['tag']}, class={f['class']}, rect={f['rect']}, parents={f['parents'][:3]}")

        # If found a visible one, click it
        for f in broad:
            if f['rect']['w'] > 0 and f['rect']['h'] > 0 and f['text'] == '更改安全组':
                print(f"    -> Clicking visible element...")
                page.evaluate(f"""(() => {{
                    const xpath = "//*[text()='更改安全组']";
                    const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (el) el.click();
                }})()""")
                break

    # Wait and check containers
    print("\n[6] Checking containers after click...")
    for i in range(12):
        page.wait_for_timeout(500)
        t = (i + 1) * 0.5

        result = page.evaluate("""(() => {
            const result = {};
            const visible = [];

            // Check el-drawer
            const drawers = document.querySelectorAll('.el-drawer');
            for (const drawer of drawers) {
                const rect = drawer.getBoundingClientRect();
                const style = window.getComputedStyle(drawer);
                if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                    visible.push('drawer');
                    result.drawerFound = true;
                    result.drawerRect = { w: Math.round(rect.width), h: Math.round(rect.height) };
                    break;
                }
            }

            // Check el-dialog (current method)
            const dialogs = document.querySelectorAll('.el-dialog');
            result.dialogDetails = [];
            for (const dialog of dialogs) {
                const rect = dialog.getBoundingClientRect();
                const style = window.getComputedStyle(dialog);
                const wrapper = dialog.closest('.el-dialog__wrapper');
                const wrapperStyle = wrapper ? window.getComputedStyle(wrapper) : null;
                const passes = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                if (passes && !visible.includes('dialog')) {
                    visible.push('dialog');
                }
                // Only record non-hidden ones for brevity
                if (wrapperStyle && wrapperStyle.display !== 'none') {
                    result.dialogDetails.push({
                        rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                        dialogDisplay: style.display,
                        wrapperDisplay: wrapperStyle.display,
                        passes: passes
                    });
                }
            }

            // Check el-dialog__wrapper (proposed fix)
            const wrappers = document.querySelectorAll('.el-dialog__wrapper');
            result.wrapperDetails = [];
            for (const wrapper of wrappers) {
                const style = window.getComputedStyle(wrapper);
                if (style.display !== 'none') {
                    result.wrapperDetails.push({
                        display: style.display,
                        visibility: style.visibility
                    });
                }
            }

            result.detectVisible = visible;
            result.pageStats = {
                rows: document.querySelectorAll('.el-table__body-wrapper tbody tr').length,
                forms: document.querySelectorAll('form, .el-form').length,
                inputs: document.querySelectorAll('input, textarea, select').length
            };
            return result;
        })()""")

        detected = result.get('detectVisible', [])
        stats = result['pageStats']
        print(f"\n  [{t}s] detected={detected} | rows={stats['rows']}, forms={stats['forms']}, inputs={stats['inputs']}")

        if result.get('drawerFound'):
            print(f"    drawer: rect={result['drawerRect']}")

        if result.get('dialogDetails'):
            for j, d in enumerate(result['dialogDetails']):
                print(f"    dialog[{j}]: rect={d['rect']}, dialog.display={d['dialogDisplay']}, wrapper.display={d['wrapperDisplay']}, passes={d['passes']}")

        if result.get('wrapperDetails'):
            for j, w in enumerate(result['wrapperDetails']):
                print(f"    wrapper[{j}]: display={w['display']}, visibility={w['visibility']}")

        if detected:
            print(f"\n  >>> Container detected: {detected}")
            break

    page.screenshot(path='debug_final.png')
    print(f"\n[7] Screenshot saved: debug_final.png")
    browser.close()
    pw.stop()

if __name__ == '__main__':
    run()
