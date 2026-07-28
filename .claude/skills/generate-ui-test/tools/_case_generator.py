#!/usr/bin/env python3
"""
_case_generator.py — Case/Data YAML 生成器：解析 Excel 步骤，生成 case YAML + data YAML。

输出 required_fields 供 PagesWriter 按需生成 pages YAML。

来源（重构自）：
  - generate_cases_from_excel.py: CaseGenerator 类（2170 行）
  - generate_cases_from_excel.py: generate_case_file(), preflight_check(), SelfCheckLayer
  - generate_cases_from_excel.py: L3 加载函数, _batch_repair_case(), V3/V4 辅助

关键变化：
  - 旧：CaseGenerator(PagesIndex, ...) — 从 pages YAML 读取组名
  - 新：CaseGenerator(ElementResolver, ...) — 从 element_resolver 获取组名
  - PagesIndex 类（973 行）→ 删除，查询能力由 ElementResolver 替代
"""

import copy
import glob
import json
import os
import re
import sys
import yaml
from collections import defaultdict

# ─── DEBUG-F7 控制 ───
_DEBUG_F7 = os.environ.get('DEBUG_F7', '')

def _debug_f7(*args, **kwargs):
    """条件化 DEBUG-F7 输出"""
    if _DEBUG_F7:
        print(*args, **kwargs)

# ─── 共享导入 ───
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from step_patterns import parse_step, STEP_PATTERNS, Q
from field_suffixes import (
    label_to_key as _shared_label_to_key,
)
from xpath_utils import inject_hidden_filter as _inject_hidden_filter
from xpath_utils import HIDDEN_FILTER as _HIDDEN_FILTER_SUFFIX
from xpath_utils import _unwrap_positional, _rewrap_positional
from xpath_utils import apply_container_prefix, detect_container_type
from _element_resolver import ElementResolver, ElementEntry
from probe_element import _get_expand_patterns, _safe_format, load_knowledge
from _pages_writer import _make_editable_locator, DEFAULT_COMMON_ELEMENTS as COMMON_ELEMENTS

# ═══════════════════════════════════════════════════════════════
# 独立辅助函数
# ═══════════════════════════════════════════════════════════════

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
    panel_scope = (f"{scope_prefix}//div[@x-placement='bottom-start'"
                   f" or @x-placement='top-start']")
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


# ═══════════════════════════════════════════════════════════════
# CaseGenerator
# ═══════════════════════════════════════════════════════════════

