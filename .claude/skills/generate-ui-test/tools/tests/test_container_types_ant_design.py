"""
Ant Design 容器前缀支持 - 单元测试

验证三个核心修改：
1. CONTAINER_TYPES 扩展 ant-modal/ant-drawer
2. M10 upgrade 逻辑正确识别 Ant Design 容器
3. CONTAINER-DOWNGRADE 跨框架纠错逻辑
"""

import pytest
from verification.verify_engine import CONTAINER_TYPES
from verification.pages_writeback import _store_verified_locator


class TestContainerTypesExtension:
    """测试 1: CONTAINER_TYPES 是否包含 Ant Design 容器"""

    def test_container_types_includes_element_ui(self):
        """验证 Element UI 容器类型仍在列表中"""
        assert 'dialog' in CONTAINER_TYPES
        assert 'drawer' in CONTAINER_TYPES
        assert 'message-box' in CONTAINER_TYPES

    def test_container_types_includes_ant_design(self):
        """验证 Ant Design 容器类型已添加到列表"""
        assert 'ant-modal' in CONTAINER_TYPES
        assert 'ant-drawer' in CONTAINER_TYPES

    def test_container_types_length(self):
        """验证容器类型数量为 5"""
        assert len(CONTAINER_TYPES) == 5


class TestM10UpgradeLogic:
    """测试 2: M10 upgrade 逻辑正确识别 Ant Design 容器"""

    def test_upgrade_to_ant_modal(self):
        """验证从无前缀升级到 ant-modal 前缀"""
        v_loc = "xpath=//div[contains(@class,'ant-modal')]//button[text()='OK']"
        v_ct = 'ant-modal'
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "//button[text()='OK']"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证写入
        assert 'test_group.field_btn' in verified_locators
        assert verified_locators['test_group.field_btn']['marker'] == '[UPGRADED: ant-modal]'
        assert verified_locators['test_group.field_btn']['locator'] == v_loc
        assert verified_locators['test_group.field_btn']['container_type'] == 'ant-modal'

    def test_upgrade_to_ant_drawer(self):
        """验证从无前缀升级到 ant-drawer 前缀"""
        v_loc = "xpath=//div[contains(@class,'ant-drawer')]//button[text()='Submit']"
        v_ct = 'ant-drawer'
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "//button[text()='Submit']"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证写入
        assert 'test_group.field_btn' in verified_locators
        assert verified_locators['test_group.field_btn']['marker'] == '[UPGRADED: ant-drawer]'

    def test_upgrade_to_el_dialog(self):
        """验证从无前缀升级到 el-dialog 前缀（保持向后兼容）"""
        v_loc = "xpath=//div[contains(@class,'el-dialog')]//button[text()='确定']"
        v_ct = 'dialog'
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "//button[text()='确定']"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证写入
        assert 'test_group.field_btn' in verified_locators
        assert verified_locators['test_group.field_btn']['marker'] == '[UPGRADED: dialog]'

    def test_upgrade_to_el_drawer(self):
        """验证从无前缀升级到 el-drawer 前缀（保持向后兼容）"""
        v_loc = "xpath=//div[contains(@class,'el-drawer')]//button[text()='保存']"
        v_ct = 'drawer'
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "//button[text()='保存']"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证写入
        assert 'test_group.field_btn' in verified_locators
        assert verified_locators['test_group.field_btn']['marker'] == '[UPGRADED: drawer]'


