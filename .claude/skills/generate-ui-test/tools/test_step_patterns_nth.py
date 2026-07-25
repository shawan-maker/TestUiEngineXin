#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 step_patterns.py 的 el_select 序号功能
"""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

# 添加 tools 目录到 path
tools_dir = Path(__file__).parent
sys.path.insert(0, str(tools_dir))

from step_patterns import parse_step

def test_nth_patterns():
    """测试 el_select 的 nth 序号解析"""

    # 测试用例 1: 无序号（默认 nth=1）
    desc1 = '在"省份"下拉框中选择"江苏"'
    result1 = parse_step(desc1)
    print(f"\n测试 1: {desc1}")
    print(f"  结果: type={result1['type']}, args={result1['args']}")
    assert result1['type'] == 'el_select', f"Expected el_select, got {result1['type']}"
    assert len(result1['args']) == 2, f"Expected 2 args (label, value), got {len(result1['args'])}"
    assert result1['args'][0] == '省份', f"Expected label='省份', got {result1['args'][0]}"
    assert result1['args'][1] == '江苏', f"Expected value='江苏', got {result1['args'][1]}"
    print("  ✓ 通过")

    # 测试用例 2: 第 1 个下拉框
    desc2 = '在"镜像来源"第1个下拉框中选择"BC-Linux"'
    result2 = parse_step(desc2)
    print(f"\n测试 2: {desc2}")
    print(f"  结果: type={result2['type']}, args={result2['args']}")
    assert result2['type'] == 'el_select', f"Expected el_select, got {result2['type']}"
    assert len(result2['args']) == 3, f"Expected 3 args (label, nth, value), got {len(result2['args'])}"
    assert result2['args'][0] == '镜像来源', f"Expected label='镜像来源', got {result2['args'][0]}"
    assert result2['args'][1] == '1', f"Expected nth='1', got {result2['args'][1]}"
    assert result2['args'][2] == 'BC-Linux', f"Expected value='BC-Linux', got {result2['args'][2]}"
    print("  ✓ 通过")

    # 测试用例 3: 第 2 个下拉框
    desc3 = '在"操作系统"第2个下拉框中选择"CentOS 7.9"'
    result3 = parse_step(desc3)
    print(f"\n测试 3: {desc3}")
    print(f"  结果: type={result3['type']}, args={result3['args']}")
    assert result3['type'] == 'el_select', f"Expected el_select, got {result3['type']}"
    assert len(result3['args']) == 3, f"Expected 3 args (label, nth, value), got {len(result3['args'])}"
    assert result3['args'][0] == '操作系统', f"Expected label='操作系统', got {result3['args'][0]}"
    assert result3['args'][1] == '2', f"Expected nth='2', got {result3['args'][1]}"
    assert result3['args'][2] == 'CentOS 7.9', f"Expected value='CentOS 7.9', got {result3['args'][2]}"
    print("  ✓ 通过")

    # 测试用例 4: 第 3 个下拉框
    desc4 = '在"存储类型"第3个下拉框中选择"SSD"'
    result4 = parse_step(desc4)
    print(f"\n测试 4: {desc4}")
    print(f"  结果: type={result4['type']}, args={result4['args']}")
    assert result4['type'] == 'el_select', f"Expected el_select, got {result4['type']}"
    assert len(result4['args']) == 3, f"Expected 3 args (label, nth, value), got {len(result4['args'])}"
    assert result4['args'][0] == '存储类型', f"Expected label='存储类型', got {result4['args'][0]}"
    assert result4['args'][1] == '3', f"Expected nth='3', got {result4['args'][1]}"
    assert result4['args'][2] == 'SSD', f"Expected value='SSD', got {result4['args'][2]}"
    print("  ✓ 通过")

    # 测试用例 5: 变体 - "选择" 而非 "中选择"
    desc5 = '在"网络类型"第1个下拉框选择"VPC"'
    result5 = parse_step(desc5)
    print(f"\n测试 5: {desc5}")
    print(f"  结果: type={result5['type']}, args={result5['args']}")
    assert result5['type'] == 'el_select', f"Expected el_select, got {result5['type']}"
    assert len(result5['args']) == 3, f"Expected 3 args (label, nth, value), got {len(result5['args'])}"
    assert result5['args'][0] == '网络类型', f"Expected label='网络类型', got {result5['args'][0]}"
    assert result5['args'][1] == '1', f"Expected nth='1', got {result5['args'][1]}"
    assert result5['args'][2] == 'VPC', f"Expected value='VPC', got {result5['args'][2]}"
    print("  ✓ 通过")

    print("\n✅ 所有 step_patterns 测试通过")

if __name__ == '__main__':
    test_nth_patterns()
