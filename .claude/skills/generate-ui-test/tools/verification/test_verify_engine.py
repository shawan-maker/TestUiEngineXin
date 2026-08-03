"""Unit tests for _convert_input_to_el_select"""

import pytest
import sys
import os

# 添加 tools 目录到 Python 路径
tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, tools_dir)

from verification.verify_engine import _convert_input_to_el_select


class TestConvertInputToElSelect:
    """测试 _convert_input_to_el_select 函数"""

    def test_basic_conversion(self):
        """T1: 基础转换 + //div + ()[1]"""
        input_locator = "xpath=//label//input[@class='el-input__inner']"
        expected = "xpath=(//label//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))])[1]"
        result = _convert_input_to_el_select(input_locator)
        assert result == expected

    def test_nested_brackets(self):
        """T2: 嵌套 [] 正确处理（hidden filter）+ //div"""
        input_locator = "xpath=//label//input[@class='el-input__inner' and not(ancestor::*[contains(@style,'display: none')])]"
        expected = "xpath=(//label//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))])[1]"
        result = _convert_input_to_el_select(input_locator)
        assert result == expected

    def test_user_actual_scenario(self):
        """T3: 用户实际场景（项目字段）+ //div"""
        input_locator = "xpath=//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@style,'display: none')])]"
        expected = "xpath=(//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))])[1]"
        result = _convert_input_to_el_select(input_locator)
        assert result == expected

    def test_editable_variant_not_converted(self):
        """T4: editable 变体（带 [1][not(@readonly)]）— 只替换第一个 [] 块"""
        input_locator = "xpath=//label//input[@class='el-input__inner'][1][not(@readonly)]"
        result = _convert_input_to_el_select(input_locator)
        assert 'el-select' in result

    def test_non_input_no_conversion(self):
        """T5: 非 input 不转换"""
        input_locator = "xpath=//button[text()='确认']"
        expected = "xpath=//button[text()='确认']"
        result = _convert_input_to_el_select(input_locator)
        assert result == expected

    def test_already_wrapped_n1(self):
        """T6: 已包裹 ()[1] — 保留 [1]"""
        input_locator = "xpath=(//label//input[@class='el-input__inner'])[1]"
        result = _convert_input_to_el_select(input_locator)
        assert 'el-select' in result
        assert result.endswith(')[1]')
        # 确认没有多余包裹
        assert result.count('(') == result.count(')')

    def test_preserve_n2(self):
        """T7: 已包裹 ()[2] — 保留 [2] 不变"""
        input_locator = "xpath=(//*[contains(text(),'网络')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@style,'display: none')])])[2]"
        result = _convert_input_to_el_select(input_locator)
        assert result.endswith(')[2]')
        assert '//div[contains' in result
        assert '//*[contains(@class' not in result
        # 括号平衡
        assert result.count('(') == result.count(')')
        xpath = result[6:]
        assert xpath.count('[') == xpath.count(']')

    def test_preserve_n3(self):
        """T8: 已包裹 ()[3] — 保留 [3]"""
        input_locator = "xpath=(//label//input[@class='el-input__inner'])[3]"
        result = _convert_input_to_el_select(input_locator)
        assert result.endswith(')[3]')

    def test_bracket_counting(self):
        """T9: 括号计数验证（复杂嵌套场景）"""
        result = _convert_input_to_el_select(
            "xpath=//input[@class='el-input__inner' and not(ancestor::*[contains(@style,'display: none')])]"
        )
        assert result.count('(') == result.count(')')
        xpath = result[6:]
        assert xpath.count('[') == xpath.count(']')

    def test_no_wildcard_tag(self):
        """T10: 确认输出中不含 //*（已全部替换为 //div）"""
        test_cases = [
            "xpath=//label//input[@class='el-input__inner']",
            "xpath=(//label//input[@class='el-input__inner'])[1]",
            "xpath=(//label//input[@class='el-input__inner'])[2]",
        ]
        for tc in test_cases:
            result = _convert_input_to_el_select(tc)
            assert '//*[contains(@class,\'el-select\')' not in result, f"Found //* in: {result}"
            assert '//div[contains(@class,\'el-select\')' in result, f"Missing //div in: {result}"
