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
from urllib.parse import urlparse

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
sys.path.insert(0, SCRIPT_DIR)

from probe_element import (
    parse_cookie, detect_visible_containers,
    _xpath_escape_label, _safe_format, _has_table_context,
)
from probe_utils import (
    load_knowledge, get_kb_patterns, kb_fallback,
    _detect_rich_text,
    KB_KEY_ALIAS,
)
from xpath_utils import inject_hidden_filter, has_hidden_filter, CONTAINER_XPATH
from _wait_utils import wait_for_dom_stable as _wait_for_dom_stable
from _element_types import normalize_type as _normalize_type

# Token keys for cookie -> localStorage auto-sync
TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'auth_token', 'jwt_token'}

# Container priority for select_priority_container
CONTAINER_TYPE_PRIORITY = ['dialog', 'drawer', 'message-box']


# ============================================================================
# XPath filter injection helpers (§9.2 P1-C / P1-A)
# ============================================================================

def _inject_button_disabled_filter(xpath):
    """Append disabled filter to button XPath (D5: self + ancestor check).

    Injects BEFORE the last ']' (the outermost predicate), so the disabled
    filter is combined with the original button predicate in a single
    predicate block.

    Checks both:
      - not(contains(@class,'is-disabled')) — element itself
      - not(ancestor::*[contains(@class,'is-disabled')]) — ancestor chain
    """
    disabled_check = (
        "not(contains(@class,'is-disabled'))"
        " and not(ancestor::*[contains(@class,'is-disabled')])"
    )
    last_bracket = xpath.rfind(']')
    if last_bracket < 0:
        # no predicate — add one
        return xpath + f"[{disabled_check}]"
    return xpath[:last_bracket] + f" and {disabled_check}" + xpath[last_bracket:]


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

        # §9.2 P1-C: button 类型全局追加 is-disabled 过滤
        if elem_type == 'button':
            xpath = _inject_button_disabled_filter(xpath)

        # §9.2 P1-A: scope 过滤（toolbar vs row）
        if elem_type == 'button' and scope_filter:
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

