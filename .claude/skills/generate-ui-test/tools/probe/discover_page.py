#!/usr/bin/env python3
"""discover_page.py — Phase 4 广撒网探测工具

自动发现列表页所有交互元素（按钮、输入框、下拉框等），遍历点击每个按钮，
检测容器类型，记录容器内元素，生成 discovery_{module}.json。

设计文档: docs/debug/phase3-broad-discovery-and-phase4a-context-matching.md §2

用法:
    python tools/discover_page.py "{url}" \
      --cookie "name=value;..." \
      --module "cloud_question" \
      --output {project}/_probe/discovery_{module}.json
"""

import argparse
import json
import os
import sys
import time
from urllib.parse import urlparse

# Ensure tools/ is on sys.path for cross-module imports
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    import yaml
except ImportError:
    yaml = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from probe.probe_element import (
    parse_cookie, detect_visible_containers,
    _xpath_escape_label, _safe_format, _has_table_context,
    TOKEN_KEYS,
)
from probe.probe_utils import (
    load_knowledge, get_kb_patterns, kb_fallback,
    _detect_rich_text,
    KB_KEY_ALIAS,
)
from core.xpath_utils import inject_hidden_filter, has_hidden_filter, CONTAINER_XPATH
from core.wait_utils import wait_for_dom_stable as _wait_for_dom_stable
from core.element_types import normalize_type as _normalize_type
from core.field_suffixes import EXPAND_LABELS


def _load_framework():
    """从 _probe/framework.json 读取 UI 框架信息"""
    try:
        fw_path = os.path.join(os.path.dirname(_TOOLS_DIR), '_probe', 'framework.json')
        if os.path.exists(fw_path):
            with open(fw_path, 'r', encoding='utf-8') as f:
                return json.load(f).get('framework')
    except Exception:
        pass
    return None


def _detect_page_framework(page):
    """检测当前页面的 UI 框架

    Ant Design 优先：如果检测到 ant-btn 或 ant-table，返回 'ant-design'
    Element UI：如果检测到 el-button 或 el-table，返回 'element-ui'
    其他：返回 None

    :param page: Playwright page
    :return: 'ant-design' | 'element-ui' | None
    """
    try:
        return page.evaluate("""() => {
            // Ant Design: 检查 ant-btn 或 ant-table
            if (document.querySelector('.ant-btn') || document.querySelector('.ant-table')) {
                return 'ant-design';
            }
            // Element UI: 检查 el-button 或 el-table
            if (document.querySelector('.el-button') || document.querySelector('.el-table')) {
                return 'element-ui';
            }
            return null;
        }""")
    except Exception:
        return None


def _get_page_framework(page_data, global_framework=None):
    """获取页面框架：优先页面级，回退全局。

    L1: 页面级框架感知 — 每个页面可以有独立的框架信息。

    Args:
        page_data: 页面数据字典，包含 'framework' 字段
        global_framework: 全局框架（来自 framework.json）

    Returns:
        'ant-design' | 'element-ui' | None
    """
    # 优先：页面级 framework
    page_fw = page_data.get('framework') if isinstance(page_data, dict) else None
    if page_fw:
        return page_fw

    # 回退：全局 framework.json
    if global_framework is None:
        global_framework = _load_framework()

    return global_framework


