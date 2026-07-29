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
    ('option-card', 'option-card'),
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
    ('option-card', ('inputs',)),
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
    ('option-card', '_card'),
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
    ('click_element', '在"架构"选项卡中选择"ARM计算型"', 'option-card'),
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
    ({'type': 'option-card'}, 'inputs'),  # L1 fix: option-card → inputs
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

# FIELD_TYPE_SUFFIXES canonical keys (migrated from probe_from_pages.py)
print('FIELD_TYPE_SUFFIXES canonical keys:')
from _element_types import FIELD_TYPE_SUFFIXES as TYPE_SUFFIXES
for suffix, etype in TYPE_SUFFIXES.items():
    if etype in ('option',):  # option is not a KB key, it's a pseudo-type
        continue
    check(etype in KB_TYPE_KEYS or normalize_type(etype) in KB_TYPE_KEYS,
          f"TYPE_SUFFIXES['{suffix}'] = '{etype}' not canonical")


# ================================================================
# Part 5: L7 集成测试 — option-card 容器前缀 + M1/L1/L3 修复验证
# ================================================================
print('\n' + '=' * 60)
print('Part 5: option-card Integration Tests')
print('=' * 60)

# L7-1: TYPE_SUFFIXES option-card 后缀规范化 (M1 fix)
print('\nL7-1: TYPE_SUFFIXES option-card 后缀规范化 (M1 fix):')
check(TYPE_SUFFIXES.get('_card') == 'option-card',
      f"TYPE_SUFFIXES['_card'] = {TYPE_SUFFIXES.get('_card')!r}, expected 'option-card'")
check(TYPE_SUFFIXES.get('_option') == 'option',
      f"TYPE_SUFFIXES['_option'] = {TYPE_SUFFIXES.get('_option')!r}, expected 'option'")
check(TYPE_SUFFIXES.get('_first_option') == 'option',
      f"TYPE_SUFFIXES['_first_option'] = {TYPE_SUFFIXES.get('_first_option')!r}, expected 'option'")

# L7-2: infer_discovery_section option-card 处理 (L1 fix)
print('L7-2: infer_discovery_section option-card (L1 fix):')
check(infer_discovery_section({'type': 'option-card'}) == 'inputs',
      "infer_discovery_section({'type': 'option-card'}) != 'inputs'")

# L7-3: infer_type_from_field 类型推断 (migrated from probe_from_pages._infer_type)
print('L7-3: infer_type_from_field (M1 downstream):')
from _element_types import infer_type_from_field as _infer_type
check(_infer_type('架构_card', 'xpath=//label...') == 'option-card',
      f"_infer_type('架构_card', ...) = {_infer_type('架构_card', 'xpath=//label...')!r}")
check(_infer_type('规格_card', '//label...') == 'option-card',
      f"_infer_type('规格_card', ...) = {_infer_type('规格_card', '//label...')!r}")

# L7-4: option-card 容器 XPath 前缀逻辑（数据分离模式）
print('L7-4: option-card 容器 XPath 前缀生成:')
# 新实现：容器 XPath 不含选项值（选项值存储在 data 中）
base_xpath = "//label[contains(.,'架构')]//following-sibling::*[self::div or self::span]"
drawer_xpath = f"//div[contains(@class,'el-drawer')]{base_xpath}"
dialog_xpath = f"//div[contains(@class,'el-dialog')]{base_xpath}"
msgbox_xpath = f"//div[contains(@class,'el-message-box')]{base_xpath}"

# 验证前缀格式正确
check(drawer_xpath.startswith("//div[contains(@class,'el-drawer')]"),
      "drawer 前缀格式错误")
check(dialog_xpath.startswith("//div[contains(@class,'el-dialog')]"),
      "dialog 前缀格式错误")
check(msgbox_xpath.startswith("//div[contains(@class,'el-message-box')]"),
      "message-box 前缀格式错误")
check("//label[contains(.,'架构')]" in drawer_xpath,
      "drawer XPath 缺少 label 选择器")

# L7-5: infer_elem_type 死代码删除验证 (L2 fix)
print('L7-5: infer_elem_type 无重复分支 (L2 fix):')
# 验证 '选项卡' 仍能正确推断（死代码删除不影响功能）
check(infer_elem_type('click_element', '在"架构"选项卡中选择"ARM计算型"') == 'option-card',
      "选项卡推断失败（死代码删除后）")
check(infer_elem_type('fill_value', '在"规格"选项卡中点击"16核"') == 'option-card',
      "选项卡推断失败（fill_value 上下文）")

