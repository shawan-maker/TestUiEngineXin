"""framework_registry.py — 框架差异数据注册表（单一真相源）

所有 UI 框架间的差异数据（CSS 类名、XPath 模板、JS 选择器、prompt 模板）
集中管理在此文件中。业务代码通过 get_xxx(framework) 查表，不做硬编码。

新增框架时只需在此文件中增加对应条目，零改动现有 .py/.js 文件。

设计原则:
  - 所有框架差异数据集中在注册表中
  - 业务代码只做"查表+格式化"
  - 新增框架零改动现有 .py/.js 文件

See: docs/debug/antd-framework-compatibility-plan.md §4
"""

import json
import re

# ============================================================
# 探测阶段 JS 选择器表
# ============================================================

DISCOVER_SELECTORS = {
    'element-ui': {
        # --- 表单标签关联 ---
        'formItem':          '.el-form-item',
        'formItemLabel':     '.el-form-item__label',
        'formItemContent':   '.el-form-item__content',
        # --- 输入框 ---
        'inputInner':        'input.el-input__inner',
        'inputWrapper':      '.el-input',
        'textarea':          '.el-textarea',
        'textareaInner':     'textarea.el-textarea__inner',
        # --- 下拉框 ---
        'selectInput':       '.el-select .el-input__inner',
        'selectExclude':     '.el-select, .el-date-editor, .el-cascader',
        'selectDropdown':    '.el-select-dropdown',
        # --- 日期/级联 ---
        'dateEditor':        '.el-date-editor input',
        'cascaderInput':     '.el-cascader .el-input__inner',
        # --- 按钮 ---
        'button':            'button.el-button, button.ec-button',
        'iconSearch':        '.el-icon-search',
        'iconDownload':      '.el-icon-download',
        # --- 表格 ---
        'tableHeader':       '.el-table__header-wrapper',
        'tableBody':         '.el-table__body-wrapper',
        'tableFixedRight':   '.el-table__fixed-right',
        'checkboxInner':     '.el-checkbox__inner',
        'rowButton':         (
            'tbody .el-button, tbody .ec-button, '
            'tbody .el-dropdown span.el-dropdown-link, '
            'tbody .ec-dropdown span.el-dropdown-link, '
            'tbody span.el-dropdown-link, '
            'tbody .el-dropdown span[style*="cursor"], '
            'tbody .ec-dropdown span[style*="cursor"]'
        ),
        # --- 导航 ---
        'menuItem':          '.el-menu-item',
        'breadcrumb':        '.el-breadcrumb',
        'dropdown':          '.el-dropdown',
        # --- 容器 ---
        'drawerBody':        'div.el-drawer__body',
        'dialogBody':        'div.el-dialog__body',
        'drawer':            'div.el-drawer',
        'dialog':            'div.el-dialog',
        'messageBox':        'div.el-message-box',
        'containerAll':      'div.el-drawer, div.el-dialog__wrapper, div.el-message-box',
        # --- 其他 ---
        'loadingMask':       '.el-loading-mask',
        'dropdownMenu':      (
            '.el-dropdown-menu .el-dropdown-menu__item, '
            '.el-dropdown-menu li, '
            '.el-popover .el-button, '
            '.el-tooltip__popper .el-button, '
            'div[x-placement] div.el-tooltip.clickClass, '
            'div[x-placement] div.clickClass'
        ),
        'dropdownLink':      '.el-dropdown-link, .el-popover__reference',
        'dialogConfirm':     "//div[contains(@class,'el-dialog')]",
        # --- 表格行 ---
        'tableBodyRows':     '.el-table__body-wrapper > table > tbody > tr',
        'tableFixedRows':    '.el-table__fixed-right tbody tr',
        'expandTrigger':     '.el-table__expand-icon',
        # --- iframe ---
        'iframeButton':      '.el-button, .ec-button',
        'iframeInputExclude': '.el-select, .el-date-editor',
        'iframeSelectInput': '.el-select .el-input__inner',
    },
    'ant-design': {
        # --- 表单标签关联 ---
        'formItem':          '.ant-form-item',
        'formItemLabel':     '.ant-form-item-label',
        'formItemContent':   '.ant-form-item-control',
        # --- 输入框 ---
        'inputInner':        'input.ant-input',
        'inputWrapper':      '.ant-input-wrapper, .ant-input',
        'textarea':          'textarea.ant-input',
        'textareaInner':     'textarea.ant-input',
        # --- 下拉框 ---
        'selectInput':       '.ant-select .ant-select-selector',
        'selectExclude':     '.ant-select, .ant-picker, .ant-cascader',
        'selectDropdown':    '.ant-select-dropdown',
        # --- 日期/级联 ---
        'dateEditor':        '.ant-picker .ant-picker-input input',
        'cascaderInput':     '.ant-cascader .ant-select-selector',
        # --- 按钮 ---
        'button':            'button.ant-btn, a.ant-btn',
        'iconSearch':        '.anticon-search',
        'iconDownload':      '.anticon-download',
        # --- 表格 ---
        'tableHeader':       '.ant-table-thead',
        'tableBody':         '.ant-table-tbody',
        'tableFixedRight':   '.ant-table-fixed-right',
        'checkboxInner':     '.ant-checkbox-inner',
        'rowButton':         (
            'tbody button.ant-btn, tbody a.ant-btn, '
            'tbody .ant-dropdown-trigger'
        ),
        # --- 导航 ---
        'menuItem':          '.ant-menu-item',
        'breadcrumb':        '.ant-breadcrumb',
        'dropdown':          '.ant-dropdown-trigger',
        # --- 容器 ---
        'drawerBody':        'div.ant-drawer-body',
        'dialogBody':        'div.ant-modal-body',
        'drawer':            'div.ant-drawer',
        'dialog':            'div.ant-modal',
        'messageBox':        'div.ant-modal-confirm',
        'containerAll':      'div.ant-drawer, div.ant-modal, div.ant-modal-confirm',
        # --- 其他 ---
        'loadingMask':       '.ant-spin-spinning',
        'dropdownMenu':      (
            '.ant-dropdown-menu .ant-dropdown-menu-item, '
            '.ant-dropdown-menu li'
        ),
        'dropdownLink':      '.ant-dropdown-trigger',
        'dialogConfirm':     "//div[contains(@class,'ant-modal')]",
        # --- 表格行 ---
        'tableBodyRows':     '.ant-table-tbody > tr.ant-table-row',
        'tableFixedRows':    '.ant-table-fixed-right tbody tr',
        'expandTrigger':     '.ant-table-row-expand-icon',
        # --- iframe ---
        'iframeButton':      '.ant-btn',
        'iframeInputExclude': '.ant-select, .ant-picker',
        'iframeSelectInput': '.ant-select .ant-select-selector',
    },
}

