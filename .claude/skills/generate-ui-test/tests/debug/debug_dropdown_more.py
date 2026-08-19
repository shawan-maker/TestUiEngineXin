"""诊断 vm/list 页面 dropdown-more 组件中"退订"按钮探测失败的原因

问题：Phase 4 无法探测到 vm/list 页面"更多"菜单中的"退订"按钮
用户提供的可用 locator：
  退订: //div[@x-placement]//div[contains(@class,"clickClass") and contains(.,"退订")]
  更多: //div[@class="dropdown-more" and not(ancestor-or-self::*[contains(@class,'is-hidden')])
        and not(ancestor-or-self::*[contains(@style,'display: none')])]

运行方式：
    PYTHONIOENCODING=utf-8 python tests/debug_dropdown_more.py
"""
import json
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root.parent.parent.parent))

import yaml
from playwright.sync_api import sync_playwright

# ── 与 discover_page.py 完全一致的菜单扫描选择器 ──
_MENU_SELECTORS_DISCOVER = [
    '.el-dropdown-menu .el-dropdown-menu__item',
    '.el-dropdown-menu li',
    '.el-popover .el-button',
    '.el-tooltip__popper .el-button',
    'div[x-placement] div.el-tooltip.clickClass',
    'div[x-placement] div.clickClass',
]
_MENU_SEL_STR = ', '.join(_MENU_SELECTORS_DISCOVER)

# ── 用户提供的 locator ──
USER_XPATH_TUIDING = '//div[@x-placement]//div[contains(@class,"clickClass") and contains(.,"退订")]'
USER_XPATH_MORE = '//div[@class="dropdown-more" and not(ancestor-or-self::*[contains(@class,\'is-hidden\')]) and not(ancestor-or-self::*[contains(@style,\'display: none\')])]'

# ── Phase 4 行按钮扫描 JS（与 discover_page.py 完全一致）──
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
            print(f"[AUTH] Injected {len(cookies)} cookies for domain={domain}")


