#!/usr/bin/env python3
"""测试 step_patterns 匹配"""
import sys
sys.path.insert(0, 'tools')

from core.step_patterns import parse_step

test_cases = [
    '在"告警范围"第一个下拉框中，选择"资源类型"。',
    '在"告警范围"第一个下拉框中选择"资源类型"',
    '在"告警范围"下拉框中选择"资源类型"',
]

for test in test_cases:
    result = parse_step(test)
    print(f"输入: {test}")
    print(f"  类型: {result['type']}")
    print(f"  参数: {result.get('args', {})}")
    print()
