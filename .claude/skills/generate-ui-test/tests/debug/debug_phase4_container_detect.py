"""验证 Phase 4 点击菜单项后的容器检测流程"""
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

    # Step 1: Hover 行 + 点击"更多"
    print("\n" + "=" * 80)
    print("Step 1: Hover 行 + 点击'更多'触发器")
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

    click_result = page.evaluate("""(() => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const row = fixedRows[0];
        if (!row) return { error: 'no row' };
        let expandTrigger = null;
        row.querySelectorAll('tbody .el-dropdown span.el-dropdown-link, tbody span.el-dropdown-link').forEach(el => {
            const t = (el.textContent || '').trim();
            if (t === '更多' && !expandTrigger) expandTrigger = el;
        });
        if (expandTrigger) {
            expandTrigger.click();
            return { clicked: true };
        }
        return { clicked: false };
    })()""")
    print(f"  点击'更多': {_json.dumps(click_result, ensure_ascii=False)}")

    # Step 2: 等待菜单项出现
    print("\n" + "=" * 80)
    print("Step 2: 等待菜单项出现")
    print("=" * 80)

    for i in range(10):
        loading = page.evaluate("() => document.querySelectorAll(\".el-loading-mask:not([style*='display: none'])\").length")
        if loading == 0:
            print(f"  Loading mask cleared at {(i+1)*300}ms")
            break
        page.wait_for_timeout(300)

    _menu_sel = '.el-dropdown-menu .el-dropdown-menu__item, .el-dropdown-menu li, .el-popover .el-button, .el-tooltip__popper .el-button, div[x-placement] div.el-tooltip.clickClass, div[x-placement] div.clickClass'
    for i in range(20):
        cnt = page.evaluate(f"(sel) => document.querySelectorAll(sel).length", _menu_sel)
        if cnt > 0:
            print(f"  Menu items appeared at {(i+1)*300}ms (count={cnt})")
            break
        page.wait_for_timeout(300)

    page.wait_for_timeout(500)

    # Step 3: 点击"更改安全组"菜单项
    print("\n" + "=" * 80)
    print("Step 3: 点击'更改安全组'菜单项")
    print("=" * 80)

    click_sg = page.evaluate("""(() => {
        const items = document.querySelectorAll('div[x-placement] div.clickClass');
        for (const item of items) {
            const text = (item.textContent || '').trim();
            if (text.includes('更改安全组')) {
                const rect = item.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    item.click();
                    return { clicked: true, text: text, rect: { w: Math.round(rect.width), h: Math.round(rect.height) } };
                }
            }
        }
        return { clicked: false };
    })()""")
    print(f"  点击结果: {_json.dumps(click_sg, ensure_ascii=False)}")

    # Step 4: 模拟 Phase 4 的 wait_for_stable
    print("\n" + "=" * 80)
    print("Step 4: wait_for_stable (8s timeout + 1s animation + 1s second-pass)")
    print("=" * 80)

    # Phase 4 的 wait_for_stable 逻辑
    container_selector = "div.el-drawer:not([style*='display: none']), div.el-dialog__wrapper:not([style*='display: none']), div.el-message-box, div.ant-drawer:not(.ant-drawer-hidden), div.ant-modal-wrap:not([style*='display: none'])"

    try:
        page.wait_for_selector(container_selector, state='visible', timeout=8000)
        print("  wait_for_selector 检测到可见容器")
    except Exception as e:
        print(f"  wait_for_selector 超时: {e}")

    page.wait_for_timeout(1000)  # extra animation wait
    print("  额外等待 1s 动画")

    # Step 5: 第一次 detect_visible_containers（Phase 4 L1852-1857 的 3 次重试）
    print("\n" + "=" * 80)
    print("Step 5: detect_visible_containers (3 次重试，每次间隔 500ms)")
    print("=" * 80)

    for retry in range(3):
        print(f"\n  Retry {retry + 1}/3:")

        # 完整的 detect_visible_containers 实现
        result = page.evaluate("""(() => {
            const visible = [];

            // 检查 el-drawer
            const drawers = document.querySelectorAll('.el-drawer');
            const drawerDetails = [];
            for (const drawer of drawers) {
                const rect = drawer.getBoundingClientRect();
                const style = window.getComputedStyle(drawer);
                const passes = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                drawerDetails.push({
                    rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                    display: style.display,
                    visibility: style.visibility,
                    passes: passes
                });
                if (passes) {
                    visible.push('drawer');
                    break;
                }
            }

            // 检查 el-dialog
            const dialogs = document.querySelectorAll('.el-dialog');
            const dialogDetails = [];
            for (const dialog of dialogs) {
                const rect = dialog.getBoundingClientRect();
                const style = window.getComputedStyle(dialog);
                const wrapper = dialog.closest('.el-dialog__wrapper');
                const wrapperStyle = wrapper ? window.getComputedStyle(wrapper) : null;
                const passes = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                dialogDetails.push({
                    rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                    display: style.display,
                    visibility: style.visibility,
                    wrapperDisplay: wrapperStyle ? wrapperStyle.display : null,
                    passes: passes
                });
                if (passes) {
                    visible.push('dialog');
                    break;
                }
            }

            // 检查 el-message-box
            const messageBoxes = document.querySelectorAll('.el-message-box');
            const messageBoxDetails = [];
            for (const box of messageBoxes) {
                const rect = box.getBoundingClientRect();
                const style = window.getComputedStyle(box);
                const passes = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                messageBoxDetails.push({
                    rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                    display: style.display,
                    passes: passes
                });
                if (passes) {
                    visible.push('message-box');
                    break;
                }
            }

            return {
                visible: visible,
                drawers: drawerDetails,
                dialogs: dialogDetails.slice(0, 5),  // 只返回前 5 个，避免输出过长
                totalDialogs: dialogDetails.length,
                messageBoxes: messageBoxDetails
            };
        })()""")

        print(f"    检测到: {result['visible']}")
        print(f"    Drawers ({len(result['drawers'])}):")
        for i, d in enumerate(result['drawers'][:3]):
            print(f"      [{i}] rect={d['rect']}, display={d['display']}, passes={d['passes']}")

        print(f"    Dialogs (前 5 个 / 共 {result['totalDialogs']} 个):")
        for i, d in enumerate(result['dialogs']):
            print(f"      [{i}] rect={d['rect']}, display={d['display']}, wrapper={d['wrapperDisplay']}, passes={d['passes']}")

        print(f"    MessageBoxes ({len(result['messageBoxes'])}):")
        for i, d in enumerate(result['messageBoxes'][:3]):
            print(f"      [{i}] rect={d['rect']}, display={d['display']}, passes={d['passes']}")

        if result['visible']:
            print(f"\n  >>> 第 {retry + 1} 次检测到容器: {result['visible']}")
            break

        page.wait_for_timeout(500)

    # Step 6: 检查所有 dialog wrapper 的状态
    print("\n" + "=" * 80)
    print("Step 6: 检查所有 dialog wrapper 的 display 状态")
    print("=" * 80)

    wrappers = page.evaluate("""(() => {
        const wrappers = document.querySelectorAll('.el-dialog__wrapper');
        const results = [];
        for (const wrapper of wrappers) {
            const style = window.getComputedStyle(wrapper);
            const dialog = wrapper.querySelector('.el-dialog');
            const dialogRect = dialog ? dialog.getBoundingClientRect() : null;
            results.push({
                display: style.display,
                visibility: style.visibility,
                hasDialog: !!dialog,
                dialogRect: dialogRect ? { w: Math.round(dialogRect.width), h: Math.round(dialogRect.height) } : null
            });
        }
        return results;
    })()""")

    visible_wrappers = [w for w in wrappers if w['display'] != 'none']
    print(f"  总 wrappers: {len(wrappers)}")
    print(f"  可见 wrappers (display !== none): {len(visible_wrappers)}")

    for i, w in enumerate(visible_wrappers):
        print(f"    [{i}] display={w['display']}, visibility={w['visibility']}, hasDialog={w['hasDialog']}, dialogRect={w['dialogRect']}")

    # Step 7: 额外等待 1s 后再次检测（Phase 4 L936 的 second-pass）
    if not result['visible']:
        print("\n" + "=" * 80)
        print("Step 7: 额外等待 1s 后再次检测 (Phase 4 second-pass)")
        print("=" * 80)

        page.wait_for_timeout(1000)

        result2 = page.evaluate("""(() => {
            const visible = [];
            const dialogs = document.querySelectorAll('.el-dialog');
            for (const dialog of dialogs) {
                const rect = dialog.getBoundingClientRect();
                const style = window.getComputedStyle(dialog);
                const passes = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                if (passes) {
                    visible.push('dialog');
                    break;
                }
            }
            return visible;
        })()""")

        print(f"  Second-pass 检测到: {result2}")

    browser.close()
    pw.stop()

if __name__ == '__main__':
    run()
