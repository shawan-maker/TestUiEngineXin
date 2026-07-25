#!/usr/bin/env python3
"""xpath_utils 单元测试 — 容器前缀操作函数

验证 has_container_prefix / apply_container_prefix / detect_container_type 三个公共函数
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from xpath_utils import (
    has_container_prefix,
    apply_container_prefix,
    detect_container_type,
    CONTAINER_XPATH,
    CONTAINER_CLASS_PATTERNS,
)


# ============================================================================
# Part 1: has_container_prefix 测试
# ============================================================================
print("=" * 60)
print("Part 1: has_container_prefix")
print("=" * 60)

# 1.1 正向测试 — 三种容器类型
assert has_container_prefix("//div[contains(@class,'el-drawer')]//button") is True
print("✓ 1.1.1 drawer 前缀检测")

assert has_container_prefix("//div[contains(@class,'el-dialog')]//button") is True
print("✓ 1.1.2 dialog 前缀检测")

assert has_container_prefix("//div[contains(@class,'el-message-box')]//button") is True
print("✓ 1.1.3 message-box 前缀检测")

# 1.2 负向测试 — 无前缀
assert has_container_prefix("//button[contains(.,'确认')]") is False
print("✓ 1.2.1 无前缀 XPath")

assert has_container_prefix("//div[contains(@class,'el-table')]//button") is False
print("✓ 1.2.2 其他组件前缀")

# 1.3 边界情况
assert has_container_prefix("") is False
print("✓ 1.3.1 空字符串")

assert has_container_prefix(None) is False
print("✓ 1.3.2 None")

assert has_container_prefix("not a xpath") is False
print("✓ 1.3.3 非 XPath 字符串")

# 1.4 位置包裹
assert has_container_prefix("(//div[contains(@class,'el-drawer')]//button)[1]") is True
print("✓ 1.4.1 (xpath)[N] 包裹")

assert has_container_prefix("(//div[contains(@class,'el-dialog')]//button)[last()]") is True
print("✓ 1.4.2 (xpath)[last()] 包裹")

# 1.5 xpath= 前缀
assert has_container_prefix("xpath=//div[contains(@class,'el-drawer')]//button") is True
print("✓ 1.5.1 xpath= 前缀 + 容器前缀")

print()

# ============================================================================
# Part 2: apply_container_prefix 测试
# ============================================================================
print("=" * 60)
print("Part 2: apply_container_prefix")
print("=" * 60)

# 2.1 基础功能 — 三种容器类型
xpath = "//button[contains(.,'确认')]"
result = apply_container_prefix(xpath, 'drawer')
assert result == "//div[contains(@class,'el-drawer')]" + xpath
print("✓ 2.1.1 drawer 前缀添加")

result = apply_container_prefix(xpath, 'dialog')
assert result == "//div[contains(@class,'el-dialog')]" + xpath
print("✓ 2.1.2 dialog 前缀添加")

result = apply_container_prefix(xpath, 'message-box')
assert result == "//div[contains(@class,'el-message-box')]" + xpath
print("✓ 2.1.3 message-box 前缀添加")

# 2.2 幂等性 — 已有前缀不重复添加
xpath_with_prefix = "//div[contains(@class,'el-drawer')]//button"
result = apply_container_prefix(xpath_with_prefix, 'drawer')
assert result == xpath_with_prefix
print("✓ 2.2.1 已有 drawer 前缀不重复")

result = apply_container_prefix(xpath_with_prefix, 'dialog')
assert result == xpath_with_prefix  # 已有 drawer，不再加 dialog
print("✓ 2.2.2 已有 drawer 前缀不加 dialog")

# 2.3 BUG-13 保护 — (xpath)[N] 包裹
xpath_wrapped = "(//button[contains(.,'确认')])[1]"
result = apply_container_prefix(xpath_wrapped, 'drawer')
assert result == "(//div[contains(@class,'el-drawer')]//button[contains(.,'确认')])[1]"
print("✓ 2.3.1 (xpath)[1] 包裹正确解包和重新包裹")

xpath_last = "(//button[contains(.,'确认')])[last()]"
result = apply_container_prefix(xpath_last, 'dialog')
assert result == "(//div[contains(@class,'el-dialog')]//button[contains(.,'确认')])[last()]"
print("✓ 2.3.2 (xpath)[last()] 包裹正确解包和重新包裹")

# 2.4 相对路径保护 — 不以 // 开头不添加前缀
xpath_relative = ".//button[contains(.,'确认')]"
result = apply_container_prefix(xpath_relative, 'drawer')
assert result == xpath_relative
print("✓ 2.4.1 相对路径 .// 不添加前缀")

xpath_single = "/html/body//button"
result = apply_container_prefix(xpath_single, 'drawer')
assert result == xpath_single
print("✓ 2.4.2 绝对路径 /html 不添加前缀")

# 2.5 无效参数保护
result = apply_container_prefix(xpath, None)
assert result == xpath
print("✓ 2.5.1 container_type=None 不添加前缀")

result = apply_container_prefix(xpath, '')
assert result == xpath
print("✓ 2.5.2 container_type='' 不添加前缀")

result = apply_container_prefix(xpath, 'invalid-type')
assert result == xpath
print("✓ 2.5.3 container_type='invalid-type' 不添加前缀")

result = apply_container_prefix(None, 'drawer')
assert result is None
print("✓ 2.5.4 xpath=None 返回 None")

result = apply_container_prefix('', 'drawer')
assert result == ''
print("✓ 2.5.5 xpath='' 返回 ''")

# 2.6 new_page 上下文（非容器类型）
result = apply_container_prefix(xpath, 'new_page')
assert result == xpath
print("✓ 2.6.1 container_type='new_page' 不添加前缀")

# 2.7 复杂 XPath — el-select KB 标准模式
xpath_el_select = "//*[contains(text(),'状态')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
result = apply_container_prefix(xpath_el_select, 'drawer')
expected = "//div[contains(@class,'el-drawer')]" + xpath_el_select
assert result == expected
print("✓ 2.7.1 el-select KB 标准模式 XPath")

# 2.8 复杂 XPath — option-card KB 标准模式
xpath_option_card = "//label[contains(*,'架构')]//following-sibling::*[self::div or self::span]//*[contains(text(),'ARM计算型')]"
result = apply_container_prefix(xpath_option_card, 'dialog')
expected = "//div[contains(@class,'el-dialog')]" + xpath_option_card
assert result == expected
print("✓ 2.8.1 option-card KB 标准模式 XPath")

print()

# ============================================================================
# Part 3: detect_container_type 测试
# ============================================================================
print("=" * 60)
print("Part 3: detect_container_type")
print("=" * 60)

# 3.1 正向测试 — 三种容器类型
assert detect_container_type("//div[contains(@class,'el-drawer')]//button") == 'drawer'
print("✓ 3.1.1 drawer 类型检测")

assert detect_container_type("//div[contains(@class,'el-dialog')]//button") == 'dialog'
print("✓ 3.1.2 dialog 类型检测")

assert detect_container_type("//div[contains(@class,'el-message-box')]//button") == 'message-box'
print("✓ 3.1.3 message-box 类型检测")

# 3.2 负向测试 — 无前缀
assert detect_container_type("//button[contains(.,'确认')]") is None
print("✓ 3.2.1 无前缀返回 None")

assert detect_container_type("//div[contains(@class,'el-table')]//button") is None
print("✓ 3.2.2 其他组件前缀返回 None")

# 3.3 边界情况
assert detect_container_type("") is None
print("✓ 3.3.1 空字符串返回 None")

assert detect_container_type(None) is None
print("✓ 3.3.2 None 返回 None")

assert detect_container_type("not a xpath") is None
print("✓ 3.3.3 非 XPath 字符串返回 None")

# 3.4 位置包裹
assert detect_container_type("(//div[contains(@class,'el-drawer')]//button)[1]") == 'drawer'
print("✓ 3.4.1 (xpath)[N] 包裹检测")

# 3.5 xpath= 前缀
assert detect_container_type("xpath=//div[contains(@class,'el-dialog')]//button") == 'dialog'
print("✓ 3.5.1 xpath= 前缀 + 容器前缀检测")

print()

# ============================================================================
# Part 4: 集成测试 — 函数间交互
# ============================================================================
print("=" * 60)
print("Part 4: 集成测试")
print("=" * 60)

# 4.1 apply → has → detect 完整流程
xpath = "//button[contains(.,'确认')]"
result = apply_container_prefix(xpath, 'drawer')
assert has_container_prefix(result) is True
assert detect_container_type(result) == 'drawer'
print("✓ 4.1.1 apply → has → detect 完整流程")

# 4.2 幂等性验证 — 多次 apply 不改变结果
result1 = apply_container_prefix(xpath, 'drawer')
result2 = apply_container_prefix(result1, 'drawer')
result3 = apply_container_prefix(result2, 'drawer')
assert result1 == result2 == result3
print("✓ 4.2.1 多次 apply 幂等性")

# 4.3 容器类型切换 — 已有前缀不覆盖
result_drawer = apply_container_prefix(xpath, 'drawer')
result_dialog = apply_container_prefix(result_drawer, 'dialog')
assert result_drawer == result_dialog  # 已有 drawer，不加 dialog
assert detect_container_type(result_dialog) == 'drawer'
print("✓ 4.3.1 已有前缀不覆盖")

# 4.4 复杂场景 — (xpath)[N] + 前缀 + 检测
xpath_wrapped = "(//button[contains(.,'确认')])[1]"
result = apply_container_prefix(xpath_wrapped, 'dialog')
assert has_container_prefix(result) is True
assert detect_container_type(result) == 'dialog'
assert result.startswith("(//div[contains(@class,'el-dialog')]")
assert result.endswith(")[1]")
print("✓ 4.4.1 (xpath)[N] + 前缀 + 检测")

print()

# ============================================================================
# Part 5: 边界情况与异常处理
# ============================================================================
print("=" * 60)
print("Part 5: 边界情况与异常处理")
print("=" * 60)

# 5.1 超长 XPath
long_xpath = "//div" + "//span" * 100 + "//button"
result = apply_container_prefix(long_xpath, 'drawer')
assert result.startswith("//div[contains(@class,'el-drawer')]//div")
print("✓ 5.1.1 超长 XPath 处理")

# 5.2 嵌套括号（非位置包裹）
xpath_nested = "//button[contains(text(),'(确认)')]"
result = apply_container_prefix(xpath_nested, 'drawer')
assert result == "//div[contains(@class,'el-drawer')]" + xpath_nested
print("✓ 5.2.1 嵌套括号（非位置包裹）")

# 5.3 多重位置包裹（异常情况）
xpath_double_wrap = "((//button)[1])[2]"
result = apply_container_prefix(xpath_double_wrap, 'drawer')
# 外层包裹被识别，内层 (//button)[1] 不以 // 开头，所以不添加前缀
assert result == xpath_double_wrap
assert has_container_prefix(result) is False
print("✓ 5.3.1 多重位置包裹处理（不添加前缀）")

# 5.4 空括号位置包裹
xpath_empty_wrap = "(//button)[]"
result = apply_container_prefix(xpath_empty_wrap, 'drawer')
# 不符合 (xpath)[N] 格式，作为普通字符串处理
assert result == xpath_empty_wrap  # 不以 // 开头（以 ( 开头）
print("✓ 5.4.1 空括号位置包裹（不添加前缀）")

# 5.5 中文容器类型（无效）
result = apply_container_prefix("//button", '抽屉')
assert result == "//button"
print("✓ 5.5.1 中文容器类型不添加前缀")

# 5.6 nth 序号包裹
xpath_base = "//button[contains(.,'确认')]"
xpath_nth1 = f"({xpath_base})[1]"
result = apply_container_prefix(xpath_nth1, 'drawer')
expected = f"(//div[contains(@class,'el-drawer')]{xpath_base})[1]"
assert result == expected
print("✓ 5.6.1 (xpath)[1] + 容器前缀")

xpath_nth2 = f"({xpath_base})[2]"
result = apply_container_prefix(xpath_nth2, 'dialog')
expected = f"(//div[contains(@class,'el-dialog')]{xpath_base})[2]"
assert result == expected
print("✓ 5.6.2 (xpath)[2] + 容器前缀")

# 5.7 nth 序号 + 复杂 XPath
xpath_complex = "//*[contains(text(),'镜像来源')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
xpath_nth1 = f"({xpath_complex})[1]"
result = apply_container_prefix(xpath_nth1, 'drawer')
expected = f"(//div[contains(@class,'el-drawer')]{xpath_complex})[1]"
assert result == expected
print("✓ 5.7.1 el-select KB 标准模式 + [1] + 容器前缀")

print()

# ============================================================================
# Part 6: nth 序号后缀（el-select 增强）
# ============================================================================
print("=" * 60)
print("Part 6: nth 序号后缀（el-select 增强）")
print("=" * 60)

# 6.1 基础序号包裹
xpath = "//*[contains(text(),'省份')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
xpath_wrapped = f"({xpath})[1]"
assert has_container_prefix(xpath_wrapped) is False
print("✓ 6.1.1 (xpath)[1] 无容器前缀")

# 6.2 序号 + 容器前缀
xpath_with_container = apply_container_prefix(xpath_wrapped, 'drawer')
expected = f"(//div[contains(@class,'el-drawer')]{xpath})[1]"
assert xpath_with_container == expected
print("✓ 6.2.1 (xpath)[1] + drawer 容器前缀")

# 6.3 序号 [2]
xpath_nth2 = f"({xpath})[2]"
xpath_with_container = apply_container_prefix(xpath_nth2, 'dialog')
expected = f"(//div[contains(@class,'el-dialog')]{xpath})[2]"
assert xpath_with_container == expected
print("✓ 6.3.1 (xpath)[2] + dialog 容器前缀")

# 6.4 幂等性
result1 = apply_container_prefix(xpath_nth2, 'drawer')
result2 = apply_container_prefix(result1, 'drawer')
assert result1 == result2
print("✓ 6.4.1 多次 apply 幂等性（含序号）")

# 6.5 容器类型检测
assert detect_container_type(xpath_with_container) == 'dialog'
print("✓ 6.5.1 (xpath)[N] + 容器前缀类型检测")

# 6.6 nth=3
xpath_nth3 = f"({xpath})[3]"
xpath_with_container = apply_container_prefix(xpath_nth3, 'message-box')
expected = f"(//div[contains(@class,'el-message-box')]{xpath})[3]"
assert xpath_with_container == expected
print("✓ 6.6.1 (xpath)[3] + message-box 容器前缀")

# 6.7 序号包裹 + 已有容器前缀
xpath_with_prefix = f"(//div[contains(@class,'el-drawer')]{xpath})[1]"
result = apply_container_prefix(xpath_with_prefix, 'dialog')
assert result == xpath_with_prefix  # 已有前缀，不覆盖
print("✓ 6.7.1 (xpath)[1] + 已有 drawer 前缀不加 dialog")

# 6.8 序号包裹 + 相对路径（不添加前缀）
xpath_relative = f"(.//button)[1]"
result = apply_container_prefix(xpath_relative, 'drawer')
assert result == xpath_relative
print("✓ 6.8.1 (.//button)[1] 相对路径不添加前缀")

print()

# ============================================================================
# 总结
# ============================================================================
print("=" * 60)
print("✓ 所有测试通过")
print("=" * 60)
print()
print("测试覆盖:")
print("  - has_container_prefix: 9 个用例")
print("  - apply_container_prefix: 22 + 8 个用例（含 nth 序号）")
print("  - detect_container_type: 9 个用例")
print("  - 集成测试: 4 个用例")
print("  - 边界情况: 5 个用例")
print()
print("总计: 57 个测试用例")
