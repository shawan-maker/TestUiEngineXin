#!/usr/bin/env python3
"""
_pages_writer.py — Pages YAML 写入器：将 required_fields 格式化为 pages YAML。

支持 R4.11 隐藏过滤注入、el-select option 生成、容器作用域前缀、
companion 字段自动补全（_select/_input/_editable/_first_option）。

来源（重构自）：
  - generate_pages_from_probe.py: write_yaml_with_comments(),
    _write_yaml_with_comments(), _build_discovery_group_entries(),
    generate_option_locators(), extract_verified_locators(),
    _fix_el_select_div_to_input(), _make_editable_locator(),
    _add_container_prefix()

职责：
  1. 从 required_fields 按需写入 pages YAML
  2. R4.11 隐藏过滤注入
  3. el-select companion 字段 + option locator 生成
  4. 容器作用域前缀注入
  5. common_elements 固定模板写入
  6. page_urls 元数据写入
"""

import os
import re
import sys
from collections import OrderedDict

# Ensure tools/ is on sys.path for cross-module imports
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

# ─── 共享导入 ───
from core.yaml_utils import escape_yaml_scalar as _yaml_scalar
from core.xpath_utils import (
    inject_hidden_filter as _inject_hidden_filter,
    has_hidden_filter as _has_hidden_filter,
)
from core.element_types import normalize_type as _normalize_type, infer_type_from_field as _infer_type_from_field

try:
    from ..probe.probe_utils import _xpath_escape_label, _safe_format, get_kb_patterns
except ImportError:
    _xpath_escape_label = None
    _safe_format = None
    get_kb_patterns = None

try:
    import yaml
except ImportError:
    yaml = None


# ═══════════════════════════════════════════════════════════════════
# 模块级常量（从 generate_pages_from_probe.py 迁移）
# ═══════════════════════════════════════════════════════════════════

# el-select 选项 XPath 模板（R4.12 双向面板 + R4.11 隐藏过滤在 li 上）
# 注意：这是 Element UI 默认模板，Ant Design 模板在 PagesWriter.__init__ 中按框架选择
_OPTION_XPATH_TEMPLATE = (
    "(//div[@x-placement and not(@x-placement='')]//"
    "li[{match_expr}"
    " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
    " and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
)

# Ant Design select option 模板
_OPTION_XPATH_TEMPLATE_ANTD = (
    "(//div[contains(@class,'ant-select-dropdown')"
    " and not(contains(@class,'ant-select-dropdown-hidden'))]//"
    "div[contains(@class,'ant-select-item')][{match_expr}"
    " and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
)

# el-select _first_option 通用 XPath（带 hidden filter，排除虚拟滚动隐藏项）
_FIRST_OPTION_XPATH = (
    "(//div[@x-placement and not(@x-placement='')]//"
    "li[contains(@class,'el-select-dropdown__item')"
    " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
    " and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
)

# Ant Design _first_option XPath
_FIRST_OPTION_XPATH_ANTD = (
    "(//div[contains(@class,'ant-select-dropdown')"
    " and not(contains(@class,'ant-select-dropdown-hidden'))]//"
    "div[contains(@class,'ant-select-item')][1])"
)

# 通用定位器模板（Element UI 默认）
DEFAULT_COMMON_ELEMENTS = OrderedDict([
    ('loading_mask', "xpath=//div[contains(@class,'el-loading-mask')]"),
    ('success_text', "xpath=//*[contains(.,'成功')]"),
    ('error_text', "xpath=//*[contains(.,'失败') or contains(.,'错误')]"),
    ('confirm_btn', "xpath=//button[contains(.,'确') and contains(.,'定') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]"),
    ('cancel_btn', "xpath=//button[contains(.,'取') and contains(.,'消') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]"),
])

# Ant Design 通用定位器模板
DEFAULT_COMMON_ELEMENTS_ANTD = OrderedDict([
    ('loading_mask', "xpath=//div[contains(@class,'ant-spin-spinning')]"),
    ('success_text', "xpath=//*[contains(.,'成功')]"),
    ('error_text', "xpath=//*[contains(.,'失败') or contains(.,'错误')]"),
    ('confirm_btn', "xpath=//button[contains(.,'确') and contains(.,'定') and not(ancestor-or-self::*[contains(@style,'display: none')])]"),
    ('cancel_btn', "xpath=//button[contains(.,'取') and contains(.,'消') and not(ancestor-or-self::*[contains(@style,'display: none')])]"),
])

