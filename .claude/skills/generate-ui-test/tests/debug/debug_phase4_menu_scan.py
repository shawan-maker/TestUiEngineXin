"""验证 Phase 4 菜单扫描流程 — 为什么"更改安全组"没被发现"""
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

    # ============================================
    # Step 1: 模拟 Phase 4 的 hover 阶段（不点"更多"）
    # ============================================
    print("\n" + "=" * 80)
    print("Step 1: 仅 hover 行（不点更多），检查菜单项可见性")
    print("=" * 80)

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

    # Phase 4 的菜单等待选择器
    _menu_sel = (
        '.el-dropdown-menu .el-dropdown-menu__item, '
        '.el-dropdown-menu li, '
        '.el-popover .el-button, '
        '.el-tooltip__popper .el-button, '
        'div[x-placement] div.el-tooltip.clickClass, '
        'div[x-placement] div.clickClass, '
        '.ant-dropdown-menu .ant-dropdown-menu-item, '
        '.ant-dropdown-menu li, '
        '.ant-dropdown .ant-dropdown-menu-item'
    )

    before_click = page.evaluate(f"""(() => {{
        const sel = `{_menu_sel}`;
        const all = document.querySelectorAll(sel);
        const visible = [];
        const hidden = [];
        all.forEach(el => {{
            const text = (el.textContent || '').trim().slice(0, 30);
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const info = {{ text, rect: {{ w: Math.round(rect.width), h: Math.round(rect.height) }}, display: style.display }};
            if (rect.width > 0 && rect.height > 0 && style.display !== 'none') {{
                visible.push(info);
            }} else {{
                hidden.push(info);
            }}
        }});
        return {{ total: all.length, visibleCount: visible.length, visible: visible.slice(0, 5), hiddenSample: hidden.slice(0, 3) }};
    }})()""")
    print(f"  菜单等待选择器匹配: total={before_click['total']}, visible={before_click['visibleCount']}")
    print(f"  可见项: {before_click['visible']}")

    # 同时检查 _row_hover.js 能发现什么
    row_buttons = page.evaluate("""(() => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const row = fixedRows[0];
        if (!row) return { error: 'no row' };
        const buttons = [];
        row.querySelectorAll('tbody .el-button, tbody .ec-button, tbody .el-dropdown span.el-dropdown-link, tbody .ec-dropdown span.el-dropdown-link, tbody span.el-dropdown-link, button, [role="button"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return;
            const text = (el.textContent || '').trim().slice(0, 30);
            if (!text) return;
            buttons.push({ text, tag: el.tagName, class: (typeof el.className === 'string') ? el.className.slice(0, 50) : '', rect: { w: Math.round(rect.width), h: Math.round(rect.height) } });
        });
        return buttons;
    })()""")
    print(f"\n  _row_hover.js 发现的按钮: {len(row_buttons)}")
    for b in row_buttons:
        print(f"    '{b['text']}' tag={b['tag']} class={b['class']} rect={b['rect']}")

    # ============================================
    # Step 2: 点击"更多"（模拟 Phase 4 的展开逻辑）
    # ============================================
    print("\n" + "=" * 80)
    print("Step 2: 点击'更多'触发器")
    print("=" * 80)

    # Phase 4 的"更多"点击逻辑：先找行内的 el-dropdown-link
    click_result = page.evaluate("""(() => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const mainRows = document.querySelectorAll('.el-table__body-wrapper tbody tr');
        const row = (fixedRows.length > 0) ? fixedRows[0] : ((mainRows.length > 0) ? mainRows[0] : null);
        if (!row) return { error: 'no row' };

        // Phase 4 在行内搜索"更多"
        let expandTrigger = null;
        const expandLabels = ['更多', '操作', '批量操作', '...', '⋯', '更多操作'];
        row.querySelectorAll('tbody .el-button, tbody .ec-button, tbody .el-dropdown span.el-dropdown-link, tbody .ec-dropdown span.el-dropdown-link, tbody span.el-dropdown-link, button, [role="button"]').forEach(el => {
            const t = (el.textContent || '').trim();
            if (expandLabels.includes(t) && !expandTrigger) {
                expandTrigger = el;
            }
        });

        if (expandTrigger) {
            const rect = expandTrigger.getBoundingClientRect();
            expandTrigger.click();
            return { clicked: true, text: expandTrigger.textContent.trim(), class: expandTrigger.className, rect: { w: Math.round(rect.width), h: Math.round(rect.height) } };
        }

        // 回退：全局搜索 .dropdown-more
        const dms = document.querySelectorAll('.dropdown-more');
        for (const dm of dms) {
            const rect = dm.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            const trigger = dm.querySelector('.el-dropdown-link');
            if (trigger) {
                trigger.click();
                return { clicked: true, text: 'dropdown-more fallback', class: trigger.className };
            }
        }
        return { clicked: false };
    })()""")
    print(f"  点击结果: {_json.dumps(click_result, ensure_ascii=False)}")

    # ============================================
    # Step 3: 模拟 Phase 4 的菜单等待和扫描
    # ============================================
    print("\n" + "=" * 80)
    print("Step 3: 菜单等待后扫描（Phase 4 逻辑）")
    print("=" * 80)

    # 等待 loading mask 消失
    for i in range(10):
        loading = page.evaluate("() => document.querySelectorAll(\".el-loading-mask:not([style*='display: none'])\").length")
        if loading == 0:
            print(f"  Loading mask cleared at {(i+1)*300}ms")
            break
        page.wait_for_timeout(300)

    # 等待菜单项出现
    menu_ready = False
    for i in range(20):
        cnt = page.evaluate(f"(sel) => document.querySelectorAll(sel).length", _menu_sel)
        if cnt > 0:
            print(f"  Menu items appeared at {(i+1)*300}ms (count={cnt})")
            menu_ready = True
            break
        page.wait_for_timeout(300)

    if not menu_ready:
        print("  Menu items never appeared within timeout")

    page.wait_for_timeout(500)  # extra animation wait

    # Phase 4 实际扫描代码（来自 discover_page.py L754-809 简化）
    scan_result = page.evaluate(f"""(() => {{
        const sel = `{_menu_sel}`;
        const all = document.querySelectorAll(sel);
        const items = [];
        all.forEach(el => {{
            const text = (el.textContent || '').trim();
            if (!text) return;
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            // Phase 4 的可见性过滤
            if (rect.width <= 0 || rect.height <= 0) return;
            if (style.display === 'none' || style.visibility === 'hidden') return;

            // 祖先链可见性检查
            let ancestorHidden = false;
            let ap = el.parentElement;
            while (ap) {{
                const cn = typeof ap.className === 'string' ? ap.className : '';
                if (cn && cn.includes('is-hidden')) {{ ancestorHidden = true; break; }}
                const st = window.getComputedStyle(ap);
                if (st.display === 'none' || st.visibility === 'hidden') {{ ancestorHidden = true; break; }}
                ap = ap.parentElement;
            }}
            if (ancestorHidden) return;

            items.push({{
                text: text.slice(0, 40),
                tag: el.tagName,
                class: (typeof el.className === 'string') ? el.className.slice(0, 60) : '',
                rect: {{ w: Math.round(rect.width), h: Math.round(rect.height) }}
            }});
        }});
        return items;
    }})()""")
    print(f"\n  Phase 4 扫描结果: {len(scan_result)} 项可见菜单")
    has_sg = False
    for item in scan_result:
        marker = ""
        if '更改安全组' in item['text'] or '安全组' in item['text']:
            marker = " ← 安全组相关!"
            has_sg = True
        print(f"    '{item['text']}' class={item['class'][:40]} rect={item['rect']}{marker}")

    if not has_sg:
        print(f"\n  >>> '更改安全组' 不在扫描结果中！")
        print(f"\n  检查'更改安全组'为什么不可见:")
        sg_debug = page.evaluate("""(() => {
            const xpath = "//*[contains(text(),'更改安全组')]";
            const snap = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            const results = [];
            for (let i = 0; i < snap.snapshotLength; i++) {
                const el = snap.snapshotItem(i);
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                // Walk ancestors to find x-placement parent
                let parents = [];
                let ap = el;
                while (ap && parents.length < 8) {
                    const cn = typeof ap.className === 'string' ? ap.className : '';
                    const xp = ap.getAttribute ? ap.getAttribute('x-placement') : null;
                    const st = window.getComputedStyle(ap);
                    parents.push({
                        tag: ap.tagName,
                        class: cn.slice(0, 40),
                        xPlacement: xp || '',
                        display: st.display,
                        visibility: st.visibility,
                        rect: { w: Math.round(ap.getBoundingClientRect().width), h: Math.round(ap.getBoundingClientRect().height) }
                    });
                    ap = ap.parentElement;
                }
                results.push({
                    text: (el.textContent || '').trim().slice(0, 30),
                    tag: el.tagName,
                    class: (typeof el.className === 'string') ? el.className.slice(0, 60) : '',
                    rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                    display: style.display,
                    visibility: style.visibility,
                    parents: parents
                });
            }
            return results;
        })()""")
        print(f"  找到 {len(sg_debug)} 个'更改安全组'元素:")
        for i, sg in enumerate(sg_debug[:5]):
            print(f"\n  [{i}] tag={sg['tag']}, class={sg['class']}, rect={sg['rect']}, display={sg['display']}")
            print(f"      祖先链:")
            for j, p in enumerate(sg['parents']):
                xp = f" x-placement={p['xPlacement']}" if p['xPlacement'] else ""
                print(f"        [{j}] {p['tag']}.{p['class']}{xp} display={p['display']} rect={p['rect']}")

    browser.close()
    pw.stop()

if __name__ == '__main__':
    run()
