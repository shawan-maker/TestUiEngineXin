"""
Unified Element Type System — Single Source of Truth
=====================================================

Eliminates 5 independent type classification systems that caused
cross-system inconsistencies (BUG-1 through BUG-5).

Five layers unified:
  1. KB keys (probe_knowledge.json)        → KB_TYPE_KEYS
  2. Discovery types (discover_page.py)    → DISCOVERY_TO_KB
  3. D4 inference (verify_locators.py)     → infer_elem_type()
  4. Type→section guard                  → TYPE_TO_SECTIONS
  5. Step→KB mapping                      → STEP_TO_KB

Canonical type = KB key (hyphenated, e.g. 'date-picker', 'input-generic').
All legacy aliases resolve via normalize_type().
"""

import re

# ════════════════════════════════════════════════════════════════════════
# A. KB_TYPE_KEYS — All 23 KB canonical types + 1 reserved
# ════════════════════════════════════════════════════════════════════════

KB_TYPE_KEYS = frozenset({
    # ── single_step (13) ──
    'button', 'search-button', 'download-button', 'close-button',
    'menu-item', 'tab',
    'checkbox', 'checkbox-all', 'form-checkbox',
    'input-generic', 'textarea-generic',
    'detail-link', 'field-assertion',
    'option-card',                     # 选项卡（单选组）
    # ── multi_step (3) ──
    'el-select', 'el-cascader', 'date-picker',
    # ── composite (4) ──
    'table-action-button', 'dropdown-menu',
    'section-row-link', 'tab-scoped',
    # ── assertion (4) ──
    'success-toast', 'error-toast',
    'first-row-content', 'field-value',
    # ── RESERVED: 待补充 iframe KB ──
    'rich_text',
})

# Types that don't participate in discovery section search
_ASSERTION_TYPES = frozenset({
    'success-toast', 'error-toast', 'first-row-content', 'field-value',
})

# ════════════════════════════════════════════════════════════════════════
# B. STEP_TO_KB — Step type → KB key (replaces _case_generator._STEP_TO_KB)
# ════════════════════════════════════════════════════════════════════════
# BUG-1 fix: table_action→table-action-button (was table-row-button)
# BUG-1 fix: row_link→section-row-link (was row-link)

STEP_TO_KB = {
    # ── fill / input ──
    'fill': 'input-generic',
    'textarea': 'textarea-generic',
    'el_select': 'el-select',
    'el_cascader': 'el-cascader',
    'date_select': 'date-picker',
    'option_card': 'option-card',      # 选项卡
    # ── click / button ──
    'click_btn': 'button',
    'search_btn': 'search-button',
    'download_btn': 'download-button',
    'close_btn': 'close-button',
    'click_tab': 'tab',
    'menu_item': 'menu-item',
    'checkbox': 'checkbox',
    'checkbox_all': 'checkbox-all',
    'check_option': 'form-checkbox',
    'detail_link': 'detail-link',
    # ── BUG-1 fixes ──
    'table_action': 'table-action-button',   # was 'table-row-button'
    'row_link': 'section-row-link',          # was 'row-link'
    # ── New entries from _BUTTON_TYPES ──
    'click_table_row_btn': 'table-action-button',
    'click_table_action': 'table-action-button',
    'click_first_in_list': 'button',
    'click_detail_link': 'detail-link',
    'confirm_dialog': 'button',
    'confirm_delete': 'button',
    'click_more_then': 'table-action-button',        # Fix-2a: 更多按钮 = 行操作触发器（合并 click_more_then_click）
    # ── RESERVED: iframe ──
    'frame_fill': 'rich_text',
}

# ════════════════════════════════════════════════════════════════════════
# C. TYPE_TO_SECTIONS — KB type → allowed discovery sections
# ════════════════════════════════════════════════════════════════════════
# BUG-2 fix: added table-action-button, menu-item, rich_text