# ============================================================
# 容器 XPath 映射
# ============================================================

CONTAINER_XPATH_MAP = {
    'element-ui': {
        'drawer':      "//div[contains(@class,'el-drawer')]",
        'dialog':      "//div[contains(@class,'el-dialog')]",
        'message-box': "//div[contains(@class,'el-message-box')]",
    },
    'ant-design': {
        'drawer':      "//div[contains(@class,'ant-drawer')]",
        'dialog':      "//div[contains(@class,'ant-modal')]",
        'message-box': "//div[contains(@class,'ant-modal')]",
    },
}

# ============================================================
# 隐藏过滤表达式
# ============================================================

HIDDEN_FILTERS = {
    'element-ui': (
        " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
        " and not(ancestor-or-self::*[contains(@style,'display: none')])"
        " and not(@disabled)"
        " and not(ancestor-or-self::*[contains(@class,'is-disabled')])"
    ),
    'ant-design': (
        " and not(ancestor-or-self::*[contains(@class,'ant-drawer-hidden')])"
        " and not(ancestor-or-self::*[contains(@class,'ant-modal-hidden')])"
        " and not(ancestor-or-self::*[contains(@style,'display: none')])"
        " and not(ancestor-or-self::*[@aria-hidden='true'])"
        " and not(@disabled)"
        " and not(ancestor-or-self::*[contains(@class,'ant-btn-disabled')])"
        " and not(ancestor-or-self::*[contains(@class,'ant-select-disabled')])"
    ),
    '_universal': (
        " and not(ancestor-or-self::*[contains(@style,'display: none')])"
        " and not(@disabled)"
    ),
}

