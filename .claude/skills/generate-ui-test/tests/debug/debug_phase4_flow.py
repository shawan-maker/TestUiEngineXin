"""精确复现 discover_page.py 的多行扫描流程，定位"退订"在哪一步丢失

运行方式：
    PYTHONIOENCODING=utf-8 python tests/debug_phase4_flow.py
"""
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root.parent.parent.parent))

import yaml
from playwright.sync_api import sync_playwright

# Phase 4 使用的选择器
_MENU_SELECTORS = (
    '.el-dropdown-menu .el-dropdown-menu__item, '
    '.el-dropdown-menu li, '
    '.el-popover .el-button, '
    '.el-tooltip__popper .el-button, '
    'div[x-placement] div.el-tooltip.clickClass, '
    'div[x-placement] div.clickClass'
)

# Phase 4 行悬停 JS（完整复制）
_ROW_HOVER_JS = """
(rowIndex) => {
    const buttons = [];
    const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
    const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
    const row = (rowIndex < fixedRows.length) ? fixedRows[rowIndex]
              : (rowIndex < mainRows.length) ? mainRows[rowIndex] : null;
    if (!row) return buttons;
    row.querySelectorAll(
        '.el-button, .ec-button, button, [role="button"], '
        + '.el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, '
        + 'span.el-dropdown-link, .el-dropdown span[style*="cursor"], '
        + '.ec-dropdown span[style*="cursor"]'
    ).forEach(el => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width <= 0 || rect.height <= 0) return;
        if (style.display === 'none' || style.visibility === 'hidden') return;
        const text = (el.textContent || '').trim().slice(0, 100);
        if (!text) return;
        buttons.push({
            text: text,
            tag: el.tagName,
            className: (typeof el.className === 'string' ? el.className : (el.className.baseVal || '')).slice(0, 200),
            disabled: el.classList.contains('is-disabled')
                      || el.getAttribute('aria-disabled') === 'true'
                      || el.hasAttribute('disabled'),
            rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                   w: Math.round(rect.width), h: Math.round(rect.height)},
        });
    });
    return buttons;
}
"""

EXPAND_LABELS = ['更多', 'More', 'more', '...']


def load_config():
    config_path = Path('D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def inject_auth(context, config):
    cookie_str = config.get('cookie', '')
    domain = config.get('cookie_domain', '')
    if cookie_str:
        cookies = []
        for item in cookie_str.split(';'):
            item = item.strip()
            if '=' in item:
                name, value = item.split('=', 1)
                cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': domain,
                    'path': '/',
                })
        if cookies:
            context.add_cookies(cookies)


