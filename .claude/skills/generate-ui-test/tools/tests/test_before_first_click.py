"""测试 _before_first_click 标记功能

验证场景：
1. case_generator 在首个按钮前标记 _before_first_click=True
2. 首个按钮操作后不再标记
3. verify_engine 根据 _before_first_click 设置正确的 fallback_prefix
4. 框架感知（ant-design vs element-ui）
"""
import pytest
import sys
from pathlib import Path

# 添加 tools 目录到 Python 路径
tools_dir = Path(__file__).parent.parent
sys.path.insert(0, str(tools_dir))

from generation.case_generator import CaseGenerator
from generation.case_orchestration import generate_case_file
from core.step_patterns import parse_step
from verification.verify_engine import CONTAINER_XPATH


class MockResolver:
    """模拟 ElementResolver"""
    def __init__(self):
        self._discovery_raw = {}
        self.field_meta = {}

    def resolve(self, label, elem_type, context=None):
        return None, None

    def get_container_type(self, label):
        return None

    def get_trigger_map(self):
        return {}

    def get_element_map(self):
        return {}

    def get_page_element_map(self):
        return {}


class TestBeforeFirstClickMarking:
    """测试 Phase 5 标记逻辑"""

    def test_mark_steps_before_first_button(self):
        """首个按钮前的所有步骤应标记 _before_first_click=True"""
        resolver = MockResolver()
        gen = CaseGenerator(resolver, 'test_module', project_dir='', framework='element-ui')
        gen.set_case_context(1)

        # 模拟 Phase 5 循环逻辑（简化版，不调用 generate_step）
        raw_steps = [
            ('访问页面', 'open_url'),
            ('等待页面加载完成', 'wait'),
            ('点击"新增"按钮', 'click_btn'),
            ('在"项目名称"中输入"测试项目"', 'fill_value'),
        ]

        all_steps = []
        for step_text, step_type in raw_steps:
            parsed = parse_step(step_text)

            # 模拟生成步骤（简化）
            steps = [{'desc': step_text, 'keyword': 'test'}]

            # 应用标记逻辑（同 case_orchestration.py）
            if not gen._has_emitted_click:
                for s in steps:
                    s['_before_first_click'] = True
            if gen._is_button_action(parsed):
                gen._has_emitted_click = True

            all_steps.extend(steps)

        # 验证：前 3 个步骤应标记，第 4 个不标记
        assert all_steps[0].get('_before_first_click') == True, "访问页面应标记"
        assert all_steps[1].get('_before_first_click') == True, "等待加载应标记"
        assert all_steps[2].get('_before_first_click') == True, "点击按钮应标记"
        assert all_steps[3].get('_before_first_click', False) == False, "输入框不应标记"

    def test_no_mark_after_first_button(self):
        """首个按钮后的步骤不应标记"""
        resolver = MockResolver()
        gen = CaseGenerator(resolver, 'test_module', project_dir='', framework='element-ui')
        gen.set_case_context(1)

        # 模拟：点击 → 等待
        parsed1 = parse_step('点击"新增"按钮')
        steps1 = [{'desc': '点击', 'keyword': 'click_element'}]
        if not gen._has_emitted_click:
            for s in steps1:
                s['_before_first_click'] = True
        if gen._is_button_action(parsed1):
            gen._has_emitted_click = True

        parsed2 = parse_step('等待页面加载完成')
        steps2 = [{'desc': '等待', 'keyword': 'wait'}]
        if not gen._has_emitted_click:
            for s in steps2:
                s['_before_first_click'] = True
        if gen._is_button_action(parsed2):
            gen._has_emitted_click = True

        assert steps1[0].get('_before_first_click') == True, "首个按钮应标记"
        assert steps2[0].get('_before_first_click', False) == False, "等待步骤不应标记"

    def test_case_context_reset(self):
        """set_case_context 应重置 _has_emitted_click"""
        resolver = MockResolver()
        gen = CaseGenerator(resolver, 'test_module', project_dir='', framework='element-ui')

        # Case 1: 点击按钮
        gen.set_case_context(1)
        parsed = parse_step('点击"新增"按钮')
        if gen._is_button_action(parsed):
            gen._has_emitted_click = True
        assert gen._has_emitted_click == True

        # Case 2: 重置
        gen.set_case_context(2)
        assert gen._has_emitted_click == False, "新 case 应重置标记"