# ============================================================
# 禁用过滤表达式（已合并到 HIDDEN_FILTERS，保留空定义以防向后兼容问题）
# ============================================================

DISABLED_FILTERS = {
    'element-ui': '',
    'ant-design': '',
}

# ============================================================
# AI 探测相关
# ============================================================

JS_BREAK_CLASSES = {
    'element-ui': ['el-dialog', 'el-drawer', 'el-form-item'],
    'ant-design': ['ant-modal', 'ant-drawer', 'ant-form-item'],
}

JS_CONTAINER_CLASSES = {
    'element-ui': ['el-form-item', 'el-dialog', 'el-drawer', 'el-table'],
    'ant-design': ['ant-form-item', 'ant-modal', 'ant-drawer', 'ant-table'],
}

PROMPT_TEMPLATES = {
    'element-ui': {
        'prefix_hints': {
            'dialog': "//div[contains(@class,'el-dialog')]",
            'drawer': "//div[contains(@class,'el-drawer')]",
            'message-box': "//div[contains(@class,'el-message-box')]",
        },
        'input_hint': "对于输入框: 定位 input[@class='el-input__inner']",
        'select_hint': "对于下拉框: 定位 .el-select 的 input[@class='el-input__inner']",
    },
    'ant-design': {
        'prefix_hints': {
            'dialog': "//div[contains(@class,'ant-modal')]",
            'drawer': "//div[contains(@class,'ant-drawer')]",
            'message-box': "//div[contains(@class,'ant-modal-confirm')]",
        },
        'input_hint': "对于输入框: 定位 input[contains(@class,'ant-input')]",
        'select_hint': "对于下拉框: 定位 .ant-select 的 .ant-select-selector",
    },
}

# ============================================================
# 容器标记（用于 _get_table_group_name / element_resolver 等
# 函数截断 group 名）
# ============================================================

CONTAINER_MARKERS_ALL = (
    '_el-drawer_', '_el-dialog_', '_el-message-box_',
    '_ant-drawer_', '_ant-modal_',
    '_drawer_', '_dialog_', '_messagebox_', '_message_box_',
)

# ============================================================
# 容器前缀统一正则（_strip_container_prefix / VLC 归一化共用）
# ============================================================

ALL_CONTAINER_PREFIXES_RE_PATTERN = (
    r"//div\[contains\(@class,"
    r"'(el-(drawer|dialog|message-box)|ant-(drawer|modal))'\)\]"
)

# ============================================================
# checkbox 硬编码回退（统一维护，消除 case_utils/probe_utils 双份）
# ============================================================

CHECKBOX_HARDCODED = {
    'element-ui': (
        '//div[contains(@class,"el-table__body-wrapper")]'
        '//tbody//tr[1]//*[@class="el-checkbox__inner"]'
    ),
    'ant-design': (
        '//div[contains(@class,"ant-table-tbody")]'
        '//tr[contains(@class,"ant-table-row")][1]'
        '//span[contains(@class,"ant-checkbox-inner")]'
    ),
}

FORM_CHECKBOX_HARDCODED = {
    'element-ui': (
        "(//label[contains(.,'{field_text}')]/following-sibling::*[self::div or self::span]"
        "//span[contains(text(),'{option_text}')]/parent::div"
        "//span[@class='el-checkbox__inner'])[1]"
    ),
    'ant-design': (
        "(//label[contains(.,'{field_text}')]/following-sibling::*[self::div or self::span]"
        "//span[contains(text(),'{option_text}')]/parent::div"
        "//span[contains(@class,'ant-checkbox-inner')])[1]"
    ),
}