# 正则
_OUTER_WRAP_RE = re.compile(r'^\(.*\)\[(\d+|last\(\))\]$')
_SLUG_UNSAFE_RE = re.compile(r'[^a-zA-Z0-9一-鿿_]+')
_CSS_CLASS_RE = re.compile(r'^\.[-\w]')
_CSS_ID_RE = re.compile(r'^#\w')
_CSS_PREFIX_RE = re.compile(r'^css=', re.I)
_PW_PSEUDO_RE = re.compile(r':(?:has-text|visible|has|is|nth-match)\s*\(')
_CSS_AFTER_CHAIN_RE = re.compile(
    r'>>\s*(?!xpath=)(?!//)(?!text=)(?!role=)(?!\$\{)[a-zA-Z.#\[]'
)
_VALID_PREFIXES = ('xpath=', '//', 'text=', 'role=', '${')

# el-select div→input 修正
_EL_SELECT_DIV_RE = re.compile(
    r"(following-sibling::)(?:div|span|\*\[self::div or self::span\])"
    r"(//div\[contains\(@class,'el-select'\)"
    r"(?:\s+and\s+not\(contains\(@class,'el-select-dropdown'\)\))?\])"
)

# 按钮相关正则
_BTN_FIELD_RE = re.compile(
    r'(btn|button|confirm|cancel|save|submit|close|delete_btn|query|reset|search_btn)',
    re.IGNORECASE
)
_BTN_CONTAINS_TEXT_RE = re.compile(
    r"contains\((?:\.|text\(\)),\s*"
    r"(?:'([^']+)'|concat\((.+?)\))"
    r"\)"
)


# ═══════════════════════════════════════════════════════════════════
# 模块级辅助函数
# ═══════════════════════════════════════════════════════════════════

def _slugify(text):
    """将选项文本转为安全的 key slug（保留中文和字母数字）"""
    s = _SLUG_UNSAFE_RE.sub('_', text).strip('_')
    return s if s else 'opt'


def _make_editable_locator(sel_locator):
    """从 _select locator 生成 _editable locator（加 not(@readonly)）。

    支持 Element UI（el-input__inner）和 Ant Design（ant-input）。
    """
    # Element UI marker
    target_eu = "input[@class='el-input__inner'"
    # Ant Design marker
    target_antd = "input[contains(@class,'ant-input')"

    # 选择匹配的 marker
    target = None
    target_pos = -1
    if target_eu in sel_locator:
        target = target_eu
        target_pos = sel_locator.index(target)
    elif target_antd in sel_locator:
        target = target_antd
        target_pos = sel_locator.index(target)

    if target is None:
        return sel_locator

    after_target = sel_locator[target_pos + len(target):]

    bracket_depth = 1
    close_pos = -1
    for i, ch in enumerate(after_target):
        if ch == '[':
            bracket_depth += 1
        elif ch == ']':
            bracket_depth -= 1
            if bracket_depth == 0:
                close_pos = i
                break

    if close_pos < 0:
        return sel_locator

    abs_close = target_pos + len(target) + close_pos
    return (sel_locator[:abs_close]
            + " and not(@readonly)"
            + sel_locator[abs_close:])


def _make_editable_locator_postfix(sel_locator):
    """从 _select locator 生成 _editable locator（后置 not(@readonly) 检查）。

    与 _make_editable_locator() 的区别：
    - _make_editable_locator: 注入到 input 谓词内部 → (//input[...and not(@readonly)])[1]
    - _make_editable_locator_postfix: 追加到末尾 → (//input[...])[1][not(@readonly)]

    后置模式确保 _editable 与 _select 始终指向同一个 DOM 元素（第 N 个），
    再检查该元素是否可编辑。解决了同一 label 下多个 input 时，
    前置过滤导致 _editable 跳到后面 input 的问题。

    :param sel_locator: _select 字段的完整 locator（已包含 [nth] 包裹）
    :return: 追加 [not(@readonly)] 后的 locator
    """
    if not sel_locator or not isinstance(sel_locator, str):
        return sel_locator
    if 'not(@readonly)' in sel_locator:
        return sel_locator  # 幂等：已包含则不重复追加

    # 检查是否已有 (xpath)[N] 包裹
    if _OUTER_WRAP_RE.match(sel_locator):
        return sel_locator + "[not(@readonly)]"

    # 无包裹 → 先加 (xpath)[1] 再追加 [not(@readonly)]
    return f"({sel_locator})[1][not(@readonly)]"


