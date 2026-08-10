"""
测试内嵌变量解析修复
验证修复：inline ${data.field} 变量在 locator 中正确解析
"""
import sys
import os

# 添加 tools 目录到路径
_TOOLS_DIR = r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools'
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from verification.data_layer import resolve_locator, resolve_var


def test_inline_var_resolution():
    """测试1: 内嵌 ${data.field} 在 XPath 中正确解析"""
    pages = {'estack_vm_elements': {'btn': 'xpath=//button'}}
    data = {
        'estack_data.case01_field_0eaa6a_card_value': 'ARM 计算',
        'estack_data.case01_field_31ecc0_option': 'Project-060f0629'
    }

    # Case A: 内嵌变量的 XPath（架构 ARM 计算场景）
    loc = "xpath=(//label[contains(.,'架构')]//*[contains(text(),'${estack_data.case01_field_0eaa6a_card_value}')])[1]"
    resolved = resolve_var(loc, data)
    assert '${' not in resolved, f"变量未解析: {resolved}"
    assert 'ARM 计算' in resolved, f"预期值未出现: {resolved}"
    print(f"[OK] Case A: {resolved}")

    # Case B: 内嵌变量的 XPath（项目选项场景）
    loc2 = "xpath=(//div[@x-placement and not(@x-placement='')]//li[contains(.,'${estack_data.case01_field_31ecc0_option}')])[1]"
    resolved2 = resolve_var(loc2, data)
    assert '${' not in resolved2, f"变量未解析: {resolved2}"
    assert 'Project-060f0629' in resolved2, f"预期值未出现: {resolved2}"
    print(f"[OK] Case B: {resolved2}")


def test_pages_var_resolution():
    """测试2: 纯 ${pages.field} 变量正常解析（回归测试）"""
    pages = {
        'estack_vm_elements': {
            'btn': 'xpath=//button',
            'input': 'xpath=//input[@type="text"]'
        }
    }
    data = {}

    # Case A: 纯 pages 变量
    locator = resolve_locator({'locator': '${estack_vm_elements.btn}'}, pages)
    assert locator == 'xpath=//button', f"解析失败: {locator}"
    print(f"[OK] Case A: {locator}")

    # Case B: 解析后再调用 resolve_var（应该无影响）
    resolved = resolve_var(locator, data)
    assert resolved == locator, f"不应被修改: {resolved}"
    print(f"[OK] Case B: {resolved}")


def test_empty_locator_handling():
    """测试3: 空 locator 正确处理"""
    pages = {}
    data = {}

    # Case A: 不存在的 pages 字段 → 返回空字符串
    locator = resolve_locator({'locator': '${missing.field}'}, pages)
    assert locator == '', f"预期空字符串，实际: {locator}"
    print(f"[OK] Case A: 空字符串")

    # Case B: 空字符串 + resolve_var → 仍为空
    resolved = resolve_var(locator, data)
    assert resolved == '', f"预期空字符串，实际: {resolved}"
    print(f"[OK] Case B: 空字符串保持不变")


def test_partial_var_preservation():
    """测试4: 部分变量（data中不存在）保持原样"""
    pages = {}
    data = {'estack_data.exists': 'value'}

    # Case A: data 中不存在的变量保持原样
    loc = "xpath=//*[contains(.,'${estack_data.missing}')]"
    resolved = resolve_var(loc, data)
    assert '${estack_data.missing}' in resolved, f"不存在的变量应保持原样: {resolved}"
    print(f"[OK] Case A: {resolved}")

    # Case B: 混合存在和不存在的变量
    loc2 = "xpath=//*[text()='${estack_data.exists}'][@class='${estack_data.missing}']"
    resolved2 = resolve_var(loc2, data)
    assert 'value' in resolved2, f"存在的变量应被解析: {resolved2}"
    assert '${estack_data.missing}' in resolved2, f"不存在的变量应保持原样: {resolved2}"
    print(f"[OK] Case B: {resolved2}")


if __name__ == '__main__':
    print("=" * 60)
    print("测试内嵌变量解析修复")
    print("=" * 60)

    test_inline_var_resolution()
    print()

    test_pages_var_resolution()
    print()

    test_empty_locator_handling()
    print()

    test_partial_var_preservation()
    print()

    print("=" * 60)
    print("[OK] 所有测试通过")
    print("=" * 60)
