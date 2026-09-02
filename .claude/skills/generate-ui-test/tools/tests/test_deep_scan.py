"""单元测试：深度结构扫描（Deep Structural Scan）Layer 0

测试 _layer0_deep_scan() 在各种场景下的行为。
使用 mock page 对象验证逻辑分支。
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 将 tools 目录添加到 sys.path
_tools_dir = str(Path(__file__).parent.parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from probe.ai_probe import _layer0_deep_scan, init as ai_probe_init
from core.framework_registry import get_deep_scan_rules, get_scan_break_classes


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_page():
    """创建 mock Playwright page 对象"""
    page = MagicMock()
    page.url = "http://example.com/test"
    return page


@pytest.fixture
def mock_inject_filter():
    """创建 mock inject_hidden_filter 函数"""
    def inject_filter(xpath, **kwargs):
        # 简单返回 xpath，不添加过滤条件
        return xpath
    return inject_filter


@pytest.fixture(autouse=True)
def init_ai_probe():
    """每个测试前初始化 ai_probe 模块"""
    config = {
        'enabled': True,
        'layer0_enabled': True,
        'max_calls': 30,
        'model': 'gpt-4o-mini',
    }
    ai_probe_init(config, framework='element-ui')
    yield


# ============================================================================
# 测试：成功场景
# ============================================================================

def test_deep_scan_single_match_success(mock_page, mock_inject_filter):
    """测试：深度扫描找到单个匹配，返回 xpath"""
    # Mock page.evaluate 返回成功结果
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {
            'tag': 'label',
            'class': 'el-form-item__label',
            'text': '项目名称'
        },
        'container': {
            'tag': 'div',
            'class': 'el-form-item',
            'found': True
        },
        'candidates': [
            {
                'tag': 'input',
                'class': 'el-input__inner',
                'text': '',
                'isHidden': False,
                'isDisabled': False,
                'isReadonly': False,
                'isInsideSelect': False,
                'isInsideCascader': False,
                'isInsideDatePicker': False,
                'textMatch': False,
                'xpath': "//div[contains(@class,'el-form-item')]//input[contains(@class,'el-input__inner')]"
            }
        ],
        'bestMatch': 0
    }

    # Mock page.locator().count() 返回 1
    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_page.locator.return_value = mock_locator

    # 执行测试
    result = _layer0_deep_scan(
        mock_page,
        label='项目名称',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    # 验证结果
    assert result is not None
    xpath, strategy = result
    assert strategy == 'deep-scan'
    assert 'input' in xpath
    assert 'el-input__inner' in xpath

    # 验证调用了 page.evaluate
    mock_page.evaluate.assert_called_once()


def test_deep_scan_multiple_matches_with_narrowing(mock_page, mock_inject_filter):
    """测试：深度扫描找到多个匹配，通过 [1] 收窄成功"""
    # Mock page.evaluate 返回多个候选
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '编辑'},
        'container': {'tag': 'tr', 'class': '', 'found': True},
        'candidates': [
            {
                'tag': 'button',
                'class': 'el-button',
                'text': '编辑',
                'isHidden': False,
                'isDisabled': False,
                'isReadonly': False,
                'isInsideSelect': False,
                'isInsideCascader': False,
                'isInsideDatePicker': False,
                'textMatch': True,
                'xpath': "//tr//button[contains(@class,'el-button')]"
            },
            {
                'tag': 'button',
                'class': 'el-button',
                'text': '编辑',
                'isHidden': False,
                'isDisabled': False,
                'isReadonly': False,
                'isInsideSelect': False,
                'isInsideCascader': False,
                'isInsideDatePicker': False,
                'textMatch': True,
                'xpath': "//tr//button[contains(@class,'el-button')]"
            }
        ],
        'bestMatch': 0
    }

    # Mock page.locator().count()
    # 第一次调用（原 xpath）返回 2
    # 第二次调用（收窄后）返回 1
    mock_locator = MagicMock()
    mock_locator.count.side_effect = [2, 1]  # 原 xpath count=2, 收窄后 count=1
    mock_page.locator.return_value = mock_locator

    # 执行测试
    result = _layer0_deep_scan(
        mock_page,
        label='编辑',
        elem_type='table-action-button',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    # 验证结果
    assert result is not None
    xpath, strategy = result
    assert strategy == 'deep-scan-narrowed'
    assert xpath.endswith(')[1]')  # 应该有 [1] 收窄


# ============================================================================
# 测试：失败场景
# ============================================================================

def test_deep_scan_label_not_found(mock_page, mock_inject_filter):
    """测试：DOM 中找不到 label，返回 None"""
    # Mock page.evaluate 返回 labelFound=False
    mock_page.evaluate.return_value = {
        'labelFound': False,
        'labelElement': None,
        'container': None,
        'candidates': [],
        'bestMatch': None
    }

    # 执行测试
    result = _layer0_deep_scan(
        mock_page,
        label='不存在的标签',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    # 验证结果
    assert result is None

    # 验证调用了 page.evaluate
    mock_page.evaluate.assert_called_once()


def test_deep_scan_no_candidates(mock_page, mock_inject_filter):
    """测试：找到 label 但无匹配候选，返回 None"""
    # Mock page.evaluate 返回无候选
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '测试'},
        'container': {'tag': 'div', 'class': 'el-form-item', 'found': True},
        'candidates': [],
        'bestMatch': None
    }

    # 执行测试
    result = _layer0_deep_scan(
        mock_page,
        label='测试',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    # 验证结果
    assert result is None


def test_deep_scan_xpath_count_zero(mock_page, mock_inject_filter):
    """测试：xpath 验证 count=0，返回 None"""
    # Mock page.evaluate 返回成功
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '提交'},
        'container': {'tag': 'div', 'class': '', 'found': True},
        'candidates': [
            {
                'tag': 'button',
                'class': 'el-button',
                'text': '提交',
                'isHidden': False,
                'isDisabled': False,
                'isReadonly': False,
                'isInsideSelect': False,
                'isInsideCascader': False,
                'isInsideDatePicker': False,
                'textMatch': True,
                'xpath': "//button[contains(@class,'el-button')]"
            }
        ],
        'bestMatch': 0
    }

    # Mock page.locator().count() 返回 0
    mock_locator = MagicMock()
    mock_locator.count.return_value = 0
    mock_page.locator.return_value = mock_locator

    # 执行测试
    result = _layer0_deep_scan(
        mock_page,
        label='提交',
        elem_type='submit-btn',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    # 验证结果
    assert result is None


def test_deep_scan_js_execution_error(mock_page, mock_inject_filter):
    """测试：JS 执行异常，返回 None"""
    # Mock page.evaluate 抛出异常
    mock_page.evaluate.side_effect = Exception("JS execution failed")

    # 执行测试
    result = _layer0_deep_scan(
        mock_page,
        label='测试',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    # 验证结果
    assert result is None


# ============================================================================
# 测试：框架注册表
# ============================================================================

def test_get_deep_scan_rules_element_ui():
    """测试：获取 Element UI 的深度扫描规则"""
    rules = get_deep_scan_rules('element-ui')

    # 验证关键规则存在
    assert 'input-generic' in rules
    assert 'button' in rules
    assert 'el-select' in rules
    assert 'table-action-button' in rules
    assert '_default' in rules

    # 验证 input-generic 规则
    input_rule = rules['input-generic']
    assert input_rule['scan'] == 'input, textarea'
    assert input_rule['excludeInsideSelect'] is True
    assert input_rule['excludeInsideCascader'] is True
    assert input_rule['needTextMatch'] is False

    # 验证 button 规则
    button_rule = rules['button']
    assert 'button' in button_rule['scan']
    assert button_rule['needTextMatch'] is True


def test_get_deep_scan_rules_ant_design():
    """测试：获取 Ant Design 的深度扫描规则"""
    rules = get_deep_scan_rules('ant-design')

    # 验证关键规则存在
    assert 'input-generic' in rules
    assert 'button' in rules

    # 验证 Ant Design 特定的选择器
    input_rule = rules['input-generic']
    assert 'ant-input' in input_rule['scan']


def test_get_deep_scan_rules_default_framework():
    """测试：framework=None 时回退到 element-ui"""
    rules = get_deep_scan_rules(None)
    rules_element = get_deep_scan_rules('element-ui')

    assert rules == rules_element


def test_get_scan_break_classes_element_ui():
    """测试：获取 Element UI 的容器中断类名"""
    classes = get_scan_break_classes('element-ui')

    # 验证包含关键类名
    assert 'el-form-item' in classes
    assert 'el-dialog' in classes
    assert 'el-drawer' in classes
    assert 'el-table__body' in classes


def test_get_scan_break_classes_ant_design():
    """测试：获取 Ant Design 的容器中断类名"""
    classes = get_scan_break_classes('ant-design')

    # 验证包含 Ant Design 特定的类名
    assert 'ant-form-item' in classes
    assert 'ant-modal' in classes
    assert 'ant-table-tbody' in classes


def test_get_scan_break_classes_default_framework():
    """测试：framework=None 时回退到 element-ui"""
    classes = get_scan_break_classes(None)
    classes_element = get_scan_break_classes('element-ui')

    assert classes == classes_element


# ============================================================================
# 测试：各种 elem_type 的规则覆盖
# ============================================================================

@pytest.mark.parametrize("elem_type", [
    'input-generic',
    'textarea-generic',
    'el-select',
    'el-cascader',
    'button',
    'table-action-button',
    'detail-link',
    'tab',
    'submit-btn',
    'search-button',
    'close-button',
    'download-button',
    'checkbox',
])
def test_deep_scan_rules_coverage(elem_type):
    """测试：所有常见 elem_type 都有对应的扫描规则"""
    rules = get_deep_scan_rules('element-ui')

    # 验证规则存在
    assert elem_type in rules, f"缺少 {elem_type} 的扫描规则"

    rule = rules[elem_type]

    # 验证规则结构完整
    assert 'scan' in rule
    assert 'excludeInsideSelect' in rule
    assert 'excludeInsideCascader' in rule
    assert 'excludeInsideDatePicker' in rule
    assert 'needTextMatch' in rule

    # 验证 scan 不为空
    assert rule['scan'], f"{elem_type} 的 scan 规则为空"


# ============================================================================
# 测试：边界场景
# ============================================================================

def test_deep_scan_empty_candidates_list(mock_page, mock_inject_filter):
    """测试：candidates 为空列表"""
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '测试'},
        'container': {'tag': 'div', 'class': '', 'found': True},
        'candidates': [],
        'bestMatch': -1  # bestMatch 为 -1 表示无匹配
    }

    result = _layer0_deep_scan(
        mock_page,
        label='测试',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    assert result is None


def test_deep_scan_best_match_null(mock_page, mock_inject_filter):
    """测试：bestMatch 为 None"""
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '测试'},
        'container': {'tag': 'div', 'class': '', 'found': True},
        'candidates': [
            {'tag': 'input', 'xpath': "//input", 'textMatch': False}
        ],
        'bestMatch': None  # bestMatch 为 None
    }

    result = _layer0_deep_scan(
        mock_page,
        label='测试',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    assert result is None


def test_deep_scan_candidate_without_xpath(mock_page, mock_inject_filter):
    """测试：候选元素缺少 xpath 字段"""
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '测试'},
        'container': {'tag': 'div', 'class': '', 'found': True},
        'candidates': [
            {
                'tag': 'input',
                'class': 'el-input__inner',
                'text': '',
                'isHidden': False,
                'isDisabled': False,
                'isReadonly': False,
                'isInsideSelect': False,
                'isInsideCascader': False,
                'isInsideDatePicker': False,
                'textMatch': False,
                # 缺少 xpath 字段
            }
        ],
        'bestMatch': 0
    }

    result = _layer0_deep_scan(
        mock_page,
        label='测试',
        elem_type='input-generic',
        container_prefix_str='',
        inject_hidden_filter=mock_inject_filter
    )

    assert result is None


def test_deep_scan_with_container_prefix(mock_page, mock_inject_filter):
    """测试：带容器前缀的深度扫描"""
    mock_page.evaluate.return_value = {
        'labelFound': True,
        'labelElement': {'tag': 'label', 'class': '', 'text': '确认'},
        'container': {'tag': 'div', 'class': 'el-dialog__footer', 'found': True},
        'candidates': [
            {
                'tag': 'button',
                'class': 'el-button--primary',
                'text': '确认',
                'isHidden': False,
                'isDisabled': False,
                'isReadonly': False,
                'isInsideSelect': False,
                'isInsideCascader': False,
                'isInsideDatePicker': False,
                'textMatch': True,
                'xpath': "//div[contains(@class,'el-dialog__footer')]//button"
            }
        ],
        'bestMatch': 0
    }

    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_page.locator.return_value = mock_locator

    container_prefix = "//div[contains(@class,'el-dialog') and not(contains(@style,'display: none'))]//"

    result = _layer0_deep_scan(
        mock_page,
        label='确认',
        elem_type='submit-btn',
        container_prefix_str=container_prefix,
        inject_hidden_filter=mock_inject_filter
    )

    assert result is not None
    xpath, strategy = result
    assert strategy == 'deep-scan'


# ============================================================================
# 测试：JS 文件加载
# ============================================================================

def test_deep_scan_js_file_exists():
    """测试：_ai_deep_scan.js 文件存在"""
    js_path = Path(__file__).parent.parent / 'probe' / 'js' / '_ai_deep_scan.js'
    assert js_path.exists(), "_ai_deep_scan.js 文件不存在"


def test_deep_scan_js_file_loadable():
    """测试：_ai_deep_scan.js 可以被加载"""
    from probe.ai_probe import _load_ai_js

    # 应该不抛出异常
    js_code = _load_ai_js('_ai_deep_scan.js')
    assert js_code is not None
    assert len(js_code) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
