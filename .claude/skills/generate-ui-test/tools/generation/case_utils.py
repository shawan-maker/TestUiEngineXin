#!/usr/bin/env python3
"""
case_utils.py — 独立辅助函数：从 _case_generator.py 提取的通用工具函数。

这些函数不依赖 CaseGenerator 类，可以被其他模块独立使用。
"""

import os
import re

# ─── DEBUG-F7 控制 ───
_DEBUG_F7 = os.environ.get('DEBUG_F7', '')


def _debug_f7(*args, **kwargs):
    """条件化 DEBUG-F7 输出"""
    if _DEBUG_F7:
        print(*args, **kwargs)


# ─── 导入依赖 ───
from core.xpath_utils import detect_container_type
from probe.probe_element import load_knowledge, _safe_format, _get_expand_patterns


def _slugify(text):
    """中文/英文 → 小写 slug"""
    if not text:
        return 'unknown'
    text = text.strip().lower()
    text = re.sub(r'[^a-z0-9一-鿿]+', '_', text)
    return text.strip('_') or 'unknown'


def _detect_container_type(locator):
    """从 locator 中检测容器类型（委托给 detect_container_type）

    Returns: 'drawer' / 'dialog' / 'message-box' / None
    """
    return detect_container_type(locator)


def _build_date_picker_xpath(value, scope_prefix=''):
    """根据时间选择值构建正确的 Element UI 日期面板 XPath。

    KB 知识库定义 4 种模式:
    - 今天: td[contains(@class,'today')] in @x-placement panel
    - 此刻: button[contains(.,'此刻')] in @x-placement panel
    - 当月: td[@class='today' or @class='current'] in el-month-table
    - 起始/结束: is-left/is-right panel 中第一个 available

    Args:
        value: 用户指定的时间值（"今天"/"此刻"/"当月"/"开始时间"/"结束时间"）
        scope_prefix: 可选的容器作用域前缀（如 dialog scope）
    Returns:
        (xpath_str, desc_str): XPath 和步骤描述
    """
    panel_scope = (f"{scope_prefix}//div[@x-placement"
                   f" and not(@x-placement='') and not(@role='tooltip')]")
    table_filter = "not(contains(@style,'display: none'))"

    if '今天' in value or '当天' in value or 'today' in value.lower():
        xpath = (f"{panel_scope}//table[{table_filter}]"
                 f"//td[contains(@class,'today')]")
        desc = "选择今天"
    elif '此刻' in value or 'now' in value.lower():
        xpath = (f"{panel_scope}//table[{table_filter}]"
                 f"//button[contains(.,'此刻')]")
        desc = "选择此刻"
    elif '当月' in value or 'current' in value.lower():
        xpath = (f"//table[@class='el-month-table' and {table_filter}]"
                 f"//td[@class='today' or @class='current']")
        if scope_prefix:
            xpath = f"{scope_prefix}{xpath}"
        desc = "选择当月"
    elif '开始' in value or 'start' in value.lower():
        xpath = (f"({scope_prefix}//div[contains(@class,'is-left')]"
                 f"//*[contains(@class,'available')])[1]")
        desc = "选择开始时间"
    elif '结束' in value or 'end' in value.lower():
        xpath = (f"({scope_prefix}//div[contains(@class,'is-right')]"
                 f"//*[contains(@class,'available')])[1]")
        desc = "选择结束时间"
    else:
        xpath = (f"{panel_scope}//table[{table_filter}]"
                 f"//*[contains(.,'{value}')]")
        desc = f"选择「{value}」"
    return xpath, desc


def _get_assertion_kb_pattern(category, **kwargs):
    """从 KB assertion 段读取模板并填充参数。

    Args:
        category: 'success-toast' / 'error-toast' / 'first-row-content' / 'field-value'
        **kwargs: 模板参数 (keyword, field_label 等)
    Returns:
        str or None: 填充后的 XPath
    """
    try:
        db = load_knowledge()
        cats = db.get('assertion', {}).get('categories', {})
        if category in cats:
            patterns = cats[category].get('patterns', [])
            if patterns:
                result = _safe_format(patterns[0], kwargs)
                if '{' not in result:
                    return result
    except Exception:
        pass
    return None


def _get_first_kb_pattern(kb_key, label, step_type=None):
    """从 KB 获取第一个可完全替换的 pattern（Fix-4）。

    Args:
        kb_key: KB 类型键（如 'input-generic'），None 表示硬编码兜底
        label: 中文标签
        step_type: 步骤类型（用于 checkbox 硬编码判断）

    Returns: 替换后的 XPath 字符串，或 None
    """
    if kb_key is None:
        if step_type == 'checkbox':
            return ('//div[contains(@class,"el-table__body-wrapper")]'
                    '//tbody//tr[1]//*[@class="el-checkbox__inner"]')
        return None

    patterns = _get_expand_patterns(kb_key)
    chars_all = " and ".join(f"contains(.,'{c}')" for c in label if c != "'") if label else ""
    fmt_vars = {
        'label': label, 'tab_name': label,
        'section': label,
        'char1': label[0] if label else "",
        'char2': label[-1] if label else "",
        'chars_all': chars_all,
        'field_label': label, 'keyword': label,
    }
    candidates = []
    for p in patterns:
        xpath = _safe_format(p, fmt_vars)
        if '{' not in xpath:
            candidates.append(xpath)
    return candidates[0] if candidates else None


