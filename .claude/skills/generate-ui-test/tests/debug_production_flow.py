"""精确复现 _discover_row_buttons_with_hover 流程，定位退订丢失原因"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml")
URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"

# 生产代码的菜单选择器
MENU_SEL = (
    '.el-dropdown-menu .el-dropdown-menu__item, '
    '.el-dropdown-menu li, '
    '.el-popover .el-button, '
    '.el-tooltip__popper .el-button, '
    'div[x-placement] div.el-tooltip.clickClass, '
    'div[x-placement] div.clickClass'
)

# 诊断选择器（diagnose_hover_diff.py 使用的）
DIAG_SEL = 'div[x-placement] div.clickClass'


def run():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True, ignore_https_errors=True)
        cookies = []
        for part in config["cookie"].split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                cookies.append({"name": name.strip(), "value": value.strip(),
                                "domain": config["cookie_domain"], "path": "/"})
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        print("=" * 70)
        print("Step 0: 检查 .dropdown-more 数量和可见性")
        print("=" * 70)
        dm_info = page.evaluate("""
        (() => {
            const dms = document.querySelectorAll('.dropdown-more');
            const results = [];
            for (const dm of dms) {
                const rect = dm.getBoundingClientRect();
                let hidden = false;
                let reason = '';
                let p = dm;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn && cn.includes('is-hidden')) { hidden = true; reason = 'is-hidden'; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none') { hidden = true; reason = 'display:none'; break; }
                    if (st.visibility === 'hidden') { hidden = true; reason = 'visibility:hidden'; break; }
                    p = p.parentElement;
                }
                const trigger = dm.querySelector('.el-dropdown-link, .el-popover__reference');
                results.push({
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    hidden, reason,
                    hasTrigger: !!trigger,
                    tbodyType: dm.closest('.el-table__fixed-right') ? 'fixed-right'
                              : dm.closest('.el-table__fixed') ? 'fixed'
                              : dm.closest('.el-table__body-wrapper') ? 'main'
                              : 'unknown',
                });
            }
            return results;
        })()
        """)
        print(f"  .dropdown-more 总数: {len(dm_info)}")
        visible_dms = [d for d in dm_info if not d['hidden'] and d['hasTrigger'] and d['rect']['w'] > 0]
        print(f"  可见+有trigger: {len(visible_dms)}")
        for i, d in enumerate(dm_info):
            vis = f"[HID:{d['reason']}]" if d['hidden'] else "[VIS]" if d['rect']['w'] > 0 else "[ZERO]"
            print(f"    [{i}] {vis} {d['tbodyType']} rect=({d['rect']['x']},{d['rect']['y']},{d['rect']['w']}x{d['rect']['h']}) trigger={d['hasTrigger']}")

        # 模拟生产代码的行迭代 (i=0 only)
        for row_idx in range(1):  # 只测第1行
            print(f"\n{'='*70}")
            print(f"Step 1: Hover row {row_idx} (生产代码方式: scrollIntoView + 双 tbody)")
            print(f"{'='*70}")

            # 精确复现生产代码的 hover
            page.evaluate("""(rowIndex) => {
                const mainRows = document.querySelectorAll(
                    '.el-table__body-wrapper > table > tbody > tr');
                if (rowIndex < mainRows.length) {
                    const mainRow = mainRows[rowIndex];
                    mainRow.scrollIntoView({block: 'center', inline: 'nearest'});
                    mainRow.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                    mainRow.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                }
                const fixedRows = document.querySelectorAll(
                    '.el-table__fixed-right tbody tr');
                if (rowIndex < fixedRows.length) {
                    const fixedRow = fixedRows[rowIndex];
                    fixedRow.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                    fixedRow.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                }
            }""", row_idx)
            page.wait_for_timeout(500)  # hover_delay_ms

            # Step 2: 扫描行按钮 (_ROW_HOVER_JS 模拟)
            print(f"\nStep 2: 扫描行按钮 (检查是否找到'更多')")
            btns = page.evaluate("""
            (rowIndex) => {
                const buttons = [];
                const rowSelectors = [
                    '.el-table__fixed-right tbody tr',
                    '.el-table__body-wrapper > table > tbody > tr'
                ];
                for (const sel of rowSelectors) {
                    const rows = document.querySelectorAll(sel);
                    if (rowIndex >= rows.length) continue;
                    const row = rows[rowIndex];
                    if (!row) continue;
                    row.querySelectorAll('.el-button, .ec-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, span.el-dropdown-link, .el-dropdown span[style*="cursor"], .ec-dropdown span[style*="cursor"]').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        if (rect.width <= 0 || rect.height <= 0) return;
                        if (style.display === 'none' || style.visibility === 'hidden') return;
                        let ancestorHidden = false;
                        let ap = el.parentElement;
                        while (ap && ap !== document.body) {
                            const as = window.getComputedStyle(ap);
                            if (as.display === 'none' || as.visibility === 'hidden') { ancestorHidden = true; break; }
                            ap = ap.parentElement;
                        }
                        if (ancestorHidden) return;
                        const text = (el.textContent || '').trim().slice(0, 100);
                        if (!text) return;
                        buttons.push({
                            text,
                            tbodyType: el.closest('.el-table__fixed-right') ? 'fixed-right'
                                      : el.closest('.el-table__fixed') ? 'fixed'
                                      : el.closest('.el-table__body-wrapper') ? 'main'
                                      : 'unknown',
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y)}
                        });
                    });
                }
                return buttons;
            }
            """, row_idx)

            expand_labels = ['更多', 'More', 'more', '...', '…']
            expand_btn = None
            for b in btns:
                if b['text'] in expand_labels:
                    expand_btn = b
                    break

            print(f"  行按钮数: {len(btns)}")
            for b in btns:
                tag = " [EXPAND]" if b['text'] in expand_labels else ""
                print(f"    '{b['text']}' in {b['tbodyType']} at ({b['rect']['x']},{b['rect']['y']}){tag}")
            print(f"  expand_btn: {expand_btn['text'] if expand_btn else 'NONE'}")

            if not expand_btn:
                print("  [SKIP] 没有展开按钮，跳过")
                continue

            # Step 3: 点击展开 (生产代码方式: 全局搜索 .dropdown-more)
            print(f"\nStep 3: 点击展开 (全局搜索 .dropdown-more)")
            click_result = page.evaluate("""
            (() => {
                const dms = document.querySelectorAll('.dropdown-more');
                for (const dm of dms) {
                    const rect = dm.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) continue;
                    let hidden = false;
                    let p = dm;
                    while (p) {
                        const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                        if (cn && cn.includes('is-hidden')) { hidden = true; break; }
                        const st = window.getComputedStyle(p);
                        if (st.display === 'none' || st.visibility === 'hidden') { hidden = true; break; }
                        p = p.parentElement;
                    }
                    if (hidden) continue;
                    const trigger = dm.querySelector('.el-dropdown-link, .el-popover__reference');
                    if (trigger) {
                        trigger.click();
                        return {
                            clicked: true,
                            dmRect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                            triggerRect: {x: Math.round(trigger.getBoundingClientRect().x), y: Math.round(trigger.getBoundingClientRect().y)},
                            tbodyType: dm.closest('.el-table__fixed-right') ? 'fixed-right'
                                      : dm.closest('.el-table__fixed') ? 'fixed'
                                      : dm.closest('.el-table__body-wrapper') ? 'main'
                                      : 'unknown',
                        };
                    }
                }
                return {clicked: false};
            })()
            """)
            print(f"  click result: {click_result}")

            # Step 4: 等待菜单 (生产代码方式: 轮询)
            print(f"\nStep 4: 等待菜单出现 (轮询)")
            menu_ready = False
            for poll in range(10):
                page.wait_for_timeout(300)
                cnt = page.evaluate(f"""(sel) => document.querySelectorAll(sel).length""", MENU_SEL)
                print(f"  poll {poll}: {cnt} items matched production selector")
                if cnt > 0:
                    menu_ready = True
                    break

            if not menu_ready:
                print("  [FAIL] 菜单未出现！")

            # Step 5: 用两种选择器分别扫描菜单
            print(f"\nStep 5: 扫描菜单项")

            # 生产代码选择器
            prod_items = page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll(
                    '.el-dropdown-menu .el-dropdown-menu__item, '
                    + '.el-dropdown-menu li, '
                    + '.el-popover .el-button, '
                    + '.el-tooltip__popper .el-button, '
                    + 'div[x-placement] div.el-tooltip.clickClass, '
                    + 'div[x-placement] div.clickClass'
                ).forEach(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (rect.width <= 0 || rect.height <= 0) return;
                    if (style.display === 'none' || style.visibility === 'hidden') return;
                    let ancestorHidden = false;
                    let ap = el.parentElement;
                    while (ap && ap !== document.body) {
                        const as = window.getComputedStyle(ap);
                        if (as.display === 'none' || as.visibility === 'hidden') { ancestorHidden = true; break; }
                        ap = ap.parentElement;
                    }
                    if (ancestorHidden) return;
                    const text = (el.textContent || '').trim().slice(0, 100);
                    if (!text) return;
                    items.push({
                        text,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                        selector: el.closest('.el-dropdown-menu') ? 'dropdown-menu'
                                   : el.closest('.el-popover') ? 'popover'
                                   : el.closest('[x-placement]') ? 'x-placement'
                                   : 'other',
                    });
                });
                return items;
            }
            """)

            # 诊断选择器
            diag_items = page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('div[x-placement] div.clickClass').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (rect.width <= 0 || rect.height <= 0) return;
                    if (style.display === 'none' || style.visibility === 'hidden') return;
                    let ancestorHidden = false;
                    let ap = el.parentElement;
                    while (ap && ap !== document.body) {
                        const as = window.getComputedStyle(ap);
                        if (as.display === 'none' || as.visibility === 'hidden') { ancestorHidden = true; break; }
                        ap = ap.parentElement;
                    }
                    if (ancestorHidden) return;
                    const text = (el.textContent || '').trim().replace(/\\s*(new|hot)\\s*/gi, '').trim();
                    if (!text) return;
                    items.push({
                        text,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                    });
                });
                return items;
            }
            """)

            prod_texts = [i['text'] for i in prod_items]
            diag_texts = [i['text'] for i in diag_items]
            has_tuiding_prod = any('退订' in t for t in prod_texts)
            has_tuiding_diag = any('退订' in t for t in diag_texts)

            print(f"  生产选择器: {len(prod_items)} items, 有退订: {has_tuiding_prod}")
            for item in prod_items:
                tag = " [TUIDING]" if '退订' in item['text'] else ""
                print(f"    '{item['text']}' [{item['selector']}] at ({item['rect']['x']},{item['rect']['y']}){tag}")

            print(f"\n  诊断选择器: {len(diag_items)} items, 有退订: {has_tuiding_diag}")
            for item in diag_items:
                tag = " [TUIDING]" if '退订' in item['text'] else ""
                print(f"    '{item['text']}' at ({item['rect']['x']},{item['rect']['y']}){tag}")

            # 对比差异
            prod_set = set(prod_texts)
            diag_set = set(diag_texts)
            only_prod = prod_set - diag_set
            only_diag = diag_set - prod_set
            if only_prod:
                print(f"\n  仅生产选择器有: {only_prod}")
            if only_diag:
                print(f"\n  仅诊断选择器有: {only_diag}")

            # Step 6: 检查 popover 原始结构
            print(f"\nStep 6: 检查 popover DOM 结构")
            popover_info = page.evaluate("""
            (() => {
                const results = [];
                // 所有带 x-placement 的元素
                document.querySelectorAll('[x-placement]').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return;
                    const children = [];
                    el.querySelectorAll('*').forEach(child => {
                        const cr = child.getBoundingClientRect();
                        if (cr.width <= 0 || cr.height <= 0) return;
                        const text = (child.textContent || '').trim().slice(0, 50);
                        if (text && !children.some(c => c.text === text)) {
                            children.push({
                                tag: child.tagName,
                                className: (typeof child.className === 'string' ? child.className : '').slice(0, 80),
                                text: text.slice(0, 30),
                                rect: {x: Math.round(cr.x), y: Math.round(cr.y)},
                            });
                        }
                    });
                    results.push({
                        tag: el.tagName,
                        className: (typeof el.className === 'string' ? el.className : '').slice(0, 100),
                        placement: el.getAttribute('x-placement'),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                        childCount: children.length,
                        firstChildren: children.slice(0, 10),
                    });
                });
                return results;
            })()
            """)
            print(f"  带 x-placement 的元素: {len(popover_info)}")
            for pi in popover_info:
                print(f"    <{pi['tag']}> class='{pi['className'][:60]}' placement={pi['placement']} rect=({pi['rect']['x']},{pi['rect']['y']},{pi['rect']['w']}x{pi['rect']['h']}) children={pi['childCount']}")

            # 关闭
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            page.mouse.click(10, 10)
            page.wait_for_timeout(500)

        # ─── 对比测试: 不 hover，直接全局点击 ───
        print(f"\n{'='*70}")
        print(f"对比: 不做 hover，直接全局搜索 .dropdown-more 并点击")
        print(f"{'='*70}")

        click_result2 = page.evaluate("""
        (() => {
            const dms = document.querySelectorAll('.dropdown-more');
            for (const dm of dms) {
                const rect = dm.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                let hidden = false;
                let p = dm;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn && cn.includes('is-hidden')) { hidden = true; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none' || st.visibility === 'hidden') { hidden = true; break; }
                    p = p.parentElement;
                }
                if (hidden) continue;
                const trigger = dm.querySelector('.el-dropdown-link, .el-popover__reference');
                if (trigger) {
                    trigger.click();
                    return {
                        clicked: true,
                        dmRect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                        tbodyType: dm.closest('.el-table__fixed-right') ? 'fixed-right'
                                  : dm.closest('.el-table__fixed') ? 'fixed'
                                  : dm.closest('.el-table__body-wrapper') ? 'main'
                                  : 'unknown',
                    };
                }
            }
            return {clicked: false};
        })()
        """)
        print(f"  click result: {click_result2}")
        page.wait_for_timeout(2000)

        # 扫描 popover
        no_hover_items = page.evaluate("""
        (() => {
            const items = [];
            document.querySelectorAll('div[x-placement] div.clickClass').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return;
                const text = (el.textContent || '').trim().replace(/\\s*(new|hot)\\s*/gi, '').trim();
                if (!text) return;
                items.push({text, rect: {x: Math.round(rect.x), y: Math.round(rect.y)}});
            });
            return items;
        })()
        """)
        has_tuiding_nh = any('退订' in i['text'] for i in no_hover_items)
        print(f"  popover items: {len(no_hover_items)}, 有退订: {has_tuiding_nh}")
        for item in no_hover_items[:10]:
            tag = " [TUIDING]" if '退订' in item['text'] else ""
            print(f"    '{item['text']}'{tag}")

        browser.close()


if __name__ == "__main__":
    run()
