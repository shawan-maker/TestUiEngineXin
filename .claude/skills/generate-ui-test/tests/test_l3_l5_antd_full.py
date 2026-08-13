#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3-L5 验证测试：Ant Design 兼容性增强完整测试
验证生成器框架路由 (L3)、验证器框架路由 (L4)、KB 单步/组合类型补充 (L5)
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

passed = 0
failed = 0


class MockResolver:
    """Mock resolver for testing CaseGenerator framework parameter"""
    def get_trigger_map(self):
        return {}
    def get_element_map(self):
        return {}
    def get_page_element_map(self):
        return {}
    def get_page_data(self):
        return {'containers': [], 'list_page': {}}

def test_case_generator_framework_ctor():
    """验证 CaseGenerator 接受 framework 参数"""
    global passed, failed
    print("=" * 60)
    print("Test 1: CaseGenerator framework 参数")
    print("=" * 60)

    from generation.case_generator import CaseGenerator

    resolver = MockResolver()

    # 测试 1: 默认框架（None）
    gen = CaseGenerator(resolver, 'test', None)
    assert gen._framework is None, "Default framework should be None"
    print("  [OK] Default framework is None")

    # 测试 2: ant-design 框架
    gen = CaseGenerator(resolver, 'test', None, framework='ant-design')
    assert gen._framework == 'ant-design', "Framework should be 'ant-design'"
    print("  [OK] ant-design framework accepted")

    # 测试 3: element-ui 框架
    gen = CaseGenerator(resolver, 'test', None, framework='element-ui')
    assert gen._framework == 'element-ui', "Framework should be 'element-ui'"
    print("  [OK] element-ui framework accepted")

    print("[PASS] Test 1 passed\n")
    passed += 1


def test_dropdown_option_xpath():
    """验证 _build_dropdown_option_xpath 框架感知"""
    global passed, failed
    print("=" * 60)
    print("Test 2: _build_dropdown_option_xpath 框架感知")
    print("=" * 60)

    from generation.case_generator import CaseGenerator

    resolver = MockResolver()

    # 测试 1: element-ui 模式（默认）
    gen = CaseGenerator(resolver, 'test', None)
    xpath = gen._build_dropdown_option_xpath('删除')
    assert 'x-placement' in xpath, "Element UI should use x-placement"
    assert '删除' in xpath, "Should contain action text"
    print(f"  [OK] Element UI: x-placement pattern")

    # 测试 2: ant-design 模式
    gen = CaseGenerator(resolver, 'test', None, framework='ant-design')
    xpath = gen._build_dropdown_option_xpath('编辑')
    assert 'ant-dropdown-menu' in xpath, "Ant Design should use ant-dropdown-menu"
    assert 'ant-dropdown-menu-item' in xpath, "Should use ant-dropdown-menu-item"
    assert '编辑' in xpath, "Should contain action text"
    print(f"  [OK] Ant Design: ant-dropdown-menu pattern")

    print("[PASS] Test 2 passed\n")
    passed += 1


def test_more_button_fallback_xpath():
    """验证 _build_more_button_fallback_xpath 框架感知"""
    global passed, failed
    print("=" * 60)
    print("Test 3: _build_more_button_fallback_xpath 框架感知")
    print("=" * 60)

    from generation.case_generator import CaseGenerator

    resolver = MockResolver()

    # 测试 1: element-ui 模式（默认）
    gen = CaseGenerator(resolver, 'test', None)
    xpath = gen._build_more_button_fallback_xpath()
    assert 'el-select-dropdown' in xpath, "Element UI should exclude el-select-dropdown"
    assert '更多' in xpath, "Should contain '更多' text"
    print(f"  [OK] Element UI: exclude el-select-dropdown")

    # 测试 2: ant-design 模式
    gen = CaseGenerator(resolver, 'test', None, framework='ant-design')
    xpath = gen._build_more_button_fallback_xpath()
    assert 'ant-select-dropdown' in xpath, "Ant Design should exclude ant-select-dropdown"
    assert '更多' in xpath, "Should contain '更多' text"
    print(f"  [OK] Ant Design: exclude ant-select-dropdown")

    print("[PASS] Test 3 passed\n")
    passed += 1