TYPE_TO_SECTIONS = {
    # ── single_step ──
    'input-generic':      ('inputs',),
    'textarea-generic':   ('inputs',),
    'el-select':          ('inputs',),
    'el-cascader':        ('inputs',),
    'date-picker':        ('inputs',),
    'button':             ('buttons', 'row_buttons'),
    'search-button':      ('buttons', 'row_buttons'),
    'download-button':    ('buttons', 'row_buttons'),
    'close-button':       ('buttons',),
    'dropdown-menu':      ('buttons', 'row_buttons'),
    'menu-item':          ('menu_items',),           # BUG-2 fix: was missing
    'tab':                ('tabs',),
    'detail-link':        ('detail_links',),
    'checkbox':           ('checkboxes',),
    'checkbox-all':       ('checkboxes',),
    'form-checkbox':      ('checkboxes',),
    'field-assertion':    ('inputs',),
    'option-card':        ('inputs',),
    # ── composite ──
    'table-action-button': ('row_buttons',),          # BUG-2 fix: was missing
    'section-row-link':   ('detail_links',),
    'tab-scoped':         ('tabs',),
    # ── assertion (no section, used for assertions not element search) ──
    'success-toast':      (),
    'error-toast':        (),
    'first-row-content':  (),
    'field-value':        (),
    # ── RESERVED: iframe ──
    'rich_text':          ('inputs',),                # BUG-2 fix: was missing
}

# All discovery sections (fallback when elem_type is None)
ALL_LIST_SECTIONS = (
    'buttons', 'row_buttons', 'inputs', 'tabs',
    'detail_links', 'checkboxes', 'menu_items',
)

# ════════════════════════════════════════════════════════════════════════
# D. DISCOVERY_TO_KB — Discovery raw type → KB canonical key
# ════════════════════════════════════════════════════════════════════════
# BUG-4 fix: date_picker → date-picker unified here
# Merges KB_TYPE_MAP (discover_page.py) + KB_KEY_ALIAS (probe_utils.py)
# Includes identity mappings (KB key → KB key) for normalize_type() idempotency

DISCOVERY_TO_KB = {
    # ── Discovery raw types → KB keys ──
    'button':                'button',
    'el-select':             'el-select',
    'el-cascader':           'el-cascader',
    'date_picker':           'date-picker',          # BUG-4 fix: underscore→hyphen
    'textarea':              'textarea-generic',
    'input':                 'input-generic',
    'checkbox':              'checkbox',
    'checkbox-all':          'checkbox-all',
    'form-checkbox':         'form-checkbox',
    'menu-item':             'menu-item',
    'search-button':         'search-button',
    'download-button':       'download-button',
    'close-button':          'close-button',
    'table-action-button':   'table-action-button',
    'tab':                   'tab',
    'rich_text':             'rich_text',            # RESERVED: iframe
    'option-card':           'option-card',
    # ── Identity mappings (KB key → KB key, for idempotent normalize) ──
    'input-generic':         'input-generic',
    'textarea-generic':      'textarea-generic',
    'date-picker':           'date-picker',
    'detail-link':           'detail-link',
    'field-assertion':       'field-assertion',
    'dropdown-menu':         'dropdown-menu',
    'section-row-link':      'section-row-link',
    'tab-scoped':            'tab-scoped',
    'success-toast':         'success-toast',
    'error-toast':           'error-toast',
    'first-row-content':     'first-row-content',
    'field-value':           'field-value',
}

# ════════════════════════════════════════════════════════════════════════
# E. KB_TO_SUFFIX — KB type → field key suffix
# ════════════════════════════════════════════════════════════════════════
# Replaces SUFFIX_MAP + _STEP_TYPE_ALIASES in field_suffixes.py

KB_TO_SUFFIX = {
    # ── single_step ──
    'button':              '_btn',
    'search-button':       '_btn',
    'download-button':     '_btn',
    'close-button':        '_close_btn',
    'menu-item':           '_menu',
    'tab':                 '_tab',
    'checkbox':            '_checkbox',
    'checkbox-all':        '_checkbox_all',
    'form-checkbox':       '_checkbox',
    'input-generic':       '_input',
    'textarea-generic':    '_textarea',
    'detail-link':         '_link',
    'field-assertion':     '_field',
    'option-card':         '_card',
    # ── multi_step ──
    'el-select':           '_select',
    'el-cascader':         '_cascader',
    'date-picker':         '_select',
    # ── composite ──
    'table-action-button': '_btn',
    'dropdown-menu':       '_btn',
    'section-row-link':    '_link',
    'tab-scoped':          '_tab',
    # ── assertion ──
    'success-toast':       '_text',
    'error-toast':         '_text',
    'first-row-content':   '_text',
    'field-value':         '_text',
    # ── RESERVED: iframe ──
    'rich_text':           '_iframe',
}