class CaseGenerator:
    """从结构化步骤生成 case YAML。

    与旧版的区别：
    - 旧：CaseGenerator(PagesIndex, ...) — 从 pages YAML 读取组名
    - 新：CaseGenerator(ElementResolver, ...) — 从 element_resolver 获取组名
    """

    # 可见型断言关键词（含内容包含类动词）
    _VISIBILITY_KW = {'可见', '显示', '存在', '展示', '出现', '包括', '包含', '含有'}
    _STRIP_SUFFIX = re.compile(r'(?<=.{3})(区域|列表|统计|信息|数据|页面).*$')
    _ASSERTION_VIS_PREFIX_RE = re.compile(
        r'^(?:可见|显示|存在|展示|出现|包含|含有)'
    )

    _BUTTON_TYPES = frozenset({
        'click_btn', 'click_table_row_btn', 'click_first_in_list',
        'click_table_action', 'click_more_then', 'click_more_then_click',
        'confirm_dialog', 'confirm_delete',
        'conditional_click_btn', 'conditional_click_row',
        'conditional_click', 'conditional_click_tab',
    })
    _NO_WAIT_AFTER_TYPES = frozenset({
        'wait_element',
        'assert', 'assert_row', 'assert_count', 'check_assert',
        'l3_call',
    })
    _RANDOM_NAME_RE = re.compile(r'随机名称[(（](.*?)[)）]')
    _CT_HASH_RE = re.compile(r'_([0-9a-f]{4})$')  # BUG-14: 容器哈希后缀检测

    def __init__(self, resolver, module_name, project_dir=''):
        """
        Args:
            resolver: ElementResolver 实例（唯一 discovery 数据源）
            module_name: 模块 slug
            project_dir: 项目根目录
        """
        self.resolver = resolver
        self.module = module_name
        self._project_dir = project_dir
        self._workflow_cache = None
        self.data_entries = {}
        self.data_group_name = f"{module_name.replace('-', '_')}_data"
        self.current_case_prefix = ''
        self.current_container = None
        self.current_tab_scope = None
        self.current_tab_scope_label = None
        self.pending_detail_links = []
        self._pending_nav_wait = False
        self._random_name_counter = 0
        self.required_fields = {}  # {(group, field): {locator, label, comment}}
        self._compat_groups_cache = None  # H2: _compat_groups() 内存缓存
        self._compat_groups_mtime = 0  # M5: pages 目录 mtime 缓存

        # 兼容属性（供外部访问）
        self.field_meta = {}  # (group, field) -> {type, keyword, frame, body}

        # Page context（替代 PagesIndex.set_page_context）
        self._current_page_url = None

        # 同源：直接引用 resolver 已注册的数据（唯一真相源）
        # entry.raw 是 _register_element() 处理后的 dict，含 group_name/field_key
        self._discovery_trigger_map = resolver.get_trigger_map().copy()  # 防御性拷贝，避免修改 resolver 内部状态
        self._discovery_element_map = {
            (ctx, label): entry.raw
            for (ctx, label), entry in resolver.get_element_map().items()
            if entry.raw and entry.raw.get('locator')
        }
        # 多URL精确索引：按 page_slug 区分
        self._discovery_page_element_map = {
            (ps, ctx, label): entry.raw
            for (ps, ctx, label), entry in resolver.get_page_element_map().items()
            if entry.raw and entry.raw.get('locator')
        }
        self._current_context = 'list_page'

        # [DEBUG-F7] 显示 trigger_map 内容
        _debug_f7(f"\n[DEBUG-F7] CaseGenerator 初始化: module='{module_name}'")
        _debug_f7(f"[DEBUG-F7] _discovery_trigger_map ({len(self._discovery_trigger_map)} 个触发器):")
        for trigger, entry in self._discovery_trigger_map.items():
            ct = entry.get('container_type', '?')
            rt = entry.get('result_type', '?')
            elem_count = len(entry.get('elements', []))
            _debug_f7(f"[DEBUG-F7]   '{trigger}' → container_type='{ct}', result_type='{rt}', elements={elem_count}")
        _debug_f7(f"[DEBUG-F7] _discovery_element_map ({len(self._discovery_element_map)} 个元素)")
        _debug_f7(f"[DEBUG-F7] _current_context = '{self._current_context}'\n")

    # ─── 兼容适配层 ───────────────────────────────────────────

    def _compat_groups(self):
        """将 resolver 的 {group: {field: ElementEntry}} 转为 {group: {field: locator}}。

        H2: 增加内存缓存，避免每次调用都从磁盘重读所有 YAML 文件。
        缓存在 _track_field() 注册新字段时自动失效。
        M5: 增加 mtime 检查，检测外部修改。
        """
        import time

        # 检查缓存是否过期
        if self._compat_groups_cache is not None:
            if self._project_dir:
                pages_dir = os.path.join(self._project_dir, 'pages')
                if os.path.isdir(pages_dir):
                    current_mtime = os.path.getmtime(pages_dir)
                    if current_mtime > self._compat_groups_mtime:
                        self._compat_groups_cache = None  # 外部修改，强制刷新

        if self._compat_groups_cache is not None:
            return self._compat_groups_cache

        result = {}
        for gname, field_map in self.resolver.get_groups().items():
            result[gname] = {
                fkey: entry.locator
                for fkey, entry in field_map.items()
            }

        # 合并现有 pages YAML 的字段（companion 字段等）
        if self._project_dir:
            pages_dir = os.path.join(self._project_dir, 'pages')
            if os.path.isdir(pages_dir):
                for mod_dir in os.listdir(pages_dir):
                    yaml_path = os.path.join(pages_dir, mod_dir, 'elements.yaml')
                    if not os.path.isfile(yaml_path):
                        continue
                    try:
                        import yaml as _yaml
                        with open(yaml_path, encoding='utf-8') as _f:
                            data = _yaml.safe_load(_f) or {}
                        for gname, fields in data.items():
                            if not isinstance(fields, dict):
                                continue
                            if gname not in result:
                                result[gname] = {}
                            for fkey, locator in fields.items():
                                # 只合并 resolver 中没有的字段（companion 等）
                                if fkey not in result[gname] and isinstance(locator, str):
                                    result[gname][fkey] = locator
                    except Exception as _e:
                        print(f"  [WARN] 加载 pages YAML 失败: {yaml_path}: {_e}")
                # 记录 mtime
                self._compat_groups_mtime = os.path.getmtime(pages_dir)

        self._compat_groups_cache = result
        return result

    def _compat_labels(self):
        """从 resolver element_map 构建 label_map: {label: [(group, field_prefix, ct)]}。"""
        labels = {}
        for (ctx, label), entry in self.resolver.get_element_map().items():
            ct = entry.container_type
            field_key = entry.field or ''

            # BUG-14: 先剥离容器哈希后缀（4 hex chars），再剥离标准后缀
            field_without_ct = self._CT_HASH_RE.sub('', field_key)
            field_prefix = field_without_ct
            for suf in ('_select', '_input', '_editable', '_first_option',
                        '_textarea', '_btn', '_tab', '_link', '_row_link',
                        '_row', '_option', '_card', '_cascader'):
                if field_without_ct.endswith(suf):
                    field_prefix = field_without_ct[:-len(suf)]
                    break
            labels.setdefault(label, []).append((entry.group, field_prefix, ct))
        return labels

    # ─── 查找方法 ─────────────────────────────────────────────

    def find_el_select(self, label, preferred_container=None):
        """根据中文标签查找 el-select 触发器 locator 引用。

        与 find_input / find_button 统一（BUG-14 一致性修复）。
        注：当前已被 _emit_el_select_steps 绕过，保留以备未来使用。
        """
        elem = self._discovery_lookup(label, type_hint='el-select')
        if not elem:
            return None

        ref = self._elem_to_ref(elem)
        if not ref:
            return None

        return {
            'group': elem.get('group_name', ''),
            'select': ref,
            'field_prefix': elem.get('field_key', ''),
            'editable': None,
            'first_option': None,
        }

    def _add_container_prefix_to_xpath(self, xpath):
        """当 current_container 不为 None 时，为裸 XPath 添加容器前缀。

        Plan A: 与 _emit_el_select_steps L485-498 逻辑对称。
        用于 fill_value / textarea 等非 el-select 路径。

        BUG-13 修复：支持 (xpath)[N] 包裹格式，前缀注入到括号内部

        Args:
            xpath: 原始 XPath（以 // 开头，不含 xpath= 前缀）
        Returns:
            带容器前缀的 XPath（如果适用），否则原样返回
        """
        return apply_container_prefix(xpath, self.current_container)

    def _emit_el_select_steps(self, steps, label, value, nth=1):
        """生成 el-select 完整 3 步条件分支（始终使用 KB 标准 XPath）。

        KB XPath 通过 _track_field() 注册，由 PagesWriter 写入 pages YAML。
        PagesWriter Stage 2 自动注入 hidden filter（幂等）。
        PagesWriter Stage 3 自动生成 _editable + _first_option companion。

        生成步骤:
          1. click_element(${group.field_select})       ← 点击第 nth 个 input 展开
          2. if_element_visible(${group.field_editable}) ← 判断可编辑？
             then: fill_value + wait + click_option     ← 可搜索（带 hidden filter）
             else: 判断目标选项可见？                   ← readonly 路径
               then: click_option                        ← 直接点目标选项
               else: click_first_option                  ← 回退选第一项
          3. wait_for_time(1000)                         ← 等待选择完成
        """
        # 1. 生成 field prefix（hash-based，与现有机制一致）
        #    skip_container_prefix=True: 容器区分由 group name 承担
        #    label_to_key 已含 _select 后缀，需剥离得到纯 prefix
        field_with_suffix = _shared_label_to_key(
            label, 'el_select',
            container_type=self.current_container,
            skip_container_prefix=True)
        field = field_with_suffix[:-len('_select')] if field_with_suffix.endswith('_select') else field_with_suffix

        # 2. 确定 group（复用现有容器上下文逻辑）
        #    self._current_context = 打开容器的按钮标签（如 "新增"），
        #    由 _update_container_context_post() 在上一步按钮点击后设置
        group = self.resolver.get_group_name(
            self.module,
            page_slug=self._get_current_page_slug(),
            container_type=self.current_container,
            trigger=self._current_context)
        if not group:
            group = self.resolver.construct_pending_group(
                self.current_container, self.module,
                page_slug=self._get_current_page_slug(),
                trigger=self._current_context)

        # 3. KB 标准 XPath（来自 probe_knowledge.json el-select multi_step）
        select_xpath_base = (
            f"//*[contains(text(),'{label}')]"
            f"/following-sibling::*[self::div or self::span]"
            f"//input[@class='el-input__inner']"
        )

        # 4. 容器前缀（在 drawer/dialog 内时限定范围，避免跨容器误匹配）
        select_xpath_base = apply_container_prefix(select_xpath_base, self.current_container)

        # 4.5. _editable 从 base 生成（在 [nth] 包裹之前，避免 _make_editable_locator 误解析 [N]）
        editable_xpath_base = _make_editable_locator(select_xpath_base)

        # 4.6. 序号后缀：(xpath)[nth] — 默认 [1]，兼容多同名下拉框场景
        select_xpath = f"({select_xpath_base})[{nth}]"
        editable_xpath = f"({editable_xpath_base})[{nth}]"

        # 5. 注册 _select 到 required_fields（原始 XPath，无 hidden filter）
        #    PagesWriter Stage 2 注入 hidden filter
        #    PagesWriter Stage 3 生成 _editable + _first_option companion
        self._track_field(group, f'{field}_select',
                          locator=f'xpath={select_xpath}',
                          label=label,
                          comment='el-select KB 标准模式')

        # 5b. 预注册 companion 字段（防止 collect_refs_from_steps 注册空 locator）
        #     collect_refs_from_steps 扫描 ${group._editable} 时会在 resolver
        #     中找不到该字段 → 注册 locator='' → PagesWriter guard 跳过生成。
        #     预注册正确的 locator 可避免此问题。
        #     _editable: _select 的 XPath + and not(@readonly)
        self._track_field(group, f'{field}_editable',
                          locator=f'xpath={editable_xpath}',
                          label=f'{label}（可编辑状态）')
        #     _first_option: 通用第一项 XPath（带 hidden filter，下拉面板选项可能被虚拟滚动隐藏）
        #     注意：下拉面板渲染在 body 级别（非容器 DOM 内），不加容器前缀
        first_option_xpath = (
            "(//div[(@x-placement='bottom-start' "
            "or @x-placement='top-start')]//li"
            "[not(ancestor::*[contains(@class,'is-hidden')])"
            " and not(ancestor::*[contains(@style,'display: none')])])[1]"
        )
        self._track_field(group, f'{field}_first_option',
                          locator=f'xpath={first_option_xpath}',
                          label=f'{label}（第一个可见选项）')

        # 6. 数据引用
        resolved_value, is_random = self._try_expand_random_name(
            value, field, steps)
        if is_random:
            option_ref = resolved_value
        else:
            option_ref = self.add_data(f'{field}_option', value)
        search_ref = self.add_data(f'{field}_search', value)

        # 7. Pages YAML 引用（companion 已在 5b 预注册）
        select_ref = f'${{{group}.{field}_select}}'
        editable_ref = f'${{{group}.{field}_editable}}'
        first_option_ref = f'${{{group}.{field}_first_option}}'

        # 8. 选项 XPath（inline，不走 PagesWriter Stage 2，需手动拼接 hidden filter）
        option_xpath = (
            f"(//div[(@x-placement='bottom-start' "
            f"or @x-placement='top-start')]//li"
            f"[contains(.,'{option_ref}')"
            f" and not(ancestor::*[contains(@class,'is-hidden')])"
            f" and not(ancestor::*[contains(@style,'display: none')])])[1]"
        )

        # === Step 1: 点击下拉框 ===
        nth_desc = f"第{nth}个" if nth > 1 else ""
        steps.append({
            'desc': f"选择「{label}」 - 点击{nth_desc}下拉框",
            'keyword': 'click_element',
            'params': {'locator': select_ref},
        })

        # === Step 2: 条件分支 ===
        then_steps = [
            {
                'desc': f"选择「{label}」 - 输入搜索",
                'keyword': 'fill_value',
                'params': {'locator': select_ref, 'value': search_ref},
            },
            {
                'desc': f"等待「{label}」搜索结果加载",
                'keyword': 'wait_for_time',
                'params': {'timeout': 1500},
            },
            {
                'desc': f"选择「{label}」 - 选择选项",
                'keyword': 'click_element',
                'params': {'locator': f'xpath={option_xpath}'},
            },
        ]

        # else 分支：readonly 模式
        # 下拉面板已展开，先检查目标选项是否可见（虚拟滚动场景可能不可见）
        else_then_steps = [
            {
                'desc': f"选择「{label}」 - 点击目标选项",
                'keyword': 'click_element',
                'params': {'locator': f'xpath={option_xpath}'},
            },
        ]
        else_else_steps = [
            {
                'desc': f"选择「{label}」 - 目标选项不可见，回退选择第一项",
                'keyword': 'click_element',
                'params': {'locator': first_option_ref},
            },
        ]
        else_steps = [
            {
                'desc': f"判断「{label}」目标选项是否可见",
                'keyword': 'if_element_visible',
                'params': {
                    'locator': f'xpath={option_xpath}',
                    'timeout': 500,
                    'then_steps': else_then_steps,
                    'else_steps': else_else_steps,
                },
            },
        ]

        steps.append({
            'desc': f"判断「{label}」是否可编辑",
            'keyword': 'if_element_visible',
            'params': {
                'locator': editable_ref,
                'timeout': 500,
                'then_steps': then_steps,
                'else_steps': else_steps,
            },
        })

        # === Step 3: 等待 ===
        steps.append({
            'desc': "等待",
            'keyword': 'wait_for_time',
            'params': {'timeout': 1000},
        })

    def find_el_cascader(self, label, preferred_container=None):
        """根据中文标签查找级联选择器的 locator 引用。

        与 find_input / find_button 统一：直接取 discovery 的 group+key，
        不做 suffix stripping + key 重建（BUG-14 修复）。
        """
        elem = self._discovery_lookup(label, type_hint='el-cascader')
        if not elem:
            return None

        ref = self._elem_to_ref(elem)
        if not ref:
            return None

        return {
            'group': elem.get('group_name', ''),
            'cascader': ref,
            'field_prefix': elem.get('field_key', ''),
        }

    def find_button(self, label, preferred_container=None, prefer_row=False):
        """根据按钮标签查找 locator 引用。
        L2: 传入 type_hint='button' 启用类型过滤。
        """
        _debug_f7(f"  [DEBUG-F7] find_button: label='{label}', "
              f"preferred_container='{preferred_container}', "
              f"current_context='{self._current_context}'")

        elem = self._discovery_lookup(label, type_hint='button')
        if not elem:
            _debug_f7(f"  [DEBUG-F7] find_button: 未找到 '{label}'")
            return None

        ref = self._elem_to_ref(elem)
        if not ref:
            _debug_f7(f"  [DEBUG-F7] find_button: _elem_to_ref 返回 None")
            return None

        _debug_f7(f"  [DEBUG-F7] find_button: → {ref}")

        if prefer_row:
            group = ref.split('.')[0].strip('${')
            field = ref.split('.')[1].strip('}')
            fields = self._compat_groups().get(group, {})
            row_key = f"{field}_row"
            if row_key in fields:
                row_ref = f"${{{group}.{row_key}}}"
                _debug_f7(f"  [DEBUG-F7] find_button: prefer_row → {row_ref}")
                return row_ref

        return ref

    def find_all_buttons(self, label):
        """返回同名标签的所有候选按钮。"""
        results = []
        seen_refs = set()
        for (ctx, disc_label), elem in self._discovery_element_map.items():
            if disc_label != label and self._substring_similarity(label, disc_label) < 0.6:
                continue
            ref = self._elem_to_ref(elem)
            if ref and ref not in seen_refs:
                seen_refs.add(ref)
                results.append({
                    'ref': ref,
                    'container': elem.get('container_type'),
                })
        return results

    # Scheme 2: 类型守卫 — fill/textarea 步骤不兼容的元素类型
    _FILL_INCOMPATIBLE_TYPES = frozenset({
        'button', 'row_button', 'download-button', 'close-button',
        'tab', 'detail_link', 'checkbox', 'menu_item',
    })

    def find_input(self, label, preferred_container=None):
        """根据标签查找输入框 locator 引用。

        Scheme 2: 类型守卫 — fill/textarea 步骤不应匹配 button/row_button。
        防止 "在「进展更新」中输入" 误匹配到 "进展更新" 行按钮。
        L2: 传入 type_hint='input' 启用类型过滤。
        """
        elem = self._discovery_lookup(label, type_hint='input')
        if not elem:
            return None, None

        # ── Scheme 2: 类型守卫 ──
        elem_type = elem.get('type', '')
        if elem_type in self._FILL_INCOMPATIBLE_TYPES:
            print(f"    [WARN] find_input('{label}'): discovery 匹配到 "
                  f"'{elem_type}' 类型，与 fill 步骤不兼容，跳过")
            return None, None

        ref = self._elem_to_ref(elem)
        if not ref:
            return None, None

        field_key = elem.get('field_key', '')
        field_without_ct = self._CT_HASH_RE.sub('', field_key)
        field_prefix = field_without_ct
        for suf in ('_input', '_textarea'):
            if field_without_ct.endswith(suf):
                field_prefix = field_without_ct[:-len(suf)]
                break

        info = {
            'field_prefix': field_prefix,
            'group': elem.get('group_name', ''),
        }
        return ref, info

    # ─── Discovery 查找链 ─────────────────────────────────────

    def _get_discovery_container_type(self, button_label):
        entry = self._discovery_trigger_map.get(button_label)
        if entry:
            return entry.get('container_type')
        return None

    def _lookup_discovery_element(self, label, context=None):
        """从 discovery_element_map 查找元素（三层 context 回退）。

        多URL场景：优先按 page_slug 精确索引查找，避免跨URL同名覆盖。
        """
        ctx = context or self._current_context or 'list_page'
        page_slug = self._get_current_page_slug()

        # 多URL精确索引：优先按 page_slug 查找
        if page_slug:
            elem = self._discovery_page_element_map.get((page_slug, ctx, label))
            if elem and elem.get('locator'):
                return elem
            # 容器回退到 list_page
            if ctx != 'list_page':
                elem = self._discovery_page_element_map.get((page_slug, 'list_page', label))
                if elem and elem.get('locator'):
                    return elem

        # 向后兼容：原有逻辑
        elem = self._discovery_element_map.get((ctx, label))
        if elem and elem.get('locator'):
            return elem
        if ctx != 'list_page':
            is_container_ctx = ctx in self._discovery_trigger_map
            if is_container_ctx:
                print(f"    [WARN] '{label}' 在容器 '{ctx}' 中未发现，"
                      f"跳过 list_page 回退（避免无前缀引用）")
                return None
            elem = self._discovery_element_map.get(('list_page', label))
            if elem and elem.get('locator'):
                return elem
        for (c, l), e in self._discovery_element_map.items():
            if l == label and e.get('locator'):
                if ctx in self._discovery_trigger_map:
                    continue
                return e
        return None

    def _discovery_lookup(self, label, context=None, type_hint=None):
        """discovery 四步查找链 — 精确→别名→子串→None"""
        ctx = context or self._current_context or 'list_page'
        _debug_f7(f"  [DEBUG-F7] _discovery_lookup: label='{label}', "
              f"context_param='{context}', current_context='{self._current_context}', "
              f"effective_ctx='{ctx}'")

        elem = self._lookup_discovery_element(label, ctx)
        if elem:
            group = elem.get('group_name', '?')
            field = elem.get('field_key', '?')
            _debug_f7(f"  [DEBUG-F7] → 精确匹配: {group}.{field}")
            return elem

        best_elem = None
        best_score = 0.4
        is_container_ctx = ctx in self._discovery_trigger_map
        _debug_f7(f"  [DEBUG-F7] 精确匹配失败，开始子串搜索 (is_container_ctx={is_container_ctx})")

        # L2: 类型兼容性映射（子串搜索时过滤不兼容类型）
        _TYPE_COMPAT = {
            'button': {'button', 'table-action-button', 'close-button', 'search-button'},
            'input': {'input', 'textarea'},
            'el-select': {'el-select', 'el-cascader'},
            'textarea': {'textarea', 'input'},
            'el-cascader': {'el-cascader', 'el-select'},
        }

        def _type_ok(elem):
            if not type_hint:
                return True
            elem_type = elem.get('type', '')
            if not elem_type:
                return True  # 无类型信息时不过滤
            compat = _TYPE_COMPAT.get(type_hint)
            if compat:
                return elem_type in compat
            return elem_type == type_hint

        # 多URL场景：子串搜索也只搜当前 page_slug 的元素
        page_slug = self._get_current_page_slug()
        if page_slug:
            for (ps, c, disc_label), e in self._discovery_page_element_map.items():
                if ps and ps != page_slug:
                    continue  # 跳过其他 URL 的元素
                if c != ctx and c != 'list_page':
                    continue
                if is_container_ctx and c == 'list_page':
                    continue
                if not _type_ok(e):
                    continue  # L2: 类型不兼容，跳过
                score = self._substring_similarity(label, disc_label)
                if score >= best_score:
                    best_score = score
                    best_elem = e
                    _debug_f7(f"  [DEBUG-F7]   候选: ps='{ps}', ctx='{c}', disc_label='{disc_label}', score={score:.2f}")
        else:
            for (c, disc_label), e in self._discovery_element_map.items():
                if c != ctx and c != 'list_page':
                    continue
                if is_container_ctx and c == 'list_page':
                    continue
                if not _type_ok(e):
                    continue  # L2: 类型不兼容，跳过
                score = self._substring_similarity(label, disc_label)
                if score >= best_score:
                    best_score = score
                    best_elem = e
                    _debug_f7(f"  [DEBUG-F7]   候选: ctx='{c}', disc_label='{disc_label}', score={score:.2f}")

        if best_elem and best_elem.get('locator'):
            group = best_elem.get('group_name', '?')
            field = best_elem.get('field_key', '?')
            _debug_f7(f"  [DEBUG-F7] → 子串匹配: {group}.{field} (score={best_score:.2f})")
            return best_elem

        _debug_f7(f"  [DEBUG-F7] → 未找到匹配")
        return None

    @staticmethod
    def _substring_similarity(a, b):
        if not a or not b:
            return 0.0
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if shorter in longer:
            return len(shorter) / len(longer)
        return 0.0

    def _elem_to_ref(self, elem):
        """discovery element → ${group.field} 引用（F-D 安全检查）。"""
        return self.resolver.resolve_ref(elem)

    # ─── 容器上下文管理 ───────────────────────────────────────

    _CONTAINER_CLOSE_KEYWORDS = ('取消', '关闭', '返回', '确定', '保存', '提交')
    _CONTAINER_OPEN_KEYWORDS = ('新增', '编辑', '添加', '修改', '创建')

    def _is_container_close(self, parsed):
        ptype = parsed['type']
        args = parsed['args']
        # ===== 新增：处理 if_visible 包裹的关闭按钮 =====
        # 当"确定"/"取消"按钮被 if_visible 包裹时，同样需要识别为容器关闭操作
        if ptype == 'if_visible' and args:
            label = args[0]
            return any(kw in label for kw in self._CONTAINER_CLOSE_KEYWORDS)
        if ptype == 'click_btn' and args:
            label = args[0]
            return any(kw in label for kw in self._CONTAINER_CLOSE_KEYWORDS)
        return ptype in ('go_back', 'refresh')

    def _is_container_open(self, parsed):
        ptype = parsed['type']
        args = parsed['args']
        # ===== 新增：处理 if_visible 类型 =====
        # 当按钮（如"新增"）被 if_visible 包裹时，同样需要识别为容器打开操作
        if ptype == 'if_visible' and args:
            label = args[0]
            entry = self._discovery_trigger_map.get(label)
            if entry:
                result_type = entry.get('result_type')
                is_open = result_type in ('container', 'navigation')
                _debug_f7(f"  [DEBUG-F7] _is_container_open: if_visible label='{label}', "
                      f"result_type={result_type} → {is_open}")
                return is_open
            # if_visible 不匹配 heuristic（保守策略）
            _debug_f7(f"  [DEBUG-F7] _is_container_open: if_visible label='{label}' "
                  f"no trigger_map entry → False")
            return False
        if ptype in ('click_btn', 'click_table_row_btn') and args:
            label = args[0] if args else ''
            entry = self._discovery_trigger_map.get(label)
            _debug_f7(f"  [DEBUG-F7] _is_container_open: label='{label}', "
                  f"trigger_map_hit={entry is not None}, "
                  f"result_type={entry.get('result_type') if entry else 'N/A'}")
            if entry:
                result_type = entry.get('result_type')
                is_open = result_type in ('container', 'navigation')
                _debug_f7(f"  [DEBUG-F7] → returns {is_open} (from trigger_map)")
                return is_open
            heuristic_hit = any(kw in label for kw in self._CONTAINER_OPEN_KEYWORDS)
            _debug_f7(f"  [DEBUG-F7] → returns {heuristic_hit} (from heuristic: {self._CONTAINER_OPEN_KEYWORDS})")
            return heuristic_hit
        if ptype == 'click_table_row_btn' and not args:
            _debug_f7(f"  [DEBUG-F7] _is_container_open: click_table_row_btn without args → True")
            return True
        # 点击详情链接：检查 trigger map 判断是否打开容器/导航
        if ptype == 'click_detail_link':
            dl_label = args[0] if args else ''
            entry = self._discovery_trigger_map.get(dl_label)
            if entry:
                result_type = entry.get('result_type')
                is_open = result_type in ('container', 'navigation')
                _debug_f7(f"  [DEBUG-F7] _is_container_open: detail_link label='{dl_label}', "
                      f"result_type={result_type} → {is_open}")
                return is_open
            # trigger map 无匹配 → 保守假设不打开容器（保持列表页上下文）
            _debug_f7(f"  [DEBUG-F7] _is_container_open: detail_link label='{dl_label}' "
                  f"no trigger_map entry → False (conservative)")
            return False
        _debug_f7(f"  [DEBUG-F7] _is_container_open: ptype='{ptype}' → False")
        return False

    def _is_button_action(self, parsed):
        return parsed.get('type') in self._BUTTON_TYPES

    def _next_needs_no_wait(self, raw_steps, idx):
        if idx + 1 >= len(raw_steps):
            return False
        next_parsed = parse_step(raw_steps[idx + 1])
        return next_parsed.get('type') in self._NO_WAIT_AFTER_TYPES

    def _update_container_context_pre(self, parsed):
        if parsed['type'] in ('go_back', 'refresh'):
            self.current_container = None

    def _update_container_context_post(self, parsed):
        _debug_f7(f"  [DEBUG-F7] _update_container_context_post: "
              f"type='{parsed['type']}', args={parsed['args']}, "
              f"current_context='{self._current_context}'")

        if self._is_container_open(parsed):
            btn_label = ''
            if parsed['type'] in ('click_btn', 'click_table_row_btn', 'click_detail_link', 'if_visible') and parsed['args']:
                btn_label = parsed['args'][0]

            entry = self._discovery_trigger_map.get(btn_label) if btn_label else None

            if entry:
                result_type = entry.get('result_type')
                if result_type == 'container':
                    self.current_container = entry.get('container_type')
                elif result_type == 'navigation':
                    self.current_container = 'new_page'
                    self._pending_nav_wait = True
                elif result_type == 'inline':
                    pass
                self._current_context = btn_label
                _debug_f7(f"  [DEBUG-F7] → 更新 _current_context='{btn_label}', "
                      f"current_container='{self.current_container}' (from trigger_map)")
            else:
                dominant = self._detect_dominant_container()
                self.current_container = dominant
                self._current_context = btn_label or 'unknown'
                _debug_f7(f"  [DEBUG-F7] → 更新 _current_context='{self._current_context}', "
                      f"current_container='{self.current_container}' (from heuristic)")
                if not dominant:
                    print(f"  [WARN] 按钮 '{btn_label}' 无 discovery 数据且无容器信息")
        elif self._is_container_close(parsed) and parsed['type'] in ('click_btn', 'if_visible'):
            self.current_container = None
            self._current_context = 'list_page'
            _debug_f7(f"  [DEBUG-F7] → 容器关闭，重置 _current_context='list_page'")
        else:
            _debug_f7(f"  [DEBUG-F7] → 未触发上下文更新 (is_close={self._is_container_close(parsed)})")

    def _detect_dominant_container(self):
        """从 resolver groups 推断当前模块的主要容器类型。"""
        container_fields = {'drawer': 0, 'dialog': 0, 'message-box': 0}
        groups = self._compat_groups()
        for gname, fields in groups.items():
            if gname == 'common_elements':
                continue
            for locator in fields.values():
                if isinstance(locator, str):
                    ct = _detect_container_type(locator)
                    if ct and ct in container_fields:
                        container_fields[ct] += 1
                        break
        best = max(container_fields, key=container_fields.get)
        return best if container_fields[best] > 0 else None

    _TRIGGER_TO_SLUG = {
        '新增': 'add', '添加': 'add', '创建': 'add',
        '编辑': 'edit', '修改': 'edit',
        '详情': 'detail', '查看': 'detail',
    }

    def _trigger_to_slug(self, trigger):
        return self._TRIGGER_TO_SLUG.get(trigger, trigger)

    def _find_tab_element(self, label):
        """在 resolver groups 中查找 tab 元素引用。"""
        groups = self._compat_groups()
        for group_name, fields in groups.items():
            for field_name, locator in fields.items():
                if not isinstance(locator, str):
                    continue
                if field_name.endswith('_tab') and label in locator:
                    return f"${{{group_name}.{field_name}}}"
                if "@role='tab'" in locator and label in locator:
                    return f"${{{group_name}.{field_name}}}"
        pending_ref, _ = self.resolver.make_pending_ref(
            label, 'tab',
            container_type=self.current_container,
            module_slug=self.module)
        return pending_ref or f"xpath=[待确认]"

    def _is_visibility_assertion(self, text):
        return any(kw in text for kw in self._VISIBILITY_KW)

    @staticmethod
    def _cn_to_int(text):
        text = text.strip()
        cn_map = {
            '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        }
        if text in cn_map:
            return cn_map[text]
        try:
            return int(text)
        except ValueError:
            return 1

    def _build_count_row_xpath(self, section):
        if section:
            # Fix-5b: 增强引号提取 — 覆盖所有引号类型（含标准 ASCII 双引号）
            quoted = re.findall(
                r'["“”「」‘’"]([^"“”「」‘’"]+)'
                r'["“”「」‘’"]',
                section
            )
            if quoted:
                section = quoted[0]
            # 去除常见外层描述词
            section = re.sub(r'^(包含|含有|包括|显示|搜索|关键词|匹配)(?=[：:\s""\"「「''“”「」‘’])', '', section).strip()
            section = re.sub(r'(记录|数据|列表|信息|的行|的结果|的条目)$', '', section).strip()
            if section:
                xpath = f"//tbody/tr[.//*[contains(.,'{section}')]]"
                return _inject_hidden_filter(xpath)
            else:
                # 空 section 不加隐藏过滤：inject_hidden_filter 对 //tbody/tr（无 predicate）
                # 会将过滤加到 tbody 而非 tr，语义不对。//tbody/tr 匹配所有行，无需过滤。
                xpath = "//tbody/tr"
        else:
            xpath = "//tbody/tr"
        return xpath

    def _clean_assertion_label(self, label):
        if not label:
            return label
        cleaned = self._ASSERTION_VIS_PREFIX_RE.sub('', label).strip()
        cleaned = cleaned.strip('"""\'\'「」『』')
        return cleaned if cleaned else label

    def _extract_keywords(self, text):
        quoted = re.findall(r'[""\'"「]([^""\'"」「]+)[""\'"」]', text)
        if quoted:
            return [q.strip() for q in quoted if q.strip()]

        text = re.sub(r'^(页面)?(正确)?(显示)?(验证)?', '', text)
        text = re.sub(r'(可见|显示|存在|展示|出现|正确)$', '', text)
        text = re.sub(r'(?:之后|后|之前|前)$', '', text)
        text = re.sub(r'^(?:返回|进入|打开|关闭|点击\S+?)(?=\S)', '', text)
        text = re.sub(r'(?<=[一-鿿])(?:之后|后)(?!台|面|来|续|端|果|天|半|备|继)', '', text)
        parts = re.split(r'[、，,]', text)
        keywords = []
        for p in parts:
            p = self._STRIP_SUFFIX.sub('', p).strip()
            if p and len(p) < 3:
                print(f"[WARN] M16: 断言关键词过短 '{p}'（{len(p)}字符），"
                      f"可能匹配过多元素（原文: {text}）")
            if p:
                keywords.append(p)
        return keywords if keywords else [text]

    @staticmethod
    def _extract_quoted_text(text):
        m = re.search(f"{Q}(.*?){Q}", text)
        return m.group(1) if m else ''

    # ─── Workflow 加载 ────────────────────────────────────────

    def _load_workflows(self):
        if self._workflow_cache is not None:
            return self._workflow_cache

        cache = {}
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        sys_path = os.path.join(skill_dir, 'lib', 'system_workflows.yaml')
        if os.path.isfile(sys_path):
            try:
                data = yaml.safe_load(open(sys_path, encoding='utf-8'))
                for wf in (data or {}).get('workflows', []):
                    cn = wf.get('chinese_name')
                    if cn:
                        cache[cn] = wf
            except Exception as _e:
                print(f"  [WARN] L3 workflow 加载失败: {sys_path}: {_e}")

        skill_knowledge_dir = os.path.join(skill_dir, 'lib', '_knowledge')
        if os.path.isdir(skill_knowledge_dir):
            for f in sorted(glob.glob(os.path.join(skill_knowledge_dir, '*.yaml'))):
                try:
                    data = yaml.safe_load(open(f, encoding='utf-8'))
                    wfs = (data or {}).get('workflows', [])
                    if isinstance(wfs, dict):
                        wfs = [{'name': k, **v} for k, v in wfs.items()]
                    for wf in (wfs or []):
                        cn = wf.get('chinese_name')
                        if cn:
                            cache[cn] = wf
                except Exception:
                    pass

        if self._project_dir:
            knowledge_dir = os.path.join(self._project_dir, '_knowledge')
            if os.path.isdir(knowledge_dir):
                for f in sorted(glob.glob(os.path.join(knowledge_dir, '*.yaml'))):
                    if os.path.basename(f) == 'workflow_aliases.yaml':
                        continue
                    try:
                        data = yaml.safe_load(open(f, encoding='utf-8'))
                        wfs = (data or {}).get('workflows', [])
                        if isinstance(wfs, dict):
                            wfs = [{'name': k, **v} for k, v in wfs.items()]
                        for wf in (wfs or []):
                            cn = wf.get('chinese_name')
                            if cn:
                                cache[cn] = wf
                    except Exception:
                        pass

        self._workflow_cache = cache
        return cache

    def _find_workflow(self, cn_name):
        cache = self._load_workflows()
        return cache.get(cn_name)

    def _find_section_row_link(self, section_name):
        groups = self._compat_groups()
        return _find_section_row_link(groups, section_name)

    # ─── 用例上下文 ──────────────────────────────────────────

    def set_case_context(self, case_seq):
        self.current_case_prefix = f"case{case_seq:02d}_"
        self.current_container = None
        self.current_tab_scope = None
        self.current_tab_scope_label = None
        self._random_name_counter = 0

    def add_data(self, field, value):
        self.data_entries.setdefault(self.data_group_name, {})
        actual_field = f"{self.current_case_prefix}{field}"
        self.data_entries[self.data_group_name][actual_field] = value
        return f"${{{self.data_group_name}.{actual_field}}}"

    def _track_field(self, group, field, locator='', label='', comment=''):
        """记录被引用的字段（供 PagesWriter 按需生成 pages YAML）。"""
        key = (group, field)
        if key in self.required_fields:
            existing = self.required_fields[key]
            existing_locator = existing.get('locator', '')
            if existing_locator and locator and existing_locator != locator:
                print(f"  [WARN] _track_field 冲突: {group}.{field}")
                print(f"         已有: {existing_locator}")
                print(f"         新增: {locator}")
        self.required_fields[key] = {
            'locator': locator,
            'label': label,
            'comment': comment,
        }
        # H2: 新字段注册时清除缓存（下次 _compat_groups 调用会重新构建）
        self._compat_groups_cache = None

    def _get_table_group_name(self):
        """获取表格区域的 group name（供 detail_link / count_row 使用）。

        优先查找列表页 group（不含容器前缀），避免 find_group_for_container(None)
        错误返回 drawer/dialog group。
        """
        prefix = self.module.replace('-', '_')
        _container_markers = ('el-drawer', 'el-dialog', 'el-message-box')
        # 在 resolver 的 group_map 中找第一个非容器、非同模块的 group
        for gname in self.resolver._group_map:
            if gname == 'common_elements' or gname.startswith('common_'):
                continue
            if not gname.startswith(prefix):
                continue
            # 检查是否包含容器标记
            is_container = False
            for entry in self.resolver._group_map[gname].values():
                if entry.locator and any(m in str(entry.locator)
                                         for m in _container_markers):
                    is_container = True
                    break
            if not is_container:
                return gname
        # 兜底：构造标准列表页 group 名
        return self.resolver.get_group_name(self.module, page_slug=self._get_current_page_slug())

    def get_required_fields(self):
        """返回所有被引用的字段。

        Returns: {(group, field): {locator, label, comment}}
        """
        return self.required_fields

    def collect_refs_from_steps(self, steps):
        """从生成的步骤中提取所有 ${group.field} 引用并记录到 required_fields。

        应在 generate_step() 返回后调用。
        """
        import re as _re
        _ref_re = _re.compile(r'\$\{([^}]+)\}')

        def _scan(obj):
            if isinstance(obj, str):
                for m in _ref_re.finditer(obj):
                    ref = m.group(1)
                    if '.' in ref:
                        group, field = ref.split('.', 1)
                        # R6 Defense 2: cross-module reference detection
                        if self.module:
                            _r6_prefix = self.module.replace('-', '_')
                            if (group != 'common_elements'
                                    and not group.startswith('common_')
                                    and not group.startswith(_r6_prefix)
                                    and not group.startswith('dropdown_menu')):
                                _r6_new_group = f"{_r6_prefix}_elements"
                                print(f"    [WARN R6] 跨模块引用检测: "
                                      f"${{{group}.{field}}} → "
                                      f"${{{_r6_new_group}.{field}}}")
                                if (_r6_new_group, field) not in self.required_fields:
                                    # H1: 从 resolver 查找新 group 中该 field 的 locator
                                    _r6_loc = ''
                                    _r6_gm = self.resolver.get_groups().get(_r6_new_group, {})
                                    _r6_entry = _r6_gm.get(field)
                                    if _r6_entry:
                                        _r6_loc = _r6_entry.locator or ''
                                    if not _r6_loc:
                                        _r6_loc = 'xpath=[待确认]'
                                        print(f"    [WARN R6] 跨模块改写无 locator: "
                                              f"${{{_r6_new_group}.{field}}} → [待确认]")
                                    self._track_field(_r6_new_group, field,
                                                      locator=_r6_loc, label='',
                                                      comment='R6: cross-module rewrite')
                                continue  # skip registering original cross-module ref
                        # Normal registration
                        if (group, field) not in self.required_fields:
                            # 查找 locator 值
                            loc = ''
                            gm = self.resolver.get_groups().get(group, {})
                            entry = gm.get(field)
                            if entry:
                                loc = entry.locator or ''
                            self._track_field(group, field, locator=loc)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _scan(v)
            elif isinstance(obj, list):
                for v in obj:
                    _scan(v)

        _scan(steps)

    def _try_expand_random_name(self, value, field, steps):
        m = self._RANDOM_NAME_RE.search(str(value))
        if not m:
            return value, False

        prefix = m.group(1)
        self._random_name_counter += 1

        var_name = f"random_{field}"
        if self._random_name_counter > 1:
            var_name = f"{var_name}_{self._random_name_counter}"

        prefix_ref = self.add_data(f'{field}_random_prefix', prefix)

        steps.append({
            'desc': f'生成随机名称({field})',
            'keyword': 'set_random_variable',
            'params': {
                'name': var_name,
                'prefix': prefix_ref,
            },
        })

        return f'${{{var_name}}}', True

    def _build_multi_candidate_click(self, label, candidates):
        result = {
            'desc': f'点击「{label}」按钮',
            'keyword': 'click_element',
            'params': {'locator': candidates[-1]['ref']},
        }

        for i in range(len(candidates) - 2, -1, -1):
            c = candidates[i]
            container_desc = c['container'] or '页面'
            result = {
                'desc': f'点击「{label}」按钮（{container_desc}优先）',
                'keyword': 'if_element_visible',
                'params': {
                    'locator': c['ref'],
                    'timeout': 300,
                    'then_steps': [{
                        'desc': f'点击「{label}」按钮',
                        'keyword': 'click_element',
                        'params': {'locator': c['ref']},
                    }],
                    'else_steps': [result],
                },
            }

        return result

    # ─── Page context ────────────────────────────────────────

    def set_page_context(self, url):
        """设置当前 page context（根据 URL 限定搜索范围）。"""
        self._current_page_url = url

    def _get_current_page_slug(self):
        """从 _current_page_url 反查 page_slug。

        Returns: page_slug 或 None
        """
        if not self._current_page_url:
            return None
        return self.resolver.url_to_page_slug(self._current_page_url)

    def _get_common(self, field_name):
        """获取 common_elements 中的 locator 引用。"""
        if field_name in COMMON_ELEMENTS:
            return f"${{common_elements.{field_name}}}"
        return None

    # ─── generate_step 核心 ──────────────────────────────────

    def generate_step(self, parsed):
        """将解析后的步骤转换为 YAML 步骤列表"""
        steps = []
        ptype = parsed['type']
        args = parsed['args']

        if ptype == 'skip':
            return []

        elif ptype == 'open_url':
            url = args[0]
            data_ref = self.add_data('page_url', url)
            steps.append({
                'desc': f"访问页面",
                'keyword': 'open_url',
                'params': {'url': data_ref},
            })
            self.set_page_context(url)

        elif ptype == 'el_select':
            if len(args) == 3:
                # 带序号: label, nth, value
                label, nth_raw, value = args
                nth = self._cn_to_int(nth_raw)
                self._emit_el_select_steps(steps, label, value, nth=nth)
            else:
                # 无序号: label, value (默认 nth=1)
                label, value = args[0], args[1]
                self._emit_el_select_steps(steps, label, value, nth=1)

        elif ptype == 'el_cascader':
            label = args[0]
            values_raw = args[1] if len(args) > 1 else ''
            _q_vals = re.findall(r'[""“”\']([^""“”\']+?)[""“”\']',
                                 values_raw)
            if _q_vals:
                value = '、'.join(_q_vals)
            else:
                value = values_raw
            levels = [l.strip() for l in value.replace('、', '/').split('/')]
            el = self.find_el_cascader(label, preferred_container=self.current_container)
            if not el:
                pending_ref, pending_key = self.resolver.make_pending_ref(
                    label, 'el_cascader',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    el = {
                        'group': pending_ref.split('.')[0].strip('${'),
                        'cascader': pending_ref,
                        'field_prefix': pending_key or label,
                    }
            if el:
                steps.append({
                    'desc': f'展开「{label}」级联选择器',
                    'keyword': 'click_element',
                    'params': {'locator': el['cascader']},
                })
                for i, text in enumerate(levels[:-1]):
                    level_ref = self.add_data(f'{el["field_prefix"]}_level{i+1}', text)
                    level_xpath = f"//li[@role='menuitem']//span[contains(text(),'{level_ref}')]"
                    level_xpath = _inject_hidden_filter(level_xpath)
                    steps.append({
                        'desc': f'「{label}」第{i+1}级: {text}',
                        'keyword': 'click_element',
                        'params': {
                            'locator': f"xpath={level_xpath}"
                        },
                    })
                last = levels[-1]
                last_ref = self.add_data(f'{el["field_prefix"]}_last', last)
                checkbox_xpath = (f"//li[@role='menuitem' and contains(.,'{last_ref}')]"
                                 f"//span[@class='el-checkbox__inner']")
                checkbox_xpath = _inject_hidden_filter(checkbox_xpath)
                checkbox_xpath = f"xpath={checkbox_xpath}"
                text_xpath = (f"//li[@role='menuitem']//span"
                             f"[contains(text(),'{last_ref}')]")
                text_xpath = _inject_hidden_filter(text_xpath)
                text_xpath = f"xpath={text_xpath}"
                steps.append({
                    'desc': f'「{label}」最后一级: {last}',
                    'keyword': 'if_element_visible',
                    'params': {
                        'locator': checkbox_xpath,
                        'timeout': 500,
                        'then_steps': [{
                            'desc': f'「{label}」 - 点击勾选框',
                            'keyword': 'click_element',
                            'params': {'locator': checkbox_xpath},
                        }],
                        'else_steps': [{
                            'desc': f'「{label}」 - 点击文本',
                            'keyword': 'click_element',
                            'params': {'locator': text_xpath},
                        }],
                    },
                })
            else:
                steps.append({
                    'desc': f'[待确认] 在「{label}」级联选择器中选择「{value}」',
                    'keyword': 'log',
                    'params': {'message': f"[PENDING-NO-GROUP] 未找到'{label}'对应的级联选择器定位器，请手动补充"},
                })

        elif ptype == 'option_card':
            label, value = args[0], args[1]
            # 选项卡：单次点击选项文本
            # 生成 field prefix（hash-based）
            field_with_suffix = _shared_label_to_key(
                label, 'option_card',
                container_type=self.current_container,
                skip_container_prefix=True)
            field = field_with_suffix[:-len('_card')] if field_with_suffix.endswith('_card') else field_with_suffix

            # 确定 group
            group = self.resolver.get_group_name(
                self.module,
                page_slug=self._get_current_page_slug(),
                container_type=self.current_container,
                trigger=self._current_context)
            if not group:
                group = self.resolver.construct_pending_group(
                    self.current_container, self.module,
                    page_slug=self._get_current_page_slug(),
                    trigger=self._current_context)

            # KB 标准 XPath
            card_xpath = (
                f"//label[contains(.,'{label}')]"
                f"//following-sibling::*[self::div or self::span]"
                f"//*[contains(text(),'{value}')]"
            )

            # 容器前缀
            card_xpath = apply_container_prefix(card_xpath, self.current_container)

            # 注册到 required_fields
            self._track_field(group, f'{field}_card',
                              locator=f'xpath={card_xpath}',
                              label=label,
                              comment='option-card KB 标准模式')

            # 生成引用
            card_ref = f'${{{group}.{field}_card}}'

            # 单步点击
            steps.append({
                'desc': f"在「{label}」选项卡中选择「{value}」",
                'keyword': 'click_element',
                'params': {'locator': card_ref},
            })

        elif ptype in ('fill', 'textarea'):
            label, value = args[0], args[1]

            # N8: fill/el-select 冲突警告
            if any(kw in label for kw in ('下拉', '选择', 'select', '下拉框')):
                print(f"    [WARN N8] fill 步骤字段 '{label}' 疑似下拉框，"
                      f"建议改用 el-select 语法（如：在「{label}」中选择「{value}」）")

            locator_ref, field_info = self.find_input(label, preferred_container=self.current_container)
            if locator_ref:
                field = field_info.get('field_prefix', label) if field_info else label
                group = field_info.get('group') if field_info else None

                # ── Plan A：容器前缀注入（与 _emit_el_select_steps 对称） ──
                # 在容器上下文中，预注册带容器前缀的 locator 到 required_fields，
                # 防止 collect_refs_from_steps 注册无前缀版本 → 运行时 strict mode violation
                if (self.current_container
                        and self.current_container not in ('new_page', None)
                        and group and field):
                    disc_elem = self._discovery_lookup(label)
                    if disc_elem:
                        raw_locator = disc_elem.get('locator', '')
                        if raw_locator and raw_locator.startswith('xpath='):
                            raw_xpath = raw_locator[6:]
                            prefixed_xpath = self._add_container_prefix_to_xpath(raw_xpath)
                            if prefixed_xpath != raw_xpath:
                                # 确定字段后缀（_input 或 _textarea）
                                # BUG-FIX: 先去除容器 hash 后缀再检测类型后缀
                                elem_fk = disc_elem.get('field_key', '')
                                elem_fk_no_ct = self._CT_HASH_RE.sub('', elem_fk)
                                if elem_fk_no_ct.endswith('_textarea'):
                                    f_suffix = '_textarea'
                                else:
                                    f_suffix = '_input'
                                self._track_field(group, f'{field}{f_suffix}',
                                                  locator=f'xpath={prefixed_xpath}',
                                                  label=label,
                                                  comment='Plan A: 容器前缀注入')

                resolved_value, is_random = self._try_expand_random_name(
                    value, field, steps)
                if is_random:
                    data_ref = resolved_value
                else:
                    data_ref = self.add_data(f'{field}_text', value)

                meta_key = (group, f'{field}_textarea') if group else None
                meta = self.field_meta.get(meta_key) if meta_key else None
                if meta and meta.get('type') == 'tinymce':
                    frame_ref = f"${{{group}.{meta['frame']}}}"
                    body_ref = f"${{{group}.{meta['body']}}}"
                    steps.append({
                        'desc': f"在「{label}」中输入（富文本）",
                        'keyword': 'frame_fill_value',
                        'params': {'frame': frame_ref, 'locator': body_ref, 'value': data_ref},
                    })
                else:
                    steps.append({
                        'desc': f"在「{label}」中输入",
                        'keyword': 'fill_value',
                        'params': {'locator': locator_ref, 'value': data_ref},
                    })
            else:
                # Fallback 路径 — Scheme 2b: 统一类型守卫
                disc_elem = self._discovery_lookup(label)

                # ── Scheme 2b: 与 find_input() 相同的类型守卫 ──
                if disc_elem:
                    elem_type = disc_elem.get('type', '')
                    if elem_type in self._FILL_INCOMPATIBLE_TYPES:
                        print(f"    [WARN] fallback lookup('{label}'): "
                              f"匹配到 '{elem_type}'，与 fill 不兼容，跳过")
                        disc_elem = None

                disc_ref = self._elem_to_ref(disc_elem) if disc_elem else None
                if disc_ref:
                    locator_ref = disc_ref
                    data_ref = self.add_data(f'{label}_text', value)
                    steps.append({
                        'desc': f"在「{label}」中输入",
                        'keyword': 'fill_value',
                        'params': {'locator': locator_ref, 'value': data_ref},
                    })
                else:
                    # Scheme 3a: 从 ptype 推断 pending 类型
                    pending_type = 'textarea' if ptype == 'textarea' else 'input'
                    pending_ref, pending_key = self.resolver.make_pending_ref(
                        label, pending_type,
                        container_type=self.current_container,
                        module_slug=self.module)
                    if pending_ref:
                        data_ref = self.add_data(f'{pending_key}_text', value)
                        steps.append({
                            'desc': f"[待确认] 在「{label}」中输入",
                            'keyword': 'fill_value',
                            'params': {'locator': pending_ref, 'value': data_ref},
                        })
                    else:
                        steps.append({
                            'desc': f"[待确认] 在「{label}」中输入「{value}」",
                            'keyword': 'log',
                            'params': {'message': f"[PENDING-NO-GROUP] 未找到'{label}'对应的输入框定位器"},
                        })

        elif ptype == 'click_btn':
            label = args[0]
            _CONFIRM_KW = {'确定': 'confirm_btn', '确认': 'confirm_btn',
                           '取消': 'cancel_btn', '关闭': 'close_btn', '提交': 'submit_btn'}
            if label in _CONFIRM_KW:
                _common_ref = self._get_common(_CONFIRM_KW[label])
                if _common_ref:
                    steps.append({
                        'desc': f'点击「{label}」按钮',
                        'keyword': 'click_element',
                        'params': {'locator': _common_ref},
                    })
                    return steps
            all_candidates = self.find_all_buttons(label)

            if len(all_candidates) == 1:
                steps.append({
                    'desc': f'点击「{label}」按钮',
                    'keyword': 'click_element',
                    'params': {'locator': all_candidates[0]['ref']},
                })
            elif len(all_candidates) > 1:
                steps.append(self._build_multi_candidate_click(
                    label, all_candidates))
            else:
                disc_elem = self._discovery_lookup(label)
                disc_ref = self._elem_to_ref(disc_elem) if disc_elem else None
                if disc_ref:
                    steps.append({
                        'desc': f'点击「{label}」按钮',
                        'keyword': 'click_element',
                        'params': {'locator': disc_ref},
                    })
                else:
                    pending_ref, pending_key = self.resolver.make_pending_ref(
                        label, 'button',
                        container_type=self.current_container,
                        module_slug=self.module)
                    if pending_ref:
                        steps.append({
                            'desc': f'[待确认] 点击「{label}」按钮',
                            'keyword': 'click_element',
                            'params': {'locator': pending_ref},
                        })
                    else:
                        steps.append({
                            'desc': f'[待确认] 点击「{label}」按钮',
                            'keyword': 'log',
                            'params': {'message': f"[PENDING-NO-GROUP] 未找到'{label}'按钮定位器"},
                        })

        elif ptype == 'click_table_action':
            label = args[0]
            groups = self._compat_groups()
            ref = _find_table_action(groups, label)
            if ref:
                steps.append({
                    'desc': f'点击第一条记录的「{label}」按钮',
                    'keyword': 'click_element',
                    'params': {'locator': ref},
                })
            else:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'table_action',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    steps.append({
                        'desc': f'[待确认] 点击第一条记录的「{label}」按钮',
                        'keyword': 'click_element',
                        'params': {'locator': pending_ref},
                    })
                else:
                    steps.append({
                        'desc': f'[待确认] 点击表格行操作「{label}」',
                        'keyword': 'log',
                        'params': {'message': f"[PENDING-NO-GROUP] 未找到表格行操作按钮'{label}'"},
                    })

        elif ptype == 'assert':
            desc_text = args[0]
            if self._is_visibility_assertion(desc_text):
                keywords = self._extract_keywords(desc_text)
                for kw in keywords:
                    kw = self._clean_assertion_label(kw)
                    kw_xpath = f"//*[contains(text(),'{kw}')]"
                    kw_xpath = _inject_hidden_filter(kw_xpath)
                    steps.append({
                        'desc': f"断言{kw}可见",
                        'keyword': 'except_to_be_visible',
                        'params': {
                            'locator': f"xpath={kw_xpath}"
                        },
                    })
            else:
                # Fix-2d: 断言分支重构 — 引号精确 > 成功通用 > 文本兜底
                # 优先级 1: 提取引号内容 → 精确匹配
                quoted = re.findall(r'[""\'"「]([^""\'"」「]+)[""\'"」]', desc_text)
                if quoted:
                    assert_text = quoted[0].strip()
                    kb_xpath = f"//*[contains(text(),'{assert_text}')]"
                    kb_xpath = _inject_hidden_filter(kb_xpath)
                    steps.append({
                        'desc': f"断言：{desc_text}",
                        'keyword': 'except_to_be_visible',
                        'params': {'locator': f'xpath={kb_xpath}'},
                    })
                # 优先级 2: 无引号 + 含"成功" → 通用成功断言
                elif '成功' in desc_text:
                    success_ref = self._get_common('success_text')
                    steps.append({
                        'desc': f"断言：{desc_text}",
                        'keyword': 'except_to_be_visible',
                        'params': {'locator': success_ref},
                    })
                else:
                    # 优先级 3: 非成功断言 → 提取原始文本兜底
                    assert_text = re.sub(r'^断言[：:]\s*', '', desc_text).strip()
                    if assert_text:
                        kb_xpath = f"//*[contains(text(),'{assert_text}')]"
                        kb_xpath = _inject_hidden_filter(kb_xpath)
                        steps.append({
                            'desc': f"断言：{desc_text}",
                            'keyword': 'except_to_be_visible',
                            'params': {'locator': f'xpath={kb_xpath}'},
                        })
                    else:
                        steps.append({
                            'desc': f"[待确认] 断言：{desc_text}",
                            'keyword': 'log',
                            'params': {'message': "未找到断言定位器"},
                        })

        elif ptype == 'assert_count':
            min_count_raw = args[0]
            section = args[1].strip() if len(args) > 1 else ''
            min_count = self._cn_to_int(min_count_raw)
            row_xpath = self._build_count_row_xpath(section)

            # Fix-5c: 存入 pages YAML，使用变量引用（符合 R4.3）
            group_name = self._get_table_group_name()
            case_suffix = self.current_case_prefix.replace('case', '').rstrip('_') or '00'
            field_key = f"count_row_{case_suffix}"
            self._track_field(group_name, field_key,
                              locator=f'xpath={row_xpath}',
                              label=section,
                              comment='Fix-5: assert_count 行计数定位器')

            steps.append({
                'desc': f"断言记录数≥{min_count}",
                'keyword': 'except_element_count',
                'params': {
                    'locator': f'${{{group_name}.{field_key}}}',
                    'min_count': min_count,
                },
            })

        elif ptype == 'assert_row':
            value = args[0]
            kb_xpath = _get_assertion_kb_pattern('first-row-content', keyword=value)
            if not kb_xpath:
                kb_xpath = f"//tbody/tr[1]//*[contains(.,'{value}')]"
            kb_xpath = _inject_hidden_filter(kb_xpath)
            steps.append({
                'desc': f"断言第一条记录包含'{value}'",
                'keyword': 'except_to_be_visible',
                'params': {
                    'locator': f"xpath={kb_xpath}"
                },
            })

        elif ptype == 'wait':
            desc = args[0].strip() if args else ''
            if '加载完成' in parsed['raw']:
                wf_def = self._find_workflow('等待加载完成')
                if wf_def:
                    steps.append({
                        'desc': f"等待{desc}加载完成",
                        'keyword': wf_def['name'],
                        'params': {},
                    })
                else:
                    steps.append({
                        'desc': f"等待{desc}加载完成",
                        'keyword': 'wait_for_time',
                        'params': {'timeout': 5000},
                    })
            else:
                steps.append({
                    'desc': f"等待{desc}",
                    'keyword': 'wait_for_time',
                    'params': {'timeout': 2000},
                })

        elif ptype == 'wait_time':
            ms = int(args[0]) * 1000
            steps.append({
                'desc': f"等待{args[0]}秒",
                'keyword': 'wait_for_time',
                'params': {'timeout': ms},
            })

        elif ptype == 'click':
            label = args[0]
            btn_ref = self.find_button(label, preferred_container=self.current_container)
            if not btn_ref:
                disc_elem = self._discovery_lookup(label)
                btn_ref = self._elem_to_ref(disc_elem) if disc_elem else None
            if btn_ref:
                steps.append({
                    'desc': f'点击「{label}」',
                    'keyword': 'click_element',
                    'params': {'locator': btn_ref},
                })
            else:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'click_btn',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    steps.append({
                        'desc': f'[待确认] 点击「{label}」',
                        'keyword': 'click_element',
                        'params': {'locator': pending_ref},
                    })
                else:
                    steps.append({
                        'desc': f'[待确认] 点击「{label}」',
                        'keyword': 'log',
                        'params': {'message': f"[PENDING-NO-GROUP] 未找到'{label}'的定位器"},
                    })

        elif ptype == 'date_select':
            label, value = args[0], args[1]
            locator_ref, _ds_field_info = self.find_input(label, preferred_container=self.current_container)
            if not locator_ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'date_select',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    locator_ref = pending_ref
                    _ds_field_info = None

            # Plan A: 日期选择器容器前缀注入
            if (locator_ref and _ds_field_info
                    and self.current_container
                    and self.current_container not in ('new_page', None)):
                _ds_group = _ds_field_info.get('group')
                _ds_field = _ds_field_info.get('field_prefix', '')
                if _ds_group and _ds_field:
                    _ds_elem = self._discovery_lookup(label)
                    if _ds_elem:
                        _ds_raw_loc = _ds_elem.get('locator', '')
                        if _ds_raw_loc.startswith('xpath='):
                            _ds_prefixed = self._add_container_prefix_to_xpath(_ds_raw_loc[6:])
                            if _ds_prefixed != _ds_raw_loc[6:]:
                                self._track_field(_ds_group, f'{_ds_field}_input',
                                                  locator=f'xpath={_ds_prefixed}',
                                                  label=label,
                                                  comment='Plan A: date_select 容器前缀')

            if locator_ref:
                steps.append({
                    'desc': f'点击「{label}」日期选择框',
                    'keyword': 'click_element',
                    'params': {'locator': locator_ref},
                })

                picker_ref = None
                groups = self._compat_groups()
                if '今天' in value:
                    picker_ref = (self._get_common('today_btn') or
                        next((f"${{{g}.{f}}}" for g, fs in groups.items()
                              for f in fs if 'today' in f), None))
                elif '此刻' in value:
                    picker_ref = (self._get_common('now_btn') or
                        next((f"${{{g}.{f}}}" for g, fs in groups.items()
                              for f in fs if 'now' in f), None))

                if picker_ref:
                    picker_xpath, picker_desc = _build_date_picker_xpath(value)
                    steps.append({
                        'desc': picker_desc,
                        'keyword': 'click_element',
                        'params': {'locator': picker_ref},
                    })
                else:
                    picker_xpath, picker_desc = _build_date_picker_xpath(value)
                    picker_xpath = _inject_hidden_filter(picker_xpath)
                    steps.append({
                        'desc': picker_desc,
                        'keyword': 'click_element',
                        'params': {'locator': f"xpath={picker_xpath}"},
                    })
            else:
                steps.append({
                    'desc': f'[待确认] 日期选择「{label}」',
                    'keyword': 'log',
                    'params': {'message': f"[PENDING-NO-GROUP] 未找到日期选择器'{label}'"},
                })

        elif ptype == 'click_tab':
            label = args[0]
            tab_ref = self._find_tab_element(label)

            steps.append({
                'desc': f'点击「{label}」tab',
                'keyword': 'click_element',
                'params': {'locator': tab_ref},
            })

            var_name = f"tab_{_slugify(label)}_id"
            steps.append({
                'desc': f'获取「{label}」tab面板ID',
                'keyword': 'get_attribute',
                'params': {
                    'locator': tab_ref,
                    'name': 'aria-controls',
                    'target_var': var_name,
                },
            })

            self.current_tab_scope = var_name
            self.current_tab_scope_label = label

        elif ptype == 'go_back':
            steps.append({
                'desc': "返回上一页",
                'keyword': 'go_back',
            })
            steps.append({
                'desc': "等待页面加载",
                'keyword': 'wait_for_time',
                'params': {'timeout': 2000},
            })

        elif ptype == 'refresh':
            steps.append({
                'desc': "刷新页面",
                'keyword': 'refresh',
            })

        elif ptype == 'confirm_dialog':
            confirm_ref = self._get_common('confirm_btn')
            if not confirm_ref:
                for _label in ('确认', '确定'):
                    confirm_ref = self.find_button(
                        _label, preferred_container=self.current_container)
                    if confirm_ref:
                        break
            if not confirm_ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    '确认', 'click_btn',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    confirm_ref = pending_ref
            steps.append({
                'desc': "确认弹窗",
                'keyword': 'click_element',
                'params': {'locator': confirm_ref},
            })

        elif ptype == 'confirm_delete':
            btn_label = args[0]
            confirm_ref = self._get_common('confirm_btn')
            if not confirm_ref:
                confirm_ref = self.find_button(btn_label, preferred_container=self.current_container)
            if not confirm_ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    btn_label, 'click_btn',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    confirm_ref = pending_ref
            steps.append({
                'desc': f"确认删除 - 点击「{btn_label}」",
                'keyword': 'click_element',
                'params': {'locator': confirm_ref},
            })

        elif ptype == 'check_first':
            # 解析行号和描述
            row_num_str = args[0] if args else '一'  # 中文数字或阿拉伯数字
            item_desc = args[1] if len(args) > 1 and args[1] else ''

            # 中文数字转阿拉伯数字
            _cn_to_num = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                          '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
            if row_num_str.isdigit():
                row_idx = int(row_num_str)
            else:
                row_idx = _cn_to_num.get(row_num_str, 1)

            # 生成完整描述
            full_desc = f"勾选第{row_num_str}个{item_desc}" if item_desc else f"勾选第{row_num_str}个"

            _chk_xpath = _get_first_kb_pattern('checkbox', None, 'checkbox')
            if _chk_xpath:
                # 动态替换行号: tr[1] → tr[N]
                _chk_xpath = re.sub(r'tr\[1\]', f'tr[{row_idx}]', _chk_xpath)
                _chk_xpath = _inject_hidden_filter(_chk_xpath)
                steps.append({
                    'desc': full_desc,
                    'keyword': 'click_element',
                    'params': {'locator': f'xpath={_chk_xpath}'},
                })
            else:
                pending_ref, _ = self.resolver.make_pending_ref(
                    '复选框', 'checkbox',
                    container_type=self.current_container,
                    module_slug=self.module)
                steps.append({
                    'desc': f"{full_desc} [待确认]",
                    'keyword': 'click_element',
                    'params': {'locator': pending_ref or 'xpath=[待确认]'},
                })

        elif ptype == 'click_more_then':
            action = args[0].strip()
            groups = self._compat_groups()
            more_ref = _find_table_action(groups, '更多') or \
                self.find_button('更多', preferred_container=self.current_container)
            if more_ref:
                steps.append({
                    'desc': "点击更多按钮",
                    'keyword': 'click_element',
                    'params': {'locator': more_ref},
                })
                steps.append({
                    'desc': "等待下拉菜单",
                    'keyword': 'wait_for_time',
                    'params': {'timeout': 1000},
                })
                option_ref = f"xpath=//*[(@x-placement='top-end' or @x-placement='bottom-end')]//*[contains(text(),'{action}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]"
                steps.append({
                    'desc': f'选择「{action}」',
                    'keyword': 'click_element',
                    'params': {'locator': option_ref},
                })
            else:
                steps.append({
                    'desc': "[待确认] 点击更多按钮",
                    'keyword': 'click_element',
                    'params': {'locator': "xpath=(//*[contains(text(),'更多')]"
                               "[not(ancestor::*[contains(@class,'el-select-dropdown')])]"
                               "[ancestor::tbody])[1]"},
                })
                steps.append({
                    'desc': "等待下拉菜单",
                    'keyword': 'wait_for_time',
                    'params': {'timeout': 1000},
                })
                option_ref = (f"xpath=//*[(@x-placement='top-end' or @x-placement='bottom-end')]"
                              f"//*[contains(text(),'{action}')"
                              f" and not(ancestor::*[contains(@class,'is-hidden')])"
                              f" and not(ancestor::*[contains(@style,'display: none')])]")
                steps.append({
                    'desc': f'[待确认] 选择「{action}」',
                    'keyword': 'click_element',
                    'params': {'locator': option_ref},
                })

        elif ptype == 'click_more_then_click':
            action = args[0].strip()
            groups = self._compat_groups()
            more_ref = _find_table_action(groups, '更多') or \
                self.find_button('更多', preferred_container=self.current_container)
            if more_ref:
                steps.append({
                    'desc': "点击第一条记录的更多按钮",
                    'keyword': 'click_element',
                    'params': {'locator': more_ref},
                })
                steps.append({
                    'desc': "等待下拉菜单展开",
                    'keyword': 'wait_for_time',
                    'params': {'timeout': 1000},
                })
                option_ref = f"xpath=//*[(@x-placement='top-end' or @x-placement='bottom-end')]//*[contains(text(),'{action}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]"
                steps.append({
                    'desc': f'点击「{action}」',
                    'keyword': 'click_element',
                    'params': {'locator': option_ref},
                })
            else:
                pending_ref, _ = self.resolver.make_pending_ref(
                    '更多', 'table_action',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    steps.append({
                        'desc': "[待确认] 点击第一条记录的更多按钮",
                        'keyword': 'click_element',
                        'params': {'locator': pending_ref},
                    })
                else:
                    steps.append({
                        'desc': "[待确认] 点击更多按钮",
                        'keyword': 'click_element',
                        'params': {'locator': "xpath=(//*[contains(text(),'更多')]"
                                   "[not(ancestor::*[contains(@class,'el-select-dropdown')])]"
                                   "[ancestor::tbody])[1]"},
                    })
                steps.append({
                    'desc': "等待下拉菜单展开",
                    'keyword': 'wait_for_time',
                    'params': {'timeout': 1000},
                })
                option_ref = (f"xpath=//*[(@x-placement='top-end' or @x-placement='bottom-end')]"
                              f"//*[contains(text(),'{action}')"
                              f" and not(ancestor::*[contains(@class,'is-hidden')])"
                              f" and not(ancestor::*[contains(@style,'display: none')])]")
                steps.append({
                    'desc': f'点击「{action}」',
                    'keyword': 'click_element',
                    'params': {'locator': option_ref},
                })

        elif ptype == 'click_detail_link':
            text = args[0] if args else ''

            # Fix-4 修正: 当有数据值时，始终构建精确 locator（不依赖 pages YAML 的通用 first_desc_link）
            # 原因: pages YAML 的 first_desc_link 可能包含探测时的占位文本（如 xxxxxxxxxx）
            if text:
                safe_text = text.replace("'", '').replace('"', '').replace('‘', '').replace('’', '')
                # 手动注入隐藏过滤：此 locator 已含完整 hidden filter 签名，
                # 下游 _pages_writer 的 inject_hidden_filter 会通过 has_hidden_filter 幂等检查跳过。
                # 不要移除此手动注入，否则 _pages_writer 会在错误位置（//td 而非 //*）注入。
                detail_locator = (
                    f"xpath=//td[not(contains(@class,'is-hidden'))]"
                    f"//*[contains(text(),'{safe_text}')"
                    f" and not(ancestor::*[contains(@class,'is-hidden')])"
                    f" and not(ancestor::*[contains(@style,'display: none')])]"
                )
                # 使用唯一 field key 避免多 case 冲突
                case_suffix = self.current_case_prefix.replace('case', '').rstrip('_') or '00'
                group_name = self._get_table_group_name()
                field_key = f"detail_link_{case_suffix}"
                self._track_field(group_name, field_key,
                                  locator=detail_locator,
                                  label=text,
                                  comment='Fix-4: detail-link 数据值构建')
                link_ref = f"${{{group_name}.{field_key}}}"
            else:
                # 无数据值时回退到 pages YAML 查找
                groups = self._compat_groups()
                link_ref = _find_detail_link(groups, preferred_container=self.current_container,
                                             module_slug=self.module)
                if not link_ref:
                    link_ref = self.find_button(text, preferred_container=self.current_container)
                if not link_ref:
                    group_name = self._get_table_group_name()
                    field_key = 'first_desc_link'
                    self._track_field(group_name, field_key,
                                      label=text,
                                      comment='detail-link pending')
                    link_ref = f"${{{group_name}.{field_key}}}"
                    self.pending_detail_links.append({
                        'group': group_name,
                        'field': field_key,
                        'label': text,
                        'type': 'detail-link',
                        'case_id': self.current_case_prefix,
                    })

            steps.append({
                'desc': f"点击第一条记录的「{text}」",
                'keyword': 'click_element',
                'params': {'locator': link_ref},
            })

            # R6 Defense 3: 输出后校验 — 重写跨模块引用
            if link_ref and self.module:
                _r6_prefix = self.module.replace('-', '_')
                _r6_m = re.match(r'^\$\{([^}.]+)\.', link_ref)
                if _r6_m:
                    _r6_group = _r6_m.group(1)
                    if (_r6_group != 'common_elements'
                            and not _r6_group.startswith('common_')
                            and not _r6_group.startswith(_r6_prefix)):
                        _r6_new_group = f"{_r6_prefix}_elements"
                        _r6_new_ref = link_ref.replace(
                            f"${{{_r6_group}.", f"${{{_r6_new_group}.")
                        steps[-1]['params']['locator'] = _r6_new_ref
                        link_ref = _r6_new_ref
                        print(f"    [WARN R6] detail-link 跨模块引用重写: "
                              f"{_r6_group} → {_r6_new_group}")

        elif ptype == 'wait_element':
            desc = args[0].strip() if args else ''
            steps.append({
                'desc': f"等待{desc}",
                'keyword': 'wait_for_time',
                'params': {'timeout': 3000},
            })

        elif ptype == 'conditional_click_btn':
            section, label = args[0], args[1]
            check_xpath = _get_assertion_kb_pattern('first-row-content', keyword=section)
            if not check_xpath:
                check_xpath = f"//tbody/tr[1]//*[contains(.,'{section}')]"
            check_xpath = _inject_hidden_filter(check_xpath)

            btn_ref = self.find_button(label, preferred_container=self.current_container)
            if not btn_ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'click_btn',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    btn_ref = pending_ref

            steps.append({
                'desc': f"如果「{section}」有数据则点击「{label}」按钮",
                'keyword': 'if_element_visible',
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element',
                         'params': {'locator': btn_ref}},
                    ],
                },
            })

        elif ptype == 'conditional_click_tab':
            section, tab_label = args[0], args[1]
            check_xpath = _get_assertion_kb_pattern('first-row-content', keyword=section)
            if not check_xpath:
                check_xpath = f"//tbody/tr[1]//*[contains(.,'{section}')]"
            check_xpath = _inject_hidden_filter(check_xpath)

            tab_ref = self._find_tab_element(tab_label)
            steps.append({
                'desc': f"如果「{section}」有数据则点击「{tab_label}」tab",
                'keyword': 'if_element_visible',
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element',
                         'params': {'locator': tab_ref}},
                    ],
                },
            })

        elif ptype == 'conditional_click_row':
            section = args[0] if args else ''
            check_xpath = _get_assertion_kb_pattern('first-row-content', keyword=section)
            if not check_xpath:
                check_xpath = f"//tbody/tr[1]//*[contains(.,'{section}')]"
            check_xpath = _inject_hidden_filter(check_xpath)

            groups = self._compat_groups()
            click_ref = _find_detail_link(groups, section)
            if not click_ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    section, 'detail_link',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    click_ref = pending_ref

            steps.append({
                'desc': f"如果「{section}」有数据则点击第一条记录",
                'keyword': 'if_element_visible',
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element',
                         'params': {'locator': click_ref}},
                    ],
                },
            })

        elif ptype == 'conditional_click':
            section = args[0] if args else ''
            check_xpath = _get_assertion_kb_pattern('first-row-content', keyword=section)
            if not check_xpath:
                check_xpath = f"//tbody/tr[1]//*[contains(.,'{section}')]"
            check_xpath = _inject_hidden_filter(check_xpath)

            then_xpath = f"//*[contains(text(),'{section}')]"
            then_xpath = _inject_hidden_filter(then_xpath)
            steps.append({
                'desc': f"如果「{section}」有数据则点击",
                'keyword': 'if_element_visible',
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element',
                         'params': {'locator': f"xpath={then_xpath}"}},
                    ],
                },
            })

        elif ptype == 'check_assert':
            actual = args[0].strip() if args else ''
            expected = args[1].strip() if len(args) > 1 else ''

            field_label = self._extract_quoted_text(actual)
            check_value = self._extract_quoted_text(expected) if expected else ''

            if field_label and check_value:
                kb_xpath = _get_assertion_kb_pattern(
                    'field-value', field_label=field_label, keyword=check_value)
                if not kb_xpath:
                    kb_xpath = (f"//*[contains(text(),'{field_label}')]"
                                f"/following-sibling::*[self::div or self::span]"
                                f"//*[contains(.,'{check_value}')]")
            else:
                kb_xpath = f"//*[contains(.,'{actual}')]"

            kb_xpath = _inject_hidden_filter(kb_xpath)
            steps.append({
                'desc': f"检查{actual}与{expected}一致",
                'keyword': 'except_to_be_visible',
                'params': {
                    'locator': f"xpath={kb_xpath}"
                },
            })

        elif ptype == 'click_table_row_btn':
            label = args[0]
            groups = self._compat_groups()
            ref = self.find_button(label, preferred_container=self.current_container, prefer_row=True) or _find_table_action(groups, label)
            if ref:
                steps.append({
                    'desc': f'点击第一条记录的「{label}」按钮',
                    'keyword': 'click_element',
                    'params': {'locator': ref},
                })
            else:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'table_action',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    steps.append({
                        'desc': f'[待确认] 点击第一条记录的「{label}」按钮',
                        'keyword': 'click_element',
                        'params': {'locator': pending_ref},
                    })
                else:
                    steps.append({
                        'desc': f'[待确认] 点击记录中的「{label}」按钮',
                        'keyword': 'log',
                        'params': {'message': f"[PENDING-NO-GROUP] 未找到'{label}'按钮定位器"},
                    })

        elif ptype == 'click_first_in_list':
            label = args[0]
            ref = self.find_button(label, preferred_container=self.current_container)
            if not ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'click_btn',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    ref = pending_ref
            steps.append({
                'desc': f'点击第一个「{label}」按钮',
                'keyword': 'click_element',
                'params': {'locator': ref},
            })

        elif ptype == 'dialog_date_select':
            context = args[0].strip() if args else ''
            value = args[1].strip() if len(args) > 1 else ''

            dialog_scope = ''
            if context:
                groups = self._compat_groups()
                for group_name, fields in groups.items():
                    if context in group_name and ('dialog' in group_name or 'drawer' in group_name):
                        container_cls = 'el-drawer' if 'drawer' in group_name else 'el-dialog'
                        dialog_scope = f"//div[contains(@class,'{container_cls}') and .//*[contains(text(),'{context}')]]"
                        break

            raw_text = parsed.get('raw', '')
            field_label = ''
            m_label = re.search(r'[,，]\s*(.+?)选择', raw_text)
            if m_label:
                field_label = m_label.group(1).strip()

            input_ref = None
            _ds2_field_info = None
            if field_label:
                input_ref, _ds2_field_info = self.find_input(field_label, preferred_container=self.current_container)
            if not input_ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    field_label or '日期', 'date_select',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    input_ref = pending_ref

            # Plan A: date_select 容器前缀注入（第二路径）
            if (input_ref and _ds2_field_info
                    and self.current_container
                    and self.current_container not in ('new_page', None)):
                _ds2_group = _ds2_field_info.get('group')
                _ds2_field = _ds2_field_info.get('field_prefix', '')
                if _ds2_group and _ds2_field and field_label:
                    _ds2_elem = self._discovery_lookup(field_label)
                    if _ds2_elem:
                        _ds2_raw = _ds2_elem.get('locator', '')
                        if _ds2_raw.startswith('xpath='):
                            _ds2_pfx = self._add_container_prefix_to_xpath(_ds2_raw[6:])
                            if _ds2_pfx != _ds2_raw[6:]:
                                self._track_field(_ds2_group, f'{_ds2_field}_input',
                                                  locator=f'xpath={_ds2_pfx}',
                                                  label=field_label,
                                                  comment='Plan A: date_select-2 容器前缀')

            if input_ref:
                steps.append({
                    'desc': f"点击「{field_label or '日期'}」选择框",
                    'keyword': 'click_element',
                    'params': {'locator': input_ref},
                })

            picker_xpath, picker_desc = _build_date_picker_xpath(value, scope_prefix=dialog_scope)
            picker_xpath = _inject_hidden_filter(picker_xpath)
            steps.append({
                'desc': picker_desc,
                'keyword': 'click_element',
                'params': {'locator': f"xpath={picker_xpath}"},
            })

        elif ptype == 'click_section':
            section = args[0].strip() if args else ''
            ref = self._find_section_row_link(section)
            if not ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    section, 'row_link',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    ref = pending_ref
            steps.append({
                'desc': f"点击「{section}」区域",
                'keyword': 'click_element',
                'params': {'locator': ref},
            })

        elif ptype == 'click_navigate':
            label = args[0]
            ref = self.find_button(label, preferred_container=self.current_container)
            if not ref:
                pending_ref, _ = self.resolver.make_pending_ref(
                    label, 'click_btn',
                    container_type=self.current_container,
                    module_slug=self.module)
                if pending_ref:
                    ref = pending_ref
            steps.append({
                'desc': f'点击「{label}」跳转',
                'keyword': 'click_element',
                'params': {'locator': ref},
            })

        elif ptype == 'close_btn':
            label = args[0] if args else None

            if label:
                # 有标签：生成带标签的 XPath（KB 模板 pattern[0] + 隐藏过滤）
                xpath = (
                    f"//*[contains(text(),'{label}')]//following-sibling::i"
                    f"[contains(@class,'el-icon-close')"
                    f" and not(ancestor::*[contains(@class,'is-hidden')])"
                    f" and not(ancestor::*[contains(@style,'display: none')])]"
                )
                steps.append({
                    'desc': f'点击「{label}」的关闭按钮',
                    'keyword': 'click_element',
                    'params': {'locator': f'xpath={xpath}'},
                })
            else:
                # 无标签：生成通用 XPath（KB 模板 pattern[1] + 隐藏过滤）
                xpath = (
                    "//i[contains(@class,'el-icon-close')"
                    " and not(ancestor::*[contains(@class,'is-hidden')])"
                    " and not(ancestor::*[contains(@style,'display: none')])]"
                )
                steps.append({
                    'desc': '点击关闭按钮',
                    'keyword': 'click_element',
                    'params': {'locator': f'xpath={xpath}'},
                })

        elif ptype == 'l3_call':
            cn_name = args[0]
            raw_params = args[1] or '' if len(args) > 1 else ''

            wf_def = self._find_workflow(cn_name)

            if not wf_def:
                if cn_name == '随机名称':
                    steps.append({
                        'desc': f"[待确认] {parsed['raw']}",
                        'keyword': 'log',
                        'params': {'message': (
                            "'随机名称(前缀)' 是值表达式，必须在输入框上下文中使用，"
                            "如: 在\"XX\"输入框中输入随机名称(前缀)")},
                    })
                    return steps

                raw_text = parsed.get('raw', '').strip()
                reparsed = None
                for pattern, action_type, group_names in STEP_PATTERNS:
                    if action_type == 'l3_call':
                        continue
                    m = pattern.search(raw_text)
                    if m:
                        reparsed = {
                            'type': action_type,
                            'args': m.groups(),
                            'raw': raw_text,
                        }
                        break

                if reparsed:
                    return self.generate_step(reparsed)
                else:
                    steps.append({
                        'desc': f"[待确认] {parsed['raw']}",
                        'keyword': 'log',
                        'params': {'message': f"'{cn_name}' 不是已注册的 L3 关键字且无法回退解析"},
                    })
            else:
                param_names = wf_def.get('params', [])
                param_values = [v.strip() for v in re.split(r'[,，]', raw_params)] if raw_params else []

                if len(param_values) < len(param_names):
                    steps.append({
                        'desc': f"[参数缺失] {cn_name} 需要 {len(param_names)} 个参数: {', '.join(param_names)}",
                        'keyword': 'log',
                        'params': {'message': f"L3 关键字 '{cn_name}' 参数不足，需要: {', '.join(param_names)}"},
                    })
                else:
                    params = dict(zip(param_names, param_values))
                    steps.append({
                        'desc': f"执行{cn_name}",
                        'keyword': wf_def['name'],
                        'params': params,
                    })

        else:
            steps.append({
                'desc': f"[待确认] {parsed['raw']}",
                'keyword': 'log',
                'params': {'message': f"无法解析步骤: {parsed['raw']}"},
            })

        return steps

    def generate_preamble(self, url):
        """生成用例开头的标准三步"""
        url_ref = self.add_data('page_url', url)
        steps = [
            {
                'desc': '访问页面',
                'keyword': 'open_url',
                'params': {'url': url_ref},
            },
            {
                'desc': '刷新页面确保环境干净',
                'keyword': 'refresh',
            },
            {
                'desc': '等待加载完成',
                'keyword': 'wait_for_loading_complete',
                'params': {},
            },
        ]
        return steps


