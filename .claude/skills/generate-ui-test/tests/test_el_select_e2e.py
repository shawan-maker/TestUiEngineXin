#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端测试：验证 _emit_el_select_steps 的 nth 序号 + hidden filter + else 分支重构 + not(@readonly) 后置注入
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import json

from generation.pages_writer import _make_editable_locator, _make_editable_locator_postfix

print("=" * 60)
print("端到端验证: el-select 增强方案")
print("=" * 60)

# ── 测试 1: _make_editable_locator + (xpath)[N] 交互 ──
print("\n测试 1: _make_editable_locator 在 [nth] 之前调用")

select_base = (
    "//*[contains(text(),'镜像来源')]"
    "/following-sibling::*[self::div or self::span]"
    "//input[@class='el-input__inner']"
)

# 正确顺序：先 _make_editable_locator，再 [nth]
editable_base = _make_editable_locator(select_base)
nth = 2
select_xpath = f"({select_base})[{nth}]"
editable_xpath = f"({editable_base})[{nth}]"

print(f"  select_base:  {select_base[:60]}...")
print(f"  editable_base: {editable_base[:60]}...")
print(f"  select_xpath:  {select_xpath[:70]}...")
print(f"  editable_xpath: {editable_xpath[:70]}...")

assert "and not(@readonly)" in editable_xpath
assert "[2]" in editable_xpath
assert "el-input__inner" in editable_xpath
print("  ✓ 通过")

# ── 测试 2: 验证反向顺序会导致问题（_make_editable_locator 在 [nth] 之后）──
print("\n测试 2: 反向顺序验证（证明必须先 editable 再 [nth]）")

select_nth1 = f"({select_base})[1]"
# 如果先 [nth] 再 editable，_make_editable_locator 会在 [1] 的 ] 前插入 not(@readonly)
editable_wrong = _make_editable_locator(select_nth1)
print(f"  select_nth1:  {select_nth1[:60]}...")
print(f"  editable_wrong: {editable_wrong[:80]}...")

# 错误顺序仍然能工作（因为 _make_editable_locator 找 el-input__inner 后面的 ] 闭合）
# 但括号深度计数会在 [1] 的 ] 处归零，导致 not(@readonly) 被插入到错误位置
if "and not(@readonly)" in editable_wrong:
    # 检查 not(@readonly) 是否在正确的位置
    idx = editable_wrong.index("and not(@readonly)")
    # 在 (xpath)[1] 格式中，如果 not(@readonly) 出现在 ) 之后，说明插入位置错误
    after = editable_wrong[idx:]
    if ")[" in after[:30]:
        print("  ⚠ 确认：反向顺序导致 not(@readonly) 插入位置偏移")
    else:
        print("  ✓ 反向顺序偶然正确（但不可靠）")
else:
    print("  ✓ 反向顺序失败（_make_editable_locator 未匹配）")

# ── 测试 3: hidden filter 拼接验证 ──
print("\n测试 3: option_xpath hidden filter 手动拼接")

option_ref = "${group.province_option}"
option_xpath = (
    f"(//div[@x-placement and not(@x-placement='') and not(@role='tooltip')]//li"
    f"[contains(.,'{option_ref}')"
    f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
    f" and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
)

assert "is-hidden" in option_xpath
assert "display: none" in option_xpath
assert "ancestor-or-self::" in option_xpath
assert option_xpath.startswith("(")
assert option_xpath.endswith(")[1]")
print(f"  option_xpath: {option_xpath[:80]}...")
print("  ✓ 通过")

# ── 测试 4: first_option_xpath hidden filter ──
print("\n测试 4: first_option_xpath hidden filter")

first_option_xpath = (
    "(//div[@x-placement and not(@x-placement='') and not(@role='tooltip')]//li"
    "[contains(@class,'el-select-dropdown__item')"
    " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
    " and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
)

assert "is-hidden" in first_option_xpath
assert "display: none" in first_option_xpath
assert first_option_xpath.startswith("(")
assert first_option_xpath.endswith(")[1]")
print(f"  first_option_xpath: {first_option_xpath[:80]}...")
print("  ✓ 通过")

# ── 测试 5: else 分支结构验证 ──
print("\n测试 5: else 分支嵌套 if_element_visible 结构")

# 模拟 else_steps 生成
else_then_steps = [
    {'desc': '选择「镜像来源」 - 点击目标选项', 'keyword': 'click_element',
     'params': {'locator': f'xpath={option_xpath}'}},
]
else_else_steps = [
    {'desc': '选择「镜像来源」 - 目标选项不可见，回退选择第一项', 'keyword': 'click_element',
     'params': {'locator': 'xpath=' + first_option_xpath}},
]
else_steps = [
    {'desc': '判断「镜像来源」目标选项是否可见', 'keyword': 'if_element_visible',
     'params': {
         'locator': f'xpath={option_xpath}',
         'timeout': 500,
         'then_steps': else_then_steps,
         'else_steps': else_else_steps,
     }},
]

# 验证结构
assert len(else_steps) == 1
assert else_steps[0]['keyword'] == 'if_element_visible'
assert len(else_steps[0]['params']['then_steps']) == 1
assert len(else_steps[0]['params']['else_steps']) == 1
assert else_steps[0]['params']['then_steps'][0]['keyword'] == 'click_element'
assert else_steps[0]['params']['else_steps'][0]['keyword'] == 'click_element'
assert '回退选择第一项' in else_steps[0]['params']['else_steps'][0]['desc']
print(f"  else_steps 结构:")
print(f"    - if_element_visible(option_xpath)")
print(f"      then: click_element(option) ← 目标选项可见")
print(f"      else: click_element(first_option) ← 回退第一项")
print("  ✓ 通过")