# Legacy SUFFIX_MAP for backward compatibility (field_suffixes.py re-export).
# Includes both canonical and raw/underscore keys so existing callers
# that pass 'date_picker', 'table_action', etc. still work.
SUFFIX_MAP_COMPAT = {
    'button':             '_btn',
    'el-select':          '_select',
    'input':              '_input',
    'textarea':           '_textarea',
    'date_picker':        '_select',      # raw discovery type
    'el-cascader':        '_cascader',
    'tab':                '_tab',
    'link':               '_link',        # legacy alias
    'detail_link':        '_link',        # underscore step type
    'checkbox':           '_checkbox',
    'checkbox-all':       '_checkbox_all',
    'form-checkbox':      '_checkbox',
    'table_action':       '_btn',         # underscore step type
    'table-action':       '_btn',         # partial hyphen
    'menu_item':          '_menu',        # underscore step type
    'menu-item':          '_menu',        # hyphen format
    # Canonical KB keys (for direct lookup after normalize)
    'input-generic':      '_input',
    'textarea-generic':   '_textarea',
    'date-picker':        '_select',
    'search-button':      '_btn',
    'download-button':    '_btn',
    'close-button':       '_close_btn',
    'detail-link':        '_link',
    'table-action-button': '_btn',
    'dropdown-menu':      '_btn',
    'section-row-link':   '_link',
    'tab-scoped':         '_tab',
    'field-assertion':    '_field',
    'rich_text':          '_iframe',
    'option-card':        '_card',
    'option_card':        '_card',
}

# Legacy _STEP_TYPE_ALIASES for backward compatibility
STEP_TYPE_ALIASES_COMPAT = {
    'click_btn': 'button',
    'date_select': 'date_picker',
    'row_link': 'link',
    'checkbox': 'checkbox',
    'checkbox_all': 'checkbox-all',
    'check_option': 'form-checkbox',
    'table_action': 'table_action',
    'menu_item': 'menu_item',
}

# ════════════════════════════════════════════════════════════════════════
# F. D4_INFERENCE_RULES — Ordered rules for element type inference
# ════════════════════════════════════════════════════════════════════════
# BUG-3 fix: added table-action-button rules
# BUG-5 fix: added detail-link rules
# Format: list of (check_func, result_type) — first match wins.
# Implemented as imperative function for clarity (see infer_elem_type).

D4_RULES_DOC = [
    # (description, result_type) — for documentation/testing
    ('keyword contains select/el_select', 'el-select'),
    ('desc contains 下拉框/下拉', 'el-select'),
    ('desc contains 级联/cascader', 'el-cascader'),
    ('keyword contains date OR desc contains 日期/时间', 'date-picker'),
    ('desc contains 选择 + 点击/click (excluding 编辑/删除/查看/详情/文件/上传/第)', 'el-select'),
    ('locator_ref suffix _select/_editable', 'el-select'),
    ('keyword contains tab OR desc contains 标签', 'tab'),
    ('desc contains 选项卡', 'option-card'),
    ('desc contains 全选', 'checkbox-all'),
    ('keyword contains checkbox OR desc contains 勾选框/勾选', 'checkbox'),
    ('desc contains 选择+第 + click', 'checkbox'),
    ('keyword contains detail_link', 'detail-link'),             # BUG-5 fix
    ('desc contains 详情链接/详情', 'detail-link'),               # BUG-5 fix
    ('keyword contains table_row_btn/table_action', 'table-action-button'),  # BUG-3 fix
    ('click + desc contains 编辑/删除/查看/详情', 'table-action-button'),     # BUG-3 fix
    ('click + desc contains 搜索/查询', 'search-button'),
    ('click + desc contains 导出/下载', 'download-button'),
    ('click + desc contains 关闭按钮', 'close-button'),
    ('click + desc contains 更多', 'table-action-button'),   # Fix-2a: was dropdown-menu
    ('click + desc contains 菜单/menu', 'menu-item'),
    ('click (default)', 'button'),
    ('fill/input + textarea/文本/描述', 'textarea-generic'),
    ('fill/input (default)', 'input-generic'),
    ('fallback', 'button'),
]

# ════════════════════════════════════════════════════════════════════════
# G. Helper Functions
# ════════════════════════════════════════════════════════════════════════

def normalize_type(raw):
    """Convert any type alias to KB canonical key.

    Idempotent: normalize_type('date-picker') == 'date-picker'.
    Handles: discovery raw types, underscore aliases, KB keys.

    Examples:
        >>> normalize_type('date_picker')
        'date-picker'
        >>> normalize_type('input')
        'input-generic'
        >>> normalize_type('input-generic')
        'input-generic'
        >>> normalize_type('el-select')
        'el-select'
        >>> normalize_type('')
        ''
        >>> normalize_type(None)
        ''
    """
    if not raw:
        return ''
    result = DISCOVERY_TO_KB.get(raw)
    if result:
        return result
    # Try underscore→hyphen conversion
    hyphenated = raw.replace('_', '-')
    result = DISCOVERY_TO_KB.get(hyphenated)
    if result:
        return result
    # Unknown type — return as-is (caller decides fallback)
    return raw