# ============================================================
# 生成器定位器模板（KB-first：用于替代 case_generator 中
# 3 个已废弃的 _build_*_xpath 硬编码方法）
# ============================================================

GENERATOR_LOCATORS = {
    'dropdown-menu': {
        # 修改4: Element UI 使用 @x-placement 作用域（与 discover 阶段一致）
        # 添加 hidden filter，与 el-select first-option 模板保持一致
        'element-ui': "//*[@x-placement and not(@x-placement='')]//*[contains(text(),'{label}') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]",
        'ant-design': "//li[contains(@class,'ant-dropdown-menu-item')][contains(.,'{label}') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]",
    },
    'more-button': {
        'element-ui': "//button[contains(@class,'el-button')]//span[contains(text(),'更多')]",
        'ant-design': "//button[contains(@class,'ant-btn')][.//span[contains(text(),'更多')]]",
    },
    'date-picker-month': {
        'element-ui': "//td[contains(@class,'el-month-table__cell')][@data-month='{month0}']",
        'ant-design': "//td[@title='{year}-{month:02d}']",
    },
    'close-icon': {
        'element-ui': "//i[contains(@class,'el-icon-close')]",
        'ant-design': "//span[contains(@class,'ant-modal-close-x')] | //span[contains(@class,'ant-drawer-close')]",
    },
    'option-xpath': {
        'element-ui': (
            "//*[contains(@class,'el-select-dropdown__item')]"
            "[not(contains(@class,'is-hidden'))]"
            "[not(contains(@style,'display: none'))]"
            "[contains(.,'{option_text}')]"
        ),
        'ant-design': (
            "//*[contains(@class,'ant-select-item-option')]"
            "[not(contains(@class,'ant-select-item-option-hidden'))]"
            "[not(contains(@style,'display: none'))]"
            "[contains(.,'{option_text}')]"
        ),
    },
    'first-option-xpath': {
        'element-ui': (
            "(//*[contains(@class,'el-select-dropdown__item')]"
            "[not(contains(@class,'is-hidden'))])[1]"
        ),
        'ant-design': (
            "(//*[contains(@class,'ant-select-item-option')]"
            "[not(contains(@class,'ant-select-item-option-hidden'))])[1]"
        ),
    },
}

# ============================================================
# 深度扫描规则（Deep Structural Scan）
# ============================================================