def _unwrap_positional(xpath):
    """解包 (xpath)[N] 格式，返回 (inner_xpath, wrap_suffix)"""
    m = _OUTER_WRAP_RE.match(xpath)
    if m and xpath.startswith('('):
        wrap = f'[{m.group(1)}]'
        wrap_len = len(wrap) + 1
        inner = xpath[1:-wrap_len]
        return inner, wrap
    return xpath, ''


def _rewrap_positional(xpath, wrap_suffix):
    """重新包裹 (xpath)[N] 格式"""
    if wrap_suffix:
        return f'({xpath}){wrap_suffix}'
    return xpath


# M2: _add_container_prefix / _has_container_prefix 已移除（死代码 — 从未被调用）
# 统一重构到 xpath_utils.apply_container_prefix / has_container_prefix


def fix_el_select_div_to_input(locator):
    """R4.32 安全网 — 独立函数，供 verify_locators.py 导入。

    替代旧的 from generate_pages_from_probe import _fix_el_select_div_to_input。
    """
    had_hidden = _has_hidden_filter(locator)

    def _replace(m):
        return (f"{m.group(1)}*[self::div or self::span]"
                f"//input[@class='el-input__inner']")

    new_loc = _EL_SELECT_DIV_RE.sub(_replace, locator)
    if new_loc != locator:
        if had_hidden and not _has_hidden_filter(new_loc):
            new_loc = _inject_hidden_filter(new_loc)
    return new_loc


# ═══════════════════════════════════════════════════════════════════
# PagesWriter 类
# ═══════════════════════════════════════════════════════════════════

