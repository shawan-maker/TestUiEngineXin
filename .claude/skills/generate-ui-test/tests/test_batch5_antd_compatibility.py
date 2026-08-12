#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第五批验证测试：Ant Design 兼容性修改
验证所有修改点是否正确工作
"""
import sys
import os
import json

# 添加 tools 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

def test_framework_loading():
    """Test framework info loading"""
    print("=" * 60)
    print("Test 1: Framework info loading")
    print("=" * 60)

    # Test Phase 4 _load_framework
    from probe.discover_page import _load_framework
    fw = _load_framework()
    print(f"[OK] Phase 4 _load_framework() returns: {fw}")
    assert fw == "ant-design", f"Expected 'ant-design', got '{fw}'"

    # Test Phase 5 _load_framework
    from generation.case_utils import _load_framework as load_fw_phase5
    fw2 = load_fw_phase5()
    print(f"[OK] Phase 5 _load_framework() returns: {fw2}")
    assert fw2 == "ant-design", f"Expected 'ant-design', got '{fw2}'"

    print("[PASS] Test 1 passed\n")

def test_assertion_kb_patterns():
    """Test assertion KB pattern selection"""
    print("=" * 60)
    print("Test 2: Assertion KB pattern selection")
    print("=" * 60)

    from generation.case_utils import _get_assertion_kb_pattern

    # Test first-row-content
    pattern = _get_assertion_kb_pattern('first-row-content', keyword='testdata')
    print(f"[OK] first-row-content pattern: {pattern}")
    assert pattern is not None, "first-row-content pattern should not be None"
    assert 'testdata' in pattern, f"Pattern should contain 'testdata', got: {pattern}"
    # antd framework should select antd-specific pattern
    assert 'ant-table' in pattern or 'tbody' in pattern, f"Should contain table selector, got: {pattern}"

    # Test field-value (antd pattern only uses keyword, not field_label)
    pattern2 = _get_assertion_kb_pattern('field-value', field_label='name', keyword='vm')
    print(f"[OK] field-value pattern: {pattern2}")
    assert pattern2 is not None, "field-value pattern should not be None"
    assert 'vm' in pattern2, f"Pattern should contain 'vm', got: {pattern2}"

    # Test generic pattern (success-toast has no framework-specific pattern)
    pattern3 = _get_assertion_kb_pattern('success-toast', keyword='create')
    print(f"[OK] success-toast pattern (generic): {pattern3}")
    assert pattern3 is not None, "success-toast pattern should not be None"
    assert 'create' in pattern3, f"Pattern should contain 'create', got: {pattern3}"

    print("[PASS] Test 2 passed\n")

def test_hidden_filter_on_antd_patterns():
    """Test hidden filter injection on antd patterns"""
    print("=" * 60)
    print("Test 3: Hidden filter injection")
    print("=" * 60)

    from core.xpath_utils import inject_hidden_filter
    from generation.case_utils import _get_assertion_kb_pattern

    # Get antd pattern
    pattern = _get_assertion_kb_pattern('first-row-content', keyword='test')
    print(f"Original pattern: {pattern}")

    # Inject hidden filter
    filtered = inject_hidden_filter(pattern)
    print(f"Filtered pattern: {filtered}")

    # Verify filter was correctly injected
    assert "not(ancestor-or-self::*" in filtered, "Should contain hidden filter"
    assert "is-hidden" in filtered, "Should contain is-hidden check"
    assert "test" in filtered, "Should preserve original keyword"

    print("[PASS] Test 3 passed\n")

def test_knowledge_base_extensions():
    """Test knowledge base extensions"""
    print("=" * 60)
    print("Test 4: Knowledge base extension verification")
    print("=" * 60)

    from probe.probe_element import load_knowledge
    kb = load_knowledge()

    # Check table-action-button
    table_btn = kb['composite']['categories']['table-action-button']['patterns']
    antd_patterns = [p for p in table_btn if 'ant-table' in p]
    print(f"[OK] table-action-button: {len(antd_patterns)} antd patterns")
    assert len(antd_patterns) >= 2, "Should have at least 2 antd patterns"

    # Check dropdown-menu.click-more
    click_more = kb['composite']['categories']['dropdown-menu']['steps']['click-more']['patterns']
    antd_more = [p for p in click_more if 'ant-table' in p]
    print(f"[OK] dropdown-menu.click-more: {len(antd_more)} antd patterns")
    assert len(antd_more) >= 2, "Should have at least 2 antd patterns"

    # Check checkbox
    checkbox = kb['single_step']['categories']['checkbox']['patterns']
    antd_cb = [p for p in checkbox if 'ant-checkbox' in p]
    print(f"[OK] checkbox: {len(antd_cb)} antd patterns")
    assert len(antd_cb) >= 1, "Should have at least 1 antd pattern"

    # Check first-row-content
    first_row = kb['assertion']['categories']['first-row-content']['patterns']
    antd_first = [p for p in first_row if isinstance(p, dict) and p.get('framework') == 'ant-design']
    print(f"[OK] first-row-content: {len(antd_first)} framework-specific patterns")
    assert len(antd_first) >= 1, "Should have at least 1 framework-specific pattern"

    print("[PASS] Test 4 passed\n")

def test_container_xpath_constants():
    """Test container XPath constants"""
    print("=" * 60)
    print("Test 5: Container XPath constants")
    print("=" * 60)

    from core.xpath_utils import CONTAINER_XPATH, CONTAINER_CLASS_PATTERNS

    # Check CONTAINER_XPATH
    print(f"[OK] CONTAINER_XPATH contains {len(CONTAINER_XPATH)} container types")
    assert 'ant-drawer' in CONTAINER_XPATH, "Should contain ant-drawer"
    assert 'ant-modal' in CONTAINER_XPATH, "Should contain ant-modal"
    print(f"  - ant-drawer: {CONTAINER_XPATH['ant-drawer']}")
    print(f"  - ant-modal: {CONTAINER_XPATH['ant-modal']}")

    # Check CONTAINER_CLASS_PATTERNS
    antd_patterns = [p for p in CONTAINER_CLASS_PATTERNS if 'ant-' in p]
    print(f"[OK] CONTAINER_CLASS_PATTERNS contains {len(antd_patterns)} antd patterns")
    assert len(antd_patterns) >= 2, "Should have at least 2 antd patterns"

    print("[PASS] Test 5 passed\n")

def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Batch 5 Verification: Ant Design Compatibility")
    print("=" * 60 + "\n")

    tests = [
        test_framework_loading,
        test_assertion_kb_patterns,
        test_hidden_filter_on_antd_patterns,
        test_knowledge_base_extensions,
        test_container_xpath_constants,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Test results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