def test_date_picker_antd_xpath():
    """验证 _build_date_picker_xpath(framework='ant-design')"""
    global passed, failed
    print("=" * 60)
    print("Test 4: _build_date_picker_xpath ant-design 模式")
    print("=" * 60)

    from generation.case_utils import _build_date_picker_xpath

    # 测试 1: 今天 - ant-design
    xpath, desc = _build_date_picker_xpath('今天', framework='ant-design')
    assert 'ant-picker-dropdown' in xpath, "Should use ant-picker-dropdown"
    assert 'ant-picker-today-btn' in xpath, "Should use ant-picker-today-btn"
    print(f"  [OK] 今天: {desc}")

    # 测试 2: 此刻 - ant-design
    xpath, desc = _build_date_picker_xpath('此刻', framework='ant-design')
    assert 'ant-picker-dropdown' in xpath, "Should use ant-picker-dropdown"
    assert 'ant-picker-now-btn' in xpath, "Should use ant-picker-now-btn"
    print(f"  [OK] 此刻: {desc}")

    # 测试 3: 当月 - ant-design
    xpath, desc = _build_date_picker_xpath('当月', framework='ant-design')
    assert 'ant-picker-dropdown' in xpath, "Should use ant-picker-dropdown"
    assert 'ant-picker-cell-today' in xpath, "Should use ant-picker-cell-today"
    print(f"  [OK] 当月: {desc}")

    # 测试 4: 默认 element-ui 模式
    xpath, desc = _build_date_picker_xpath('今天')
    assert 'x-placement' in xpath, "Default should use Element UI x-placement"
    assert 'today' in xpath, "Should use today class"
    print(f"  [OK] 默认 Element UI: {desc}")

    print("[PASS] Test 4 passed\n")
    passed += 1


def test_strip_container_prefix_antd():
    """验证 _strip_container_prefix 能剥离 antd 前缀"""
    global passed, failed
    print("=" * 60)
    print("Test 5: _strip_container_prefix antd 模式")
    print("=" * 60)

    from probe.probe_element import _strip_container_prefix

    # 测试 1: ant-drawer
    xpath = "//div[contains(@class,'ant-drawer')]//button[contains(.,'提交')]"
    stripped = _strip_container_prefix(xpath)
    assert stripped == "//button[contains(.,'提交')]", f"Should strip ant-drawer: {stripped}"
    print(f"  [OK] ant-drawer stripped")

    # 测试 2: ant-modal
    xpath = "//div[contains(@class,'ant-modal')]//input[@placeholder='请输入']"
    stripped = _strip_container_prefix(xpath)
    assert stripped == "//input[@placeholder='请输入']", f"Should strip ant-modal: {stripped}"
    print(f"  [OK] ant-modal stripped")

    # 测试 3: el-drawer（向后兼容）
    xpath = "//div[contains(@class,'el-drawer')]//button[contains(.,'确认')]"
    stripped = _strip_container_prefix(xpath)
    assert stripped == "//button[contains(.,'确认')]", f"Should strip el-drawer: {stripped}"
    print(f"  [OK] el-drawer stripped (backward compat)")

    # 测试 4: el-dialog（向后兼容）
    xpath = "//div[contains(@class,'el-dialog')]//input[@class='el-input__inner']"
    stripped = _strip_container_prefix(xpath)
    assert stripped == "//input[@class='el-input__inner']", f"Should strip el-dialog: {stripped}"
    print(f"  [OK] el-dialog stripped (backward compat)")

    print("[PASS] Test 5 passed\n")
    passed += 1


def test_data_layer_framework():
    """验证 data_layer 构建 locators 时使用框架感知"""
    global passed, failed
    print("=" * 60)
    print("Test 6: data_layer 框架感知")
    print("=" * 60)

    from verification.data_layer import _get_kb_locators_for_type

    fmt_vars = {
        'label': '状态',
        'char1': '状',
        'char2': '态',
        'chars_all': "contains(.,'状') and contains(.,'态')",
    }

    # 测试 1: 默认模式（element-ui）
    locators = _get_kb_locators_for_type('el-select', fmt_vars)
    assert len(locators) > 0, "Should return locators"
    assert any('el-input__inner' in loc for loc in locators), "Should contain el-input__inner"
    print(f"  [OK] Default mode: {len(locators)} locators")

    # 测试 2: ant-design 模式
    locators = _get_kb_locators_for_type('el-select', fmt_vars, framework='ant-design')
    assert len(locators) > 0, "Should return locators"
    assert any('ant-select-selector' in loc for loc in locators), "Should contain ant-select-selector"
    print(f"  [OK] ant-design mode: {len(locators)} locators")

    print("[PASS] Test 6 passed\n")
    passed += 1


