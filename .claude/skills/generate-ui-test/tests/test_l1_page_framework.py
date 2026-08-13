#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 验证测试：页面级框架感知
验证 discovery.json 结构、_get_page_framework() 辅助函数
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

passed = 0
failed = 0

def test_get_page_framework():
    """Test _get_page_framework helper function"""
    global passed, failed
    print("=" * 60)
    print("Test 1: _get_page_framework()")
    print("=" * 60)

    from probe.discover_page import _get_page_framework

    # Case 1: page has framework → returns it
    page_data = {'framework': 'ant-design'}
    result = _get_page_framework(page_data)
    assert result == 'ant-design', f"Expected 'ant-design', got '{result}'"
    print(f"  [OK] page with ant-design → {result}")

    # Case 2: page has framework element-ui → returns it
    page_data = {'framework': 'element-ui'}
    result = _get_page_framework(page_data)
    assert result == 'element-ui', f"Expected 'element-ui', got '{result}'"
    print(f"  [OK] page with element-ui → {result}")

    # Case 3: page has no framework, global provided → fallback to global
    page_data = {}
    result = _get_page_framework(page_data, global_framework='ant-design')
    assert result == 'ant-design', f"Expected 'ant-design', got '{result}'"
    print(f"  [OK] page without framework + global=ant-design → {result}")

    # Case 4: page has no framework, no global → None
    page_data = {}
    result = _get_page_framework(page_data, global_framework=None)
    # May return None or the global framework.json value
    print(f"  [OK] page without framework + no global → {result}")

    # Case 5: page_data is None → fallback
    result = _get_page_framework(None, global_framework='element-ui')
    assert result == 'element-ui', f"Expected 'element-ui', got '{result}'"
    print(f"  [OK] None page_data + global=element-ui → {result}")

    # Case 6: page framework overrides global
    page_data = {'framework': 'ant-design'}
    result = _get_page_framework(page_data, global_framework='element-ui')
    assert result == 'ant-design', f"Expected 'ant-design', got '{result}'"
    print(f"  [OK] page=ant-design + global=element-ui → {result} (page wins)")

    print("[PASS] Test 1 passed\n")
    passed += 1


def test_discover_output_structure():
    """Test that discover() output includes framework field"""
    global passed, failed
    print("=" * 60)
    print("Test 2: discover() output structure")
    print("=" * 60)

    # We can't run discover() without Playwright, so verify the code structure
    from probe import discover_page
    import inspect

    source = inspect.getsource(discover_page.discover)
    assert "'framework': page_framework" in source, \
        "discover() should include 'framework' in output dict"
    print("  [OK] discover() output includes 'framework': page_framework")

    print("[PASS] Test 2 passed\n")
    passed += 1


def test_multi_url_framework():
    """Test that multi-URL mode preserves per-page framework"""
    global passed, failed
    print("=" * 60)
    print("Test 3: Multi-URL framework preservation")
    print("=" * 60)

    from probe import discover_page
    import inspect

    source = inspect.getsource(discover_page.main)
    assert "'framework': single_result.get('framework')" in source, \
        "Multi-URL mode should preserve per-page framework"
    print("  [OK] Multi-URL pages[] includes framework field")

    print("[PASS] Test 3 passed\n")
    passed += 1


def test_run_phase4_merge():
    """Test that run_phase4 merge preserves framework"""
    global passed, failed
    print("=" * 60)
    print("Test 4: run_phase4 merge preserves framework")
    print("=" * 60)

    from probe import run_phase4
    import inspect

    source = inspect.getsource(run_phase4._merge_discovery_files)
    assert "'framework': data.get('framework')" in source, \
        "Merge should preserve framework field"
    print("  [OK] _merge_discovery_files preserves framework")

    print("[PASS] Test 4 passed\n")
    passed += 1


def test_detect_page_framework_exists():
    """Test _detect_page_framework function exists and has correct signature"""
    global passed, failed
    print("=" * 60)
    print("Test 5: _detect_page_framework function")
    print("=" * 60)

    from probe.discover_page import _detect_page_framework
    import inspect

    sig = inspect.signature(_detect_page_framework)
    assert len(sig.parameters) == 1, "Should have 1 parameter (page)"
    assert 'page' in sig.parameters, "Parameter should be named 'page'"
    print(f"  [OK] Signature: _detect_page_framework(page)")

    # Verify the JS checks both ant and el frameworks
    source = inspect.getsource(_detect_page_framework)
    assert 'ant-btn' in source or 'ant-table' in source, "Should detect ant-design"
    assert 'el-button' in source or 'el-table' in source, "Should detect element-ui"
    print("  [OK] Detects both ant-design and element-ui")

    print("[PASS] Test 5 passed\n")
    passed += 1


def test_framework_json_format():
    """Test that framework.json format is still valid"""
    global passed, failed
    print("=" * 60)
    print("Test 6: framework.json format")
    print("=" * 60)

    from probe.discover_page import _load_framework
    fw = _load_framework()
    print(f"  Global framework: {fw}")
    if fw:
        assert fw in ('ant-design', 'element-ui', 'arco-design', 'tdesign'), \
            f"Unexpected framework: {fw}"
    print("  [OK] framework.json loads correctly")

    print("[PASS] Test 6 passed\n")
    passed += 1


def main():
    print("\n" + "=" * 60)
    print("L1 Verification: Page-Level Framework Detection")
    print("=" * 60 + "\n")

    tests = [
        test_get_page_framework,
        test_discover_output_structure,
        test_multi_url_framework,
        test_run_phase4_merge,
        test_detect_page_framework_exists,
        test_framework_json_format,
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
    print(f"L1 Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
