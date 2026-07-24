#!/usr/bin/env python3
"""_element_types_test.py — V5 five-system consistency check + unit tests

Verify consistency of 5 type systems:
  1. KB keys reachable via DISCOVERY_TO_KB
  2. Discovery raw types normalize to KB keys
  3. D4 outputs are valid KB keys
  4. TYPE_TO_SECTIONS covers all KB keys
  5. STEP_TO_KB values are valid KB keys
  6. KB_TO_SUFFIX covers all KB keys
  7. normalize_type idempotency

Run: python _element_types_test.py
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _element_types import (
    KB_TYPE_KEYS, STEP_TO_KB, TYPE_TO_SECTIONS,
    DISCOVERY_TO_KB, KB_TO_SUFFIX, D4_RULES_DOC,
    ALL_LIST_SECTIONS, SUFFIX_MAP_COMPAT, STEP_TYPE_ALIASES_COMPAT,
    normalize_type, get_sections_for_type, get_suffix_for_type,
    infer_elem_type, infer_discovery_section,
)

RESERVED = {'rich_text'}
_passed = 0
_failed = 0


def check(condition, msg):
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f'  [FAIL] {msg}')


# ================================================================
# Part 1: V5 五体系一致性
# ================================================================
print('=' * 60)
print('Part 1: V5 Cross-System Consistency')
print('=' * 60)

# ① KB key completeness
print('\n[1] KB key reachable via DISCOVERY_TO_KB:')
reachable = set(DISCOVERY_TO_KB.values())
for key in sorted(KB_TYPE_KEYS):
    if key in RESERVED:
        continue
    # Assertion types don't need discovery raw types
    from _element_types import _ASSERTION_TYPES
    if key in _ASSERTION_TYPES:
        continue
    check(key in reachable, f"KB key '{key}' not reachable via DISCOVERY_TO_KB")

# ② Discovery raw types normalize to KB keys
print('[2] Discovery raw -> normalize in KB keys:')
for raw, canonical in sorted(DISCOVERY_TO_KB.items()):
    check(canonical in KB_TYPE_KEYS or canonical in RESERVED,
          f"DISCOVERY_TO_KB['{raw}'] = '{canonical}' not in KB_TYPE_KEYS")

# ③ D4 inference outputs
print('[3] D4 inference outputs in KB_TYPE_KEYS:')
for desc, elem_type in D4_RULES_DOC:
    check(elem_type in KB_TYPE_KEYS or elem_type in RESERVED,
          f"D4 rule '{desc}' produces '{elem_type}' not in KB_TYPE_KEYS")

# [4] TYPE_TO_SECTIONS keys >= KB_TYPE_KEYS
print('[4] TYPE_TO_SECTIONS keys >= KB_TYPE_KEYS:')
for key in sorted(KB_TYPE_KEYS):
    check(key in TYPE_TO_SECTIONS,
          f"KB key '{key}' missing from TYPE_TO_SECTIONS")

# [5] STEP_TO_KB values <= KB_TYPE_KEYS
print('[5] STEP_TO_KB values <= KB_TYPE_KEYS:')
for step, kb_key in sorted(STEP_TO_KB.items()):
    check(kb_key in KB_TYPE_KEYS or kb_key in RESERVED,
          f"STEP_TO_KB['{step}'] = '{kb_key}' not in KB_TYPE_KEYS")

# [6] KB_TO_SUFFIX keys >= KB_TYPE_KEYS
print('[6] KB_TO_SUFFIX keys >= KB_TYPE_KEYS:')
for key in sorted(KB_TYPE_KEYS):
    check(key in KB_TO_SUFFIX,
          f"KB key '{key}' missing from KB_TO_SUFFIX")

# [7] normalize_type 幂等性
print('[7] normalize_type idempotency:')
for key in sorted(KB_TYPE_KEYS):
    result = normalize_type(key)
    check(result == key,
          f"normalize_type('{key}') = '{result}' (not idempotent)")


# ================================================================
# Part 2: BUG 修复验证
# ================================================================
print('\n' + '=' * 60)
print('Part 2: Bug Fix Verification')
print('=' * 60)

# BUG-1: _STEP_TO_KB 拼写错误
print('\nBUG-1: STEP_TO_KB spelling fixes:')
check(STEP_TO_KB['table_action'] == 'table-action-button',
      f"table_action -> {STEP_TO_KB['table_action']} (expected table-action-button)")
check(STEP_TO_KB['row_link'] == 'section-row-link',
      f"row_link -> {STEP_TO_KB['row_link']} (expected section-row-link)")

# BUG-2: _TYPE_COMPATIBLE_SECTIONS 缺失
print('BUG-2: TYPE_TO_SECTIONS completeness:')
check('table-action-button' in TYPE_TO_SECTIONS, "table-action-button missing")
check('menu-item' in TYPE_TO_SECTIONS, "menu-item missing")
check('rich_text' in TYPE_TO_SECTIONS, "rich_text missing")
check(TYPE_TO_SECTIONS['table-action-button'] == ('row_buttons',),
      f"table-action-button sections: {TYPE_TO_SECTIONS['table-action-button']}")
check(TYPE_TO_SECTIONS['menu-item'] == ('menu_items',),
      f"menu-item sections: {TYPE_TO_SECTIONS['menu-item']}")

# BUG-3: D4 infer table-action-button
print('BUG-3: D4 can infer table-action-button:')
check(infer_elem_type('click_table_row_btn', 'xxx') == 'table-action-button',
      "click_table_row_btn -> not table-action-button")
check(infer_elem_type('click_element', '点击编辑') == 'table-action-button',
      "click+编辑 -> not table-action-button")
check(infer_elem_type('click_element', '点击删除') == 'table-action-button',
      "click+删除 -> not table-action-button")

# BUG-4: date_picker vs date-picker
print('BUG-4: date_picker normalization:')
check(normalize_type('date_picker') == 'date-picker',
      f"date_picker -> {normalize_type('date_picker')}")
check(normalize_type('date-picker') == 'date-picker',
      f"date-picker -> {normalize_type('date-picker')}")

# BUG-5: D4 infer detail-link
print('BUG-5: D4 can infer detail-link:')
check(infer_elem_type('detail_link', 'xxx') == 'detail-link',
      "detail_link -> not detail-link")
check(infer_elem_type('click_element', '点击详情链接') == 'detail-link',
      "click+详情链接 -> not detail-link")
check(infer_elem_type('click_element', '点击详情') == 'detail-link',
      "click+详情 -> not detail-link")


# ================================================================
# Part 3: 单元测试
# ================================================================
print('\n' + '=' * 60)
print('Part 3: Unit Tests')
print('=' * 60)

# normalize_type
print('\nnormalize_type():')
test_cases = [
    ('input', 'input-generic'),
    ('textarea', 'textarea-generic'),
    ('date_picker', 'date-picker'),
    ('el-select', 'el-select'),
    ('button', 'button'),
    ('input-generic', 'input-generic'),
    ('textarea-generic', 'textarea-generic'),
    ('date-picker', 'date-picker'),
    ('rich_text', 'rich_text'),
    ('', ''),
    (None, ''),
    ('unknown_type', 'unknown_type'),  # passthrough
]
for raw, expected in test_cases:
    actual = normalize_type(raw)
    check(actual == expected, f"normalize_type({raw!r}) = {actual!r}, expected {expected!r}")

# get_sections_for_type
print('get_sections_for_type():')
section_cases = [
    ('input-generic', ('inputs',)),
    ('el-select', ('inputs',)),
    ('date-picker', ('inputs',)),
    ('button', ('buttons', 'row_buttons')),
    ('search-button', ('buttons', 'row_buttons')),
    ('table-action-button', ('row_buttons',)),
    ('tab', ('tabs',)),
    ('detail-link', ('detail_links',)),
    ('checkbox', ('checkboxes',)),
    ('menu-item', ('menu_items',)),
    ('success-toast', ()),
    (None, ALL_LIST_SECTIONS),
    ('unknown_xyz', ALL_LIST_SECTIONS),
]
for etype, expected in section_cases:
    actual = get_sections_for_type(etype)
    check(actual == expected,
          f"get_sections_for_type({etype!r}) = {actual!r}, expected {expected!r}")

# get_suffix_for_type
print('get_suffix_for_type():')
suffix_cases = [
    ('el-select', '_select'),
    ('date_picker', '_select'),
    ('date-picker', '_select'),
    ('button', '_btn'),
    ('search-button', '_btn'),
    ('table-action-button', '_btn'),
    ('tab', '_tab'),
    ('detail-link', '_link'),
    ('checkbox', '_checkbox'),
    ('checkbox-all', '_checkbox_all'),
    ('menu-item', '_menu'),
    ('rich_text', '_iframe'),
    ('unknown', '_field'),
    ('', '_field'),
    (None, '_field'),
]
for etype, expected in suffix_cases:
    actual = get_suffix_for_type(etype)
    check(actual == expected,
          f"get_suffix_for_type({etype!r}) = {actual!r}, expected {expected!r}")

# infer_elem_type — comprehensive
print('infer_elem_type():')
infer_cases = [
    ('select_option', '选择状态', 'el-select'),
    ('el_select_value', 'xxx', 'el-select'),
    ('click_element', '选择级联', 'el-cascader'),
    ('click_element', '选择日期', 'date-picker'),
    ('click_element', '选择时间', 'date-picker'),
    ('click_element', '点击标签', 'tab'),
    ('click_element', '全选', 'checkbox-all'),
    ('click_element', '选择框', 'el-select'),          # 选择框 = el-select per convention
    ('click_element', '勾选框', 'checkbox'),           # checkbox = 勾选框 per convention
    ('click_element', '勾选第一个产品', 'checkbox'),    # 勾选 action verb → checkbox
    ('click_element', '选择第一个产品', 'checkbox'),    # 选择第N个 → checkbox (ordinal pattern)
    ('detail_link', 'xxx', 'detail-link'),
    ('click_element', '点击详情', 'detail-link'),
    ('click_table_row_btn', 'xxx', 'table-action-button'),
    ('click_table_action', 'xxx', 'table-action-button'),
    ('click_element', '点击编辑', 'table-action-button'),
    ('click_element', '点击删除', 'table-action-button'),
    ('click_element', '点击查看', 'table-action-button'),
    ('click_element', '点击搜索', 'search-button'),
    ('click_element', '点击查询', 'search-button'),
    ('click_element', '点击导出', 'download-button'),
    ('click_element', '点击下载', 'download-button'),
    ('click_element', '点击更多', 'table-action-button'),   # Fix-2a: was dropdown-menu
    ('click_element', '点击菜单项', 'menu-item'),       # menu-item detection
    ('click_element', 'click menu item', 'menu-item'),    # menu-item (English)
    ('click_element', '点击确定', 'button'),
    ('click_element', '点击新增', 'button'),
    ('fill_value', '填写描述', 'textarea-generic'),
    ('fill_value', '填写文本', 'textarea-generic'),
    ('fill_value', '填写名称', 'input-generic'),
    ('fill_value', '填写', 'input-generic'),
    ('unknown_keyword', 'xxx', 'button'),  # fallback
]
for kw, desc, expected in infer_cases:
    actual = infer_elem_type(kw, desc)
    check(actual == expected,
          f"infer_elem_type({kw!r}, {desc!r}) = {actual!r}, expected {expected!r}")

# infer_discovery_section
print('infer_discovery_section():')
discovery_cases = [
    ({'is_row_button': True}, 'row_buttons'),
    ({'is_detail_link': True}, 'detail_links'),
    ({'type': 'button'}, 'buttons'),
    ({'type': 'search-button'}, 'buttons'),
    ({'type': 'table-action-button'}, 'buttons'),
    ({'type': 'menu-item'}, 'menu_items'),
    ({'type': 'input'}, 'inputs'),
    ({'type': 'el-select'}, 'inputs'),
    ({'type': 'date_picker'}, 'inputs'),
    ({'type': 'rich_text'}, 'inputs'),
    ({'type': 'tab'}, 'tabs'),
    ({'type': 'checkbox'}, 'checkboxes'),
    ({'type': 'unknown_xyz'}, None),
]
for elem, expected in discovery_cases:
    actual = infer_discovery_section(elem)
    check(actual == expected,
          f"infer_discovery_section({elem!r}) = {actual!r}, expected {expected!r}")


# ================================================================
# Part 4: 向后兼容验证
# ================================================================
print('\n' + '=' * 60)
print('Part 4: Backward Compatibility')
print('=' * 60)

# KB_KEY_ALIAS re-export
print('\nKB_KEY_ALIAS re-exports:')
from probe_utils import KB_KEY_ALIAS
from probe_element import _KB_KEY_ALIAS
check(KB_KEY_ALIAS == _KB_KEY_ALIAS, "probe_utils vs probe_element mismatch")
check('input' in KB_KEY_ALIAS, "missing 'input'")
check('textarea' in KB_KEY_ALIAS, "missing 'textarea'")
check('date_picker' in KB_KEY_ALIAS, "missing 'date_picker'")

# SUFFIX_MAP backward compat
print('SUFFIX_MAP backward compat:')
from field_suffixes import SUFFIX_MAP, _STEP_TYPE_ALIASES
legacy_keys = ['button', 'el-select', 'input', 'textarea', 'date_picker',
               'el-cascader', 'tab', 'link', 'detail_link', 'checkbox',
               'checkbox-all', 'table_action', 'table-action', 'menu_item', 'menu-item']
for key in legacy_keys:
    check(key in SUFFIX_MAP, f"SUFFIX_MAP missing legacy key '{key}'")

# _STEP_TYPE_ALIASES backward compat
print('_STEP_TYPE_ALIASES backward compat:')
legacy_aliases = ['click_btn', 'date_select', 'row_link', 'checkbox',
                  'checkbox_all', 'table_action', 'menu_item']
for key in legacy_aliases:
    check(key in _STEP_TYPE_ALIASES, f"_STEP_TYPE_ALIASES missing '{key}'")

# _STEP_TO_KB: 同源修复后 _case_generator.py 不再 import _STEP_TO_KB（死导入已删除）
print('_STEP_TO_KB removal check:')
import _case_generator as _cg_mod
check(not hasattr(_cg_mod, '_STEP_TO_KB'),
      "_case_generator._STEP_TO_KB should be removed (dead import after single-source fix)")

# TYPE_SUFFIXES canonical keys
print('TYPE_SUFFIXES canonical keys:')
from probe_from_pages import TYPE_SUFFIXES
for suffix, etype in TYPE_SUFFIXES.items():
    if etype in ('option',):  # option is not a KB key, it's a pseudo-type
        continue
    check(etype in KB_TYPE_KEYS or normalize_type(etype) in KB_TYPE_KEYS,
          f"TYPE_SUFFIXES['{suffix}'] = '{etype}' not canonical")


# ================================================================
# Summary
# ================================================================
print('\n' + '=' * 60)
total = _passed + _failed
if _failed:
    print(f'RESULT: {_passed}/{total} passed, {_failed} FAILED')
    sys.exit(1)
else:
    print(f'RESULT: {total}/{total} ALL PASSED ✓')
    print(f'  KB_TYPE_KEYS:      {len(KB_TYPE_KEYS)}')
    print(f'  DISCOVERY_TO_KB:   {len(DISCOVERY_TO_KB)}')
    print(f'  D4_RULES:          {len(D4_RULES_DOC)}')
    print(f'  TYPE_TO_SECTIONS:  {len(TYPE_TO_SECTIONS)}')
    print(f'  STEP_TO_KB:        {len(STEP_TO_KB)}')
    print(f'  KB_TO_SUFFIX:      {len(KB_TO_SUFFIX)}')
    sys.exit(0)