def get_sections_for_type(elem_type):
    """Get allowed discovery sections for a given element type.

    Returns ALL_LIST_SECTIONS when elem_type is unknown/None (backward compat).
    Returns empty tuple for assertion types (not searched in discovery).

    Examples:
        >>> get_sections_for_type('table-action-button')
        ('row_buttons',)
        >>> get_sections_for_type('el-select')
        ('inputs',)
        >>> get_sections_for_type('success-toast')
        ()
        >>> get_sections_for_type(None) == ALL_LIST_SECTIONS
        True
    """
    if not elem_type:
        return ALL_LIST_SECTIONS
    canonical = normalize_type(elem_type)
    return TYPE_TO_SECTIONS.get(canonical, ALL_LIST_SECTIONS)


def get_suffix_for_type(elem_type, step_type=None):
    """Get field key suffix for an element type.

    Tries: normalize(elem_type) → KB_TO_SUFFIX → step_type alias → '_field'.

    Examples:
        >>> get_suffix_for_type('el-select')
        '_select'
        >>> get_suffix_for_type('date_picker')
        '_select'
        >>> get_suffix_for_type('unknown_type')
        '_field'
    """
    if not elem_type:
        return '_field'
    canonical = normalize_type(elem_type)
    suffix = KB_TO_SUFFIX.get(canonical)
    if suffix:
        return suffix
    # Try step_type fallback
    if step_type:
        kb_key = STEP_TO_KB.get(step_type, '')
        suffix = KB_TO_SUFFIX.get(kb_key)
        if suffix:
            return suffix
    return '_field'


