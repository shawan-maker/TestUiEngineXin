#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
case_generator.py - Case 生成器核心类

从 _case_generator.py 提取的 CaseGenerator 类，负责将解析后的步骤转换为
case YAML 格式。
"""

import glob
import os
import re
import json
import yaml
from collections import defaultdict

from core.step_patterns import parse_step, STEP_PATTERNS, Q
from core.field_suffixes import label_to_key as _shared_label_to_key, EXPAND_LABELS
from core.xpath_utils import (
    inject_hidden_filter as _inject_hidden_filter,
    apply_container_prefix,
)
from core.element_types import normalize_type as _normalize_type
from core.element_resolver import ElementResolver
from probe.probe_element import _get_expand_patterns, _safe_format, load_knowledge
from generation.case_utils import (
    _slugify, _detect_container_type, _build_date_picker_xpath,
    _get_assertion_kb_pattern, _get_first_kb_pattern,
    _find_table_action, _find_detail_link, _find_section_row_link
)
from generation.pages_writer import (
    _make_editable_locator, _make_editable_locator_postfix,
    DEFAULT_COMMON_ELEMENTS as COMMON_ELEMENTS
)

# DEBUG-F7 控制
_DEBUG_F7 = os.environ.get('DEBUG_F7', '')

def _debug_f7(*args, **kwargs):
    """条件化 DEBUG-F7 输出"""
    if _DEBUG_F7:
        print(*args, **kwargs)

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

    def __init__(self, resolver, module_name, project_dir='', framework=None):
        """
        Args:
            resolver: ElementResolver 实例（唯一 discovery 数据源）
            module_name: 模块 slug
            project_dir: 项目根目录
            framework: 页面 UI 框架（'ant-design' | 'element-ui' | None）
        """
        self.resolver = resolver
        self.module = module_name
        self._project_dir = project_dir
        self._framework = framework  # L3: 页面级框架
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

        # 填充 iframe field_meta
        self._populate_field_meta()

    def _populate_field_meta(self):
        """从 resolver 元素中提取 iframe 信息，填充 field_meta。

        [H4] 使用 raw dict（self._discovery_element_map 的值是 dict，非 ElementEntry）
        [H5] 同时检查 iframe_context 和 has_iframe（向后兼容 rich_text）
        [C4] 保守策略：只标记探测确认的 base_field + _iframe 引用字段，
             不扩散到伴随后缀（_select/_input/_editable 等）。
             未标记的 companion 由 Phase 6 _try_find_in_iframes 运行时兜底。
        """
        for (ctx, label), elem in self._discovery_element_map.items():
            iframe_ctx = elem.get('iframe_context')
            has_iframe = elem.get('has_iframe')
            if not (iframe_ctx or has_iframe):
                continue

            group = elem.get('group_name')
            field = elem.get('field_key')
            if not group or not field:
                continue

            # 去掉容器 hash 后缀
            base_field = self._CT_HASH_RE.sub('', field)

            # 只标记探测确认的字段 + _iframe 引用字段
            # 不扩散到 _select/_input/_editable 等伴随后缀 — Phase 6 运行时兜底
            meta_entry = {
                'type': 'iframe',
                'iframe_context': iframe_ctx,
                'iframe_field': f'{base_field}_iframe',
            }
            self.field_meta[(group, base_field)] = meta_entry
            self.field_meta[(group, f'{base_field}_iframe')] = meta_entry

    # ─── 兼容适配层 ───────────────────────────────────────────

    def _build_dropdown_option_xpath(self, action):
        """构建下拉菜单选项的 XPath（L3e: 框架感知）

        用于 click_more_then 和 click_more_then_click 分支。

        Args:
            action: 菜单项文本

        Returns:
            str: 带 xpath= 前缀的定位器
        """
        if self._framework == 'ant-design':
            # Ant Design: 使用 ant-dropdown-menu 容器
            return (f"xpath=//ul[contains(@class,'ant-dropdown-menu')]"
                    f"//li[contains(@class,'ant-dropdown-menu-item')]"
                    f"//*[contains(text(),'{action}')]"
                    f"[not(ancestor-or-self::*[contains(@class,'ant-dropdown-hidden')])]")
        else:
            # Element UI: 使用 x-placement 定位浮层
            return (f"xpath=//*[@x-placement and not(@x-placement='')]"
                    f"//*[contains(text(),'{action}')]"
                    f"[not(ancestor-or-self::*[contains(@class,'is-hidden')])]"
                    f"[not(ancestor-or-self::*[contains(@style,'display: none')])]")

    def _build_more_button_fallback_xpath(self):
        """构建「更多」按钮的回退 XPath（L3e: 框架感知）

        当找不到更多按钮的定位器时使用。

        Returns:
            str: 带 xpath= 前缀的定位器
        """
        if self._framework == 'ant-design':
            # Ant Design: 排除下拉菜单中的「更多」文本
            return ("xpath=(//*[contains(text(),'更多')]"
                    "[not(ancestor-or-self::*[contains(@class,'ant-select-dropdown')])]"
                    "[ancestor::tbody])[1]")
        else:
            # Element UI: 排除下拉菜单中的「更多」文本
            return ("xpath=(//*[contains(text(),'更多')]"
                    "[not(ancestor-or-self::*[contains(@class,'el-select-dropdown')])]"
                    "[ancestor::tbody])[1]")

    def _build_month_table_xpath(self, scope_prefix=''):
        """构建月份选择器的 XPath（L3c: 框架感知）

        Args:
            scope_prefix: 容器作用域前缀

        Returns:
            str: XPath 表达式
        """
        if self._framework == 'ant-design':
            # Ant Design: 使用 ant-picker-month-panel
            return f"{scope_prefix}//table[contains(@class,'ant-picker-month-panel')]"
        else:
            # Element UI: 使用 el-month-table
            return f"{scope_prefix}//table[@class='el-month-table']"

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
            # C1: _iframe 放最前面，避免 submit_btn_iframe 先匹配 _btn
            for suf in ('_iframe', '_select', '_input', '_editable', '_first_option',
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

    def _wrap_click_for_iframe(self, group, field, keyword='click_element', **extra_params):
        """将 click_element 包装为 frame_click_element（如果在 iframe 内）。

        Args:
            group: 元素组名
            field: 元素字段名
            keyword: 原始关键字（默认 click_element）
            **extra_params: 额外参数（如 button='right'）
        Returns:
            (keyword, params) 元组
        """
        meta = self.field_meta.get((group, field))
        if meta and meta.get('type') == 'iframe':
            iframe_ref = f"${{{group}.{meta['iframe_field']}}}"
            params = {
                'frame': iframe_ref,
                'locator': f"${{{group}.{field}}}",
            }
            params.update(extra_params)
            return 'frame_click_element', params
        else:
            params = {'locator': f"${{{group}.{field}}}"}
            params.update(extra_params)
            return keyword, params

    def _wrap_fill_for_iframe(self, group, field, value, keyword='fill_value'):
        """将 fill_value 包装为 frame_fill_value（如果在 iframe 内）。

        Args:
            group: 元素组名
            field: 元素字段名
            value: 填充值
            keyword: 原始关键字（默认 fill_value）
        Returns:
            (keyword, params) 元组
        """
        meta = self.field_meta.get((group, field))
        if meta and meta.get('type') == 'iframe':
            iframe_ref = f"${{{group}.{meta['iframe_field']}}}"
            return 'frame_fill_value', {
                'frame': iframe_ref,
                'locator': f"${{{group}.{field}}}",
                'value': value,
            }
        else:
            return keyword, {
                'locator': f"${{{group}.{field}}}",
                'value': value,
            }

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

        # nth > 1 时追加序号后缀，避免同 label 不同 nth 的 field 冲突（如"网络"第1/2个下拉框）
        if nth > 1:
            field = f'{field}_{nth}'

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
        # L3: 根据框架选择不同的 XPath 模式
        if self._framework == 'ant-design':
            # Ant Design: 使用 ant-select-selector
            select_xpath_base = (
                f"//*[contains(text(),'{label}')]"
                f"/ancestor::*[contains(@class,'ant-form-item')]"
                f"//span[contains(@class,'ant-select-selector')]"
            )
        else:
            # Element UI (默认): 使用 el-input__inner
            select_xpath_base = (
                f"//*[contains(text(),'{label}')]"
                f"/following-sibling::*[self::div or self::span]"
                f"//input[@class='el-input__inner']"
            )

        # 4. 容器前缀（在 drawer/dialog 内时限定范围，避免跨容器误匹配）
        select_xpath_base = apply_container_prefix(select_xpath_base, self.current_container)

        # 4.5. 序号后缀：(xpath)[nth] — 默认 [1]，兼容多同名下拉框场景
        select_xpath = f"({select_xpath_base})[{nth}]"

        # 4.6. _editable 从 select_xpath 后置追加（确保与 _select 指向同一个 DOM 元素）
        #      后置 [not(@readonly)] 先锁定第 N 个 input，再检查该元素是否非 readonly
        editable_xpath = _make_editable_locator_postfix(select_xpath)

        # 4.7. _expand: click 展开下拉框（Phase 5 生成 input 目标，Phase 6 验证后转换为 el-select 容器）
        #      与 select_xpath_base 保持一致的锚点和目标，由 Phase 6 根据验证结果决定最终形态
        expand_xpath_base = select_xpath_base  # 复用 select_xpath_base（已含容器前缀）
        expand_xpath = f"({expand_xpath_base})[{nth}]"

        # 5. 注册 _select 到 required_fields（原始 XPath，无 hidden filter）
        #    PagesWriter Stage 2 注入 hidden filter
        #    PagesWriter Stage 3 生成 _editable + _first_option companion
        self._track_field(group, f'{field}_select',
                          locator=f'xpath={select_xpath}',
                          label=label,
                          comment='el-select KB 标准模式')

        # 5a. 注册 _expand（Phase 5 生成 input 目标，Phase 6 验证后转换为 el-select 容器）
        self._track_field(group, f'{field}_expand',
                          locator=f'xpath={expand_xpath}',
                          label=label,
                          comment='el-select 点击展开（Phase 6 转换）')

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
        # L3: 根据框架选择下拉面板 XPath
        if self._framework == 'ant-design':
            # Ant Design: 使用 ant-select-dropdown + ant-select-item-option
            first_option_xpath = (
                "(//div[contains(@class,'ant-select-dropdown')]"
                "//*[contains(@class,'ant-select-item-option')"
                " and not(contains(@class,'ant-select-item-option-disabled'))])[1]"
            )
        else:
            # Element UI (默认): 使用 x-placement + el-select-dropdown__item
            first_option_xpath = (
                "(//div[@x-placement and not(@x-placement='')]//li"
                "[contains(@class,'el-select-dropdown__item')"
                " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                " and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
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
        expand_ref = f'${{{group}.{field}_expand}}'

        # 8. 选项 XPath（inline，不走 PagesWriter Stage 2，需手动拼接 hidden filter）
        # L3: 根据框架选择下拉面板 XPath
        if self._framework == 'ant-design':
            # Ant Design: 使用 ant-select-dropdown + ant-select-item-option
            option_xpath = (
                f"(//div[contains(@class,'ant-select-dropdown')]"
                f"//*[contains(@class,'ant-select-item-option')"
                f" and contains(.,'{option_ref}')"
                f" and not(contains(@class,'ant-select-item-option-disabled'))])[1]"
            )
        else:
            # Element UI (默认): 使用 x-placement + el-select-dropdown__item
            option_xpath = (
                f"(//div[@x-placement and not(@x-placement='')]//li"
                f"[contains(.,'{option_ref}')"
                f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                f" and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
            )

        # === Step 1: 点击下拉框 ===
        nth_desc = f"第{nth}个" if nth > 1 else ""
        steps.append({
            'desc': f"选择「{label}」 - 点击{nth_desc}下拉框",
            'keyword': 'click_element',
            'label': label,
            'params': {'locator': expand_ref},
        })

        # === Step 1.5: 等待下拉面板打开 ===
        steps.append({
            'desc': f"等待「{label}」下拉面板打开",
            'keyword': 'wait_for_time',
            'label': label,
            'params': {'timeout': 1000},
        })

        # === Step 2: 条件分支 ===
        then_steps = [
            {
                'desc': f"选择「{label}」 - 输入搜索",
                'keyword': 'fill_value',
                'label': label,
                'params': {'locator': select_ref, 'value': search_ref},
            },
            {
                'desc': f"等待「{label}」搜索结果加载",
                'keyword': 'wait_for_time',
                'label': label,
                'params': {'timeout': 1500},
            },
            {
                'desc': f"选择「{label}」 - 选择选项",
                'keyword': 'click_element',
                'label': label,
                'params': {'locator': f'xpath={option_xpath}'},
            },
        ]

        # else 分支：readonly 模式
        # 下拉面板已展开，先检查目标选项是否可见（虚拟滚动场景可能不可见）
        else_then_steps = [
            {
                'desc': f"选择「{label}」 - 点击目标选项",
                'keyword': 'click_element',
                'label': label,
                'params': {'locator': f'xpath={option_xpath}'},
            },
        ]
        else_else_steps = [
            {
                'desc': f"选择「{label}」 - 目标选项不可见，回退选择第一项",
                'keyword': 'click_element',
                'label': label,
                'params': {'locator': first_option_ref},
            },
        ]
        else_steps = [
            {
                'desc': f"判断「{label}」目标选项是否可见",
                'keyword': 'if_element_visible',
                'label': label,
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
            'label': label,
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
        """返回同名标签的候选按钮（容器上下文感知）。

        严格容器过滤：
        - 在 dropdown 中（current_container == 'dropdown'）：只返回 from_expand=True 的按钮
        - 在容器内（current_container != None）：只返回该容器内的按钮
        - 在列表页（current_container == None）：只返回列表页级别的按钮
        - 不回退：避免点击错误上下文的同名按钮
        """
        results = []
        seen_refs = set()
        for (ctx, disc_label), elem in self._discovery_element_map.items():
            if disc_label != label and self._substring_similarity(label, disc_label) < 0.6:
                continue
            ref = self._elem_to_ref(elem)
            if ref and ref not in seen_refs:
                elem_container = elem.get('container_type')
                is_from_expand = elem.get('from_expand', False)
                # 严格容器过滤：只匹配当前上下文
                if self.current_container == 'dropdown':
                    # 在 dropdown 中：只接受 from_expand=True 的按钮
                    if not is_from_expand:
                        continue
                elif self.current_container:
                    # 在其他容器内：只接受当前容器的按钮
                    if elem_container != self.current_container:
                        continue
                else:
                    # 在列表页：只接受无容器的按钮
                    if elem_container is not None:
                        continue
                seen_refs.add(ref)
                results.append({
                    'ref': ref,
                    'container': elem_container,
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
        """从 discovery_element_map 查找元素（两层 context 回退）。

        多URL场景：优先按 page_slug 精确索引查找，避免跨URL同名覆盖。
        L3 全局回退已删除（2026-08-07）：防止跨页面误匹配，未命中时返回 None，
        交由调用方生成 [待确认] 占位符，Phase 6 运行时补探。
        """
        ctx = context or self._current_context or 'list_page'
        page_slug = self._get_current_page_slug()

        # L1: 多URL精确索引：优先按 page_slug 查找
        if page_slug:
            elem = self._discovery_page_element_map.get((page_slug, ctx, label))
            if elem and elem.get('locator'):
                return elem
            # 容器回退到 list_page
            if ctx != 'list_page':
                elem = self._discovery_page_element_map.get((page_slug, 'list_page', label))
                if elem and elem.get('locator'):
                    return elem

        # L2: 向后兼容：原有逻辑（无 page_slug 维度）
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
        # L3 已删除：不再做跨 context 全局回退，直接返回 None
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
        best_score = 0.6
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

    _CONTAINER_OPEN_KEYWORDS = ('新增', '编辑', '添加', '修改', '创建')

    def _extract_button_label(self, parsed):
        """从任意 ptype 中提取按钮名。

        设计原则：只有按钮点击才触发容器状态判断，
        非按钮操作（输入、选择、勾选）返回 None，不触发判断。
        两次按钮点击之间，容器前缀保持不变。
        """
        ptype = parsed['type']
        args = parsed['args']
        if not args:
            return None
        # 所有按钮点击类 ptype，args[0] 就是按钮名
        if ptype in (
            'click_btn', 'click_table_row_btn', 'click_detail_link',
            'if_visible',
            'click_more_then_click', 'click_more_then',
            'click_table_action', 'conditional_click_btn',
        ):
            return args[0]
        return None

    def _is_container_open(self, parsed):
        """检查步骤是否会打开容器。

        通用逻辑：从任意按钮点击 ptype 提取按钮名，查询 trigger_map 判断。
        不再使用 ptype 白名单硬编码。
        """
        label = self._extract_button_label(parsed)
        if not label:
            _debug_f7(f"  [DEBUG-F7] _is_container_open: no button label → False")
            return False

        entry = self._discovery_trigger_map.get(label)
        if entry:
            result_type = entry.get('result_type')
            is_open = result_type in ('container', 'navigation', 'new_tab')
            _debug_f7(f"  [DEBUG-F7] _is_container_open: label='{label}', "
                      f"trigger_map_hit=True, result_type={result_type} → {is_open}")
            return is_open

        # 启发式回退（无 discovery 数据时）
        heuristic = any(kw in label for kw in self._CONTAINER_OPEN_KEYWORDS)
        _debug_f7(f"  [DEBUG-F7] _is_container_open: label='{label}', "
                  f"trigger_map_hit=False, heuristic={heuristic}")
        return heuristic

    def _is_button_action(self, parsed):
        return parsed.get('type') in self._BUTTON_TYPES

    def _next_needs_no_wait(self, raw_steps, idx):
        """判断下一步是否不需要自动插入 wait_for_loading_complete

        返回 True（不插入等待）的情况：
        - 下一步是 wait_element（显式等待元素）
        - 下一步是 assert/assert_row/assert_count/check_assert（断言）
        - 下一步是 l3_call 且包含"等待加载完成"或"等待页面加载完成"（已显式等待）

        返回 False（需要插入等待）的情况：
        - 下一步是 l3_call 且为 wait_for_time（如"等待1s"）→ 仍需插入 wait_for_loading_complete
        - 下一步是其他 l3_call（如 log、refresh）→ 仍需插入

        Args:
            raw_steps: Excel 原始步骤列表
            idx: 当前步骤索引

        Returns:
            bool: True 表示不需要自动插入等待，False 表示需要插入
        """
        if idx + 1 >= len(raw_steps):
            return False

        next_step = raw_steps[idx + 1]
        next_parsed = parse_step(next_step)
        next_type = next_parsed.get('type')

        # 非 l3_call 类型：直接检查是否在黑名单中
        if next_type != 'l3_call':
            return next_type in self._NO_WAIT_AFTER_TYPES

        # l3_call 类型：精细化判断
        # parse_step 返回结构：{'type': 'l3_call', 'args': ('中文名称', None), 'raw': '原文'}
        # 需要通过 _find_workflow 解析出英文 name，然后判断

        cn_name = next_parsed.get('args', (None,))[0]
        if not cn_name:
            return False

        # 通过 workflow 解析获取英文 name
        wf_def = self._find_workflow(cn_name)
        if not wf_def:
            return False

        # 阻止插入的 workflow 英文名
        blocking_l3_keywords = {
            'wait_for_loading_complete',
            'check_page_loaded',
        }

        wf_name = wf_def.get('name')
        return wf_name in blocking_l3_keywords

    def _update_container_context_pre(self, parsed):
        if parsed['type'] in ('go_back', 'refresh'):
            self.current_container = None

    def _update_container_context_post(self, parsed):
        """Post 阶段：按钮点击后更新容器上下文。

        只处理"打开容器/导航"的情况，不猜测"关闭容器"。
        容器是否关闭由 Phase 6 实际探测决定并写回 pages.yaml。
        """
        _debug_f7(f"  [DEBUG-F7] _update_container_context_post: "
              f"type='{parsed['type']}', args={parsed['args']}, "
              f"current_context='{self._current_context}'")

        label = self._extract_button_label(parsed)
        if not label:
            # 非按钮操作（输入、选择、勾选等），不触发判断，前缀保持不变
            _debug_f7(f"  [DEBUG-F7] → 非按钮操作，保持当前前缀")
            return

        # P5-2: 识别 dropdown trigger（如"更多"），设置临时 dropdown 状态
        if label in EXPAND_LABELS:
            self.current_container = 'dropdown'
            self._current_context = label
            _debug_f7(f"  [DEBUG-F7] → 识别 dropdown trigger '{label}', "
                      f"current_container='dropdown'")
            return

        entry = self._discovery_trigger_map.get(label)
        if entry:
            result_type = entry.get('result_type')
            if result_type == 'container':
                self.current_container = entry.get('container_type')
            elif result_type == 'navigation':
                self.current_container = 'new_page'
                self._pending_nav_wait = True
            elif result_type == 'new_tab':
                self.current_container = 'new_tab'
                self._pending_nav_wait = True
            elif result_type == 'inline':
                pass
            elif entry.get('skipped'):
                # Phase 4 跳过了探测（如按钮 disabled），但按钮确实存在
                # 推断会打开容器（toolbar 按钮最常见的情况）
                # Phase 6 运行时会根据实际探测结果纠正定位器值
                self.current_container = 'dialog'
            self._current_context = label
            _debug_f7(f"  [DEBUG-F7] → 更新 _current_context='{label}', "
                      f"current_container='{self.current_container}' (from trigger_map)")
        else:
            # 不在 trigger_map 中 → 不变，保持当前前缀
            _debug_f7(f"  [DEBUG-F7] → label='{label}' 不在 trigger_map 中，保持当前前缀")

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

    def _find_menu_item_element(self, label):
        """在 resolver groups 中查找菜单项元素引用。"""
        groups = self._compat_groups()
        for group_name, fields in groups.items():
            for field_name, locator in fields.items():
                if not isinstance(locator, str):
                    continue
                if field_name.endswith('_menu') and label in locator:
                    return f"${{{group_name}.{field_name}}}"
                if ("el-menu-item" in locator or "ant-menu-item" in locator) and label in locator:
                    return f"${{{group_name}.{field_name}}}"
        pending_ref, _ = self.resolver.make_pending_ref(
            label, 'menu_item',
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
        skill_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        self._current_context = 'list_page'  # 防止上一个 case 的容器上下文泄漏

    def add_data(self, field, value):
        """添加数据字段，同 case 内同 field 自动添加 _2, _3 后缀避免覆盖"""
        self.data_entries.setdefault(self.data_group_name, {})
        actual_field = f"{self.current_case_prefix}{field}"
        # 同 case 内同 field 自动后缀（如"架构"两次选择不同值）
        if actual_field in self.data_entries[self.data_group_name]:
            existing_val = self.data_entries[self.data_group_name][actual_field]
            if existing_val != value:
                # 值不同才添加后缀，值相同则复用（幂等）
                suffix = 2
                while f"{actual_field}_{suffix}" in self.data_entries[self.data_group_name]:
                    suffix += 1
                actual_field = f"{actual_field}_{suffix}"
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
                return  # 拒绝覆盖，保留第一个版本
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
        _container_markers = ('el-drawer', 'el-dialog', 'el-message-box',
                              'ant-drawer', 'ant-modal')
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
                    'label': label,
                    'params': {'locator': el['cascader']},
                })
                for i, text in enumerate(levels[:-1]):
                    level_ref = self.add_data(f'{el["field_prefix"]}_level{i+1}', text)
                    # L3: 根据框架选择级联菜单 XPath
                    if self._framework == 'ant-design':
                        level_xpath = f"//div[contains(@class,'ant-cascader-menu')]//li[contains(.,'{level_ref}')]"
                    else:
                        level_xpath = f"//li[@role='menuitem']//span[contains(text(),'{level_ref}')]"
                    level_xpath = _inject_hidden_filter(level_xpath)
                    steps.append({
                        'desc': f'「{label}」第{i+1}级: {text}',
                        'keyword': 'click_element',
                        'label': label,
                        'params': {
                            'locator': f"xpath={level_xpath}"
                        },
                    })
                last = levels[-1]
                last_ref = self.add_data(f'{el["field_prefix"]}_last', last)
                # L3: 根据框架选择最后一级 XPath
                if self._framework == 'ant-design':
                    checkbox_xpath = (f"//div[contains(@class,'ant-cascader-menu')]//li[contains(.,'{last_ref}')]"
                                     f"//span[contains(@class,'ant-checkbox-inner')]")
                    text_xpath = (f"//div[contains(@class,'ant-cascader-menu')]//li[contains(.,'{last_ref}')]")
                else:
                    checkbox_xpath = (f"//li[@role='menuitem' and contains(.,'{last_ref}')]"
                                     f"//span[@class='el-checkbox__inner']")
                    text_xpath = (f"//li[@role='menuitem']//span"
                                 f"[contains(text(),'{last_ref}')]")
                checkbox_xpath = _inject_hidden_filter(checkbox_xpath)
                checkbox_xpath = f"xpath={checkbox_xpath}"
                text_xpath = _inject_hidden_filter(text_xpath)
                text_xpath = f"xpath={text_xpath}"
                steps.append({
                    'desc': f'「{label}」最后一级: {last}',
                    'keyword': 'if_element_visible',
                    'label': label,
                    'params': {
                        'locator': checkbox_xpath,
                        'timeout': 500,
                        'then_steps': [{
                            'desc': f'「{label}」 - 点击勾选框',
                            'keyword': 'click_element',
                            'label': label,
                            'params': {'locator': checkbox_xpath},
                        }],
                        'else_steps': [{
                            'desc': f'「{label}」 - 点击文本',
                            'keyword': 'click_element',
                            'label': label,
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
            # 选项卡：单次点击选项文本（数据分离模式）
            # pages 存容器 XPath（不含选项值），data 存选项值，case 用内联 XPath

            # ── Step 1: 生成 field prefix（hash-based，只含 label）──
            field_with_suffix = _shared_label_to_key(
                label, 'option_card',
                container_type=self.current_container,
                skip_container_prefix=True)
            field = field_with_suffix[:-len('_card')] if field_with_suffix.endswith('_card') else field_with_suffix

            # ── Step 2: 确定 group ──
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

            # ── Step 3: 注册 pages 字段（通用容器 XPath，不含 value）──
            # 用途：文档存档 + probe 验证（R4.43）
            container_xpath = (
                f"//label[contains(.,'{label}')]"
                f"//following-sibling::*[self::div or self::span]"
            )
            container_xpath = apply_container_prefix(container_xpath, self.current_container)

            self._track_field(group, f'{field}_card',
                              locator=f'xpath={container_xpath}',
                              label=label,
                              comment='option-card 容器定位（不含选项值）')

            # ── Step 4: 注册 data 字段（选项值）──
            card_value_ref = self.add_data(f'{field}_card_value', value)
            # 生成: ${compute_data.case01_field_0eaa6a_card_value} = "ARM 计算"

            # ── Step 5: 生成内联 XPath（模板 + data 引用）──
            # Python 层完成参数替换，运行时 UIEngine 只做 ${data} → 字符串替换
            inline_xpath = (
                f"(//label[contains(.,'{label}')]"
                f"//following-sibling::*[self::div or self::span]"
                f"//*[contains(text(),'{card_value_ref}')"
                f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                f" and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
            )
            inline_xpath = apply_container_prefix(inline_xpath, self.current_container)

            # ── Step 6: 生成 case step（内联 XPath）──
            steps.append({
                'desc': f"在「{label}」选项卡中选择「{value}」",
                'keyword': 'click_element',
                'label': label,
                'params': {'locator': f'xpath={inline_xpath}'},
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
                        'label': label,
                        'params': {'frame': frame_ref, 'locator': body_ref, 'value': data_ref},
                    })
                elif meta and meta.get('type') == 'iframe':
                    # iframe 内的输入框
                    kw, params = self._wrap_fill_for_iframe(group, f'{field}_textarea', data_ref)
                    # iframe 操作前插入 wait_for_element 步骤
                    if kw.startswith('frame_') and 'frame' in params:
                        steps.append({
                            'desc': f"等待「{label}」的 iframe 加载完成",
                            'keyword': 'wait_for_element',
                            'label': label,
                            'params': {'locator': params['frame'], 'timeout': 10000},
                        })
                    steps.append({
                        'desc': f"在「{label}」中输入",
                        'keyword': kw,
                        'label': label,
                        'params': params,
                    })
                else:
                    # 检查是否是 iframe 内的普通输入框
                    input_meta = self.field_meta.get((group, f'{field}_input'))
                    if input_meta and input_meta.get('type') == 'iframe':
                        kw, params = self._wrap_fill_for_iframe(group, f'{field}_input', data_ref)
                        # iframe 操作前插入 wait_for_element 步骤
                        if kw.startswith('frame_') and 'frame' in params:
                            steps.append({
                                'desc': f"等待「{label}」的 iframe 加载完成",
                                'keyword': 'wait_for_element',
                                'label': label,
                                'params': {'locator': params['frame'], 'timeout': 10000},
                            })
                        steps.append({
                            'desc': f"在「{label}」中输入",
                            'keyword': kw,
                            'label': label,
                            'params': params,
                        })
                    else:
                        steps.append({
                            'desc': f"在「{label}」中输入",
                            'keyword': 'fill_value',
                            'label': label,
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
                        'label': label,
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
                            'label': label,
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
                        'label': label,
                        'params': {'locator': _common_ref},
                    })
                    return steps
            all_candidates = self.find_all_buttons(label)

            if all_candidates:
                # 严格容器过滤后，同一上下文不应有多个同名候选
                # 如果仍有多个（discovery 数据异常），取第一个并记录 warning
                if len(all_candidates) > 1:
                    print(f"    [WARN] 按钮「{label}」在当前上下文 "
                          f"({self.current_container or 'list_page'}) "
                          f"有 {len(all_candidates)} 个候选，取第一个")

                # 检查是否在 iframe 内
                ref = all_candidates[0]['ref']
                if ref.startswith('${') and ref.endswith('}'):
                    # 提取 group 和 field
                    inner = ref[2:-1]  # 去掉 ${ }
                    if '.' in inner:
                        group, field = inner.split('.', 1)
                        kw, params = self._wrap_click_for_iframe(group, field)
                        # iframe 操作前插入 wait_for_element 步骤
                        if kw.startswith('frame_') and 'frame' in params:
                            steps.append({
                                'desc': f"等待「{label}」按钮的 iframe 加载完成",
                                'keyword': 'wait_for_element',
                                'label': label,
                                'params': {'locator': params['frame'], 'timeout': 10000},
                            })
                        steps.append({
                            'desc': f'点击「{label}」按钮',
                            'keyword': kw,
                            'label': label,
                            'params': params,
                        })
                    else:
                        steps.append({
                            'desc': f'点击「{label}」按钮',
                            'keyword': 'click_element',
                            'label': label,
                            'params': {'locator': ref},
                        })
                else:
                    steps.append({
                        'desc': f'点击「{label}」按钮',
                        'keyword': 'click_element',
                        'label': label,
                        'params': {'locator': ref},
                    })
            else:
                disc_elem = self._discovery_lookup(label)
                disc_ref = self._elem_to_ref(disc_elem) if disc_elem else None
                if disc_ref:
                    steps.append({
                        'desc': f'点击「{label}」按钮',
                        'keyword': 'click_element',
                        'label': label,
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
                            'label': label,
                            'params': {'locator': pending_ref},
                        })
                    else:
                        steps.append({
                            'desc': f'[待确认] 点击「{label}」按钮',
                            'keyword': 'log',
                            'label': label,
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
                    'label': label,
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
                        'label': label,
                        'params': {'locator': pending_ref},
                    })
                else:
                    steps.append({
                        'desc': f'[待确认] 点击表格行操作「{label}」',
                        'keyword': 'log',
                        'label': label,
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
                        'label': kw,
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
                        'label': assert_text,
                        'params': {'locator': f'xpath={kb_xpath}'},
                    })
                # 优先级 2: 无引号 + 含"成功" → 通用成功断言
                elif '成功' in desc_text:
                    success_ref = self._get_common('success_text')
                    steps.append({
                        'desc': f"断言：{desc_text}",
                        'keyword': 'except_to_be_visible',
                        'label': '成功',
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
                            'label': assert_text,
                            'params': {'locator': f'xpath={kb_xpath}'},
                        })
                    else:
                        steps.append({
                            'desc': f"[待确认] 断言：{desc_text}",
                            'keyword': 'log',
                            'label': desc_text,
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
                'label': section or '记录数',
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
                'label': value,
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
                        'label': desc or '加载',
                        'params': {},
                    })
                else:
                    steps.append({
                        'desc': f"等待{desc}加载完成",
                        'keyword': 'wait_for_time',
                        'label': desc or '加载',
                        'params': {'timeout': 5000},
                    })
            else:
                steps.append({
                    'desc': f"等待{desc}",
                    'keyword': 'wait_for_time',
                    'label': desc or '等待',
                    'params': {'timeout': 2000},
                })

        elif ptype == 'wait_time':
            ms = int(args[0]) * 1000
            steps.append({
                'desc': f"等待{args[0]}秒",
                'keyword': 'wait_for_time',
                'label': '等待',
                'params': {'timeout': ms},
            })

        elif ptype == 'click':
            label = args[0]
            btn_ref = self.find_button(label, preferred_container=self.current_container)
            if btn_ref:
                steps.append({
                    'desc': f'点击「{label}」',
                    'keyword': 'click_element',
                    'label': label,
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
                        'label': label,
                        'params': {'locator': pending_ref},
                    })
                else:
                    steps.append({
                        'desc': f'[待确认] 点击「{label}」',
                        'keyword': 'log',
                        'label': label,
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
                    'label': label,
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
                        'label': label,
                        'params': {'locator': picker_ref},
                    })
                else:
                    picker_xpath, picker_desc = _build_date_picker_xpath(value)
                    picker_xpath = _inject_hidden_filter(picker_xpath)
                    steps.append({
                        'desc': picker_desc,
                        'keyword': 'click_element',
                        'label': label,
                        'params': {'locator': f"xpath={picker_xpath}"},
                    })
            else:
                steps.append({
                    'desc': f'[待确认] 日期选择「{label}」',
                    'keyword': 'log',
                    'label': label,
                    'params': {'message': f"[PENDING-NO-GROUP] 未找到日期选择器'{label}'"},
                })

        elif ptype == 'click_tab':
            label = args[0]
            tab_ref = self._find_tab_element(label)

            steps.append({
                'desc': f'点击「{label}」tab',
                'keyword': 'click_element',
                'label': label,
                'params': {'locator': tab_ref},
            })

            var_name = f"tab_{_slugify(label)}_id"
            steps.append({
                'desc': f'获取「{label}」tab面板ID',
                'keyword': 'get_attribute',
                'label': label,
                'params': {
                    'locator': tab_ref,
                    'name': 'aria-controls',
                    'target_var': var_name,
                },
            })

            self.current_tab_scope = var_name
            self.current_tab_scope_label = label

        elif ptype == 'menu_item':
            label = args[0]
            # 查找菜单项元素（支持侧边栏/顶部导航菜单）
            menu_ref = self._find_menu_item_element(label)

            steps.append({
                'desc': f'点击「{label}」菜单',
                'keyword': 'click_element',
                'label': label,
                'params': {'locator': menu_ref},
            })

        elif ptype == 'go_back':
            steps.append({
                'desc': "返回上一页",
                'keyword': 'go_back',
                'label': '返回',
            })
            steps.append({
                'desc': "等待页面加载",
                'keyword': 'wait_for_time',
                'label': '加载',
                'params': {'timeout': 2000},
            })

        elif ptype == 'refresh':
            steps.append({
                'desc': "刷新页面",
                'keyword': 'refresh',
                'label': '刷新',
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
                'label': '确认',
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
                'label': btn_label,
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
                    'label': item_desc or '勾选',
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
                    'label': item_desc or '勾选',
                    'params': {'locator': pending_ref or 'xpath=[待确认]'},
                })

        elif ptype == 'click_more_then':
            action = args[0].strip()
            groups = self._compat_groups()
            # Fix-More: 三层查找链，类型守卫防止 discovery 类型污染
            # ptype='click_more_then' 已知类型为 table-action-button，
            # 不依赖 discovery 的 type 字段决定后缀
            more_ref = _find_table_action(groups, '更多')
            if not more_ref:
                _btn_elem = self.find_button('更多', preferred_container=self.current_container)
                if _btn_elem:
                    # 类型守卫：只接受按钮类后缀，拦截 _select/_editable 等
                    _btn_field = _btn_elem.split('.', 1)[1].rstrip('}')
                    if _btn_field.endswith(('_btn', '_btn_row', '_link')):
                        more_ref = _btn_elem
            if not more_ref:
                more_ref, _ = self.resolver.make_pending_ref(
                    '更多', 'table_action',
                    container_type=self.current_container,
                    module_slug=self.module)
            if more_ref:
                steps.append({
                    'desc': "点击更多按钮",
                    'keyword': 'click_element',
                    'label': '更多',
                    'params': {'locator': more_ref},
                })
                steps.append({
                    'desc': "等待下拉菜单",
                    'keyword': 'wait_for_time',
                    'label': '更多',
                    'params': {'timeout': 1000},
                })
                option_ref = self._build_dropdown_option_xpath(action)
                steps.append({
                    'desc': f'选择「{action}」',
                    'keyword': 'click_element',
                    'label': action,
                    'params': {'locator': option_ref},
                })
            else:
                more_fallback = self._build_more_button_fallback_xpath()
                steps.append({
                    'desc': "[待确认] 点击更多按钮",
                    'keyword': 'click_element',
                    'label': '更多',
                    'params': {'locator': more_fallback},
                })
                steps.append({
                    'desc': "等待下拉菜单",
                    'keyword': 'wait_for_time',
                    'label': '更多',
                    'params': {'timeout': 1000},
                })
                option_ref = self._build_dropdown_option_xpath(action)
                steps.append({
                    'desc': f'[待确认] 选择「{action}」',
                    'keyword': 'click_element',
                    'label': action,
                    'params': {'locator': option_ref},
                })

        elif ptype == 'click_more_then_click':
            action = args[0].strip()
            groups = self._compat_groups()
            # Fix-More: 三层查找链，类型守卫防止 discovery 类型污染
            # ptype='click_more_then_click' 已知类型为 table-action-button，
            # 不依赖 discovery 的 type 字段决定后缀
            more_ref = _find_table_action(groups, '更多')
            if not more_ref:
                _btn_elem = self.find_button('更多', preferred_container=self.current_container)
                if _btn_elem:
                    # 类型守卫：只接受按钮类后缀，拦截 _select/_editable 等
                    _btn_field = _btn_elem.split('.', 1)[1].rstrip('}')
                    if _btn_field.endswith(('_btn', '_btn_row', '_link')):
                        more_ref = _btn_elem
            if not more_ref:
                more_ref, _ = self.resolver.make_pending_ref(
                    '更多', 'table_action',
                    container_type=self.current_container,
                    module_slug=self.module)
            if more_ref:
                steps.append({
                    'desc': "点击第一条记录的更多按钮",
                    'keyword': 'click_element',
                    'label': '更多',
                    'params': {'locator': more_ref},
                })
                steps.append({
                    'desc': "等待下拉菜单展开",
                    'keyword': 'wait_for_time',
                    'label': '更多',
                    'params': {'timeout': 1000},
                })
                option_ref = self._build_dropdown_option_xpath(action)
                steps.append({
                    'desc': f'点击「{action}」',
                    'keyword': 'click_element',
                    'label': action,
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
                        'label': '更多',
                        'params': {'locator': pending_ref},
                    })
                else:
                    more_fallback = self._build_more_button_fallback_xpath()
                    steps.append({
                        'desc': "[待确认] 点击更多按钮",
                        'keyword': 'click_element',
                        'label': '更多',
                        'params': {'locator': more_fallback},
                    })
                steps.append({
                    'desc': "等待下拉菜单展开",
                    'keyword': 'wait_for_time',
                    'label': '更多',
                    'params': {'timeout': 1000},
                })
                option_ref = self._build_dropdown_option_xpath(action)
                steps.append({
                    'desc': f'点击「{action}」',
                    'keyword': 'click_element',
                    'label': action,
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
                    f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                    f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
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
                'label': text,
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
                'label': desc or '等待',
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
                'label': section,
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element', 'label': label,
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
                'label': section,
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element', 'label': tab_label,
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
                'label': section,
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element', 'label': section,
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
                'label': section,
                'params': {
                    'locator': f'xpath={check_xpath}',
                    'then_steps': [
                        {'keyword': 'click_element', 'label': section,
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
            # Fix-TableRowBtn: 三层查找链，类型守卫防止 discovery 类型污染
            # ptype='click_table_row_btn' 已知类型为 table-action-button
            ref = _find_table_action(groups, label)
            if not ref:
                _btn_elem = self.find_button(label, preferred_container=self.current_container, prefer_row=True)
                if _btn_elem:
                    # 类型守卫：只接受按钮类后缀
                    _btn_field = _btn_elem.split('.', 1)[1].rstrip('}')
                    if _btn_field.endswith(('_btn', '_btn_row', '_link')):
                        ref = _btn_elem
            if not ref:
                ref, _ = self.resolver.make_pending_ref(
                    label, 'table_action',
                    container_type=self.current_container,
                    module_slug=self.module)
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
                    if context in group_name and ('dialog' in group_name or 'drawer' in group_name or 'modal' in group_name):
                        # L3d: 根据框架选择容器类名
                        if self._framework == 'ant-design':
                            if 'drawer' in group_name:
                                container_cls = 'ant-drawer'
                            else:
                                container_cls = 'ant-modal'
                        else:
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
                if self._framework == 'ant-design':
                    xpath = (
                        f"//*[contains(text(),'{label}')]//following-sibling::span"
                        f"[contains(@class,'ant-modal-close-x') or contains(@class,'ant-drawer-close')"
                        f" and not(ancestor-or-self::*[contains(@class,'ant-drawer-hidden')])"
                        f" and not(ancestor-or-self::*[contains(@class,'ant-modal-hidden')])"
                        f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
                    )
                else:
                    xpath = (
                        f"//*[contains(text(),'{label}')]//following-sibling::i"
                        f"[contains(@class,'el-icon-close')"
                        f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                        f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
                    )
                steps.append({
                    'desc': f'点击「{label}」的关闭按钮',
                    'keyword': 'click_element',
                    'params': {'locator': f'xpath={xpath}'},
                })
            else:
                # 无标签：生成通用 XPath（KB 模板 pattern[1] + 隐藏过滤）
                if self._framework == 'ant-design':
                    xpath = (
                        "//span[contains(@class,'ant-modal-close-x') or contains(@class,'ant-drawer-close')"
                        " and not(ancestor-or-self::*[contains(@class,'ant-drawer-hidden')])"
                        " and not(ancestor-or-self::*[contains(@class,'ant-modal-hidden')])"
                        " and not(ancestor-or-self::*[contains(@style,'display: none')])]"
                    )
                else:
                    xpath = (
                        "//i[contains(@class,'el-icon-close')"
                        " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
                        " and not(ancestor-or-self::*[contains(@style,'display: none')])]"
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