class PagesWriter:
    """从 required_fields + discovery 数据生成 pages YAML。"""

    def __init__(self, element_resolver, framework=None):
        """
        Args:
            element_resolver: ElementResolver 实例（获取 locator 值）
            framework: UI 框架名称（'ant-design' 或 None 默认 Element UI）
        """
        self._resolver = element_resolver
        self._framework = framework
        # 按框架选择模板常量
        if framework == 'ant-design':
            self._option_template = _OPTION_XPATH_TEMPLATE_ANTD
            self._first_option_xpath = _FIRST_OPTION_XPATH_ANTD
            self._common_elements = DEFAULT_COMMON_ELEMENTS_ANTD
        else:
            self._option_template = _OPTION_XPATH_TEMPLATE
            self._first_option_xpath = _FIRST_OPTION_XPATH
            self._common_elements = DEFAULT_COMMON_ELEMENTS

    # ─── 公共接口 ───

    def write_pages_yaml(self, required_fields, output_path,
                          module_slug, cn_name='', append=False):
        """从 required_fields 生成 pages YAML。

        核心变化（vs 旧工具）：
        - 旧：接受全量 discovery 元素 → 写入所有 group/field
        - 新：接受 required_fields → 只写入 case 需要的 group/field

        Args:
            required_fields: {(group, field): {locator, label, comment}}
            output_path: 输出 YAML 路径
            module_slug: 模块 slug
            cn_name: 中文模块名（写入注释）
            append: 是否追加到现有文件
        """
        print(f"  [TRACE] write_pages_yaml: required_fields={len(required_fields)}, output={output_path}, append={append}")
        # 1. 按 group 聚合（过滤 _data 组和 common_elements）
        groups = OrderedDict()
        for (group, field), info in sorted(required_fields.items()):
            # 跳过 data YAML 组（*_data）和 common_elements（由 write_common_elements 处理）
            if group.endswith('_data') or group == 'common_elements':
                continue
            if group not in groups:
                groups[group] = OrderedDict()
            locator = info.get('locator', '')
            comment = info.get('label', '')
            groups[group][field] = (locator, comment)

        # 1.5 M7: xpath= 前缀规范化（裸 XPath 以 // 或 ( 开头时自动补齐）
        for group_name, fields in groups.items():
            for field_key, (locator, comment) in list(fields.items()):
                if isinstance(locator, str) and not locator.startswith(('xpath=', 'text=', 'role=', '${', 'css=', '')):
                    if locator.startswith('//') or locator.startswith('('):
                        fields[field_key] = (f'xpath={locator}', comment)

        # 2. R4.11 隐藏过滤注入
        resolver_groups = self._resolver.get_groups()
        for group_name, fields in groups.items():
            resolver_fields = resolver_groups.get(group_name, {})
            for field_key, (locator, comment) in list(fields.items()):
                if isinstance(locator, str) and locator.startswith('xpath='):
                    # H1: 跳过 iframe companion 字段（CSS 选择器不是 XPath）
                    if field_key.endswith('_iframe'):
                        continue
                    # 检查是否为 iframe 内元素
                    entry = resolver_fields.get(field_key)
                    in_iframe = bool(entry and entry.iframe_context)
                    # 推断元素类型，为按钮类型注入 disabled 过滤
                    elem_type = _infer_type_from_field(field_key, locator)
                    locator = _inject_hidden_filter(locator, in_iframe=in_iframe, elem_type=elem_type)
                    fields[field_key] = (locator, comment)

        # 3. el-select companion 字段自动补全
        self._inject_companion_fields(groups)

        # 4. el-select option locator 生成
        self._inject_option_fields(groups)

        # 5. R4.32 安全网：_select div→input 修正
        for group_name, fields in groups.items():
            for field_key, (locator, comment) in list(fields.items()):
                if field_key.endswith('_select') and isinstance(locator, str):
                    new_locator = fix_el_select_div_to_input(locator)
                    if new_locator != locator:
                        fields[field_key] = (new_locator, comment)

        # 5.5 iframe companion 字段生成 [C5]
        self._inject_iframe_companion_fields(groups)

        # 6. append 模式 — 字段级合并（N4 修复）
        if append and os.path.exists(output_path):
            try:
                with open(output_path, encoding='utf-8') as f:
                    existing = yaml.safe_load(f) if yaml else {}
                if isinstance(existing, dict):
                    for grp_name, grp_data in existing.items():
                        if not isinstance(grp_data, dict):
                            continue
                        if grp_name not in groups:
                            # 新 group，整体合并
                            groups[grp_name] = OrderedDict(
                                (k, (v, '')) for k, v in grp_data.items()
                            )
                        else:
                            # 已有 group，字段级合并（只添加不存在的字段）
                            for fkey, fval in grp_data.items():
                                if fkey not in groups[grp_name]:
                                    groups[grp_name][fkey] = (fval, '')
            except Exception:
                pass

        # 7. 写入
        header = self._build_header(module_slug, cn_name)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        # TRACE: 写入前统计
        total_fields = sum(len(fields) for fields in groups.values())
        print(f"  [TRACE] 准备写入: {len(groups)} groups, {total_fields} fields")
        for g_name, g_fields in groups.items():
            print(f"    - {g_name}: {len(g_fields)} fields")
        self._write_yaml_with_comments(output_path, groups, header)

    def write_common_elements(self, output_path, extra_fields=None):
        """追加 common_elements 组（固定模板 + 动态变体）。

        Args:
            output_path: 输出 YAML 路径
            extra_fields: 动态新增的字段 {name: template_value}，来自 CaseGenerator._common_fields_extra
        """
        if not os.path.exists(output_path):
            return

        # 检查是否已有 common_elements
        try:
            with open(output_path, encoding='utf-8') as f:
                content = f.read()
            if 'common_elements:' in content:
                return  # 已有
        except Exception:
            pass

        with open(output_path, 'a', encoding='utf-8') as f:
            f.write('\ncommon_elements:\n')
            for key, locator in self._common_elements.items():
                scalar = _yaml_scalar(locator)
                f.write(f'  {key}: {scalar}\n')
            # 动态变体（来自 Phase 5 生成过程）
            if extra_fields:
                for key, locator in extra_fields.items():
                    scalar = _yaml_scalar(locator)
                    f.write(f'  {key}: {scalar}\n')

    def write_page_urls(self, output_path, page_url_map):
        """追加 page_urls 元数据组（仅多 URL 模块）。幂等保护：已存在则跳过。"""
        if not page_url_map or len(page_url_map) <= 1:
            return  # 单 URL 模块不需要

        if not os.path.exists(output_path):
            return

        # N5: 幂等保护 — 检查是否已存在 page_urls 段
        with open(output_path, encoding='utf-8') as f:
            content = f.read()
        if 'page_urls:' in content:
            return  # 已存在，跳过

        with open(output_path, 'a', encoding='utf-8') as f:
            f.write('\n# === 页面 URL 映射 ===\npage_urls:\n')
            for slug, info in page_url_map.items():
                url = info.get('url', '')
                groups = info.get('groups', [])
                f.write(f'  {slug}:\n')
                f.write(f'    url: "{url}"\n')
                if groups:
                    f.write(f'    groups:\n')
                    for g in groups:
                        f.write(f'      - {g}\n')

    # ─── 内部方法 ───

    def _build_header(self, module_slug, cn_name):
        """构建 YAML 头部注释"""
        display = cn_name or module_slug
        return (
            f'# {display} - 页面元素定位器（自动生成）\n'
            f'# 模块: {display}\n'
            f'# [WARN] 请勿手动修改 locator，修改后请重新运行工具\n'
            f'#\n'
            f'# 如需添加 probe 未覆盖的元素（如详情页字段），请在末尾追加，\n'
            f'# 并确保 XPath 包含隐藏过滤:\n'
            f'#   and not(ancestor-or-self::*[contains(@class,\'is-hidden\')])\n'
            f'#\n\n'
        )

    def _inject_companion_fields(self, groups):
        """自动补全 el-select companion 字段（_select/_input/_editable/_first_option）。

        双路径检测 el-select 元素：
        1. locator 字符串匹配 input[@class='el-input__inner']
        2. resolver 中 entry.raw.type == 'el-select'
        """
        resolver_groups = self._resolver.get_groups()

        for group_name, fields in list(groups.items()):
            resolver_fields = resolver_groups.get(group_name, {})
            new_fields = OrderedDict()

            for field_key, (locator, comment) in fields.items():
                new_fields[field_key] = (locator, comment)

            # 收集 el-select 前缀（仅从 resolver 类型信息）
            el_select_prefixes = set()

            # 来源1: resolver 中的 el-select / date-picker 类型元素
            # normalize_type handles both 'date_picker' and 'date-picker'
            for field_key, entry in resolver_fields.items():
                if entry.raw and _normalize_type(entry.raw.get('type', '')) in ('el-select', 'date-picker'):
                    # 提取前缀：去掉 _input/_select 后缀
                    if field_key.endswith('_select'):
                        prefix = field_key[:-7]
                    elif field_key.endswith('_input'):
                        prefix = field_key[:-6]
                    else:
                        prefix = field_key
                    el_select_prefixes.add(prefix)

                    # 确保基础 _input/_select 也在 fields 中
                    locator = entry.locator or ''
                    label = entry.label or ''
                    base_comment = label

                    input_key = f'{prefix}_input'
                    if input_key not in fields and input_key not in new_fields:
                        new_fields[input_key] = (locator, f'{base_comment}（输入搜索）')

                    select_key = f'{prefix}_select'
                    if select_key not in fields and select_key not in new_fields:
                        new_fields[select_key] = (locator, f'{base_comment}（选择触发）')

            # 来源2: locator 字符串匹配（resolver 无 type 时的 fallback）
            # 检测 _select 字段且 locator 包含 el-input__inner 模式
            for field_key, (locator, comment) in list(fields.items()):
                if not field_key.endswith('_select'):
                    continue
                if not isinstance(locator, str):
                    continue
                # 检测 el-select 或 ant-select 触发器模式
                if ("el-input__inner" in locator or "el-select" in locator
                        or "ant-input" in locator or "ant-select" in locator
                        or field_key.endswith('_select')):
                    prefix = field_key[:-7]  # 去掉 _select
                    if prefix and prefix not in el_select_prefixes:
                        el_select_prefixes.add(prefix)
            # 也检查 new_fields 中已有的 _select
            for field_key, (locator, comment) in list(new_fields.items()):
                if not field_key.endswith('_select'):
                    continue
                if not isinstance(locator, str):
                    continue
                if "el-input__inner" in locator or "el-select" in locator or "ant-input" in locator or "ant-select" in locator:
                    prefix = field_key[:-7]
                    if prefix and prefix not in el_select_prefixes:
                        el_select_prefixes.add(prefix)

            # 为每个 el-select 前缀生成 companion 字段
            for prefix in el_select_prefixes:
                # 获取 _select locator（优先用 fields 中的，回退到 new_fields）
                select_key = f'{prefix}_select'
                sel_loc = ''
                if select_key in fields:
                    sel_loc = fields[select_key][0]
                elif select_key in new_fields:
                    sel_loc = new_fields[select_key][0]
                if not sel_loc:
                    # 回退：用 _input 的 locator
                    input_key = f'{prefix}_input'
                    if input_key in fields:
                        sel_loc = fields[input_key][0]
                    elif input_key in new_fields:
                        sel_loc = new_fields[input_key][0]

                # 确保 _select 也有 (xpath)[N] 包裹（防止丢失 [1]）
                if sel_loc and isinstance(sel_loc, str):
                    raw = sel_loc
                    has_xpath_prefix = raw.startswith('xpath=')
                    bare = raw[6:] if has_xpath_prefix else raw
                    if not _OUTER_WRAP_RE.match(bare) and bare.startswith('//'):
                        wrapped = f"({bare})[1]"
                        sel_loc = f"xpath={wrapped}" if has_xpath_prefix else wrapped
                        # 同步更新 fields 和 new_fields 中的 _select
                        if select_key in new_fields:
                            new_fields[select_key] = (sel_loc, new_fields[select_key][1])
                        if select_key in fields:
                            fields[select_key] = (sel_loc, fields[select_key][1])

                base_comment = ''
                for ck in (select_key, f'{prefix}_input'):
                    if ck in fields:
                        base_comment = fields[ck][1].split('（')[0]
                        break
                    if ck in new_fields:
                        base_comment = new_fields[ck][1].split('（')[0]
                        break

                # _editable companion
                editable_key = f'{prefix}_editable'
                if editable_key not in fields and editable_key not in new_fields:
                    if isinstance(sel_loc, str) and sel_loc:
                        new_fields[editable_key] = (
                            _make_editable_locator_postfix(sel_loc),  # 后置模式：(xpath)[N][not(@readonly)]
                            f'{base_comment}（可编辑状态）'
                        )

                # _first_option companion
                first_key = f'{prefix}_first_option'
                if first_key not in fields and first_key not in new_fields:
                    new_fields[first_key] = (
                        f'xpath={self._first_option_xpath}',
                        f'{base_comment}（第一个可见选项）'
                    )

            groups[group_name] = new_fields

    def _inject_option_fields(self, groups):
        """自动补充 el-select option 字段（从 discovery 的 select_options 生成）。"""
        resolver_groups = self._resolver.get_groups()

        for group_name, fields in list(groups.items()):
            resolver_fields = resolver_groups.get(group_name, {})

            for field_key in list(fields.keys()):
                # 找到 _select 字段
                if not field_key.endswith('_select'):
                    continue

                # 从 resolver 获取元素信息
                entry = resolver_fields.get(field_key)
                if not entry or not entry.raw:
                    continue

                options = entry.raw.get('select_options', [])
                if not options:
                    continue

                conflicts = entry.raw.get('option_conflicts', {})

                for opt_text in options:
                    slug = _slugify(opt_text)
                    opt_key = f'{field_key}_{slug}_option'
                    if opt_key in fields:
                        continue

                    if _xpath_escape_label is None:
                        continue

                    # 构建 match expression
                    if opt_text in conflicts:
                        if "'" in opt_text:
                            escaped = _xpath_escape_label(opt_text)
                            match_expr = f"text()={escaped}"
                        else:
                            match_expr = f"text()='{opt_text}'"
                    else:
                        if "'" in opt_text:
                            escaped = _xpath_escape_label(opt_text)
                            match_expr = f"contains(.,{escaped})"
                        else:
                            match_expr = f"contains(.,'{opt_text}')"

                    xpath = self._option_template.replace(
                        '{match_expr}', match_expr)
                    fields[opt_key] = (
                        f'xpath={xpath}',
                        f'{opt_text}（选项）'
                    )

    def _inject_iframe_companion_fields(self, groups):
        """为 iframe 内元素生成 {field}_iframe companion 字段。

        iframe 元素需要两个 locator：
        1. {field}: 元素在 iframe 内的 XPath
        2. {field}_iframe: iframe 本身的 CSS 选择器（用于 frame_locator）

        [C5] 对 el-select companion 字段也生成 _iframe
        """
        resolver_groups = self._resolver.get_groups()

        for group_name, fields in list(groups.items()):
            resolver_fields = resolver_groups.get(group_name, {})
            new_fields = OrderedDict()

            for field_key, (locator, comment) in fields.items():
                new_fields[field_key] = (locator, comment)

                # 检查是否为 iframe 元素
                entry = resolver_fields.get(field_key)
                if entry and entry.iframe_context:
                    iframe_key = f'{field_key}_iframe'
                    if iframe_key not in fields and iframe_key not in new_fields:
                        iframe_selector = entry.iframe_context
                        # 2026-08-07: 全 XPath 格式，不再强制添加 css= 前缀
                        # 如果已经是 xpath= 开头则保留，否则保留原始格式
                        if not iframe_selector.startswith(('xpath=', 'css=')):
                            # 兼容旧格式：如果不是 xpath= 也不是 css=，假设是 CSS 选择器并转换为 XPath
                            # 这种情况很少见，仅在旧数据中出现
                            iframe_selector = f'xpath={iframe_selector}'
                        new_fields[iframe_key] = (
                            iframe_selector,
                            f'{comment}（iframe 定位器）'
                        )

            groups[group_name] = new_fields

    def _write_yaml_with_comments(self, filepath, groups, header=''):
        """手写 YAML，保留每个 key 后的中文注释。

        groups: OrderedDict of {group_name: OrderedDict of {key: (locator, comment)}}
        """
        # ── 兜底保护：空内容不覆盖有实质内容的现有文件 ──
        if not groups and os.path.isfile(filepath):
            existing_size = os.path.getsize(filepath)
            if existing_size > 100:  # 有实质内容（不只是 header）
                print(f"  [WARN] 跳过空内容写入，保留现有文件: {filepath} ({existing_size} bytes)")
                return

        with open(filepath, 'w', encoding='utf-8') as f:
            if header:
                f.write(header)
            for group_name, entries in groups.items():
                f.write(f'{group_name}:\n')
                for key, (locator, comment) in entries.items():
                    # 防御: 拒绝写入 contains(text(),'') 废模板
                    if isinstance(locator, str) and "contains(text(),'')" in locator:
                        print(f"  [WARN] 跳过废模板: {key}")
                        continue
                    # M7: 强制 xpath= 前缀（裸 XPath 以 // 或 ( 开头时自动补齐）
                    if isinstance(locator, str) and not locator.startswith(('xpath=', 'text=', 'role=', '${', 'css=')):
                        if locator.startswith('//') or locator.startswith('('):
                            locator = f'xpath={locator}'
                    scalar = _yaml_scalar(str(locator))
                    if comment:
                        f.write(f'  {key}: {scalar}  # {comment}\n')
                    else:
                        f.write(f'  {key}: {scalar}\n')


