#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 2: 验证 KB 生成的定位器是否缺少 [nth] 索引

问题假设：
- case_generator.py 生成的原始 locator 有 [2]: (base_xpath)[2]
- 但 Phase 6 调用 _get_kb_locators(elem_type, label) 时，KB 模板没有 nth 信息
- 所以 KB 生成的候选都是无索引或默认 [1]
- 导致第一个和第二个下拉框的 KB 候选一样
"""

import sys
import os

# Windows 控制台编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加 tools 目录到路径
tools_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '.claude', 'skills', 'generate-ui-test', 'tools'))
sys.path.insert(0, tools_dir)

from verification.data_layer import _get_kb_locators
from verification.verify_engine import _generate_el_select_candidates

def test_kb_locators():
    """测试 KB 生成的定位器是否缺少 [nth] 索引"""
    print("=" * 80)
    print("测试: KB 生成的定位器是否有 [nth] 索引")
    print("=" * 80)

    # 模拟 Phase 6 调用 _get_kb_locators
    elem_type = 'el-select'
    label = '网络'

    print(f"\n调用参数:")
    print(f"  elem_type={elem_type}")
    print(f"  label='{label}'")

    kb_locators = _get_kb_locators(elem_type, label)

    print(f"\nKB 生成的 {len(kb_locators)} 个定位器:")
    for i, loc in enumerate(kb_locators):
        print(f"\n  [{i}] {loc}")

        # 检查是否有 [nth] 索引
        if '])[' in loc:
            # 提取索引
            import re
            m = re.search(r'\]\)\[(\d+)\]$', loc)
            if m:
                nth = m.group(1)
                print(f"      ✅ 有索引: [{nth}]")
            else:
                print(f"      ❌ 有 )[] 但格式异常")
        elif '])[1]' in loc:
            print(f"      ✅ 有索引: [1]")
        else:
            print(f"      ❌ 无索引 (默认匹配第一个)")

    print()
    return kb_locators


def test_original_vs_kb():
    """对比原始 locator 和 KB 生成的 locator"""
    print("=" * 80)
    print("对比: 原始 locator vs KB locator")
    print("=" * 80)

    # case_generator.py 生成的原始 locator (nth=2)
    original_locator_2 = (
        "xpath=(//*[contains(text(),'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner'])[2]"
    )

    print(f"\n原始 locator (第2个网络下拉框):")
    print(f"  {original_locator_2}")

    # KB 生成的定位器
    kb_locators = _get_kb_locators('el-select', '网络')

    print(f"\nKB 生成的定位器 (共 {len(kb_locators)} 个):")

    # 检查 KB 定位器是否与原始 locator 匹配
    for i, kb_loc in enumerate(kb_locators):
        print(f"\n  [{i}] {kb_loc}")

        # 检查是否有 [2]
        if '])[2]' in kb_loc:
            print(f"      ✅ 有 [2] 索引，可以匹配第2个下拉框")
        elif '])[1]' in kb_loc:
            print(f"      ❌ 只有 [1] 索引，会匹配第1个下拉框")
        elif 'input[@class' in kb_loc and '])[1]' not in kb_loc:
            print(f"      ❌ 无索引，默认匹配第1个下拉框")

    print()


def test_dual_candidates_with_nth():
    """测试双候选生成时是否正确应用 [nth]"""
    print("=" * 80)
    print("测试: 双候选生成时 [nth] 索引传递")
    print("=" * 80)

    # 模拟 KB 生成的 input locator (无 [nth])
    kb_input_locator_no_nth = (
        "//*[contains(text(),'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner']"
    )

    print(f"\nKB 生成的 input locator (无 [nth]):")
    print(f"  {kb_input_locator_no_nth}")

    # 调用 _generate_el_select_candidates
    candidates = _generate_el_select_candidates(kb_input_locator_no_nth)

    print(f"\n生成的双候选 (共 {len(candidates)} 个):")
    for i, cand in enumerate(candidates):
        print(f"\n  [{i}] {cand}")

        # 检查是否有 [nth]
        if '])[' in cand:
            print(f"      有索引包裹")
        else:
            print(f"      ❌ 无索引，会匹配第一个")

    print()

    # 模拟 KB 生成的 input locator (有 [2])
    kb_input_locator_with_nth = (
        "(//*[contains(text(),'网络')]"
        "/following-sibling::*[self::div or self::span]"
        "//input[@class='el-input__inner'])[2]"
    )

    print(f"\n如果 KB locator 有 [2]:")
    print(f"  {kb_input_locator_with_nth}")

    candidates_with_nth = _generate_el_select_candidates(kb_input_locator_with_nth)

    print(f"\n生成的双候选 (共 {len(candidates_with_nth)} 个):")
    for i, cand in enumerate(candidates_with_nth):
        print(f"\n  [{i}] {cand}")

        if '])[2]' in cand:
            print(f"      ✅ [2] 索引正确保留")
        else:
            print(f"      ❌ [2] 索引丢失")

    print()


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("el-select [nth] 索引传递测试")
    print("=" * 80 + "\n")

    try:
        test_kb_locators()
        test_original_vs_kb()
        test_dual_candidates_with_nth()

        print("\n" + "=" * 80)
        print("结论")
        print("=" * 80)
        print("""
问题确认:
1. _get_kb_locators(elem_type, label) 生成的 KB 模板没有 [nth] 索引
2. 原始 locator 有 [2]，但 KB 候选没有
3. Phase 6 验证时，KB 候选都是 [1]，导致第一个下拉框被点击两次

根因:
- KB 模板是通用的，不知道当前是第几个下拉框
- Phase 6 调用 _get_kb_locators 时没有传递 nth 信息
- 需要从原始 locator 中提取 [nth] 并应用到 KB 候选

修复方案:
- Phase 6 的 execute_step 应该从 raw_locator_ref 中提取 field 名称
- 从 field 名称推断 nth (如 field_7ddbe1_2_expand → nth=2)
- 将 [nth] 应用到所有 KB 生成的候选定位器
""")

        sys.exit(0)

    except Exception as e:
        print(f"\n❌ [ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
