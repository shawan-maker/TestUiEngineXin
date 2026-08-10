"""
test_cross_scope_fix.py - 验证跨作用域匹配修复

修改点 1: _discovery_lookup 阈值 0.4 → 0.6
修改点 2: _update_container_context_post 推断跳过的容器

场景：删除云主机用例中的"退订"按钮
- Step 6: click_more_then_click("退订") → 触发容器打开（Phase 4 skipped）
- Step 17: click_btn("确认退订") → dialog 内，不应匹配 list_page 的"退订"
- Step 20: click_btn("退订") → dialog 内，不应匹配 list_page 的"退订"
"""

import os
import sys
import unittest
from unittest.mock import Mock

# Add tools/ to path
_TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from generation.case_generator import CaseGenerator


class TestCrossScopeFix(unittest.TestCase):
    """验证跨作用域匹配修复"""

    def setUp(self):
        """构造模拟的 generator"""
        # Mock resolver
        mock_resolver = Mock()
        mock_resolver.get_trigger_map.return_value = {
            '退订': {
                'trigger': '退订',
                'result_type': 'skipped',
                'skipped': True,
                'reason': 'button is disabled'
            }
        }
        mock_resolver.get_element_map.return_value = {
            ('list_page', '退订'): Mock(raw={
                'text': '退订',
                'type': 'button',
                'locator': "//button[text()='退订']",
                'verified': False,
                'disabled': True,
                'group_name': 'order_list_elements',
                'field_key': 'field_b30d52_btn'
            })
        }
        mock_resolver.get_page_element_map.return_value = {}
        mock_resolver.get_module.return_value = 'order'

        # Create generator with mock resolver
        self.generator = CaseGenerator(mock_resolver, 'order')

    def test_threshold_06_blocks_substring_match(self):
        """修改点 1: 阈值 0.6 阻止"确认退订"子串匹配到"退订"

        "确认退订" (4字) vs "退订" (2字) → 2/4 = 0.5 < 0.6 → 不匹配
        """
        # 模拟 Step 17: click_btn("确认退订")
        # 在 dialog 作用域内查找"确认退订"
        result = self.generator._discovery_lookup("确认退订", context='dialog')

        # 预期：无匹配（list_page 的"退订"不应被匹配）
        self.assertIsNone(result,
            "确认退订不应子串匹配到退订（0.5 < 0.6 阈值）")

    def test_threshold_06_allows_exact_match(self):
        """修改点 1: 阈值 0.6 不影响精确匹配

        "退订" == "退订" → 精确匹配 → 应返回
        """
        # 模拟在 list_page 作用域查找"退订"
        result = self.generator._discovery_lookup("退订", context='list_page')

        # 预期：精确匹配成功
        self.assertIsNotNone(result,
            "退订应精确匹配到 list_page 的退订按钮")

    def test_skipped_button_updates_container(self):
        """修改点 2: skipped 按钮推断为 dialog 容器

        Phase 4 跳过的按钮（disabled）→ 推断会打开容器 → current_container='dialog'
        """
        # 模拟 Step 6: click_more_then_click("退订")
        parsed_step = {
            'type': 'click_more_then_click',
            'args': ['退订']
        }

        # 执行 post-hook（更新容器上下文）
        self.generator._update_container_context_post(parsed_step)

        # 预期：current_container 应被设置为 'dialog'
        self.assertEqual(self.generator.current_container, 'dialog',
            "skipped 按钮应推断为 dialog 容器")
        self.assertEqual(self.generator._current_context, '退订',
            "current_context 应更新为按钮标签")

    def test_container_filter_blocks_list_page_elements(self):
        """修改点 2: _current_context='退订' 时过滤 list_page 元素

        _current_context 在 trigger_map 中 → is_container_ctx=True → 不回退 list_page
        """
        # 设置容器上下文（模拟 Step 6 之后的状态）
        self.generator.current_container = 'dialog'
        self.generator._current_context = '退订'

        # 查找"退订" — 不传 context，使用 _current_context='退订'
        result = self.generator._discovery_lookup("退订")

        # 预期：无匹配（'退订' 在 trigger_map 中 → 不回退 list_page）
        self.assertIsNone(result,
            "容器上下文内不应回退匹配 list_page 的退订按钮")

    def test_find_all_buttons_respects_container(self):
        """find_all_buttons 尊重容器过滤

        current_container='dialog' → 只返回 dialog 内的按钮
        """
        # 设置容器上下文
        self.generator.current_container = 'dialog'

        # 查找所有名为"退订"的按钮
        candidates = self.generator.find_all_buttons("退订")

        # 预期：无候选（list_page 的"退订"被过滤）
        self.assertEqual(len(candidates), 0,
            "dialog 作用域内不应找到 list_page 的退订按钮")

    def test_full_scenario_delete_cloud_host(self):
        """完整场景：删除云主机用例的步骤序列

        Step 6:  click_more_then_click("退订") → current_container='dialog', _current_context='退订'
        Step 17: click_btn("确认退订") → [待确认]（阈值 0.6 阻止子串匹配）
        Step 20: click_btn("退订") → [待确认]（_current_context='退订' 在 trigger_map → 不回退 list_page）
        """
        # Step 6: 点击"退订"（skipped 按钮）→ post-hook 更新容器
        parsed_step6 = {
            'type': 'click_more_then_click',
            'args': ['退订']
        }
        self.generator._update_container_context_post(parsed_step6)
        self.assertEqual(self.generator.current_container, 'dialog')
        self.assertEqual(self.generator._current_context, '退订')

        # Step 17: 点击"确认退订" — 不传 context，使用 _current_context='退订'
        result_step17 = self.generator._discovery_lookup("确认退订")
        self.assertIsNone(result_step17,
            "Step 17: 确认退订应标记为 [待确认]（阈值 0.6 阻止子串匹配）")

        # Step 20: 点击"退订" — 不传 context，使用 _current_context='退订'
        # '退订' 在 trigger_map 中 → is_container_ctx=True → 不回退 list_page
        result_step20 = self.generator._discovery_lookup("退订")
        self.assertIsNone(result_step20,
            "Step 20: 退订应标记为 [待确认]（不回退 list_page）")

    def test_non_skipped_buttons_unaffected(self):
        """修改点 2: 非 skipped 按钮不受影响

        result_type='container' → 正常更新
        result_type='inline' → 不更新
        """
        # 添加正常容器按钮到 trigger_map
        self.generator._discovery_trigger_map['新增'] = {
            'trigger': '新增',
            'result_type': 'container',
            'container_type': 'drawer'
        }

        parsed = {'type': 'click_btn', 'args': ['新增']}
        self.generator._update_container_context_post(parsed)

        self.assertEqual(self.generator.current_container, 'drawer')
        self.assertEqual(self.generator._current_context, '新增')

        # 模拟 inline 按钮
        self.generator._discovery_trigger_map['展开'] = {
            'trigger': '展开',
            'result_type': 'inline'
        }

        parsed2 = {'type': 'click_btn', 'args': ['展开']}
        self.generator._update_container_context_post(parsed2)

        # current_container 应保持 'drawer'（inline 不改变）
        self.assertEqual(self.generator.current_container, 'drawer')
        self.assertEqual(self.generator._current_context, '展开')


if __name__ == '__main__':
    unittest.main(verbosity=2)
