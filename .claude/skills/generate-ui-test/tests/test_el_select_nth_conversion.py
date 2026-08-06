#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本：验证 el-select 转换过程中 [nth] 索引是否丢失

问题现象：
- 网络标签有两个下拉框
- 第一个下拉框（nth=1）被点击了两次
- 第二个下拉框（nth=2）没有被点击
- 怀疑：_convert_input_to_el_select 把 ()[2] 改成了 ()[1]
"""

import sys
import os

# Windows 控制台编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加 tools 目录到路径
tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, tools_dir)

from verification.verify_engine import _convert_input_to_el_select, _generate_el_select_candidates

def test_case_1():
    """测试用例 1：第1个网络下拉框 (nth=1)"""
    print("=" * 80)
    print("测试用例 1: 第1个网络下拉框 (nth=1)")
    print("=" * 80)

    # 模拟 case_generator.py 生成的 expand_xpath (nth=1)
    # 格式: (base_xpath)[1]
    input_locator_1 = (
        "xpath=(//*[contains(text(),'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner'])[1]"
    )

    print(f"\n输入 (nth=1):")
    print(f"  {input_locator_1}")

    # 调用转换函数
    converted_1 = _convert_input_to_el_select(input_locator_1)

    print(f"\n转换后:")
    print(f"  {converted_1}")

    # 检查 [1] 是否保留
    if '])[1]' in converted_1:
        print("\n✅ [PASS] [1] 索引正确保留")
    else:
        print(f"\n❌ [FAIL] [1] 索引丢失或错误")
        print(f"  期望包含: ')[1]'")
        print(f"  实际结果: {converted_1}")

    # 测试双候选生成
    print(f"\n双候选生成:")
    input_xpath_1 = input_locator_1[6:]  # 去掉 xpath= 前缀
    candidates_1 = _generate_el_select_candidates(input_xpath_1)

    for i, cand in enumerate(candidates_1):
        print(f"  [{i}] {cand}")
        if '])[1]' in cand:
            print(f"      ✅ [1] 索引正确")
        else:
            print(f"      ❌ [1] 索引错误")

    print()
    return converted_1


def test_case_2():
    """测试用例 2：第2个网络下拉框 (nth=2)"""
    print("=" * 80)
    print("测试用例 2: 第2个网络下拉框 (nth=2)")
    print("=" * 80)

    # 模拟 case_generator.py 生成的 expand_xpath (nth=2)
    # 格式: (base_xpath)[2]
    input_locator_2 = (
        "xpath=(//*[contains(text(),'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner'])[2]"
    )

    print(f"\n输入 (nth=2):")
    print(f"  {input_locator_2}")

    # 调用转换函数
    converted_2 = _convert_input_to_el_select(input_locator_2)

    print(f"\n转换后:")
    print(f"  {converted_2}")

    # 检查 [2] 是否保留
    if '])[2]' in converted_2:
        print("\n✅ [PASS] [2] 索引正确保留")
    else:
        print(f"\n❌ [FAIL] [2] 索引丢失或错误")
        print(f"  期望包含: ')[2]'")
        print(f"  实际结果: {converted_2}")

    # 测试双候选生成
    print(f"\n双候选生成:")
    input_xpath_2 = input_locator_2[6:]  # 去掉 xpath= 前缀
    candidates_2 = _generate_el_select_candidates(input_xpath_2)

    for i, cand in enumerate(candidates_2):
        print(f"  [{i}] {cand}")
        if '])[2]' in cand:
            print(f"      ✅ [2] 索引正确")
        else:
            print(f"      ❌ [2] 索引错误")

    print()
    return converted_2


def test_case_3():
    """测试用例 3：带 hidden filter 的 input (nth=2)"""
    print("=" * 80)
    print("测试用例 3: 带 hidden filter 的 input (nth=2)")
    print("=" * 80)

    # 模拟 PagesWriter 注入 hidden filter 后的 locator
    input_locator_3 = (
        "xpath=(//*[contains(text(),'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner'"
        " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
        " and not(ancestor-or-self::*[contains(@style,'display: none')])])[2]"
    )

    print(f"\n输入 (nth=2, 带 hidden filter):")
    print(f"  {input_locator_3}")

    # 调用转换函数
    converted_3 = _convert_input_to_el_select(input_locator_3)

    print(f"\n转换后:")
    print(f"  {converted_3}")

    # 检查 [2] 是否保留
    if '])[2]' in converted_3:
        print("\n✅ [PASS] [2] 索引正确保留")
    else:
        print(f"\n❌ [FAIL] [2] 索引丢失或错误")
        print(f"  期望包含: ')[2]'")
        print(f"  实际结果: {converted_3}")

    print()
    return converted_3


def test_case_4():
    """测试用例 4：无 () 包裹的 input (应该自动添加 ()[1])"""
    print("=" * 80)
    print("测试用例 4: 无 () 包裹的 input (应该自动添加 ()[1])")
    print("=" * 80)

    # 无 () 包裹的 input
    input_locator_4 = (
        "xpath=//label[contains(.,'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner']"
    )

    print(f"\n输入 (无 () 包裹):")
    print(f"  {input_locator_4}")

    # 调用转换函数
    converted_4 = _convert_input_to_el_select(input_locator_4)

    print(f"\n转换后:")
    print(f"  {converted_4}")

    # 检查是否自动添加了 ()[1]
    if 'xpath=(' in converted_4 and '())[1]' in converted_4:
        print("\n✅ [PASS] 自动添加了 ()[1]")
    else:
        print(f"\n❌ [FAIL] 未正确添加 ()[1]")
        print(f"  期望格式: 'xpath=(...)[1]'")
        print(f"  实际结果: {converted_4}")

    print()
    return converted_4


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("el-select [nth] 索引转换测试")
    print("=" * 80 + "\n")

    results = []

    try:
        results.append(("Case 1 (nth=1)", test_case_1()))
        results.append(("Case 2 (nth=2)", test_case_2()))
        results.append(("Case 3 (nth=2 + hidden filter)", test_case_3()))
        results.append(("Case 4 (无 () 包裹)", test_case_4()))

        print("\n" + "=" * 80)
        print("总结")
        print("=" * 80)

        for name, result in results:
            print(f"\n{name}:")
            print(f"  {result}")

        sys.exit(0)

    except Exception as e:
        print(f"\n❌ [ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