class TestCrossFrameworkCorrection:
    """测试 3: CONTAINER-DOWNGRADE 跨框架纠错逻辑"""

    def test_cross_framework_el_to_ant_allowed(self):
        """验证从 el-drawer 降级到无前缀，但 pages group 是 ant 框架时允许"""
        v_loc = "xpath=//button[text()='移入回收站']"
        v_ct = None
        step = {
            'params': {
                'locator': '${sds_ebs_web_sds_ebs_static_ebs_ant-modal_tr_a4006e_elements.field_6af81c_btn_c472}'
            }
        }
        pages_dict = {
            'sds_ebs_web_sds_ebs_static_ebs_ant-modal_tr_a4006e_elements': {
                'field_6af81c_btn_c472': "(//div[contains(@class,'el-drawer')]//button[contains(.,'移') and contains(.,'入') and contains(.,'回') and contains(.,'收') and contains(.,'站')])[1]"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证允许写入（跨框架纠错）
        assert 'sds_ebs_web_sds_ebs_static_ebs_ant-modal_tr_a4006e_elements.field_6af81c_btn_c472' in verified_locators
        marker = verified_locators['sds_ebs_web_sds_ebs_static_ebs_ant-modal_tr_a4006e_elements.field_6af81c_btn_c472']['marker']
        assert 'CROSS-FRAMEWORK-CORRECT' in marker
        assert 'el-drawer' in marker
        assert 'ant' in marker

    def test_same_framework_downgrade_blocked(self):
        """验证同框架降级（el-drawer → 无前缀，group 是 el）被阻止"""
        v_loc = "xpath=//button[text()='保存']"
        v_ct = None
        step = {
            'params': {
                'locator': '${test_group_el_drawer.field_btn}'
            }
        }
        pages_dict = {
            'test_group_el_drawer': {
                'field_btn': "(//div[contains(@class,'el-drawer')]//button[text()='保存'])[1]"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证被阻止（无写入）
        assert 'test_group_el_drawer.field_btn' not in verified_locators

    def test_same_framework_downgrade_ant_blocked(self):
        """验证同框架降级（ant-modal → 无前缀，group 是 ant）被阻止"""
        v_loc = "xpath=//button[text()='确定']"
        v_ct = None
        step = {
            'params': {
                'locator': '${test_group_ant-modal.field_btn}'
            }
        }
        pages_dict = {
            'test_group_ant-modal': {
                'field_btn': "(//div[contains(@class,'ant-modal')]//button[text()='确定'])[1]"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证被阻止（无写入）
        assert 'test_group_ant-modal.field_btn' not in verified_locators

    def test_cross_framework_ant_to_el_allowed(self):
        """验证从 ant-modal 降级到无前缀，但 pages group 含 el 框架标记时允许（跨框架纠错）"""
        v_loc = "xpath=//button[text()='确定']"
        v_ct = None
        step = {
            'params': {
                'locator': '${test_dialog_group.field_btn}'
            }
        }
        pages_dict = {
            'test_dialog_group': {
                'field_btn': "(//div[contains(@class,'ant-modal')]//button[text()='确定'])[1]"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证允许写入（跨框架纠错：group 名含 _dialog_ 是 el 框架标记，但原 locator 用了 ant-modal）
        assert 'test_dialog_group.field_btn' in verified_locators
        marker = verified_locators['test_dialog_group.field_btn']['marker']
        assert 'CROSS-FRAMEWORK-CORRECT' in marker
        assert 'ant-modal' in marker


class TestContainerChange:
    """测试 4: 容器类型变化场景"""

    def test_container_change_el_to_ant(self):
        """验证从 el-drawer 变为 ant-modal 时允许写入"""
        v_loc = "xpath=//div[contains(@class,'ant-modal')]//button[text()='OK']"
        v_ct = 'ant-modal'
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "(//div[contains(@class,'el-drawer')]//button[text()='OK'])[1]"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证写入
        assert 'test_group.field_btn' in verified_locators
        assert '[CONTAINER-CHANGE:' in verified_locators['test_group.field_btn']['marker']

    def test_container_change_ant_to_el(self):
        """验证从 ant-modal 变为 el-dialog 时允许写入"""
        v_loc = "xpath=//div[contains(@class,'el-dialog')]//button[text()='确定']"
        v_ct = 'dialog'
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "(//div[contains(@class,'ant-modal')]//button[text()='确定'])[1]"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证写入
        assert 'test_group.field_btn' in verified_locators
        assert '[CONTAINER-CHANGE:' in verified_locators['test_group.field_btn']['marker']


class TestNoChange:
    """测试 5: 无变化场景"""

    def test_same_locator_no_write(self):
        """验证 locator 相同时不写入"""
        v_loc = "xpath=//button[text()='确定']"
        v_ct = None
        step = {
            'params': {
                'locator': '${test_group.field_btn}'
            }
        }
        pages_dict = {
            'test_group': {
                'field_btn': "//button[text()='确定']"
            }
        }
        verified_locators = {}

        _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators)

        # 验证不写入（相同 locator）
        assert 'test_group.field_btn' not in verified_locators


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
