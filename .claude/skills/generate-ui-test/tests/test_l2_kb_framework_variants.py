#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 验证测试：KB 框架变体结构
验证 probe_knowledge.json 中 framework_variants 结构和辅助函数
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

passed = 0
failed = 0


def test_kb_structure():
    """验证 KB 中 framework_variants 结构完整"""
    global passed, failed
    print("=" * 60)
    print("Test 1: KB framework_variants 结构")
    print("=" * 60)

    from probe.probe_element import load_knowledge
    kb = load_knowledge()

    multi_step = kb.get('multi_step', {}).get('categories', {})

    # 检查 el-select
    assert 'el-select' in multi_step, "el-select should exist"
    el_select = multi_step['el-select']
    assert 'framework_variants' in el_select, "el-select should have framework_variants"
    assert 'ant-design' in el_select['framework_variants'], "el-select should have ant-design variant"
    antd_select = el_select['framework_variants']['ant-design']
    assert 'steps' in antd_select, "ant-design variant should have steps"
    assert 'expand' in antd_select['steps'], "should have expand step"
    assert 'select' in antd_select['steps'], "should have select step"
    print("  [OK] el-select framework_variants structure valid")

    # 检查 el-cascader
    assert 'el-cascader' in multi_step, "el-cascader should exist"
    el_cascader = multi_step['el-cascader']
    assert 'framework_variants' in el_cascader, "el-cascader should have framework_variants"
    assert 'ant-design' in el_cascader['framework_variants'], "el-cascader should have ant-design variant"
    antd_cascader = el_cascader['framework_variants']['ant-design']
    assert 'steps' in antd_cascader, "ant-design variant should have steps"
    assert 'expand' in antd_cascader['steps'], "should have expand step"
    assert 'select-last-text' in antd_cascader['steps'], "should have select-last-text step"
    print("  [OK] el-cascader framework_variants structure valid")

    # 检查 date-picker
    assert 'date-picker' in multi_step, "date-picker should exist"
    date_picker = multi_step['date-picker']
    assert 'framework_variants' in date_picker, "date-picker should have framework_variants"
    assert 'ant-design' in date_picker['framework_variants'], "date-picker should have ant-design variant"
    antd_date = date_picker['framework_variants']['ant-design']
    assert 'steps' in antd_date, "ant-design variant should have steps"
    assert 'expand' in antd_date['steps'], "should have expand step"
    assert 'select-today' in antd_date['steps'], "should have select-today step"
    print("  [OK] date-picker framework_variants structure valid")

    print("[PASS] Test 1 passed\n")
    passed += 1


def test_helper_function():
    """验证 get_multi_step_patterns_for_framework 辅助函数"""
    global passed, failed
    print("=" * 60)
    print("Test 2: get_multi_step_patterns_for_framework()")
    print("=" * 60)

    from probe.probe_utils import get_multi_step_patterns_for_framework

    # 测试 1: ant-design 框架返回 antd patterns
    patterns = get_multi_step_patterns_for_framework('el-select', 'expand', 'ant-design')
    assert len(patterns) > 0, "Should return patterns for ant-design"
    assert any('ant-select-selector' in p for p in patterns), "Should contain ant-select-selector"
    print(f"  [OK] ant-design el-select expand: {len(patterns)} patterns")

    # 测试 2: element-ui 框架返回默认 patterns
    patterns = get_multi_step_patterns_for_framework('el-select', 'expand', 'element-ui')
    assert len(patterns) > 0, "Should return patterns for element-ui"
    assert any('el-input__inner' in p for p in patterns), "Should contain el-input__inner"
    print(f"  [OK] element-ui el-select expand: {len(patterns)} patterns")

    # 测试 3: 未知框架返回默认 patterns
    patterns = get_multi_step_patterns_for_framework('el-select', 'expand', 'unknown-framework')
    assert len(patterns) > 0, "Should return default patterns"
    assert any('el-input__inner' in p for p in patterns), "Should contain el-input__inner"
    print(f"  [OK] unknown framework returns default: {len(patterns)} patterns")

    # 测试 4: None 框架返回默认 patterns
    patterns = get_multi_step_patterns_for_framework('el-select', 'expand', None)
    assert len(patterns) > 0, "Should return default patterns"
    print(f"  [OK] None framework returns default: {len(patterns)} patterns")

    # 测试 5: el-cascader ant-design
    patterns = get_multi_step_patterns_for_framework('el-cascader', 'expand', 'ant-design')
    assert len(patterns) > 0, "Should return patterns for ant-design"
    assert any('ant-select-selector' in p for p in patterns), "Should contain ant-select-selector"
    print(f"  [OK] ant-design el-cascader expand: {len(patterns)} patterns")

    # 测试 6: date-picker ant-design
    patterns = get_multi_step_patterns_for_framework('date-picker', 'expand', 'ant-design')
    assert len(patterns) > 0, "Should return patterns for ant-design"
    assert any('ant-picker-input' in p for p in patterns), "Should contain ant-picker-input"
    print(f"  [OK] ant-design date-picker expand: {len(patterns)} patterns")

    print("[PASS] Test 2 passed\n")
    passed += 1


def test_xpath_validity():
    """验证 ant-design XPath 语法正确性"""
    global passed, failed
    print("=" * 60)
    print("Test 3: XPath 语法验证")
    print("=" * 60)

    from probe.probe_utils import get_multi_step_patterns_for_framework

    # 检查所有 ant-design patterns 的 XPath 语法
    for etype in ['el-select', 'el-cascader', 'date-picker']:
        for step_name in ['expand', 'select', 'fill', 'select-today', 'select-now',
                         'select-month', 'range-start', 'range-end',
                         'expand-level', 'select-last-checkbox', 'select-last-text']:
            patterns = get_multi_step_patterns_for_framework(etype, step_name, 'ant-design')
            for pattern in patterns:
                # 基本语法检查 - 允许 / 开头或 ( 开头的括号表达式
                assert pattern.startswith('/') or pattern.startswith('('), \
                    f"XPath should start with / or (: {pattern}"
                assert pattern.count('[') == pattern.count(']'), f"Unbalanced brackets: {pattern}"
                assert pattern.count('(') == pattern.count(')'), f"Unbalanced parentheses: {pattern}"
                # 检查占位符格式
                if '{' in pattern:
                    assert '{label}' in pattern or '{option_text}' in pattern or '{value}' in pattern, \
                        f"Unexpected placeholder: {pattern}"
            if patterns:
                print(f"  [OK] {etype}.{step_name}: {len(patterns)} patterns valid")

    print("[PASS] Test 3 passed\n")
    passed += 1


def test_backward_compatibility():
    """验证向后兼容性：原有函数仍正常工作"""
    global passed, failed
    print("=" * 60)
    print("Test 4: 向后兼容性")
    print("=" * 60)

    from probe.probe_utils import get_multi_step_patterns

    # 原有函数应该仍然返回默认 patterns（element-ui）
    patterns = get_multi_step_patterns('el-select', 'expand')
    assert len(patterns) > 0, "Original function should still work"
    assert any('el-input__inner' in p for p in patterns), "Should contain el-input__inner"
    print(f"  [OK] Original get_multi_step_patterns() works: {len(patterns)} patterns")

    print("[PASS] Test 4 passed\n")
    passed += 1


def main():
    print("\n" + "=" * 60)
    print("L2 Verification: KB Framework Variants")
    print("=" * 60 + "\n")

    tests = [
        test_kb_structure,
        test_helper_function,
        test_xpath_validity,
        test_backward_compatibility,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            global failed
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"L2 Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
