"""单元测试：验证门控 _validate_deep_scan_result()

测试 Phase 6 深度扫描/AI 结果的三道防线验证逻辑。
使用 mock page 对象验证各种场景。
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 将 tools 目录添加到 sys.path
_tools_dir = str(Path(__file__).parent.parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from verification.verify_engine import _validate_deep_scan_result


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_page():
    """创建 mock Playwright page 对象"""
    page = MagicMock()
    page.url = "http://example.com/test"
    return page


def _make_mock_element(tag='button', text='确认', placeholder='', in_container=True,
                       in_select=False, parent_label='', evaluate_error=False):
    """创建 mock Playwright Element 对象"""
    el = MagicMock()

    if evaluate_error:
        el.evaluate.side_effect = Exception("evaluate failed")
        return el

    def evaluate_side_effect(fn):
        # tagName
        if 'tagName' in fn:
            return tag
        # className
        if 'className' in fn:
            return ''
        # in_select check
        if 'closest' in fn and 'el-select' in fn:
            return in_select
        # parent_label check
        if 'formItem' in fn and 'label' in fn:
            return parent_label
        # container check
        if 'closest' in fn and ('el-dialog' in fn or 'ant-modal' in fn):
            return in_container
        if 'closest' in fn and ('el-drawer' in fn or 'ant-drawer' in fn):
            return in_container
        return ''

    el.evaluate.side_effect = evaluate_side_effect
    el.inner_text.return_value = text
    el.get_attribute.return_value = placeholder
    return el


def _setup_page_with_element(page, element):
    """配置 mock page 返回指定的 element"""
    mock_locator = MagicMock()
    mock_locator.first = element
    page.locator.return_value = mock_locator


# ============================================================================
# 测试：按钮文本匹配（防线 1）
# ============================================================================

def test_validate_button_text_match(mock_page):
    """测试：按钮文本匹配 → 通过"""
    el = _make_mock_element(tag='button', text='确认')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", None)

    assert valid is True
    assert "tag=button" in reason


def test_validate_button_text_mismatch(mock_page):
    """测试：按钮文本不匹配 → 拒绝"""
    el = _make_mock_element(tag='button', text='取消')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", None)

    assert valid is False
    assert "不包含 label" in reason


def test_validate_submit_btn_text_match(mock_page):
    """测试：submit-btn 文本匹配 → 通过"""
    el = _make_mock_element(tag='button', text='提交')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "提交", "submit-btn", None)

    assert valid is True


def test_validate_table_action_button_text_match(mock_page):
    """测试：table-action-button 文本匹配 → 通过"""
    el = _make_mock_element(tag='a', text='编辑')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//a", "编辑", "table-action-button", None)

    assert valid is True
    assert "tag=a" in reason


def test_validate_tab_text_match(mock_page):
    """测试：tab 文本匹配 → 通过"""
    el = _make_mock_element(tag='div', text='基本信息')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//div", "基本信息", "tab", None)

    assert valid is True


def test_validate_search_button_text_match(mock_page):
    """测试：search-button 文本匹配 → 通过"""
    el = _make_mock_element(tag='button', text='搜索')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "搜索", "search-button", None)

    assert valid is True


def test_validate_download_button_text_match(mock_page):
    """测试：download-button 文本匹配 → 通过"""
    el = _make_mock_element(tag='button', text='下载')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "下载", "download-button", None)

    assert valid is True


# ============================================================================
# 测试：输入框文本匹配（防线 1）
# ============================================================================

def test_validate_input_placeholder_match(mock_page):
    """测试：input placeholder 匹配 → 通过"""
    el = _make_mock_element(tag='input', text='', placeholder='请输入项目名称',
                            in_select=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "项目名称", "input-generic", None)

    assert valid is True


def test_validate_input_text_match(mock_page):
    """测试：input text 匹配 → 通过"""
    el = _make_mock_element(tag='input', text='项目名称', placeholder='',
                            in_select=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "项目名称", "input-generic", None)

    assert valid is True


def test_validate_input_parent_label_match(mock_page):
    """测试：input 通过 parent label 匹配 → 通过"""
    el = _make_mock_element(tag='input', text='', placeholder='',
                            in_select=False, parent_label='项目名称')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "项目名称", "input-generic", None)

    assert valid is True


def test_validate_input_no_text_relation(mock_page):
    """测试：input 无任何文本关联 → 拒绝"""
    el = _make_mock_element(tag='input', text='', placeholder='',
                            in_select=False, parent_label='备注')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "项目名称", "input-generic", None)

    assert valid is False
    assert "无文本关联" in reason


def test_validate_input_in_el_select(mock_page):
    """测试：input 在 el-select 内部 → 拒绝"""
    el = _make_mock_element(tag='input', text='', placeholder='',
                            in_select=True)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "状态", "input-generic", None)

    assert valid is False
    assert "el-select 内部" in reason


def test_validate_textarea_match(mock_page):
    """测试：textarea 文本匹配 → 通过"""
    el = _make_mock_element(tag='textarea', text='', placeholder='请输入描述',
                            in_select=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//textarea", "描述", "textarea-generic", None)

    assert valid is True


# ============================================================================
# 测试：select/cascader 文本匹配（防线 1）
# ============================================================================

def test_validate_el_select_parent_label_match(mock_page):
    """测试：el-select 通过 parent label 匹配 → 通过"""
    el = _make_mock_element(tag='input', text='', placeholder='',
                            parent_label='状态')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "状态", "el-select", None)

    assert valid is True


def test_validate_el_select_no_text_relation(mock_page):
    """测试：el-select 无文本关联 → 拒绝"""
    el = _make_mock_element(tag='input', text='', placeholder='',
                            parent_label='备注')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "状态", "el-select", None)

    assert valid is False
    assert "无文本关联" in reason


def test_validate_el_cascader_parent_label_match(mock_page):
    """测试：el-cascader 通过 parent label 匹配 → 通过"""
    el = _make_mock_element(tag='input', text='', placeholder='',
                            parent_label='所属区域')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "所属区域", "el-cascader", None)

    assert valid is True


# ============================================================================
# 测试：容器上下文校验（防线 2）
# ============================================================================

def test_validate_element_in_dialog(mock_page):
    """测试：元素在 dialog 内 → 通过"""
    el = _make_mock_element(tag='button', text='确认', in_container=True)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", "dialog")

    assert valid is True


def test_validate_element_not_in_dialog(mock_page):
    """测试：元素不在 dialog 内 → 拒绝"""
    el = _make_mock_element(tag='button', text='确认', in_container=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", "dialog")

    assert valid is False
    assert "不在期望容器" in reason


def test_validate_element_not_in_drawer(mock_page):
    """测试：元素不在 drawer 内 → 拒绝"""
    el = _make_mock_element(tag='input', text='', placeholder='请输入名称',
                            in_container=False, in_select=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "名称", "input-generic", "drawer")

    assert valid is False
    assert "不在期望容器" in reason


def test_validate_no_container_context(mock_page):
    """测试：无容器上下文 → 跳过防线 2"""
    el = _make_mock_element(tag='button', text='确认')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", None)

    assert valid is True


def test_validate_container_context_message_box(mock_page):
    """测试：message-box 容器上下文校验"""
    el = _make_mock_element(tag='button', text='确认', in_container=True)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", "message-box")

    assert valid is True


# ============================================================================
# 测试：元素类型校验（防线 3）
# ============================================================================

def test_validate_button_tag_correct(mock_page):
    """测试：button tag 正确 → 通过"""
    el = _make_mock_element(tag='button', text='确认')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", None)

    assert valid is True
    assert "tag=button" in reason


def test_validate_button_tag_a(mock_page):
    """测试：button tag=a → 通过"""
    el = _make_mock_element(tag='a', text='确认')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//a", "确认", "button", None)

    assert valid is True
    assert "tag=a" in reason


def test_validate_button_tag_span(mock_page):
    """测试：button tag=span → 通过"""
    el = _make_mock_element(tag='span', text='确认')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//span", "确认", "button", None)

    assert valid is True
    assert "tag=span" in reason


def test_validate_button_tag_wrong(mock_page):
    """测试：button tag=div → 拒绝"""
    el = _make_mock_element(tag='div', text='确认')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//div", "确认", "button", None)

    assert valid is False
    assert "不符合" in reason


def test_validate_submit_btn_tag_button(mock_page):
    """测试：submit-btn tag=button → 通过"""
    el = _make_mock_element(tag='button', text='提交')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "提交", "submit-btn", None)

    assert valid is True


def test_validate_submit_btn_tag_wrong(mock_page):
    """测试：submit-btn tag=a → 拒绝（仅允许 button）"""
    el = _make_mock_element(tag='a', text='提交')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//a", "提交", "submit-btn", None)

    assert valid is False
    assert "不符合" in reason


def test_validate_input_tag_input(mock_page):
    """测试：input-generic tag=input → 通过"""
    el = _make_mock_element(tag='input', text='', placeholder='请输入名称',
                            in_select=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//input", "名称", "input-generic", None)

    assert valid is True


def test_validate_input_tag_wrong(mock_page):
    """测试：input-generic tag=div → 拒绝"""
    el = _make_mock_element(tag='div', text='', placeholder='请输入名称',
                            in_select=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//div", "名称", "input-generic", None)

    assert valid is False
    assert "不符合" in reason


def test_validate_tab_tag_div(mock_page):
    """测试：tab tag=div → 通过"""
    el = _make_mock_element(tag='div', text='基本信息')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//div", "基本信息", "tab", None)

    assert valid is True


def test_validate_tab_tag_li(mock_page):
    """测试：tab tag=li → 通过"""
    el = _make_mock_element(tag='li', text='基本信息')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//li", "基本信息", "tab", None)

    assert valid is True


# ============================================================================
# 测试：边界场景
# ============================================================================

def test_validate_invalid_locator_format(mock_page):
    """测试：无效 locator 格式 → 拒绝"""
    valid, reason = _validate_deep_scan_result(
        mock_page, "css=.btn", "确认", "button", None)

    assert valid is False
    assert "invalid locator format" in reason


def test_validate_empty_locator(mock_page):
    """测试：空 locator → 拒绝"""
    valid, reason = _validate_deep_scan_result(
        mock_page, "", "确认", "button", None)

    assert valid is False
    assert "invalid locator format" in reason


def test_validate_none_locator(mock_page):
    """测试：None locator → 拒绝"""
    valid, reason = _validate_deep_scan_result(
        mock_page, None, "确认", "button", None)

    assert valid is False
    assert "invalid locator format" in reason


def test_validate_evaluate_error(mock_page):
    """测试：evaluate 异常 → 拒绝"""
    el = _make_mock_element(evaluate_error=True)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", None)

    assert valid is False
    assert "evaluate failed" in reason


def test_validate_unknown_elem_type(mock_page):
    """测试：未知 elem_type → 跳过防线 1/3，仅执行防线 2"""
    el = _make_mock_element(tag='div', text='测试')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//div", "测试", "unknown-type", None)

    assert valid is True  # 未知类型不做文本和 tag 校验


def test_validate_partial_text_match(mock_page):
    """测试：按钮文本部分匹配（label 是 text 的子串）→ 通过"""
    el = _make_mock_element(tag='button', text='确认订单')
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", None)

    assert valid is True


def test_validate_combined_defenses(mock_page):
    """测试：三道防线联合 — 所有通过"""
    el = _make_mock_element(tag='button', text='确认', in_container=True)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", "dialog")

    assert valid is True
    assert "tag=button" in reason


def test_validate_defense1_fails_first(mock_page):
    """测试：防线 1 先失败 → 不检查防线 2/3"""
    el = _make_mock_element(tag='button', text='取消', in_container=False)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", "dialog")

    assert valid is False
    assert "不包含 label" in reason


# ============================================================================
# 测试：elem_type 参数化覆盖
# ============================================================================

@pytest.mark.parametrize("elem_type,tag,text,expected_valid", [
    ('button', 'button', '确认', True),
    ('submit-btn', 'button', '提交', True),
    ('tab', 'div', '基本信息', True),
    ('table-action-button', 'button', '编辑', True),
    ('search-button', 'button', '搜索', True),
    ('download-button', 'button', '下载', True),
])
def test_validate_button_types_parametrized(mock_page, elem_type, tag, text, expected_valid):
    """参数化测试：各种按钮类型文本匹配"""
    el = _make_mock_element(tag=tag, text=text)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, f"xpath=//{tag}", text, elem_type, None)

    assert valid == expected_valid


@pytest.mark.parametrize("elem_type,tag,parent_label,expected_valid", [
    ('el-select', 'input', '状态', True),
    ('el-cascader', 'input', '所属区域', True),
    ('el-select', 'div', '状态', True),
    ('el-cascader', 'div', '所属区域', True),
])
def test_validate_select_types_parametrized(mock_page, elem_type, tag, parent_label, expected_valid):
    """参数化测试：select/cascader 类型 parent label 匹配"""
    el = _make_mock_element(tag=tag, text='', placeholder='',
                            parent_label=parent_label)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, f"xpath=//{tag}", parent_label, elem_type, None)

    assert valid == expected_valid


# ============================================================================
# 测试：容器上下文参数化
# ============================================================================

@pytest.mark.parametrize("container_context,in_container,expected_valid", [
    ('dialog', True, True),
    ('dialog', False, False),
    ('drawer', True, True),
    ('drawer', False, False),
    ('message-box', True, True),
    ('message-box', False, False),
    ('ant-modal', True, True),
    ('ant-modal', False, False),
    ('ant-drawer', True, True),
    ('ant-drawer', False, False),
    (None, True, True),   # 无容器上下文 → 跳过防线 2
    (None, False, True),  # 无容器上下文 → 跳过防线 2
])
def test_validate_container_context_parametrized(mock_page, container_context, in_container, expected_valid):
    """参数化测试：各种容器上下文校验"""
    el = _make_mock_element(tag='button', text='确认', in_container=in_container)
    _setup_page_with_element(mock_page, el)

    valid, reason = _validate_deep_scan_result(
        mock_page, "xpath=//button", "确认", "button", container_context)

    assert valid == expected_valid


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