# ═══════════════════════════════════════════════════════════════
# L3 触发模式加载
# ═══════════════════════════════════════════════════════════════

def _load_l3_trigger_patterns(project_dir):
    """从 _knowledge/*.yaml 动态加载 L3 触发模式。"""
    patterns = []
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if not os.path.isdir(knowledge_dir):
        return patterns

    mk_path = os.path.join(project_dir, 'lib', 'module_keywords.py')
    if not os.path.isfile(mk_path):
        has_workflows = False
        for f in glob.glob(os.path.join(knowledge_dir, "*.yaml")):
            try:
                data = yaml.safe_load(open(f, encoding='utf-8'))
                if data and data.get('workflows'):
                    has_workflows = True
                    break
            except Exception as _e:
                print(f"  [WARN] knowledge YAML 解析失败: {f}: {_e}")
                continue
        if has_workflows:
            print(f"[WARN] _knowledge/ 有 workflows 但 lib/module_keywords.py 不存在",
                  file=sys.stderr)
            print(f"  L3 关键字已禁用。请先运行: python compile_module_keywords.py {project_dir}",
                  file=sys.stderr)
        return patterns

    for f in glob.glob(os.path.join(knowledge_dir, "*.yaml")):
        try:
            data = yaml.safe_load(open(f, encoding='utf-8'))
        except Exception as _e:
            print(f"  [WARN] knowledge YAML 加载失败: {f}: {_e}")
            continue
        if not data or not isinstance(data, dict):
            continue

        raw_wfs = data.get('workflows')
        if raw_wfs is None:
            continue

        wf_list = []
        if isinstance(raw_wfs, list):
            wf_list = [wf for wf in raw_wfs if isinstance(wf, dict)]
        elif isinstance(raw_wfs, dict):
            wf_list = [{'name': k, **v} if isinstance(v, dict) else v
                       for k, v in raw_wfs.items()]

        for wf in wf_list:
            name = wf.get('name', '')
            trigger = wf.get('trigger_pattern', [])
            if not name or not trigger:
                continue

            compiled = []
            for pat in trigger:
                try:
                    compiled.append(re.compile(pat))
                except re.error:
                    compiled = []
                    break

            if compiled:
                patterns.append((name, compiled, len(compiled)))

    return patterns


