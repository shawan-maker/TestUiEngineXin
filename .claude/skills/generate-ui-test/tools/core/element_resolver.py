#!/usr/bin/env python3
"""
_element_resolver.py — 元素解析器：从 discovery JSON 构建 (group, field) → locator 映射。

组名构建的**唯一真相源** — 其他模块禁止自行拼接组名。

来源（重构自）：
  - generate_pages_from_probe.py: _classify_element_to_group(), generate_from_discovery()
  - generate_cases_from_excel.py: _build_discovery_maps(), _find_group_for_container(),
    make_pending_ref(), _elem_to_ref()

职责：
  1. 加载 discovery JSON → 构建 element_map + trigger_map + group_map
  2. 提供 get_group_name() 作为组名构建的唯一入口
  3. 容器指纹去重 + trigger alias 映射
  4. 创建 pending 引用（[待确认] 占位）
  5. 将 discovery 元素解析为 ${group.field} 引用
"""

import json
import os
import re
import sys
from collections import OrderedDict

# Ensure tools/ is on sys.path for cross-module imports
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

# ─── 共享导入 ───
from core.field_suffixes import (
    label_to_key as _label_to_key,
    trigger_to_key as _trigger_to_key,
    normalize_label as _normalize_label,
    SUFFIX_MAP as _SUFFIX_MAP,
    _STEP_TYPE_ALIASES as _STEP_TYPE_ALIASES,
    STANDARD_SUFFIXES as _STANDARD_SUFFIXES,
)

# 待确认占位 locator
PENDING_LOCATOR = 'xpath=[待确认]'


# ─── 数据类 ───

class ElementEntry:
    """元素条目：一个 discovery 元素的完整信息。"""
    __slots__ = ('group', 'field', 'locator', 'label', 'verified',
                 'container_type', 'trigger', 'from_expand',
                 'select_options', 'companion_fields',
                 'elem_type', 'raw', 'iframe_context')  # iframe 支持

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    def __repr__(self):
        return f'ElementEntry(group={self.group!r}, field={self.field!r})'


# ─── 主类 ───