def infer_elem_type(keyword, desc, locator_ref=None):
    """D4 enhanced element type inference from keyword + desc + locator_ref.

    Replaces the inline if/elif chain in verify_locators.py.
    BUG-3 fix: can now produce 'table-action-button'
    BUG-5 fix: can now produce 'detail-link'
    BUG-6 fix: desc-based el-select detection ("下拉框"/"选择"+点击)
    BUG-7 fix: locator_ref suffix detection (_select/_editable → el-select)

    Args:
        keyword: Step keyword (e.g. 'click_element', 'fill_value')
        desc: Step description (e.g. '点击「确定」按钮')
        locator_ref: Raw locator variable reference before resolution
                     (e.g. '${group.field_select}'). Optional.

    Returns:
        KB canonical element type string.

    Examples:
        >>> infer_elem_type('select_option', '选择状态')
        'el-select'
        >>> infer_elem_type('click_element', '选择「方案名称」 - 点击下拉框')
        'el-select'
        >>> infer_elem_type('click_element', '判断「方案名称」是否可编辑', locator_ref='${g.f_select}')
        'el-select'
        >>> infer_elem_type('click_element', '点击编辑')
        'table-action-button'
        >>> infer_elem_type('click_element', '点击详情')
        'detail-link'
        >>> infer_elem_type('click_element', '点击确定')
        'button'
    """
    keyword_lower = keyword.lower()
    desc_lower = desc.lower() if desc else ''

    # 1. el-select (keyword-based)
    if 'select' in keyword_lower or 'el_select' in keyword_lower:
        return 'el-select'

    # 1b. el-select (desc-based, strongest signal first) — BUG-6 fix
    # _emit_el_select_steps generates desc: "选择「{label}」 - 点击下拉框"
    if '下拉框' in desc or '下拉' in desc:
        return 'el-select'

    # 2. el-cascader (before "选择" rule to avoid misclassification)
    if 'cascader' in desc_lower or '级联' in desc:
        return 'el-cascader'

    # 3. date-picker (before "选择" rule — "选择日期" is date-picker, not el-select)
    if 'date' in keyword_lower or '日期' in desc or '时间' in desc:
        return 'date-picker'

    # 3b. option-card — 选项卡（单选组），在 el-select 弱信号之前检测
    if '选项卡' in desc:
        return 'option-card'

    # 1b-cont. el-select (desc-based, weaker signal) — BUG-6 fix
    # "选择...点击" pattern — el-select click trigger step
    # Exclusion: 文件/上传 are file-upload contexts, not el-select
    # Exclusion: 编辑/删除/查看/详情 are table-action contexts
    # Exclusion: 第 is ordinal pattern (勾选"第N个", not el-select)
    # Exclusion: 目标选项 is el-select option selection step (点击目标选项/回退选择第一项), not expand step
    if '选择' in desc and ('点击' in desc or 'click' in keyword_lower):
        _action_words = ('编辑', '删除', '查看', '详情', '文件', '上传', '第', '目标选项')
        if not any(aw in desc for aw in _action_words):
            return 'el-select'

    # 1c. locator_ref suffix-based type detection — BUG-7 fix + H6 extension
    # _select/_editable → el-select; _textarea → textarea-generic; _input → input-generic
    # 类型从 discovery 通过 KB_TO_SUFFIX + label_to_key 传播到 pages YAML 后缀，零猜测
    # BUG-FIX: 支持带容器 hash 后缀的字段名（如 _textarea_062f, _input_abcd）
    if locator_ref and isinstance(locator_ref, str):
        _m = re.match(r'^\$\{[^.]+\.([^}]+)\}$', locator_ref)
        if _m:
            _field = _m.group(1)
            if _field.endswith(('_select', '_editable')):
                return 'el-select'
            # BUG-FIX: _textarea 可能后跟容器 hash（如 _textarea_062f）
            # 使用正则匹配 _textarea 后跟 _ 或字符串结尾
            if re.search(r'_textarea(?:_|$)', _field):
                return 'textarea-generic'
            # BUG-FIX: _input 可能后跟容器 hash（如 _input_062f）
            if re.search(r'_input(?:_|$)', _field):
                return 'input-generic'

    # 3b. textarea (desc-based, strong hints) — R2 fix
    # "文本框"/"多行输入"/"textarea" → textarea-generic
    # Placed before tab/checkbox/click checks so desc signal wins over keyword fallback
    _TEXTAREA_STRONG_HINTS = ('文本框', '多行输入', 'textarea')
    if any(hint in desc for hint in _TEXTAREA_STRONG_HINTS):
        return 'textarea-generic'

    # 4. tab
    if 'tab' in desc_lower or '标签' in desc:
        return 'tab'

    # 5. checkbox (checkbox-all first, then checkbox)
    # Convention: checkbox = "勾选框" (not "选择框" which = el-select)
    # Action verb: "勾选第一个产品" / "选择第一个产品"
    if '全选' in desc:
        return 'checkbox-all'
    if 'checkbox' in desc_lower or '勾选框' in desc or '勾选' in desc:
        return 'checkbox'
    # "选择第N个" pattern: ordinal selection = checkbox, not el-select
    if '选择' in desc and '第' in desc and 'click' in keyword_lower:
        return 'checkbox'

    # 6. detail-link (BUG-5 fix: was falling through to button)
    if 'detail_link' in keyword_lower or 'detail' in keyword_lower:
        return 'detail-link'
    if '详情链接' in desc or '详情' in desc:
        return 'detail-link'

    # 7. click-based types
    if 'click' in keyword_lower:
        # 7a. table-action-button (BUG-3 fix: was falling through to button)
        if 'table_row_btn' in keyword_lower or 'table_action' in keyword_lower:
            return 'table-action-button'
        # 7b. desc hints for row-level actions
        if any(kw in desc for kw in ('编辑', '删除', '查看', '详情')):
            # Only for "click + action word" pattern (not fill/input)
            return 'table-action-button'
        # 7c. search-button
        if '搜索' in desc or '查询' in desc:
            return 'search-button'
        # 7d. download-button
        if '导出' in desc or '下载' in desc:
            return 'download-button'
        # 7e-0. close-button（关闭按钮，如 el-tag closable 的 × 图标）
        # 匹配 '关闭按钮' 或 '「关闭」按钮'
        if '关闭' in desc and ('按钮' in desc or 'button' in keyword_lower):
            return 'close-button'
        # 7e-1. table-action-button（"更多"是表格行操作按钮，触发 el-dropdown 展开）
        # Fix-2a: dropdown-menu 在 KB composite 区域使用 steps 结构，
        #         get_all_patterns() 不可达 → KB 候选为零。
        #         "更多"按钮本身是 table-action-button（span），
        #         dropdown-menu 的面板选项由 click_more_then handler 内联处理。
        if '更多' in desc:
            return 'table-action-button'
        # 7e-2. menu-item (sidebar/top navigation menu clicks)
        if '菜单' in desc or 'menu' in desc_lower:
            return 'menu-item'
        # 7f. default button
        return 'button'

    # 8. fill/input-based types — R1 fix
    # fill_value / frame_fill_value / input → input-generic (default for fill/input ops)
    # Note: _textarea suffix and textarea desc hints are caught earlier (Steps 1c, 3b)
    if 'fill' in keyword_lower or 'input' in keyword_lower:
        return 'input-generic'

    # 9. assertion types — R1 fix
    if keyword_lower in ('get_text', 'get_element_count'):
        return 'field-assertion'

    # 10. fallback
    return 'button'


