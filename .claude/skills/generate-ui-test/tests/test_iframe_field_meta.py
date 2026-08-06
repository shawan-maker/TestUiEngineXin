#!/usr/bin/env python3
"""test_iframe_field_meta.py — 验证 _populate_field_meta iframe 标记收紧逻辑

测试 _populate_field_meta 保守策略：
  - 只标记 base_field + base_field_iframe
  - 不扩散到 _select/_input/_editable 等伴随后缀
  - _wrap_click_for_iframe / _wrap_fill_for_iframe 正确区分已标记/未标记字段

Run: python test_iframe_field_meta.py
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

from generation.case_generator import CaseGenerator

_passed = 0
_failed = 0


def check(condition, msg):
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f'  ✗ FAIL: {msg}')


# ─── Mock 基础设施 ──────────────────────────────────────────

class MockElementEntry:
    """模拟 ElementEntry，只需 .raw 属性"""
    def __init__(self, raw_dict):
        self.raw = raw_dict


class MockResolver:
    """可配置的 MockResolver，支持注入合成 discovery 数据"""
    def __init__(self, element_map_data=None):
        """
        Args:
            element_map_data: {(context_key, label): raw_dict}
                raw_dict 需包含: locator, group_name, field_key,
                可选: iframe_context, has_iframe
        """
        self._element_map = {}
        if element_map_data:
            for (ctx, label), raw in element_map_data.items():
                self._element_map[(ctx, label)] = MockElementEntry(raw)

    def get_trigger_map(self):
        return {}

    def get_element_map(self):
        return self._element_map

    def get_page_element_map(self):
        return {}


def make_gen(element_map_data=None):
    """快捷创建 CaseGenerator"""
    resolver = MockResolver(element_map_data or {})
    return CaseGenerator(resolver=resolver, module_name="test_iframe_module")


# ─── 测试用例 ────────────────────────────────────────────────

def test_1_iframe_context_marks_only_base_and_iframe():
    """T1: 元素有 iframe_context → 只标记 base_field + _iframe"""
    print('\n[T1] iframe_context → 只标记 base_field + _iframe')

    gen = make_gen({
        ('list_page', '确认订单'): {
            'locator': 'xpath=//button[contains(.,\'确认订单\')]',
            'group_name': 'estack_dialog_elements',
            'field_key': 'confirm_btn',
            'iframe_context': 'iframe[name="confirmIframe"]',
        }
    })

    fm = gen.field_meta
    # 应标记
    check(('estack_dialog_elements', 'confirm_btn') in fm,
          "base_field 'confirm_btn' 应被标记")
    check(('estack_dialog_elements', 'confirm_btn_iframe') in fm,
          "'confirm_btn_iframe' 应被标记")

    # 不应标记 — 伴随后缀
    for suffix in ('_select', '_input', '_editable', '_first_option', '_textarea', '_btn'):
        key = ('estack_dialog_elements', f'confirm_btn{suffix}')
        check(key not in fm,
              f"伴随后缀 '{suffix}' 不应被标记（保守策略）")

    # 验证 meta 内容
    if ('estack_dialog_elements', 'confirm_btn') in fm:
        meta = fm[('estack_dialog_elements', 'confirm_btn')]
        check(meta['type'] == 'iframe', "type 应为 'iframe'")
        check(meta['iframe_field'] == 'confirm_btn_iframe',
              "iframe_field 应为 'confirm_btn_iframe'")
        check(meta['iframe_context'] == 'iframe[name="confirmIframe"]',
              "iframe_context 应保留原值")

    print(f'  ✓ T1 完成')


def test_2_has_iframe_rich_text_compat():
    """T2: has_iframe=True（rich_text 向后兼容）→ 同样只标记 base + _iframe"""
    print('\n[T2] has_iframe=True → 只标记 base_field + _iframe')

    gen = make_gen({
        ('form_page', '富文本内容'): {
            'locator': 'xpath=//div[contains(@class,"ql-editor")]',
            'group_name': 'form_elements',
            'field_key': 'rich_content',
            'has_iframe': True,
        }
    })

    fm = gen.field_meta
    check(('form_elements', 'rich_content') in fm,
          "base_field 'rich_content' 应被标记")
    check(('form_elements', 'rich_content_iframe') in fm,
          "'rich_content_iframe' 应被标记")

    for suffix in ('_select', '_input', '_editable', '_btn'):
        key = ('form_elements', f'rich_content{suffix}')
        check(key not in fm,
              f"伴随后缀 '{suffix}' 不应被标记")

    print(f'  ✓ T2 完成')


def test_3_no_iframe_no_mark():
    """T3: 元素无 iframe 属性 → field_meta 为空"""
    print('\n[T3] 无 iframe 属性 → field_meta 为空')

    gen = make_gen({
        ('list_page', '用户名'): {
            'locator': 'xpath=//input[@placeholder="用户名"]',
            'group_name': 'login_elements',
            'field_key': 'username',
            # 无 iframe_context，无 has_iframe
        }
    })

    check(len(gen.field_meta) == 0,
          f"field_meta 应为空，实际有 {len(gen.field_meta)} 项: {list(gen.field_meta.keys())}")

    print(f'  ✓ T3 完成')


def test_4_mixed_elements():
    """T4: 多元素混合 — 只 iframe 元素的 base_field 被标记"""
    print('\n[T4] 多元素混合 → 选择性标记')

    gen = make_gen({
        ('list_page', '确认按钮'): {
            'locator': 'xpath=//button[contains(.,\'确认\')]',
            'group_name': 'dialog_elements',
            'field_key': 'confirm_btn',
            'iframe_context': 'iframe[name="confirmIframe"]',
        },
        ('list_page', '搜索框'): {
            'locator': 'xpath=//input[@placeholder="搜索"]',
            'group_name': 'list_elements',
            'field_key': 'search_input',
            # 无 iframe
        },
        ('list_page', '富文本'): {
            'locator': 'xpath=//div[@class="ql-editor"]',
            'group_name': 'form_elements',
            'field_key': 'rich_text',
            'has_iframe': True,
        },
    })

    fm = gen.field_meta

    # iframe 元素应标记
    check(('dialog_elements', 'confirm_btn') in fm, "confirm_btn 应标记")
    check(('dialog_elements', 'confirm_btn_iframe') in fm, "confirm_btn_iframe 应标记")
    check(('form_elements', 'rich_text') in fm, "rich_text 应标记")
    check(('form_elements', 'rich_text_iframe') in fm, "rich_text_iframe 应标记")

    # 非 iframe 元素不应标记
    check(('list_elements', 'search_input') not in fm, "search_input 不应标记")
    check(('list_elements', 'search_input_iframe') not in fm, "search_input_iframe 不应标记")

    # 总数应为 4（2 个 iframe 元素 × 2 标记）
    check(len(fm) == 4,
          f"field_meta 应有 4 项，实际 {len(fm)}: {list(fm.keys())}")

    print(f'  ✓ T4 完成')


def test_5_wrap_click_marked_field():
    """T5: _wrap_click_for_iframe 对已标记字段 → frame_click_element"""
    print('\n[T5] _wrap_click_for_iframe 已标记字段 → frame_click_element')

    gen = make_gen({
        ('list_page', '确认按钮'): {
            'locator': 'xpath=//button[contains(.,\'确认\')]',
            'group_name': 'dialog_elements',
            'field_key': 'confirm_btn',
            'iframe_context': 'iframe[name="confirmIframe"]',
        }
    })

    kw, params = gen._wrap_click_for_iframe('dialog_elements', 'confirm_btn')
    check(kw == 'frame_click_element',
          f"keyword 应为 'frame_click_element'，实际 '{kw}'")
    check('frame' in params, "params 应含 'frame' 键")
    check('locator' in params, "params 应含 'locator' 键")
    if 'frame' in params:
        check('confirm_btn_iframe' in params['frame'],
              f"frame 引用应包含 'confirm_btn_iframe'，实际 '{params['frame']}'")

    print(f'  ✓ T5 完成')


def test_6_wrap_click_unmarked_field():
    """T6: _wrap_click_for_iframe 对未标记字段 → click_element，无 frame"""
    print('\n[T6] _wrap_click_for_iframe 未标记字段 → click_element')

    gen = make_gen({
        ('list_page', '确认按钮'): {
            'locator': 'xpath=//button[contains(.,\'确认\')]',
            'group_name': 'dialog_elements',
            'field_key': 'confirm_btn',
            'iframe_context': 'iframe[name="confirmIframe"]',
        }
    })

    # confirm_btn_select 是伴随后缀，不应被标记
    kw, params = gen._wrap_click_for_iframe('dialog_elements', 'confirm_btn_select')
    check(kw == 'click_element',
          f"伴随后缀 keyword 应为 'click_element'，实际 '{kw}'")
    check('frame' not in params,
          f"伴随后缀 params 不应含 'frame'，实际 keys: {list(params.keys())}")
    check('locator' in params, "params 应含 'locator' 键")

    print(f'  ✓ T6 完成')


def test_7_wrap_fill_marked_field():
    """T7: _wrap_fill_for_iframe 对已标记字段 → frame_fill_value"""
    print('\n[T7] _wrap_fill_for_iframe 已标记字段 → frame_fill_value')

    gen = make_gen({
        ('form_page', '富文本'): {
            'locator': 'xpath=//div[@class="ql-editor"]',
            'group_name': 'form_elements',
            'field_key': 'rich_text',
            'has_iframe': True,
        }
    })

    kw, params = gen._wrap_fill_for_iframe('form_elements', 'rich_text', 'hello')
    check(kw == 'frame_fill_value',
          f"keyword 应为 'frame_fill_value'，实际 '{kw}'")
    check('frame' in params, "params 应含 'frame' 键")
    check(params.get('value') == 'hello',
          f"value 应为 'hello'，实际 '{params.get('value')}'")

    print(f'  ✓ T7 完成')


def test_8_wrap_fill_unmarked_field():
    """T8: _wrap_fill_for_iframe 对未标记字段 → fill_value，无 frame"""
    print('\n[T8] _wrap_fill_for_iframe 未标记字段 → fill_value')

    gen = make_gen({
        ('form_page', '富文本'): {
            'locator': 'xpath=//div[@class="ql-editor"]',
            'group_name': 'form_elements',
            'field_key': 'rich_text',
            'has_iframe': True,
        }
    })

    # rich_text_input 是伴随后缀，不应被标记
    kw, params = gen._wrap_fill_for_iframe('form_elements', 'rich_text_input', 'world')
    check(kw == 'fill_value',
          f"伴随后缀 keyword 应为 'fill_value'，实际 '{kw}'")
    check('frame' not in params,
          f"伴随后缀 params 不应含 'frame'，实际 keys: {list(params.keys())}")
    check(params.get('value') == 'world',
          f"value 应为 'world'，实际 '{params.get('value')}'")

    print(f'  ✓ T8 完成')


# ─── 主入口 ──────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('测试 _populate_field_meta iframe 标记收紧逻辑')
    print('=' * 60)

    test_1_iframe_context_marks_only_base_and_iframe()
    test_2_has_iframe_rich_text_compat()
    test_3_no_iframe_no_mark()
    test_4_mixed_elements()
    test_5_wrap_click_marked_field()
    test_6_wrap_click_unmarked_field()
    test_7_wrap_fill_marked_field()
    test_8_wrap_fill_unmarked_field()

    print('\n' + '=' * 60)
    total = _passed + _failed
    if _failed == 0:
        print(f'✓ 全部通过: {_passed}/{total}')
    else:
        print(f'✗ {_failed}/{total} 失败, {_passed}/{total} 通过')
    print('=' * 60)
    sys.exit(1 if _failed else 0)