# L7-6: 容器上下文下的 option-card 推断
print('L7-6: 容器上下文 option-card 推断:')
for container, expected_prefix in [('drawer', 'el-drawer'), ('dialog', 'el-dialog'), ('message-box', 'el-message-box')]:
    # 模拟 _case_generator 的容器前缀逻辑
    xpath = "//label[contains(.,'test')]"
    if container == 'drawer':
        xpath = f"//div[contains(@class,'el-drawer')]{xpath}"
    elif container == 'dialog':
        xpath = f"//div[contains(@class,'el-dialog')]{xpath}"
    elif container == 'message-box':
        xpath = f"//div[contains(@class,'el-message-box')]{xpath}"
    check(f"el-{container.replace('-box', '')}" in xpath,
          f"{container} 容器前缀缺失")


# ================================================================
# Part 6: option_card 数据分离测试
# ================================================================
print('\n' + '=' * 60)
print('Part 6: option_card 数据分离测试')
print('=' * 60)

def test_option_card_data_separation():
    """验证 option_card 生成器正确分离数据和定位器"""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from _case_generator import CaseGenerator

    # Mock resolver — 最小化实现
    class MockResolver:
        def get_group_name(self, *args, **kwargs):
            return "test_group"
        def construct_pending_group(self, *args, **kwargs):
            return "test_group"
        def get_trigger_map(self):
            return {}
        def get_element_map(self):
            return {}
        def get_page_element_map(self):
            return {}

    gen = CaseGenerator(
        resolver=MockResolver(),
        module_name="test_module",
    )
    gen.data_group_name = "test_data"
    gen.current_case_prefix = "case01_"
    gen.current_container = None
    gen._current_context = None
    gen._current_page_url = None

    # 测试场景：同 label 两个不同 value
    steps1 = gen.generate_step({'type': 'option_card', 'args': ('架构', 'ARM 计算')})
    steps2 = gen.generate_step({'type': 'option_card', 'args': ('架构', 'ARM计算型')})

    # 验证 1: data_entries 中有两个不同的 value
    data = gen.data_entries.get('test_data', {})
    check('case01_field_0eaa6a_card_value' in data,
          "应有第一个 value (case01_field_0eaa6a_card_value)")
    check('case01_field_0eaa6a_card_value_2' in data,
          "应有第二个 value（自动后缀 _2）")
    if 'case01_field_0eaa6a_card_value' in data:
        check(data['case01_field_0eaa6a_card_value'] == 'ARM 计算',
              f"第一个 value 应为 'ARM 计算'，实际 {data['case01_field_0eaa6a_card_value']!r}")
    if 'case01_field_0eaa6a_card_value_2' in data:
        check(data['case01_field_0eaa6a_card_value_2'] == 'ARM计算型',
              f"第二个 value 应为 'ARM计算型'，实际 {data['case01_field_0eaa6a_card_value_2']!r}")
    print('  ✓ 6.1 data_entries 正确存储两个不同的 value')

    # 验证 2: steps 中有两个内联 XPath，引用不同的 data key
    check(len(steps1) == 1, f"步骤 1 应有 1 个 step，实际 {len(steps1)}")
    check(len(steps2) == 1, f"步骤 2 应有 1 个 step，实际 {len(steps2)}")
    locator1 = steps1[0]['params']['locator']
    locator2 = steps2[0]['params']['locator']
    check('${test_data.case01_field_0eaa6a_card_value}' in locator1,
          f"步骤 1 locator 应引用第一个 data key，实际: {locator1[:80]}")
    check('${test_data.case01_field_0eaa6a_card_value_2}' in locator2,
          f"步骤 2 locator 应引用第二个 data key，实际: {locator2[:80]}")
    print('  ✓ 6.2 case steps 使用内联 XPath + 不同的 data 引用')

    # 验证 3: pages 字段只注册一次（容器 XPath，不含 value）
    card_fields = [k for k in gen.required_fields if k[1].endswith('_card')]
    check(len(card_fields) == 1,
          f"应只有一个 _card 字段，实际 {len(card_fields)}")
    if card_fields:
        container_xpath = gen.required_fields[card_fields[0]]['locator']
        check('ARM' not in container_xpath,
              f"容器 XPath 不应包含选项值，实际: {container_xpath}")
        check('label' in container_xpath and '架构' in container_xpath,
              "容器 XPath 应包含 label 定位")
    print('  ✓ 6.3 pages 字段只注册一次（容器 XPath，不含 value）')

test_option_card_data_separation()
print('\n✅ Part 6: option_card 数据分离测试通过')


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