def _load_l3_keyword_names(project_dir):
    """从 lib/module_keywords.py 提取已注册的 L3 关键字名称集合。"""
    mk_path = os.path.join(project_dir, 'lib', 'module_keywords.py')
    if not os.path.isfile(mk_path):
        return set()

    names = set()
    _DEF_RE = re.compile(r'^\s*def\s+(\w+)\s*\(')
    try:
        with open(mk_path, encoding='utf-8') as f:
            for line in f:
                m = _DEF_RE.match(line)
                if m:
                    name = m.group(1)
                    if not name.startswith('_') and name not in (
                        'register', 'setup', 'teardown', 'perform',
                    ):
                        names.add(name)
    except Exception:
        pass
    return names


# ═══════════════════════════════════════════════════════════════
# SelfCheckLayer
# ═══════════════════════════════════════════════════════════════

_SC_ENGINE_KEYWORDS = {
    'open_url', 'refresh', 'go_back', 'go_forward', 'execute_script',
    'scroll_to_height', 'scroll_to_element', 'open_browser',
    'download_file', 'save_page_img', 'set_viewport_size', 'set_cookie',
    'click_element', 'fill_value', 'type_text', 'hover', 'clear',
    'double_click', 'long_click', 'right_click', 'drag_and_drop',
    'check', 'uncheck', 'set_checked', 'select_option', 'upload_file',
    'click_select_option', 'select_multiple_options',
    'focus_element', 'highlight_element',
    'get_text', 'get_attribute', 'get_input_value', 'get_element_count',
    'is_visible', 'is_hidden', 'is_enabled', 'is_disabled', 'is_checked',
    'frame_fill_value', 'frame_click_element', 'frame_hover',
    'frame_except_to_be_visible', 'frame_except_to_be_hidden',
    'switch_to_frame', 'switch_to_main_frame',
    'except_to_be_visible', 'except_to_be_hidden', 'except_to_be_enabled',
    'except_to_be_disabled', 'except_to_be_checked', 'except_to_be_empty',
    'except_to_be_editable', 'except_to_be_focused',
    'except_to_have_text', 'except_to_have_value', 'except_to_have_attribute',
    'assert_page_title', 'assert_page_url',
    'wait_for_time', 'wait_for_element', 'wait_for_element_hidden',
    'wait_for_load', 'wait_for_network', 'wait_for_url', 'set_default_timeout',
    'set_variable', 'set_variable_from_element', 'if_element_visible',
    'if_variable', 'for_each', 'retry_until', 'goto_step', 'log',
    'inject_cookies', 'inject_token_header', 'inject_local_storage',
    'accept_dialog', 'dismiss_dialog', 'get_page_title', 'get_page_url',
    'frame_focus_element', 'frame_select_option', 'frame_type_value',
    'frame_long_click_element', 'frame_drag_and_drop',
    'mouse_click', 'move_mouse', 'mouse_down', 'mouse_up',
    'press_key', 'press_type',
    'set_random_variable', 'except_element_count',
}