def run():
    config = load_config()
    url = 'https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm'

    print(f"Target: {url}")
    print("=" * 70)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True, ignore_https_errors=True)
        inject_auth(context, config)
        page = context.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(6000)
        print(f"[OK] Page loaded: {page.url}")
        print(f"viewport: {page.evaluate('[window.innerWidth, window.innerHeight]')}")

        # ── Step 0: 表格基本信息 ──
        print("\n" + "=" * 70)
        print("[Step 0] 表格基本信息")
        print("=" * 70)

        table_info = page.evaluate("""
        (() => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
            const fixedBody = document.querySelector('.el-table__fixed-right');
            const mainBody = document.querySelector('.el-table__body-wrapper');
            // 检查 fixed-right 的祖先链
            let fixedAncestors = [];
            let p = fixedBody;
            while (p && fixedAncestors.length < 5) {
                const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                fixedAncestors.push({tag: p.tagName, class: cn.slice(0, 100)});
                p = p.parentElement;
            }
            // 检查有多少个 tbody 在 fixed-right 中
            const tbodies = fixedBody ? fixedBody.querySelectorAll('tbody') : [];
            const tbodyInfo = Array.from(tbodies).map((tb, idx) => {
                const rows = tb.querySelectorAll('tr');
                const firstRow = rows[0];
                let hidden = false;
                let p = tb;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn.includes('is-hidden')) { hidden = true; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none' || st.visibility === 'hidden') { hidden = true; break; }
                    p = p.parentElement;
                }
                // Check first row's "更多" trigger
                let moreTrigger = null;
                if (firstRow) {
                    firstRow.querySelectorAll('.el-dropdown-link, .el-popover__reference, span.el-dropdown-link').forEach(el => {
                        const t = (el.textContent || '').trim();
                        if (t === '更多' && !moreTrigger) {
                            const rect = el.getBoundingClientRect();
                            moreTrigger = {
                                text: t,
                                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                            };
                        }
                    });
                }
                return {
                    index: idx,
                    rowCount: rows.length,
                    hidden: hidden,
                    parentClass: (typeof tb.parentElement.className === 'string' ? tb.parentElement.className : '').slice(0, 80),
                    firstRowY: firstRow ? Math.round(firstRow.getBoundingClientRect().y) : null,
                    moreTrigger: moreTrigger,
                };
            });
            return {
                fixedRowCount: fixedRows.length,
                mainRowCount: mainRows.length,
                fixedBodyRect: fixedBody ? {
                    x: Math.round(fixedBody.getBoundingClientRect().x),
                    y: Math.round(fixedBody.getBoundingClientRect().y),
                    w: Math.round(fixedBody.getBoundingClientRect().width),
                    h: Math.round(fixedBody.getBoundingClientRect().height),
                } : null,
                fixedAncestors: fixedAncestors,
                tbodyCount: tbodies.length,
                tbodyInfo: tbodyInfo,
            };
        })()
        """)

        print(f"  fixed-right 行数: {table_info['fixedRowCount']}")
        print(f"  main body 行数: {table_info['mainRowCount']}")
        if table_info['fixedBodyRect']:
            r = table_info['fixedBodyRect']
            print(f"  fixed-right body: rect=({r['x']},{r['y']},{r['w']}x{r['h']})")
        print(f"  fixed-right 祖先链:")
        for a in table_info['fixedAncestors']:
            print(f"    <{a['tag']}> class='{a['class'][:80]}'")
        print(f"  fixed-right tbody 数量: {table_info['tbodyCount']}")
        for tb in table_info['tbodyInfo']:
            hidden = "[HIDDEN]" if tb['hidden'] else "[VISIBLE]"
            mt = f"more=({tb['moreTrigger']['rect']['x']},{tb['moreTrigger']['rect']['y']})" if tb['moreTrigger'] else "no-more"
            print(f"    tbody[{tb['index']}]: {hidden} rows={tb['rowCount']} y={tb['firstRowY']} {mt} parent='{tb['parentClass'][:60]}'")

        # ── Step 1: 模拟 discover_page.py 逐行扫描 ──
        print("\n" + "=" * 70)
        print("[Step 1] 模拟 discover_page.py 逐行扫描（hover + expand + scan）")
        print("=" * 70)

        max_rows = min(table_info['fixedRowCount'], 5)  # 前5行
        all_found_buttons = []  # 模拟 discover_page.py 的 all_row_buttons
        tuiding_found_in_row = None

        for i in range(max_rows):
            print(f"\n  --- Row [{i}] ---")

            # 1a: hover（与 discover_page.py 一致）
            try:
                page.evaluate(f"""
                (rowIndex) => {{
                    const mainRows = document.querySelectorAll(
                        '.el-table__body-wrapper > table > tbody > tr');
                    if (rowIndex < mainRows.length) {{
                        mainRows[rowIndex].scrollIntoView(
                            {{block: 'center', inline: 'nearest'}});
                        mainRows[rowIndex].dispatchEvent(
                            new MouseEvent('mouseover', {{bubbles: true}}));
                        mainRows[rowIndex].dispatchEvent(
                            new MouseEvent('mouseenter', {{bubbles: true}}));
                    }}
                    const fixedRows = document.querySelectorAll(
                        '.el-table__fixed-right tbody tr');
                    if (rowIndex < fixedRows.length) {{
                        const fixedRow = fixedRows[rowIndex];
                        fixedRow.dispatchEvent(
                            new MouseEvent('mouseover', {{bubbles: true}}));
                        fixedRow.dispatchEvent(
                            new MouseEvent('mouseenter', {{bubbles: true}}));
                    }}
                }}""", i)
                page.wait_for_timeout(500)
            except Exception as e:
                print(f"  [SKIP] hover error: {e}")
                continue

            # 1b: 行内按钮扫描
            btns = page.evaluate(_ROW_HOVER_JS, i)
            print(f"  行内按钮: {len(btns)} 个")
            for b in btns:
                dis = "[DIS]" if b['disabled'] else ""
                print(f"    {dis} '{b['text']}' <{b['tag']}> rect=({b['rect']['x']},{b['rect']['y']},{b['rect']['w']}x{b['rect']['h']})")

            # 1c: 查找"更多"
            expand_btn = None
            for b in btns:
                if b['text'] in EXPAND_LABELS and not b.get('disabled'):
                    expand_btn = b
                    break

            if not expand_btn:
                print(f"  [SKIP] 无'更多'按钮")
                all_found_buttons.extend(btns)
                continue

            print(f"  [EXPAND] 找到'更多' at ({expand_btn['rect']['x']},{expand_btn['rect']['y']})")

            # 1d: 点击"更多"（使用 discover_page.py 的逻辑：fixed-right 优先 + visibility 检测）
            try:
                click_result = page.evaluate(f"""
                    (() => {{
                        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                        const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
                        // BUG-11: fixed-right 优先
                        const row = ({i} < fixedRows.length) ? fixedRows[{i}]
                                    : (({i} < mainRows.length) ? mainRows[{i}] : null);
                        if (!row) return {{error: 'no row'}};

                        const candidates = [];
                        row.querySelectorAll('.el-button, .ec-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, span.el-dropdown-link, .el-dropdown span[style*="cursor"], .ec-dropdown span[style*="cursor"]').forEach(el => {{
                            const t = (el.textContent || '').trim();
                            if (!{json.dumps(EXPAND_LABELS, ensure_ascii=False)}.includes(t)) return;
                            const rect = el.getBoundingClientRect();

                            // Check visibility - reject hidden subtrees (BUG-14)
                            let hidden = false;
                            let p = el;
                            while (p) {{
                                const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                                if (cn.includes('is-hidden')) {{ hidden = true; break; }}
                                const st = window.getComputedStyle(p);
                                if (st.display === 'none' || st.visibility === 'hidden') {{ hidden = true; break; }}
                                p = p.parentElement;
                            }}

                            candidates.push({{
                                text: t,
                                rect: {{x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}},
                                visible: rect.width > 0 && rect.height > 0 && !hidden,
                                hidden: hidden
                            }});
                        }});

                        // Find first visible
                        let target = null;
                        let targetInfo = null;
                        for (const c of candidates) {{
                            if (c.visible) {{
                                // Re-find the element and click it
                                const fixedRows2 = document.querySelectorAll('.el-table__fixed-right tbody tr');
                                const mainRows2 = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
                                const row2 = ({i} < fixedRows2.length) ? fixedRows2[{i}]
                                            : (({i} < mainRows2.length) ? mainRows2[{i}] : null);
                                const els = row2.querySelectorAll('.el-button, .ec-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, span.el-dropdown-link, .el-dropdown span[style*="cursor"], .ec-dropdown span[style*="cursor"]');
                                for (const el of els) {{
                                    const rect = el.getBoundingClientRect();
                                    if (Math.round(rect.x) === c.rect.x && Math.round(rect.y) === c.rect.y) {{
                                        el.click();
                                        target = el;
                                        targetInfo = c;
                                        break;
                                    }}
                                }}
                                break;
                            }}
                        }}

                        return {{
                            rowSource: row.parentElement?.parentElement?.className?.includes('fixed-right') ? 'fixed' : 'main',
                            candidates: candidates,
                            clicked: targetInfo
                        }};
                    }})()
                """)
                print(f"  [DEBUG] 行来源: {click_result.get('rowSource')}, 候选触发器: {len(click_result.get('candidates', []))}")
                for c in click_result.get('candidates', []):
                    vis = "[VIS]" if c['visible'] else "[HIDDEN]"
                    print(f"    {vis} '{c['text']}' pos=({c['rect']['x']},{c['rect']['y']})")
                if click_result.get('clicked'):
                    print(f"  [CLICK] 点击了: '{click_result['clicked']['text']}' at ({click_result['clicked']['rect']['x']},{click_result['clicked']['rect']['y']})")
                else:
                    print(f"  [NO-CLICK] 没有找到可见触发器")

                # 1e: 等待菜单出现（与 discover_page.py 一致）
                menu_ready = False
                for poll in range(10):
                    page.wait_for_timeout(300)
                    cnt = page.evaluate(f"(sel) => document.querySelectorAll(sel).length", _MENU_SELECTORS)
                    if cnt > 0:
                        menu_ready = True
                        break

                if not menu_ready:
                    print(f"  [SKIP] 菜单未出现")
                    all_found_buttons.extend(btns)
                    continue

                # 1f: 扫描菜单项（与 discover_page.py 完全一致）
                menu_items = page.evaluate("""
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
                                text: text,
                                disabled: el.classList.contains('is-disabled')
                                          || el.getAttribute('aria-disabled') === 'true',
                                row_index: -1,
                                locator: null,
                                is_row_button: true,
                                from_expand: true
                            });
                        });
                        return items;
                    }
                """)

                # 统计
                visible_texts = [m['text'] for m in menu_items]
                has_tuiding = any('退订' in t for t in visible_texts)
                print(f"  菜单项: {len(menu_items)} 个, 有'退订': {has_tuiding}")

                # 只打印前5个和含"退订"的
                for idx, item in enumerate(menu_items[:5]):
                    tag = " [TUIDING]" if '退订' in item['text'] else ""
                    print(f"    [{idx}]{tag} '{item['text']}'")
                if len(menu_items) > 5:
                    print(f"    ... ({len(menu_items) - 5} more)")
                if has_tuiding:
                    for item in menu_items:
                        if '退订' in item['text']:
                            print(f"    [TUIDING FOUND] '{item['text']}' row={i}")
                    tuiding_found_in_row = i

                # 1g: 收集（与 discover_page.py 一致）
                for mi in menu_items:
                    mi['row_index'] = i
                all_found_buttons.extend(menu_items)

                # 1h: 关闭菜单
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                except:
                    pass

            except Exception as e:
                print(f"  [ERR] expand/scan error: {e}")

            all_found_buttons.extend(btns)

        # ── Step 2: 模拟 discover_page.py 去重 ──
        print("\n" + "=" * 70)
        print("[Step 2] 模拟去重逻辑")
        print("=" * 70)

        deduped = {}
        for btn in sorted(all_found_buttons, key=lambda b: (b['text'], b.get('from_expand', False), b.get('row_index', 0))):
            text = btn['text']
            from_expand = btn.get('from_expand', False)
            key = (text, from_expand)
            if key not in deduped:
                deduped[key] = btn
            elif deduped[key].get('disabled') and not btn.get('disabled'):
                deduped[key] = btn

        result = list(deduped.values())
        print(f"  去重前: {len(all_found_buttons)} 项")
        print(f"  去重后: {len(result)} 项")

        tuiding_in_result = any('退订' in b['text'] for b in result)
        print(f"  结果中有'退订': {tuiding_in_result}")

        if tuiding_in_result:
            for b in result:
                if '退订' in b['text']:
                    print(f"    [TUIDING] '{b['text']}' from_expand={b.get('from_expand')} row={b.get('row_index')}")
        else:
            # 检查去重前是否有
            tuiding_before = [b for b in all_found_buttons if '退订' in b['text']]
            if tuiding_before:
                print(f"  [BUG] 去重前有 {len(tuiding_before)} 个'退订'，去重后丢失！")
                for b in tuiding_before:
                    print(f"    '{b['text']}' from_expand={b.get('from_expand')} disabled={b.get('disabled')} row={b.get('row_index')}")
            else:
                print(f"  [ROOT CAUSE] 去重前也没有'退订' — 所有行都没扫描到'退订'！")
                if tuiding_found_in_row is not None:
                    print(f"  [CONTRADICT] 但 Step 1 在 row {tuiding_found_in_row} 找到了'退订'！")

        # ── Step 3: 打印所有 from_expand 项 ──
        print("\n" + "=" * 70)
        print("[Step 3] 去重后 from_expand 项列表")
        print("=" * 70)
        expand_items = [b for b in result if b.get('from_expand')]
        print(f"  from_expand 项: {len(expand_items)} 个")
        for idx, b in enumerate(expand_items):
            tag = " [TUIDING]" if '退订' in b['text'] else ""
            print(f"    [{idx}]{tag} '{b['text']}' row={b.get('row_index')} disabled={b.get('disabled')}")

        print("\n[DIAG] 完成")
        browser.close()


if __name__ == '__main__':
    run()
