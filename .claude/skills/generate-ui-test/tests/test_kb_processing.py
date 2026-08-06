#!/usr/bin/env python3
"""测试 _generate_xpath_from_kb 的处理逻辑"""

import sys
import os
tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, tools_dir)

from probe.probe_utils import get_kb_patterns

# 模拟 _inject_button_disabled_filter
def _inject_button_disabled_filter(xpath):
    disabled_check = (
        "not(contains(@class,'is-disabled'))"
        " and not(ancestor-or-self::*[contains(@class,'is-disabled')])"
    )
    last_bracket = xpath.rfind(']')
    if last_bracket < 0:
        return xpath + f"[{disabled_check}]"
    return xpath[:last_bracket] + f" and {disabled_check}" + xpath[last_bracket:]

# 模拟 _inject_scope_filter
def _inject_scope_filter(xpath, scope_filter):
    if not scope_filter:
        return xpath
    last_bracket = xpath.rfind(']')
    if last_bracket < 0:
        return xpath + f"[{scope_filter}]"
    return xpath[:last_bracket] + f" and {scope_filter}" + xpath[last_bracket:]

# 模拟 _safe_format
def _safe_format(pattern, fmt_vars):
    try:
        return pattern.format(**fmt_vars)
    except (KeyError, IndexError):
        return pattern

# 测试参数
elem_type = 'table-action-button'
label = '更多'
scope_filter = 'ancestor::tbody'

fmt_vars = {
    'label': label,
    'char1': label[0] if label else '',
    'char2': label[-1] if label else '',
    'tab_name': label,
    'section': label,
    'field_label': label,
    'keyword': label,
    'chars_all': " and ".join(f"contains(.,'{c}')" for c in label if c != "'") if label else "",
}

print(f"=== 测试参数 ===")
print(f"elem_type: {elem_type}")
print(f"label: {label}")
print(f"scope_filter: {scope_filter}")
print()

# 获取 KB patterns
patterns = get_kb_patterns(elem_type)
print(f"=== 获取到 {len(patterns)} 个 KB patterns ===")
for i, p in enumerate(patterns, 1):
    print(f"{i}. {p}")
print()

# 模拟处理过程
print(f"=== 处理过程 ===")
for i, pattern in enumerate(patterns, 1):
    print(f"\n--- Pattern {i} ---")
    print(f"原始: {pattern}")

    # Step 1: 格式化
    xpath = _safe_format(pattern, fmt_vars)
    print(f"格式化后: {xpath}")

    # Step 2: 注入 disabled filter
    xpath = _inject_button_disabled_filter(xpath)
    print(f"+ disabled filter: {xpath}")

    # Step 3: 注入 scope filter
    xpath = _inject_scope_filter(xpath, scope_filter)
    print(f"+ scope filter: {xpath}")

    print(f"最终 XPath 长度: {len(xpath)}")