class ElementResolver:
    """从 discovery JSON 构建元素映射，提供组名查询接口。"""

    def __init__(self, discovery_paths, project_dir=None):
        """加载 discovery JSON，构建全量元素映射。

        Args:
            discovery_paths: discovery JSON 文件路径列表
            project_dir: 项目根目录（用于读取 container_aliases.json）
        """
        self._module_slug = None
        self._cn_name = None
        self._element_map = {}      # {(context_key, label): ElementEntry} — 向后兼容
        self._page_element_map = {}  # {(page_slug, context_key, label): ElementEntry} — 多URL精确索引
        self._trigger_map = {}      # {button_text: container_entry}
        self._group_map = {}        # {group_name: {field_key: ElementEntry}}
        self._page_url_map = {}     # {slug: {url, groups}}
        self._container_aliases = {}  # {alias_trigger: canonical_trigger}
        self._alias_map = {}        # {trigger: group_name}
        self._from_expand = {}      # {group_name: set(labels)}
        self._discovery_raw = {}    # {path: raw_discovery_dict} — 保留原始数据

        self._load_discovery(discovery_paths)
        if project_dir:
            self._load_container_aliases(project_dir)

    # ═══════════════════════════════════════════════════════════════
    # 公共接口
    # ═══════════════════════════════════════════════════════════════

    def get_group_name(self, module, page_slug=None,
                       container_type=None, trigger=None):
        """构建标准组名（唯一的组名构建入口）。

        单 URL 模块（page_slug=None）：
          列表页:     {module}_elements
          容器内:     {module}_{ct}_{trigger}_elements
          导航新页面: {module}_newpage_{trigger}_elements

        多 URL 模块（page_slug 有值）：
          列表页:     {module}_{page_slug}_elements
          容器内:     {module}_{page_slug}_{ct}_{trigger}_elements
          导航新页面: {module}_{page_slug}_newpage_{trigger}_elements

        Args:
            module: 模块 slug（如 'question'）
            page_slug: 页面 slug（多 URL 模式），单 URL 传 None
            container_type: 容器类型（'drawer'/'dialog'/'message-box'/None）
            trigger: 触发按钮文本

        Returns: str — 标准组名
        """
        module = module.replace('-', '_')

        if container_type is None and trigger is None:
            # 列表页
            if page_slug:
                return f'{module}_{page_slug}_elements'
            return f'{module}_elements'

        trigger_key = _trigger_to_key(trigger) if trigger else 'unknown'

        if container_type is None:
            # navigation（新页面）
            if page_slug:
                return f'{module}_{page_slug}_newpage_{trigger_key}_elements'
            return f'{module}_newpage_{trigger_key}_elements'

        # 容器内元素
        ct_prefix = {'drawer': 'drawer', 'dialog': 'dialog',
                     'message-box': 'messagebox'}.get(container_type, container_type)
        if page_slug:
            return f'{module}_{page_slug}_{ct_prefix}_{trigger_key}_elements'
        return f'{module}_{ct_prefix}_{trigger_key}_elements'

    def find_element(self, context_key, label):
        """按 (context_key, label) 查找元素。

        Args:
            context_key: 上下文标识（'list_page' 或触发按钮文本）
            label: 元素中文标签

        Returns: ElementEntry 或 None
        """
        return self._element_map.get((context_key, label))

    def find_detail_link(self, groups=None):
        """在指定组范围内搜索 first_desc_link 字段。

        Args:
            groups: 限定搜索的组名列表，None=搜索全部

        Returns: (group_name, field_key, locator) 或 None
        """
        search_groups = groups or list(self._group_map.keys())
        for gname in search_groups:
            fields = self._group_map.get(gname, {})
            for fkey, entry in fields.items():
                if fkey.endswith('_link') or fkey.endswith('_row_link'):
                    if entry.locator and entry.locator != PENDING_LOCATOR:
                        return (gname, fkey, entry.locator)
        return None

    def find_group_for_container(self, trigger, container_type=None,
                                  module_slug=None):
        """按容器类型+触发器查找对应组名。

        优先级：
          1. alias_map 中 trigger 对应的 group
          2. trigger_map 中 trigger 对应的容器 → 构建 group_name
          3. 同 container_type 的任何 group（module_hint 匹配优先）
          4. 任何有容器前缀的 group
          5. 兜底：第一个非 common group

        Args:
            trigger: 触发按钮文本
            container_type: 容器类型
            module_slug: 模块 slug（用于限定搜索范围）

        Returns: group_name 或 None
        """
        # 1. alias_map 直接查找
        if trigger and trigger in self._alias_map:
            return self._alias_map[trigger]

        # 2. trigger_map → 构建 group_name
        if trigger and trigger in self._trigger_map:
            container = self._trigger_map[trigger]
            ct = container.get('container_type', container_type)
            result_type = container.get('result_type', '')
            if result_type == 'navigation':
                return self.get_group_name(
                    module_slug or self._module_slug, trigger=trigger)
            if ct:
                return self.get_group_name(
                    module_slug or self._module_slug,
                    container_type=ct, trigger=trigger)

        # 3. 按 container_type 在 group_map 中搜索
        if container_type:
            ct_markers = {
                'drawer': 'el-drawer',
                'dialog': 'el-dialog',
                'message-box': 'el-message-box',
                # Ant Design
                'ant-drawer': 'ant-drawer',
                'ant-modal': 'ant-modal',
            }
            marker = ct_markers.get(container_type, container_type)
            # 优先匹配同模块的 group
            for gname in self._group_map:
                if gname == 'common_elements':
                    continue
                if module_slug and module_slug not in gname:
                    continue
                # 检查 group 中是否有包含容器标记的 locator
                for entry in self._group_map[gname].values():
                    if entry.locator and marker in str(entry.locator):
                        return gname

        # 4. 任何有容器前缀的 group（R6: 加 module_slug 过滤）
        _any_container_markers = ('el-drawer', 'el-dialog', 'el-message-box',
                                  'ant-drawer', 'ant-modal')
        _module_prefix = module_slug.replace('-', '_') if module_slug else None
        for gname in self._group_map:
            if gname == 'common_elements':
                continue
            if _module_prefix and not gname.startswith(_module_prefix):
                continue  # R6: skip cross-module groups
            for entry in self._group_map[gname].values():
                if entry.locator and any(m in str(entry.locator)
                                         for m in _any_container_markers):
                    return gname

        # 5. 兜底：第一个非 common group（R6: 加 module_slug 过滤）
        for gname in self._group_map:
            if gname != 'common_elements':
                if _module_prefix and not gname.startswith(_module_prefix):
                    continue  # R6: skip cross-module groups
                return gname

        return None

    def construct_pending_group(self, container_type, module,
                                 trigger=None, page_slug=None):
        """discovery 无记录时，构造标准组名（与 get_group_name 同一逻辑）。

        Returns: group_name
        """
        return self.get_group_name(
            module or self._module_slug or 'common',
            page_slug=page_slug,
            container_type=container_type,
            trigger=trigger)

    def make_pending_ref(self, label, step_type, container_type=None,
                          module_slug=None):
        """创建 [待确认] 占位引用。

        替代旧 PagesIndex.make_pending_ref()，保证组名来自同一入口。

        Args:
            label: 中文标签
            step_type: 步骤类型 (fill/click_btn/el_select 等)
            container_type: 容器类型 (drawer/dialog/None)
            module_slug: 模块 slug

        Returns: ('${group.field}' 引用, field_key) 或 (None, None)
        """
        # 1. 确定目标 group
        group_name = self.find_group_for_container(
            trigger=None, container_type=container_type,
            module_slug=module_slug)
        if not group_name:
            group_name = self.construct_pending_group(
                container_type, module_slug or self._module_slug)

        # 2. 在 group_map 中查找已有 key（Fix-R431 逻辑）
        _effective_type = step_type if step_type != 'fill' else 'input'
        _preferred_suffix = (
            _SUFFIX_MAP.get(_effective_type)
            or _SUFFIX_MAP.get(_effective_type.replace('_', '-'))
            or _SUFFIX_MAP.get(_STEP_TYPE_ALIASES.get(_effective_type, ''))
        )
        existing_key = self._lookup_existing_key(
            group_name, label, _preferred_suffix)
        if existing_key:
            ref = f'${{{group_name}.{existing_key}}}'
            return ref, existing_key

        # 3. 生成 field key
        field_key = _label_to_key(
            label, step_type if step_type != 'fill' else 'input',
            container_type=container_type,
            skip_container_prefix=bool(container_type))

        # 4. 避免覆盖已有非占位条目
        if group_name in self._group_map:
            existing = self._group_map[group_name].get(field_key)
            if existing and existing.locator != PENDING_LOCATOR:
                return None, None

        # 5. 创建 pending 占位
        if group_name not in self._group_map:
            self._group_map[group_name] = {}
        self._group_map[group_name][field_key] = ElementEntry(
            group=group_name, field=field_key,
            locator=PENDING_LOCATOR, label=label)

        ref = f'${{{group_name}.{field_key}}}'
        return ref, field_key

    def resolve_ref(self, discovery_element):
        """将 discovery 元素转为 ${group.field} 引用。

        替代旧 CaseGenerator._elem_to_ref()。
        从 discovery 元素的 group_name/field_key 字段构建引用，
        并验证该字段在 group_map 中存在（F-D 安全检查）。

        Args:
            discovery_element: discovery JSON 中的元素 dict
                （需含 group_name, field_key 字段）

        Returns: '${group.field}' 引用 或 None
        """
        if not discovery_element:
            return None
        group = discovery_element.get('group_name', '')
        field = discovery_element.get('field_key', '')
        if not group or not field:
            return None

        # F-D: 验证 key 存在于声称的 group 中
        if group in self._group_map and field in self._group_map[group]:
            return f'${{{group}.{field}}}'

        # key 不在声称的 group — 搜索所有 groups
        for gname, fields in self._group_map.items():
            if field in fields:
                return f'${{{gname}.{field}}}'

        return None

    def get_element_map(self):
        """返回全量元素映射（只读）。

        Returns: {(context_key, label): ElementEntry}
        """
        return self._element_map

    def get_page_element_map(self):
        """返回按 page_slug 索引的全量元素映射（只读）。

        Returns: {(page_slug, context_key, label): ElementEntry}
        """
        return self._page_element_map

    def find_element_by_page(self, page_slug, context_key, label):
        """按 page_slug 精确查找元素，回退到无 page_slug 的 element_map。

        Args:
            page_slug: 页面标识（从 URL 提取）
            context_key: 上下文标识（'list_page' 或触发按钮文本）
            label: 元素标签

        Returns: ElementEntry 或 None
        """
        entry = self._page_element_map.get((page_slug, context_key, label))
        if entry:
            return entry
        # 回退：单 URL 模块或 page_slug 不匹配时
        return self._element_map.get((context_key, label))

    def url_to_page_slug(self, url):
        """从 URL 反查 page_slug。

        Args:
            url: 完整 URL

        Returns: page_slug 或 None
        """
        if not url:
            return None
        for slug, meta in self._page_url_map.items():
            meta_url = meta.get('url', '')
            if meta_url and meta_url in url:
                return slug
        return None

    def get_groups(self):
        """返回全量分组映射（只读）。

        Returns: {group_name: {field_key: ElementEntry}}
        """
        return self._group_map

    def get_alias_map(self):
        """返回容器 trigger alias 映射。

        Returns: {trigger_text: group_name}
        """
        return self._alias_map

    def get_from_expand(self, group_name):
        """返回指定组中来自"更多"展开按钮的元素标签集合。

        Returns: set of label strings
        """
        return self._from_expand.get(group_name, set())

    def get_page_url_map(self):
        """返回 URL → groups 映射。

        Returns: {slug: {url, groups}}
        """
        return self._page_url_map

    def get_trigger_map(self):
        """返回 trigger → container entry 映射。

        Returns: {button_text: container_entry_dict}
        """
        return self._trigger_map

    @property
    def module_slug(self):
        """模块 slug"""
        return self._module_slug

    @property
    def cn_name(self):
        """模块中文名"""
        return self._cn_name

    def validate_groups(self):
        """跨组一致性验证。

        替代旧 _self_check_groups()。
        检查 R4.27（同名跨容器冲突）、R4.28（通用按钮容器前缀）、
        R4.38（后缀标准）、R4.58（后缀校验）。

        Returns: list of {rule, action, detail} dicts
        """
        sc_log = []

        # R4.27: 检测同名字段跨容器冲突
        field_to_groups = {}
        for gname, gfields in self._group_map.items():
            for field in gfields:
                field_to_groups.setdefault(field, set()).add(gname)

        for field, gnames in field_to_groups.items():
            if len(gnames) > 1:
                sc_log.append({
                    'rule': 'R4.27',
                    'action': 'warning',
                    'detail': f'字段 {field} 在 {len(gnames)} 个 group 中重复: '
                              f'{sorted(gnames)}',
                })

        # R4.28: 通用按钮检查容器前缀
        _GENERIC_BTNS = {'confirm_btn', 'cancel_btn', 'ok_btn', 'delete_btn',
                         'save_btn', 'submit_btn'}
        for gname, gfields in self._group_map.items():
            if 'search_elements' in gname:
                for btn in _GENERIC_BTNS & set(gfields.keys()):
                    entry = gfields[btn]
                    if entry.locator and any(c in str(entry.locator) for c in
                            ('el-dialog', 'el-drawer', 'el-message-box',
                             'ant-modal', 'ant-drawer')):
                        sc_log.append({
                            'rule': 'R4.28',
                            'action': 'warning',
                            'detail': f'{gname}.{btn} 的 locator 包含容器前缀，'
                                      f'建议移到对应的容器 group',
                        })

        # R4.58: 字段名标准后缀校验
        for gname, gfields in self._group_map.items():
            for field in gfields:
                if field.startswith(('common_', 'detail_', '_')):
                    continue
                if not any(field.endswith(s) for s in _STANDARD_SUFFIXES):
                    sc_log.append({
                        'rule': 'R4.58',
                        'action': 'info',
                        'detail': f'{gname}.{field} 缺少标准后缀',
                    })

        # R4.38: 确认按钮容器路由（同 group 不混用 drawer/dialog class）
        for gname, gfields in self._group_map.items():
            drawer_count = 0
            dialog_count = 0
            for entry in gfields.values():
                if not entry.locator:
                    continue
                loc = str(entry.locator)
                if 'el-drawer' in loc or 'ant-drawer' in loc:
                    drawer_count += 1
                elif 'el-dialog' in loc or 'ant-modal' in loc:
                    dialog_count += 1
            if drawer_count and dialog_count:
                sc_log.append({
                    'rule': 'R4.38',
                    'action': 'warning',
                    'detail': f'{gname} 混用容器类型: '
                              f'drawer({drawer_count}) + dialog({dialog_count})',
                })

        if sc_log:
            print(f"\n[SELF-CHECK] ElementResolver 自检: {len(sc_log)} 项")
            for item in sc_log[:5]:
                print(f"  [{item['rule']}] {item['detail']}")
            if len(sc_log) > 5:
                print(f"  ... 还有 {len(sc_log) - 5} 项")

        return sc_log

    def get_required_fields_from_refs(self, refs):
        """从 ${group.field} 引用集合提取 required_fields 结构。

        Args:
            refs: {'group.field', ...} 集合

        Returns: {(group, field): {locator, label, comment}}
        """
        result = {}
        for ref in refs:
            parts = ref.split('.', 1)
            if len(parts) != 2:
                continue
            group, field = parts
            if group in self._group_map and field in self._group_map[group]:
                entry = self._group_map[group][field]
                result[(group, field)] = {
                    'locator': entry.locator or PENDING_LOCATOR,
                    'label': entry.label or '',
                    'comment': f'  # {entry.label}' if entry.label else '',
                }
            else:
                # 引用了不存在的字段 → pending
                result[(group, field)] = {
                    'locator': PENDING_LOCATOR,
                    'label': '',
                    'comment': '  # [待确认]',
                }
        return result

    # ═══════════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════════

    def _load_discovery(self, discovery_paths):
        """加载所有 discovery JSON，构建全量映射。

        合并旧 _build_discovery_maps() + generate_from_discovery() 的
        组名构建 + 指纹去重 + alias 映射 + from_expand + page_url_metadata。
        """
        if isinstance(discovery_paths, str):
            discovery_paths = [discovery_paths]

        for path in discovery_paths:
            if not os.path.isfile(path):
                print(f"[WARN] discovery 文件不存在: {path}")
                continue

            with open(path, encoding='utf-8') as f:
                discovery = json.load(f)

            self._discovery_raw[path] = discovery
            self._module_slug = discovery.get('module', '')
            self._cn_name = discovery.get('cn_name', '')

            # 支持 pages[] 多 URL 格式
            pages_array = discovery.get('pages', [])
            if not pages_array:
                pages_array = [{
                    'list_page': discovery.get('list_page', {}),
                    'containers': discovery.get('containers', []),
                    'name': 'default',
                }]

            multi_page = len(pages_array) > 1
            # 检查实际有元素的页面数
            _pages_with_elements = 0
            for _p in pages_array:
                _lp = _p.get('list_page', {})
                _conts = _p.get('containers', [])
                _has = any(_lp.get(cat) for cat in
                           ['buttons', 'row_buttons', 'inputs', 'tabs',
                            'detail_links', 'checkboxes', 'menu_items'])
                _has = _has or any(c.get('elements') for c in _conts)
                if _has:
                    _pages_with_elements += 1
            multi_page = multi_page and _pages_with_elements > 1

            # G3: 全局容器指纹（跨页面去重）
            container_fingerprints = OrderedDict()

            for _page_idx, page_entry in enumerate(pages_array):
                page_slug = None
                if multi_page:
                    page_name = page_entry.get('name', f'page_{_page_idx}')
                    page_slug = re.sub(r'[^a-zA-Z0-9_]', '_',
                                       page_name).strip('_').lower()
                    if not page_slug:
                        page_slug = f'page_{_page_idx}'

                # G4: 构建 page_url_metadata
                page_url = page_entry.get(
                    'url', page_entry.get('list_page', {}).get('url', ''))
                url_path = page_url.split('#')[-1] if '#' in page_url else page_url
                main_group = self.get_group_name(self._module_slug, page_slug)
                _meta_key = page_slug or self._module_slug
                self._page_url_map[_meta_key] = {
                    'url': url_path,
                    'groups': [main_group],
                }

                # Build trigger map
                for container in page_entry.get('containers', []):
                    trigger = container.get('trigger', '')
                    if trigger and container.get('result_type') in (
                            'container', 'navigation', 'inline', 'skipped'):
                        self._trigger_map[trigger] = container

                # Build element map for list_page
                list_page = page_entry.get('list_page', {})
                self._build_element_map_from_section(
                    list_page, 'list_page', page_slug)

                # Build element map for each container
                for container in page_entry.get('containers', []):
                    trigger = container.get('trigger', '')
                    if not trigger:
                        continue
                    for elem in container.get('elements', []):
                        self._register_element(
                            elem, trigger, page_slug, container)

                # G5: from_expand 追踪（toolbar + row buttons）
                for btn in list_page.get('buttons', []) + list_page.get('row_buttons', []):
                    if btn.get('from_expand'):
                        text = btn.get('text', '')
                        if text:
                            self._from_expand.setdefault(
                                main_group, set()).add(text)

                # G3: 容器指纹去重 + alias 收集
                for container in page_entry.get('containers', []):
                    trigger = container.get('trigger', '')
                    ct = container.get('container_type')
                    elements = container.get('elements', [])
                    result_type = container.get('result_type', '')
                    if not elements or not trigger:
                        continue

                    if result_type == 'navigation':
                        # navigation: 不参与指纹去重
                        group_name = self.get_group_name(
                            self._module_slug, page_slug, trigger=trigger)
                        self._register_container_entries(
                            elements, group_name, trigger, page_slug)
                        self._alias_map[trigger] = group_name
                        # 追加到 page_url_map
                        meta = self._page_url_map.get(_meta_key)
                        if meta and group_name not in meta['groups']:
                            meta['groups'].append(group_name)
                        continue

                    if ct is None or ct not in ('drawer', 'dialog', 'message-box'):
                        if ct is not None:
                            print(f"[WARN] 跳过非标准容器类型: {ct} "
                                  f"(trigger: {trigger}), "
                                  f"{len(elements)} 个元素被丢弃")
                        continue

                    entries = self._build_entries_from_elements(
                        elements, ct, trigger, page_slug)
                    if not entries:
                        continue

                    fingerprint = self._compute_fingerprint(entries)
                    if fingerprint in container_fingerprints:
                        existing_name, aliases, expand = \
                            container_fingerprints[fingerprint]
                        aliases.append(trigger)
                        # 更新 from_expand
                        for e in elements:
                            if e.get('from_expand'):
                                expand.add(e.get('label', e.get('text', '')))
                    else:
                        group_name = self.get_group_name(
                            self._module_slug, page_slug, ct, trigger)
                        container_fingerprints[fingerprint] = (
                            group_name, [trigger], set())
                        # 将 entries 注册到 group_map
                        self._group_map.setdefault(group_name, {})
                        for fkey, entry in entries.items():
                            self._group_map[group_name][fkey] = entry

                    # 追加到 page_url_map
                    meta = self._page_url_map.get(_meta_key)
                    if meta:
                        ct_group = container_fingerprints[fingerprint][0]
                        if ct_group not in meta['groups']:
                            meta['groups'].append(ct_group)

            # G3: 将去重结果写入 alias_map
            for fp, (group_name, aliases, expand_set) in \
                    container_fingerprints.items():
                for alias in aliases:
                    self._alias_map[alias] = group_name
                if expand_set:
                    self._from_expand.setdefault(
                        group_name, set()).update(expand_set)

    def _build_element_map_from_section(self, section, context_key, page_slug):
        """从 list_page 或 container section 构建 element_map 条目。

        Audit fixes (ported from generate-pages-grouping-audit.md):
          GAP-1: toolbar/row buttons processed separately → _row suffix
          GAP-2: tab['tab_elements'] traversed → panel elements registered
        """
        # GAP-1 fix: toolbar buttons first (no _row suffix)
        for btn in section.get('buttons', []):
            text = btn.get('text', '')
            if text and btn.get('locator'):
                self._register_element(btn, context_key, page_slug)

        # GAP-1 fix: row buttons second, with _row suffix to prevent collision
        for btn in section.get('row_buttons', []):
            text = btn.get('text', '')
            if text and btn.get('locator'):
                if 'field_key' not in btn and '_field_key' not in btn:
                    elem_type = btn.get('type', 'button')
                    base_key = _label_to_key(text, elem_type)
                    if not base_key.endswith('_row'):
                        btn['field_key'] = f'{base_key}_row'
                self._register_element(btn, context_key, page_slug)

        for inp in section.get('inputs', []):
            label = inp.get('label', '')
            if label and inp.get('locator'):
                self._register_element(inp, context_key, page_slug)

        # GAP-2 fix: register tab buttons + tab panel elements
        for tab in section.get('tabs', []):
            label = tab.get('label', tab.get('text', ''))
            if label and tab.get('locator'):
                self._register_element(tab, context_key, page_slug)

            # Process elements inside tab panels (tab_elements structure
            # mirrors list_page: {buttons, row_buttons, inputs, ...})
            tab_elems = tab.get('tab_elements', {})
            if not tab_elems:
                continue
            _seen_tab_desc_link = False
            for cat in ('buttons', 'inputs', 'detail_links',
                        'checkboxes', 'menu_items'):
                for elem in tab_elems.get(cat, []):
                    elabel = (elem.get('label', '') or
                              elem.get('text', ''))
                    if elabel and elem.get('locator'):
                        # 修改 1: tab 内 detail-link 也用 first_desc_link
                        if (cat == 'detail_links'
                                and not _seen_tab_desc_link
                                and 'field_key' not in elem):
                            elem['type'] = 'detail_link'
                            elem['field_key'] = 'first_desc_link'
                            _seen_tab_desc_link = True
                        self._register_element(
                            elem, context_key, page_slug)
            # Row buttons inside tabs — apply _row suffix (GAP-1)
            for elem in tab_elems.get('row_buttons', []):
                elabel = (elem.get('label', '') or
                          elem.get('text', ''))
                if elabel and elem.get('locator'):
                    if 'field_key' not in elem and '_field_key' not in elem:
                        elem_type = elem.get('type', 'button')
                        base_key = _label_to_key(elabel, elem_type)
                        if not base_key.endswith('_row'):
                            elem['field_key'] = f'{base_key}_row'
                    self._register_element(
                        elem, context_key, page_slug)

        # 修改 1: detail-link 统一注册为 first_desc_link（仅第一个）
        _seen_first_desc_link = False
        for link in section.get('detail_links', []):
            label = link.get('label', link.get('text', ''))
            if label and link.get('locator'):
                if not _seen_first_desc_link:
                    link['type'] = 'detail_link'
                    link['field_key'] = 'first_desc_link'
                    _seen_first_desc_link = True
                self._register_element(link, context_key, page_slug)

        for cb in section.get('checkboxes', []):
            label = cb.get('label', cb.get('text', ''))
            if label and cb.get('locator'):
                self._register_element(cb, context_key, page_slug)

        for mi in section.get('menu_items', []):
            label = mi.get('label', mi.get('text', ''))
            if label and mi.get('locator'):
                self._register_element(mi, context_key, page_slug)

    def _register_element(self, elem, context_key, page_slug=None,
                           container=None):
        """注册单个元素到 element_map + group_map。

        方案 C: 透传 _group_name/_field_key → group_name/field_key。
        """
        # 方案 C: 规范化下划线前缀字段
        if '_group_name' in elem and 'group_name' not in elem:
            elem['group_name'] = elem['_group_name']
        if '_field_key' in elem and 'field_key' not in elem:
            elem['field_key'] = elem['_field_key']

        label = elem.get('label', '') or elem.get('text', '')
        locator = elem.get('locator', '')
        if not label or not locator:
            return

        group = elem.get('group_name', '')
        field = elem.get('field_key', '')

        if not group or not field:
            # 没有 Scheme C 注入的 group/field — 从 context 推断
            ct = None
            trigger = None
            if container:
                ct = container.get('container_type')
                trigger = container.get('trigger', '')
                result_type = container.get('result_type', '')
                if result_type == 'navigation':
                    ct = None  # navigation 不传 container_type

            if not group:
                group = self.get_group_name(
                    self._module_slug, page_slug, ct, trigger)
            if not field:
                elem_type = elem.get('type', 'input')
                field = _label_to_key(
                    label, elem_type,
                    container_type=ct,
                    skip_container_prefix=bool(ct))

        # 写回 raw dict，确保 entry.raw 含 group_name/field_key（resolve_ref 需要）
        elem['group_name'] = group
        elem['field_key'] = field

        entry = ElementEntry(
            group=group,
            field=field,
            locator=locator,
            label=label,
            verified=elem.get('verified', False),
            container_type=elem.get('container_type'),
            trigger=context_key if context_key != 'list_page' else None,
            from_expand=elem.get('from_expand', False),
            select_options=elem.get('select_options'),
            elem_type=elem.get('type', ''),
            raw=elem,
            iframe_context=elem.get('iframe_context'),  # iframe 支持
        )

        # 注册到 element_map（向后兼容）
        self._element_map[(context_key, label)] = entry

        # 注册到 page_element_map（多URL精确索引）
        self._page_element_map[(page_slug, context_key, label)] = entry

        # 注册到 group_map
        self._group_map.setdefault(group, {})
        self._group_map[group][field] = entry

    def _register_container_entries(self, elements, group_name, trigger,
                                     page_slug=None):
        """为 navigation 容器注册元素到 group_map。"""
        self._group_map.setdefault(group_name, {})
        for elem in elements:
            label = elem.get('label', '') or elem.get('text', '')
            locator = elem.get('locator', '')
            if not label or not locator:
                continue

            # 方案 C
            if '_group_name' in elem and 'group_name' not in elem:
                elem['group_name'] = elem['_group_name']
            if '_field_key' in elem and 'field_key' not in elem:
                elem['field_key'] = elem['_field_key']

            field = elem.get('field_key', '')
            if not field:
                elem_type = elem.get('type', 'input')
                field = _label_to_key(label, elem_type)

            # 写回 raw dict（resolve_ref 需要）
            elem['group_name'] = group_name
            elem['field_key'] = field

            entry = ElementEntry(
                group=group_name,
                field=field,
                locator=locator,
                label=label,
                verified=elem.get('verified', False),
                trigger=trigger,
                from_expand=elem.get('from_expand', False),
                select_options=elem.get('select_options'),
                elem_type=elem.get('type', ''),
                raw=elem,
            )
            self._group_map[group_name][field] = entry
            self._element_map[(trigger, label)] = entry
            self._page_element_map[(page_slug, trigger, label)] = entry

    def _build_entries_from_elements(self, elements, container_type, trigger,
                                      page_slug=None):
        """从容器元素列表构建 {field_key: ElementEntry} 字典。"""
        group_name = self.get_group_name(
            self._module_slug, page_slug, container_type, trigger)
        entries = OrderedDict()
        for elem in elements:
            label = elem.get('label', '') or elem.get('text', '')
            locator = elem.get('locator', '')
            if not label or not locator:
                continue

            # 方案 C
            if '_group_name' in elem and 'group_name' not in elem:
                elem['group_name'] = elem['_group_name']
            if '_field_key' in elem and 'field_key' not in elem:
                elem['field_key'] = elem['_field_key']

            field = elem.get('field_key', '')
            if not field:
                elem_type = elem.get('type', 'input')
                field = _label_to_key(
                    label, elem_type,
                    container_type=container_type,
                    skip_container_prefix=True)

            # 写回 raw dict（resolve_ref 需要）
            elem['group_name'] = group_name
            elem['field_key'] = field

            entry = ElementEntry(
                group=group_name,
                field=field,
                locator=locator,
                label=label,
                verified=elem.get('verified', False),
                container_type=container_type,
                trigger=trigger,
                from_expand=elem.get('from_expand', False),
                select_options=elem.get('select_options'),
                elem_type=elem.get('type', ''),
                raw=elem,
            )
            entries[field] = entry
        return entries

    def _compute_fingerprint(self, entries):
        """容器内容指纹 — 用于去重相同内容的容器。

        指纹包含 key=locator[:50]，避免 key 相同但 locator 不同的容器被误合并。
        """
        parts = []
        for k, entry in sorted(entries.items()):
            loc = str(entry.locator)[:50] if entry.locator else ''
            parts.append(f'{k}={loc}')
        return '|'.join(parts)

    def _lookup_existing_key(self, group_name, label, preferred_suffix=None):
        """Fix-R431: 在 group 中查找同 label 已有 key。

        优先匹配带 preferred_suffix 的 key，避免回退到通用 _field 后缀。
        """
        fields = self._group_map.get(group_name, {})
        if not fields:
            return None

        normalized = _normalize_label(label)
        if not normalized:
            return None

        # 1. 精确匹配：相同 label 的 entry
        for fkey, entry in fields.items():
            if entry.label and _normalize_label(entry.label) == normalized:
                # 优先返回带 preferred_suffix 的
                if preferred_suffix and fkey.endswith(preferred_suffix):
                    return fkey

        # 2. 再找一次，不限后缀
        for fkey, entry in fields.items():
            if entry.label and _normalize_label(entry.label) == normalized:
                return fkey

        return None

    def _load_container_aliases(self, project_dir):
        """加载 _probe/container_aliases.json，注册别名映射。

        解决指纹合并后别名触发按钮在 discovery 查找中 miss 的问题。
        """
        alias_path = os.path.join(project_dir, '_probe', 'container_aliases.json')
        if not os.path.isfile(alias_path):
            return

        try:
            with open(alias_path, encoding='utf-8') as f:
                alias_data = json.load(f)
        except Exception as e:
            print(f"  [WARN] 读取别名映射失败: {e}")
            return

        aliases = alias_data.get('aliases', {})
        registered = 0
        for alias_trigger, info in aliases.items():
            canonical = info.get('canonical', '')
            if not canonical:
                continue

            self._container_aliases[alias_trigger] = canonical

            # 复制 canonical 的 trigger_map 条目给 alias
            if canonical in self._trigger_map and \
                    alias_trigger not in self._trigger_map:
                self._trigger_map[alias_trigger] = self._trigger_map[canonical]

            # 复制 canonical 的 page_element_map 条目（多URL精确索引）
            for (ps, ctx, lbl), elem in list(self._page_element_map.items()):
                if ctx == canonical and \
                        (ps, alias_trigger, lbl) not in self._page_element_map:
                    self._page_element_map[(ps, alias_trigger, lbl)] = elem
                    registered += 1
                    # 同步到 element_map（向后兼容）
                    if (alias_trigger, lbl) not in self._element_map:
                        self._element_map[(alias_trigger, lbl)] = elem

            # 注册 alias_map
            if canonical in self._alias_map:
                self._alias_map[alias_trigger] = self._alias_map[canonical]

        if registered:
            print(f"  [G1] 别名注册: {len(aliases)} 个别名触发按钮, "
                  f"{registered} 条 element_map 条目")