_DISCOVER_JS = """
(scopeSelector) => {
    const results = { buttons: [], inputs: [], tabs: [], row_buttons: [], detail_links: [], checkboxes: [], menu_items: [] };

    // D2: scope to container DOM subtree, or full document
    let root;
    if (scopeSelector) {
        const candidates = document.querySelectorAll(scopeSelector);
        const visible = Array.from(candidates).filter(el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0
                && s.display !== 'none'
                && s.visibility !== 'hidden';
        });
        if (visible.length === 0) {
            return results;
        } else if (visible.length === 1) {
            root = visible[0];
        } else {
            // Multiple visible same-type containers → pick the one with most form fields
            root = visible.sort((a, b) =>
                b.querySelectorAll('input,select,textarea,.el-select,.el-cascader,.el-date-editor').length
                - a.querySelectorAll('input,select,textarea,.el-select,.el-cascader,.el-date-editor').length
            )[0];
        }
    } else {
        root = document;
    }
    if (!root) return results;

    function findAssociatedLabel(input) {
        function cleanLabel(t) {
            return t.trim().replace(/^\\s*[*＊]\\s*|\\s*[*＊]\\s*$/g, '');
        }

        // ── Route 1: .el-form-item → .el-form-item__label ──
        const formItem = input.closest('.el-form-item');
        if (formItem) {
            const lbl = formItem.querySelector('.el-form-item__label');
            if (lbl) return cleanLabel(lbl.textContent);
        }

        // ── Route 2: textarea special handling ──
        if (input.tagName === 'TEXTAREA') {
            // Route 2a: .el-textarea wrapper → previousElementSibling
            // Symmetric with input Route 3 (.el-input → previousElementSibling)
            const textareaWrap = input.closest('.el-textarea');
            if (textareaWrap) {
                const prev = textareaWrap.previousElementSibling;
                if (prev) {
                    const text = prev.textContent.trim();
                    if (text.length >= 1 && text.length <= 30) return cleanLabel(text);
                }
            }
            // Route 2b: walk up 8 levels to find .el-form-item → .el-form-item__label
            let parent = input.parentElement;
            let depth = 0;
            while (parent && depth < 8) {
                const fi = parent.closest ? parent.closest('.el-form-item') : null;
                if (fi) {
                    const lbl = fi.querySelector('.el-form-item__label');
                    if (lbl) return cleanLabel(lbl.textContent);
                }
                parent = parent.parentElement;
                depth++;
            }
        }

        // ── Route 3: .el-input → previousElementSibling ──
        const prev = input.closest('.el-input')?.previousElementSibling;
        if (prev) return cleanLabel(prev.textContent);

        // ── Fallback: placeholder ──
        return input.getAttribute('placeholder') || '';
    }

    function getText(el) {
        return (el.textContent || '').trim().slice(0, 100);
    }

    function isDisabled(el) {
        if (el.disabled || el.classList.contains('is-disabled')
            || el.getAttribute('aria-disabled') === 'true') return true;
        // D5: ancestor check (up to 5 levels)
        let parent = el.parentElement, depth = 0;
        while (parent && depth < 5) {
            if (parent.classList.contains('is-disabled')) return true;
            if (parent.getAttribute('aria-disabled') === 'true') return true;
            parent = parent.parentElement; depth++;
        }
        return false;
    }

    function isVisible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0
            && style.display !== 'none'
            && style.visibility !== 'hidden';
    }

    // D7+D8: noise filter functions
    function isBreadcrumb(el) {
        return !!el.closest('.el-breadcrumb, .breadcrumb, [class*="breadcrumb"]');
    }
    function isTopNav(el) {
        return el.getBoundingClientRect().top < 60;
    }
    function isUserDropdown(el) {
        return !!el.closest('.el-dropdown, .user-info, .header-right, [class*="user"]');
    }

    // C7: Button subtype detection
    function getButtonSubtype(el) {
        if (el.querySelector('.el-icon-search') || /搜.*索|查.*询/.test(el.textContent))
            return 'search-button';
        if (el.querySelector('.el-icon-download') || /导出|下载/.test(el.textContent))
            return 'download-button';
        return 'button';
    }

    // 1. Buttons (excluding row buttons — toolbar scope)
    root.querySelectorAll('button.el-button, button, [role="button"]').forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('tbody')) return;  // skip row buttons here
        if (!scopeSelector) {
            // D7+D8: only filter noise on full-page scan (not container-scoped)
            if (isBreadcrumb(el)) return;
            if (isTopNav(el)) return;
            if (isUserDropdown(el)) return;
        }
        const text = getText(el);
        if (!text) return;
        results.buttons.push({
            text: text,
            type: getButtonSubtype(el),  // C7: button subtype
            disabled: isDisabled(el),
            locator: null,  // will be generated by KB
            is_row_button: false  // §9.2 P1-A: mark as toolbar
        });
    });

    // 1b. Clickable custom elements (divs/spans acting as buttons)
    // Catches non-standard interactive elements like div.flex-item, div.card-item etc.
    root.querySelectorAll(
        'div.flex-item, div.card-item, div.action-item, '
        + 'div[class*="btn-"], div[class*="-btn"], '
        + 'span[class*="btn-"], span[class*="-btn"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('tbody')) return;  // skip row scope
        if (!scopeSelector) {
            if (isBreadcrumb(el)) return;
            if (isTopNav(el)) return;
            if (isUserDropdown(el)) return;
        }
        const text = getText(el);
        if (!text || text.length > 30) return;  // skip overly long text
        // Avoid duplicates with standard buttons already collected
        const alreadyExists = results.buttons.some(b => b.text === text);
        if (alreadyExists) return;
        results.buttons.push({
            text: text,
            type: getButtonSubtype(el),
            disabled: false,
            locator: null,
            is_row_button: false,
            is_custom_clickable: true,  // mark as non-standard button
            custom_class: el.className || ''  // preserve class for precise XPath
        });
    });

    // 2. Inputs (excluding el-select, el-date, el-cascader)
    root.querySelectorAll('input.el-input__inner:not([type="hidden"])').forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('.el-select') || el.closest('.el-date-editor') || el.closest('.el-cascader')) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'input', locator: null });
    });

    // 3. el-select
    root.querySelectorAll('.el-select .el-input__inner').forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'el-select', locator: null });
    });

    // 4. textarea — Fix-3: 拓宽选择器，不依赖 class（el-textarea__inner 在某些版本不存在）
    root.querySelectorAll('textarea').forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'textarea', locator: null });
    });

    // 4b. iframe 内富文本编辑器（TinyMCE / UEditor / Quill）— §9.2 P3
    root.querySelectorAll('iframe').forEach(iframe => {
        try {
            const doc = iframe.contentDocument;
            if (!doc) return;
            // 跨域 iframe：contentDocument 为 null 或访问抛异常，都走 catch
            const editables = doc.querySelectorAll(
                '[contenteditable="true"], body.mce-content-body, body.ql-editor'
            );
            editables.forEach(el => {
                // 反向推导 label: 从 iframe 在主 frame 的父级找最近的 .el-form-item__label
                let label = '';
                let parent = iframe.parentElement;
                let depth = 0;
                while (parent && depth < 8) {
                    const formItem = parent.closest
                        ? parent.closest('.el-form-item')
                        : null;
                    if (formItem) {
                        const lbl = formItem.querySelector('.el-form-item__label');
                        if (lbl) {
                            label = lbl.textContent.trim().replace(/^\\s*[*＊]\\s*|\\s*[*＊]\\s*$/g, '');
                            break;
                        }
                    }
                    parent = parent.parentElement;
                    depth++;
                }
                if (!label) return;  // 找不到 label 的跳过
                results.inputs.push({
                    label: label,
                    type: 'rich_text',
                    locator: null,
                    has_iframe: true,
                    recommended_keyword: 'frame_fill_value'
                });
            });
        } catch (e) {
            // cross-origin iframe — 静默跳过
        }
    });

    // 5. date picker
    root.querySelectorAll('.el-date-editor input').forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'date_picker', locator: null });
    });

    // 6. cascader
    root.querySelectorAll('.el-cascader .el-input__inner').forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'el-cascader', locator: null });
    });

    // 7. Tabs (D3: add type='tab' marker)
    root.querySelectorAll('[role="tab"]').forEach(el => {
        if (!isVisible(el)) return;
        const name = getText(el);
        results.tabs.push({ name: name, type: 'tab', locator: null });
    });

    // 8. Row buttons (inside tbody) — C7: all typed as table-action-button
    //    Fix-2: 增加 el-dropdown 内 span 按钮（"更多"展开菜单等）
    root.querySelectorAll('tbody .el-button, tbody button, tbody .el-dropdown span.el-dropdown-link, tbody .el-dropdown span[style*="cursor"]').forEach(el => {
        if (!isVisible(el)) return;
        const text = getText(el);
        if (!text) return;
        results.row_buttons.push({
            text: text,
            type: 'table-action-button',  // C7: tbody buttons are table-actions
            disabled: isDisabled(el),
            locator: null,
            is_row_button: true
        });
    });

    // 9. Detail links / clickable text inside table cells — F-R5
    //    These are used for detail navigation (e.g., clicking a title to view details)
    if (!results.detail_links) results.detail_links = [];
    const seenDetailLinks = new Set();
    // 9a: Inside table cells (a, cursor:pointer, .link, .common-href, + precise classes)
    root.querySelectorAll([
        'tbody td a',
        'tbody td [style*="cursor: pointer"]',
        'tbody td .link',
        'tbody td .common-href',
        'tbody td .link-style',
        'tbody td .click-list',
        'tbody td .resource-id',
        'tbody td .edit-name'
    ].join(', ')).forEach(el => {
        if (!isVisible(el)) return;
        const text = getText(el);
        if (!text || text.length > 50) return;  // skip empty or overly long text
        // Dedup by text content (only first occurrence per unique text)
        if (seenDetailLinks.has(text)) return;
        seenDetailLinks.add(text);
        results.detail_links.push({
            text: text,
            locator: null,
            is_detail_link: true,
            has_common_href: el.classList.contains('common-href')  // D6 detail_link enhancement
        });
    });
    // 9b: .common-href outside table cells (e.g., list items, cards)
    root.querySelectorAll('.common-href').forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('tbody td')) return;  // already handled in 9a
        const text = getText(el);
        if (!text || text.length > 50) return;
        if (seenDetailLinks.has(text)) return;
        seenDetailLinks.add(text);
        results.detail_links.push({
            text: text,
            locator: null,
            is_detail_link: true,
            has_common_href: true
        });
    });

    // 10. Checkboxes (el-table) — C5
    const checkboxResults = [];
    root.querySelectorAll('.el-checkbox__inner').forEach(el => {
        if (!isVisible(el)) return;
        const isHeader = !!el.closest('.el-table__header-wrapper');
        const isBody = !!el.closest('.el-table__body-wrapper');
        if (!isHeader && !isBody) return;  // skip non-table checkboxes
        checkboxResults.push({
            type: isHeader ? 'checkbox-all' : 'checkbox',
            name: isHeader ? '批量全选' : '第1行选择框',
            label: isHeader ? '批量全选' : '第1行选择框',
            locator: null,
            row_index: isBody ? 0 : -1
        });
    });
    // Dedup: one header checkbox, one body checkbox
    const seenCheckbox = new Set();
    results.checkboxes = checkboxResults.filter(c => {
        const key = c.type;
        if (seenCheckbox.has(key)) return false;
        seenCheckbox.add(key);
        return true;
    });

    // 11. Sidebar menu items — C6
    results.menu_items = [];
    root.querySelectorAll('.el-menu-item').forEach(el => {
        if (!isVisible(el)) return;
        const text = getText(el);
        if (!text) return;
        results.menu_items.push({
            type: 'menu-item',
            name: text,
            label: text,
            locator: null
        });
    });

    return results;
}
"""