DEEP_SCAN_RULES = {
    'element-ui': {
        'input-generic': {
            'scan': 'input, textarea',
            'excludeInsideSelect': True,
            'excludeInsideCascader': True,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
        'textarea-generic': {
            'scan': 'textarea',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': False,
        },
        'el-select': {
            'scan': '.el-select .el-input__inner',
            'excludeInsideSelect': False,
            'excludeInsideCascader': True,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
        'el-cascader': {
            'scan': '.el-cascader .el-input__inner',
            'excludeInsideSelect': True,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
        'button': {
            'scan': 'button, a[role="button"], span[class*="btn"]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'table-action-button': {
            'scan': 'button, a, span[class*="link"], span[style*="cursor"]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'detail-link': {
            'scan': 'a, span[class*="link"], td[class*="name"]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'tab': {
            'scan': '.el-tabs__item',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'submit-btn': {
            'scan': 'button[type="submit"], button.el-button--primary, button.ec-button--primary',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'search-button': {
            'scan': 'button, .el-input-group__append button',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'close-button': {
            'scan': 'i.el-icon-close, button .el-icon-close, .el-dialog__close',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': False,
        },
        'download-button': {
            'scan': 'button, a[download], i.el-icon-download',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'checkbox': {
            'scan': '.el-checkbox__inner, input[type="checkbox"]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        '_default': {
            'scan': 'input, textarea, button, a, select',
            'excludeInsideSelect': True,
            'excludeInsideCascader': True,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
    },
    'ant-design': {
        'input-generic': {
            'scan': 'input.ant-input, textarea.ant-input',
            'excludeInsideSelect': True,
            'excludeInsideCascader': True,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
        'textarea-generic': {
            'scan': 'textarea.ant-input',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': False,
        },
        'el-select': {
            'scan': '.ant-select .ant-select-selector',
            'excludeInsideSelect': False,
            'excludeInsideCascader': True,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
        'el-cascader': {
            'scan': '.ant-cascader .ant-select-selector',
            'excludeInsideSelect': True,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
        'button': {
            'scan': 'button.ant-btn, a.ant-btn',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'table-action-button': {
            'scan': 'button.ant-btn, a.ant-btn, .ant-dropdown-trigger',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'detail-link': {
            'scan': 'a, span[class*="link"], td[class*="name"]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'tab': {
            'scan': '.ant-tabs-tab',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'submit-btn': {
            'scan': 'button[type="submit"], button.ant-btn-primary',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'search-button': {
            'scan': 'button.ant-btn',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'close-button': {
            'scan': '.ant-modal-close, .ant-drawer-close, span.anticon-close',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': False,
        },
        'download-button': {
            'scan': 'button.ant-btn, a[download]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        'checkbox': {
            'scan': '.ant-checkbox-inner, input[type="checkbox"]',
            'excludeInsideSelect': False,
            'excludeInsideCascader': False,
            'excludeInsideDatePicker': False,
            'needTextMatch': True,
        },
        '_default': {
            'scan': 'input, textarea, button, a, select',
            'excludeInsideSelect': True,
            'excludeInsideCascader': True,
            'excludeInsideDatePicker': True,
            'needTextMatch': False,
        },
    },
}

SCAN_BREAK_CLASSES = {
    'element-ui': [
        'el-form-item', 'el-dialog', 'el-drawer', 'el-message-box',
        'el-table__body', 'el-table__fixed-right',
        'el-form--inline', 'el-tabs__nav',
    ],
    'ant-design': [
        'ant-form-item', 'ant-modal', 'ant-drawer',
        'ant-table-tbody', 'ant-table-fixed-right',
        'ant-tabs-nav',
    ],
}

# ============================================================
# 查询函数
# ============================================================

def get_discover_selector(framework, key, default=''):
    """获取探测 JS 选择器

    Args:
        framework: 'element-ui' / 'ant-design' / None (回退到 element-ui)
        key: 选择器键名
        default: 未找到时的默认值
    """
    selectors = DISCOVER_SELECTORS.get(
        framework, DISCOVER_SELECTORS.get('element-ui', {})
    )
    return selectors.get(key, default)


def get_discover_selectors_json(framework):
    """获取探测 JS 选择器的 JSON 字符串（用于注入 JS）

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        JSON 字符串，可直接用于 JS 模板注入
    """
    selectors = DISCOVER_SELECTORS.get(
        framework, DISCOVER_SELECTORS.get('element-ui', {})
    )
    return json.dumps(selectors, ensure_ascii=False)


def get_container_xpath(container_type, framework=None):
    """根据框架获取容器 XPath 前缀

    Args:
        container_type: 'drawer' / 'dialog' / 'message-box'
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        XPath 前缀字符串，如 "//div[contains(@class,'el-dialog')]"
    """
    fw_map = CONTAINER_XPATH_MAP.get(
        framework, CONTAINER_XPATH_MAP.get('element-ui', {})
    )
    return fw_map.get(container_type, '')


def get_hidden_filter(framework=None):
    """获取框架感知的隐藏过滤表达式

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        XPath and 子句，如 " and not(ancestor-or-self::*[...])"
    """
    if framework in HIDDEN_FILTERS:
        return HIDDEN_FILTERS[framework]
    return HIDDEN_FILTERS.get('element-ui', '')


def get_disabled_filter(framework=None):
    """获取框架感知的禁用过滤表达式

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        XPath and 子句
    """
    if framework in DISABLED_FILTERS:
        return DISABLED_FILTERS[framework]
    return DISABLED_FILTERS.get('element-ui', '')


def get_checkbox_hardcoded(framework=None):
    """获取 checkbox 硬编码回退 XPath

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        完整 XPath 字符串
    """
    return CHECKBOX_HARDCODED.get(
        framework or 'element-ui',
        CHECKBOX_HARDCODED['element-ui']
    )


def get_form_checkbox_hardcoded(framework=None):
    """获取表单勾选框硬编码回退 XPath（非表格上下文）

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        XPath 模板字符串（含 {field_text}, {option_text} 占位符）
    """
    return FORM_CHECKBOX_HARDCODED.get(
        framework or 'element-ui',
        FORM_CHECKBOX_HARDCODED['element-ui']
    )


def get_framework_locator(key, framework=None, **fmt_vars):
    """获取生成器定位器模板（KB-first：替代 case_generator 中
    3 个已废弃的 _build_*_xpath 硬编码方法）

    Args:
        key: 定位器键名（'dropdown-menu' / 'more-button' / 'date-picker-month' 等）
        framework: 'element-ui' / 'ant-design' / None
        **fmt_vars: 格式化变量（如 label='确认', year=2026, month=8）

    Returns:
        格式化后的 XPath 字符串
    """
    templates = GENERATOR_LOCATORS.get(key, {})
    fw = framework or 'element-ui'
    template = templates.get(fw, templates.get('element-ui', ''))
    if not template:
        return ''

    # 特殊处理 date-picker-month 的 month0 变量
    if key == 'date-picker-month' and 'month' in fmt_vars:
        month = fmt_vars.get('month', 1)
        fmt_vars['month0'] = month - 1  # Element UI 用 0-indexed

    try:
        return template.format(**fmt_vars)
    except (KeyError, IndexError):
        return template


def get_js_break_classes(framework=None):
    """获取 JS 向上遍历中断类名列表

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        类名列表，如 ['el-dialog', 'el-drawer', 'el-form-item']
    """
    return JS_BREAK_CLASSES.get(
        framework, JS_BREAK_CLASSES.get('element-ui', [])
    )


def get_js_container_classes(framework=None):
    """获取 JS DOM 提取容器类名列表

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        类名列表
    """
    return JS_CONTAINER_CLASSES.get(
        framework, JS_CONTAINER_CLASSES.get('element-ui', [])
    )


def get_prompt_templates(framework=None):
    """获取 AI 探测 prompt 模板

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        dict with prefix_hints, input_hint, select_hint
    """
    return PROMPT_TEMPLATES.get(
        framework, PROMPT_TEMPLATES.get('element-ui', {})
    )


def get_deep_scan_rules(framework=None):
    """获取深度扫描规则

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        dict，每个 elem_type 对应一个扫描规则 dict
    """
    return DEEP_SCAN_RULES.get(
        framework, DEEP_SCAN_RULES.get('element-ui', {})
    )


def get_scan_break_classes(framework=None):
    """获取深度扫描容器中断类名

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        类名列表
    """
    return SCAN_BREAK_CLASSES.get(
        framework, SCAN_BREAK_CLASSES.get('element-ui', [])
    )


# ============================================================
# 验证门控规则（Validation Gate）
# ============================================================

VALIDATION_RULES = {
    'element-ui': {
        'container_selectors': {
            'dialog': '.el-dialog',
            'drawer': '.el-drawer',
            'message-box': '.el-message-box',
        },
        'form_item_selector': '.el-form-item',
        'label_selector': 'label',
    },
    'ant-design': {
        'container_selectors': {
            'dialog': '.ant-modal',
            'drawer': '.ant-drawer',
            'message-box': '.ant-modal-confirm',
        },
        'form_item_selector': '.ant-form-item',
        'label_selector': 'label',
    },
}


def get_validation_rules(framework=None):
    """获取验证规则

    Args:
        framework: 'element-ui' / 'ant-design' / None

    Returns:
        dict with container_selectors, form_item_selector, label_selector
    """
    return VALIDATION_RULES.get(
        framework, VALIDATION_RULES.get('element-ui', {})
    )
