"""测试 compile_step 自动 tolerant 规则

验证防御性等待关键字自动添加 tolerant: true
"""
import pytest
import sys
from pathlib import Path

# 添加 tools 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from generators.compile_module_keywords import compile_step


class TestAutoTolerantRule:
    """测试自动 tolerant 规则"""

    def test_wait_for_element_hidden_auto_tolerant(self):
        """验证 wait_for_element_hidden 自动添加 tolerant"""
        step = {
            'keyword': 'wait_for_element_hidden',
            'desc': '等待 loading 消失',
            'params': {
                'locator': 'xpath=//div[@class="loading"]',
                'timeout': 10000
            }
        }

        code = compile_step(step, workflow={}, indent=0)

        # 应该包含 try/except
        assert 'try:' in code[0], f"应该包含 try:, 实际: {code[0]}"
        assert any('except Exception' in line for line in code), f"应该包含 except Exception: {code}"
        assert any('tolerant skip' in line for line in code), f"应该包含 tolerant skip: {code}"

    def test_wait_for_load_auto_tolerant(self):
        """验证 wait_for_load 自动添加 tolerant"""
        step = {
            'keyword': 'wait_for_load',
            'desc': '等待页面加载',
            'params': {'timeout': 30000}
        }

        code = compile_step(step, workflow={}, indent=0)

        # 应该包含 try/except
        assert 'try:' in code[0], f"应该包含 try:, 实际: {code[0]}"
        assert any('except Exception' in line for line in code)

    def test_wait_for_network_auto_tolerant(self):
        """验证 wait_for_network 自动添加 tolerant"""
        step = {
            'keyword': 'wait_for_network',
            'desc': '等待网络空闲',
            'params': {'timeout': 5000}
        }

        code = compile_step(step, workflow={}, indent=0)

        # 应该包含 try/except
        assert 'try:' in code[0], f"应该包含 try:, 实际: {code[0]}"
        assert any('except Exception' in line for line in code)

    def test_explicit_tolerant_false_respected(self):
        """验证显式 tolerant: false 仍然生效"""
        step = {
            'keyword': 'wait_for_element_hidden',
            'desc': '等待 loading 消失',
            'tolerant': False,  # 显式禁用
            'params': {
                'locator': 'xpath=//div[@class="loading"]',
                'timeout': 10000
            }
        }

        code = compile_step(step, workflow={}, indent=0)

        # 不应该包含 try/except
        assert 'try:' not in code[0], f"不应该包含 try:, 实际: {code[0]}"
        assert not any('except Exception' in line for line in code)

    def test_explicit_tolerant_true_still_works(self):
        """验证显式 tolerant: true 仍然生效"""
        step = {
            'keyword': 'click_element',  # 非自动 tolerant 关键字
            'desc': '点击按钮',
            'tolerant': True,  # 显式启用
            'params': {'locator': 'xpath=//button'}
        }

        code = compile_step(step, workflow={}, indent=0)

        # 应该包含 try/except
        assert 'try:' in code[0], f"应该包含 try:, 实际: {code[0]}"
        assert any('except Exception' in line for line in code)

    def test_click_element_no_auto_tolerant(self):
        """验证 click_element 不会自动添加 tolerant"""
        step = {
            'keyword': 'click_element',
            'desc': '点击按钮',
            'params': {'locator': 'xpath=//button'}
        }

        code = compile_step(step, workflow={}, indent=0)

        # 不应该包含 try/except
        assert 'try:' not in code[0], f"不应该包含 try:, 实际: {code[0]}"
        assert not any('except Exception' in line for line in code)

    def test_fill_value_no_auto_tolerant(self):
        """验证 fill_value 不会自动添加 tolerant"""
        step = {
            'keyword': 'fill_value',
            'desc': '填写输入框',
            'params': {
                'locator': 'xpath=//input',
                'value': '测试数据'
            }
        }

        code = compile_step(step, workflow={}, indent=0)

        # 不应该包含 try/except
        assert 'try:' not in code[0], f"不应该包含 try:, 实际: {code[0]}"
        assert not any('except Exception' in line for line in code)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