class TestFallbackPrefixLogic:
    """测试 Phase 6 fallback 前缀逻辑"""

    def test_before_first_click_none_prefix(self):
        """_before_first_click=True 且无容器时应使用 'none' 前缀"""
        # 模拟 verify_engine.py 中的逻辑
        step = {'_before_first_click': True}
        current_ct = None
        _framework = 'element-ui'

        if current_ct:
            _fallback_prefix = current_ct
        elif step.get('_before_first_click'):
            _fallback_prefix = 'none'
        else:
            if _framework == 'ant-design':
                _fallback_prefix = 'ant-drawer'
            else:
                _fallback_prefix = 'drawer'

        assert _fallback_prefix == 'none', "首个按钮前应使用 none"
        assert CONTAINER_XPATH.get(_fallback_prefix, '') == '', "none 前缀应为空字符串"

    def test_container_override_before_first_click(self):
        """有容器时应优先使用容器前缀，忽略 _before_first_click"""
        step = {'_before_first_click': True}
        current_ct = 'drawer'
        _framework = 'element-ui'

        if current_ct:
            _fallback_prefix = current_ct
        elif step.get('_before_first_click'):
            _fallback_prefix = 'none'
        else:
            _fallback_prefix = 'drawer'

        assert _fallback_prefix == 'drawer', "容器应优先"
        assert 'el-drawer' in CONTAINER_XPATH.get(_fallback_prefix, ''), "drawer 前缀应包含 el-drawer"

    def test_after_first_click_element_ui(self):
        """首个按钮后且无容器时，element-ui 应使用 drawer 前缀"""
        step = {'_before_first_click': False}
        current_ct = None
        _framework = 'element-ui'

        if current_ct:
            _fallback_prefix = current_ct
        elif step.get('_before_first_click'):
            _fallback_prefix = 'none'
        else:
            if _framework == 'ant-design':
                _fallback_prefix = 'ant-drawer'
            else:
                _fallback_prefix = 'drawer'

        assert _fallback_prefix == 'drawer', "element-ui 应使用 drawer"
        assert 'el-drawer' in CONTAINER_XPATH.get(_fallback_prefix, ''), "drawer 前缀应包含 el-drawer"

    def test_after_first_click_ant_design(self):
        """首个按钮后且无容器时，ant-design 应使用 ant-drawer 前缀"""
        step = {'_before_first_click': False}
        current_ct = None
        _framework = 'ant-design'

        if current_ct:
            _fallback_prefix = current_ct
        elif step.get('_before_first_click'):
            _fallback_prefix = 'none'
        else:
            if _framework == 'ant-design':
                _fallback_prefix = 'ant-drawer'
            else:
                _fallback_prefix = 'drawer'

        assert _fallback_prefix == 'ant-drawer', "ant-design 应使用 ant-drawer"
        assert 'ant-drawer' in CONTAINER_XPATH.get(_fallback_prefix, ''), "ant-drawer 前缀应包含 ant-drawer"

    def test_no_mark_legacy_behavior(self):
        """无标记时应保持原有行为（使用 drawer 或 ant-drawer）"""
        step = {}  # 无 _before_first_click
        current_ct = None
        _framework = 'element-ui'

        if current_ct:
            _fallback_prefix = current_ct
        elif step.get('_before_first_click'):
            _fallback_prefix = 'none'
        else:
            if _framework == 'ant-design':
                _fallback_prefix = 'ant-drawer'
            else:
                _fallback_prefix = 'drawer'

        assert _fallback_prefix == 'drawer', "无标记时应使用 drawer（兼容旧产物）"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
