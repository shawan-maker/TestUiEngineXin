#!/usr/bin/env python3
"""field_suffixes.py — 共享常量：字段后缀、容器优先级、对话框确认标签

被多个工具共同导入，确保常量定义唯一：
  - _case_generator.py (_FIELD_RE, label_map, CaseGenerator)
  - validate_08_scripts.py (R4.58 字段命名校验)
  - probe_element.py (容器前缀)
  - step_patterns.py (未来扩展)
  - _pages_writer.py (label_to_key 共享)

用法:
    from field_suffixes import (
        STANDARD_SUFFIXES, EXEMPT_GROUPS, DIALOG_CONFIRM_LABELS,
        CONTAINER_PRIORITY, FIELD_RE_SUFFIXES,
        normalize_label, label_to_key, trigger_to_key, UNIVERSAL_BUTTONS,
    )
"""

import re
import hashlib
from _element_types import (
    normalize_type as _normalize_type,
    KB_TO_SUFFIX as _KB_TO_SUFFIX,
    SUFFIX_MAP_COMPAT as SUFFIX_MAP,
    STEP_TYPE_ALIASES_COMPAT as _STEP_TYPE_ALIASES,
)

# ============================================================================
# 标准字段后缀列表
# ============================================================================
# pages YAML 中业务字段必须以此后缀结尾（R4.58 校验）。
# 与 _FIELD_RE 正则和 _extract_comment_labels() 同步。

STANDARD_SUFFIXES = (
    '_select', '_input', '_option', '_editable', '_first_option', '_expand',
    '_btn', '_close_btn', '_text', '_textarea', '_link', '_area', '_field',
    '_count', '_tab', '_cascader', '_level', '_checkbox',
    '_iframe', '_body', '_row_link', '_row', '_menu', '_card',
    '_date', '_picker', '_search',
)

# ============================================================================
# 用于 _FIELD_RE 正则的后缀列表（不含 _level / _row_link）
# ============================================================================
# _FIELD_RE 从 YAML 字段行提取前缀，只匹配核心后缀

FIELD_RE_SUFFIXES = (
    'select', 'input', 'option', 'btn', 'close_btn', 'text', 'textarea',
    'link', 'area', 'field', 'count', 'editable', 'iframe', 'body', 'row',
    'cascader', 'checkbox', 'checkbox_all', 'menu', 'card',
)

# ============================================================================
# 豁免组 — 不参与后缀校验和 label_map 统计
# ============================================================================

EXEMPT_GROUPS = frozenset({
    'common_elements',
    'dropdown_menu',
})

# ============================================================================
# 对话框确认标签 — 多候选遍历时默认加 el-dialog 前缀
# ============================================================================
# probe_element.py:_kb_fallback() 和多候选遍历共用

DIALOG_CONFIRM_LABELS = frozenset({
    '确定', '确认', '取消',
})

# ============================================================================
# 容器优先级 — 多候选遍历排序
# ============================================================================
# 值越小优先级越高：dialog > drawer > message-box > 无前缀

CONTAINER_PRIORITY = {
    'dialog': 0,
    'drawer': 1,
    'message-box': 2,
    'new_page': 3,   # L2: 新页面优先于列表页
    None: 4,
}


# ============================================================================
# 标签归一化（用于 key 生成，不用于 XPath）
# ============================================================================
# 解决 "确 定"（Element UI 带空格）和 "确定"（无空格）hash 不同的问题。
# 归一化只用于 key 生成，XPath 仍用原始 label（因为 DOM 文本可能带空格）。


def normalize_label(label):
    """标签归一化：去除所有空白字符（含全角空格），统一为空字符串。

    Examples:
        >>> normalize_label('确 定')
        '确定'
        >>> normalize_label('PMO 更新')
        'PMO更新'
        >>> normalize_label(' 方案名称 ')
        '方案名称'
        >>> normalize_label(None)
        ''
    """
    if not label:
        return ''
    # 去除所有 ASCII 空白 + 全角空格
    return re.sub(r'[\s　]+', '', str(label)).strip()