def _find_table_action(groups, label):
    """在 groups 中查找表格行操作按钮。

    搜索策略（按优先级）：
    1. GAP-1: 在所有 group 中查找 _row 后缀字段（新格式）
    2. 在 table_action/table group 中查找 _btn 字段（旧格式）
    """
    normalized = label.replace(' ', '')
    for group_name, fields in groups.items():
        for field_name in fields:
            if field_name.endswith('_row'):
                base = field_name.replace('_row', '').replace('_btn', '')
                if normalized in base or base in normalized:
                    return f"${{{group_name}.{field_name}}}"
                if all(c in field_name for c in normalized if c.strip()):
                    return f"${{{group_name}.{field_name}}}"
    for group_name, fields in groups.items():
        if 'table_action' in group_name or 'table' in group_name:
            for field_name in fields:
                if '_btn' in field_name:
                    for char in label:
                        if char in field_name:
                            return f"${{{group_name}.{field_name}}}"
    return None


def _find_section_row_link(groups, section_name):
    """根据区域名称查找区域行链接定位器。"""
    for group_name, fields in groups.items():
        for field_name, locator in fields.items():
            if not field_name.endswith('_row_link'):
                continue
            if section_name in field_name:
                return f"${{{group_name}.{field_name}}}"
            if isinstance(locator, str) and f"contains(text(),'{section_name}')" in locator:
                return f"${{{group_name}.{field_name}}}"
    return None


def _find_detail_link(groups, preferred_container=None, module_slug=None):
    """查找 detail-link 类型的 locator 引用。

    三层查找链：first_desc_link → _link/_row_link → _field 兼容回退。
    修改 2: 增加值有效性校验，过滤空值和 [待确认] 占位符。
    R6: 增加 module_slug 过滤，防止返回其他模块的 group。
    """
    # R6: module filter helper
    _module_prefix = module_slug.replace('-', '_') if module_slug else None

    def _is_same_module(group_name):
        if not _module_prefix:
            return True  # no filter when module_slug not provided
        return (group_name.startswith(_module_prefix)
                or group_name == 'common_elements'
                or group_name.startswith('common_'))

    # Fix-4a: 过滤语义占位符（xxxxxxxxxx 等测试数据）
    _PLACEHOLDER_RE = re.compile(
        r'contains\(\.,\s*[\x27"]('
        r'x{3,}|X{3,}|-{3,}|\*{3,}|#{3,}|_{3,}|test|TEST|placeholder|TODO|TBD|FIXME'
        r')[\x27"]\s*\)'
    )

    def _is_valid_locator(loc):
        """检查 locator 是否为有效值（非空、非占位符）。"""
        if not loc:
            return False
        if isinstance(loc, str):
            if loc in ('xpath=[待确认]', '[待确认]'):
                return False
            if loc.startswith('[待确认]'):
                return False
            # Fix-4a: 过滤语义占位符
            if _PLACEHOLDER_RE.search(loc):
                return False
        return True

    # Strategy 1: first_desc_link（值有效性校验 + R6 模块过滤）
    for group_name, fields in groups.items():
        if not _is_same_module(group_name):
            continue  # R6: skip cross-module groups
        if 'first_desc_link' in fields:
            loc = fields['first_desc_link']
            if _is_valid_locator(loc):
                return f"${{{group_name}.first_desc_link}}"

    # Strategy 2: _link / _row_link（值有效性校验 + R6 模块过滤）
    link_candidates = []
    for group_name, fields in groups.items():
        if not _is_same_module(group_name):
            continue  # R6: skip cross-module groups
        for field_name in fields:
            if field_name.endswith('_link') or field_name.endswith('_row_link'):
                loc = fields[field_name]
                if _is_valid_locator(loc):
                    link_candidates.append((group_name, field_name))
    if link_candidates:
        if preferred_container:
            for g, f in link_candidates:
                if preferred_container in g:
                    return f"${{{g}.{f}}}"
        g, f = link_candidates[0]
        return f"${{{g}.{f}}}"

    # Strategy 3: _field 兼容回退（+ R6 模块过滤）
    for group_name, fields in groups.items():
        if not _is_same_module(group_name):
            continue  # R6: skip cross-module groups
        for field_name in fields:
            if (field_name.endswith('_field') and
                    any(kw in field_name for kw in ('desc', 'detail', 'link', 'title', 'name'))):
                return f"${{{group_name}.{field_name}}}"
    return None
