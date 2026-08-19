#!/usr/bin/env python3
"""验证 _element_types.py 的容器 hash 后缀修复"""

import sys
import re

# 模拟 _infer_elem_type 中的关键逻辑
def infer_type_fixed(locator_ref):
    """修复后的类型推断（支持容器 hash 后缀）"""
    if locator_ref and isinstance(locator_ref, str):
        _m = re.match(r'^\$\{[^.]+\.([^}]+)\}$', locator_ref)
        if _m:
            _field = _m.group(1)
            if _field.endswith(('_select', '_editable')):
                return 'el-select'
            # BUG-FIX: _textarea 可能后跟容器 hash（如 _textarea_062f）
            if re.search(r'_textarea(?:_|$)', _field):
                return 'textarea-generic'
            # BUG-FIX: _input 可能后跟容器 hash（如 _input_062f）
            if re.search(r'_input(?:_|$)', _field):
                return 'input-generic'
    return None

def infer_type_old(locator_ref):
    """修复前的类型推断（不支持容器 hash 后缀）"""
    if locator_ref and isinstance(locator_ref, str):
        _m = re.match(r'^\$\{[^.]+\.([^}]+)\}$', locator_ref)
        if _m:
            _field = _m.group(1)
            if _field.endswith(('_select', '_editable')):
                return 'el-select'
            if _field.endswith('_textarea'):
                return 'textarea-generic'
            if _field.endswith('_input'):
                return 'input-generic'
    return None

# 测试用例
test_cases = [
    # (locator_ref, expected_type, description)
    ('${group.field_textarea}', 'textarea-generic', '纯 _textarea 后缀（无容器 hash）'),
    ('${group.field_textarea_062f}', 'textarea-generic', '_textarea + 容器 hash（4位）'),
    ('${group.field_textarea_abcd}', 'textarea-generic', '_textarea + 容器 hash（4位字母）'),
    ('${group.field_textarea_12345}', 'textarea-generic', '_textarea + 容器 hash（5位）'),
    ('${group.field_input}', 'input-generic', '纯 _input 后缀（无容器 hash）'),
    ('${group.field_input_062f}', 'input-generic', '_input + 容器 hash（4位）'),
    ('${group.field_input_abcd}', 'input-generic', '_input + 容器 hash（4位字母）'),
    ('${group.field_select}', 'el-select', '_select 后缀'),
    ('${group.field_select_062f}', None, '_select + 容器 hash（当前不支持）'),
    ('${group.field_editable}', 'el-select', '_editable 后缀'),
    ('${group.field_editable_062f}', None, '_editable + 容器 hash（当前不支持）'),
]

print("=" * 80)
print("容器 hash 后缀修复验证")
print("=" * 80)

passed = 0
failed = 0

for locator_ref, expected, desc in test_cases:
    old_result = infer_type_old(locator_ref)
    new_result = infer_type_fixed(locator_ref)

    old_ok = old_result == expected
    new_ok = new_result == expected

    status = "[OK]" if new_ok else "[FAIL]"
    print(f"\n{status} {desc}")
    print(f"  locator_ref: {locator_ref}")
    print(f"  expected: {expected}")
    print(f"  old result: {old_result} {'[OK]' if old_ok else '[FAIL]'}")
    print(f"  new result: {new_result} {'[OK]' if new_ok else '[FAIL]'}")

    if new_ok:
        passed += 1
    else:
        failed += 1

print("\n" + "=" * 80)
print(f"测试结果: {passed} passed, {failed} failed")
print("=" * 80)

# 验证实际场景
print("\n实际场景验证:")
print("-" * 80)

actual_case = '${cloud_question_drawer_progress_elements.field_57e8b7_textarea_062f}'
result = infer_type_fixed(actual_case)
expected = 'textarea-generic'

if result == expected:
    print(f"[OK] 实际 case 验证通过")
    print(f"  locator: {actual_case}")
    print(f"  result: {result}")
    print(f"  expected: {expected}")
else:
    print(f"[FAIL] 实际 case 验证失败")
    print(f"  locator: {actual_case}")
    print(f"  result: {result}")
    print(f"  expected: {expected}")
    failed += 1

print("\n" + "=" * 80)
if failed == 0:
    print("[OK] 所有测试通过")
    sys.exit(0)
else:
    print(f"[FAIL] {failed} 个测试失败")
    sys.exit(1)