def infer_discovery_section(elem):
    """Infer discovery section from element attributes.

    Replaces _infer_discovery_section() in verify_locators.py.
    Uses element properties (is_row_button, is_detail_link, type)
    to determine which discovery section the element belongs to.

    Args:
        elem: Discovery element dict with keys like 'type',
              'is_row_button', 'is_detail_link'.

    Returns:
        Section name string or None if unknown.
    """
    if elem.get('is_row_button'):
        return 'row_buttons'
    if elem.get('is_detail_link'):
        return 'detail_links'
    etype = elem.get('type', '')
    if etype in ('table-action-button', 'search-button',
                 'download-button', 'button'):
        return 'buttons'
    if etype == 'menu-item':
        return 'menu_items'
    if etype in ('input', 'el-select', 'el-cascader',
                 'textarea', 'date_picker', 'rich_text',
                 # Canonical equivalents (robustness for normalized callers)
                 'input-generic', 'textarea-generic', 'date-picker',
                 'option-card'):
        return 'inputs'
    if etype == 'tab':
        return 'tabs'
    if etype in ('checkbox', 'checkbox-all', 'form-checkbox'):
        return 'checkboxes'
    return None  # Unknown type, don't filter


# ════════════════════════════════════════════════════════════════════════
# H. FIELD_TYPE_SUFFIXES — Field 后缀 → 元素类型推断
# ════════════════════════════════════════════════════════════════════════
# 从 probe_from_pages.py 迁移（2026-07-25）
# 用于从 field 名后缀快速推断元素类型（KB key 格式）

FIELD_TYPE_SUFFIXES = {
    '_btn': 'button', '_button': 'button',
    '_select': 'el-select', '_dropdown': 'el-select',
    '_input': 'input-generic', '_textarea': 'textarea-generic',
    '_tab': 'tab', '_checkbox': 'checkbox',
    '_date': 'date-picker', '_picker': 'date-picker',
    '_card': 'option-card', '_option': 'option', '_first_option': 'option',
    '_link': 'detail-link', '_menu': 'menu-item',
    '_editable': 'el-select',  # el-select 条件分支伴随字段
    '_iframe': 'rich_text',  # iframe companion 字段（iframe 支持 2026-08-03）
}


def infer_type_from_field(field: str, locator: str = '') -> str:
    """从 field 名后缀和 locator 内容推断元素类型。

    优先级：
    1. field 后缀匹配 FIELD_TYPE_SUFFIXES（去除容器 hash 后缀）
    2. locator 内容特征（el-select/textarea/tab/checkbox）
    3. 默认 'button'

    原 probe_from_pages.py _infer_type() 迁移。
    BUG-FIX: 去除容器 hash 后缀再检查类型后缀，支持 _textarea_062f 等字段。

    Args:
        field: pages YAML 中的 field 名（如 'add_btn', 'name_input_062f'）
        locator: locator 字符串（如 'xpath=//div[@class="el-select"]'）

    Returns:
        KB key 格式的元素类型（如 'button', 'el-select', 'input-generic'）
    """
    # BUG-FIX: 去除容器 hash 后缀（4位十六进制）再检查类型后缀
    field_without_ct = re.sub(r'_[0-9a-f]{4}$', '', field.lower())
    # 后缀匹配（最长匹配优先）
    for suffix in sorted(FIELD_TYPE_SUFFIXES.keys(), key=len, reverse=True):
        if field_without_ct.endswith(suffix):
            return FIELD_TYPE_SUFFIXES[suffix]
    # locator 特征匹配
    if locator:
        if 'el-select' in locator or 'ant-select' in locator:
            return 'el-select'
        if 'textarea' in locator:
            return 'textarea-generic'
        if "@role='tab'" in locator or '@role="tab"' in locator:
            return 'tab'
        if 'el-checkbox' in locator or 'ant-checkbox' in locator or 'checkbox' in locator:
            return 'checkbox'
    return 'button'