_SC_KEYWORD_MISTAKES = {
    'assert_text': 'except_to_have_text',
    'assert_visible': 'except_to_be_visible',
    'assert_not_visible': 'except_to_be_hidden',
    'assert_contains': 'except_to_have_text',
    'verify_text': 'except_to_have_text',
    'check_element': 'except_to_be_visible',
    'click_text': 'click_element',
}

_SC_FORBIDDEN_PARAMS = {
    'except_to_be_visible': {'timeout', 'expect_results'},
    'except_to_be_hidden': {'timeout', 'expect_results'},
    'except_to_be_enabled': {'timeout', 'expect_results'},
    'except_to_be_disabled': {'timeout', 'expect_results'},
    'except_to_be_checked': {'timeout', 'expect_results'},
    'except_to_be_empty': {'timeout', 'expect_results'},
    'except_to_be_editable': {'timeout', 'expect_results'},
    'except_to_be_focused': {'timeout', 'expect_results'},
    'except_to_have_text': {'timeout'},
    'except_to_have_value': {'timeout'},
    'except_to_have_attribute': {'timeout'},
    'assert_page_title': {'timeout'},
    'assert_page_url': {'timeout'},
    'if_element_visible': {'then', 'else'},
    'if_variable': {'then', 'else'},
    'for_each': {'then_steps', 'then', 'else_steps', 'else'},
    'get_element_count': {'timeout'},
    'is_visible': {'timeout'},
    'is_hidden': {'timeout'},
}

