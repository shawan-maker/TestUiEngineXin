"""验证 eStack "更多"菜单的真实 DOM 结构"""
import sys, json as _json, io
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
    page.goto("http://10.151.37.249/", wait_until='domcontentloaded', timeout=15000)
    page.evaluate("() => { localStorage.setItem('accessToken', '7818c272-7932-4517-bfc7-8218c6c43e79'); }")
    page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(5000)
    print(f"URL: {page.url}")

    # Hover + click "更多"
    page.evaluate("""(() => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const mainRows = document.querySelectorAll('.el-table__body-wrapper tbody tr');
        if (mainRows[0]) {
            mainRows[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            mainRows[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        }
        if (fixedRows[0]) {
            fixedRows[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            fixedRows[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        }
    })()""")
    page.wait_for_timeout(500)

    page.evaluate("""(() => {
        const triggers = document.querySelectorAll('.el-dropdown-link');
        for (const t of triggers) {
            if ((t.textContent || '').trim() === '更多') {
                const rect = t.getBoundingClientRect();
                if (rect.width > 0) { t.click(); return true; }
            }
        }
        return false;
    })()""")
    page.wait_for_timeout(1000)

    print("\n" + "=" * 80)
    print("1. Phase 4 现有 CSS 选择器匹配结果")
    print("=" * 80)

    # Phase 4 用的 CSS 选择器
    phase4_selectors = {
        '.el-dropdown-menu .el-dropdown-menu__item': None,
        '.el-dropdown-menu li': None,
        '.el-popover .el-button': None,
        '.el-tooltip__popper .el-button': None,
        'div[x-placement] div.el-tooltip.clickClass': None,
        'div[x-placement] div.clickClass': None,
        '.ant-dropdown-menu .ant-dropdown-menu-item': None,
        '.ant-dropdown-menu li': None,
    }
    for sel in phase4_selectors:
        count = page.evaluate(f"() => document.querySelectorAll('{sel}').length")
        print(f"  {sel}: {count}")

    print("\n" + "=" * 80)
    print("2. 用户提供的 XPath 匹配结果")
    print("=" * 80)

    xpath = '//div[@x-placement]//div[contains(@class,"more-item-dropdown")]//div[contains(@class,"clickClass") and not(contains(@style,"display: none;"))]'
    result = page.evaluate(f"""(() => {{
        const xpath = '{xpath}';
        const snapshot = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
        const items = [];
        for (let i = 0; i < snapshot.snapshotLength; i++) {{
            const el = snapshot.snapshotItem(i);
            const rect = el.getBoundingClientRect();
            items.push({{
                text: (el.textContent || '').trim().slice(0, 30),
                class: el.className,
                rect: {{ w: Math.round(rect.width), h: Math.round(rect.height) }},
                visible: rect.width > 0 && rect.height > 0
            }});
        }}
        return {{ total: snapshot.snapshotLength, items: items }};
    }})()""")
    print(f"  Total: {result['total']}")
    visible_items = [i for i in result['items'] if i['visible']]
    hidden_items = [i for i in result['items'] if not i['visible']]
    print(f"  Visible (rect > 0): {len(visible_items)}")
    print(f"  Hidden (rect = 0): {len(hidden_items)}")
    print(f"\n  Visible items:")
    for item in visible_items:
        print(f"    '{item['text']}' class={item['class']} rect={item['rect']}")

    print("\n" + "=" * 80)
    print("3. 分析 eStack 菜单的 DOM 结构")
    print("=" * 80)

    structure = page.evaluate("""(() => {
        // Find the visible x-placement popover
        const popovers = document.querySelectorAll('div[x-placement]');
        for (const p of popovers) {
            const rect = p.getBoundingClientRect();
            const style = window.getComputedStyle(p);
            if (style.display === 'none' || rect.width <= 0) continue;

            // Get the more-item-dropdown divs
            const groups = p.querySelectorAll('div.more-item-dropdown');
            const result = {
                popoverClass: p.className,
                placement: p.getAttribute('x-placement'),
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                groups: []
            };

            for (const g of groups) {
                const gRect = g.getBoundingClientRect();
                const gStyle = window.getComputedStyle(g);
                const items = [];
                g.querySelectorAll('div.clickClass').forEach(el => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    items.push({
                        text: (el.textContent || '').trim().slice(0, 30),
                        rect: { w: Math.round(r.width), h: Math.round(r.height) },
                        display: s.display,
                        style: el.getAttribute('style') || ''
                    });
                });
                result.groups.push({
                    class: g.className,
                    rect: { w: Math.round(gRect.width), h: Math.round(gRect.height) },
                    display: gStyle.display,
                    itemCount: items.length,
                    items: items
                });
            }
            return result;
        }
        return { error: 'no visible popover' };
    })()""")
    print(f"  Popover: class={structure.get('popoverClass','')}, placement={structure.get('placement','')}")
    print(f"  Groups (more-item-dropdown): {len(structure.get('groups', []))}")
    for i, g in enumerate(structure.get('groups', [])):
        vis = [it for it in g['items'] if it['rect']['w'] > 0]
        hid = [it for it in g['items'] if it['rect']['w'] == 0]
        print(f"\n  Group[{i}]: class={g['class']}, display={g['display']}, rect={g['rect']}")
        print(f"    Visible items: {len(vis)}, Hidden items: {len(hid)}")
        for it in vis:
            print(f"      V: '{it['text']}' rect={it['rect']} style='{it['style']}'")
        for it in hid[:3]:
            print(f"      H: '{it['text']}' rect={it['rect']} style='{it['style']}'")
        if len(hid) > 3:
            print(f"      ... and {len(hid)-3} more hidden")

    print("\n" + "=" * 80)
    print("4. Phase 4 CSS 选择器 vs 实际 DOM 的差异")
    print("=" * 80)

    diff = page.evaluate("""(() => {
        // Check: div[x-placement] div.clickClass (Phase 4 selector)
        const p4 = document.querySelectorAll('div[x-placement] div.clickClass');
        const p4Texts = Array.from(p4).map(el => ({
            text: (el.textContent || '').trim().slice(0, 30),
            inMoreItem: !!el.closest('.more-item-dropdown'),
            rect: { w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height) }
        }));

        // Check: actual more-item-dropdown clickClass items
        const real = document.querySelectorAll('div.more-item-dropdown div.clickClass');
        const realTexts = Array.from(real).map(el => ({
            text: (el.textContent || '').trim().slice(0, 30),
            inXPlacement: !!el.closest('div[x-placement]'),
            rect: { w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height) }
        }));

        return {
            p4Selector: { count: p4Texts.length, items: p4Texts.filter(t => t.rect.w > 0) },
            realStructure: { count: realTexts.length, inXPlacement: realTexts.filter(t => t.inXPlacement).length }
        };
    })()""")
    print(f"  Phase 4 'div[x-placement] div.clickClass': {diff['p4Selector']['count']} total")
    print(f"    Visible: {len(diff['p4Selector']['items'])}")
    print(f"  Actual more-item-dropdown clickClass: {diff['realStructure']['count']} total")
    print(f"    In x-placement: {diff['realStructure']['inXPlacement']}")

    # Check if p4 selector items are inside more-item-dropdown
    overlap = page.evaluate("""(() => {
        const p4 = document.querySelectorAll('div[x-placement] div.clickClass');
        let inMore = 0, notInMore = 0;
        const samples = { inMore: [], notInMore: [] };
        for (const el of p4) {
            const text = (el.textContent || '').trim().slice(0, 30);
            const rect = el.getBoundingClientRect();
            if (el.closest('.more-item-dropdown')) {
                inMore++;
                if (samples.inMore.length < 3) samples.inMore.push({ text, rect: { w: Math.round(rect.width), h: Math.round(rect.height) } });
            } else {
                notInMore++;
                if (samples.notInMore.length < 3) samples.notInMore.push({ text, rect: { w: Math.round(rect.width), h: Math.round(rect.height) } });
            }
        }
        return { inMore, notInMore, samples };
    })()""")
    print(f"\n  Phase 4 匹配项分布:")
    print(f"    在 .more-item-dropdown 内: {overlap['inMore']} (samples: {overlap['samples']['inMore']})")
    print(f"    不在 .more-item-dropdown 内: {overlap['notInMore']} (samples: {overlap['samples']['notInMore']})")

    browser.close()
    pw.stop()

if __name__ == '__main__':
    run()