def test_kb_single_step_antd():
    """验证 7 个 single_step 类型有 antd 模式"""
    global passed, failed
    print("=" * 60)
    print("Test 7: KB single_step antd 模式")
    print("=" * 60)

    from probe.probe_element import load_knowledge

    kb = load_knowledge()
    single_step = kb.get('single_step', {}).get('categories', {})

    # 检查 7 个类型
    types_to_check = {
        'button': 'ant-btn',
        'search-button': 'anticon-search',
        'download-button': 'anticon-download',
        'close-button': 'ant-modal-close',
        'input-generic': 'ant-input',
        'textarea-generic': 'ant-input',
        'detail-link': 'ant-table',
    }

    for type_name, expected_class in types_to_check.items():
        assert type_name in single_step, f"{type_name} should exist"
        patterns = single_step[type_name].get('patterns', [])
        assert len(patterns) > 0, f"{type_name} should have patterns"

        # 检查是否有 antd 模式
        has_antd = any(expected_class in p for p in patterns if isinstance(p, str))
        assert has_antd, f"{type_name} should have {expected_class} pattern"
        print(f"  [OK] {type_name}: has {expected_class}")

    print("[PASS] Test 7 passed\n")
    passed += 1


def test_kb_composite_antd():
    """验证 4 个 composite 步骤有 antd 模式"""
    global passed, failed
    print("=" * 60)
    print("Test 8: KB composite antd 模式")
    print("=" * 60)

    from probe.probe_element import load_knowledge

    kb = load_knowledge()
    composite = kb.get('composite', {}).get('categories', {})

    # 检查 4 个步骤
    checks = [
        ('dropdown-menu', 'click-action', 'ant-dropdown'),
        ('tab-scoped', 'scoped-input', 'ant-input'),
        ('tab-scoped', 'scoped-detail-link', 'ant-table'),
        ('tab-scoped', 'scoped-menu-item', 'ant-menu-item'),
    ]

    for category, step_name, expected_class in checks:
        assert category in composite, f"{category} should exist"
        steps = composite[category].get('steps', {})
        assert step_name in steps, f"{category}.{step_name} should exist"
        patterns = steps[step_name].get('patterns', [])
        assert len(patterns) > 0, f"{category}.{step_name} should have patterns"

        # 检查是否有 antd 模式
        has_antd = any(expected_class in p for p in patterns if isinstance(p, str))
        assert has_antd, f"{category}.{step_name} should have {expected_class} pattern"
        print(f"  [OK] {category}.{step_name}: has {expected_class}")

    print("[PASS] Test 8 passed\n")
    passed += 1


def test_backward_compat_l1():
    """验证 L1 测试仍然通过"""
    global passed, failed
    print("=" * 60)
    print("Test 9: L1 向后兼容性")
    print("=" * 60)

    # 运行 L1 测试
    import subprocess
    result = subprocess.run(
        ['python', 'tests/test_l1_page_framework.py'],
        cwd=os.path.join(os.path.dirname(__file__), '..'),
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"L1 tests failed: {result.stderr}"
    print("  [OK] L1 tests passed")

    print("[PASS] Test 9 passed\n")
    passed += 1


def test_backward_compat_l2():
    """验证 L2 测试仍然通过"""
    global passed, failed
    print("=" * 60)
    print("Test 10: L2 向后兼容性")
    print("=" * 60)

    # 运行 L2 测试
    import subprocess
    result = subprocess.run(
        ['python', 'tests/test_l2_kb_framework_variants.py'],
        cwd=os.path.join(os.path.dirname(__file__), '..'),
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"L2 tests failed: {result.stderr}"
    print("  [OK] L2 tests passed")

    print("[PASS] Test 10 passed\n")
    passed += 1


def main():
    print("\n" + "=" * 60)
    print("L3-L5 Verification: Ant Design Compatibility Enhancement")
    print("=" * 60 + "\n")

    tests = [
        test_case_generator_framework_ctor,
        test_dropdown_option_xpath,
        test_more_button_fallback_xpath,
        test_date_picker_antd_xpath,
        test_strip_container_prefix_antd,
        test_data_layer_framework,
        test_kb_single_step_antd,
        test_kb_composite_antd,
        test_backward_compat_l1,
        test_backward_compat_l2,
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
    print(f"L3-L5 Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