_SC_WRONG_PARAM_MAP = {
    'expected': 'expect_results',
    'text': 'expect_results',
    'selector': 'locator',
    'wait_time': 'timeout',
    'time': 'timeout',
    'ms': 'timeout',
    'duration': 'timeout',
    'input': 'value',
    'code': 'script',
    'js': 'script',
    'iframe': 'frame',
    'variable': 'name',
    'condition': 'operator',
    'attribute': 'name',
    'then': 'then_steps',
    'else': 'else_steps',
}

_SC_FORBIDDEN_ASSERT_KW = {'except_to_have_text', 'except_to_have_value', 'except_to_have_attribute'}
_SC_VAR_REF_RE = re.compile(r'\$\{([^}]+)\}')
_SC_EXEMPT_VALUES = {'成功', '失败', '确定', '取消', '是', '否', ''}


class SelfCheckLayer:
    """生成后自检层 — 在 case YAML 写入磁盘前执行"""

    def __init__(self, resolver, data_entries, data_group_name,
                 l3_keywords=None, module_name=''):
        self.resolver = resolver
        self.data_entries = data_entries
        self.data_group_name = data_group_name
        self.l3_keywords = l3_keywords or set()
        self.module_name = module_name
        self.repair_log = []
        self.remaining = []

    def run_all_checks(self, steps, case_id=''):
        steps = self._safe_repair(steps, self._repair_keywords, 'R4.13')
        steps = self._safe_repair(steps, self._repair_params, 'R4.14')
        steps = self._safe_repair(steps, self._repair_locator_format, 'R4.21')
        steps = self._safe_repair(steps, self._repair_forbidden_kw, 'R4.22')
        steps = self._safe_repair(steps, self._repair_env_isolation, 'R4.9')
        steps = self._safe_repair(steps, self._repair_var_format, 'R4.6')
        steps = self._safe_repair(steps, self._repair_hardcoded_values, 'R4.2')
        self.remaining = self._verify_all(steps, case_id)
        return steps, self.repair_log, self.remaining

    def _safe_repair(self, steps, repair_fn, rule_id):
        original = copy.deepcopy(steps)
        try:
            repaired = repair_fn(copy.deepcopy(steps))
            new_issues = self._verify_rule(repaired, rule_id)
            if len(new_issues) > len(self._verify_rule(original, rule_id)):
                self.repair_log.append({
                    'rule': rule_id, 'action': 'rollback',
                    'reason': f'修复后新增 {len(new_issues)} 个同规则问题',
                })
                return original
            return repaired
        except Exception as e:
            self.repair_log.append({
                'rule': rule_id, 'action': 'rollback',
                'reason': f'修复异常: {e}',
            })
            return original

    def _repair_keywords(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            if kw in _SC_KEYWORD_MISTAKES:
                old_kw = kw
                step['keyword'] = _SC_KEYWORD_MISTAKES[kw]
                self.repair_log.append({
                    'rule': 'R4.13',
                    'action': f'rename {old_kw} → {step["keyword"]}',
                    'guarantee': 'COMMON_KEYWORD_MISTAKES 静态映射',
                })
        return steps

    def _repair_params(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue

            for forbidden in _SC_FORBIDDEN_PARAMS.get(kw, set()):
                if forbidden in params:
                    del params[forbidden]
                    self.repair_log.append({
                        'rule': 'R4.14', 'action': f'delete forbidden: {forbidden}',
                        'guarantee': 'FORBIDDEN_PARAMS 静态表',
                    })

            for wrong, correct in _SC_WRONG_PARAM_MAP.items():
                if wrong in params:
                    params[correct] = params.pop(wrong)
                    self.repair_log.append({
                        'rule': 'R4.14', 'action': f'rename param {wrong} → {correct}',
                        'guarantee': 'WRONG_PARAM_MAP 静态映射',
                    })
        return steps

    def _repair_locator_format(self, steps):
        _CSS_PATTERNS = [
            (re.compile(r'^css=\.([a-zA-Z_-]+)'),
             lambda m: f"xpath=//*[contains(@class,'{m.group(1)}')]"),
            (re.compile(r'^css=#([a-zA-Z_-]+)'),
             lambda m: f"xpath=//*[@id='{m.group(1)}']"),
            (re.compile(r'^css=button:has-text\((.+?)\)'),
             lambda m: f"xpath=//button[contains(.,'{m.group(1)}')]"),
            (re.compile(r'^css=input\[placeholder=[\"\'](.+?)[\"\']\]'),
             lambda m: f"xpath=//input[@placeholder='{m.group(1)}']"),
        ]

        for step in steps:
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            locator = params.get('locator', '')
            if not isinstance(locator, str):
                continue

            if locator.startswith('css='):
                for pattern, replacer in _CSS_PATTERNS:
                    m = pattern.match(locator)
                    if m:
                        new_loc = replacer(m)
                        params['locator'] = new_loc
                        self.repair_log.append({
                            'rule': 'R4.21',
                            'action': f'CSS→XPath: {locator} → {new_loc}',
                            'guarantee': '常见 CSS 模式有确定 XPath 映射',
                        })
                        break
        return steps

    def _repair_forbidden_kw(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            if kw in _SC_FORBIDDEN_ASSERT_KW:
                params = step.get('params', {})
                if not isinstance(params, dict):
                    continue
                text = params.get('expect_results', '')
                if text and isinstance(text, str) and not text.startswith('${'):
                    new_locator = (
                        f"xpath=//*[contains(.,'{text}') and "
                        f"not(ancestor::*[contains(@style,'display:none') or "
                        f"contains(@style,'display: none')])]"
                    )
                    step['keyword'] = 'except_to_be_visible'
                    step['params'] = {'locator': new_locator}
                    self.repair_log.append({
                        'rule': 'R4.22',
                        'action': f'{kw} → except_to_be_visible + text locator',
                        'guarantee': '语义等价替换',
                    })
        return steps

    def _repair_env_isolation(self, steps):
        ISOLATION_KW = {'open_url', 'refresh', 'wait_for_element_hidden'}
        first_keywords = set()
        for s in steps[:5]:
            if isinstance(s, dict):
                first_keywords.add(s.get('keyword', ''))

        if ISOLATION_KW.issubset(first_keywords):
            return steps

        preamble = [
            {'desc': '导航到目标页', 'keyword': 'open_url',
             'params': {'url': '${common_data.target_url}'}},
            {'desc': '刷新页面', 'keyword': 'refresh'},
            {'desc': '等待加载完成', 'keyword': 'wait_for_loading_complete', 'params': {}},
        ]
        for p_step in reversed(preamble):
            if p_step['keyword'] not in first_keywords:
                steps.insert(0, p_step)
                first_keywords.add(p_step['keyword'])
                self.repair_log.append({
                    'rule': 'R4.9',
                    'action': f'insert {p_step["keyword"]}',
                    'guarantee': '标准环境隔离模板',
                })
        return steps

    def _repair_var_format(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            for key in ('locator', 'value', 'expect_results'):
                val = params.get(key, '')
                if not isinstance(val, str):
                    continue
                for m in _SC_VAR_REF_RE.finditer(val):
                    ref = m.group(1)
                    if '.' not in ref:
                        group = self._find_group_for_field(ref)
                        if group:
                            new_ref = f"{group}.{ref}"
                            val = val.replace(f"${{{ref}}}", f"${{{new_ref}}}")
                            params[key] = val
                            self.repair_log.append({
                                'rule': 'R4.6',
                                'action': f'add group: ${{{ref}}} → ${{{new_ref}}}',
                                'guarantee': 'ElementResolver 精确查找',
                            })
        return steps

    def _repair_hardcoded_values(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue

            if kw in ('fill_value', 'frame_fill_value'):
                value = str(params.get('value', ''))
                if (value and not value.startswith('${')
                        and value not in _SC_EXEMPT_VALUES
                        and any('一' <= c <= '鿿' for c in value)
                        and len(value) > 1):
                    field_name = self._generate_data_field_name(value)
                    var_ref = f"${{{self.data_group_name}.{field_name}}}"
                    grp = self.data_entries.setdefault(self.data_group_name, {})
                    grp[field_name] = value
                    params['value'] = var_ref
                    self.repair_log.append({
                        'rule': 'R4.2',
                        'action': f'extract "{value}" → {var_ref}',
                        'guarantee': '值已存入 data_entries',
                    })
        return steps

    def _find_group_for_field(self, field_name):
        """在 resolver groups 中查找字段所属的 group"""
        if not self.resolver:
            return None
        matches = []
        for gname, field_map in self.resolver.get_groups().items():
            if field_name in field_map:
                matches.append(gname)
        if len(matches) == 1:
            return matches[0]
        if self.module_name:
            prefix = self.module_name.replace('-', '_')
            for g in matches:
                if g.replace('-', '_').startswith(prefix):
                    return g
        return matches[0] if matches else None

    def _generate_data_field_name(self, value):
        slug = re.sub(r'[^a-z0-9]', '_', value.lower()).strip('_')
        if slug and len(slug) < 30:
            return slug
        existing = self.data_entries.get(self.data_group_name, {})
        idx = len(existing) + 1
        return f'field_{idx}'

    def _verify_all(self, steps, case_id=''):
        issues = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue

            if (kw and kw not in _SC_ENGINE_KEYWORDS
                    and kw not in self.l3_keywords):
                issues.append({'rule': 'R4.13', 'step': i, 'kw': kw,
                               'reason': '关键字不在注册表'})

            for p in _SC_FORBIDDEN_PARAMS.get(kw, set()):
                if p in params:
                    issues.append({'rule': 'R4.14', 'step': i, 'param': p,
                                   'reason': '仍存在禁止参数'})

            locator = str(params.get('locator', ''))
            if locator.startswith('css='):
                issues.append({'rule': 'R4.21', 'step': i, 'locator': locator,
                               'reason': 'CSS 选择器无法转换为 XPath'})

            if kw in _SC_FORBIDDEN_ASSERT_KW:
                issues.append({'rule': 'R4.22', 'step': i, 'kw': kw,
                               'reason': '仍使用禁止断言'})

            for param_key in ('locator', 'value', 'expect_results'):
                val = params.get(param_key, '')
                if not isinstance(val, str):
                    continue
                for m_ref in _SC_VAR_REF_RE.finditer(val):
                    ref = m_ref.group(1)
                    if '.' not in ref:
                        issues.append({'rule': 'R4.6', 'step': i, 'ref': ref,
                                       'reason': '变量缺少 group 前缀'})

        # M9: 4 项盲区检查（只检测不修复，作为 warning 报告）

        # M9-1: R4.41 变量引用有效性 — ${group.field} 是否在 resolver/required_fields 中存在
        all_groups = self.resolver.get_groups() if self.resolver else {}
        required_keys = set()
        if hasattr(self, '_required_fields_ref'):
            required_keys = self._required_fields_ref
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            for param_key in ('locator', 'value'):
                val = str(params.get(param_key, ''))
                for m_ref in _SC_VAR_REF_RE.finditer(val):
                    ref = m_ref.group(1)
                    if '.' in ref:
                        gname, fkey = ref.split('.', 1)
                        if gname in all_groups and fkey not in all_groups[gname]:
                            if ref not in required_keys:
                                issues.append({'rule': 'R4.41', 'step': i,
                                               'ref': ref,
                                               'reason': f'变量引用 {ref} 在 resolver 中不存在'})

        # M9-2: R4.42 XPath 基础语法检查 — 括号平衡 + ]*[ 残留
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            locator = str(params.get('locator', ''))
            if not locator:
                continue
            # 检查 ]*[ 残留（Fix-1 修复后不应出现）
            if ']*[' in locator:
                issues.append({'rule': 'R4.42', 'step': i, 'locator': locator[:80],
                               'reason': 'XPath 含 ]*[ 残留（容器前缀拼接错误）'})
            # 检查 [待确认] 占位符
            if '[待确认]' in locator:
                issues.append({'rule': 'R4.42', 'step': i, 'locator': locator[:80],
                               'reason': 'XPath 含 [待确认] 占位符'})
            # 括号平衡检查
            raw = locator.replace('xpath=', '')
            depth = 0
            for ch in raw:
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
            if depth != 0:
                issues.append({'rule': 'R4.42', 'step': i, 'locator': locator[:80],
                               'reason': f'XPath 方括号不平衡 (depth={depth})'})

        # M9-3: R4.43 companion 字段完整性 — el-select 步骤的 _select 引用
        #       是否有对应 _editable companion
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            locator = str(params.get('locator', ''))
            # 检查 if_element_visible 步骤引用的 _editable 是否存在
            if kw == 'if_element_visible' and '_editable' in locator:
                m = _SC_VAR_REF_RE.search(locator)
                if m:
                    ref = m.group(1)
                    if '.' in ref:
                        gname, fkey = ref.split('.', 1)
                        if gname in all_groups:
                            # 检查对应的 _select 是否也存在
                            select_key = fkey.replace('_editable', '_select')
                            if select_key not in all_groups.get(gname, {}):
                                issues.append({'rule': 'R4.43', 'step': i,
                                               'ref': ref,
                                               'reason': f'_editable 引用但对应 _select({select_key}) 不存在'})

        for issue in issues:
            issue['case_id'] = case_id
            issue['file'] = f'cases/{self.module_name}/{case_id}' if case_id else ''
            issue['suggestion'] = self._get_suggestion(issue)
        return issues

    def _verify_rule(self, steps, rule_id):
        return [i for i in self._verify_all(steps) if i['rule'] == rule_id]

    def _get_suggestion(self, issue):
        rule = issue.get('rule', '')
        suggestions = {
            'R4.13': '确认关键字是否在 ENGINE_KEYWORDS 或 L3 关键字中',
            'R4.14': '检查参数名是否符合关键字规范',
            'R4.21': '复杂 CSS 选择器需手动转为 XPath',
            'R4.22': 'except_to_have_text 已被全局约束禁止',
            'R4.6': '多 group 同名时无法自动确定所属 group',
            'R4.2': '硬编码值已提取但字段名可能需要人工调整',
            'R4.41': 'M9: 变量引用的 group.field 在 resolver 中不存在，检查 pages YAML 是否生成',
            'R4.42': 'M9: XPath 语法错误（括号不平衡/]*[残留/[待确认]占位符）',
            'R4.43': 'M9: _editable companion 引用但对应 _select 不存在',
        }
        return suggestions.get(rule, '')


def save_repair_log(project_dir, repair_log, remaining, module_name=''):
    """保存修复日志到 _probe/repair_log.json"""
    probe_dir = os.path.join(project_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)
    path = os.path.join(probe_dir, 'repair_log.json')

    import datetime
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    for r in repair_log + remaining:
        r.setdefault('module', module_name)
        r.setdefault('timestamp', ts)

    existing = {'repairs': [], 'remaining': []}
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            pass

    existing['repairs'].extend(repair_log)
    existing['remaining'].extend(remaining)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return path


# ═══════════════════════════════════════════════════════════════
# V3: desc 引号规范化
# ═══════════════════════════════════════════════════════════════

def _normalize_desc_quotes(desc, known_labels):
    """给 desc 中已知的字段名加中文引号「」。"""
    if not desc or not known_labels:
        return desc
    for label in sorted(known_labels, key=len, reverse=True):
        if label not in desc:
            continue
        already_quoted = False
        idx = desc.find(label)
        while idx != -1:
            for qo, qc in [('"', '"'), ('“', '”'), ('「', '」')]:
                if idx >= len(qo) and desc[idx - len(qo):idx] == qo:
                    end = idx + len(label)
                    if end < len(desc) and desc[end:end + len(qc)] == qc:
                        already_quoted = True
                        break
            if already_quoted:
                break
            idx = desc.find(label, idx + 1)
        if not already_quoted:
            desc = desc.replace(label, f'「{label}」', 1)
    return desc


def _ensure_desc_quotes(steps):
    """确保所有 [待确认] desc 中的操作目标有引号。

    Phase 6 的 label 提取依赖引号对 (verify_locators.py line 1077)。
    无引号的 desc 导致 label 为空，KB/discovery/fallback 全部跳过。
    此函数作为 generate_step 后的兜底，统一补齐引号。
    """
    for step in steps:
        if not isinstance(step, dict):
            continue
        desc = step.get('desc', '')
        if not isinstance(desc, str):
            continue

        # 递归处理子步骤
        for sub_key in ('then_steps', 'else_steps'):
            sub_steps = step.get(sub_key, [])
            if sub_steps:
                _ensure_desc_quotes(sub_steps)

        # 只处理 [待确认] 步骤
        if '[待确认]' not in desc:
            continue

        # 跳过断言步骤（Phase 6 不验证断言）
        if '断言' in desc:
            continue

        # 跳过 parsed['raw'] 透传（Phase 1 已处理引号）
        if desc.startswith('[待确认] ') and not any(
            kw in desc for kw in ('点击', '在', '选择', '日期')
        ):
            continue

        # 1. '...' -> 「...」（所有单引号对统一为中文引号）
        if "'" in desc:
            desc = re.sub(r"'([^']+?)'", r'「\1」', desc)

        # 2. [待确认] 点击第一条记录的XX按钮（比 pattern 3 更具体，必须先匹配）
        m = re.match(
            r'^(\[待确认\] 点击第一条记录的)([^「」"""\s]{2,10}?)(按钮)$', desc)
        if m:
            prefix, target, suffix = m.group(1), m.group(2), m.group(3)
            desc = f'{prefix}「{target}」{suffix}'

        # 3. [待确认] 点击XX按钮/日期选择框/tab
        if '「' not in desc:
            m = re.match(
                r'^(\[待确认\] 点击)([^「」"""\s]{2,10}?)(按钮|日期选择框|tab)$', desc)
            if m:
                prefix, target, suffix = m.group(1), m.group(2), m.group(3)
                desc = f'{prefix}「{target}」{suffix}'

        # 4. [待确认] 点击XX（无后缀）
        if '「' not in desc:
            m = re.match(r'^(\[待确认\] 点击)([^「」"""\s]{2,10})$', desc)
            if m:
                prefix, target = m.group(1), m.group(2)
                desc = f'{prefix}「{target}」'

        # 5. [待确认] 选择XX
        if '「' not in desc:
            m = re.match(r'^(\[待确认\] 选择)([^「」"""\s]{2,10})$', desc)
            if m:
                prefix, target = m.group(1), m.group(2)
                desc = f'{prefix}「{target}」'

        step['desc'] = desc


# ═══════════════════════════════════════════════════════════════
# V4: _knowledge/ 自动同步
# ═══════════════════════════════════════════════════════════════

def _sync_l3_workflows_to_project(project_dir, cases_dir):
    """扫描所有已生成 case 引用的 L3 keyword，同步 workflow 定义。"""
    if not project_dir or not cases_dir or not os.path.isdir(cases_dir):
        return

    referenced_keywords = set()
    for f in os.listdir(cases_dir):
        if not f.endswith('.yaml') or f.startswith('_'):
            continue
        try:
            with open(os.path.join(cases_dir, f), encoding='utf-8') as fh:
                case_yaml = yaml.safe_load(fh) or {}
            for step in (case_yaml.get('steps') or []):
                kw = step.get('keyword', '')
                if kw and kw not in _SC_ENGINE_KEYWORDS and kw != 'l3_call':
                    referenced_keywords.add(kw)
                if kw == 'l3_call':
                    wf_name = (step.get('params') or {}).get('workflow', '')
                    if wf_name:
                        referenced_keywords.add(wf_name)
        except Exception:
            continue

    if not referenced_keywords:
        return

    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    all_workflows = {}

    sys_path = os.path.join(skill_dir, 'lib', 'system_workflows.yaml')
    if os.path.isfile(sys_path):
        try:
            with open(sys_path, encoding='utf-8') as fh:
                data = yaml.safe_load(fh) or {}
            if isinstance(data, dict):
                for name, wf in data.items():
                    if isinstance(wf, dict) and 'steps' in wf:
                        all_workflows[name] = wf
        except Exception:
            pass

    skill_kd = os.path.join(skill_dir, 'lib', '_knowledge')
    if os.path.isdir(skill_kd):
        for f in os.listdir(skill_kd):
            if f.endswith(('.yaml', '.yml')):
                try:
                    with open(os.path.join(skill_kd, f), encoding='utf-8') as fh:
                        data = yaml.safe_load(fh) or {}
                    wf_list = data.get('workflows', [])
                    if isinstance(wf_list, list):
                        for wf in wf_list:
                            if isinstance(wf, dict) and 'name' in wf:
                                all_workflows[wf['name']] = wf
                    elif isinstance(wf_list, dict):
                        for name, wf in wf_list.items():
                            if isinstance(wf, dict) and 'steps' in wf:
                                wf.setdefault('name', name)
                                all_workflows[name] = wf
                except Exception:
                    pass

    matched = {name: all_workflows[name] for name in referenced_keywords if name in all_workflows}
    if not matched:
        return

    knowledge_dir = os.path.join(project_dir, '_knowledge')
    os.makedirs(knowledge_dir, exist_ok=True)
    output_path = os.path.join(knowledge_dir, 'auto_synced.yaml')

    # 合并已有 workflows（多模块循环时不能覆盖）
    existing = {}
    if os.path.isfile(output_path):
        try:
            with open(output_path, encoding='utf-8') as fh:
                old_data = yaml.safe_load(fh) or {}
            for wf in (old_data.get('workflows') or []):
                if isinstance(wf, dict) and 'name' in wf:
                    existing[wf['name']] = wf
        except Exception:
            pass
    existing.update(matched)  # 新模块的 workflow 覆盖同名旧条目

    output_data = {'workflows': list(existing.values())}
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(output_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"[INFO] V4: 同步 {len(matched)} 个 L3 workflow 到 {output_path}")
    for name in sorted(matched.keys()):
        print(f"  - {name}")


# ═══════════════════════════════════════════════════════════════
# 主流程函数
# ═══════════════════════════════════════════════════════════════

# 静态关键字集合（非元素操作，无需定位器）
_STATIC_KEYWORDS = frozenset({
    'open_url', 'refresh', 'go_back', 'wait_for_element_hidden',
    'wait_for_time', 'open_browser', 'close_browser', 'inject_local_storage',
    'inject_token_header', 'confirm_dialog', 'log',
})

# 引擎原子关键字集合（generate_step 产出的标准步骤类型）
_ATOMIC_KEYWORDS = frozenset({
    'click_element', 'fill_value', 'select_option',
    'wait_for_element_hidden', 'wait_for_time',
    'except_to_be_visible', 'except_element_count',
    'if_element_visible', 'click_first_if_exists',
    'open_url', 'refresh', 'go_back', 'log',
    'confirm_dialog', 'open_browser', 'close_browser',
    'inject_local_storage', 'inject_token_header',
})


def _classify_steps_for_report(all_steps, source_map, l3_keywords=None):
    """后推断法：扫描已生成的步骤，按解析来源分类。

    不改任何内部接口，仅从输出 YAML 步骤反推来源类型。

    Args:
        all_steps: 最终步骤列表（SelfCheckLayer 修复后）
        source_map: 位置映射列表（excel_step → yaml_step）

    Returns:
        (source_counts, pending_fields):
            source_counts: {source_type: count}
            pending_fields: [{desc, step_type, excel_step}]
    """
    source_counts = {
        'pending': 0, 'discovery': 0, 'l3_call': 0,
        'static': 0, 'other': 0,
    }
    pending_fields = []

    # 构建 yaml_step → excel_step 反向映射
    yaml_to_excel = {}
    for entry in source_map:
        start = entry['yaml_step_start']
        for idx in range(start, start + entry['yaml_step_count']):
            yaml_to_excel[idx] = entry['excel_step']

    for idx, step in enumerate(all_steps):
        if not isinstance(step, dict):
            source_counts['other'] += 1
            continue

        keyword = step.get('keyword', '')
        params = step.get('params', {}) or {}
        locator = str(params.get('locator', ''))
        desc = step.get('desc', '')

        # P0: pending 检测 — locator 或 desc 含待确认标记
        if '[待确认]' in locator or '[PENDING' in locator or '[待确认]' in desc:
            source_counts['pending'] += 1
            pending_fields.append({
                'desc': desc,
                'step_type': keyword,
                'excel_step': yaml_to_excel.get(idx),
            })
        # P1: 静态步骤（无定位器需求）
        elif keyword in _STATIC_KEYWORDS:
            source_counts['static'] += 1
        # P2: L3 关键字调用（已知 L3 名称 或 非引擎原子关键字）
        elif keyword == 'l3_call' or keyword.startswith('L3:'):
            source_counts['l3_call'] += 1
        elif l3_keywords and keyword in l3_keywords:
            source_counts['l3_call'] += 1
        elif keyword and keyword not in _ATOMIC_KEYWORDS:
            # 非原子关键字 → 大概率是 L3 编译关键字
            source_counts['l3_call'] += 1
        # P3: 含变量引用 — discovery 匹配或 KB 回退（替代方案不区分二者）
        elif '${' in locator:
            source_counts['discovery'] += 1
        # P4: 其他（if_element_visible、except_element_count 等无 locator 步骤）
        else:
            source_counts['other'] += 1

    return source_counts, pending_fields

def generate_case_file(case_data, generator, seq, output_dir, module='', project_dir='', l3_patterns=None):
    """为单条用例生成 YAML 文件"""
    case_name = case_data.get('case_name', f'用例{seq}')
    generator.set_case_context(seq)
    case_id = case_data.get('case_id', '') or case_name
    raw_steps = case_data.get('steps', [])

    url = None
    for step in raw_steps:
        m = re.search(r'(https?://\S+)', step)
        if m:
            url = m.group(1)
            break

    all_steps = generator.generate_preamble(url or 'http://localhost')
    generator.collect_refs_from_steps(all_steps)

    generator.set_page_context(url)

    if l3_patterns is None:
        l3_patterns = _load_l3_trigger_patterns(project_dir) if project_dir else []

    def _detect_l3_patterns(steps_list, start_idx):
        if not l3_patterns:
            return None
        remaining = steps_list[start_idx:]

        for kw_name, regexes, consumed in l3_patterns:
            if len(remaining) < consumed:
                continue
            matches = []
            all_match = True
            for idx, regex in enumerate(regexes):
                m = regex.search(remaining[idx])
                if m:
                    matches.append(m)
                else:
                    all_match = False
                    break
            if all_match and matches:
                params = {}
                if matches[0].lastindex and matches[0].lastindex >= 1:
                    params['tab_name'] = matches[0].group(1)
                return (kw_name, params, consumed)

        return None

    pending_desc = None
    source_map = []
    i = 0
    while i < len(raw_steps):
        step_text = raw_steps[i]

        if re.search(r'^访问\s*https?://', step_text):
            i += 1
            generator._pending_nav_wait = False
            continue

        l3_result = _detect_l3_patterns(raw_steps, i)
        if l3_result:
            kw_name, kw_params, consumed = l3_result
            yaml_start = len(all_steps)
            all_steps.append({
                'desc': f"L3: {kw_name}({', '.join(f'{k}={v}' for k, v in kw_params.items())})",
                'keyword': kw_name,
                'params': kw_params,
            })
            source_map.append({
                'excel_step': i + 1,
                'excel_steps_consumed': consumed,
                'yaml_step_start': yaml_start,
                'yaml_step_count': 1,
            })
            i += consumed
            generator._pending_nav_wait = False
            continue

        parsed = parse_step(step_text)

        # [DEBUG-F7] 追踪步骤处理
        _debug_f7(f"\n[DEBUG-F7] === 处理步骤 [{i+1}/{len(raw_steps)}]: '{step_text}' ===")

        generator._update_container_context_pre(parsed)
        steps = generator.generate_step(parsed)
        generator._update_container_context_post(parsed)

        if (generator._is_button_action(parsed)
                and not generator._next_needs_no_wait(raw_steps, i)):
            steps.append({
                'desc': '等待页面加载完成',
                'keyword': 'wait_for_loading_complete',
                'params': {},
            })

        if getattr(generator, '_pending_nav_wait', False):
            if not any(s.get('keyword') == 'wait_for_loading_complete' for s in steps):
                steps.append({
                    'desc': '等待页面加载完成',
                    'keyword': 'wait_for_loading_complete',
                    'params': {},
                })
            generator._pending_nav_wait = False

        yaml_start = len(all_steps)
        source_map.append({
            'excel_step': i + 1,
            'excel_steps_consumed': 1,
            'yaml_step_start': yaml_start,
            'yaml_step_count': len(steps),
        })
        all_steps.extend(steps)
        generator.collect_refs_from_steps(steps)
        i += 1

    total_steps = len(all_steps)
    log_steps = sum(1 for s in all_steps if s.get('keyword') == 'log')
    if total_steps > 3 and log_steps / total_steps > 0.30:
        pct = int(100 * log_steps / total_steps)
        print(f"  [WARN] {case_name}: log 步骤占比 {log_steps}/{total_steps} = {pct}%，"
              f"已加入节点 4 批量修复队列")
        _repair_needed = True
    else:
        _repair_needed = False
    if log_steps > 0:
        print(f"  [INFO] {case_name}: {log_steps}/{total_steps} log 步骤")

    # SelfCheckLayer
    l3_kw = _load_l3_keyword_names(project_dir) if project_dir else set()
    self_checker = SelfCheckLayer(
        resolver=generator.resolver,
        data_entries=generator.data_entries,
        data_group_name=generator.data_group_name,
        l3_keywords=l3_kw,
        module_name=module,
    )
    all_steps, sc_repairs, sc_remaining = self_checker.run_all_checks(all_steps, case_id)
    if sc_repairs:
        print(f"  [SELF-CHECK] {case_name}: {len(sc_repairs)} 项自修复")
    if sc_remaining:
        print(f"  [SELF-CHECK] {case_name}: {len(sc_remaining)} 项 remaining（待人工）")

    # V3: desc 引号规范化
    known_labels = set(generator._compat_labels().keys()) if generator.resolver else set()
    if known_labels:
        for step in all_steps:
            if isinstance(step, dict) and 'desc' in step and isinstance(step['desc'], str):
                step['desc'] = _normalize_desc_quotes(step['desc'], known_labels)

    # V3b: [待确认] desc 引号兜底（确保 Phase 6 label 提取不失败）
    _ensure_desc_quotes(all_steps)

    # 生成 YAML
    case_yaml = {
        'id': case_id,
        'name': case_name,
        'skip': False,
        'steps': all_steps,
    }

    filename = f"{seq:02d}_{case_id}.yaml"
    filepath = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# {case_name}\n")
        yaml.dump(case_yaml, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 后推断法：按解析来源分类步骤（Gap 1 替代方案）
    source_counts, pending_fields = _classify_steps_for_report(all_steps, source_map, l3_kw)

    return filepath, source_map, {
        'repair_needed': _repair_needed,
        'log_steps': log_steps,
        'total_steps': total_steps,
        'case_name': case_name,
        'case_id': case_id,
        'seq': seq,
        'self_check_repairs': sc_repairs,
        'self_check_remaining': sc_remaining,
        'source_counts': source_counts,
        'pending_fields': pending_fields,
    }


def preflight_check(target_cases, disc_labels, target_module):
    """discovery 覆盖率预检。"""
    excel_labels = {}
    for case in target_cases:
        for step in case.get('steps', []):
            step_text = step if isinstance(step, str) else step.get('step', '')
            if not step_text:
                continue
            parsed = parse_step(step_text)
            if not parsed or parsed['type'] in ('skip', 'open_url', 'unknown'):
                continue
            pargs = parsed.get('args', [])
            if len(pargs) >= 1:
                label = pargs[0]
                if label and not label.startswith('http'):
                    excel_labels[label] = parsed['type']

    if not excel_labels:
        return {'hit_rate': 1.0, 'hits': [], 'misses': [], 'fix_strategies': {}}

    hits = []
    misses = []
    fix_strategies = defaultdict(int)

    for label, step_type in excel_labels.items():
        if label in disc_labels:
            hits.append(label)
            continue

        matched = False
        for disc_label in disc_labels:
            if CaseGenerator._substring_similarity(label, disc_label) >= 0.4:
                hits.append(label)
                fix_strategies['substring-match'] += 1
                matched = True
                break
        if matched:
            continue

        closest = None
        best_score = 0.0
        for disc_label in disc_labels:
            score = CaseGenerator._substring_similarity(label, disc_label)
            if score > best_score:
                best_score = score
                closest = disc_label
        misses.append({'label': label, 'type': step_type, 'closest': closest})

    hit_rate = len(hits) / len(excel_labels) if excel_labels else 1.0

    result = {
        'excel_labels': len(excel_labels),
        'exact_hits': len(hits) - sum(fix_strategies.values()),
        'auto_fixed': sum(fix_strategies.values()),
        'fix_strategies': dict(fix_strategies),
        'remaining_misses': len(misses),
        'final_hit_rate': f"{int(hit_rate * 100)}%",
        'hit_rate': hit_rate,
        'misses': misses,
    }

    if hit_rate < 0.6:
        extra = (" discovery 数据与 Excel 严重脱节，建议检查 Phase 4 探测是否覆盖了所有操作对象。"
                 if hit_rate < 0.3 else " 建议检查 discovery 覆盖率。")
        print(f"[WARN] discovery 覆盖率偏低: {len(hits)}/{len(excel_labels)}"
              f" ({int(hit_rate * 100)}%){extra}")
        print("未匹配的标签:")
        for m in misses[:10]:
            hint = f" ← 最接近: '{m['closest']}'" if m.get('closest') else " ← 无近似"
            print(f"  - '{m['label']}' ({m['type']}){hint}")

    if hit_rate < 0.8:
        print(f"[WARN] discovery 覆盖率偏低: {int(hit_rate * 100)}%")
        for m in misses[:5]:
            print(f"  - '{m['label']}' ({m['type']})")

    return result


def _batch_repair_case(case_file, generator):
    """节点 4 批量修复：读取已生成的 case YAML，尝试修复 log 步骤"""
    with open(case_file, 'r', encoding='utf-8') as f:
        raw = f.read()

    data = yaml.safe_load(raw)
    if not data or not isinstance(data, dict):
        return 0

    steps = data.get('steps', [])
    repaired = 0

    def _infer_container(idx):
        for delta in (-1, 1, -2, 2):
            nidx = idx + delta
            if 0 <= nidx < len(steps):
                loc = steps[nidx].get('params', {}).get('locator', '')
                if isinstance(loc, str):
                    ct = _detect_container_type(loc)
                    if ct:
                        return ct
        return None

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if step.get('keyword') != 'log':
            continue

        desc = step.get('desc', '')
        msg = step.get('params', {}).get('message', '')

        quoted = re.findall(r'[""“”\'](.+?)[""“”\']', desc + ' ' + msg)
        _container = _infer_container(i)
        if len(quoted) >= 2:
            label, value = quoted[0], quoted[1]
            disc_elem = generator._discovery_lookup(label)
            locator_ref = generator._elem_to_ref(disc_elem) if disc_elem else None
            if locator_ref:
                data_ref = generator.add_data(f'repair_{i}_text', value)
                steps[i] = {
                    'desc': f"在「{label}」中输入 [自修复]",
                    'keyword': 'fill_value',
                    'params': {'locator': locator_ref, 'value': data_ref},
                }
                repaired += 1
                continue

        elif len(quoted) == 1:
            label = quoted[0]
            disc_elem = generator._discovery_lookup(label)
            locator_ref = generator._elem_to_ref(disc_elem) if disc_elem else None
            if locator_ref:
                steps[i] = {
                    'desc': f'点击「{label}」 [自修复]',
                    'keyword': 'click_element',
                    'params': {'locator': locator_ref},
                }
                repaired += 1
                continue

    if repaired > 0:
        data['steps'] = steps
        with open(case_file, 'w', encoding='utf-8') as f:
            f.write(f"# {data.get('name', '')}\n")
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return repaired