# ═══════════════════════════════════════════════════════════════════
# 模块级函数（供 run_phase3.py 等外部导入）
# ═══════════════════════════════════════════════════════════════════

def generate_pages_yaml_from_discovery(discovery_path, output_path,
                                        module_name, module_slug=None,
                                        append=False):
    """从 discovery JSON 直接生成 pages YAML。

    供 run_phase3.py Step 3 调用（替代旧的 subprocess → generate_pages_from_probe.py）。
    内部组合 ElementResolver + PagesWriter。

    Args:
        discovery_path: discovery JSON 文件路径
        output_path: 输出 YAML 路径
        module_name: 中文模块名
        module_slug: 英文 slug（None 时从 module_name 推导）
        append: 是否追加到现有文件
    """
    from core.element_resolver import ElementResolver

    resolver = ElementResolver([discovery_path])
    writer = PagesWriter(resolver)

    # 全量模式：所有 resolver 中的字段都是 required
    required_fields = {}
    for group_name, fields in resolver.get_groups().items():
        for field_key, entry in fields.items():
            required_fields[(group_name, field_key)] = {
                'locator': entry.locator,
                'label': entry.label or '',
                'comment': '',
            }

    slug = module_slug or resolver.module_slug
    if not slug:
        slug = re.sub(r'[^a-zA-Z0-9_]', '_', module_name or '').strip('_').lower()

    writer.write_pages_yaml(required_fields, output_path,
                             slug, module_name, append=append)
    writer.write_common_elements(output_path)
    writer.write_page_urls(output_path, resolver.get_page_url_map())

    print(f'[OK] generate_pages_yaml_from_discovery: {output_path}')