def run():
    config = load_config()
    vm_list_url = 'http://console-estack-intel.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm'

    print(f"[DIAG] Target URL: {vm_list_url}")
    print("=" * 70)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True)
        inject_auth(context, config)
        page = context.new_page()

        page.goto(vm_list_url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)

        print(f"[OK] Page loaded: {page.url}")

        # ─── Step 1: 检测 dropdown-more 自定义组件 ───
        print("\n" + "=" * 70)
        print("[Step 1] 检测 dropdown-more 自定义组件")
        print("=" * 70)

        dd_more_info = page.evaluate("""
        (() => {
            const getCN = (el) => {
                if (!el.className) return '';
                return (typeof el.className === 'string' ? el.className : (el.className.baseVal || ''));
            };
            const results = [];
            document.querySelectorAll('.dropdown-more, [class*="dropdown-more"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                let ancestors = [];
                let p = el.parentElement;
                let depth = 0;
                while (p && depth < 6) {
                    ancestors.push({
                        tag: p.tagName,
                        class: getCN(p).slice(0, 120),
                        display: window.getComputedStyle(p).display,
                    });
                    p = p.parentElement;
                    depth++;
                }
                let children = [];
                el.querySelectorAll('*').forEach(child => {
                    const cr = child.getBoundingClientRect();
                    if (cr.width > 0 && cr.height > 0) {
                        children.push({
                            tag: child.tagName,
                            text: (child.textContent || '').trim().slice(0, 50),
                            class: getCN(child).slice(0, 150),
                            rect: {x: Math.round(cr.x), y: Math.round(cr.y),
                                   w: Math.round(cr.width), h: Math.round(cr.height)},
                        });
                    }
                });
                const parentDropdown = el.closest('.el-dropdown, .ec-dropdown, .el-popover');
                results.push({
                    tag: el.tagName,
                    class: getCN(el).slice(0, 200),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                    display: style.display,
                    visibility: style.visibility,
                    isInTbody: !!el.closest('tbody'),
                    parentDropdown: parentDropdown ? getCN(parentDropdown).slice(0, 100) : null,
                    parentDropdownTag: parentDropdown ? parentDropdown.tagName : null,
                    ancestors: ancestors,
                    children: children.slice(0, 10),
                });
            });
            return results;
        })()
        """)

        print(f"  找到 {len(dd_more_info)} 个 dropdown-more 元素:")
        for i, dm in enumerate(dd_more_info):
            in_tbody = "tbody内" if dm['isInTbody'] else "tbody外"
            print(f"\n  [{i}] <{dm['tag']}> class='{dm['class']}' {in_tbody}")
            print(f"       rect=({dm['rect']['x']},{dm['rect']['y']},{dm['rect']['w']}x{dm['rect']['h']})")
            print(f"       display={dm['display']} visibility={dm['visibility']}")
            if dm['parentDropdown']:
                print(f"       父级dropdown: <{dm['parentDropdownTag']}> class='{dm['parentDropdown']}'")
            else:
                print(f"       无父级 el-dropdown/ec-dropdown/el-popover")
            print(f"       祖先链:")
            for j, anc in enumerate(dm['ancestors'][:4]):
                print(f"         [{j}] <{anc['tag']}> class='{anc['class'][:80]}' display={anc['display']}")
            print(f"       可见子元素: {len(dm['children'])} 个")
            for child in dm['children'][:5]:
                print(f"         <{child['tag']}> text='{child['text']}' class='{child['class'][:60]}'")

        # ─── Step 2: Phase 4 行悬停扫描能否发现 dropdown-more ───
        print("\n" + "=" * 70)
        print("[Step 2] Phase 4 行悬停 JS 能否扫描到 dropdown-more 内的触发器")
        print("=" * 70)

        # 先 hover 第一行
        page.evaluate("""
        (rowIndex) => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
            if (rowIndex < mainRows.length) {
                mainRows[rowIndex].scrollIntoView({block: 'center', inline: 'nearest'});
                mainRows[rowIndex].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                mainRows[rowIndex].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
            if (rowIndex < fixedRows.length) {
                fixedRows[rowIndex].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                fixedRows[rowIndex].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }
        """, 0)
        page.wait_for_timeout(1000)

        row_btns = page.evaluate(_ROW_HOVER_JS, 0)
        print(f"  Phase 4 行扫描 JS 返回 {len(row_btns)} 个按钮:")
        has_more = False
        for b in row_btns:
            disabled = "[DISABLED]" if b['disabled'] else ""
            print(f"    {disabled} '{b['text']}' <{b['tag']}> class='{b['className'][:80]}' "
                  f"rect=({b['rect']['x']},{b['rect']['y']},{b['rect']['w']}x{b['rect']['h']})")
            if '更多' in b['text'] or 'more' in b['text'].lower():
                has_more = True
        if not has_more:
            print(f"\n  [KEY] '更多' 未出现在行扫描结果中！")
        else:
            print(f"\n  [OK] '更多' 出现在行扫描结果中")

        # ─── Step 3: 尝试展开 dropdown-more 菜单 ───
        print("\n" + "=" * 70)
        print("[Step 3] 尝试展开 dropdown-more 菜单")
        print("=" * 70)

        # 3a: Phase 4 方式
        print("\n  3a: Phase 4 方式 — 行内搜索'更多'并 JS click")
        expand_result = page.evaluate("""
        (() => {
            const expandLabels = ['更多', 'More', 'more', '...'];
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
            const row = (0 < fixedRows.length) ? fixedRows[0]
                      : (0 < mainRows.length) ? mainRows[0] : null;
            if (!row) return {error: 'no row'};
            let target = null;
            row.querySelectorAll(
                '.el-button, .ec-button, button, [role="button"], '
                + '.el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, '
                + 'span.el-dropdown-link, .el-dropdown span[style*="cursor"], '
                + '.ec-dropdown span[style*="cursor"]'
            ).forEach(el => {
                const t = (el.textContent || '').trim();
                if (expandLabels.includes(t) && !target) target = el;
            });
            if (!target) return {error: 'no expand trigger found in row'};
            return {
                found: true,
                tag: target.tagName,
                text: target.textContent.trim(),
                class: (typeof target.className === 'string' ? target.className
                       : (target.className.baseVal || '')).slice(0, 200),
            };
        })()
        """)
        print(f"  结果: {json.dumps(expand_result, ensure_ascii=False)}")

        if expand_result.get('found'):
            # 点击并等待
            page.evaluate("""
            (() => {
                const expandLabels = ['更多', 'More', 'more', '...'];
                const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
                const row = (0 < fixedRows.length) ? fixedRows[0]
                          : (0 < mainRows.length) ? mainRows[0] : null;
                if (!row) return;
                let target = null;
                row.querySelectorAll(
                    '.el-button, .ec-button, button, [role="button"], '
                    + '.el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, '
                    + 'span.el-dropdown-link, .el-dropdown span[style*="cursor"], '
                    + '.ec-dropdown span[style*="cursor"]'
                ).forEach(el => {
                    const t = (el.textContent || '').trim();
                    if (expandLabels.includes(t) && !target) target = el;
                });
                if (target) target.click();
            })()
            """)
            page.wait_for_timeout(1500)

            # 3b: 检查菜单是否出现
            print("\n  3b: 检查菜单浮层是否出现")
            menu_phase4 = page.evaluate(f"(sel) => document.querySelectorAll(sel).length", _MENU_SEL_STR)
            print(f"  Phase 4 菜单选择器匹配数: {menu_phase4}")
            for sel in _MENU_SELECTORS_DISCOVER:
                cnt = page.evaluate(f"(sel) => document.querySelectorAll(sel).length", sel)
                if cnt > 0:
                    print(f"    {sel} => {cnt}")

            # 3c: 扫描所有菜单项（dump 全部 + 专门搜退订）
            print("\n  3c: 扫描展开后的所有菜单项（全量 dump）")
            menu_items = page.evaluate(f"""
            (() => {{
                const items = [];
                document.querySelectorAll('{_MENU_SEL_STR}').forEach(el => {{
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const visible = rect.width > 0 && rect.height > 0
                        && style.display !== 'none' && style.visibility !== 'hidden';
                    const text = (el.textContent || '').trim().slice(0, 100);
                    if (!text) return;
                    items.push({{
                        text: text,
                        tag: el.tagName,
                        class: (typeof el.className === 'string' ? el.className : (el.className.baseVal || '')).slice(0, 150),
                        rect: {{x: Math.round(rect.x), y: Math.round(rect.y),
                                w: Math.round(rect.width), h: Math.round(rect.height)}},
                        display: style.display,
                        visible: visible,
                        matchedBy: [],
                    }});
                }});
                // 标记每个元素被哪个选择器匹配
                const sels = {json.dumps(_MENU_SELECTORS_DISCOVER)};
                items.forEach(item => {{}});  // already matched
                return items;
            }})()
            """)

            visible_items = [i for i in menu_items if i['visible']]
            hidden_items = [i for i in menu_items if not i['visible']]
            print(f"  总数: {len(menu_items)}, 可见: {len(visible_items)}, 隐藏: {len(hidden_items)}")
            print(f"\n  === 全部可见菜单项 ===")
            for idx, item in enumerate(visible_items):
                has_tuiding = '[TUIDING]' if '退订' in item['text'] else ''
                print(f"    [{idx}] {has_tuiding} '{item['text']}' <{item['tag']}> class='{item['class'][:60]}' ({item['rect']['w']}x{item['rect']['h']}) pos=({item['rect']['x']},{item['rect']['y']})")

            tuiding_in_menu = any('退订' in i['text'] for i in visible_items)

            # 3d: 全局搜索"退订"在哪里（不限制选择器）
            print("\n  3d: 全局搜索'退订'（展开菜单后，不限选择器）")
            tuiding_global = page.evaluate("""
            (() => {
                const getCN = (el) => {
                    if (!el.className) return '';
                    return (typeof el.className === 'string' ? el.className : (el.className.baseVal || ''));
                };
                const results = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                while (walker.nextNode()) {
                    const el = walker.currentNode;
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');
                    if (directText !== '退订') continue;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    // 检查祖先链 — 是否有 x-placement
                    let inXPlacement = false;
                    let xPlacementEl = null;
                    let ancestors = [];
                    let p = el;
                    let depth = 0;
                    while (p && depth < 12) {
                        const xp = p.getAttribute ? p.getAttribute('x-placement') : null;
                        if (xp) { inXPlacement = true; xPlacementEl = p; }
                        if (p !== el) {
                            ancestors.push({
                                tag: p.tagName,
                                class: getCN(p).slice(0, 120),
                                display: window.getComputedStyle(p).display,
                                xplacement: xp || '',
                                rect: {w: Math.round(p.getBoundingClientRect().width),
                                       h: Math.round(p.getBoundingClientRect().height)},
                            });
                        }
                        p = p.parentElement;
                        depth++;
                    }
                    results.push({
                        tag: el.tagName,
                        text: directText,
                        class: getCN(el).slice(0, 200),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                        display: style.display,
                        visibility: style.visibility,
                        inXPlacement: inXPlacement,
                        xPlacementParentClass: xPlacementEl ? getCN(xPlacementEl).slice(0, 150) : null,
                        ancestors: ancestors,
                    });
                }
                return results;
            })()
            """)

            print(f"  全局找到 '退订' 叶子元素: {len(tuiding_global)} 个:")
            for i, el in enumerate(tuiding_global):
                vis = "[VIS]" if el['rect']['w'] > 0 else "[HIDDEN]"
                xp = "[IN x-placement]" if el['inXPlacement'] else "[NOT in x-placement]"
                print(f"\n    [{i}] {vis} {xp} <{el['tag']}> class='{el['class'][:80]}'")
                print(f"        rect=({el['rect']['x']},{el['rect']['y']},{el['rect']['w']}x{el['rect']['h']}) display={el['display']}")
                if el['xPlacementParentClass']:
                    print(f"        x-placement parent: class='{el['xPlacementParentClass']}'")
                print(f"        祖先链:")
                for j, anc in enumerate(el['ancestors'][:8]):
                    xp_tag = f" x-placement={anc['xplacement']}" if anc['xplacement'] else ""
                    print(f"          [{j}] <{anc['tag']}> class='{anc['class'][:80]}'{xp_tag} ({anc['rect']['w']}x{anc['rect']['h']})")

            if not tuiding_in_menu:
                print(f"\n  [KEY] '退订' 在 x-placement 浮层中但未匹配 Phase 4 选择器！")
                # 检查"退订"元素是否被 clickClass 选择器覆盖
                for el in tuiding_global:
                    if el['rect']['w'] > 0 and el['inXPlacement']:
                        has_clickclass = 'clickClass' in el['class']
                        is_div = el['tag'] == 'DIV'
                        print(f"        退订元素: <{el['tag']}> class='{el['class']}', hasClickClass={has_clickclass}, isDiv={is_div}")

        # ─── Step 4: 验证用户提供的 locator ───
        print("\n" + "=" * 70)
        print("[Step 4] 验证用户提供的 locator")
        print("=" * 70)

        try:
            user_cnt = page.evaluate(
                f"(xp) => {{ const r = document.evaluate(xp, document, null, 0, null); let c = 0; while(r.iterateNext()) c++; return c; }}",
                USER_XPATH_TUIDING)
            print(f"  用户 locator (退订) count={user_cnt}")
        except Exception as e:
            print(f"  [FAIL] {e}")

        try:
            dm_cnt = page.evaluate(
                f"(xp) => {{ const r = document.evaluate(xp, document, null, 0, null); let c = 0; while(r.iterateNext()) c++; return c; }}",
                USER_XPATH_MORE)
            print(f"  dropdown-more locator count={dm_cnt}")
        except Exception as e:
            print(f"  dropdown-more locator: {e}")

        # ─── Step 5: 全局扫描所有含"退订"文字的元素 ───
        print("\n" + "=" * 70)
        print("[Step 5] 全局扫描所有含'退订'文字的元素")
        print("=" * 70)

        all_tuiding = page.evaluate("""
        (() => {
            const getCN = (el) => {
                if (!el.className) return '';
                return (typeof el.className === 'string' ? el.className : (el.className.baseVal || ''));
            };
            const results = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
            while (walker.nextNode()) {
                const el = walker.currentNode;
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                const text = (el.textContent || '').trim();
                if (directText === '退订' || (el.children.length === 0 && text === '退订')) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    let ancestors = [];
                    let p = el.parentElement;
                    let depth = 0;
                    while (p && depth < 8) {
                        ancestors.push({
                            tag: p.tagName,
                            class: getCN(p).slice(0, 120),
                            display: window.getComputedStyle(p).display,
                            xplacement: p.getAttribute('x-placement') || '',
                        });
                        p = p.parentElement;
                        depth++;
                    }
                    results.push({
                        tag: el.tagName,
                        text: text.slice(0, 60),
                        directText: directText.slice(0, 60),
                        class: getCN(el).slice(0, 200),
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                        display: style.display,
                        visibility: style.visibility,
                        isInTbody: !!el.closest('tbody'),
                        ancestors: ancestors,
                    });
                }
            }
            return results;
        })()
        """)

        print(f"  找到 {len(all_tuiding)} 个 '退订' 元素:")
        for i, el in enumerate(all_tuiding):
            in_tbody = "tbody内" if el['isInTbody'] else "tbody外"
            vis = "[VIS]" if el['rect']['w'] > 0 else "[HIDDEN]"
            print(f"\n  [{i}] {vis} <{el['tag']}> text='{el['directText']}' class='{el['class'][:80]}' {in_tbody}")
            print(f"       rect=({el['rect']['x']},{el['rect']['y']},{el['rect']['w']}x{el['rect']['h']})")
            print(f"       display={el['display']} visibility={el['visibility']}")
            for j, anc in enumerate(el['ancestors'][:6]):
                xp = f" x-placement={anc['xplacement']}" if anc['xplacement'] else ""
                print(f"         [{j}] <{anc['tag']}> class='{anc['class'][:80]}'{xp} display={anc['display']}")

        # ─── Step 6: 分析 dropdown-more 弹出浮层的 DOM 结构 ───
        print("\n" + "=" * 70)
        print("[Step 6] 分析 dropdown-more 弹出浮层的 DOM 结构")
        print("=" * 70)

        dm_popper_analysis = page.evaluate("""
        (() => {
            const getCN = (el) => {
                if (!el.className) return '';
                return (typeof el.className === 'string' ? el.className : (el.className.baseVal || ''));
            };
            const poppers = [];
            const candidates = document.querySelectorAll(
                '.el-popover, .el-tooltip__popper, .el-dropdown-menu, '
                + '[x-placement], [class*="dropdown-more"], [class*="popper"]'
            );
            candidates.forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return;
                const cn = getCN(el);
                let hasTuiding = false;
                let tuidingEl = null;
                el.querySelectorAll('*').forEach(child => {
                    if ((child.textContent || '').trim() === '退订') {
                        hasTuiding = true;
                        tuidingEl = child;
                    }
                });
                poppers.push({
                    tag: el.tagName,
                    class: cn.slice(0, 200),
                    xplacement: el.getAttribute('x-placement') || '',
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                    hasTuiding: hasTuiding,
                    tuidingTag: tuidingEl ? tuidingEl.tagName : null,
                    tuidingClass: tuidingEl ? getCN(tuidingEl).slice(0, 150) : null,
                    matchesPhase4: {
                        'el-dropdown-menu__item': !!el.querySelector('.el-dropdown-menu__item'),
                        'el-dropdown-menu li': !!el.querySelector('.el-dropdown-menu li'),
                        'el-popover .el-button': !!el.querySelector('.el-button') && cn.includes('el-popover'),
                        'el-tooltip__popper .el-button': !!el.querySelector('.el-button') && cn.includes('el-tooltip__popper'),
                        'div.clickClass': !!el.querySelector('div.clickClass'),
                        'div.el-tooltip.clickClass': !!el.querySelector('div.el-tooltip.clickClass'),
                    },
                });
            });
            return poppers;
        })()
        """)

        print(f"  可见浮层容器: {len(dm_popper_analysis)} 个")
        for popper in dm_popper_analysis:
            tuiding = " [HAS TUIDING]" if popper['hasTuiding'] else ""
            print(f"\n    <{popper['tag']}> class='{popper['class'][:100]}'{tuiding}")
            print(f"    x-placement={popper['xplacement']} rect=({popper['rect']['x']},{popper['rect']['y']},{popper['rect']['w']}x{popper['rect']['h']})")
            if popper['hasTuiding']:
                print(f"    退订元素: <{popper['tuidingTag']}> class='{popper['tuidingClass']}'")
            phase4_matches = [k for k, v in popper['matchesPhase4'].items() if v]
            if phase4_matches:
                print(f"    Phase 4 匹配: {phase4_matches}")
            else:
                print(f"    Phase 4 匹配: [NONE]")

        # ─── 总结 ───
        print("\n" + "=" * 70)
        print("[总结]")
        print("=" * 70)
        print(f"  1. dropdown-more 元素数量: {len(dd_more_info)}")
        print(f"  2. dropdown-more 在 tbody 内: {any(d['isInTbody'] for d in dd_more_info) if dd_more_info else 'N/A'}")
        print(f"  3. Phase 4 行扫描能找到'更多': {has_more}")
        print(f"  4. 展开菜单后包含'退订': {tuiding_in_menu if 'tuiding_in_menu' in dir() else 'N/A'}")
        print(f"  5. 用户 locator 能找到'退订': {user_cnt if 'user_cnt' in dir() else 'N/A'}")

        has_unmatched = any(
            not any(v for v in p['matchesPhase4'].values())
            for p in dm_popper_analysis if p['hasTuiding']
        )
        if has_unmatched:
            print(f"\n  [ROOT CAUSE] dropdown-more 弹出的退订浮层不被 Phase 4 菜单选择器覆盖！")
        elif not has_more:
            print(f"\n  [ROOT CAUSE] Phase 4 行扫描 JS 无法发现 dropdown-more 中的'更多'触发器！")
        elif 'tuiding_in_menu' in dir() and not tuiding_in_menu:
            print(f"\n  [ROOT CAUSE] 当前行状态不支持退订（可能需要运行中的实例）")

        print("\n[DIAG] 完成")
        browser.close()


if __name__ == '__main__':
    run()