# ============================================================================
# 通用按钮（所有项目共享，仅 12 个）
# ============================================================================
# 这些按钮在所有 UI 项目中都常见，不需要项目级映射。

UNIVERSAL_BUTTONS = {
    '确定': 'confirm', '取消': 'cancel', '新增': 'add', '查询': 'query',
    '重置': 'reset', '导出': 'export', '删除': 'delete', '编辑': 'edit',
    '保存': 'save', '提交': 'submit', '关闭': 'close', '返回': 'back',
}


# ============================================================================
# 通用 trigger 词典（用于 container 前缀命名，避免 hash 不可读）
# ============================================================================
# 覆盖常见 UI 触发按钮名。未命中的 trigger 走 ASCII 提取或 hash 兜底。
# 只用于 trigger_to_key()，不用于 label_to_key()，所以不影响 key 对齐。

UNIVERSAL_TRIGGERS = {
    # 基础 CRUD
    '新增': 'add', '编辑': 'edit', '删除': 'delete', '详情': 'detail',
    '查看': 'view', '修改': 'modify', '创建': 'create',
    # 操作类
    '查询': 'query', '搜索': 'search', '重置': 'reset',
    '导入': 'import', '导出': 'export', '批量删除': 'batch_delete',
    '批量导入': 'batch_import', '批量导出': 'batch_export',
    # 流程类
    '保存': 'save', '提交': 'submit', '发布': 'publish', '审核': 'audit',
    '审批': 'approve', '归档': 'archive', '复制': 'copy', '移动': 'move',
    # 状态类
    '启用': 'enable', '禁用': 'disable', '激活': 'activate', '停用': 'deactivate',
    # 特殊
    '进展更新': 'progress', '登录': 'login', '登出': 'logout',
}


# ============================================================================
# 元素类型 → 后缀映射
# ============================================================================

# SUFFIX_MAP and _STEP_TYPE_ALIASES are now imported from _element_types
# (see import block above). Backward-compatible names preserved.


# ============================================================================
# label → key 转换（单一真相源）
# ============================================================================
# 被 _pages_writer.py 和 _case_generator.py 共同导入，
# 确保相同中文 label 在两个工具中生成相同的 field key，消除引用断裂。

# 容器类型前缀（drawer / dialog / messagebox），用于区分同名元素在不同容器中
# navigation 类型（详情页）不加前缀，其元素通常与列表页不会同名
CONTAINER_TYPE_PREFIXES = {
    'drawer': 'drawer',
    'dialog': 'dialog',
    'message-box': 'messagebox',
    'new_page': '',   # L2: 新页面不加前缀
}


