#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 S1.4 case_generator.py 框架感知改造
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from generation.case_generator import CaseGenerator
from core.element_resolver import ElementResolver

def test_menu_item_antd():
    """验证 _find_menu_item_element 能匹配 ant-menu-item"""
    print("\n=== Test 1: _find_menu_item_element ant-menu-item ===")

    # Mock resolver
    class MockResolver:
        def get_trigger_map(self): return {}
        def get_element_map(self): return {}
        def get_page_element_map(self): return {}
        def get_page_data(self): return {'containers': [], 'list_page': {}}
        _group_map = {}
        def make_pending_ref(self, *args, **kwargs): return None, None

    resolver = MockResolver()
    gen = CaseGenerator(resolver, 'test', None)

    # Mock _compat_groups to return ant-menu-item
    gen._compat_groups = lambda: {
        'test_elements': {
            'home_menu': "//li[contains(@class,'ant-menu-item')][contains(.,'首页')]"
        }
    }

    result = gen._find_menu_item_element('首页')
    assert result == '${test_elements.home_menu}', f"Expected ref, got: {result}"
    print(f"[OK] Matched ant-menu-item: {result}")


def test_table_group_antd():
    """验证 _get_table_group_name 能过滤 ant-modal 容器"""
    print("\n=== Test 2: _get_table_group_name filters ant-modal ===")

    class MockResolver:
        def get_trigger_map(self): return {}
        def get_element_map(self): return {}
        def get_page_element_map(self): return {}
        def get_page_data(self): return {'containers': [], 'list_page': {}}
        _group_map = {
            'test_elements': {
                'field1': type('E', (), {'locator': "//button[contains(@class,'ant-btn')]"})()
            },
            'test_dialog_elements': {
                'field2': type('E', (), {'locator': "//div[contains(@class,'ant-modal')]//input"})()
            },
        }
        def make_pending_ref(self, *args, **kwargs): return None, None

    resolver = MockResolver()
    gen = CaseGenerator(resolver, 'test', None)

    group = gen._get_table_group_name()
    assert group == 'test_elements', f"Expected test_elements (non-container), got: {group}"
    print(f"✓ Filtered ant-modal container, selected: {group}")


def test_close_btn_antd():
    """验证 close_btn 生成器支持 ant-design 框架"""
    print("\n=== Test 3: close_btn framework awareness ===")

    class MockResolver:
        def get_trigger_map(self): return {}
        def get_element_map(self): return {}
        def get_page_element_map(self): return {}
        def get_page_data(self): return {'containers': [], 'list_page': {}}
        _group_map = {}
        def make_pending_ref(self, *args, **kwargs): return None, None

    resolver = MockResolver()

    # Element UI
    gen_eu = CaseGenerator(resolver, 'test', None, framework=None)
    steps_eu = []
    # 直接调用内部的 close_btn 处理逻辑
    gen_eu._handle_close_btn(None, steps_eu)
    locator_eu = steps_eu[0]['params']['locator']
    assert 'el-icon-close' in locator_eu, f"Expected el-icon-close in: {locator_eu}"
    print(f"✓ Element UI close_btn: {locator_eu[:80]}...")

    # Ant Design
    gen_antd = CaseGenerator(resolver, 'test', None, framework='ant-design')
    steps_antd = []
    gen_antd._handle_close_btn(None, steps_antd)
    locator_antd = steps_antd[0]['params']['locator']
    assert 'ant-modal-close-x' in locator_antd or 'ant-drawer-close' in locator_antd, \
        f"Expected ant-modal-close-x or ant-drawer-close in: {locator_antd}"
    assert 'el-icon-close' not in locator_antd, f"Should not contain el-icon-close: {locator_antd}"
    print(f"✓ Ant Design close_btn: {locator_antd[:80]}...")


if __name__ == '__main__':
    try:
        test_menu_item_antd()
        test_table_group_antd()
        test_close_btn_antd()
        print("\n" + "=" * 60)
        print("✓ S1.4 case_generator.py 框架感知验证通过")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