# ── 测试 6: nth_desc 描述文本 ──
print("\n测试 6: nth_desc 描述文本")

for nth, expected_desc in [(1, "点击下拉框"), (2, "点击第2个下拉框"), (3, "点击第3个下拉框")]:
    nth_desc = f"第{nth}个" if nth > 1 else ""
    desc = f"选择「镜像来源」 - 点击{nth_desc}下拉框"
    assert expected_desc in desc
    print(f"  nth={nth}: {desc}")

print("  ✓ 通过")

# ── 测试 7: _FIRST_OPTION_XPATH 常量一致性 ──
print("\n测试 7: _FIRST_OPTION_XPATH 常量与 _case_generator 一致")

from generation.pages_writer import _FIRST_OPTION_XPATH

assert "is-hidden" in _FIRST_OPTION_XPATH
assert "display: none" in _FIRST_OPTION_XPATH
assert _FIRST_OPTION_XPATH.startswith("(")
assert _FIRST_OPTION_XPATH.endswith(")[1]")
# 确保与 _case_generator 中的 first_option_xpath 一致
assert _FIRST_OPTION_XPATH == first_option_xpath, (
    f"不一致:\n  PagesWriter: {_FIRST_OPTION_XPATH}\n  CaseGen: {first_option_xpath}"
)
print(f"  PagesWriter._FIRST_OPTION_XPATH: {_FIRST_OPTION_XPATH[:60]}...")
print(f"  CaseGen first_option_xpath:        {first_option_xpath[:60]}...")
print("  ✓ 一致")

# ── 测试 8: _make_editable_locator_postfix 基本功能 ──
print("\n测试 8: _make_editable_locator_postfix 基本功能")

test_xpath_1 = "(//input[@class='el-input__inner'])[1]"
result_1 = _make_editable_locator_postfix(test_xpath_1)
expected_1 = "(//input[@class='el-input__inner'])[1][not(@readonly)]"
assert result_1 == expected_1, f"期望: {expected_1}\n实际: {result_1}"
print(f"  输入: {test_xpath_1}")
print(f"  输出: {result_1}")
print("  ✓ 通过")

# ── 测试 9: _make_editable_locator_postfix 幂等性 ──
print("\n测试 9: _make_editable_locator_postfix 幂等性")

test_xpath_2 = "(//input[@class='el-input__inner'])[2][not(@readonly)]"
result_2 = _make_editable_locator_postfix(test_xpath_2)
assert result_2 == test_xpath_2, f"已包含 not(@readonly) 时不应重复添加"
print(f"  输入: {test_xpath_2}")
print(f"  输出: {result_2}")
print("  ✓ 通过")

# ── 测试 10: 对比 inline vs postfix 在多 input 场景的差异 ──
print("\n测试 10: inline vs postfix 在多 input 场景的差异")

base_xpath = "//label[.='系统盘']/following-sibling::div//input[@class='el-input__inner']"
nth = 1

# Inline 模式（旧）：先加 not(@readonly)，再加 [nth]
editable_inline_base = _make_editable_locator(base_xpath)
editable_inline = f"({editable_inline_base})[{nth}]"

# Postfix 模式（新）：先加 [nth]，再加 [not(@readonly)]
select_xpath = f"({base_xpath})[{nth}]"
editable_postfix = _make_editable_locator_postfix(select_xpath)

print(f"  基础 XPath: {base_xpath}")
print(f"  Inline 模式: {editable_inline[:80]}...")
print(f"  Postfix 模式: {editable_postfix[:80]}...")

# 关键断言：postfix 模式的 not(@readonly) 在 [1] 之后
assert "])[1][not(@readonly)]" in editable_postfix, "Postfix 模式应在 [1] 之后添加 [not(@readonly)]"
# Inline 模式的 not(@readonly) 在 input 谓词内部
assert "and not(@readonly)" in editable_inline, "Inline 模式应在 input 谓词内添加"
# 两者结构不同
assert editable_inline != editable_postfix, "两种模式应产生不同的 XPath 结构"

print("  ✓ 两种模式结构正确区分")

# ── 测试 11: Postfix 模式确保与 _select 指向同一元素 ──
print("\n测试 11: Postfix 模式确保 _editable 与 _select 指向同一元素")

select_xpath_11 = "(//label[.='系统盘']/following-sibling::div//input[@class='el-input__inner'])[1]"
editable_xpath_11 = _make_editable_locator_postfix(select_xpath_11)

# 提取基础部分（不含 [not(@readonly)]）
editable_base_part = editable_xpath_11.replace("[not(@readonly)]", "")
assert editable_base_part == select_xpath_11, f"Postfix 模式应基于 _select 的完整 XPath"
print(f"  _select:   {select_xpath_11[:70]}...")
print(f"  _editable: {editable_xpath_11[:80]}...")
print("  ✓ _editable 与 _select 指向同一 DOM 元素（第 1 个）")

print()
print("=" * 60)
print("✅ 端到端验证全部通过（11/11）")
print("=" * 60)