def discover_all_elements(page, scope_selector=''):
    """Scan all interactive elements on the page via JS.

    :param scope_selector: CSS selector to scope the scan to a container.
        Empty string = full page scan (default).
        E.g. 'div.el-drawer' = only scan inside drawer.
    """
    try:
        return page.evaluate(_DISCOVER_JS, scope_selector)
    except Exception as e:
        print(f"  [WARN] discover JS error: {e}")
        return {'buttons': [], 'inputs': [], 'tabs': [], 'row_buttons': [], 'detail_links': [], 'checkboxes': [], 'menu_items': []}


# D2: Container selectors for scoped scanning
CONTAINER_SELECTORS = {
    'drawer': 'div.el-drawer',
    'dialog': 'div.el-dialog__wrapper:not([style*="display: none"]) .el-dialog',
    'message-box': 'div.el-message-box',
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

_ROW_HOVER_JS = """
(rowIndex) => {
    const buttons = [];
    // BUG-11: 搜索双 tbody — fixed-right 优先（操作按钮在这里），主 tbody 补充
    const rowSelectors = [
        '.el-table__fixed-right tbody tr',
        '.el-table__body-wrapper > table > tbody > tr'
    ];
    for (const sel of rowSelectors) {
        const rows = document.querySelectorAll(sel);
        if (rowIndex >= rows.length) continue;
        const row = rows[rowIndex];
        if (!row) continue;
        // Fix-2: 增加 el-dropdown span（hover 展开的"更多"菜单按钮）
        row.querySelectorAll('.el-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .el-dropdown span[style*="cursor"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            // Relaxed visibility: only reject truly hidden elements (§9.2 P4 fix)
            // — accept opacity<1, transform-hidden (Element UI row-action pattern)
            if (rect.width <= 0 || rect.height <= 0) return;
            if (style.display === 'none' || style.visibility === 'hidden') return;
            const text = (el.textContent || '').trim().slice(0, 100);
            if (!text) return;
            // D5: Enhanced isDisabled with 5-level ancestor check (matches _DISCOVER_JS)
            let isDisabled = el.disabled || el.classList.contains('is-disabled')
                             || el.getAttribute('aria-disabled') === 'true';
            if (!isDisabled) {
                let p = el.parentElement;
                let depth = 0;
                while (p && depth < 5) {
                    if (p.classList && p.classList.contains('is-disabled')) {
                        isDisabled = true;
                        break;
                    }
                    p = p.parentElement;
                    depth++;
                }
            }
            buttons.push({
                text: text,
                type: 'table-action-button',  // C7: 与 _DISCOVER_JS 对齐
                disabled: isDisabled,
                row_index: rowIndex,
                locator: null,
                is_row_button: true
            });
        });
    }
    return buttons;
}
"""


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
    try:
        has_fixed_right = page.locator(".el-table__fixed-right").count() > 0
    except Exception:
        has_fixed_right = False

    try:
        if has_fixed_right:
            row_count = page.locator(".el-table__fixed-right tbody tr").count()
        else:
            row_count = page.locator("tbody tr").count()
    except Exception:
        row_count = 0
    row_count = min(row_count, max_rows)

    if row_count == 0:
        return []

    # "更多"-style expand trigger labels
    EXPAND_LABELS = {'更多', '操作', '...', '⋯', '更多操作'}

    for i in range(row_count):
        try:
            # BUG-11: 同时 hover 主 tbody 和 fixed-right tbody 的对应行
            # Element UI 的 fixed-column overlay 不自动同步 hover 状态，
            # 必须手动分发事件到两个 tbody 的对应行。
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
            }""", i)
            page.wait_for_timeout(hover_delay_ms)
        except Exception:
            continue
        try:
            btns = page.evaluate(_ROW_HOVER_JS, i)
            # Check if row has an expand trigger (更多)
            expand_btn = None
            for b in btns:
                if b['text'] in EXPAND_LABELS and not b.get('disabled'):
                    expand_btn = b
                    break
            # If expand exists, click it and scan menu items
            if expand_btn:
                try:
                    page.evaluate(f"""
                        (() => {{
                            // BUG-11: 定向 tbody — fixed-right 优先
                            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                            const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
                            const row = ({i} < fixedRows.length) ? fixedRows[{i}]
                                        : (({i} < mainRows.length) ? mainRows[{i}] : null);
                            if (!row) return;
                            let target = null;
                            row.querySelectorAll('.el-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .el-dropdown span[style*="cursor"]').forEach(el => {{
                                const t = (el.textContent || '').trim();
                                if ({json.dumps(list(EXPAND_LABELS), ensure_ascii=False)}.includes(t)) target = el;
                            }});
                            if (target) target.click();
                        }})()
                    """)
                    page.wait_for_timeout(500)
                    # Scan newly visible dropdown menu items (Element UI el-dropdown-menu)
                    menu_items = page.evaluate("""
                        () => {
                            const items = [];
                            // Element UI dropdown menu is rendered at body level
                            document.querySelectorAll(
                                '.el-dropdown-menu .el-dropdown-menu__item, '
                                + '.el-dropdown-menu li, '
                                + '.el-popover .el-button, '
                                + '.el-tooltip__popper .el-button'
                            ).forEach(el => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                if (rect.width <= 0 || rect.height <= 0) return;
                                if (style.display === 'none' || style.visibility === 'hidden') return;
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
                    # Tag with current row_index (so click can hover row again)
                    for mi in menu_items:
                        mi['row_index'] = i
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

    # Dedup: 按 text 去重，优先取 row_index 最小且非 disabled 的
    deduped = {}
    for btn in sorted(all_row_buttons, key=lambda b: (b['text'], b['row_index'])):
        text = btn['text']
        if text not in deduped:
            deduped[text] = btn
        elif deduped[text].get('disabled') and not btn.get('disabled'):
            deduped[text] = btn

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
        "div.el-message-box"
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

_FLEXIBLE_LOCATOR_JS = """
(label, elemType) => {
    // Determine target elements by type
    let targets;
    switch(elemType) {
        case 'el-select':
            targets = document.querySelectorAll('.el-select .el-input__inner');
            break;
        case 'textarea':
            targets = document.querySelectorAll('textarea.el-textarea__inner');
            break;
        case 'date_picker':
        case 'date-picker':
            targets = document.querySelectorAll('.el-date-editor input');
            break;
        case 'el-cascader':
            targets = document.querySelectorAll('.el-cascader .el-input__inner');
            break;
        case 'menu-item':
        case 'tab':
        case 'detail-link':
            // These types don't use input-based locator strategy
            return null;
        default:
            targets = document.querySelectorAll('input.el-input__inner:not([type="hidden"])');
    }

    for (const el of targets) {
        // Strategy 1: via el-form-item label
        const formItem = el.closest('.el-form-item');
        if (formItem) {
            const lbl = formItem.querySelector('.el-form-item__label');
            if (lbl && lbl.textContent.trim().includes(label)) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className;
                return "//*[contains(text(),'" + label + "')]//following-sibling::*[self::div or self::span]//"
                    + tag + "[@class='" + cls + "']";
            }
        }

        // Strategy 2: via placeholder
        const ph = el.getAttribute('placeholder');
        if (ph && ph.includes(label)) {
            return "//*[@placeholder='" + ph + "']";
        }

        // Strategy 3: via nearest text-bearing ancestor
        let parent = el.parentElement;
        let depth = 0;
        while (parent && depth < 6) {
            const text = parent.textContent?.trim();
            if (text && text.includes(label) && text.length < 50) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className;
                return "//*[contains(text(),'" + label + "')]//" + tag + "[@class='" + cls + "']";
            }
            parent = parent.parentElement;
            depth++;
        }
    }
    return null;  // unable to generate
}
"""


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

        # Generate button locator differently
        if elem_type in ('', 'button') and 'text' in elem:
            # It's a button
            is_custom = elem.get('is_custom_clickable', False)
            # §9.2 P1-A: scope by is_row_button flag
            if elem.get('is_row_button'):
                scope_filter = 'ancestor::tbody'
            else:
                scope_filter = 'not(ancestor::tbody)'
            xpath, verified = _generate_xpath_from_kb(
                page, 'button', label, container_type, scope_filter=scope_filter
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
                    base = _inject_button_disabled_filter(base)
                base = _inject_scope_filter(base, scope_filter)
                # D4: Hidden filter for fallback path (bypasses _generate_xpath_from_kb)
                if not has_hidden_filter(base):
                    base = inject_hidden_filter(base)
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
                flexible = page.evaluate(_FLEXIBLE_LOCATOR_JS, label, elem_type)
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
        browser = pw.chromium.launch(headless=True)
        domain = urlparse(url).hostname
        cookies = parse_cookie(cookie, domain)

        context = browser.new_context(no_viewport=True)
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
        # Navigate once, inject localStorage, then reload
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_dom_stable(page, timeout_ms=4000)  # 初始页面加载等待 DOM 渲染
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_dom_stable(page, timeout_ms=4000)  # 重载后等待 DOM 稳定
        # Check auth
        if '/login' in page.url or page.url.rstrip('/').endswith('login'):
            print(f"[ERROR] Redirected to login page — cookie invalid/expired")
            return {'module': module_name, 'url': url, 'containers': [], 'auth_error': True}

        # Inject localStorage
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        # Re-navigate to apply localStorage
        page.goto(url, wait_until="networkidle", timeout=30000)
        _wait_for_dom_stable(page, timeout_ms=3000, debug=True)  # networkidle 后等待 DOM 渲染（含表格行）

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

        # BUG-12: EXPAND_LABELS 必须在 discover() 作用域内定义
        # （_discover_row_buttons_with_hover 内的同名变量不在 _process_button 的闭包中）
        EXPAND_LABELS = {'更多', '操作', '...', '⋯', '更多操作'}

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
            page.goto(baseline_url, wait_until="networkidle", timeout=30000)
            # SPA hash 路由不变时 goto 可能不触发全页面重载，
            # reload 强制销毁 Vue app，清除残留 dialog/drawer wrapper
            page.reload(wait_until="networkidle", timeout=30000)
            _wait_for_dom_stable(page, timeout_ms=3000, debug=True)  # 回到基线页等待 DOM 稳定（含表格行）

            # §9.2 P4: row button 需要绕过 el-table fixed-column overlay
            # Playwright hover()/click() 会被 overlay 拦截 actionability check，
            # 用 dispatchEvent('click') 绕过。
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
                        page.evaluate(f"""
                            (() => {{
                                const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                                const mainRows = document.querySelectorAll(
                                    '.el-table__body-wrapper > table > tbody > tr');
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
                                const searchRow = ({row_idx} < fixedRows.length)
                                    ? fixedRows[{row_idx}]
                                    : (({row_idx} < mainRows.length) ? mainRows[{row_idx}] : null);
                                if (searchRow) {{
                                    const expandLabels = {json.dumps(list(EXPAND_LABELS), ensure_ascii=False)};
                                    let expandTrigger = null;
                                    searchRow.querySelectorAll(
                                        '.el-button, button, [role="button"], '
                                        + '.el-dropdown span.el-dropdown-link, '
                                        + '.el-dropdown span[style*="cursor"]'
                                    ).forEach(el => {{
                                        const t = (el.textContent || '').trim();
                                        if (expandLabels.includes(t) && !expandTrigger) {{
                                            expandTrigger = el;
                                        }}
                                    }});
                                    if (expandTrigger) expandTrigger.click();
                                }}
                            }})()
                        """)
                        # Python 级等待: Vue nextTick 异步渲染菜单 DOM
                        page.wait_for_timeout(800)

                        # 第二次: 在菜单浮层中搜索目标并点击
                        page.evaluate(f"""
                            (() => {{
                                let target = null;
                                const menuSelectors = [
                                    '.el-dropdown-menu .el-dropdown-menu__item',
                                    '.el-dropdown-menu li',
                                    '.el-popover .el-button',
                                    '.el-tooltip__popper .el-button'
                                ];
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
                        """)
                    else:
                        # ── 普通行按钮路径（原有逻辑，单次 evaluate） ──
                        page.evaluate(f"""
                            (() => {{
                                const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                                const mainRows = document.querySelectorAll(
                                    '.el-table__body-wrapper > table > tbody > tr');
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
                                const searchRow = ({row_idx} < fixedRows.length)
                                    ? fixedRows[{row_idx}]
                                    : (({row_idx} < mainRows.length) ? mainRows[{row_idx}] : null);
                                let target = null;
                                if (searchRow) {{
                                    searchRow.querySelectorAll('.el-button, button, [role=\"button\"], .el-dropdown span.el-dropdown-link, .el-dropdown span[style*=\"cursor\"]').forEach(el => {{
                                        const t = (el.textContent || '').trim();
                                        if (t === {json.dumps(btn_text, ensure_ascii=False)}) target = el;
                                    }});
                                }}
                                if (target) target.click();
                                return !!target;
                            }})()
                        """)
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

            # Detect result type
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

        # 4a. Toolbar buttons first
        print(f"\n[Discover] === Toolbar buttons ({len(toolbar_unique)}) ===")
        for btn in toolbar_unique:
            _process_button(btn, is_row=False)

        # 4b. Row buttons second
        print(f"\n[Discover] === Row buttons ({len(row_unique)}) ===")
        for btn in row_unique:
            _process_button(btn, is_row=True)

        # ================================================================
        # Step 5: Build output
        # ================================================================
        result = {
            'module': module_name,
            'url': baseline_url,
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
            # 不传 config_path，避免 discover() 内部再次解析列表
            single_result = discover(page_url, args.cookie, args.module,
                                     args.local_storage, config_path=None)
            pages.append({
                'name': page_name,
                'url': page_url,
                'list_page': single_result.get('list_page', {}),
                'containers': single_result.get('containers', []),
            })

        # 合并结果
        result = {
            'module': args.module,
            'pages': pages,
            # 向后兼容：顶层保留第一个 URL 的数据
            'url': multi_urls[0][1],
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