def _load_fw_selectors(framework=None):
    """Load framework-specific CSS selectors from JSON file.

    Returns dict of selector names → CSS selector strings.
    Falls back to Element UI selectors if framework is unknown.

    :param framework: 'ant-design' | 'element-ui' | None
    :return: dict
    """
    if framework is None:
        framework = _load_framework()

    js_dir = os.path.join(SCRIPT_DIR, 'js')
    if framework == 'ant-design':
        path = os.path.join(js_dir, 'selectors_antd.json')
    else:
        path = os.path.join(js_dir, 'selectors_element.json')

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  [WARN] Failed to load fw selectors from {path}: {e}")
        # Ultimate fallback: Element UI
        fallback = os.path.join(js_dir, 'selectors_element.json')
        if fallback != path:
            try:
                with open(fallback, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def _fw_js(fw_selectors):
    """Generate JS const declaration for fwSelectors injection.

    :param fw_selectors: dict from _load_fw_selectors()
    :return: string like 'const fwSelectors = {...};'
    """
    return f'const fwSelectors = {json.dumps(fw_selectors)};'


def _inject_selectors(js_code, fw_selectors):
    """Prepend const fwSelectors declaration to JS code string.

    :param js_code: original JS code string
    :param fw_selectors: dict of selector names to CSS selector strings
    :return: JS code with fwSelectors prepended
    """
    return f'const fwSelectors = {json.dumps(fw_selectors)};\n' + js_code


# Module-level cache for fwSelectors — set once in discover(), used by all evaluate helpers
_FW_SELECTORS = {}


def _with_fw(js_code):
    """Prepend const fwSelectors declaration to JS code string.

    Uses module-level _FW_SELECTORS cache (set in discover()).
    No-op if _FW_SELECTORS is empty.
    """
    if _FW_SELECTORS:
        return f'const fwSelectors = {json.dumps(_FW_SELECTORS)};\n' + js_code
    return js_code


def _load_js(filename):
    """Load JS code from external file in js/ directory.

    :param filename: filename relative to js/ (e.g., '_discover_common.js')
    :return: JS code string
    """
    path = os.path.join(SCRIPT_DIR, 'js', filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# Container priority for select_priority_container
CONTAINER_TYPE_PRIORITY = ['dialog', 'drawer', 'message-box']

# Page recycling interval — every N buttons, close and recreate page to release memory
PAGE_RECYCLE_INTERVAL = 15
MAX_RETRY_PER_BUTTON = 3    # 每个按钮最多重试次数（容错机制）


# ============================================================================
# Navigation with networkidle fallback (§X)
# ============================================================================

def _navigate_with_fallback(page, url, timeout_ms=10000):
    """Navigate to URL with networkidle, fallback to domcontentloaded on timeout.

    Some systems (eStack) have continuous API polling, causing networkidle to never
    trigger. This helper tries networkidle first (ensures API data is loaded),
    then falls back to domcontentloaded + wait_for_dom_stable for polling systems.
    Also handles "Page crashed" by retrying with domcontentloaded.
    """
    try:
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    except Exception as e:
        err_str = str(e).lower()
        if "timeout" in err_str or "crashed" in err_str or "connection" in err_str:
            reason = 'crash' if 'crashed' in err_str else ('connection' if 'connection' in err_str else 'timeout')
            print(f"    [INFO] networkidle failed ({reason}), fallback to domcontentloaded")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            raise


def _reload_with_fallback(page, timeout_ms=10000):
    """Reload page with networkidle, fallback to domcontentloaded on timeout/crash."""
    try:
        page.reload(wait_until="networkidle", timeout=timeout_ms)
    except Exception as e:
        err_str = str(e).lower()
        if "timeout" in err_str or "crashed" in err_str or "connection" in err_str:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        else:
            raise


def _wait_for_load_state_fallback(page, timeout_ms=10000):
    """Wait for networkidle, fallback to domcontentloaded on timeout/crash."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception as e:
        err_str = str(e).lower()
        if "timeout" in err_str or "crashed" in err_str or "connection" in err_str:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        else:
            raise


# ============================================================================
# XPath filter injection helpers (§9.2 P1-C / P1-A)
# ============================================================================

def _inject_scope_filter(xpath, scope_filter):
    """Append a scope filter (e.g. 'ancestor::tbody' / 'not(ancestor::tbody)')
    to the outermost predicate of a button XPath.

    Injects BEFORE the last ']' so the scope filter lives in the same predicate
    block as the button text match.
    """
    if not scope_filter:
        return xpath
    last_bracket = xpath.rfind(']')
    if last_bracket < 0:
        return xpath + f"[{scope_filter}]"
    return xpath[:last_bracket] + f" and {scope_filter}" + xpath[last_bracket:]


# ============================================================================
# XPath generation from KB templates
# ============================================================================

def _generate_xpath_from_kb(page, elem_type, label, container_type=None, scope_filter=None):
    """Generate XPath using KB templates, verify count==1.

    :param scope_filter: Optional predicate to scope the XPath to a region:
        - 'not(ancestor::tbody)' → toolbar buttons (exclude row buttons)
        - 'ancestor::tbody'      → row buttons only
      Only applied when elem_type == 'button' (§9.2 P1-A).

    :returns: (xpath_str, verified) tuple.
    """
    fmt_vars = {
        'label': label,
        'char1': label[0] if label else '',
        'char2': label[-1] if label else '',
        'tab_name': label,
        'section': label,
        'field_label': label,
        'keyword': label,
        # M4: 全拆字模式（与 probe_utils.py / _case_generator.py 同步）
        'chars_all': " and ".join(f"contains(.,'{c}')" for c in label if c != "'") if label else "",
    }

    patterns = get_kb_patterns(elem_type)

    # D4: input types that need hidden filter injection
    # rich_text reserved for future iframe KB support
    _INPUT_KB_TYPES = {'input-generic', 'el-select', 'el-cascader', 'date-picker', 'textarea-generic', 'rich_text'}

    for pattern in patterns:
        xpath = _safe_format(pattern, fmt_vars)
        if '{' in xpath:
            continue  # unresolved placeholder

        # D4: inject hidden filter for input-type KB templates BEFORE count()
        if elem_type in _INPUT_KB_TYPES and not has_hidden_filter(xpath):
            xpath = inject_hidden_filter(xpath)

        # §9.2 P1-C: button 类型追加 disabled 过滤（使用统一的 inject_hidden_filter）
        if elem_type in ('button', 'table-action-button'):
            xpath = inject_hidden_filter(xpath, elem_type=elem_type)

        # §9.2 P1-A: scope 过滤（toolbar vs row）
        if elem_type in ('button', 'table-action-button') and scope_filter:
            xpath = _inject_scope_filter(xpath, scope_filter)

        # Add container prefix if needed
        if container_type and container_type in CONTAINER_XPATH:
            prefix = CONTAINER_XPATH[container_type]
            full_xpath = prefix + xpath
        else:
            full_xpath = xpath

        # Verify
        try:
            sel = f"xpath={full_xpath}" if not full_xpath.startswith('xpath=') else full_xpath
            count = page.locator(sel).count()
            if count == 1:
                return full_xpath, True
            if count > 1:
                # Wrap with [1]
                wrapped = f"({full_xpath})[1]"
                sel2 = f"xpath={wrapped}"
                count2 = page.locator(sel2).count()
                if count2 == 1:
                    return wrapped, True
        except Exception:
            pass

    return None, False


# ============================================================================
# JS discovery — scan all interactive elements
# ============================================================================

_DISCOVER_JS = _load_js('_discover_common.js')


# ============================================================================
# Cross-origin iframe scanning (M1)
# ============================================================================

def _discover_cross_origin_iframes(page, max_iframes=10):
    """Scan cross-origin iframes using Playwright frame API.

    JS scanning can only access same-origin iframes (contentDocument).
    This function uses page.frames() to enumerate ALL frames including
    cross-origin ones, and evaluates a simplified scan script in each.

    :param page: Playwright Page object
    :param max_iframes: maximum number of iframes to scan (performance guard)
    :returns: dict with 'buttons' and 'inputs' lists
    """
    iframe_elements = {'buttons': [], 'inputs': []}
    main_frame = page.main_frame

    scan_js = """
    () => {
        const results = {buttons: [], inputs: []};
        const isVisible = el => el.offsetParent !== null && el.offsetWidth > 0;

        // 扫描按钮
        document.querySelectorAll('button, [role="button"], ' + fwSelectors.iframeButton)
            .forEach(el => {
                if (!isVisible(el)) return;
                const text = (el.textContent || '').trim();
                if (!text || text.length > 30) return;
                results.buttons.push({text: text, type: 'button', locator: null});
            });

        // 扫描 input/textarea
        document.querySelectorAll('input:not([type="hidden"]), textarea')
            .forEach(el => {
                if (!isVisible(el)) return;
                if (el.closest(fwSelectors.selectExclude) || el.closest(fwSelectors.selectExclude)) return;
                const label = el.getAttribute('placeholder') ||
                              el.getAttribute('aria-label') ||
                              el.getAttribute('name') || '';
                if (!label) return;
                results.inputs.push({
                    label: label,
                    type: el.tagName === 'TEXTAREA' ? 'textarea' : 'input',
                    locator: null
                });
            });

        return results;
    }
    """

    scanned = 0
    for frame in page.frames:
        if frame == main_frame:
            continue
        if scanned >= max_iframes:
            print(f"  [WARN] iframe scan limit reached ({max_iframes}), skipping remaining")
            break

        try:
            result = frame.evaluate(_with_fw(scan_js))
            if not result:
                continue

            # Generate iframe XPath selector (2026-08-07: use DOM attributes, not frame.name)
            # Priority: id > class > name > index
            iframe_selector = None
            try:
                iframe_el = frame.frame_element()
                iframe_id = iframe_el.get_attribute('id')
                if iframe_id:
                    iframe_selector = f'xpath=//iframe[@id="{iframe_id}"]'
                else:
                    iframe_class = iframe_el.get_attribute('class')
                    if iframe_class:
                        iframe_selector = f'xpath=//iframe[@class="{iframe_class}"]'
                    else:
                        iframe_name = iframe_el.get_attribute('name')
                        if iframe_name:
                            iframe_selector = f'xpath=//iframe[@name="{iframe_name}"]'
            except Exception:
                pass

            # Fallback: position-based selector
            if not iframe_selector:
                frame_idx = page.frames.index(frame)
                iframe_selector = f'xpath=(//iframe)[{frame_idx + 1}]'

            # Tag elements with iframe_context [C2]
            for btn in result.get('buttons', []):
                btn['iframe_context'] = iframe_selector
                btn['iframe_index'] = scanned
                btn['is_row_button'] = False
                btn['disabled'] = False
                iframe_elements['buttons'].append(btn)

            for inp in result.get('inputs', []):
                inp['iframe_context'] = iframe_selector
                inp['iframe_index'] = scanned
                iframe_elements['inputs'].append(inp)

            scanned += 1

        except Exception:
            # Frame may have been detached or navigated away
            pass

    return iframe_elements


def discover_all_elements(page, scope_selector=''):
    """Scan all interactive elements on the page via JS.

    :param scope_selector: CSS selector to scope the scan to a container.
        Empty string = full page scan (default).
        E.g. 'div.el-drawer' = only scan inside drawer.
    """
    try:
        js_result = page.evaluate(_with_fw(_DISCOVER_JS), scope_selector)
    except Exception as e:
        print(f"  [WARN] discover JS error: {e}")
        js_result = {'buttons': [], 'inputs': [], 'tabs': [], 'row_buttons': [], 'detail_links': [], 'checkboxes': [], 'menu_items': []}

    # 补充跨域 iframe 扫描
    try:
        iframe_result = _discover_cross_origin_iframes(page)
        js_result['buttons'].extend(iframe_result['buttons'])
        js_result['inputs'].extend(iframe_result['inputs'])
    except Exception as e:
        print(f"  [WARN] cross-origin iframe scan error: {e}")

    return js_result


# D2: Container selectors for scoped scanning
CONTAINER_SELECTORS = {
    'drawer': 'div.el-drawer',
    'dialog': 'div.el-dialog__wrapper:not([style*="display: none"]) .el-dialog',
    'message-box': 'div.el-message-box',
    # Ant Design
    'ant-drawer': 'div.ant-drawer:not(.ant-drawer-hidden)',
    'ant-modal': 'div.ant-modal-root:not([style*="display: none"]) .ant-modal',
}


def _merge_element_scans(scan1, scan2):
    """Merge two element scan results, deduplicating by (text/label, type) key.

    Used by V8a drawer lazy loading: first scan + scroll + second scan → union.
    """
    merged = {}
    for cat in ('buttons', 'inputs', 'tabs', 'row_buttons', 'detail_links', 'checkboxes', 'menu_items'):
        seen = set()
        items = []
        for elem in (scan1.get(cat, []) + scan2.get(cat, [])):
            key = (elem.get('text', elem.get('label', '')), elem.get('type', ''))
            if key not in seen and (key[0] or key[1]):
                seen.add(key)
                items.append(elem)
        merged[cat] = items
    return merged


# ============================================================================
# Button deduplication
# ============================================================================

def deduplicate_buttons(buttons, row_buttons):
    """Deduplicate buttons by text — toolbar and row independently (§9.2 P1-B).

    Toolbar buttons and row buttons are kept as separate lists. A button named
    "编辑" may appear in BOTH lists (one toolbar "编辑" + one row "编辑"), and
    both will be clicked and their containers discovered independently.

    :param buttons: list of toolbar button dicts (from _DISCOVER_JS)
    :param row_buttons: list of row button dicts (from hover scan or _DISCOVER_JS)
    :returns: (toolbar_unique, row_unique) tuple of lists
    """
    toolbar_seen = set()
    toolbar_unique = []
    for btn in buttons:
        text = btn['text']
        if text in toolbar_seen:
            continue
        toolbar_seen.add(text)
        toolbar_unique.append(btn)

    row_seen = set()
    row_unique = []
    for btn in row_buttons:
        text = btn['text']
        if text in row_seen:
            continue
        row_seen.add(text)
        row_unique.append(btn)

    return toolbar_unique, row_unique


# ============================================================================
# Row button discovery with hover (§9.2 P4)
# ============================================================================

_ROW_HOVER_JS = _load_js('_row_hover.js')


def _discover_row_buttons_with_hover(page, hover_delay_ms=300, max_rows=30):
    """Hover each table row and collect row action buttons (§9.2 P4).

    Playwright's native hover() fails on Element UI tables because fixed-column
    overlays (``<div class="cell el-tooltip">``) intercept pointer events and
    trigger actionability check timeouts. We work around this by dispatching
    the mouseover event via JavaScript, which triggers Element UI's
    ``mouseenter`` listener that reveals row-action buttons.

    **Extended behavior**: when a row has a button named "更多" (or similar
    expand-trigger labels), we also click it to reveal the sub-menu and
    collect its child buttons (commonly 编辑/删除/详情 etc.).

    For each <tr> in <tbody>:
      1. scrollIntoView — ensure row is in viewport
      2. dispatch mouseover + mouseenter events via JS
      3. wait 300ms for Element UI animation
      4. evaluate JS to collect visible buttons in that row
      5. if row has a "更多"-type button, click it and scan expanded menu

    Dedup strategy:
      - By text across all rows
      - Prefer the first non-disabled occurrence
      - If first occurrence is disabled, upgrade to later non-disabled row

    :returns: list of unique row button dicts with 'row_index' field
    """
    all_row_buttons = []
    # BUG-11: 检测 fixed-right 列，定向查询避免双 tbody 行数叠加
    # 当 el-table 有 fixed="right" 列时，document.querySelectorAll('tbody tr')
    # 返回主 tbody + fixed-right tbody 的总行数 = 2×实际行数，
    # max_rows=30 截断后迭代全在主 tbody（操作列为空占位），行按钮永远探测不到。
    # Ant Design: 增加 ant-table-fixed-right 检测
    try:
        has_fixed_right = page.locator(".el-table__fixed-right, .ant-table-fixed-right").count() > 0
    except Exception:
        has_fixed_right = False

    try:
        if has_fixed_right:
            # Ant Design: 增加 ant-table-fixed-right 选择器
            row_count = page.locator(".el-table__fixed-right tbody tr, .ant-table-fixed-right tbody tr.ant-table-row").count()
        else:
            # Ant Design: 增加 ant-table-tbody 选择器
            row_count = page.locator("tbody tr, .ant-table-tbody > tr.ant-table-row").count()
    except Exception:
        row_count = 0
    row_count = min(row_count, max_rows)

    if row_count == 0:
        return []

    # EXPAND_LABELS imported from core/field_suffixes.py (shared with Phase 5)

    for i in range(row_count):
        try:
            # BUG-11: 同时 hover 主 tbody 和 fixed-right tbody 的对应行
            # Element UI 的 fixed-column overlay 不自动同步 hover 状态，
            # 必须手动分发事件到两个 tbody 的对应行。
            page.evaluate(_with_fw("""(rowIndex) => {
                const mainRows = document.querySelectorAll(fwSelectors.tableBodyRows);
                if (rowIndex < mainRows.length) {
                    const mainRow = mainRows[rowIndex];
                    mainRow.scrollIntoView({block: 'center', inline: 'nearest'});
                    mainRow.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                    mainRow.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                }
                const fixedRows = document.querySelectorAll(fwSelectors.tableFixedRows);
                if (rowIndex < fixedRows.length) {
                    const fixedRow = fixedRows[rowIndex];
                    fixedRow.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                    fixedRow.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
                }
            }"""), i)
            page.wait_for_timeout(hover_delay_ms)
        except Exception:
            continue
        try:
            btns = page.evaluate(_with_fw(_ROW_HOVER_JS), i)
            # Check if row has an expand trigger (更多)
            expand_btn = None
            for b in btns:
                if b['text'] in EXPAND_LABELS and not b.get('disabled'):
                    expand_btn = b
                    break
            # If expand exists, click it and scan menu items
            if expand_btn:
                try:
                    page.evaluate(_with_fw(f"""
                        ((rowIndex) => {{
                            // Step 1: 行内搜索展开按钮（原有逻辑，兼容其他项目）
                            const fixedRows = document.querySelectorAll(fwSelectors.tableFixedRows);
                            const mainRows = document.querySelectorAll(fwSelectors.tableBodyRows);
                            const row = (rowIndex < fixedRows.length) ? fixedRows[rowIndex]
                                        : ((rowIndex < mainRows.length) ? mainRows[rowIndex] : null);
                            let rowTarget = null;
                            let hasDropdownMore = false;
                            if (row) {{
                                const labels = {json.dumps(list(EXPAND_LABELS), ensure_ascii=False)};
                                row.querySelectorAll(fwSelectors.rowButton + ', button, [role="button"]').forEach(el => {{
                                    const t = (el.textContent || '').trim();
                                    if (!labels.includes(t)) return;
                                    // Visibility filter — skip hidden copies
                                    const rect = el.getBoundingClientRect();
                                    if (rect.width <= 0 || rect.height <= 0) return;
                                    let hidden = false;
                                    let p = el;
                                    while (p) {{
                                        const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                                        if (cn && cn.includes('is-hidden')) {{ hidden = true; break; }}
                                        const st = window.getComputedStyle(p);
                                        if (st.display === 'none' || st.visibility === 'hidden') {{ hidden = true; break; }}
                                        p = p.parentElement;
                                    }}
                                    if (hidden) return;
                                    // Check if inside .dropdown-more component
                                    const dropdownMore = el.closest('.dropdown-more');
                                    if (dropdownMore) {{
                                        hasDropdownMore = true;
                                        // Don't click row-level .dropdown-more triggers — they produce wrong popover
                                    }} else {{
                                        // Not a .dropdown-more — use direct click (original logic)
                                        if (!rowTarget) rowTarget = el;
                                    }}
                                }});
                                // If non-dropdown-more target found, click it directly
                                if (rowTarget) {{ rowTarget.click(); return; }}
                            }}

                            // Step 2: 全局搜索可见 .dropdown-more（popover 是全局的）
                            const dms = document.querySelectorAll('.dropdown-more');
                            for (const dm of dms) {{
                                const rect = dm.getBoundingClientRect();
                                if (rect.width <= 0 || rect.height <= 0) continue;
                                let hidden = false;
                                let p = dm;
                                while (p) {{
                                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                                    if (cn && cn.includes('is-hidden')) {{ hidden = true; break; }}
                                    const st = window.getComputedStyle(p);
                                    if (st.display === 'none' || st.visibility === 'hidden') {{ hidden = true; break; }}
                                    p = p.parentElement;
                                }}
                                if (hidden) continue;
                                const trigger = dm.querySelector(fwSelectors.dropdownLink);
                                if (trigger) {{ trigger.click(); return; }}
                            }}
                        }})({i})
                    """))
                    # 两阶段等待策略:
                    # 阶段1: 等待 el-loading-mask 消失（最多 15s）
                    for _poll in range(50):  # 50 × 300ms = 15s
                        page.wait_for_timeout(300)
                        _loading = page.evaluate(
                            _with_fw("""() => document.querySelectorAll(fwSelectors.loadingMask + ':not([style*="display: none"])').length""")
                        )
                        if _loading == 0:
                            break
                    # 阶段2: 等待菜单项出现（最多 15s）
                    _menu_ready = False
                    # Ant Design: 增加 ant-dropdown-menu 和 ant-dropdown 选择器
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
                    for _poll in range(50):  # 50 × 300ms = 15s
                        page.wait_for_timeout(300)
                        _cnt = page.evaluate(
                            f"""(sel) => document.querySelectorAll(sel).length""",
                            _menu_sel
                        )
                        if _cnt > 0:
                            _menu_ready = True
                            break
                    # Scan newly visible dropdown menu items (Element UI el-dropdown-menu)
                    menu_items = page.evaluate("""
                        () => {
                            const items = [];
                            // Element UI dropdown menu is rendered at body level
                            // Ant Design: 增加 ant-dropdown-menu 和 ant-dropdown 选择器
                            document.querySelectorAll(
                                '.el-dropdown-menu .el-dropdown-menu__item, '
                                + '.el-dropdown-menu li, '
                                + '.el-popover .el-button, '
                                + '.el-tooltip__popper .el-button, '
                                + 'div[x-placement] div.el-tooltip.clickClass, '
                                + 'div[x-placement] div.clickClass, '
                                + '.ant-dropdown-menu .ant-dropdown-menu-item, '
                                + '.ant-dropdown-menu li, '
                                + '.ant-dropdown .ant-dropdown-menu-item'
                            ).forEach(el => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                if (rect.width <= 0 || rect.height <= 0) return;
                                if (style.display === 'none' || style.visibility === 'hidden') return;
                                // Ancestor chain: reject if any ancestor is display:none/hidden
                                let ancestorHidden = false;
                                let ap = el.parentElement;
                                while (ap && ap !== document.body) {
                                    const as = window.getComputedStyle(ap);
                                    if (as.display === 'none' || as.visibility === 'hidden') { ancestorHidden = true; break; }
                                    ap = ap.parentElement;
                                }
                                if (ancestorHidden) return;
                                // 提取直接文本节点，排除子元素（如<span>角标）
                                let text = '';
                                for (const node of el.childNodes) {
                                    if (node.nodeType === 3) { // TEXT_NODE
                                        const t = node.textContent.trim();
                                        if (t) {
                                            text = t;
                                            break;
                                        }
                                    }
                                }
                                text = text.slice(0, 100);
                                if (!text) return;
                                items.push({
                                    text: text,
                                    type: 'dropdown-menu',
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
                    # Tag with current row_index (so click can hover row again)
                    for mi in menu_items:
                        mi['row_index'] = i

                    # 【修复2】菜单仍打开时，批量验证所有菜单项的 locator
                    for mi in menu_items:
                        text_raw = mi.get('text', '')
                        if not text_raw:
                            mi['verified'] = False
                            mi['count'] = 0
                            continue

                        escaped = _xpath_escape_label(text_raw)

                        # Element UI: @x-placement 作用域
                        xpath_el = (
                            f"//*[@x-placement and not(@x-placement='')]"
                            f"//*[contains(text(),'{escaped}')"
                            f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                            f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
                        )

                        # Ant Design: .ant-dropdown 作用域
                        xpath_ant = (
                            f"//div[contains(@class,'ant-dropdown')]"
                            f"//*[contains(text(),'{escaped}')"
                            f" and not(ancestor-or-self::*[contains(@class,'ant-dropdown-hidden')])]"
                        )

                        # 双作用域尝试
                        count_el = 0
                        count_ant = 0
                        try:
                            count_el = page.locator(f"xpath={xpath_el}").count()
                        except Exception:
                            pass
                        if count_el == 0:
                            try:
                                count_ant = page.locator(f"xpath={xpath_ant}").count()
                            except Exception:
                                pass

                        # 选择匹配数 > 0 的作用域
                        if count_el > 0:
                            xpath, count = xpath_el, count_el
                        elif count_ant > 0:
                            xpath, count = xpath_ant, count_ant
                        else:
                            xpath, count = xpath_el, 0

                        verified = (count >= 1)
                        if count > 1:
                            xpath = f"({xpath})[1]"
                            verified = True

                        mi['locator'] = xpath
                        mi['verified'] = verified
                        mi['count'] = count

                    all_row_buttons.extend(menu_items)
                    # Close menu: press Escape
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                    except Exception:
                        pass
                except Exception:
                    pass
            all_row_buttons.extend(btns)
        except Exception:
            continue

    # Dedup: 按 (text, from_expand) 去重，保留 dropdown 内外同名按钮
    deduped = {}
    for btn in sorted(all_row_buttons, key=lambda b: (b['text'], b.get('from_expand', False), b['row_index'])):
        text = btn['text']
        from_expand = btn.get('from_expand', False)
        key = (text, from_expand)
        if key not in deduped:
            deduped[key] = btn
        elif deduped[key].get('disabled') and not btn.get('disabled'):
            deduped[key] = btn

    return list(deduped.values())


# ============================================================================
# URL change detection
# ============================================================================

def check_url_change(page, original_url):
    """Check if page URL has changed (path or hash)."""
    new_url = page.url
    orig = urlparse(original_url)
    curr = urlparse(new_url)
    return curr.path != orig.path or curr.fragment != orig.fragment


# ============================================================================
# Smart wait — wait for container or URL change
# ============================================================================

def wait_for_stable(page, original_url, timeout_ms=8000):
    """After click, wait for container to appear or URL to change (§9.2 P2).

    Accuracy > speed: timeout raised from 5000ms to 8000ms, animation wait
    raised from 500ms to 1000ms, with a second-pass container detection when
    the first pass returned nothing (handles slow Element UI animations).
    """
    container_selector = (
        "div.el-drawer:not([style*='display: none']), "
        "div.el-dialog__wrapper:not([style*='display: none']), "
        "div.el-message-box, "
        # Ant Design
        "div.ant-drawer:not(.ant-drawer-hidden), "
        "div.ant-modal-wrap:not([style*='display: none'])"
    )
    try:
        page.wait_for_selector(container_selector, state='visible', timeout=timeout_ms)
    except Exception:
        pass  # no container or inline action
    page.wait_for_timeout(1000)  # extra 1000ms for animations (§9.2 P2: was 500ms)

    # Second-pass detection (§9.2 P2): slow animations may need more time
    visible = detect_visible_containers(page)
    if not visible:
        page.wait_for_timeout(1000)
        # caller will do its own detect_visible_containers() — this is just
        # to give the animation more time before it does


# ============================================================================
# Container type selection
# ============================================================================

def select_priority_container(visible_containers):
    """Select highest-priority container from visible list."""
    for ct in CONTAINER_TYPE_PRIORITY:
        if ct in visible_containers:
            return ct
    return visible_containers[0] if visible_containers else None


# ============================================================================
# C4: Flexible locator — JS-based reverse XPath from DOM structure
# ============================================================================

_FLEXIBLE_LOCATOR_JS = _load_js('_flexible_locator.js')


# ============================================================================
# Generate locators for discovered elements
# ============================================================================

def _generate_locators_for_elements(page, elements, container_type=None):
    """Generate XPath locators for a list of discovered elements using KB templates.

    Modifies elements in-place, adding 'locator', 'verified', 'count' fields.

    For button elements, scope is applied based on the element's
    ``is_row_button`` flag (§9.2 P1-A):
      - toolbar button (is_row_button=False) → scope='not(ancestor::tbody)'
      - row button (is_row_button=True)      → scope='ancestor::tbody'
    """
    for elem in elements:
        elem_type = elem.get('type', '')
        label = elem.get('label', '') or elem.get('text', '') or elem.get('name', '')

        if not label:
            elem['locator'] = None
            elem['verified'] = False
            elem['count'] = 0
            continue

        # D3: Tab locator branch — tabs have 'name' field, type='tab'
        if elem.get('type') == 'tab':
            escaped = _xpath_escape_label(label)
            xpath = f"//*[contains(text(),'{escaped}') and @role='tab']"
            # D4: Hidden filter for tab fallback path
            if not has_hidden_filter(xpath):
                xpath = inject_hidden_filter(xpath)
            try:
                count = page.locator(f"xpath={xpath}").count()
                verified = (count >= 1)
                if count > 1:
                    xpath = f"({xpath})[1]"
            except Exception:
                verified = False
            elem['locator'] = xpath
            elem['verified'] = verified
            elem['tab_id_attribute'] = 'aria-controls'  # for Phase 6 tab-scoped
            try:
                elem['count'] = page.locator(f"xpath={xpath}").count()
            except Exception:
                elem['count'] = 0
            continue

        # Detail link / clickable text — F-R5
        # MUST be before button check: detail links also have text and type=''
        if elem.get('is_detail_link'):
            escaped = _xpath_escape_label(label)
            if elem.get('has_common_href'):
                # common-href elements: use class-based XPath (works inside and outside table cells)
                xpath = f"//*[contains(@class,'common-href') and contains(.,'{escaped}')]"
            elif container_type and container_type in CONTAINER_XPATH:
                prefix = CONTAINER_XPATH[container_type]
                xpath = f"{prefix}//tbody//td//*[contains(text(),'{escaped}')]"
            else:
                xpath = f"(//tbody//td//*[contains(text(),'{escaped}')])[1]"
            # D4: Hidden filter for detail_link fallback path
            if not has_hidden_filter(xpath):
                xpath = inject_hidden_filter(xpath)
            try:
                count = page.locator(f"xpath={xpath}").count()
                verified = (count >= 1)
                if count > 1:
                    xpath = f"({xpath})[1]" if not xpath.startswith('(') else xpath
                    verified = True
            except Exception:
                verified = False
            elem['locator'] = xpath
            elem['verified'] = verified
            try:
                elem['count'] = page.locator(f"xpath={xpath}").count()
            except Exception:
                elem['count'] = 0
            continue

        # ── from_expand: 更多菜单项在全局 popover 中 ──
        # 使用 @x-placement 作用域，跳过 KB（KB 返回 click-more 而非 click-action）
        # Ant Design: 增加 .ant-dropdown 作用域作为备选
        if elem.get('from_expand') and 'text' in elem:
            # 修改3: 如果探测阶段已验证（修改2），直接复用结果
            if elem.get('locator') and elem.get('verified') is not None:
                continue

            escaped = _xpath_escape_label(label)

            # Element UI: @x-placement 作用域
            xpath_el = (
                f"//*[@x-placement and not(@x-placement='')]"
                f"//*[contains(text(),'{escaped}')"
                f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
            )

            # Ant Design: .ant-dropdown 作用域
            xpath_ant = (
                f"//div[contains(@class,'ant-dropdown')]"
                f"//*[contains(text(),'{escaped}')"
                f" and not(ancestor-or-self::*[contains(@class,'ant-dropdown-hidden')])]"
            )

            # 双作用域尝试：先 Element UI，再 Ant Design
            count_el = 0
            count_ant = 0
            try:
                count_el = page.locator(f"xpath={xpath_el}").count()
            except Exception:
                pass
            if count_el == 0:
                try:
                    count_ant = page.locator(f"xpath={xpath_ant}").count()
                except Exception:
                    pass

            # 选择匹配数 > 0 的作用域
            if count_el > 0:
                xpath, count = xpath_el, count_el
            elif count_ant > 0:
                xpath, count = xpath_ant, count_ant
            else:
                # 两者都未匹配，使用 Element UI 作为默认
                xpath, count = xpath_el, 0

            verified = (count >= 1)
            if count > 1:
                xpath = f"({xpath})[1]"
                verified = True
            elem['locator'] = xpath
            elem['verified'] = verified
            elem['count'] = count
            continue

        # Generate button locator differently
        if elem_type in ('', 'button', 'table-action-button') and 'text' in elem:
            # It's a button
            is_custom = elem.get('is_custom_clickable', False)
            # §9.2 P1-A: scope by is_row_button flag
            if elem.get('is_row_button'):
                scope_filter = 'ancestor::tbody'
            else:
                scope_filter = 'not(ancestor::tbody)'
            xpath, verified = _generate_xpath_from_kb(
                page, elem_type, label, container_type, scope_filter=scope_filter
            )
            if not xpath or is_custom:
                # Fallback: direct XPath with scope filter + disabled filter
                if is_custom:
                    # Custom clickable element (div/span): use class-based XPath
                    # to avoid //* matching ancestor elements like <html>
                    custom_class = elem.get('custom_class', '')
                    if custom_class:
                        # Use first class name for precise matching
                        primary_class = custom_class.split()[0]
                        if container_type and container_type in CONTAINER_XPATH:
                            prefix = CONTAINER_XPATH[container_type]
                            base = f"{prefix}//*[contains(@class,'{primary_class}') and contains(.,'{label}')]"
                        else:
                            base = f"//*[contains(@class,'{primary_class}') and contains(.,'{label}')]"
                    else:
                        # No class info: use tag + text() for precise matching
                        if container_type and container_type in CONTAINER_XPATH:
                            prefix = CONTAINER_XPATH[container_type]
                            base = f"{prefix}//div[contains(text(),'{label}')]"
                        else:
                            base = f"//div[contains(text(),'{label}')]"
                else:
                    # Standard button: use //button
                    if container_type and container_type in CONTAINER_XPATH:
                        prefix = CONTAINER_XPATH[container_type]
                        base = f"{prefix}//button[contains(.,'{label}')]"
                    else:
                        base = f"//button[contains(.,'{label}')]"
                base = _inject_scope_filter(base, scope_filter)
                # D4: Hidden filter + disabled filter for fallback path (bypasses _generate_xpath_from_kb)
                if not has_hidden_filter(base):
                    base = inject_hidden_filter(base, elem_type=elem_type)
                xpath = base
                try:
                    count = page.locator(f"xpath={xpath}").count()
                    verified = (count == 1)
                except Exception:
                    verified = False
                if not verified:
                    try:
                        count = page.locator(f"xpath={xpath}").count()
                        if count > 1:
                            xpath = f"({xpath})[1]"
                            verified = True
                    except Exception:
                        pass
            elem['locator'] = xpath
            elem['verified'] = verified
            try:
                elem['count'] = page.locator(f"xpath={elem['locator']}").count()
            except Exception:
                elem['count'] = 0
            continue

        # rich_text 类型（iframe 内富文本）— §9.2 P3
        if elem_type == 'rich_text':
            # iframe_xpath 由 _pages_writer.py 自动生成
            # 此处仅生成 label-based 占位 locator（供 _fallback 识别）
            if container_type and container_type in CONTAINER_XPATH:
                prefix = CONTAINER_XPATH[container_type]
                xpath = f"{prefix}//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//iframe"
            else:
                xpath = f"//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//iframe"
            try:
                count = page.locator(f"xpath={xpath}").count()
                verified = (count >= 1)
            except Exception:
                verified = False
            elem['locator'] = xpath
            elem['verified'] = verified
            elem['has_iframe'] = True
            elem['recommended_keyword'] = 'frame_fill_value'
            if container_type:
                elem['container_scoped'] = True
                elem['container_type'] = container_type
            try:
                elem['count'] = page.locator(f"xpath={xpath}").count()
            except Exception:
                elem['count'] = 0
            continue

        # For input-like elements, use KB template
        # Unified: normalize_type() replaces local KB_TYPE_MAP + KB_KEY_ALIAS fallback
        kb_type = _normalize_type(elem_type) or 'input-generic'
        xpath, verified = _generate_xpath_from_kb(page, kb_type, label, container_type)

        if not xpath:
            # C4: Try flexible locator before hardcoded fallback
            try:
                flexible = page.evaluate(_with_fw(_FLEXIBLE_LOCATOR_JS), label, elem_type)
                if flexible:
                    xpath = flexible
                    # Inject hidden filter
                    if not has_hidden_filter(xpath):
                        xpath = inject_hidden_filter(xpath)
                    count = page.locator(f"xpath={xpath}").count()
                    verified = (count >= 1)
            except Exception:
                pass

        if not xpath:
            # Hardcoded fallback: generate from label
            # Type guard: menu-item/tab/detail-link don't use input-style fallback
            if elem_type in ('menu-item', 'tab', 'detail-link'):
                elem['locator'] = None
                elem['verified'] = False
                elem['count'] = 0
                elem['fallback_reason'] = f'{elem_type} KB pattern failed, no input fallback'
                continue
            escaped = _xpath_escape_label(label)
            if elem_type == 'textarea':
                # Use //textarea instead of //input
                tag = 'textarea'
            else:
                tag = "input[@class='el-input__inner']"
            if container_type and container_type in CONTAINER_XPATH:
                prefix = CONTAINER_XPATH[container_type]
                xpath = f"{prefix}//*[contains(text(),'{label}')]/following-sibling::*//{tag}"
            else:
                xpath = f"//*[contains(text(),'{label}')]/following-sibling::*//{tag}"
            try:
                count = page.locator(f"xpath={xpath}").count()
                verified = (count == 1)
            except Exception:
                verified = False

        # C3 (D9): textarea→iframe fallback — check if textarea is actually a rich text editor
        if elem_type == 'textarea' and not verified:
            rich_info = _detect_rich_text(page, label)
            if rich_info.get('is_rich_text'):
                elem['type'] = 'rich_text'
                elem['has_iframe'] = rich_info.get('has_iframe', False)
                elem['has_editable'] = rich_info.get('has_editable', False)
                if rich_info.get('iframe_xpath'):
                    xpath = rich_info['iframe_xpath']
                    elem['locator'] = xpath
                elem['recommended_keyword'] = 'frame_fill_value'
                # Re-verify with new locator
                if xpath:
                    try:
                        elem['count'] = page.locator(f"xpath={xpath}").count()
                        verified = (elem['count'] >= 1)
                    except Exception:
                        verified = False

        elem['locator'] = xpath
        elem['verified'] = verified
        if container_type:
            elem['container_scoped'] = True
            elem['container_type'] = container_type
        try:
            elem['count'] = page.locator(f"xpath={xpath}").count()
        except Exception:
            elem['count'] = 0


# ============================================================================
# Main discovery flow
# ============================================================================

def discover(url, cookie, module_name, local_storage_override=None, config_path=None):
    """Main discovery flow.

    1. Navigate to list page
    2. Discover all elements
    3. Deduplicate buttons
    4. Click each button, detect container, discover container elements
    5. Reset by re-visiting URL
    6. Generate XPath locators
    7. Return discovery dict
    """
    # §12.2 改动 2a: URL 解析 — config page_urls 优先
    # V7: 支持多 URL 列表格式
    page_urls_list = []  # [(name, url), ...] for multi-page modules
    if config_path and yaml:
        try:
            with open(config_path, encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            page_urls = cfg.get('page_urls', {})
            # Normalize module name: cloud_question → cloud-question
            norm = module_name.replace('_', '-')
            resolved = page_urls.get(norm) or page_urls.get(module_name)
            if resolved:
                if isinstance(resolved, list):
                    # V7 multi-URL format: [{name: "xx", url: "..."}, ...]
                    for entry in resolved:
                        if isinstance(entry, dict) and 'url' in entry:
                            page_urls_list.append((entry.get('name', ''), entry['url']))
                    if page_urls_list:
                        url = page_urls_list[0][1]  # start with first URL
                        print(f"[Discover] V7: 多页面模块，共 {len(page_urls_list)} 个 URL")
                elif isinstance(resolved, str):
                    print(f"[Discover] URL resolved from config: {url} → {resolved}")
                    url = resolved
        except Exception as e:
            print(f"[WARN] Config load failed: {e}, using CLI URL")

    print(f"\n[Discover] Module: {module_name}")
    print(f"[Discover] URL: {url}")

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage', '--disable-gpu'],
        )
        domain = urlparse(url).hostname
        cookies = parse_cookie(cookie, domain)

        context = browser.new_context(no_viewport=True, ignore_https_errors=True)
        print(f"[INFO] HTTPS certificate errors will be ignored (ignore_https_errors=True)")
        context.add_cookies(cookies)

        # Build localStorage: CLI override + cookie token (cookie wins)
        local_storage = {}
        if local_storage_override:
            try:
                override = json.loads(local_storage_override)
                if isinstance(override, dict):
                    for k, v in override.items():
                        local_storage[str(k)] = str(v)
            except Exception as e:
                print(f"[WARN] --local-storage JSON parse failed: {e}")
        # Cookie token keys override (freshest source)
        for c in cookies:
            if c['name'] in TOKEN_KEYS:
                local_storage[c['name']] = c['value']

        page = context.new_page()

        # 认证注入：先导航到根 URL，手动设置 localStorage，再跳转到目标页面
        # 某些 SPA 会清空 init_script 注入的 localStorage，必须分两步导航
        if local_storage:
            from urllib.parse import urlparse as _urlparse_ls
            parsed_url = _urlparse_ls(url)
            root_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"

            print(f"[Discover] Navigating to root URL first: {root_url}")
            try:
                _navigate_with_fallback(page, root_url, timeout_ms=10000)
            except Exception as e:
                print(f"[WARN] Root URL navigation failed: {e}, continuing to target URL")

            # 手动设置 localStorage
            print(f"[Discover] Setting {len(local_storage)} localStorage keys manually")
            page.evaluate("""(items) => {
                for (let i = 0; i < items.length; i += 2) {
                    localStorage.setItem(items[i], items[i+1]);
                }
            }""", [k for kv in local_storage.items() for k in kv])

            # 验证 localStorage 设置成功
            ls_keys = page.evaluate("() => Object.keys(localStorage)")
            print(f"[Discover] localStorage keys after set: {ls_keys}")

        # Navigate to target URL with networkidle fallback to domcontentloaded
        # Some systems (eStack) have continuous API polling, networkidle never triggers
        _navigate_with_fallback(page, url, timeout_ms=10000)
        _wait_for_dom_stable(page, timeout_ms=4000)
        # Check auth
        if '/login' in page.url or page.url.rstrip('/').endswith('login'):
            print(f"[ERROR] Redirected to login page — cookie invalid/expired")
            return {'module': module_name, 'url': url, 'containers': [], 'auth_error': True}

        # Belt-and-suspenders: ensure localStorage is set after navigation
        if local_storage:
            for k, v in local_storage.items():
                page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        _wait_for_dom_stable(page, timeout_ms=3000, debug=True)  # 等待 DOM 渲染（含表格行）

        # ================================================================
        # Step 0: Detect page-level framework (L1: 页面级框架感知)
        # ================================================================
        page_framework = _detect_page_framework(page)
        if page_framework:
            print(f"[Discover] Page framework detected: {page_framework}")
        else:
            print(f"[Discover] Page framework: unknown (will fallback to global)")

        # S2: Load framework-specific CSS selectors for JS injection
        fw_selectors = _load_fw_selectors(page_framework)
        global _FW_SELECTORS
        _FW_SELECTORS = fw_selectors
        print(f"[Discover] Loaded {len(fw_selectors)} framework selectors")

        # §12.2 改动 2b: baseline URL = 页面加载后的真实 URL
        baseline_url = page.url
        if baseline_url != url:
            print(f"[Discover] Baseline URL differs from input: {url} → {baseline_url}")

        # ================================================================
        # Step 1: List page discovery (toolbar + row via hover)
        # ================================================================
        print(f"\n[Discover] Scanning list page elements...")
        list_elements = discover_all_elements(page)

        # §9.2 P4: row button 用 hover 扫描（替代 JS 的 isVisible 检查）
        print(f"[Discover] Hovering table rows to discover row action buttons...")
        row_buttons_hover = _discover_row_buttons_with_hover(page)
        # Use hover-discovered row buttons (more accurate than JS isVisible)
        list_elements['row_buttons'] = row_buttons_hover

        n_toolbar = len(list_elements['buttons'])
        n_row = len(list_elements['row_buttons'])
        n_inputs = len(list_elements['inputs'])
        n_tabs = len(list_elements['tabs'])
        n_rich = sum(1 for e in list_elements['inputs'] if e.get('type') == 'rich_text')
        print(f"  Found: {n_toolbar} toolbar buttons + {n_row} row buttons, "
              f"{n_inputs} inputs ({n_rich} rich_text/iframe), {n_tabs} tabs")

        # ================================================================
        # Step 2: Deduplicate — toolbar and row independently (§9.2 P1-B)
        # ================================================================
        toolbar_unique, row_unique = deduplicate_buttons(
            list_elements['buttons'],
            list_elements['row_buttons']
        )
        print(f"  After dedup: {len(toolbar_unique)} toolbar + {len(row_unique)} row buttons")

        # ================================================================
        # Step 3: Generate locators for list page elements
        # ================================================================
        print(f"\n[Discover] Generating list page locators...")
        # Toolbar + row buttons share the same generator — scope is chosen
        # per-element based on is_row_button flag (§9.2 P1-A).
        all_list_buttons = toolbar_unique + row_unique
        _generate_locators_for_elements(page, all_list_buttons, container_type=None)
        _generate_locators_for_elements(page, list_elements['inputs'], container_type=None)
        _generate_locators_for_elements(page, list_elements['tabs'], container_type=None)
        # F-R5: generate locators for detail links
        _generate_locators_for_elements(page, list_elements.get('detail_links', []), container_type=None)
        # C5+C6: generate locators for checkboxes and menu items
        _generate_locators_for_elements(page, list_elements.get('checkboxes', []), container_type=None)
        _generate_locators_for_elements(page, list_elements.get('menu_items', []), container_type=None)

        # Build list_page output
        list_page = {
            'buttons': [b for b in all_list_buttons if not b.get('is_row_button')],
            'row_buttons': [b for b in all_list_buttons if b.get('is_row_button')],
            'inputs': list_elements['inputs'],
            'tabs': list_elements['tabs'],
            'detail_links': list_elements.get('detail_links', []),
            'checkboxes': list_elements.get('checkboxes', []),
            'menu_items': list_elements.get('menu_items', []),
        }

        # §12.2 改动 4: 初始化 baseline（用于 case 3 增量 diff）
        baseline = set()
        for cat in ['buttons', 'row_buttons', 'inputs', 'tabs', 'detail_links', 'checkboxes', 'menu_items']:
            for e in list_page.get(cat, []):
                text = e.get('text', e.get('label', ''))
                etype = e.get('type', '')
                baseline.add((text, etype))

        # ================================================================
        # Step 3.5: Tab-scoped element discovery (C9)
        # When page has 2+ tabs, click each and scan within its scope
        # ================================================================
        if len(list_page.get('tabs', [])) >= 2:
            print(f"\n[Discover] === Tab-scoped discovery ({len(list_page['tabs'])} tabs) ===")
            for tab in list_page['tabs']:
                tab_name = tab.get('name', '')
                if not tab_name:
                    continue
                # 1. Click tab
                tab_xpath = f"//*[contains(text(),'{tab_name}') and @role='tab']"
                try:
                    page.locator(f"xpath={tab_xpath}").first.click(timeout=3000)
                    _wait_for_dom_stable(page, timeout_ms=3000)  # tab 面板内容异步渲染
                except Exception as e:
                    print(f"    [WARN] Tab '{tab_name}' click failed: {e}")
                    continue

                # 2. Get aria-controls (tab panel ID)
                tab_id = None
                try:
                    tab_id = page.evaluate(f"""() => {{
                        const tab = document.evaluate("{tab_xpath}", document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        return tab ? tab.getAttribute('aria-controls') : null;
                    }}""")
                except Exception:
                    pass

                # 3. Scan within tab scope
                if tab_id:
                    scope_selector = f'div#{tab_id}'
                    print(f"    [TAB] '{tab_name}' → scope: #{tab_id}")
                    try:
                        tab_elements = discover_all_elements(page, scope_selector)
                        # Mark all elements as belonging to this tab
                        for cat in tab_elements:
                            for elem in tab_elements.get(cat, []):
                                elem['tab_scope'] = tab_name
                                elem['tab_id'] = tab_id
                        tab['tab_elements'] = tab_elements
                        # Generate locators for tab-scoped elements
                        all_tab_elems = []
                        for cat in ('buttons', 'inputs', 'tabs', 'row_buttons',
                                    'detail_links', 'checkboxes', 'menu_items'):
                            all_tab_elems.extend(tab_elements.get(cat, []))
                        if all_tab_elems:
                            _generate_locators_for_elements(page, all_tab_elems, container_type=None)
                            print(f"    -> {len(all_tab_elems)} elements found in tab '{tab_name}'")
                    except Exception as e:
                        print(f"    [WARN] Tab '{tab_name}' scan failed: {e}")
                else:
                    print(f"    [WARN] Tab '{tab_name}' has no aria-controls")

        # ================================================================
        # Step 4: Click each button and discover containers
        # ================================================================
        containers = []

        # F4: Page recycling — close and recreate page every N buttons
        # to release accumulated JS heap / DOM tree memory
        def _recycle_page():
            """Close current page and create a fresh one, re-injecting auth."""
            nonlocal page
            print(f"  [RECYCLE] Closing page and creating fresh context...")
            # F4-extra: 先关闭所有可能残留的新 Tab（防御性清理）
            while len(context.pages) > 1:
                try:
                    context.pages[-1].close()
                except Exception:
                    break
            try:
                page.close()
            except Exception:
                pass
            page = context.new_page()
            # Re-inject cookies (context-level, should persist, but verify)
            context.add_cookies(cookies)
            # 认证注入：先导航到根 URL，手动设置 localStorage，再跳转到 baseline_url
            if local_storage:
                from urllib.parse import urlparse as _urlparse_ls
                parsed_url = _urlparse_ls(baseline_url)
                root_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
                try:
                    _navigate_with_fallback(page, root_url, timeout_ms=10000)
                except Exception as e:
                    print(f"[WARN] Root URL navigation failed: {e}")
                page.evaluate("""(items) => {
                    for (let i = 0; i < items.length; i += 2) {
                        localStorage.setItem(items[i], items[i+1]);
                    }
                }""", [k for kv in local_storage.items() for k in kv])
            # Navigate to baseline URL
            _navigate_with_fallback(page, baseline_url, timeout_ms=10000)
            _wait_for_dom_stable(page, timeout_ms=3000, debug=False)
            print(f"  [RECYCLE] Fresh page ready")

        def _check_browser_health():
            """检查浏览器连接是否正常

            Returns:
                bool: True if connection is healthy, False otherwise
            """
            try:
                # 简单测试：执行 JavaScript 表达式
                page.evaluate("1")
                return True
            except Exception as e:
                print(f"  [WARN] Browser health check failed: {type(e).__name__}")
                return False

        # EXPAND_LABELS imported from core/field_suffixes.py (shared with Phase 5)
        # BUG-12 已解决：模块级导入，_process_button 闭包可直接访问

        def _process_button(btn, is_row=False):
            """Process a single button: click → detect container → discover inside."""
            btn_text = btn['text']
            btn_locator = btn.get('locator')

            if btn.get('disabled'):
                print(f"\n  [SKIP] '{btn_text}' ({'row' if is_row else 'toolbar'}) — disabled")
                containers.append({
                    'trigger': btn_text,
                    'trigger_scope': 'row' if is_row else 'toolbar',
                    'trigger_locator': btn_locator,
                    'result_type': 'skipped',
                    'container_type': None,
                    'elements': [],
                    'skipped': True,
                    'reason': 'button is disabled',
                })
                return

            if not btn_locator:
                print(f"\n  [SKIP] '{btn_text}' ({'row' if is_row else 'toolbar'}) — no locator")
                return

            print(f"\n  [CLICK] '{btn_text}' ({'row' if is_row else 'toolbar'})...")

            # Navigate back to list page before each click
            _navigate_with_fallback(page, baseline_url, timeout_ms=10000)
            # SPA hash 路由不变时 goto 可能不触发全页面重载，
            # reload 强制销毁 Vue app，清除残留 dialog/drawer wrapper
            try:
                _reload_with_fallback(page, timeout_ms=10000)
            except Exception as e:
                # 网络瞬态错误（如 net::ERR_NETWORK_CHANGED）时降级为 goto
                print(f"    [WARN] reload failed ({e}), fallback to goto")
                _navigate_with_fallback(page, baseline_url, timeout_ms=10000)
            _wait_for_dom_stable(page, timeout_ms=3000, debug=True)  # 回到基线页等待 DOM 稳定（含表格行）

            # §9.2 P4: row button 需要绕过 el-table fixed-column overlay
            # Playwright hover()/click() 会被 overlay 拦截 actionability check，
            # 用 dispatchEvent('click') 绕过。
            # 记录点击前的页面数量（用于检测新 Tab）
            pages_count_before = len(page.context.pages)

            if is_row and btn.get('row_index') is not None:
                try:
                    # BUG-11: 定向 tbody + 双 tbody hover（与 _discover_row_buttons_with_hover 对齐）
                    # BUG-12: from_expand 拆为两次 evaluate（与扫描阶段 L757-803 对齐）
                    #   第一次: hover + 展开菜单
                    #   Python wait: 等 Vue 异步渲染菜单 DOM
                    #   第二次: 搜索菜单项 + 点击目标
                    row_idx = btn['row_index']
                    btn_text = btn['text']
                    is_from_expand = btn.get('from_expand', False)

                    if is_from_expand:
                        # ── BUG-12 from_expand 路径（两次 evaluate） ──
                        # 第一次: hover 行 + 点击展开触发器
                        page.evaluate(_with_fw(f"""
                            (() => {{
                                const fixedRows = document.querySelectorAll(fwSelectors.tableFixedRows);
                                const mainRows = document.querySelectorAll(fwSelectors.tableBodyRows);

                                if ({row_idx} < mainRows.length) {{
                                    const mainRow = mainRows[{row_idx}];
                                    mainRow.scrollIntoView({{block: 'center', inline: 'nearest'}});
                                    mainRow.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
                                    mainRow.dispatchEvent(new MouseEvent('mouseenter', {{bubbles: true}}));
                                }}
                                if ({row_idx} < fixedRows.length) {{
                                    const fixedRow = fixedRows[{row_idx}];
                                    fixedRow.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
                                    fixedRow.dispatchEvent(new MouseEvent('mouseenter', {{bubbles: true}}));
                                }}

                                // 优先使用 fixed-right，回退到 main tbody
                                const searchRow = ({row_idx} < fixedRows.length)
                                    ? fixedRows[{row_idx}]
                                    : ({row_idx} < mainRows.length)
                                    ? mainRows[{row_idx}]
                                    : null;

                                if (searchRow) {{
                                    const expandLabels = {json.dumps(list(EXPAND_LABELS), ensure_ascii=False)};
                                    let expandTrigger = null;
                                    searchRow.querySelectorAll(fwSelectors.rowButton + ', button, [role="button"]').forEach(el => {{
                                        const t = (el.textContent || '').trim();
                                        if (expandLabels.includes(t) && !expandTrigger) {{
                                            expandTrigger = el;
                                        }}
                                    }});
                                    if (expandTrigger) expandTrigger.click();
                                }}
                            }})()
                        """))
                        # 两阶段等待策略（与发现阶段一致）:
                        # 阶段1: 等待 el-loading-mask 消失（最多 15s）
                        for _poll in range(50):
                            page.wait_for_timeout(300)
                            _loading = page.evaluate(
                                _with_fw("""() => document.querySelectorAll(fwSelectors.loadingMask + ':not([style*="display: none"])').length""")
                            )
                            if _loading == 0:
                                break
                        # 阶段2: 等待菜单项出现（最多 15s）
                        _menu_sel_expand = _FW_SELECTORS.get('dropdownMenu') if _FW_SELECTORS else (
                            '.el-dropdown-menu .el-dropdown-menu__item, '
                            '.el-dropdown-menu li, '
                            '.el-popover .el-button, '
                            '.el-tooltip__popper .el-button, '
                            'div[x-placement] div.el-tooltip.clickClass, '
                            'div[x-placement] div.clickClass, '
                            '.ant-dropdown-menu .ant-dropdown-menu-item, '
                            '.ant-dropdown-menu li'
                        )
                        for _poll in range(50):
                            page.wait_for_timeout(300)
                            _cnt = page.evaluate(
                                f"""(sel) => document.querySelectorAll(sel).length""",
                                _menu_sel_expand
                            )
                            if _cnt > 0:
                                break

                        # 第二次: 在菜单浮层中搜索目标并点击
                        page.evaluate(_with_fw(f"""
                            (() => {{
                                let target = null;
                                const menuSelectors = fwSelectors.dropdownMenu.split(', ');
                                for (const sel of menuSelectors) {{
                                    if (target) break;
                                    document.querySelectorAll(sel).forEach(el => {{
                                        if (target) return;
                                        const t = (el.textContent || '').trim();
                                        if (t === {json.dumps(btn_text, ensure_ascii=False)}) {{
                                            target = el;
                                        }}
                                    }});
                                }}
                                if (target) target.click();
                                return !!target;
                            }})()
                        """))
                    else:
                        # ── 普通行按钮路径（原有逻辑，单次 evaluate） ──
                        page.evaluate(_with_fw(f"""
                            (() => {{
                                const fixedRows = document.querySelectorAll(fwSelectors.tableFixedRows);
                                const mainRows = document.querySelectorAll(fwSelectors.tableBodyRows);

                                if ({row_idx} < mainRows.length) {{
                                    const mainRow = mainRows[{row_idx}];
                                    mainRow.scrollIntoView({{block: 'center', inline: 'nearest'}});
                                    mainRow.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
                                    mainRow.dispatchEvent(new MouseEvent('mouseenter', {{bubbles: true}}));
                                }}
                                if ({row_idx} < fixedRows.length) {{
                                    const fixedRow = fixedRows[{row_idx}];
                                    fixedRow.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
                                    fixedRow.dispatchEvent(new MouseEvent('mouseenter', {{bubbles: true}}));
                                }}

                                // 优先使用 fixed-right，回退到 main tbody
                                const searchRow = ({row_idx} < fixedRows.length)
                                    ? fixedRows[{row_idx}]
                                    : ({row_idx} < mainRows.length)
                                    ? mainRows[{row_idx}]
                                    : null;

                                let target = null;
                                if (searchRow) {{
                                    searchRow.querySelectorAll(fwSelectors.rowButton + ', button, [role="button"]').forEach(el => {{
                                        const t = (el.textContent || '').trim();
                                        if (t === {json.dumps(btn_text, ensure_ascii=False)}) target = el;
                                    }});
                                }}
                                if (target) target.click();
                                return !!target;
                            }})()
                        """))
                        page.wait_for_timeout(500)
                except Exception as e:
                    print(f"    [WARN] JS click dispatch failed: {str(e)[:80]}")
                    containers.append({
                        'trigger': btn_text,
                        'trigger_scope': 'row',
                        'trigger_locator': btn_locator,
                        'result_type': 'click_failed',
                        'container_type': None,
                        'elements': [],
                        'skipped': True,
                        'reason': f'JS click dispatch failed: {str(e)[:80]}',
                    })
                    return
            else:
                try:
                    # Toolbar button: wait loading mask + scroll + visible + click (V8b + BUG-3 fix)
                    # BUG-3 层1: 等前一次操作（查询/重置）的 loading mask 消失
                    try:
                        page.wait_for_selector(
                            "xpath=//div[contains(@class,'el-loading-mask')]",
                            state='hidden', timeout=10000
                        )
                    except Exception:
                        pass  # loading mask 可能不存在，忽略超时

                    sel = f"xpath={btn_locator}" if not btn_locator.startswith('xpath=') else btn_locator
                    loc = page.locator(sel).first
                    loc.scroll_into_view_if_needed(timeout=3000)
                    loc.wait_for(state='visible', timeout=3000)
                    try:
                        loc.click(timeout=5000)
                    except Exception:
                        # BUG-3 层1 兜底: JS dispatch 绕过 actionability 检查（与行按钮一致）
                        print(f"    [INFO] Playwright click 超时，尝试 JS dispatch 兜底")
                        page.evaluate(f"""
                            (() => {{
                                const el = document.evaluate(
                                    {json.dumps(btn_locator.replace('xpath=', ''))},
                                    document, null, 9, null
                                ).singleNodeValue;
                                if (el) el.click();
                            }})()
                        """)
                        page.wait_for_timeout(500)
                except Exception as e:
                    print(f"    [WARN] Click failed: {str(e)[:100]}")
                    containers.append({
                        'trigger': btn_text,
                        'trigger_scope': 'toolbar',
                        'trigger_locator': btn_locator,
                        'result_type': 'click_failed',
                        'container_type': None,
                        'elements': [],
                        'skipped': True,
                        'reason': f'click failed: {str(e)[:100]}',
                    })
                    return

            # Smart wait (§9.2 P2: 8s timeout + 1s animation + second-pass)
            wait_for_stable(page, url)

            # ===== 新 Tab 检测 =====
            # 检查是否打开了新标签页
            pages_count_after = len(page.context.pages)
            if pages_count_after > pages_count_before:
                # 检测到新 Tab
                new_page = page.context.pages[-1]
                new_tab_url = new_page.url
                new_tab_title = new_page.title()

                # 记录新 Tab 信息
                print(f"    [NEW TAB] 检测到新标签页打开")
                print(f"      URL: {new_tab_url}")
                print(f"      Title: {new_tab_title}")

                # 关闭新 Tab，避免污染后续测试
                new_page.close()

                # 添加到容器列表，标记为新 Tab 类型
                containers.append({
                    'trigger': btn_text,
                    'trigger_scope': 'row' if is_row else 'toolbar',
                    'trigger_locator': btn_locator,
                    'result_type': 'new_tab',
                    'new_tab_url': new_tab_url,
                    'new_tab_title': new_tab_title,
                    'container_type': None,
                    'elements': [],  # 新 Tab 的元素后续单独探测（如果需要）
                })

                # 新 Tab 场景处理完毕，跳过后续的容器/新页面/内联检测
                return

            # Detect result type (原有逻辑)
            is_new_page = check_url_change(page, baseline_url)
            # 3a: detect_visible_containers 重试机制 — 容器动画可能需要额外等待
            visible_containers = None
            for _retry in range(3):
                visible_containers = detect_visible_containers(page)
                if visible_containers:
                    break
                page.wait_for_timeout(500)

            if visible_containers:
                # Container opened
                container_type = select_priority_container(visible_containers)
                print(f"    -> Container: {container_type}")

                # D2: Build container selector for scoped scanning
                # When a drawer/dialog is open, only scan inside that container
                # to avoid toolbar buttons (查询/重置) leaking into container results
                container_selector = CONTAINER_SELECTORS.get(container_type, '')

                # V8a: Scroll + dual scan for lazy-loading (drawer/dialog long forms)
                # Scroll to bottom of container to trigger lazy rendering
                _scroll_container_js = """
                    (() => {
                        const selectors = ['div.el-drawer__body', 'div.el-dialog__body',
                                           'div.el-drawer', 'div.el-dialog'];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetHeight > 0) {
                                el.scrollTo(0, el.scrollHeight);
                                return true;
                            }
                        }
                        window.scrollTo(0, document.body.scrollHeight);
                        return false;
                    })()
                """
                try:
                    page.evaluate(_scroll_container_js)
                except Exception:
                    pass
                _wait_for_dom_stable(page, timeout_ms=3000)  # 容器滚动后等待 DOM 渲染
                scan1 = discover_all_elements(page, container_selector)

                # Second scroll + scan for deeply lazy-loaded fields
                try:
                    page.evaluate(_scroll_container_js)
                except Exception:
                    pass
                _wait_for_dom_stable(page, timeout_ms=3000)  # 二次滚动后等待 DOM 渲染
                scan2 = discover_all_elements(page, container_selector)

                # Merge two scans (union by text+type key)
                container_elements = _merge_element_scans(scan1, scan2)
                new_from_scan2 = (
                    len(container_elements.get('inputs', []))
                    - len(scan1.get('inputs', []))
                )
                if new_from_scan2 > 0:
                    print(f"    -> V8a: scroll 二次扫描发现 {new_from_scan2} 个额外字段")

                all_container_elems = (
                    container_elements['buttons']
                    + container_elements['row_buttons']
                    + container_elements['inputs']
                    + container_elements.get('tabs', [])          # D10 fix
                    + container_elements.get('detail_links', [])  # D10 fix
                    + container_elements.get('checkboxes', [])    # C5
                    + container_elements.get('menu_items', [])    # C6
                )

                # Generate locators with container prefix
                _generate_locators_for_elements(page, all_container_elems, container_type=container_type)

                verified_count = sum(1 for e in all_container_elems if e.get('verified'))
                print(f"    -> Elements: {len(all_container_elems)} ({verified_count} verified)")

                containers.append({
                    'trigger': btn_text,
                    'trigger_scope': 'row' if is_row else 'toolbar',
                    'trigger_locator': btn_locator,
                    'result_type': 'container',
                    'container_type': container_type,
                    'elements': all_container_elems,
                })

            elif is_new_page:
                # Navigation to new page
                new_url = page.url
                print(f"    -> Navigation: {new_url}")

                new_elements = discover_all_elements(page)
                all_new_elems = (
                    new_elements['buttons']
                    + new_elements['row_buttons']
                    + new_elements['inputs']
                    + new_elements.get('tabs', [])          # D10 fix
                    + new_elements.get('detail_links', [])  # D10 fix
                    + new_elements.get('checkboxes', [])    # C5
                    + new_elements.get('menu_items', [])    # C6
                )

                # Generate locators without container prefix (new page)
                _generate_locators_for_elements(page, all_new_elems, container_type=None)

                verified_count = sum(1 for e in all_new_elems if e.get('verified'))
                print(f"    -> Elements: {len(all_new_elems)} ({verified_count} verified)")

                containers.append({
                    'trigger': btn_text,
                    'trigger_scope': 'row' if is_row else 'toolbar',
                    'trigger_locator': btn_locator,
                    'result_type': 'navigation',
                    'container_type': None,
                    'new_url': new_url,
                    'elements': all_new_elems,
                })

            else:
                # §12.2 改动 4: URL 没变 + 没容器 → 重新扫描列表页，增量合入
                _wait_for_dom_stable(page, timeout_ms=3000)  # 等待内联展开动画 + DOM 渲染
                current_elements = discover_all_elements(page)

                # Diff: 按 (text, type) 去重
                new_count = 0
                for cat, field in [('buttons', 'buttons'), ('inputs', 'inputs'),
                                   ('tabs', 'tabs'), ('detail_links', 'detail_links'),
                                   ('checkboxes', 'checkboxes'), ('menu_items', 'menu_items'),
                                   ('row_buttons', 'row_buttons')]:
                    for e in current_elements.get(cat, []):
                        key = (e.get('text', e.get('label', '')), e.get('type', ''))
                        if key not in baseline and (key[0] or key[1]):
                            _generate_locators_for_elements(page, [e], container_type=None)
                            list_page[field].append(e)
                            baseline.add(key)
                            new_count += 1

                if new_count:
                    print(f"    -> Inline: {new_count} new elements merged into list_page")
                else:
                    print(f"    -> Inline: no new elements")

        def _process_detail_link(dl, is_row=False):
            """Process a detail-link: click → detect container/navigation → discover inside.

            与 _process_button 类似，但专门处理 detail-link 类型的元素。
            这些元素通常是表格行中的链接，点击后进入详情页或打开抽屉。
            """
            dl_text = dl['text']
            dl_locator = dl.get('locator')

            if not dl_locator:
                print(f"\n  [SKIP] detail-link '{dl_text}' — no locator")
                return

            print(f"\n  [DETAIL-LINK] '{dl_text}'...")

            # Navigate back to list page before each click
            _navigate_with_fallback(page, baseline_url, timeout_ms=10000)
            _reload_with_fallback(page, timeout_ms=10000)
            _wait_for_dom_stable(page, timeout_ms=3000, debug=True)

            # 记录点击前的页面数量（用于检测新 Tab）
            pages_count_before = len(page.context.pages)

            # Click the detail-link (with JS dispatch fallback like buttons)
            try:
                loc = page.locator(dl_locator)
                if loc.count() == 0:
                    print(f"    [WARN] detail-link not found: {dl_text}")
                    return

                try:
                    loc.first.click(timeout=10000)
                except Exception:
                    # JS dispatch fallback (same as button line 1601-1611)
                    print(f"    [INFO] Playwright click timeout, trying JS dispatch fallback")
                    page.evaluate(f"""
                        (() => {{
                            const el = document.evaluate(
                                {json.dumps(dl_locator.replace('xpath=', ''))},
                                document, null, 9, null
                            ).singleNodeValue;
                            if (el) el.click();
                        }})()
                    """)
                    page.wait_for_timeout(500)

                _wait_for_load_state_fallback(page, timeout_ms=10000)
                _wait_for_dom_stable(page, timeout_ms=3000)
            except Exception as e:
                print(f"    [WARN] click failed: {e}")
                # Recover page state for next button detection
                _navigate_with_fallback(page, baseline_url, timeout_ms=10000)
                _reload_with_fallback(page, timeout_ms=10000)
                _wait_for_dom_stable(page, timeout_ms=3000, debug=True)
                return

            # Detect result type (with retry like button line 1633-1638)
            # ===== 新 Tab 检测 =====
            pages_count_after = len(page.context.pages)
            if pages_count_after > pages_count_before:
                # 检测到新 Tab
                new_page = page.context.pages[-1]
                new_tab_url = new_page.url
                new_tab_title = new_page.title()

                # 记录新 Tab 信息
                print(f"    [NEW TAB] 检测到新标签页打开")
                print(f"      URL: {new_tab_url}")
                print(f"      Title: {new_tab_title}")

                # 关闭新 Tab，避免污染后续测试
                new_page.close()

                # 添加到容器列表，标记为新 Tab 类型
                containers.append({
                    'trigger': dl_text,
                    'trigger_scope': 'detail-link',
                    'trigger_locator': dl_locator,
                    'result_type': 'new_tab',
                    'new_tab_url': new_tab_url,
                    'new_tab_title': new_tab_title,
                    'container_type': None,
                    'elements': [],
                })

                # 新 Tab 场景处理完毕，跳过后续检测
                return

            is_new_page = check_url_change(page, baseline_url)
            visible_containers = None
            for _retry in range(3):
                visible_containers = detect_visible_containers(page)
                if visible_containers:
                    break
                page.wait_for_timeout(500)

            if visible_containers:
                # Container opened
                container_type = select_priority_container(visible_containers)
                container_selector = CONTAINER_SELECTORS.get(container_type)
                print(f"    -> Container opened: {container_type}")

                # V8a: Scroll + dual scan for lazy-loading (same as button line 1650-1689)
                _scroll_container_js = """
                    (() => {
                        const selectors = ['div.el-drawer__body', 'div.el-dialog__body',
                                           'div.el-drawer', 'div.el-dialog'];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetHeight > 0) {
                                el.scrollTo(0, el.scrollHeight);
                                return true;
                            }
                        }
                        window.scrollTo(0, document.body.scrollHeight);
                        return false;
                    })()
                """
                try:
                    page.evaluate(_scroll_container_js)
                except Exception:
                    pass
                _wait_for_dom_stable(page, timeout_ms=3000)
                scan1 = discover_all_elements(page, container_selector)

                # Second scroll + scan for deeply lazy-loaded fields
                try:
                    page.evaluate(_scroll_container_js)
                except Exception:
                    pass
                _wait_for_dom_stable(page, timeout_ms=3000)
                scan2 = discover_all_elements(page, container_selector)

                # Merge two scans
                container_elements = _merge_element_scans(scan1, scan2)
                new_from_scan2 = (
                    len(container_elements.get('inputs', []))
                    - len(scan1.get('inputs', []))
                )
                if new_from_scan2 > 0:
                    print(f"    -> V8a: scroll 二次扫描发现 {new_from_scan2} 个额外字段")

                all_container_elems = (
                    container_elements['buttons']
                    + container_elements['row_buttons']
                    + container_elements['inputs']
                    + container_elements.get('tabs', [])
                    + container_elements.get('detail_links', [])
                    + container_elements.get('checkboxes', [])
                    + container_elements.get('menu_items', [])
                )

                _generate_locators_for_elements(page, all_container_elems, container_type=container_type)

                verified_count = sum(1 for e in all_container_elems if e.get('verified'))
                print(f"    -> Elements: {len(all_container_elems)} ({verified_count} verified)")

                containers.append({
                    'trigger': dl_text,
                    'trigger_scope': 'detail-link',
                    'trigger_locator': dl_locator,
                    'result_type': 'container',
                    'container_type': container_type,
                    'elements': all_container_elems,
                    'source': 'detail_link',
                })

            elif is_new_page:
                # Navigation to new page (detail page)
                new_url = page.url
                print(f"    -> Navigation: {new_url}")

                new_elements = discover_all_elements(page)
                all_new_elems = (
                    new_elements['buttons']
                    + new_elements['row_buttons']
                    + new_elements['inputs']
                    + new_elements.get('tabs', [])
                    + new_elements.get('detail_links', [])
                    + new_elements.get('checkboxes', [])
                    + new_elements.get('menu_items', [])
                )

                _generate_locators_for_elements(page, all_new_elems, container_type=None)

                verified_count = sum(1 for e in all_new_elems if e.get('verified'))
                print(f"    -> Elements: {len(all_new_elems)} ({verified_count} verified)")

                containers.append({
                    'trigger': dl_text,
                    'trigger_scope': 'detail-link',
                    'trigger_locator': dl_locator,
                    'result_type': 'navigation',
                    'container_type': None,
                    'new_url': new_url,
                    'elements': all_new_elems,
                    'source': 'detail_link',
                })

            else:
                # Inline expansion or no change
                _wait_for_dom_stable(page, timeout_ms=3000)
                current_elements = discover_all_elements(page)

                new_count = 0
                for cat, field in [('buttons', 'buttons'), ('inputs', 'inputs'),
                                   ('tabs', 'tabs'), ('detail_links', 'detail_links'),
                                   ('checkboxes', 'checkboxes'), ('menu_items', 'menu_items')]:
                    for e in current_elements.get(cat, []):
                        key = (e.get('text', e.get('label', '')), e.get('type', ''))
                        if key not in baseline and (key[0] or key[1]):
                            _generate_locators_for_elements(page, [e], container_type=None)
                            if not e.get('is_row_button'):
                                list_page[field].append(e)
                            baseline.add(key)
                            new_count += 1

                if new_count:
                    print(f"    -> Inline: {new_count} new elements merged into list_page")
                else:
                    print(f"    -> Inline: no new elements")

        # 4a. Toolbar buttons first (with retry mechanism)
        print(f"\n[Discover] === Toolbar buttons ({len(toolbar_unique)}) ===")
        for i_btn, btn in enumerate(toolbar_unique):
            if i_btn > 0 and i_btn % PAGE_RECYCLE_INTERVAL == 0:
                _recycle_page()

            btn_text = btn.get('text', '?')
            success = False

            for attempt in range(MAX_RETRY_PER_BUTTON):
                try:
                    _process_button(btn, is_row=False)
                    success = True
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if "crashed" in err_str or "connection" in err_str:
                        print(f"  [WARN] Button '{btn_text}' click failed (attempt {attempt+1}/{MAX_RETRY_PER_BUTTON}): {type(e).__name__}")
                        if attempt < MAX_RETRY_PER_BUTTON - 1:
                            try:
                                _recycle_page()
                                if not _check_browser_health():
                                    print(f"  [WARN] Browser connection still unhealthy after recycle, waiting {2 ** (attempt+1)}s...")
                                    time.sleep(2 ** (attempt + 1))
                            except Exception as recycle_err:
                                print(f"  [WARN] Recycle failed (attempt {attempt+1}): {type(recycle_err).__name__}")
                                time.sleep(2 ** attempt)
                        else:
                            print(f"  [ERROR] Button '{btn_text}' failed after {MAX_RETRY_PER_BUTTON} attempts, skip this button")
                    else:
                        raise

            if not success:
                continue

        # 4b. Row buttons second (with retry mechanism)
        print(f"\n[Discover] === Row buttons ({len(row_unique)}) ===")
        for i_btn, btn in enumerate(row_unique):
            if i_btn > 0 and i_btn % PAGE_RECYCLE_INTERVAL == 0:
                _recycle_page()

            btn_text = btn.get('text', '?')
            success = False

            for attempt in range(MAX_RETRY_PER_BUTTON):
                try:
                    _process_button(btn, is_row=True)
                    success = True
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if "crashed" in err_str or "connection" in err_str:
                        print(f"  [WARN] Row button '{btn_text}' click failed (attempt {attempt+1}/{MAX_RETRY_PER_BUTTON}): {type(e).__name__}")
                        if attempt < MAX_RETRY_PER_BUTTON - 1:
                            try:
                                _recycle_page()
                                if not _check_browser_health():
                                    print(f"  [WARN] Browser connection still unhealthy after recycle, waiting {2 ** (attempt+1)}s...")
                                    time.sleep(2 ** (attempt + 1))
                            except Exception as recycle_err:
                                print(f"  [WARN] Recycle failed (attempt {attempt+1}): {type(recycle_err).__name__}")
                                time.sleep(2 ** attempt)
                        else:
                            print(f"  [ERROR] Row button '{btn_text}' failed after {MAX_RETRY_PER_BUTTON} attempts, skip this button")
                    else:
                        raise

            if not success:
                continue

        # Button discovery summary
        toolbar_success = sum(1 for c in containers if c.get('trigger_scope') == 'toolbar' and not c.get('skipped'))
        row_success = sum(1 for c in containers if c.get('trigger_scope') == 'row' and not c.get('skipped'))
        print(f"\n[Discover] Button discovery summary:")
        print(f"  Toolbar: {toolbar_success}/{len(toolbar_unique)} successful")
        print(f"  Row: {row_success}/{len(row_unique)} successful")

        # 4c. Detail links (only first one)
        detail_links = list_page.get('detail_links', [])
        if detail_links:
            print(f"\n[Discover] === Detail links ({len(detail_links)}, clicking first) ===")
            _process_detail_link(detail_links[0], is_row=False)

        # ================================================================
        # Step 5: Build output
        # ================================================================
        result = {
            'module': module_name,
            'url': baseline_url,
            'framework': page_framework,   # L1: 页面级框架
            'list_page': list_page,
            'containers': containers,
        }

        return result

    finally:
        try:
            browser.close()
            context.close()
        except Exception:
            pass
        pw.stop()


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Phase 4 广撒网探测 — 自动发现页面所有交互元素'
    )
    parser.add_argument('url', nargs='?', default=None,
                        help='列表页 URL（可选，--module-urls 时自动忽略）')
    parser.add_argument('--cookie', required=True, help='Cookie 字符串')
    parser.add_argument('--module', required=True, help='模块名 (e.g., cloud_question)')
    parser.add_argument('--output', required=True, help='输出 JSON 路径')
    parser.add_argument('--config', default=None,
                        help='config.yaml 路径（用于 page_urls 解析）')
    parser.add_argument('--module-urls', default=None,
                        help='module_urls.json 路径（自动读取该模块的所有 URL）')
    parser.add_argument('--module-map-file', default=None,
                        help='_probe/module_map.json 路径（中文模块名→slug 翻译）')
    parser.add_argument('--local-storage', default=None,
                        help='额外 localStorage 注入（JSON 对象字符串）')

    args = parser.parse_args()

    # ── 安全守卫：确保至少有一个 URL 来源 ──
    has_url_source = (args.url is not None or args.module_urls or args.config)
    if not has_url_source:
        parser.error('必须提供 url 参数、--module-urls 或 --config 之一')

    # V7: 检测多 URL 列表
    multi_urls = []  # [(name, url), ...]
    _urls_from_module_urls = False  # 标记 URL 来源，防止 config 覆盖

    # 优先级 1: --module-urls
    if args.module_urls:
        try:
            with open(args.module_urls, encoding='utf-8') as f:
                all_module_urls = json.load(f)

            # 加载 module_map（如果有）— 用于 slug→中文名反向查找
            module_map = {}
            if args.module_map_file and os.path.isfile(args.module_map_file):
                with open(args.module_map_file, encoding='utf-8') as f:
                    module_map = json.load(f)

            # 先尝试直接匹配（旧格式：key=slug）
            module_data = all_module_urls.get(args.module, {})
            urls = module_data.get('urls', [])

            # 新格式：key=中文名，需要通过 module_map 反向查找
            if not urls and module_map:
                # 反向映射: slug → [所有中文名]
                slug_to_cn = {}
                for cn, slug in module_map.items():
                    slug_to_cn.setdefault(slug, []).append(cn)
                # 合并当前 slug 对应的所有中文名的 URL
                cn_names = slug_to_cn.get(args.module, [])
                merged_urls = set()
                for cn in cn_names:
                    cn_data = all_module_urls.get(cn, {})
                    merged_urls.update(cn_data.get('urls', []))
                if merged_urls:
                    urls = sorted(merged_urls)
                    print(f"[Discover] --module-map-file: {args.module}"
                          f" ← {cn_names} 合并 {len(urls)} 个 URL")

            if urls:
                for url in urls:
                    name = url.split('/')[-1].split('?')[0]
                    multi_urls.append((name, url))
                print(f"[Discover] --module-urls: {args.module} 有 {len(multi_urls)} 个 URL")
                _urls_from_module_urls = True
        except Exception as e:
            print(f"[WARN] --module-urls 读取失败: {e}", file=sys.stderr)

    # 优先级 2: config.yaml（仅在 --module-urls 无结果时）
    if not multi_urls and args.config and yaml:
        try:
            with open(args.config, encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            page_urls = cfg.get('page_urls', {})
            norm = args.module.replace('_', '-')
            resolved = page_urls.get(norm) or page_urls.get(args.module)
            if isinstance(resolved, list):
                for entry in resolved:
                    if isinstance(entry, dict) and 'url' in entry:
                        multi_urls.append((entry.get('name', ''), entry['url']))
        except Exception:
            pass

    # 优先级 3: CLI positional arg（单 URL）
    if not multi_urls:
        if args.url:
            multi_urls = [('', args.url)]
        else:
            parser.error(f'模块 {args.module} 在 --module-urls 和 config 中均未找到 URL')

    # URL 去重（基于 URL path，忽略 query params）
    seen_urls = set()
    deduped = []
    for name, url in multi_urls:
        base_url = url.split('?')[0]
        if base_url not in seen_urls:
            seen_urls.add(base_url)
            deduped.append((name, url))
    multi_urls = deduped

    if len(multi_urls) > 1:
        # V7 multi-URL: 对每个 URL 独立探测，结果合并到 pages[]
        print(f"[Discover] V7 多页面模式: {len(multi_urls)} 个 URL")
        pages = []
        for idx, (page_name, page_url) in enumerate(multi_urls):
            print(f"\n{'='*60}")
            print(f"[Discover] V7: [{idx+1}/{len(multi_urls)}] {page_name or page_url}")
            print(f"{'='*60}")
            try:
                # 不传 config_path，避免 discover() 内部再次解析列表
                single_result = discover(page_url, args.cookie, args.module,
                                         args.local_storage, config_path=None)
                pages.append({
                    'name': page_name,
                    'url': page_url,
                    'framework': single_result.get('framework'),  # L1: 保留页面级框架
                    'list_page': single_result.get('list_page', {}),
                    'containers': single_result.get('containers', []),
                })
            except Exception as e:
                err_str = str(e).lower()
                if "crashed" in err_str or "connection" in err_str:
                    print(f"[WARN] URL [{idx+1}/{len(multi_urls)}] browser error ({type(e).__name__}), skip and continue")
                    pages.append({
                        'name': page_name,
                        'url': page_url,
                        'framework': None,  # L1: 探测失败时框架未知
                        'list_page': {},
                        'containers': [],
                    })
                else:
                    raise

        # 合并结果
        result = {
            'module': args.module,
            'pages': pages,
            # 向后兼容：顶层保留第一个 URL 的数据
            'url': multi_urls[0][1],
            'framework': pages[0].get('framework'),  # L1: 顶层框架（向后兼容）
            'list_page': pages[0].get('list_page', {}),
            'containers': pages[0].get('containers', []),
        }
    else:
        # 单 URL: 原流程
        # 如果 URL 来自 --module-urls，不传 config 防止覆盖
        if _urls_from_module_urls:
            result = discover(multi_urls[0][1], args.cookie, args.module,
                              args.local_storage, config_path=None)
        else:
            result = discover(args.url or multi_urls[0][1], args.cookie, args.module,
                              args.local_storage, args.config)

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Write output
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Summary — aggregate across all pages for multi-URL
    all_containers = result.get('containers', [])
    all_list_pages = [result.get('list_page', {})]
    if 'pages' in result:
        all_containers = []
        all_list_pages = []
        for p in result['pages']:
            all_containers.extend(p.get('containers', []))
            all_list_pages.append(p.get('list_page', {}))

    n_containers = sum(1 for c in all_containers if c['result_type'] == 'container')
    n_nav = sum(1 for c in all_containers if c['result_type'] == 'navigation')
    n_inline = sum(1 for c in all_containers if c['result_type'] == 'inline')
    n_skip = sum(1 for c in all_containers if c.get('skipped'))

    total_verified = 0
    total_elements = 0
    for c in all_containers:
        for e in c.get('elements', []):
            total_elements += 1
            if e.get('verified'):
                total_verified += 1
    for lp in all_list_pages:
        for cat in ['buttons', 'row_buttons', 'inputs', 'tabs',
                     'detail_links', 'checkboxes', 'menu_items']:
            for e in lp.get(cat, []):
                total_elements += 1
                if e.get('verified'):
                    total_verified += 1

    print(f"\n{'='*60}")
    print(f"[Discover] DONE — {args.module}")
    print(f"  Output: {args.output}")
    if 'pages' in result:
        print(f"  Pages: {len(result['pages'])}")
    print(f"  Containers: {n_containers} | Navigation: {n_nav} | Inline: {n_inline} | Skipped: {n_skip}")
    rate = round(100 * total_verified / max(total_elements, 1), 1)
    print(f"  Elements: {total_elements} total, {total_verified} verified ({rate}%)")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
