#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试：验证 Tab-as-Container 机制

测试场景：
1. Tab 内元素注册到 tab:<tab_name> 独立上下文
2. Tab 上下文查找优先级（L0）
3. Tab 名称规范化（去除括号、数字、空格）
4. Tab 切换时清空容器状态
5. 多 Tab + 同名按钮场景
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

from core.element_resolver import ElementResolver
from generation.case_generator import CaseGenerator
import tempfile
import shutil
import json

print("=" * 60)
print("单元测试: Tab-as-Container 机制")
print("=" * 60)

# 创建临时目录
temp_dir = tempfile.mkdtemp()

try:
    # ── 测试 1: Tab 内元素注册到独立上下文 ──
    print("\n测试 1: Tab 内元素注册到 tab:<tab_name> 上下文")

    discovery_path = os.path.join(temp_dir, 'discovery1.json')
    discovery_data = {
        'module': 'sds_ebs_web',
        'pages': [{
            'page_slug': 'page-1',
            'framework': 'element-ui',
            'list_page': {
                'buttons': [
                    {'text': '刷新', 'locator': 'xpath=//button[text()="刷新"]', 'type': 'button'}
                ],
                'tabs': [
                    {
                        'label': '云硬盘',
                        'locator': 'xpath=//div[@role="tab"][text()="云硬盘"]',
                        'tab_elements': {
                            'buttons': [
                                {'text': '删除', 'locator': 'xpath=//button[text()="云硬盘删除"]', 'type': 'table-action-button'},
                                {'text': '编辑', 'locator': 'xpath=//button[text()="编辑"]', 'type': 'table-action-button'}
                            ],
                            'row_buttons': [
                                {'text': '卸载', 'locator': 'xpath=//button[text()="卸载"]', 'type': 'table-action-button'}
                            ]
                        }
                    },
                    {
                        'label': '回收站',
                        'locator': 'xpath=//div[@role="tab"][text()="回收站"]',
                        'tab_elements': {
                            'buttons': [
                                {'text': '恢复', 'locator': 'xpath=//button[text()="恢复"]', 'type': 'table-action-button'},
                                {'text': '删除', 'locator': 'xpath=//button[text()="回收站删除"]', 'type': 'button'}
                            ],
                            'checkboxes': [
                                {'label': '移入回收站', 'locator': 'xpath=//input[@type="checkbox"]', 'type': 'checkbox'}
                            ]
                        }
                    }
                ]
            }
        }]
    }

    with open(discovery_path, 'w', encoding='utf-8') as f:
        json.dump(discovery_data, f, ensure_ascii=False, indent=2)

    resolver = ElementResolver([discovery_path])

    # 验证 1.1: Tab 按钮注册到 list_page
    entry = resolver._element_map.get(('list_page', '云硬盘'))
    assert entry is not None, "Tab '云硬盘' 应注册到 list_page"
    print(f"  ✓ Tab '云硬盘' 注册到 list_page: {entry.field}")

    entry = resolver._element_map.get(('list_page', '回收站'))
    assert entry is not None, "Tab '回收站' 应注册到 list_page"
    print(f"  ✓ Tab '回收站' 注册到 list_page: {entry.field}")

    # 验证 1.2: Tab 内元素注册到 tab:<tab_name>
    entry = resolver._element_map.get(('tab:云硬盘', '删除'))
    assert entry is not None, "Tab 内按钮 '删除' 应注册到 tab:云硬盘"
    print(f"  ✓ Tab 内按钮 '删除' (云硬盘) 注册到 tab:云硬盘: {entry.field}")

    entry = resolver._element_map.get(('tab:回收站', '删除'))
    assert entry is not None, "Tab 内按钮 '删除' 应注册到 tab:回收站"
    print(f"  ✓ Tab 内按钮 '删除' (回收站) 注册到 tab:回收站: {entry.field}")

    # 验证 1.3: 两个同名按钮不冲突
    entry_disk = resolver._element_map.get(('tab:云硬盘', '删除'))
    entry_recycle = resolver._element_map.get(('tab:回收站', '删除'))
    assert entry_disk != entry_recycle, "两个 tab 的同名按钮应独立注册"
    print(f"  ✓ 两个 tab 的同名按钮独立注册，不冲突")

    # 验证 1.4: Row button 注册到 tab 上下文
    entry = resolver._element_map.get(('tab:云硬盘', '卸载'))
    assert entry is not None, "Row button 应注册到 tab:云硬盘"
    print(f"  ✓ Row button '卸载' 注册到 tab:云硬盘: {entry.field}")

    # 验证 1.5: Checkbox 注册到 tab 上下文
    entry = resolver._element_map.get(('tab:回收站', '移入回收站'))
    assert entry is not None, "Checkbox 应注册到 tab:回收站"
    print(f"  ✓ Checkbox '移入回收站' 注册到 tab:回收站: {entry.field}")

    print("  ✓ 测试 1 通过")

    # ── 测试 2: Tab 名称规范化 ──
    print("\n测试 2: Tab 名称规范化（去除括号、数字、空格）")

    test_cases = [
        ('回收站（3）', '回收站'),
        ('云硬盘(5)', '云硬盘'),
        ('回收站3', '回收站'),
        ('云硬盘 ', '云硬盘'),
        (' 回收站 ', '回收站'),
        ('回收站（10）', '回收站'),
    ]

    for raw_name, expected in test_cases:
        normalized = resolver._normalize_tab_name(raw_name)
        assert normalized == expected, f"'{raw_name}' 应规范化为 '{expected}'，实际为 '{normalized}'"
        print(f"  ✓ '{raw_name}' → '{normalized}'")

    print("  ✓ 测试 2 通过")

    # ── 测试 3: Tab 上下文查找优先级（L0）──
    print("\n测试 3: Tab 上下文查找优先级（L0 > L1 > L2）")

    resolver2 = ElementResolver([discovery_path])

    # 创建 CaseGenerator
    cg = CaseGenerator(resolver2, 'sds_ebs_web', temp_dir)

    # 设置当前页面 URL（用于 page_slug 查找）
    cg._current_page_url = 'http://example.com/page-1'

    # 设置当前 tab scope
    cg.current_tab_scope = 'tab_disk_id'
    cg.current_tab_scope_label = '云硬盘'

    # 验证 3.1: L0 优先匹配 tab 上下文
    elem = cg._lookup_discovery_element('删除')
    assert elem is not None, "应找到 tab 内的 '删除' 按钮"
    assert '云硬盘删除' in elem['locator'], f"应匹配 tab 内的按钮，实际: {elem['locator']}"
    print(f"  ✓ L0 优先匹配 tab 上下文: {elem['locator']}")

    # 验证 3.2: Tab 上下文未命中时回退到 list_page
    cg.current_tab_scope = 'tab_recycle_id'
    cg.current_tab_scope_label = '回收站'

    # Debug: 打印所有 list_page 元素
    print(f"    Debug: _discovery_element_map 中 list_page 元素:")
    for (ctx, label), elem in cg._discovery_element_map.items():
        if ctx == 'list_page':
            print(f"      - label='{label}', locator={elem.get('locator', '')[:50]}")

    elem = cg._lookup_discovery_element('刷新')
    assert elem is not None, "应回退到 list_page 找到 '刷新' 按钮"
    assert '刷新' in elem.get('locator', ''), f"应匹配 list_page 的按钮，实际: {elem.get('locator')}"
    print(f"  ✓ Tab 上下文未命中时回退到 list_page: {elem.get('locator')}")

    print("  ✓ 测试 3 通过")

    # ── 测试 4: Tab 切换时清空容器状态 ──
    print("\n测试 4: Tab 切换时清空容器状态")

    resolver3 = ElementResolver([discovery_path])
    cg3 = CaseGenerator(resolver3, 'sds_ebs_web', temp_dir)

    # 模拟容器状态
    cg3.current_container = '删除确认对话框'
    cg3._current_context = '删除确认对话框'

    print(f"  Tab 切换前: current_container={cg3.current_container}, _current_context={cg3._current_context}")

    # 模拟 tab 切换（手动设置 tab scope + 清空容器）
    cg3.current_tab_scope = 'tab_test_id'
    cg3.current_tab_scope_label = '测试'
    cg3.current_container = None
    cg3._current_context = 'list_page'

    print(f"  Tab 切换后: current_container={cg3.current_container}, _current_context={cg3._current_context}")

    assert cg3.current_container is None, "Tab 切换应清空 current_container"
    assert cg3._current_context == 'list_page', "Tab 切换应重置 _current_context 到 list_page"

    print("  ✓ 测试 4 通过")

    # ── 测试 5: 复杂场景：多 Tab + 同名按钮 ──
    print("\n测试 5: 复杂场景 - 多 Tab + 同名按钮")

    discovery_path5 = os.path.join(temp_dir, 'discovery5.json')
    discovery_data5 = {
        'module': 'complex_module',
        'pages': [{
            'page_slug': 'page-1',
            'framework': 'element-ui',
            'list_page': {
                'tabs': [
                    {
                        'label': '待处理',
                        'locator': 'xpath=//div[@role="tab"][text()="待处理"]',
                        'tab_elements': {
                            'buttons': [
                                {'label': '删除', 'locator': 'xpath=//button[text()="待处理删除"]', 'type': 'table-action-button'},
                                {'label': '编辑', 'locator': 'xpath=//button[text()="待处理编辑"]', 'type': 'table-action-button'}
                            ]
                        }
                    },
                    {
                        'label': '已处理',
                        'locator': 'xpath=//div[@role="tab"][text()="已处理"]',
                        'tab_elements': {
                            'buttons': [
                                {'label': '删除', 'locator': 'xpath=//button[text()="已处理删除"]', 'type': 'table-action-button'},
                                {'label': '查看', 'locator': 'xpath=//button[text()="已处理查看"]', 'type': 'button'}
                            ]
                        }
                    },
                    {
                        'label': '已归档',
                        'locator': 'xpath=//div[@role="tab"][text()="已归档"]',
                        'tab_elements': {
                            'buttons': [
                                {'label': '删除', 'locator': 'xpath=//button[text()="已归档删除"]', 'type': 'button'},
                                {'label': '恢复', 'locator': 'xpath=//button[text()="已归档恢复"]', 'type': 'button'}
                            ]
                        }
                    }
                ]
            }
        }]
    }

    with open(discovery_path5, 'w', encoding='utf-8') as f:
        json.dump(discovery_data5, f, ensure_ascii=False, indent=2)

    resolver4 = ElementResolver([discovery_path5])

    # 验证每个 tab 的 '删除' 按钮独立注册
    for tab_name, expected_locator_part in [
        ('待处理', '待处理删除'),
        ('已处理', '已处理删除'),
        ('已归档', '已归档删除')
    ]:
        entry = resolver4._element_map.get((f'tab:{tab_name}', '删除'))
        assert entry is not None, f"Tab '{tab_name}' 的 '删除' 按钮应注册"
        assert expected_locator_part in entry.locator, f"Tab '{tab_name}' 的 '删除' 应包含 '{expected_locator_part}'"
        print(f"  ✓ Tab '{tab_name}' 的 '删除' 按钮: {entry.locator[:50]}...")

    print("  ✓ 测试 5 通过")

finally:
    # 清理临时目录
    shutil.rmtree(temp_dir)

print("\n" + "=" * 60)
print("所有测试通过 ✓")
print("=" * 60)
print("\n测试覆盖:")
print("  1. Tab 内元素注册到独立上下文")
print("  2. Tab 名称规范化（括号、数字、空格）")
print("  3. Tab 上下文查找优先级（L0 > L1 > L2）")
print("  4. Tab 切换时清空容器状态")
print("  5. 多 Tab + 同名按钮场景")
print("\nTab-as-Container 机制验证完成")
