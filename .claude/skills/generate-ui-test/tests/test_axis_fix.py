#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自验证脚本：测试 inject_hidden_filter 对轴表达式的处理
"""

import sys
import os

# 添加 tools 目录到路径
tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, tools_dir)

from core.xpath_utils import inject_hidden_filter

def test_axis_with_predicate():
    """情况 F: 轴 + 已有谓词"""
    input_xpath = "xpath=//label[contains(.,'网络')]//following-sibling::*[self::div or self::span]"
    result = inject_hidden_filter(input_xpath)

    print("测试 F: 轴 + 已有谓词")
    print(f"  输入: {input_xpath}")
    print(f"  输出: {result}")

    # 验证：谓词应该在 ::* 之后，不在轴名之后
    assert "following-sibling::*[self::div or self::span and not(ancestor-or-self::" in result, \
        f"Predicate position error: {result}"
    assert "following-sibling[" not in result, \
        f"Error: predicate added after axis name: {result}"
    print("  [PASS]\n")

def test_axis_without_predicate():
    """情况 G: 轴 + 无谓词"""
    input_xpath = "xpath=//div//following-sibling::*"
    result = inject_hidden_filter(input_xpath)

    print("测试 G: 轴 + 无谓词")
    print(f"  输入: {input_xpath}")
    print(f"  输出: {result}")

    # 验证：谓词应该在 ::* 之后
    assert "following-sibling::*[not(ancestor-or-self::" in result, \
        f"谓词位置错误: {result}"
    assert "following-sibling[" not in result, \
        f"错误：在轴名后加了谓词: {result}"
    print("  ✓ 通过\n")

def test_regular_tag():
    """原有逻辑：普通标签名"""
    input_xpath = "xpath=//button[contains(.,'查询')]"
    result = inject_hidden_filter(input_xpath)

    print("测试 A: 普通标签 + 已有谓词")
    print(f"  输入: {input_xpath}")
    print(f"  输出: {result}")

    assert "button[contains(.,'查询') and not(ancestor-or-self::" in result, \
        f"谓词注入错误: {result}"
    print("  ✓ 通过\n")

def test_complex_axis():
    """复杂轴表达式"""
    input_xpath = "xpath=(//label[contains(.,'项目')]//following-sibling::*[self::div or self::span])[1]"
    result = inject_hidden_filter(input_xpath)

    print("测试 E: 带外层包裹的轴表达式")
    print(f"  输入: {input_xpath}")
    print(f"  输出: {result}")

    assert "following-sibling::*[self::div or self::span and not(ancestor-or-self::" in result, \
        f"谓词位置错误: {result}"
    assert result.startswith("(xpath="), f"外层包裹丢失: {result}"
    assert result.endswith(")[1]"), f"外层包裹丢失: {result}"
    print("  ✓ 通过\n")

if __name__ == '__main__':
    print("=" * 80)
    print("Self-verification: inject_hidden_filter axis fix")
    print("=" * 80)
    print()

    try:
        test_axis_with_predicate()
        test_axis_without_predicate()
        test_regular_tag()
        test_complex_axis()

        print("=" * 80)
        print("[PASS] All tests passed")
        print("=" * 80)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