def label_to_key(label, elem_type, container_type=None, skip_container_prefix=False):
    """中文 label 转 pages YAML field key（单一真相源）。

    Args:
        label: 中文标签（如 "方案名称"、"确 定"）
        elem_type: 元素类型（button/input/el-select/textarea/date_picker）
        container_type: 容器类型（'drawer'/'dialog'/'message-box'/'navigation'/None），
            None 表示 list_page。非 None 且非 navigation 时添加容器前缀
            （drawer_/dialog_/messagebox_）
        skip_container_prefix: 3f 方案 A — 跳过容器前缀，field name 只含
            label hash + suffix（容器区分由 group name 承担）

    Returns:
        field key（如 "field_1b0b23_select"、"drawer_confirm_btn"）

    Examples:
        >>> label_to_key('方案名称', 'el-select')[:7]
        'field_1'
        >>> label_to_key('确 定', 'button')
        'confirm_btn'
        >>> label_to_key('确定', 'button')
        'confirm_btn'
        >>> label_to_key('确定', 'button', 'drawer')
        'drawer_confirm_btn'
        >>> label_to_key('确定', 'button', 'dialog')
        'dialog_confirm_btn'
        >>> label_to_key('新增', 'button')
        'add_btn'
        >>> label_to_key('新增', 'button', 'drawer')
        'drawer_add_btn'
        >>> label_to_key('新增', 'button', 'navigation')  # 详情页不加前缀
        'add_btn'
        >>> label_to_key('确定', 'button', 'drawer', skip_container_prefix=True)  # 3f 方案 A
        'confirm_btn'
    """
    normalized = normalize_label(label)
    # F-A: 归一化 elem_type via unified type system
    # normalize_type() handles: raw→canonical, underscore→hyphen, identity
    _canonical = _normalize_type(elem_type) if elem_type else ''
    _alias = _STEP_TYPE_ALIASES.get(elem_type, '')
    suffix = (_KB_TO_SUFFIX.get(_canonical)
              or SUFFIX_MAP.get(elem_type)
              or SUFFIX_MAP.get(elem_type.replace('_', '-') if elem_type else '')
              or SUFFIX_MAP.get(_alias)
              or '_field')
    if not normalized:
        return f'unknown{suffix}'

    # 通用按钮（所有项目共享）
    if normalized in UNIVERSAL_BUTTONS:
        base = UNIVERSAL_BUTTONS[normalized]
        # close-button 类型的"关闭"标签，直接用 suffix（避免 close_close_btn）
        if base == 'close' and suffix == '_close_btn':
            key = 'close_btn'
        else:
            key = f'{base}{suffix}'
    else:
        # ASCII 优先提取（如 PMO更新 → pmo、GO → go）
        ascii_part = re.sub(r'[^a-zA-Z0-9]', '', normalized)
        if ascii_part and len(ascii_part) <= 10:
            base = ascii_part.lower()
            key = f'{base}{suffix}'
        else:
            # 纯中文标签：hash（含 container_type 避免跨容器碰撞）
            hash_input = f"{container_type}:{normalized}" if container_type else normalized
            h = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:6]
            key = f'field_{h}{suffix}'

    # 容器类型前缀（drawer/dialog/message-box 才加，navigation 不加）
    if skip_container_prefix:
        # 3f 方案 A: field name 不含容器前缀
        # 但容器内元素需要 hash 后缀避免与 list_page 同名元素碰撞
        if container_type:
            ct_hash = hashlib.md5(container_type.encode('utf-8')).hexdigest()[:4]
            return f'{key}_{ct_hash}'
        return key
    prefix = CONTAINER_TYPE_PREFIXES.get(container_type)
    if prefix:
        return f'{prefix}_{key}'
    return key


def generate_key_with_collision_check(label, elem_type, container_type, existing_keys,
                                       skip_container_prefix=False):
    """生成 key 并检测冲突，冲突时加后缀 _2, _3, ..."""
    key = label_to_key(label, elem_type, container_type, skip_container_prefix)
    if key not in existing_keys:
        return key
    for i in range(2, 100):
        alt = f'{key}_{i}'
        if alt not in existing_keys:
            print(f'[WARN] key 冲突: {key} → {alt}（label: {label}）')
            return alt
    raise ValueError(f'key 冲突无法解决: {key}')


def trigger_to_key(trigger):
    """container trigger 名转 key 片段。

    优先级:
      1. UNIVERSAL_TRIGGERS 词典（常见 UI trigger → 英文）
      2. ASCII 提取（如 PMO更新 → pmo、GO → go）
      3. hash 兜底（tr_{6}）

    Examples:
        >>> trigger_to_key('新增')
        'add'
        >>> trigger_to_key('PMO更新')
        'pmo'
        >>> trigger_to_key('GO')
        'go'
        >>> trigger_to_key('进展更新')
        'progress'
    """
    if not trigger:
        return 'tr_unknown'
    normalized = normalize_label(trigger)
    # 1. 词典查找（含空格归一化，所以 "新 增" 也能匹配）
    if normalized in UNIVERSAL_TRIGGERS:
        return UNIVERSAL_TRIGGERS[normalized]
    # 也查原始 trigger（未归一化），兼容词典中用原始形式写的条目
    if trigger in UNIVERSAL_TRIGGERS:
        return UNIVERSAL_TRIGGERS[trigger]
    # 2. ASCII 提取
    ascii_part = re.sub(r'[^a-zA-Z0-9]', '', trigger)
    if ascii_part and len(ascii_part) <= 10:
        return ascii_part.lower()
    # 3. hash 兜底
    h = hashlib.md5(normalized.encode('utf-8')).hexdigest()[:6]
    return f'tr_{h}'
