"""精确复现 Phase 4 的"更改安全组"点击流程 — 为什么 detect_visible_containers 返回空"""
import sys, json as _json, io
sys.path.insert(0, r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright

COOKIE = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; accessToken=7818c272-7932-4517-bfc7-8218c6c43e79; JSESSIONID=9B8492CFC6668BFF87733AA9051E3DC4; estack_lang=zh-CN"
TARGET_URL = "http://10.151.37.249/estack/web/ecm-compute-static/vm/list?productType=vm"

def run():
    pw = sync_playwright().start()
    # Phase 4 用 headless=True
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

    # ===== Phase 4 完整流程：hover → 展开"更多" → 扫描菜单项 =====

    # Step 1: Phase 4 的 hover 行 + 展开"更多" (from_expand 路径)
    print("\n" + "=" * 80)
    print("Step 1: Hover 行 + 展开'更多' (Phase 4 from_expand 路径)")
    print("=" * 80)

    # Phase 4 L1633-1667: hover + 展开
    page.evaluate("""(() => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const mainRows = document.querySelectorAll('.el-table__body-wrapper tbody tr');
        if (mainRows[0]) {
            mainRows[0].scrollIntoView({block: 'center', inline: 'nearest'});
            mainRows[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            mainRows[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        }
        if (fixedRows[0]) {
            fixedRows[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            fixedRows[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        }
        // 搜索"更多"触发器
        const searchRow = (fixedRows.length > 0) ? fixedRows[0] : ((mainRows.length > 0) ? mainRows[0] : null);
        if (searchRow) {
            const expandLabels = ['更多', '操作', '批量操作', '...', '⋯', '更多操作'];
            let expandTrigger = null;
            searchRow.querySelectorAll('tbody .el-button, tbody .ec-button, tbody .el-dropdown span.el-dropdown-link, tbody .ec-dropdown span.el-dropdown-link, tbody span.el-dropdown-link, button, [role="button"]').forEach(el => {
                const t = (el.textContent || '').trim();
                if (expandLabels.includes(t) && !expandTrigger) {
                    expandTrigger = el;
                }
            });
            if (expandTrigger) expandTrigger.click();
        }
    })()""")

    # Phase 4 L1672-1697: 等待 loading mask + 菜单项出现
    for _ in range(50):
        page.wait_for_timeout(300)
        loading = page.evaluate("() => document.querySelectorAll(\".el-loading-mask:not([style*='display: none'])\").length")
        if loading == 0:
            break

    _menu_sel = '.el-dropdown-menu .el-dropdown-menu__item, .el-dropdown-menu li, .el-popover .el-button, .el-tooltip__popper .el-button, div[x-placement] div.el-tooltip.clickClass, div[x-placement] div.clickClass'
    for _ in range(50):
        page.wait_for_timeout(300)
        cnt = page.evaluate(f"(sel) => document.querySelectorAll(sel).length", _menu_sel)
        if cnt > 0:
            print(f"  菜单项出现 (count={cnt})")
            break

    # Step 2: Phase 4 L1700-1717 — 在菜单中搜索并点击"更改安全组"
    print("\n" + "=" * 80)
    print("Step 2: 在菜单中搜索并点击'更改安全组' (Phase 4 L1700-1717)")
    print("=" * 80)

    # Phase 4 用 fwSelectors.dropdownMenu 的选择器来搜索
    # 实际代码: for (const sel of menuSelectors) { document.querySelectorAll(sel).forEach(el => { ... }) }
    click_result = page.evaluate("""(() => {
        const menuSelectors = [
            '.el-dropdown-menu .el-dropdown-menu__item',
            '.el-dropdown-menu li',
            '.el-popover .el-button',
            '.el-tooltip__popper .el-button',
            'div[x-placement] div.el-tooltip.clickClass',
            'div[x-placement] div.clickClass'
        ];
        let target = null;
        let foundBy = null;
        for (const sel of menuSelectors) {
            if (target) break;
            document.querySelectorAll(sel).forEach(el => {
                if (target) return;
                const t = (el.textContent || '').trim();
                if (t === '更改安全组') {
                    target = el;
                    foundBy = sel;
                }
            });
        }
        if (!target) {
            // 尝试 contains 匹配
            for (const sel of menuSelectors) {
                if (target) break;
                document.querySelectorAll(sel).forEach(el => {
                    if (target) return;
                    const t = (el.textContent || '').trim();
                    if (t.includes('更改安全组')) {
                        target = el;
                        foundBy = sel + ' (contains)';
                    }
                });
            }
        }
        if (target) {
            const rect = target.getBoundingClientRect();
            target.click();
            return { clicked: true, text: (target.textContent || '').trim().slice(0, 40), sel: foundBy, rect: { w: Math.round(rect.width), h: Math.round(rect.height) } };
        }
        // 未找到时返回所有菜单项文本
        const allTexts = [];
        document.querySelectorAll('div[x-placement] div.clickClass').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                allTexts.push((el.textContent || '').trim().slice(0, 30));
            }
        });
        return { clicked: false, availableItems: allTexts };
    })()""")
    print(f"  点击结果: {_json.dumps(click_result, ensure_ascii=False)}")

    if not click_result.get('clicked'):
        print("\n  >>> '更改安全组'未被找到！可用项:")
        for t in click_result.get('availableItems', []):
            print(f"    '{t}'")
        browser.close()
        pw.stop()
        return

    # Step 3: Phase 4 wait_for_stable (8s + 1s animation + second-pass)
    print("\n" + "=" * 80)
    print("Step 3: Phase 4 wait_for_stable (8s timeout + 1s animation)")
    print("=" * 80)

    container_selector = (
        "div.el-drawer:not([style*='display: none']), "
        "div.el-dialog__wrapper:not([style*='display: none']), "
        "div.el-message-box, "
        "div.ant-drawer:not(.ant-drawer-hidden), "
        "div.ant-modal-wrap:not([style*='display: none'])"
    )
    try:
        page.wait_for_selector(container_selector, state='visible', timeout=8000)
        print("  wait_for_selector 成功")
    except Exception:
        print("  wait_for_selector 超时 (8s)")

    page.wait_for_timeout(1000)
    print("  额外等待 1s 动画")

    # Step 4: Phase 4 的 detect_visible_containers（3 次重试）
    print("\n" + "=" * 80)
    print("Step 4: detect_visible_containers (Phase 4 3次重试)")
    print("=" * 80)

    from probe.probe_element import detect_visible_containers
    for retry in range(3):
        visible = detect_visible_containers(page)
        print(f"  Retry {retry+1}: {visible}")
        if visible:
            break
        page.wait_for_timeout(500)

    if not visible:
        # Second-pass (wait_for_stable L934-938)
        page.wait_for_timeout(1000)
        visible = detect_visible_containers(page)
        print(f"  Second-pass (额外 1s): {visible}")

    # Step 5: 深入检查 .el-dialog 元素的实际状态
    print("\n" + "=" * 80)
    print("Step 5: 深入检查 .el-dialog 元素的 computed style")
    print("=" * 80)

    dialog_debug = page.evaluate("""(() => {
        const results = [];
        // 所有 .el-dialog 元素
        document.querySelectorAll('.el-dialog').forEach((dialog, i) => {
            const rect = dialog.getBoundingClientRect();
            const style = window.getComputedStyle(dialog);
            const wrapper = dialog.closest('.el-dialog__wrapper');
            const wrapperStyle = wrapper ? window.getComputedStyle(wrapper) : null;

            // 检查 dialog 是否在 viewport 内
            const inViewport = rect.right > 0 && rect.bottom > 0 && rect.left < window.innerWidth && rect.top < window.innerHeight;

            // 检查所有祖先链
            const ancestors = [];
            let el = dialog.parentElement;
            while (el && ancestors.length < 5) {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                const cn = typeof el.className === 'string' ? el.className : '';
                ancestors.push({
                    tag: el.tagName,
                    class: cn.slice(0, 60),
                    display: s.display,
                    visibility: s.visibility,
                    opacity: s.opacity,
                    rect: { w: Math.round(r.width), h: Math.round(r.height) }
                });
                el = el.parentElement;
            }

            results.push({
                index: i,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top), left: Math.round(rect.left) },
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                inViewport: inViewport,
                wrapperDisplay: wrapperStyle ? wrapperStyle.display : null,
                wrapperVisibility: wrapperStyle ? wrapperStyle.visibility : null,
                wrapperOpacity: wrapperStyle ? wrapperStyle.opacity : null,
                wrapperRect: wrapper ? { w: Math.round(wrapper.getBoundingClientRect().width), h: Math.round(wrapper.getBoundingClientRect().height) } : null,
                ancestors: ancestors
            });
        });
        return results;
    })()""")

    print(f"  找到 {len(dialog_debug)} 个 .el-dialog 元素")
    for d in dialog_debug:
        is_vis = d['rect']['w'] > 0 and d['rect']['h'] > 0 and d['display'] != 'none' and d['visibility'] != 'hidden'
        marker = " <<< VISIBLE" if is_vis else ""
        print(f"\n  [{d['index']}] rect={d['rect']}, display={d['display']}, visibility={d['visibility']}, opacity={d['opacity']}{marker}")
        print(f"    wrapper: display={d['wrapperDisplay']}, visibility={d['wrapperVisibility']}, opacity={d['wrapperOpacity']}, rect={d['wrapperRect']}")
        print(f"    inViewport: {d['inViewport']}")
        for j, a in enumerate(d['ancestors']):
            print(f"    ancestor[{j}]: {a['tag']}.{a['class']} display={a['display']} vis={a['visibility']} opacity={a['opacity']} rect={a['rect']}")

    # Step 6: 检查 .el-dialog__wrapper 的 inline style
    print("\n" + "=" * 80)
    print("Step 6: .el-dialog__wrapper 的 style 属性")
    print("=" * 80)

    wrappers = page.evaluate("""(() => {
        const results = [];
        document.querySelectorAll('.el-dialog__wrapper').forEach((w, i) => {
            const style = window.getComputedStyle(w);
            const rect = w.getBoundingClientRect();
            results.push({
                index: i,
                inlineStyle: w.getAttribute('style') || '',
                computedDisplay: style.display,
                computedVisibility: style.visibility,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                hasDialog: !!w.querySelector('.el-dialog')
            });
        });
        return results;
    })()""")

    visible_w = [w for w in wrappers if w['computedDisplay'] != 'none']
    print(f"  总 wrappers: {len(wrappers)}")
    print(f"  可见 wrappers: {len(visible_w)}")
    for w in visible_w:
        print(f"    [{w['index']}] inlineStyle='{w['inlineStyle'][:80]}', computedDisplay={w['computedDisplay']}, rect={w['rect']}")

    browser.close()
    pw.stop()

if __name__ == '__main__':
    run()
