#!/usr/bin/env python3
"""verify_locators.py — Phase 6 运行时验证工具

按 case 步骤顺序在真实浏览器中执行，验证所有 locator（KB + discovery），
自动检测容器类型，注入隐藏过滤，回写 pages YAML。

设计文档: docs/debug/phase3-broad-discovery-and-phase4a-context-matching.md §6

用法:
    python tools/verify_locators.py {project_dir} \
      --cookie "name=value;..." \
      --url "http://100.71.19.25:30101" \
      [--discovery {project}/_probe/discovery_{module}.json]
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

# 共享工具函数
try:
    from tools._yaml_utils import escape_yaml_scalar as _escape_yaml_scalar
    from tools._wait_utils import wait_for_dom_stable as _wait_for_dom_stable
except ImportError:
    # 独立运行时 sys.path 可能不包含 tools/
    _tools_dir = os.path.dirname(os.path.abspath(__file__))
    if _tools_dir not in sys.path:
        sys.path.insert(0, _tools_dir)
    from _yaml_utils import escape_yaml_scalar as _escape_yaml_scalar
    from _wait_utils import wait_for_dom_stable as _wait_for_dom_stable

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from probe_element import (
    parse_cookie, detect_visible_containers,
    _xpath_escape_label, _safe_format, safe_count,
)
from probe_utils import (
    load_knowledge, get_kb_patterns, get_all_patterns,
    get_multi_step_patterns, kb_fallback, KB_KEY_ALIAS,
)
from xpath_utils import inject_hidden_filter, has_hidden_filter, CONTAINER_XPATH
from xpath_utils import _unwrap_positional, _rewrap_positional
from xpath_utils import apply_hidden_filters_to_pages, strip_not_ancestor_from_pages
from field_suffixes import DIALOG_CONFIRM_LABELS
from _pages_writer import _make_editable_locator as _make_editable_locator_from_select
from _pages_writer import _make_editable_locator_postfix
from _element_types import (
    TYPE_TO_SECTIONS as _TYPE_COMPATIBLE_SECTIONS,
    ALL_LIST_SECTIONS as _ALL_LIST_SECTIONS,
    infer_discovery_section as _infer_discovery_section,
    infer_elem_type as _infer_elem_type,
    normalize_type as _normalize_type,
)

# Regex for stripping old verification markers from YAML trailing comments (#7)
_OLD_MARKER_RE = re.compile(
    r'\s*#\s*\[(?:UPGRADED|DOWNGRADED|CROSS-GROUP-NEW|UNVERIFIED|FALLBACK|PENDING-NO-GROUP)'
    r'(?::\s*[\w-]+)?\]'
)

# Token keys for cookie -> localStorage auto-sync (imported from probe_element)
from probe_element import TOKEN_KEYS

# R6: AI 兜底探测模块（可选，缺失不影响现有逻辑）
try:
    from _ai_probe import init as _ai_probe_init
    from _ai_probe import ai_probe_locator as _ai_probe_locator
    from _ai_probe import flush_diagnostics as _ai_probe_flush
    from _ai_probe import MARKER_MAP as _AI_MARKER_MAP
    _HAS_AI_PROBE = True
except ImportError:
    _HAS_AI_PROBE = False

# Destructive operation triggers — confirm after these is skipped
DESTRUCTIVE_TRIGGERS = {'删除', '移除', '清空', '重置'}

# Container type priority for selection
CONTAINER_TYPES = ['dialog', 'drawer', 'message-box']

# L3 system workflows cache (for P2-3 l3_call expansion)
_SYSTEM_WORKFLOWS = None
_PROJECT_WORKFLOWS = {}

# Probe data isolation prefix (P2-6)
PROBE_ISOLATION_PREFIX = '__probe__'

# Steps that don't need locator verification
NO_VERIFY_KEYWORDS = {
    'open_url', 'open_browser', 'refresh', 'go_back', 'wait_for_time',
    'wait_for_element_hidden', 'log', 'inject_local_storage', 'inject_cookies',
    'inject_token_header', 'close_browser', 'set_viewport_size',
    'check_page_loaded',  # §9 集成修复: 页面加载检查，无 locator
    'wait_for_loading_complete',  # L3 复合关键字，无直接 locator，由 system_workflows.yaml 定义
    'if_variable',       # BUG-1b: L3 条件控制流，无 locator
    'wait_for_element',  # BUG-4: 通用等待，语义同 wait_for_element_visible，操作完成后才出现
    'set_random_variable',  # BUG-4b: 数据生成关键字，无 locator
}

# L3 keywords that need expansion (P2-3)
L3_KEYWORDS = {'l3_call'}

# Fill values for Phase 6 probing (avoid data conflicts)
PROBE_FILL_VALUES = {
    'input': PROBE_ISOLATION_PREFIX + '测试',
    'textarea': PROBE_ISOLATION_PREFIX + '测试文本',
    'number': '999',  # distinct from real data
}


# ============================================================================
# KB locators — using probe_utils shared functions
# ============================================================================

# click_element 步骤可能匹配多种元素类型，按精确度降序遍历
# 当主类型是这三个之一时，扩展查找其他类型（去重追加）
CLICK_EXPAND_TYPES = ['button', 'table-action-button', 'detail-link']


def _get_kb_locators_for_type(elem_type, fmt_vars):
    """Generate KB template locators for a single element type (internal)."""
    locators = []

    # 1. single_step + composite direct patterns
    for p in get_all_patterns(elem_type):
        x = _safe_format(p, fmt_vars)
        if '{' not in x:
            locators.append(x)

    # 2. multi_step expand + editable-check patterns
    for step_name in ('expand', 'editable-check'):
        for p in get_multi_step_patterns(elem_type, step_name):
            x = _safe_format(p, fmt_vars)
            if '{' not in x:
                locators.append(x)

    # 3. KB_KEY_ALIAS fallback lookup
    if not locators and elem_type in KB_KEY_ALIAS:
        alias_type = KB_KEY_ALIAS[elem_type]
        for p in get_all_patterns(alias_type):
            x = _safe_format(p, fmt_vars)
            if '{' not in x:
                locators.append(x)

    return locators


def _get_kb_locators(elem_type, label):
    """Generate all KB template locators for a given element type and label.

    Uses probe_utils shared functions instead of independent KB loading.

    When elem_type is in CLICK_EXPAND_TYPES (button, table-action-button,
    detail-link), also appends locators from the other types in the list
    (deduplicated). This ensures click_element steps can match elements
    rendered as <a>, <span>, <button>, etc.
    """
    fmt_vars = {
        'label': label,
        'char1': label[0] if label else '',
        'char2': label[-1] if label else '',
        # BUG-4 D2: 全拆字模式（审计 4b: 三文件同步）
        # 跳过单引号字符（XPath 语法安全）
        'chars_all': " and ".join(f"contains(.,'{c}')" for c in label if c != "'") if label else '',
        'tab_name': label, 'section': label,
        'field_label': label, 'keyword': label,
    }

    # 1. 主类型（必查，最高优先级）
    locators = _get_kb_locators_for_type(elem_type, fmt_vars)
    seen = set(locators)

    # 2. click_element 扩展类型（仅当主类型在 CLICK_EXPAND_TYPES 中时）
    if elem_type in CLICK_EXPAND_TYPES:
        for alt_type in CLICK_EXPAND_TYPES:
            if alt_type == elem_type:
                continue
            for loc in _get_kb_locators_for_type(alt_type, fmt_vars):
                if loc not in seen:
                    locators.append(loc)
                    seen.add(loc)

    return locators


# ============================================================================
# Discovery matching helpers — imported from _element_types
# ============================================================================
# _TYPE_COMPATIBLE_SECTIONS, _ALL_LIST_SECTIONS, _infer_discovery_section
# are now imported from _element_types (see imports above).


def _find_in_discovery(discovery_data, label, preferred_container=None,
                       elem_type=None):
    """从 discovery 全量数据中查找匹配 label 的已验证 locator。

    搜索范围（按优先级）：
    1. 匹配的 containers（当 preferred_container 提供时）
    2. list_page 所有分区（buttons → row_buttons → inputs → tabs →
       detail_links → checkboxes → menu_items）
    3. 所有 containers（preferred_container 未匹配时的降级）

    BUG-6 fix: 两轮搜索策略（严格→宽松）。
    Round 1 使用类型守卫（防止 fill_value 匹配到 button），
    Round 2 搜索全部 section（当 infer_elem_type 误判时的安全网）。
    Round 2 匹配时输出 [INFO] 日志，便于追踪类型不一致频率。

    Args:
        preferred_container: 当前容器上下文（'drawer'/'dialog'/None）。
            提供时优先搜索匹配的 container，找不到再降级到 list_page。
        elem_type: D4 推断的元素类型（'input-generic'/'button'/...）。
            提供时只搜索类型兼容的 section，防止 fill_value 匹配到 button。
            为 None 时搜索全部 section（向后兼容）。

    返回: (locator, container_type) 或 (None, None)
    """
    if not discovery_data or not label:
        return None, None

    # 确定类型兼容的 sections（修改 5: 类型守卫）
    if elem_type and elem_type in _TYPE_COMPATIBLE_SECTIONS:
        _strict_sections = _TYPE_COMPATIBLE_SECTIONS[elem_type]
    else:
        _strict_sections = _ALL_LIST_SECTIONS

    # BUG-6 fix: 两轮搜索（严格→宽松）
    # Round 1: 类型守卫严格匹配
    # Round 2: 全 section 宽松匹配（Round 1 未找到时的安全网）
    for _round in (1, 2):
        _sections = _strict_sections if _round == 1 else _ALL_LIST_SECTIONS
        _is_loose = (_round == 2)

        # 1. 优先搜索匹配的 containers（当有容器上下文时）
        if preferred_container:
            for container in discovery_data.get('containers', []):
                ct = container.get('container_type', '')
                if ct != preferred_container:
                    continue
                for elem in container.get('elements', []):
                    elabel = elem.get('label', '') or elem.get('text', '')
                    # H9: 容器路径也需要 verified 检查（与 L238 list_page 路径保持一致）
                    if elabel == label and elem.get('locator') and elem.get('verified'):
                        # 类型守卫：检查容器内元素类型是否兼容
                        if not _is_loose and elem_type:
                            elem_section = _infer_discovery_section(elem)
                            if elem_section and elem_section not in _sections:
                                continue
                        if _is_loose:
                            _actual_type = elem.get('type', '?')
                            print(f"    [INFO] discovery 类型宽松匹配: "
                                  f"label='{label}' inferred={elem_type} "
                                  f"actual={_actual_type}")
                        return elem['locator'], ct

        # 2. 搜索 list_page 兼容分区（修改 5: 类型守卫限制搜索范围）
        list_page = discovery_data.get('list_page', {})
        for section in _sections:
            for elem in list_page.get(section, []):
                # 兼容 text/label/name 三种标签字段
                elabel = (elem.get('text', '')
                          or elem.get('label', '')
                          or elem.get('name', ''))
                if elabel == label and elem.get('locator') and elem.get('verified'):
                    if _is_loose:
                        _actual_type = elem.get('type', '?')
                        print(f"    [INFO] discovery 类型宽松匹配(list_page): "
                              f"label='{label}' inferred={elem_type} "
                              f"actual={_actual_type}")
                    # list_page 元素不在容器内 → container_type = None
                    return elem['locator'], None

        # 3. 降级搜索所有 containers（preferred_container 未匹配时）
        for container in discovery_data.get('containers', []):
            for elem in container.get('elements', []):
                elabel = elem.get('label', '') or elem.get('text', '')
                # H9: 降级搜索也需要 verified 检查
                if elabel == label and elem.get('locator') and elem.get('verified'):
                    # 类型守卫：检查容器内元素类型是否兼容
                    if not _is_loose and elem_type:
                        elem_section = _infer_discovery_section(elem)
                        if elem_section and elem_section not in _sections:
                            continue
                    if _is_loose:
                        _actual_type = elem.get('type', '?')
                        print(f"    [INFO] discovery 类型宽松匹配(container): "
                              f"label='{label}' inferred={elem_type} "
                              f"actual={_actual_type}")
                    return elem['locator'], container.get('container_type')

    return None, None


def _find_list_page_group(pages_dict, src_group):
    """从源容器 group 名推导模块前缀，找到对应的列表页 group。

    例: 'project_manage_dialog_add_elements' → 'project_manage_elements'
    """
    _CONTAINER_MARKERS = ('_drawer_', '_dialog_', '_messagebox_',
                          '_message_box_')
    # 提取模块前缀：在第一个容器标记处截断
    module_prefix = src_group
    for cm in _CONTAINER_MARKERS:
        idx = src_group.find(cm)
        if idx >= 0:
            module_prefix = src_group[:idx]
            break

    # 在 pages_dict 中搜索匹配的非容器 group
    candidates = []
    for gname in pages_dict:
        if not isinstance(pages_dict[gname], dict):
            continue
        if not gname.startswith(module_prefix):
            continue
        if any(cm in gname for cm in _CONTAINER_MARKERS):
            continue
        candidates.append(gname)

    # 优先选择 {module_prefix}_elements（主 group）
    primary = f'{module_prefix}_elements'
    if primary in candidates:
        return primary
    return candidates[0] if candidates else None


# ============================================================================
# YAML loading helpers
# ============================================================================

def load_yaml_files(directory):
    """Load all YAML files from a directory recursively."""
    result = {}
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(('.yaml', '.yml')) and not f.startswith('_'):
                path = os.path.join(root, f)
                try:
                    with open(path, encoding='utf-8') as fh:
                        data = yaml.safe_load(fh)
                    if isinstance(data, dict):
                        result[path] = data
                except Exception:
                    pass
    return result


def load_cases(project_dir, module=None):
    """Load all case YAML files from project."""
    cases = []
    cases_dir = os.path.join(project_dir, 'cases')
    if not os.path.isdir(cases_dir):
        return cases

    # BUG-2: normalize module name (hyphen → underscore) to match cases/ directory naming
    module_norm = module.replace('-', '_') if module else None

    for root, dirs, files in os.walk(cases_dir):
        for f in sorted(files):
            if f.endswith('.yaml') and not f.startswith('_'):
                if module_norm:
                    rel = os.path.relpath(root, cases_dir)
                    rel_norm = rel.replace('-', '_')
                    if rel_norm != module_norm and rel != '.':
                        continue
                path = os.path.join(root, f)
                try:
                    with open(path, encoding='utf-8') as fh:
                        data = yaml.safe_load(fh)
                    if isinstance(data, dict):
                        data['_file'] = path
                        cases.append(data)
                except Exception:
                    pass
    return cases


def load_pages(project_dir, module=None):
    """Load all pages YAML, return {group: {field: locator}}.

    Groups from multiple YAML files are merged. elements.yaml entries
    take priority over _fallback.yaml entries (the latter are only used
    when elements.yaml doesn't define the field).

    F5: When module is specified, only load groups that start with the module
    prefix (plus 'common_elements' and 'common'). This provides module-scoped
    isolation to prevent cross-module locator collisions.
    """
    pages = {}
    pages_dir = os.path.join(project_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return pages
    # F5: build module prefix filter
    if module:
        module_prefix = module.replace('-', '_')
        _allowed = (module_prefix, 'common', 'dropdown_menu')
    else:
        _allowed = None
    # Collect all files, sort so _fallback.yaml comes FIRST (lower priority),
    # then elements.yaml (higher priority, overwrites fallback).
    all_files = []
    for root, dirs, files in os.walk(pages_dir):
        for f in files:
            if f.endswith(('.yaml', '.yml')):
                all_files.append((root, f))
    # Sort: _fallback files first, then others. This ensures elements.yaml
    # (processed later) overwrites _fallback.yaml for the same key.
    all_files.sort(key=lambda x: (0 if x[1].startswith('_fallback') else 1, x[0], x[1]))
    for root, f in all_files:
        path = os.path.join(root, f)
        try:
            with open(path, encoding='utf-8') as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                for group, fields in data.items():
                    # BUG-1 审计修复: 排除 page_urls 元数据
                    if group == 'page_urls':
                        continue
                    if isinstance(fields, dict):
                        # F5: skip groups not belonging to the target module
                        # 使用 startswith(p + '_') + 精确匹配，防止前缀相似的模块误匹配
                        if _allowed and not any(
                            group.startswith(p + '_') or group == p + '_elements' or group == p
                            for p in _allowed
                        ):
                            continue
                        if group not in pages:
                            pages[group] = {}
                        pages[group].update(fields)
        except Exception:
            pass
    return pages


def load_data(project_dir):
    """Load all data YAML, return flat {group.field: value}."""
    data = {}
    data_dir = os.path.join(project_dir, 'data')
    if not os.path.isdir(data_dir):
        return data
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith(('.yaml', '.yml')):
                path = os.path.join(root, f)
                try:
                    with open(path, encoding='utf-8') as fh:
                        d = yaml.safe_load(fh)
                    if isinstance(d, dict):
                        for group, fields in d.items():
                            if isinstance(fields, dict):
                                for k, v in fields.items():
                                    data[f'{group}.{k}'] = v
                except Exception as e:
                    print(f"    [WARN] load_data failed: {path}: {e}")
    return data


def resolve_var(value, data_dict):
    """Resolve ${group.field} references in a value string."""
    if not isinstance(value, str):
        return value
    def replacer(m):
        ref = m.group(1)
        return str(data_dict.get(ref, m.group(0)))
    return re.sub(r'\$\{([^}]+)\}', replacer, value)


def resolve_locator(params, pages_dict):
    """Extract locator from step params, resolving ${group.field} references."""
    locator = ''
    if isinstance(params, dict):
        locator = params.get('locator', '')
    if not locator:
        return ''
    # Resolve variable references
    m = re.match(r'^\$\{([^}]+)\}$', locator)
    if m:
        ref = m.group(1)
        for group, fields in pages_dict.items():
            if isinstance(fields, dict):
                # ref could be group.field
                parts = ref.split('.', 1)
                if len(parts) == 2 and parts[0] == group and parts[1] in fields:
                    return str(fields[parts[1]])
        # Try flat lookup
        return locator
    return locator


# ============================================================================
# Locator verification — try candidates × prefixes
# ============================================================================

# 容器前缀剥离正则（匹配 el-dialog/el-drawer/el-message-box 前缀）
CONTAINER_PREFIX_PATTERN = re.compile(
    r"^//div\[contains\(@class,'el-(dialog|drawer|message-box)'\)\]"
)


def _strip_container_prefix(raw_xpath):
    """剥离 XPath 中的容器前缀（el-dialog/el-drawer/el-message-box）

    支持两种格式：
    - 裸 XPath: //div[...]//button → //button
    - 包裹 XPath: (//div[...]//button)[1] → (//button)[1]

    Args:
        raw_xpath: 原始 XPath（不含 xpath= 前缀）

    Returns:
        剥离后的 XPath（保持原有包裹格式）
    """
    inner, wrap = _unwrap_positional(raw_xpath)
    stripped = CONTAINER_PREFIX_PATTERN.sub("", inner)
    return _rewrap_positional(stripped, wrap)


def _verify_count_or_first(page, locator):
    """验证 locator 匹配数，count>1 时自动 [1] 收窄避免 strict mode violation。

    与 verify_locator_candidates() 的 count>1 逻辑保持一致：
    count==1 → 通过；count>1 → 尝试 (xpath)[1] 取首个匹配元素。

    Args:
        page: Playwright Page 对象
        locator: 完整 locator 字符串（含 xpath= 前缀）

    Returns:
        str or None: 验证通过的 locator（可能已 [1] 收窄），count==0 返回 None
    """
    if not locator:
        return None
    try:
        count = page.locator(locator).count()
    except Exception:
        return None
    if count == 1:
        return locator
    if count > 1:
        # 多匹配 → [1] 收窄（与 verify_locator_candidates 的 [1] fallback 一致）
        raw = locator[6:] if locator.startswith('xpath=') else locator
        narrowed = inject_hidden_filter(f"xpath=({raw})[1]")
        try:
            if page.locator(narrowed).count() == 1:
                return narrowed
        except Exception:
            pass
    return None


def verify_locator_candidates(page, candidates, container_type=None, discovery_ct=None, is_el_select_option=False, return_index=False):
    """Try multiple locator candidates with multiple container prefixes.

    Priority: discovery container_type > default priority > no prefix

    P1-2: el-select options (is_el_select_option=True) — NO container prefix,
    dropdown panel floats globally outside drawer/dialog.

    P2-4: When count>1 in preferred container, fall back to (xpath)[last()]
    for dialog/drawer (last opened = topmost).

    Args:
        return_index: If True, return 4-tuple with matched candidate index.
                     If False (default), return 3-tuple for backward compatibility.

    Returns:
        If return_index=False: (matched_locator, matched_prefix, count) or (None, None, 0)
        If return_index=True: (matched_locator, matched_prefix, count, candidate_index) or (None, None, 0, None)
    """
    # Build prefix order
    if is_el_select_option:
        # P1-2: options are globally in dropdown panel, no container prefix
        prefix_order = [None]
    elif discovery_ct:
        prefix_order = [discovery_ct] + [p for p in CONTAINER_TYPES if p != discovery_ct] + [None]
    elif container_type:
        prefix_order = [container_type] + [p for p in CONTAINER_TYPES if p != container_type] + [None]
    else:
        prefix_order = CONTAINER_TYPES + [None]

    # Helper: return result with or without candidate index
    def _ret(xpath, pfx, cnt, cidx=None):
        if return_index:
            return xpath, pfx, cnt, cidx
        return xpath, pfx, cnt

    for prefix in prefix_order:
        for candidate_index, candidate in enumerate(candidates):
            xpath = candidate
            if not xpath.startswith('xpath='):
                xpath = f"xpath={xpath}"

            # 剥离已有容器前缀 → 得到裸 XPath
            raw_xpath = xpath[6:] if xpath.startswith('xpath=') else xpath
            bare_xpath = _strip_container_prefix(raw_xpath)

            # 按 prefix 决定的顺序测试 4 种变体
            if prefix is None:
                # prefix=None: 容器前缀优先，最后不带前缀
                # 优先级: dialog > drawer > message-box > 无前缀
                test_order = CONTAINER_TYPES + [None]
            else:
                # prefix='dialog': dialog 优先，然后其他容器，最后 none
                test_order = [prefix] + [p for p in CONTAINER_TYPES if p != prefix] + [None]

            for test_prefix in test_order:
                # 构建测试 XPath
                if test_prefix is None:
                    test_xpath = bare_xpath
                elif test_prefix in CONTAINER_XPATH:
                    # BUG-13 修复：前缀注入到括号内部，避免 prefix + (xpath)[N] 无效拼接
                    inner, wrap = _unwrap_positional(bare_xpath)
                    test_xpath = _rewrap_positional(CONTAINER_XPATH[test_prefix] + inner, wrap)
                else:
                    test_xpath = bare_xpath

                # C-3 / L-5: el-select options — do NOT inject hidden filter
                # (dropdown panel uses display:none internally when not expanded)
                if is_el_select_option:
                    full_xpath = f"xpath={test_xpath}" if not test_xpath.startswith('xpath=') else test_xpath
                else:
                    full_xpath = inject_hidden_filter(f"xpath={test_xpath}")

                try:
                    count = page.locator(full_xpath).count()
                    if count == 1:
                        return _ret(full_xpath, test_prefix, count, candidate_index)
                    if count > 1:
                        # 3b: strict mode auto-fix — 无前缀时自动尝试容器前缀
                        if test_prefix is None and not is_el_select_option:
                            for try_ct in ['dialog', 'drawer', 'message-box']:
                                if try_ct not in CONTAINER_XPATH:
                                    continue
                                try_prefix = CONTAINER_XPATH[try_ct]
                                # BUG-13 修复：前缀注入到括号内部
                                inner, wrap = _unwrap_positional(bare_xpath)
                                scoped_raw = _rewrap_positional(try_prefix + inner, wrap)
                                scoped_full = inject_hidden_filter(f"xpath={scoped_raw}")
                                try:
                                    scoped_count = page.locator(scoped_full).count()
                                    if scoped_count == 1:
                                        print(f"    [INFO] 3b strict mode 修复: 自动添加 {try_ct} 前缀")
                                        return _ret(scoped_full, try_ct, 1, candidate_index)
                                except Exception as _e:
                                    # H4: 记录异常（XPath语法错误/超时/其他）便于调试
                                    print(f"    [WARN] H4: 3b strict 前缀探测异常({try_ct}): {_e}")
                        # P2-4: [last()] strategy for dialog/drawer (topmost = last opened)
                        if test_prefix in ('dialog', 'drawer') and not is_el_select_option:
                            wrapped_last = f"({test_xpath})[last()]"
                            full_last = inject_hidden_filter(f"xpath={wrapped_last}")
                            try:
                                cnt_last = page.locator(full_last).count()
                                if cnt_last == 1:
                                    return _ret(full_last, test_prefix, 1, candidate_index)
                            except Exception as _e:
                                print(f"    [WARN] H4: [last()] 探测异常: {_e}")
                        # Fallback: [1]
                        wrapped = f"({test_xpath})[1]"
                        if is_el_select_option:
                            full_wrapped = f"xpath={wrapped}"
                        else:
                            full_wrapped = inject_hidden_filter(f"xpath={wrapped}")
                        count2 = page.locator(full_wrapped).count()
                        if count2 == 1:
                            return _ret(full_wrapped, test_prefix, 1, candidate_index)
                except Exception as _e:
                    print(f"    [WARN] H4: 候选 XPath 探测异常: {_e}")

    # BUG-3 层2: 容器前缀替换安全网 — M3: 已移除跨容器猜测
    # 旧逻辑: 尝试 el-drawer ↔ el-dialog 替换（属于"下游猜测"，违反原则二）
    # 新逻辑: 容器类型不一致会作为验证失败暴露，必须在上游修复
    # （跨容器替换已移除，不再执行任何替换操作）

    # BUG-4 D3: H9 修复 — 全部 count==0 时返回 None（而非未验证的 fallback）
    # 让 KB fallback 链（D5 + M11）可达，避免静默传播 count=0 的错误 locator
    # 拆字模式在 KB fallback 中有独立的模板，不需要此处保留错误候选
    if candidates:
        return _ret(None, None, 0, None)

    return _ret(None, None, 0, None)


# ============================================================================
# Step execution
# ============================================================================

# L3 system workflows cache (P2-3)
_L3_WORKFLOWS_CACHE = {}


def _load_l3_workflows(project_dir):
    """Load L3 system + skill + project workflows (P2-3).

    Returns: {workflow_name: {params: [...], steps: [...]}}
    """
    if project_dir in _L3_WORKFLOWS_CACHE:
        return _L3_WORKFLOWS_CACHE[project_dir]
    workflows = {}
    # System workflows (always available)
    sys_wf_path = os.path.join(SCRIPT_DIR, 'system_workflows.yaml')
    if not os.path.isfile(sys_wf_path):
        sys_wf_path = os.path.join(SCRIPT_DIR, '..', 'templates', 'system_workflows.yaml')
    if os.path.isfile(sys_wf_path):
        try:
            with open(sys_wf_path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                for name, wf in data.items():
                    if isinstance(wf, dict) and 'steps' in wf:
                        workflows[name] = wf
        except Exception as e:
            print(f"    [WARN] Failed to load system workflows: {e}")
    # Skill-level workflows (lib/_knowledge/)
    skill_knowledge_dir = os.path.join(SCRIPT_DIR, '..', 'lib', '_knowledge')
    if os.path.isdir(skill_knowledge_dir):
        for f in os.listdir(skill_knowledge_dir):
            if f.endswith(('.yaml', '.yml')):
                try:
                    with open(os.path.join(skill_knowledge_dir, f), encoding='utf-8') as fh:
                        data = yaml.safe_load(fh) or {}
                    for wf in data.get('workflows', []):
                        if isinstance(wf, dict) and 'name' in wf:
                            workflows[wf['name']] = wf
                except Exception as e:
                    print(f"    [WARN] Failed to load skill workflow {f}: {e}")
    # Project workflows (from _knowledge/)
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if os.path.isdir(knowledge_dir):
        for f in os.listdir(knowledge_dir):
            if f.endswith(('.yaml', '.yml')):
                try:
                    with open(os.path.join(knowledge_dir, f), encoding='utf-8') as fh:
                        data = yaml.safe_load(fh) or {}
                    for wf in data.get('workflows', []):
                        if isinstance(wf, dict) and 'name' in wf:
                            workflows[wf['name']] = wf
                except Exception as e:
                    print(f"    [WARN] Failed to load project workflow {f}: {e}")
    _L3_WORKFLOWS_CACHE[project_dir] = workflows
    return workflows


def _expand_l3_call(step, project_dir, pages_dict, data_dict):
    """Expand l3_call step into sub-steps (P2-3).

    Replaces ${param} placeholders in workflow steps with actual args.
    Returns list of sub-steps (empty if workflow not found).
    """
    params = step.get('params', {}) or {}
    workflow_name = params.get('workflow', '') or step.get('workflow', '')
    if not workflow_name:
        return []
    workflows = _load_l3_workflows(project_dir or '')
    wf = workflows.get(workflow_name)
    if not wf:
        print(f"    [WARN] l3_call workflow not found: {workflow_name}")
        return []
    wf_steps = wf.get('steps', []) or []
    if not wf_steps:
        return []
    # Build substitution map
    wf_param_names = wf.get('params', []) or []
    actual_args = params.get('args', []) or []
    if isinstance(actual_args, str):
        actual_args = [actual_args]
    sub_map = {}
    if isinstance(actual_args, list):
        for i, pname in enumerate(wf_param_names):
            if i < len(actual_args):
                sub_map[f'${{{pname}}}'] = str(actual_args[i])
    if isinstance(params.get('args'), dict):
        for k, v in params['args'].items():
            sub_map[f'${{{k}}}'] = str(v)
    # BUG-1: Build locators substitution map from workflow's locators dict
    wf_locators = wf.get('locators', {}) or {}
    resolved_locators = {}
    # Whitelist: only substitute {param} for params explicitly declared in workflow
    _param_whitelist = set(wf_param_names)
    for loc_name, loc_xpath in wf_locators.items():
        resolved = loc_xpath
        # Replace {param} placeholders (single brace) with actual values
        for placeholder, value in sub_map.items():
            bare_key = placeholder[2:-1]  # ${tab_name} → tab_name
            if bare_key in _param_whitelist:
                resolved = resolved.replace(f'{{{bare_key}}}', value)
        resolved_locators[loc_name] = resolved
    # Add ${locators.xxx} → resolved XPath to sub_map
    for loc_name, loc_xpath in resolved_locators.items():
        # Warn if locator template still has unresolved {param} placeholders
        _unresolved = re.findall(r'\{([a-zA-Z_]\w*)\}', loc_xpath)
        if _unresolved:
            print(f"    [WARN] Locator '{loc_name}' has unresolved placeholders: {_unresolved}")
        sub_map[f'${{locators.{loc_name}}}'] = loc_xpath
    # Deep copy + substitute
    expanded = []
    for ws in wf_steps:
        if not isinstance(ws, dict):
            continue
        ws_copy = json.loads(json.dumps(ws))
        # BUG-1: Also substitute {param} in desc field (for log readability)
        if 'desc' in ws_copy and isinstance(ws_copy['desc'], str):
            for placeholder, value in sub_map.items():
                bare_key = placeholder[2:-1]
                if bare_key in _param_whitelist:
                    ws_copy['desc'] = ws_copy['desc'].replace(f'{{{bare_key}}}', value)
        if 'params' in ws_copy and isinstance(ws_copy['params'], dict):
            for pk, pv in list(ws_copy['params'].items()):
                if isinstance(pv, str):
                    for placeholder, value in sub_map.items():
                        pv = pv.replace(placeholder, value)
                    ws_copy['params'][pk] = pv
        expanded.append(ws_copy)
    return expanded


def _smart_wait_after_action(page, wait_dom_stable=True):
    """P3-2: Smart wait after user-visible action.

    Combines networkidle (max 2s) + loading-mask hidden (max 3s) + DOM stable (max 3s).
    Non-fatal — never raises.

    Args:
        wait_dom_stable: 默认 True，等待 DOM 渲染稳定。
            仅在确认无渲染场景（如纯等待步骤）时可设为 False 跳过。
    """
    try:
        page.wait_for_load_state('networkidle', timeout=2000)
    except Exception:
        pass
    try:
        mask = page.locator("xpath=//div[contains(@class,'el-loading-mask') and not(contains(@style,'display: none'))]")
        if mask.count() > 0:
            mask.first.wait_for(state='hidden', timeout=3000)
    except Exception:
        pass

    # DOM 稳定性等待：等表单元素数量不再变化（默认启用）
    if wait_dom_stable:
        _wait_for_dom_stable(page, timeout_ms=3000)


# Plan D: 容器等待增强 — 参考 Phase 4 的 wait_for_stable() 逻辑
_SKIP_CONTAINER_WAIT_LABELS = {
    '确定', '确认', '取消', '删除', '移除', '关闭', '返回', '保存', '提交',
    '搜索', '查询', '刷新', '导出', '下载', '批量', '更多', '重置', '清空',
}




def _should_wait_for_container(desc, locator, keyword):
    """Plan D: 判断 click 后是否需要等待容器渲染完成。

    避免对所有 click 都增加 8s 等待开销。

    Returns:
        bool: True 表示应启用增强容器等待
    """
    if keyword == 'click_select_option':
        return False
    # 表格行内按钮通常不打开容器
    if 'tbody' in locator:
        return False
    # 从 desc 提取按钮标签（优先引号内，回退到直接匹配）
    btn_match = re.search(r'[「"""](.+?)[」"""]', desc)
    btn_label = btn_match.group(1) if btn_match else ''
    if not btn_label:
        # 回退：直接在 desc 中检查跳过标签
        btn_label = desc
    if any(skip in btn_label for skip in _SKIP_CONTAINER_WAIT_LABELS):
        return False
    return True


def _wait_for_container_after_click(page, timeout_ms=2000):
    """点击后容器探测（Playwright 事件驱动，非 Python 轮询）。

    在 _smart_wait_after_action（最多 ~8s）之后调用。
    _smart_wait 已覆盖网络+loading+DOM 稳定，容器如果存在通常已可见。
    本函数用 Playwright 原生 wait_for 做二次确认：
      - 容器已可见 → 立即返回（~0ms）
      - 容器在 API 回调后异步出现 → 事件驱动立即捕捉（比 Python 轮询更快更可靠）
      - 容器不存在 → timeout_ms 后返回 None

    Args:
        timeout_ms: 最大等待时长（默认 2s，_smart_wait 已给了 8s 基础等待）

    Returns:
        str or None: 检测到的容器类型，或 None
    """
    container_selector = (
        "xpath=//div[contains(@class,'el-drawer')"
        " and not(contains(@style,'display: none'))] | "
        "//div[contains(@class,'el-dialog__wrapper')"
        " and not(contains(@style,'display: none'))] | "
        "//div[contains(@class,'el-message-box')]"
    )
    try:
        page.locator(container_selector).first.wait_for(
            state='visible', timeout=timeout_ms)
    except Exception:
        return None  # 超时 → 没有容器出现

    # wait_for 返回 → 容器元素已可见，用 detect_visible_containers 确认类型
    visible = detect_visible_containers(page)
    if visible:
        for ct in CONTAINER_TYPES:
            if ct in visible:
                return ct
        return visible[0] if visible else None

    # wait_for 检测到了但 detect_visible_containers 返回空（极罕见：动画中间态）
    # 短重试
    for _retry in range(3):
        page.wait_for_timeout(300)
        visible = detect_visible_containers(page)
        if visible:
            for ct in CONTAINER_TYPES:
                if ct in visible:
                    return ct
    return None


def should_skip_confirm(steps_so_far):
    """Check if the last few steps contain a destructive trigger."""
    for step in steps_so_far[-3:]:
        desc = step.get('desc', '')
        for trigger in DESTRUCTIVE_TRIGGERS:
            if trigger in desc:
                return True
    return False


# R3: Runtime DOM element type detection
_TAG_TO_KB_TYPE = {
    'textarea': 'textarea-generic',
    'input': 'input-generic',
    'select': 'el-select',
    'date': 'date-picker',
    'button': 'button',
}

# BUG-11: R3 DOM 检测类型守卫 — 防止 button→textarea 等跨类型越界注入
# R3 (_detect_actual_element_type) 在 R4 elif 链之前执行，其结果必须通过
# 类型兼容性检查才能插入 _alt_types，否则同名表单字段会污染按钮类型。
_R3_TYPE_COMPAT = {
    # 按钮类：只允许按钮子类型之间互转
    'button':                {'button', 'search-button', 'download-button', 'close-button', 'table-action-button'},
    'table-action-button':   {'table-action-button', 'button'},
    'search-button':         {'search-button', 'button'},
    'download-button':       {'download-button', 'button'},
    'close-button':          {'close-button', 'button'},
    # 输入类：input ↔ textarea 互转
    'input-generic':         {'input-generic', 'textarea-generic'},
    'textarea-generic':      {'textarea-generic', 'input-generic'},
    # 选择类
    'el-select':             {'el-select'},
    'el-cascader':           {'el-cascader', 'el-select'},
    # 日期类
    'date-picker':           {'date-picker', 'input-generic'},
    # 其他
    'tab':                   {'tab'},
    'checkbox':              {'checkbox', 'checkbox-all'},
    'checkbox-all':          {'checkbox-all', 'checkbox'},
    'detail-link':           {'detail-link'},
    'menu-item':             {'menu-item'},
    'field-assertion':       {'field-assertion'},
}


def _detect_actual_element_type(page, label, container_prefix=''):
    """R3: 运行时 DOM 检查 — 确定 label 对应的实际表单元素类型。

    在 KB/discovery 全部 count=0 时调用。通过 JS 查找 label 附近的表单元素，
    返回实际 tagName 映射的 KB 类型。

    Returns: KB canonical type string or None
    """
    if not label:
        return None
    try:
        # Escape for JS string literal safety
        # Order matters: escape backslash FIRST, then single quote
        safe_label = label.replace('\\', '\\\\').replace("'", "\\'")
        safe_prefix = container_prefix.replace('\\', '\\\\').replace("'", "\\'")
        result = page.evaluate(f"""() => {{
            const prefix = "{safe_prefix}";
            const labelText = "{safe_label}";

            // Build XPath to find label text nodes
            const xpath = prefix
                ? prefix + "//*[contains(text(),'" + labelText + "')]"
                : "//*[contains(text(),'" + labelText + "')]";

            const nodes = document.evaluate(
                xpath, document, null,
                XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
            );

            for (let i = 0; i < nodes.snapshotLength; i++) {{
                const node = nodes.snapshotItem(i);
                // Skip hidden elements
                if (node.offsetParent === null && node.getClientRects().length === 0) continue;

                // Strategy 1: following-sibling (up to 3 siblings)
                let sibling = node.nextElementSibling;
                for (let j = 0; j < 3 && sibling; j++) {{
                    if (sibling.querySelector('textarea') || sibling.tagName === 'TEXTAREA')
                        return 'textarea';
                    const sel = sibling.querySelector('.el-select') ||
                                (sibling.classList && sibling.classList.contains('el-select') ? sibling : null);
                    if (sel) return 'select';
                    const dateEl = sibling.querySelector('.el-date-editor');
                    if (dateEl) return 'date';
                    const inp = sibling.querySelector('input:not([type=hidden])') ||
                                (sibling.tagName === 'INPUT' ? sibling : null);
                    if (inp) return 'input';
                    sibling = sibling.nextElementSibling;
                }}

                // Strategy 2: el-form-item parent structure
                const formItem = node.closest('.el-form-item');
                if (formItem) {{
                    const content = formItem.querySelector('.el-form-item__content');
                    if (content) {{
                        if (content.querySelector('textarea')) return 'textarea';
                        if (content.querySelector('.el-select')) return 'select';
                        if (content.querySelector('.el-date-editor')) return 'date';
                        if (content.querySelector('input:not([type=hidden])')) return 'input';
                    }}
                }}
            }}
            return null;
        }}""")
        if result:
            return _TAG_TO_KB_TYPE.get(result)
    except Exception:
        pass
    return None


def execute_step(page, step, pages_dict, data_dict, steps_so_far, discovery_data=None, project_dir=None,
                 is_new_page_context=False, container_context=None):
    """Execute a single case step in the browser.

    Args:
        is_new_page_context: True if we're on a different page than baseline (7.10 fix)
        container_context: 上一个步骤检测到的容器类型（dialog/drawer），当本次检测失败时作为 fallback

    Returns: (verified_locator, container_type, skipped, is_best_guess, hit_source)
             hit_source: 'discovery' | 'kb' | 'original' | 'fallback' | None
    """
    is_best_guess = False  # R5: set True when KB best-guess locator is used
    hit_source = None  # Track which candidate source succeeded
    keyword = step.get('keyword', '')
    params = step.get('params', {})
    desc = step.get('desc', '')

    if keyword in NO_VERIFY_KEYWORDS:
        # open_url / refresh must still be executed so we navigate to the right page
        if keyword == 'open_url':
            url = params.get('url', '') if isinstance(params, dict) else ''
            if url:
                url = resolve_var(url, data_dict)
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    _smart_wait_after_action(page)
                except Exception as e:
                    print(f"    [ERROR] open_url failed: {str(e)[:80]}")
        elif keyword == 'refresh':
            try:
                page.reload(wait_until='domcontentloaded', timeout=30000)
                _smart_wait_after_action(page)
            except Exception as _e:
                print(f"    [WARN] page.reload 失败: {_e}")
        return None, None, False, False, None

    # Skip assertions (Phase 9 responsibility)
    # BUG-4b: added except_element_count (assertion keyword with locator, not for Phase 6)
    if keyword in ('except_to_be_visible', 'except_to_have_text',
                   'except_to_have_value', 'except_element_count'):
        return None, None, False, False, None

    # P2-3: l3_call is expanded in the caller — skip here
    if keyword in L3_KEYWORDS:
        return None, None, False, False, None

    # V5: Custom L3 workflow names are also expanded in the caller
    if project_dir:
        _wf_cache = _load_l3_workflows(project_dir)
        if keyword in _wf_cache:
            return None, None, False, False, None

    # Extract locator
    locator = ''
    if isinstance(params, dict):
        locator = params.get('locator', '')
    if not locator:
        return None, None, False, False, None

    # BUG-7 fix: save raw locator reference before resolution for suffix detection
    raw_locator_ref = locator

    # Resolve variable references
    locator = resolve_locator(params, pages_dict)

    # Extract label from desc for KB lookup
    # BUG-4 D1 fix: 增加「」匹配（中文角括号在测试用例中极为常见）
    # 匹配: ASCII “, 左弯引号 U+201C, 右弯引号 U+201D, 左角括号 U+300C
    # F3: 提取所有引号对，取最后一个（实际操作对象）
    # 单引号对: re.findall[-1] 与 re.search 结果相同，零影响
    # 多引号对: “点击「第」一条记录的「更多」按钮” → ['第', '更多'] → '更多'
    _all_labels = re.findall(r'["\'“”「]([^"\'“”「」]+)["\'“”」]', desc)
    label = _all_labels[-1] if _all_labels else ''

    # D4: Enhanced element type inference (unified in _element_types)
    # BUG-3 fix: can now produce 'table-action-button'
    # BUG-5 fix: can now produce 'detail-link'
    # BUG-7 fix: pass locator_ref for _select/_editable suffix detection
    elem_type = _infer_elem_type(keyword, desc, locator_ref=raw_locator_ref)

    # Fix-2b-A: 类型推断 + discovery 交叉验证
    # _infer_elem_type 是纯函数（不依赖 discovery），对"编辑/删除/查看/详情"
    # 无条件返回 table-action-button。但同一文本在不同模块可能是工具栏按钮或行按钮。
    # 用 discovery 数据交叉验证：如果 label 在 buttons 区但不在 row_buttons 区，修正为 button。
    if elem_type == 'table-action-button' and discovery_data and label:
        _lp = discovery_data.get('list_page', {})
        _disc_containers = discovery_data.get('containers', [])
        _get_lbl = lambda e: (e.get('text', '') or e.get('label', '')
                              or e.get('name', ''))
        # 检查 row_buttons（list_page + containers 内的行按钮）
        _in_row_btns = any(
            _get_lbl(e) == label
            for e in _lp.get('row_buttons', [])
        )
        if not _in_row_btns:
            # 也搜索 containers 中的元素（行按钮可能在容器内）
            _in_row_btns = any(
                _get_lbl(e) == label
                for c in _disc_containers
                for e in c.get('elements', [])
                if (e.get('type', '') == 'table-action-button'
                    or e.get('is_row_button', False))
            )
        _in_btns = any(
            _get_lbl(e) == label
            for e in _lp.get('buttons', [])
        )
        if not _in_row_btns and _in_btns:
            print(f"    [TYPE-CORRECTION] '{desc}' label='{label}': "
                  f"table-action-button → button "
                  f"(discovery: in buttons, not in row_buttons)")
            elem_type = 'button'

    # Detect current visible containers (7.10: skip if on new page — no container context)
    # BUG-1b 修复：容器检测提前到 discovery 查找之前，传入 preferred_container
    visible_containers = detect_visible_containers(page) if not is_new_page_context else []
    current_ct = None
    if visible_containers:
        for ct in CONTAINER_TYPES:
            if ct in visible_containers:
                current_ct = ct
                break

    # 容器上下文 fallback：当 detect_visible_containers 返回空但有上一步传递的容器上下文时使用
    if current_ct is None and container_context and not is_new_page_context:
        current_ct = container_context
        print(f"    [CONTEXT] detect_visible_containers 返回空，使用上次容器上下文: {container_context}")

    # ── 统一兜底前缀计算（M11/R5 共用）──
    # 规则：确认类按钮 → el-dialog | 新页面 → 无前缀 | 其他 → current_ct 优先，默认 drawer
    if is_new_page_context:
        _fallback_prefix = 'none'
        _fallback_prefix_str = ''
    elif label in DIALOG_CONFIRM_LABELS:
        _fallback_prefix = 'dialog'
        _fallback_prefix_str = CONTAINER_XPATH.get('dialog', '')
    else:
        _fallback_prefix = current_ct if current_ct else 'drawer'
        _fallback_prefix_str = CONTAINER_XPATH.get(_fallback_prefix, '')

    # Build candidate locators
    # Priority: KB → Discovery → Original (stable order, reverted from Discovery-first)
    candidates = []

    # M9: 占位符检测 — xpath=[待确认] 不是真实 locator，跳过作为候选
    is_placeholder = locator in ('xpath=[待确认]', '[待确认]')

    # 优先级 0: KB templates (highest priority — stable, universal XPath patterns)
    if label:
        kb_locators = _get_kb_locators(elem_type, label)
        for kb_xpath in kb_locators:
            candidates.append((kb_xpath, 'kb'))

    # 优先级 1: Discovery locator (Phase 4 verified)
    discovery_ct = None
    _discovery_verified = False  # Fix-6 条件：跟踪 discovery 是否已验证
    if discovery_data and label:
        disc_locator, discovery_ct = _find_in_discovery(
            discovery_data, label, preferred_container=current_ct,
            elem_type=elem_type)
        if disc_locator:
            _discovery_verified = True  # _find_in_discovery 只返回 verified=true 的元素
            disc_raw = (disc_locator.replace('xpath=', '')
                        if disc_locator.startswith('xpath=')
                        else disc_locator)
            # 去重（KB 可能和 discovery 一样）
            if not any(c[0] == disc_raw for c in candidates):
                candidates.append((disc_raw, 'discovery'))

    # F2: candidates 为空时，将有效 locator 加入候选
    #
    # 触发条件（全部满足）:
    #   1. locator 非未解析变量（不以 ${ 开头）
    #   2. 非 [待确认] 占位符
    #   3. 非空且长度合理
    #
    # Fix-6: 始终将原始 locator 加入候选池尾部作为安全网（去掉 candidates==0 条件）
    # 原因：即使 KB 产生了候选（可能用错误 label 生成），原始 locator 来自 Phase 5
    #       的 _track_field，基于 Excel 单元格值构建，比 KB 候选更可靠。
    # 不影响 KB 优先级：原始 locator 在候选尾部，KB/discovery 候选优先验证。
    if (not locator.startswith('${')       # guard 1: 非未解析变量
        and not is_placeholder             # guard 2: 非占位符
        and locator                        # guard 3a: 非空
        and len(locator) > 5):             # guard 3b: 非退化值
        _resolved_bare = (locator.replace('xpath=', '', 1)
                          if locator.startswith('xpath=') else locator)
        if not any(c[0] == _resolved_bare for c in candidates):    # Fix-6: 去重
            candidates.append((_resolved_bare, 'original'))   # Fix-6: 始终加入尾部作为安全网

    # Priority 3: Click-type wildcard fallback — last resort for click steps only
    # Only applies to button/table-action-button/detail-link types.
    # Excluded: input-generic, el-select, textarea, tab, checkbox, etc.
    # Guarded by [1] to avoid count>1 strict mode violation.
    if elem_type in CLICK_EXPAND_TYPES and label:
        _click_fb = f"(//*[contains(text(),'{label}')])[1]"
        if not any(c[0] == _click_fb for c in candidates):
            candidates.append((_click_fb, 'kb-fallback'))

    # Verify candidates × prefixes (P1-2: el-select input gets container prefix normally)
    # Split candidates into xpaths and sources for return_index lookup
    xpaths = [c[0] for c in candidates]
    sources = {i: c[1] for i, c in enumerate(candidates)}

    verified_locator, matched_prefix, count, matched_index = verify_locator_candidates(
        page, xpaths, container_type=current_ct, discovery_ct=discovery_ct,
        is_el_select_option=False, return_index=True
    )

    # Determine hit source
    hit_source = sources.get(matched_index) if matched_index is not None else None

    # R4: Multi-type retry — collect alternative types when initial type fails
    # Sources: keyword/desc inference, DOM check (R3), locator_ref suffix
    # Weight only affects try order, no type is excluded.
    if not verified_locator and label:
        _alt_types = [elem_type]  # primary type first (already tried)

        # Source: keyword/desc re-inference (already captured in elem_type, skip dup)
        # Source: DOM check (R3 — highest priority, only when fast path failed)
        # BUG-11: 类型守卫 — R3 结果必须通过兼容性检查才能插入 _alt_types
        _dom_type = _detect_actual_element_type(page, label, CONTAINER_XPATH.get(current_ct, '') if current_ct else '')
        if _dom_type and _dom_type not in _alt_types:
            _compat_set = _R3_TYPE_COMPAT.get(elem_type, {elem_type})
            if _dom_type in _compat_set:
                _alt_types.insert(1, _dom_type)  # insert after primary (DOM = high priority)
                print(f"    [DOM-CHECK] inferred={elem_type}, DOM detected={_dom_type}")
            else:
                print(f"    [DOM-CHECK] REJECTED: inferred={elem_type}, "
                      f"DOM detected={_dom_type} (incompatible with {_compat_set})")

        # Source: common cross-type confusions (input↔textarea)
        if elem_type == 'input-generic' and 'textarea-generic' not in _alt_types:
            _alt_types.append('textarea-generic')
        elif elem_type == 'textarea-generic' and 'input-generic' not in _alt_types:
            _alt_types.append('input-generic')
        # Source: button → table-action-button fallback
        # 仅遍历结构泛化的按钮 KB（所有 pattern 含 {label}，不会假阳性）。
        # download-button / search-button 属于特殊场景，由 Phase 5 类型推断
        # 根据 Excel 描述关键词（导出/下载/搜索/查询）直接匹配，不参与 R4 遍历。
        elif elem_type == 'button':
            if 'table-action-button' not in _alt_types:
                _alt_types.append('table-action-button')
        # Fix-2b-B: 反向回退 — 子类型 → button
        # 当 _infer_elem_type 返回子类型（如 table-action-button）但 KB 和 discovery
        # 均未验证通过时，尝试基类 button 作为安全网。
        # 与 Fix-2b-A 互补：A 在入口处修正类型，B 在 R4 重试时兜底。
        elif elem_type in ('table-action-button', 'search-button', 'download-button', 'close-button'):
            if 'button' not in _alt_types:
                _alt_types.append('button')

        # Try each alternative type (skip first = already tried in fast path)
        for _alt_type in _alt_types[1:]:
            _alt_candidates = []

            # KB locators for this type - Priority 0 (highest)
            _alt_kb = _get_kb_locators(_alt_type, label)
            for _alt_kb_xpath in _alt_kb:
                _alt_candidates.append((_alt_kb_xpath, 'kb'))

            # Discovery locator (with relaxed type guard) - Priority 1
            if discovery_data:
                _alt_disc, _alt_disc_ct = _find_in_discovery(
                    discovery_data, label, preferred_container=current_ct,
                    elem_type=_alt_type)
                if _alt_disc:
                    _alt_disc_raw = (_alt_disc.replace('xpath=', '')
                                    if _alt_disc.startswith('xpath=') else _alt_disc)
                    # 去重
                    if not any(c[0] == _alt_disc_raw for c in _alt_candidates):
                        _alt_candidates.append((_alt_disc_raw, 'discovery'))

            # Priority 3: Click-type wildcard fallback — last resort for click steps only
            if _alt_type in CLICK_EXPAND_TYPES and label:
                _click_fb = f"(//*[contains(text(),'{label}')])[1]"
                if not any(c[0] == _click_fb for c in _alt_candidates):
                    _alt_candidates.append((_click_fb, 'kb-fallback'))

            if not _alt_candidates:
                continue

            # Split into xpaths and sources
            _alt_xpaths = [c[0] for c in _alt_candidates]
            _alt_sources = {i: c[1] for i, c in enumerate(_alt_candidates)}

            _alt_vl, _alt_mp, _alt_cnt, _alt_idx = verify_locator_candidates(
                page, _alt_xpaths, container_type=current_ct,
                discovery_ct=discovery_ct, is_el_select_option=False,
                return_index=True
            )
            if _alt_vl:
                verified_locator = _alt_vl
                matched_prefix = _alt_mp
                elem_type = _alt_type  # update type for subsequent operations
                hit_source = _alt_sources.get(_alt_idx)
                print(f"    [TYPE-CORRECT] '{desc}' → {_alt_type} "
                      f"(corrected from initial type)")
                break

    if not verified_locator:
        # D5: Try KB fallback before giving up
        if label:
            fb = kb_fallback(elem_type, label, label)
            if fb and fb.get('locator'):
                fb_locator = inject_hidden_filter(fb['locator'])
                _fb_result = _verify_count_or_first(page, fb_locator)
                if _fb_result:
                    verified_locator = _fb_result
                    print(f"    [KB-FALLBACK] '{desc}' → {fb.get('strategy', 'unknown')}")

        # Scheme 4: 跨类型 fallback — input-generic 失败时尝试 textarea-generic
        # 解决 Phase 5 将 textarea 字段误标为 _input 后缀的场景 D
        if not verified_locator and label and elem_type == 'input-generic':
            _CROSS_TYPE_ALIASES = ['textarea-generic']
            for _cross_type in _CROSS_TYPE_ALIASES:
                fb_cross = kb_fallback(_cross_type, label, label)
                if fb_cross and fb_cross.get('locator'):
                    fb_locator = inject_hidden_filter(fb_cross['locator'])
                    _fb_result = _verify_count_or_first(page, fb_locator)
                    if _fb_result:
                        verified_locator = _fb_result
                        print(f"    [KB-FALLBACK] '{desc}' → {_cross_type} "
                              f"(cross-type fallback from {elem_type})")
                        break

        # D1: Structured fallback rules if KB fallback also failed
        if not verified_locator:
            if label in DIALOG_CONFIRM_LABELS:
                # 确认/取消按钮 → default el-dialog prefix
                fallback_xpath = f"//div[contains(@class,'el-dialog')]//button[contains(.,'{label}')]"
                fallback_xpath = inject_hidden_filter(f"xpath={fallback_xpath}")
                _fb_result = _verify_count_or_first(page, fallback_xpath)
                if _fb_result:
                    verified_locator = _fb_result
                    print(f"    [FALLBACK] '{desc}' → dialog-confirm")
            elif candidates:
                # M11: KB locator优先兜底，candidates[0] 最后回退
                # 使用函数开头计算的统一前缀变量 _fallback_prefix / _fallback_prefix_str

                # M11 修复: 优先用 KB locator 兜底，不用 candidates[0]
                _m11_resolved = False
                if label:
                    kb_locators = _get_kb_locators(elem_type, label)
                    for kb_loc in kb_locators:
                        fallback_xpath = inject_hidden_filter(
                            f"xpath={_fallback_prefix_str}{kb_loc}")
                        _fb_result = _verify_count_or_first(page, fallback_xpath)
                        if _fb_result:
                            verified_locator = _fb_result
                            print(f"    [FALLBACK] '{desc}' → KB-{elem_type} with {_fallback_prefix} prefix (M11)")
                            _m11_resolved = True
                            break

                    # Scheme 4 (M11): 跨类型 fallback — input-generic 失败时尝试 textarea-generic
                    if not _m11_resolved and elem_type == 'input-generic':
                        for _cross_type in ('textarea-generic',):
                            cross_kb_locators = _get_kb_locators(_cross_type, label)
                            for kb_loc in cross_kb_locators:
                                fallback_xpath = inject_hidden_filter(
                                    f"xpath={_fallback_prefix_str}{kb_loc}")
                                _fb_result = _verify_count_or_first(page, fallback_xpath)
                                if _fb_result:
                                    verified_locator = _fb_result
                                    print(f"    [FALLBACK] '{desc}' → KB-{_cross_type} "
                                          f"with {_fallback_prefix} prefix (M11 cross-type)")
                                    _m11_resolved = True
                                    break
                            if _m11_resolved:
                                break

                # KB locator 全部失败时，回退到第一个 KB candidate（原 M11 逻辑）
                if not _m11_resolved:
                    # BUG-14 fix: candidates 是 list[tuple]，需解包取 c[0] xpath 和 c[1] source
                    first_kb_candidate = next((c[0] for c in candidates if c[1] == 'kb'), None)
                    if first_kb_candidate is None:
                        first_kb_candidate = candidates[0][0] if candidates else None
                    if first_kb_candidate:
                        fallback_xpath = inject_hidden_filter(
                            f"xpath={_fallback_prefix_str}{first_kb_candidate}")
                        _fb_result = _verify_count_or_first(page, fallback_xpath)
                        if _fb_result:
                            verified_locator = _fb_result
                            print(f"    [FALLBACK] '{desc}' → first-kb-candidate with {_fallback_prefix} prefix (M11)")

        # Fix-6: 仅当 discovery 已验证时保留 Phase 5 原始 locator
        # 设计意图（三层优先级）：
        #   1. KB 验证成功 → 使用 KB locator（主验证路径）
        #   2. KB 失败 + discovery 已验证 → 保留原始值（discovery 已验证的同值候选已尝试）
        #   3. KB 失败 + discovery 未验证 → R5 KB 兜底回写（比可能错误的原始值更可靠）
        if not verified_locator and _discovery_verified:
            _orig_ref = _extract_locator_ref(step)
            _orig_xpath = _get_original_xpath(_orig_ref, pages_dict) if _orig_ref else ''
            if (_orig_xpath
                and _orig_xpath not in ('[待确认]', '')
                and len(_orig_xpath) > 10
                and not _orig_xpath.startswith('${')):
                _preserved_locator = (f"xpath={_orig_xpath}"
                                   if not _orig_xpath.startswith('xpath=')
                                   else _orig_xpath)
                # 防御性：count>1 时自动 [1] 收窄（与 M11/R5 兜底路径一致）
                # 场景：discovery 已验证 count=1，但 Phase 6 验证时因表格异步
                # 加载等原因 count>1，运行时可能仍多匹配
                _preserved_narrowed = _verify_count_or_first(page, _preserved_locator)
                if _preserved_narrowed:
                    verified_locator = _preserved_narrowed
                    is_best_guess = True
                    _p_note = ('已 [1] 收窄' if _preserved_narrowed != _preserved_locator
                               else 'count=1')
                    print(f"    [PRESERVED] '{desc}' → 保留 Phase 5 原始 locator "
                          f"(discovery verified, {_p_note})")
                else:
                    # count==0：加 [1] 防御 Phase 9 strict mode
                    # 场景：验证时元素不可见（count=0），Phase 9 运行时前序步骤执行后元素出现
                    # 但可能出现多个匹配（如表格行按钮），[1] 防止 strict mode violation
                    _raw = (_preserved_locator.replace('xpath=', '', 1)
                            if _preserved_locator.startswith('xpath=')
                            else _preserved_locator)
                    verified_locator = f"xpath=({_raw})[1]"
                    is_best_guess = True
                    print(f"    [PRESERVED] '{desc}' → 保留 Phase 5 原始 locator "
                          f"(discovery verified, count=0, [1] 防御)")

        if not verified_locator:
            # ── R5: KB locator 兜底回写（规则 6 修复）──
            # 即使 count=0，也用 KB locator 回写（比 [待确认] 更有价值）
            # 理由：KB locator 结构正确，count=0 通常因为容器未打开，
            #       Phase 9 运行时前序步骤正确执行后大概率能命中。
            _bg_locator = None
            _bg_source = None

            # 使用函数开头计算的统一前缀变量 _fallback_prefix_str

            # 优先级 1: KB 模板 locator（推断类型 + 容器前缀）
            if label:
                kb_locs = _get_kb_locators(elem_type, label)
                if kb_locs:
                    _bg_locator = inject_hidden_filter(
                        f"xpath={_fallback_prefix_str}{kb_locs[0]}")
                    _bg_source = f'KB-{elem_type}'

            # 优先级 2: KB fallback 函数
            if not _bg_locator and label:
                fb = kb_fallback(elem_type, label, label)
                if fb and fb.get('locator'):
                    _bg_raw = fb['locator'].replace('xpath=', '') if fb['locator'].startswith('xpath=') else fb['locator']
                    _bg_locator = inject_hidden_filter(
                        f"xpath={_fallback_prefix_str}{_bg_raw}")
                    _bg_source = f'KB-fallback-{elem_type}'

            # 优先级 3: 第一个 KB candidate 的 xpath（优先），否则第一个 candidate
            if not _bg_locator and candidates:
                _first_kb_c = next((c[0] for c in candidates if c[1] == 'kb'), None)
                _fallback_xpath = _first_kb_c if _first_kb_c else candidates[0][0]
                _bg_locator = inject_hidden_filter(
                    f"xpath={_fallback_prefix_str}{_fallback_xpath}")
                _bg_source = 'first-kb-candidate' if _first_kb_c else 'first-candidate'

            if _bg_locator:
                # 防御性：count>1 时自动 [1] 收窄（与 M11 兜底路径一致）
                # 场景：表格异步加载未完成时 count=0，加载完 count>1（行按钮等）
                # 若不做 [1] 收窄，Phase 9 运行时 strict mode violation
                _bg_narrowed = _verify_count_or_first(page, _bg_locator)
                if _bg_narrowed:
                    # count==1 或 count>1 已收窄 → 使用收窄后的 locator
                    verified_locator = _bg_narrowed
                    _bg_note = ('已 [1] 收窄' if _bg_narrowed != _bg_locator
                                else 'count=1')
                else:
                    # count==0：加 [1] 防御 Phase 9 strict mode（与 Fix-6 对齐）
                    # 场景：验证时元素不可见，Phase 9 运行时可能出现多个匹配
                    _raw = (_bg_locator.replace('xpath=', '', 1)
                            if _bg_locator.startswith('xpath=')
                            else _bg_locator)
                    verified_locator = f"xpath=({_raw})[1]"
                    _bg_note = 'count=0, [1] 防御'
                is_best_guess = True
                print(f"    [UNVERIFIED] '{desc}' → {_bg_source} "
                      f"({_bg_note}, 兜底回写)")
            else:
                # ── R6: KB 已穷尽，打印警告 ──
                # R5 失败意味着 KB 模板 + KB fallback + 第一个 candidate 全部 count=0
                # probe_element() 深度探测与 R5 的 KB 遍历重复，不再调用
                if is_placeholder:
                    print(f"    [WARN] '{desc}' → KB 已穷尽，locator 仍为 [待确认]，"
                          f"请检查前序步骤是否正确打开了容器")

                # ── R6: AI 兜底探测（新增）──
                if (_HAS_AI_PROBE and is_placeholder and label
                        and page is not None):
                    _r6 = _ai_probe_locator(
                        page, step, label, elem_type, current_ct,
                        steps_so_far, container_context, inject_hidden_filter)
                    if _r6:
                        verified_locator = _r6['locator']
                        is_best_guess = _r6['is_best_guess']
                        hit_source = _r6['hit_source']

                # 走原有逻辑
                if not verified_locator:
                    is_best_guess = False
                    hit_source = None
                    if is_placeholder:
                        print(f"    [WARN] 占位符步骤 '{desc}' 验证失败 — "
                              f"KB 和 discovery 均未匹配，请检查前序步骤是否正确打开了容器")
                    else:
                        print(f"    [FALLBACK] '{desc}' — no candidate matched, KB 无覆盖")
                    return None, current_ct, False, False, hit_source

    # Execute the step
    try:
        # click_select_option: 引擎内部处理 el-select 全流程，
        # Phase 6 只需验证触发器 locator 存在 + 点击展开
        if keyword == 'click_select_option':
            page.locator(verified_locator).click(timeout=5000)  # 方案 B: 严格模式
            # 验证下拉面板出现（证明触发器有效）
            panel_xpath = ("xpath=//div[contains(@class,'el-select-dropdown') "
                           "and not(contains(@style,'display: none'))]")
            try:
                page.locator(panel_xpath).first.wait_for(
                    state='visible', timeout=3000)
            except Exception:
                pass  # 面板未出现不阻断验证
            # 关闭下拉（点空白区域）
            try:
                page.locator("xpath=//body").click(position={'x': 10, 'y': 10})
            except Exception:
                pass
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        if 'click' in keyword:
            # Check destructive operation protection
            if keyword in ('confirm_dialog', 'confirm_delete') or ('确' in desc and '定' in desc):
                if should_skip_confirm(steps_so_far):
                    print(f"    [SKIP] '{desc}' — destructive operation protection")
                    return verified_locator, matched_prefix or current_ct, True, is_best_guess, hit_source

            # BUG-9: For row buttons (ancestor::tbody), hover the row first to reveal hidden buttons
            if 'tbody' in verified_locator:
                try:
                    row = page.locator("xpath=(//tr[contains(@class,'el-table__row')])[1]")
                    if row.count() > 0:
                        row.first.hover()
                        page.wait_for_timeout(500)
                except Exception:
                    pass  # hover failure is non-fatal, click may still succeed

            # M10: detail-link 类型验证时检查 tagName（防止匹配到 <th> 表头）
            if elem_type == 'detail-link' and verified_locator:
                try:
                    _tag = page.locator(verified_locator).first.evaluate(
                        "e => e.tagName.toLowerCase()")
                    if _tag == 'th':
                        print(f"    [WARN] M10: '{desc}' locator匹配到<th>表头，"
                              f"预期<td>或链接元素")
                except Exception:
                    pass  # tag check 失败不影响主流程

            page.locator(verified_locator).click(timeout=5000)  # 方案 B: 严格模式
            # P3-2: smart wait replaces fixed 500ms (含 DOM 稳定检测)
            _smart_wait_after_action(page)

            # ── 容器探测：每次 click 后都执行（排除下拉框 click_select_option）──
            # 原因：任何 click 都可能打开容器（确定→二次确认弹窗，删除→确认弹窗等）
            #
            # 时序：
            #   1. detect_visible_containers() — 快速检查（~5ms），如果容器已渲染完就直接返回
            #   2. _wait_for_container_after_click() — Playwright wait_for（事件驱动，容器一出现立即返回）
            #      场景：API 回调触发的容器（先 networkidle → 再渲染），_smart_wait 可能早于容器出现
            #
            # 对于不打开容器的 click（搜索/查询等），wait_for 在 2s 后超时返回 None，
            # 加上 _smart_wait 8s，单个 click 最多 ~10s。
            new_containers = detect_visible_containers(page)
            if not new_containers:
                # 快速检查未检测到 → 增强等待（容器可能在 API 回调后异步出现）
                container_ct = _wait_for_container_after_click(page)
                if container_ct:
                    _wait_for_dom_stable(page, timeout_ms=3000)
                    return verified_locator, container_ct, False, is_best_guess, hit_source
            else:
                # 快速检查已检测到容器 → 等待内部表单渲染
                _wait_for_dom_stable(page, timeout_ms=3000)
                for ct in CONTAINER_TYPES:
                    if ct in new_containers:
                        return verified_locator, ct, False, is_best_guess, hit_source
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif 'fill' in keyword:
            value = params.get('value', '') if isinstance(params, dict) else ''
            value = resolve_var(value, data_dict)
            if not value:
                value = PROBE_FILL_VALUES.get('input', PROBE_ISOLATION_PREFIX + 'P3f')
            # P2-6: prepend isolation prefix if not already present
            if not value.startswith(PROBE_ISOLATION_PREFIX):
                value = PROBE_ISOLATION_PREFIX + value
            # 1c: iframe 填充支持 — 检测 locator 是否指向 iframe 元素
            _vl_clean = verified_locator.replace('xpath=', '') if verified_locator.startswith('xpath=') else verified_locator
            if 'iframe' in _vl_clean.lower():
                try:
                    iframe_el = page.locator(verified_locator)
                    if iframe_el.count() > 0:
                        frame = iframe_el.first.content_frame()
                        if frame:
                            editor = frame.locator(
                                'body[contenteditable="true"], body.mce-content-body, '
                                'body.ql-editor, textarea, [role="textbox"]'
                            )
                            if editor.count() > 0:
                                editor.first.fill(value, timeout=5000)
                                print(f"    [OK] 1c iframe fill: '{desc}'")
                                return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source
                            else:
                                print(f"    [WARN] iframe 内未找到可编辑元素，尝试标准 fill")
                        else:
                            print(f"    [WARN] 无法进入 iframe context，尝试标准 fill")
                except Exception as e:
                    print(f"    [WARN] iframe fill 异常: {str(e)[:80]}，尝试标准 fill")
            # Perf: 对 el-select 触发器（readonly input 或 div），快速检测并跳过 fill
            # 避免 5 秒超时浪费（Phase 6 目标是验证 locator，不是测试 fill 功能）
            try:
                el = page.locator(verified_locator).first
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                if tag != 'textarea':
                    is_readonly = el.evaluate(
                        "e => e.hasAttribute('readonly') || e.getAttribute('role') === 'combobox'"
                        " || e.closest('.el-select') !== null"
                    )
                    if is_readonly:
                        # readonly el-select 触发器 — 验证 locator 存在即可，跳过 fill
                        return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source
            except Exception:
                pass  # 检测失败则走正常 fill 流程

            page.locator(verified_locator).fill(value, timeout=5000)
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword in ('frame_fill_value', 'frame_click'):
            # iframe operations — skip for now
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'wait_for_element_visible':
            page.locator(verified_locator).first.wait_for(state='visible', timeout=5000)
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'wait_for_element_hidden':
            try:
                page.locator(verified_locator).first.wait_for(state='hidden', timeout=5000)
            except Exception:
                pass
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'get_text':
            try:
                text = page.locator(verified_locator).first.text_content(timeout=3000)
            except Exception:
                text = ''
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'get_element_count':
            try:
                cnt = page.locator(verified_locator).count()
            except Exception:
                cnt = 0
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        else:
            # Unknown keyword — just verify locator exists
            count = page.locator(verified_locator).count()
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

    except Exception as e:
        print(f"    [ERROR] '{desc}': {str(e)[:100]}")
        return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source


# ============================================================================
# Pages YAML writeback
# ============================================================================

def _extract_locator_ref(step):
    """从 step params 中提取 ${group.field} 引用（P3f-1 修复）"""
    params = step.get('params', {})
    locator = params.get('locator', '') if isinstance(params, dict) else ''
    m = re.match(r'^\$\{([^}]+)\}$', locator)
    if m:
        return m.group(1)
    return None


def _get_original_xpath(ref, pages_dict):
    """获取 pages_dict 中的原始 xpath（P3f-1 修复）"""
    if not ref:
        return ''
    parts = ref.split('.', 1)
    if len(parts) != 2:
        return ''
    group, field = parts
    group_data = pages_dict.get(group, {})
    if not isinstance(group_data, dict):
        return ''
    val = group_data.get(field, '')
    if isinstance(val, str):
        return val.replace('xpath=', '')
    return ''


def _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators,
                            is_best_guess=False, marker_override=None):
    """P3f-1: 存储验证通过的 locator 到 verified_locators 字典

    修复: Issue 2b — 当原 locator 有容器前缀但验证版本无前缀时，
    不再跳过写回，而是将验证通过的裸 XPath 写回到列表页 group 的对应字段。

    Args:
        is_best_guess: R5 — True when locator is KB best-guess (count=0), sets [UNVERIFIED] marker
    """
    ref = _extract_locator_ref(step)
    if not ref:
        return
    orig_xpath = _get_original_xpath(ref, pages_dict)
    # 提取 verified locator 的 xpath 部分（去掉 xpath= 前缀）
    v_xpath = v_loc.replace('xpath=', '') if isinstance(v_loc, str) and v_loc.startswith('xpath=') else v_loc
    # 只在 locator 有变化时存储（减少不必要的回写）
    if orig_xpath and v_xpath and v_xpath != orig_xpath:
        CONTAINER_MARKERS = ('el-dialog', 'el-drawer', 'el-message-box')
        CONTAINER_GROUP_MARKERS = ('_drawer_', '_dialog_', '_messagebox_',
                                    '_message_box_')
        orig_has_container = any(m in orig_xpath for m in CONTAINER_MARKERS)
        new_has_container = any(m in v_xpath for m in CONTAINER_MARKERS)
        if orig_has_container and not new_has_container:
            # 方案B: 禁止 DOWNGRADED 覆盖 — 原始有容器前缀但验证后没有，保留原始版本
            # 根因：容器检测时序问题导致 Phase 6 验证时 count==1（dialog 未完全渲染），
            # 但 Phase 9 运行时 dialog 已完全打开，count==2 → strict mode violation
            print(f"    [PRESERVED-SCOPED] '{ref}' — 原始 locator 有容器前缀，"
                  f"验证后没有，保留原始版本，不降级")
            return
        # M10: 升级方向 — 原 locator 无前缀，验证通过的有容器前缀
        elif not orig_has_container and new_has_container:
            # 确定容器类型标记
            upgrade_ct = None
            for cm in CONTAINER_MARKERS:
                if cm in v_xpath:
                    upgrade_ct = cm.replace('el-', '')
                    break
            marker = f'[UPGRADED: {upgrade_ct}]' if upgrade_ct else '[UPGRADED]'
            verified_locators[ref] = {
                'locator': v_loc,
                'marker': marker,
                'container_type': v_ct,
            }
            print(f"    {marker} '{ref}': 无前缀→{upgrade_ct or '容器'}前缀")
            return
        verified_locators[ref] = {
            'locator': v_loc,
            'marker': marker_override or ('[UNVERIFIED]' if is_best_guess else None),
            'container_type': v_ct,
        }


def update_pages_yaml(project_dir, verified_locators, module=None):
    """Update pages YAML with verified locators.

    verified_locators: {group.field: {locator, marker, container_type, is_new_field}}
    marker: None = verified, '[UPGRADED: ct]' = 升级, '[DOWNGRADED]' = 降级,
            '[UNVERIFIED]' = KB fallback, '[FALLBACK]' = fallback
    #7: marker 写入引号外作为 YAML 注释（如 ``# [UPGRADED: drawer]``），
        不嵌入 locator 值内（避免破坏 XPath 解析）
    is_new_field: True = append new field to group (cross-group writeback create)
    module: BUG-5 — when specified, restrict writeback to this module's pages directory
    """
    pages_dir = os.path.join(project_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return

    # BUG-5 + M8: Protect common_elements fields from writeback
    # M8: confirm_btn/cancel_btn 也纳入保护，防止跨模块 deep_merge 冲突
    # 不同模块的 common_elements.confirm_btn 会有不同容器前缀（drawer/dialog），
    # deep_merge 后最后加载的模块覆盖前面的，导致运行时容器定位错误
    PROTECTED_COMMON_FIELDS = {'success_text', 'error_text', 'loading_mask',
                                'confirm_btn', 'cancel_btn'}

    # BUG-5: Build module-scoped search directory
    if module:
        module_dir = module.replace('_', '-')
        search_root = os.path.join(pages_dir, module_dir)
        if not os.path.isdir(search_root):
            search_root = pages_dir  # fallback if module dir doesn't exist
    else:
        search_root = pages_dir

    # Build {filepath: {group: {field: new_locator}}}
    updates = {}
    # #7: marker 独立存储，不嵌入 locator 值（避免破坏 XPath 解析）
    field_markers = {}  # {filepath: {group: {field: marker_string}}}

    for ref, info in verified_locators.items():
        parts = ref.split('.', 1)
        if len(parts) != 2:
            continue
        group, field = parts
        locator = info.get('locator', '')
        marker = info.get('marker', '')
        is_new_field = info.get('is_new_field', False)

        # BUG-5: Protect common_elements fields from writeback
        if group == 'common_elements' and field in PROTECTED_COMMON_FIELDS:
            print(f"  [SKIP] Protected field common_elements.{field} — writeback not allowed")
            continue

        # Find which YAML file contains this group
        # F8: track all matching files to detect cross-module group name collisions
        # BUG-5: restrict search to module-scoped directory when module is specified
        matching_files = []
        for root, dirs, files in os.walk(search_root):
            for f in files:
                if f.endswith(('.yaml', '.yml')):
                    path = os.path.join(root, f)
                    try:
                        with open(path, encoding='utf-8') as fh:
                            data = yaml.safe_load(fh)
                        if isinstance(data, dict) and group in data:
                            matching_files.append(path)
                    except Exception:
                        pass
        if len(matching_files) > 1:
            # H6: 排序确保非 _ 前缀文件优先（elements.yaml > _fallback.yaml）
            matching_files.sort(key=lambda p: (0 if not os.path.basename(p).startswith('_') else 1, p))
            print(f"  [WARN] F8: group '{group}' found in {len(matching_files)} files: "
                  f"{[os.path.basename(p) for p in matching_files]}")
            print(f"         Using: {matching_files[0]} (non-underscore preferred)")
        for path in matching_files[:1]:  # use first match only
            if path not in updates:
                updates[path] = {}
            if group not in updates[path]:
                updates[path][group] = {}
            # #7: 存储干净的 locator，不嵌入 marker
            updates[path][group][field] = locator
            # M5: _select 写回时同步更新 _editable companion
            if field.endswith('_select'):
                editable_field = field[:-len('_select')] + '_editable'
                # 从 _select locator 生成 _editable locator（后置模式）
                raw_locator = locator
                if raw_locator.startswith('xpath='):
                    raw_locator = raw_locator[6:]
                editable_raw = _make_editable_locator_postfix(raw_locator)
                if editable_raw != raw_locator:  # 仅当实际修改了才同步
                    updates[path][group][editable_field] = f'xpath={editable_raw}'
            if marker:
                if path not in field_markers:
                    field_markers[path] = {}
                if group not in field_markers[path]:
                    field_markers[path][group] = {}
                field_markers[path][group][field] = marker

    # Write back
    for filepath, groups in updates.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for group, fields in groups.items():
                # 分离新字段和已有字段
                new_fields = {}
                existing_fields = {}
                for field, new_locator in fields.items():
                    ref_key = f"{group}.{field}"
                    info = verified_locators.get(ref_key, {})
                    if info.get('is_new_field', False):
                        new_fields[field] = new_locator
                    else:
                        existing_fields[field] = new_locator

                # 替换已有字段
                in_group = False
                group_end = -1
                for i, line in enumerate(lines):
                    stripped = line.rstrip()
                    if stripped.startswith(f'{group}:'):
                        in_group = True
                        continue
                    if in_group:
                        # Check if we've left the group (new top-level key)
                        if stripped and not stripped.startswith(' ') and not stripped.startswith('#'):
                            group_end = i
                            in_group = False
                            continue
                        for field, new_locator in existing_fields.items():
                            if stripped.lstrip().startswith(f'{field}:'):
                                # 防御: 拒绝回写 contains(text(),'') 废模板
                                if isinstance(new_locator, str) and "contains(text(),'')" in new_locator:
                                    print(f"  [WARN] 跳过废模板回写: {field} 包含 contains(text(),'')")
                                    continue
                                # Replace the line, preserving trailing comment
                                indent = len(line) - len(line.lstrip())
                                # Extract trailing comment after closing quote
                                # F1: 兼容单引号和双引号（_pages_writer 用单引号）
                                _comment = ''
                                _last_quote = max(line.rfind('"'), line.rfind("'"))
                                if _last_quote > 0:
                                    _after = line[_last_quote + 1:]
                                    _hash_idx = _after.find('#')
                                    if _hash_idx >= 0:
                                        _comment = _after[_hash_idx:].rstrip()
                                # #7: 清除旧版 marker，防止重复标注
                                if _comment:
                                    _comment = _OLD_MARKER_RE.sub('', _comment).strip()
                                # #7: marker 写入引号外作为 YAML 注释
                                _fmarker = field_markers.get(filepath, {}).get(group, {}).get(field, '')
                                _parts = []
                                if _comment:
                                    _parts.append(f"  {_comment}")
                                if _fmarker:
                                    _parts.append(f"  # {_fmarker}")
                                _final_comment = "".join(_parts)
                                scalar = _escape_yaml_scalar(new_locator)
                                lines[i] = f"{' ' * indent}{field}: {scalar}{_final_comment}\n"
                                break

                # 追加新字段到 group 末尾
                if new_fields:
                    insert_pos = group_end if group_end > 0 else len(lines)
                    for field, new_locator in new_fields.items():
                        # 防御: 拒绝回写 contains(text(),'') 废模板
                        if isinstance(new_locator, str) and "contains(text(),'')" in new_locator:
                            print(f"  [WARN] 跳过废模板回写: {field} 包含 contains(text(),'')")
                            continue
                        # #7: 新字段也添加 marker 作为 YAML 注释
                        _fmarker = field_markers.get(filepath, {}).get(group, {}).get(field, '')
                        _marker_part = f"  # {_fmarker}" if _fmarker else ""
                        scalar = _escape_yaml_scalar(new_locator)
                        new_line = f'  {field}: {scalar}{_marker_part}\n'
                        lines.insert(insert_pos, new_line)
                        insert_pos += 1

            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            print(f"  [OK] Updated: {filepath}")
        except Exception as e:
            print(f"  [ERROR] Failed to update {filepath}: {e}")

    # Post-processing: Apply hidden filters and strip not(ancestor::) exclusions
    # These functions were migrated from probe_from_pages.py and need to be called here
    print("\n[Post-processing] Applying hidden filters and cleaning up exclusions...")

    # Build pages_data and source_files for batch processing
    pages_data = load_pages(project_dir, module)
    source_files = {}
    for root, dirs, files in os.walk(pages_dir):
        for f in files:
            if f.endswith(('.yaml', '.yml')):
                path = os.path.join(root, f)
                try:
                    with open(path, encoding='utf-8') as fh:
                        data = yaml.safe_load(fh)
                    if isinstance(data, dict):
                        for group in data.keys():
                            if group != 'page_urls' and isinstance(data[group], dict):
                                source_files[group] = path
                except Exception:
                    pass

    # Apply hidden filters to all locators
    hidden_count = apply_hidden_filters_to_pages(pages_data, source_files, pages_dir)
    if hidden_count > 0:
        print(f"  R4.11: 补齐 {hidden_count} 个定位器的隐藏过滤属性")

    # Strip not(ancestor::) exclusions (R3.14)
    stripped_count = strip_not_ancestor_from_pages(pages_data, source_files, pages_dir)
    if stripped_count > 0:
        print(f"  R3.14: 清除 {stripped_count} 个定位器的 not(ancestor::) 排除")


# ============================================================================
# Main verification flow
# ============================================================================

def verify_project(project_dir, cookie, base_url, discovery_path=None, module=None, local_storage_override=None):
    """Main verification flow.

    1. Load all project files
    2. Open browser
    3. Execute each case step-by-step
    4. Verify locators
    5. Write back pages YAML
    """
    print(f"\n{'='*60}")
    print(f"[Verify] Project: {project_dir}")
    print(f"[Verify] URL: {base_url}")
    print(f"{'='*60}\n")

    # Load project files
    # F5: pass module for scoped page loading (prevents cross-module collisions)
    pages_dict = load_pages(project_dir, module=module)
    data_dict = load_data(project_dir)
    cases = load_cases(project_dir, module)

    # Load discovery data
    discovery_data = None
    _v7_flat = None  # G7: V7 展平回退数据（None = 非 V7 或未加载）
    _discovery_pages_by_url = {}  # V7: URL → discovery page mapping

    # C: 自动发现 discovery 文件（如果未提供 --discovery 参数）
    if discovery_path is None:
        probe_dir = os.path.join(project_dir, '_probe')
        if os.path.isdir(probe_dir):
            # 优先级 1: 统一的多模块 discovery.json
            unified_path = os.path.join(probe_dir, 'discovery.json')
            if os.path.isfile(unified_path):
                discovery_path = unified_path
                print(f"[INFO] Auto-discover: {unified_path}")

            # 优先级 2: 模块专属的 discovery 文件
            if discovery_path is None and module:
                module_path = os.path.join(probe_dir, f'discovery_{module}.json')
                module_merged_path = os.path.join(probe_dir, f'discovery_{module}_merged.json')
                if os.path.isfile(module_merged_path):
                    discovery_path = module_merged_path
                    print(f"[INFO] Auto-discover: {module_merged_path}")
                elif os.path.isfile(module_path):
                    discovery_path = module_path
                    print(f"[INFO] Auto-discover: {module_path}")

    if discovery_path and os.path.isfile(discovery_path):
        with open(discovery_path, encoding='utf-8') as f:
            discovery_data = json.load(f)

        # C: 处理统一的多模块 discovery 格式
        if 'modules' in discovery_data and isinstance(discovery_data['modules'], list):
            if module:
                # 提取指定模块的数据
                for mod_data in discovery_data['modules']:
                    if mod_data.get('module') == module:
                        discovery_data = mod_data
                        print(f"[INFO] 从统一 discovery 提取模块: {module}")
                        break
                else:
                    # 未找到指定模块，使用展平的容器数据
                    discovery_data = {
                        'list_page': discovery_data.get('list_page', {}),
                        'containers': discovery_data.get('containers', []),
                    }
                    print(f"[WARN] 模块 {module} 未在统一 discovery 中找到，使用展平数据")
            else:
                # 未指定模块，使用展平的容器数据
                discovery_data = {
                    'list_page': discovery_data.get('list_page', {}),
                    'containers': discovery_data.get('containers', []),
                }
                print(f"[INFO] 使用统一 discovery 的展平数据")

        # V7: detect multi-page discovery format
        if 'pages' in discovery_data and isinstance(discovery_data['pages'], list):
            for dp in discovery_data['pages']:
                dp_url = dp.get('url', '')
                if dp_url:
                    # Store by both full URL and path segment for flexible matching
                    _discovery_pages_by_url[dp_url] = dp
                    # Also store by hash fragment (e.g., #/work-order/new-list)
                    parsed = urlparse(dp_url)
                    if parsed.fragment:
                        _discovery_pages_by_url[parsed.fragment] = dp
                    elif parsed.path:
                        _discovery_pages_by_url[parsed.path] = dp
            print(f"[INFO] V7: 多页面 discovery — {len(discovery_data['pages'])} pages")
            # G7: V7 数据预展平 — 合并所有页面的 list_page/containers，
            # 作为 URL 匹配失败时的回退数据源（_find_in_discovery 不支持 pages[] 格式）
            _v7_flat = {'list_page': {}, 'containers': []}
            _v7_sections = ('buttons', 'row_buttons', 'inputs', 'tabs',
                            'detail_links', 'checkboxes', 'menu_items')
            for dp in discovery_data['pages']:
                lp = dp.get('list_page', {})
                for sec in _v7_sections:
                    if sec in lp:
                        _v7_flat['list_page'].setdefault(sec, []).extend(lp[sec])
                _v7_flat['containers'].extend(dp.get('containers', []))
            _v7_flat_count = (sum(len(v) for v in _v7_flat['list_page'].values())
                              + sum(len(c.get('elements', [])) for c in _v7_flat['containers']))
            print(f"[INFO] V7 展平: {_v7_flat_count} 个元素（{len(_v7_flat['containers'])} 个容器）")
        else:
            _v7_flat = None  # 非 V7 格式，无需展平
        _top_containers = len(discovery_data.get('containers', []))
        if _top_containers:
            print(f"[INFO] Loaded discovery: {_top_containers} containers")
        elif _v7_flat:
            print(f"[INFO] Loaded discovery: V7 多页面格式（已展平）")

    if not cases:
        print("[WARN] No case files found")
        return

    print(f"[INFO] Loaded: {len(pages_dict)} page groups, {len(data_dict)} data entries, {len(cases)} cases")

    # Track verified locators
    verified_locators = {}  # {group.field: {locator, marker}}
    total_steps = 0
    verified_count = 0
    fallback_count = 0
    skipped_count = 0
    error_count = 0

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
        domain = urlparse(base_url).hostname
        cookies = parse_cookie(cookie, domain)

        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)

        # Build localStorage map: tokens from cookie (highest priority) + config + CLI
        # Priority order (later overwrites earlier):
        #   1. config.yaml local_storage (base defaults)
        #   2. CLI --local-storage override
        #   3. Cookie token keys (always win — prevents stale config.yaml from overriding fresh cookie)
        local_storage = {}

        # 1. Load from project config.yaml (cookie + local_storage section)
        config_path = os.path.join(project_dir, 'config.yaml')
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                if isinstance(cfg.get('local_storage'), dict):
                    for k, v in cfg['local_storage'].items():
                        local_storage[str(k)] = str(v)
                # R6: 读取 AI probe 配置并初始化
                if _HAS_AI_PROBE and cfg.get('ai_probe'):
                    _ai_probe_init(cfg['ai_probe'])
                    print(f"  R6: AI probe enabled (model: {cfg['ai_probe'].get('model', 'gpt-4o-mini')})")
            except Exception:
                pass

        # 2. CLI override: --local-storage '{"k":"v",...}'
        if local_storage_override:
            try:
                override = json.loads(local_storage_override)
                if isinstance(override, dict):
                    for k, v in override.items():
                        local_storage[str(k)] = str(v)
            except Exception as e:
                print(f"[WARN] --local-storage JSON parse failed: {e}")

        # 3. Cookie token keys always override (freshest source)
        for c in cookies:
            if c['name'] in TOKEN_KEYS:
                local_storage[c['name']] = c['value']

        page = context.new_page()

        # Perf: 预注入 localStorage 一次（避免每个 case 重复导航）
        _ls_injected = False

        for case_idx, case in enumerate(cases):
            case_name = case.get('name', case.get('_file', f'case_{case_idx}'))
            steps = case.get('steps', [])
            if not steps:
                continue

            print(f"\n[Case {case_idx+1}/{len(cases)}] {case_name}")

            # V7: 为每个 case 选择匹配的 discovery page
            # G7: V7 格式时默认使用展平数据（而非原始 pages[] 格式，_find_in_discovery 无法搜索）
            case_discovery = _v7_flat if _v7_flat else discovery_data
            if _discovery_pages_by_url:
                # Extract open_url from case steps to find target URL
                case_url = ''
                for s in steps:
                    if s.get('keyword') == 'open_url':
                        u = (s.get('params') or {}).get('url', '')
                        if u:
                            case_url = resolve_var(u, data_dict)
                            break
                # Match against discovery pages
                if case_url:
                    matched_dp = _discovery_pages_by_url.get(case_url)
                    if not matched_dp:
                        # Try matching by path/fragment
                        cp = urlparse(case_url)
                        matched_dp = (_discovery_pages_by_url.get(cp.fragment)
                                      or _discovery_pages_by_url.get(cp.path))
                    if matched_dp:
                        # Build a synthetic discovery_data from the matched page
                        case_discovery = {
                            'containers': matched_dp.get('containers', []),
                            'list_page': matched_dp.get('list_page', {}),
                        }
                        print(f"  [V7] discovery 匹配: {matched_dp.get('name', case_url)}")
                    else:
                        # G7: URL 匹配失败时使用展平数据（而非原始 V7 pages[] 格式）
                        if _v7_flat:
                            case_discovery = _v7_flat
                        print(f"  [V7 WARN] 无匹配的 discovery page: {case_url[:80]}"
                              + (" — 使用展平数据回退" if _v7_flat else ""))

            # Navigate to base URL for each case
            try:
                if not _ls_injected:
                    # 首次: goto → inject localStorage → reload (完整认证流程)
                    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    _wait_for_dom_stable(page, timeout_ms=4000)
                    for k, v in local_storage.items():
                        page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
                    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    _wait_for_dom_stable(page, timeout_ms=4000)
                    _ls_injected = True
                    # Check if redirected to login page (invalid cookie)
                    final_url = page.url
                    if '/login' in final_url or final_url.rstrip('/').endswith('login'):
                        print(f"  [ERROR] Redirected to login page — cookie invalid/expired")
                        print(f"  [ERROR] Aborting verification. Please provide a fresh cookie.")
                        return {
                            'total_steps': 0, 'verified': 0, 'skipped': 0,
                            'failed': 0, 'auth_error': True,
                        }
                else:
                    # 后续 case: 导航回首页（localStorage 已注入）
                    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    # SPA hash 路由不变时 goto 可能不触发全页面重载，
                    # reload 强制销毁 Vue app，清除残留 dialog/drawer wrapper
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    _wait_for_dom_stable(page, timeout_ms=4000)
            except Exception as e:
                print(f"  [ERROR] Navigation failed: {str(e)[:100]}")
                continue

            steps_so_far = []
            is_new_page_context = False  # D3: track if we're on a different page than baseline
            case_baseline_url = base_url
            container_context = None  # 容器上下文：跟踪上一个步骤检测到的容器类型

            for step_idx, step in enumerate(steps):
                total_steps += 1
                keyword = step.get('keyword', '')
                desc = step.get('desc', '')

                # P2-2: Handle sub-steps (if_element_visible, then_steps, else_steps)
                if keyword == 'if_element_visible':
                    then_steps = step.get('then_steps', [])
                    else_steps = step.get('else_steps', [])
                    # Verify the condition locator
                    cond_locator = step.get('params', {}).get('locator', '')
                    if cond_locator:
                        cond_locator = resolve_locator(step.get('params', {}), pages_dict)
                        # Fix A: 使用 wait_for 等待元素可见（与 Phase 9 引擎行为一致）
                        cond_timeout = step.get('params', {}).get('timeout', 5000)
                        if isinstance(cond_timeout, (int, float)):
                            cond_timeout = int(cond_timeout)
                        else:
                            cond_timeout = 5000
                        # 至少给 3 秒，确保页面加载完成
                        cond_timeout = max(cond_timeout, 3000)
                        try:
                            page.locator(cond_locator).first.wait_for(state='visible', timeout=cond_timeout)
                            cond_count = 1
                        except Exception:
                            cond_count = 0
                        sub_steps = then_steps if cond_count > 0 else else_steps
                        for sub in sub_steps:
                            total_steps += 1
                            v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                                page, sub, pages_dict, data_dict, steps_so_far,
                                case_discovery, project_dir=project_dir,
                                is_new_page_context=is_new_page_context,
                                container_context=container_context
                            )
                            # 更新容器上下文
                            if v_ct:
                                container_context = v_ct
                            elif (v_ct is None and not v_skip
                                  and sub.get('keyword', '') in ('click_element', 'click')):
                                # 双重确认：检测容器是否真的消失了
                                if container_context:
                                    current_containers = detect_visible_containers(page)
                                    if container_context not in current_containers:
                                        old_ct = container_context
                                        container_context = None
                                        print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                                    else:
                                        print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                            if v_loc:
                                _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                                _store_verified_locator(v_loc, v_ct, sub, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                                if v_bg:
                                    fallback_count += 1
                                else:
                                    verified_count += 1
                            steps_so_far.append(sub)
                    continue

                # P2-3: l3_call expansion
                if keyword in L3_KEYWORDS:
                    sub_steps = _expand_l3_call(step, project_dir, pages_dict, data_dict)
                    print(f"    [L3] {desc} → {len(sub_steps)} sub-steps")
                    for sub in sub_steps:
                        total_steps += 1
                        v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                            page, sub, pages_dict, data_dict, steps_so_far,
                            case_discovery, project_dir=project_dir,
                            is_new_page_context=is_new_page_context,
                            container_context=container_context
                        )
                        # 更新容器上下文
                        if v_ct:
                            container_context = v_ct
                        elif (v_ct is None and not v_skip
                              and sub.get('keyword', '') in ('click_element', 'click')):
                            # 双重确认：检测容器是否真的消失了
                            if container_context:
                                current_containers = detect_visible_containers(page)
                                if container_context not in current_containers:
                                    old_ct = container_context
                                    container_context = None
                                    print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                                else:
                                    print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                        if v_loc:
                            _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                            _store_verified_locator(v_loc, v_ct, sub, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                            if v_bg:
                                fallback_count += 1
                            else:
                                verified_count += 1
                        elif v_loc is None and sub.get('keyword') in NO_VERIFY_KEYWORDS:
                            pass  # skip non-verify steps
                        else:
                            fallback_count += 1
                        steps_so_far.append(sub)
                    continue

                # V5: Custom L3 workflow name expansion
                # Recognizes keywords like 'check_inbox_display' that are L3 workflow names
                _l3_wf = _load_l3_workflows(project_dir or '') if project_dir else {}
                if keyword in _l3_wf:
                    # H3: 检查 module_keywords.py 是否已编译此关键字
                    if project_dir:
                        _mk_path = os.path.join(project_dir, 'lib', 'module_keywords.py')
                        if os.path.isfile(_mk_path):
                            try:
                                with open(_mk_path, encoding='utf-8') as _f:
                                    _mk_content = _f.read()
                                if f"def {keyword}(" not in _mk_content:
                                    print(f"    [WARN] L3 关键字 '{keyword}' 在 workflow YAML 中有定义，"
                                          f"但 module_keywords.py 未编译。运行时将无法解析。")
                            except Exception:
                                pass
                        else:
                            print(f"    [WARN] module_keywords.py 不存在，L3 关键字 '{keyword}' 运行时不可用。"
                                  f"请先运行 compile_module_keywords.py")
                    synthetic_step = {
                        'keyword': 'l3_call',
                        'params': {
                            'workflow': keyword,
                            'args': dict(step.get('params', {}) or {}),
                        },
                    }
                    sub_steps = _expand_l3_call(synthetic_step, project_dir, pages_dict, data_dict)
                    print(f"    [L3] {desc} ({keyword}) → {len(sub_steps)} sub-steps")
                    for sub in sub_steps:
                        total_steps += 1
                        v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                            page, sub, pages_dict, data_dict, steps_so_far,
                            case_discovery, project_dir=project_dir,
                            is_new_page_context=is_new_page_context,
                            container_context=container_context
                        )
                        # 更新容器上下文
                        if v_ct:
                            container_context = v_ct
                        elif (v_ct is None and not v_skip
                              and sub.get('keyword', '') in ('click_element', 'click')):
                            # 双重确认：检测容器是否真的消失了
                            if container_context:
                                current_containers = detect_visible_containers(page)
                                if container_context not in current_containers:
                                    old_ct = container_context
                                    container_context = None
                                    print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                                else:
                                    print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                        if v_loc:
                            _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                            _store_verified_locator(v_loc, v_ct, sub, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                            if v_bg:
                                fallback_count += 1
                            else:
                                verified_count += 1
                        elif v_loc is None and sub.get('keyword') in NO_VERIFY_KEYWORDS:
                            pass  # skip non-verify steps
                        else:
                            fallback_count += 1
                        steps_so_far.append(sub)
                    continue

                # Execute step
                v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                    page, step, pages_dict, data_dict, steps_so_far,
                    case_discovery, project_dir=project_dir,
                    is_new_page_context=is_new_page_context,
                    container_context=container_context
                )

                # 更新容器上下文
                if v_ct:
                    container_context = v_ct
                elif (v_ct is None and not v_skip
                      and keyword in ('click_element', 'click')):
                    # 双重确认：检测容器是否真的消失了
                    if container_context:
                        current_containers = detect_visible_containers(page)
                        if container_context not in current_containers:
                            old_ct = container_context
                            container_context = None
                            print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                        else:
                            print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                # open_url/refresh 后清除容器上下文（页面跳转）
                if keyword in ('open_url', 'refresh'):
                    container_context = None

                if v_skip:
                    skipped_count += 1
                    print(f"    [SKIP] Step {step_idx+1}: {desc}")
                elif v_loc:
                    _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                    _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                    if v_bg:
                        fallback_count += 1
                        print(f"    [UNVERIFIED] Step {step_idx+1}: {desc}")
                    else:
                        verified_count += 1
                        print(f"    [OK] Step {step_idx+1}: {desc}")
                else:
                    if keyword not in NO_VERIFY_KEYWORDS and 'except' not in keyword:
                        fallback_count += 1
                        print(f"    [FAIL] Step {step_idx+1}: {desc}")

                steps_so_far.append(step)

                # D3: Track URL changes for new page context
                try:
                    current_url = page.url
                    if current_url != case_baseline_url:
                        is_new_page_context = True
                    else:
                        is_new_page_context = False
                except Exception:
                    pass

            # Reset for next case: goto + reload 清除残留 dialog/drawer
            try:
                page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                # SPA hash 路由不变时 goto 可能不触发全页面重载，
                # reload 强制销毁 Vue app，清除残留 dialog/drawer wrapper
                page.reload(wait_until="domcontentloaded", timeout=30000)
                _wait_for_dom_stable(page, timeout_ms=2000)  # case 间重置
            except Exception as _e:
                print(f"  [WARN] case 间 page.reload 失败: {_e}")

    finally:
        try:
            browser.close()
            context.close()
        except Exception:
            pass
        pw.stop()

    # Summary
    print(f"\n{'='*60}")
    print(f"[Verify] DONE")
    print(f"  Cases: {len(cases)}")
    print(f"  Steps: {total_steps} total")
    print(f"  Verified: {verified_count} ({100*verified_count//max(total_steps,1)}%)")
    print(f"  Skipped (destructive): {skipped_count}")
    print(f"  Failed: {fallback_count}")
    print(f"  Writeback pending: {len(verified_locators)}")
    print(f"{'='*60}\n")

    # R6: Flush AI probe diagnostics
    if _HAS_AI_PROBE:
        _ai_probe_flush(project_dir)

    return {
        'total_steps': total_steps,
        'verified': verified_count,
        'skipped': skipped_count,
        'failed': fallback_count,
        'verified_locators': verified_locators,
        'writeback_count': len(verified_locators),
    }


# ============================================================================
# CLI + verify result persistence
# ============================================================================

def _write_verify_result(project_dir, result):
    """P3f-3: 写入 _probe/verify_result.json 供 _phase_registry.py 检查"""
    import hashlib, datetime

    probe_dir = os.path.join(project_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)

    # 防伪造签名
    fingerprint = hashlib.sha256(
        f"{project_dir}:{result.get('total_steps', 0)}:"
        f"{result.get('verified', 0)}:{result.get('writeback_count', 0)}".encode()
    ).hexdigest()[:16]

    output = {
        'total_steps': result.get('total_steps', 0),
        'verified': result.get('verified', 0),
        'failed': result.get('failed', 0),
        'skipped': result.get('skipped', 0),
        'writeback_count': result.get('writeback_count', 0),
        'fingerprint': fingerprint,
        'run_timestamp': datetime.datetime.now().isoformat(),
        'modules_verified': result.get('modules_verified', []),
    }

    path = os.path.join(probe_dir, 'verify_result.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] verify_result.json written: {path}")


def _consume_pending_detail_links(project_dir, cookie, url, local_storage=None):
    """M20: 自动消费 pending_detail_links.json

    如果 _probe/pending_detail_links.json 存在且非空，
    用 KB 模板在浏览器中直接探测 locator，解决后清理文件。
    不再调用 probe_from_pages.py subprocess。
    """
    pending_file = os.path.join(project_dir, '_probe', 'pending_detail_links.json')
    if not os.path.isfile(pending_file):
        return

    try:
        with open(pending_file, encoding='utf-8') as f:
            pending = json.load(f)
    except Exception:
        return

    if not pending:
        return

    print(f"[M20] 发现 {len(pending)} 个 pending detail-link")

    # ── KB 模板浏览器直连探测 ──
    resolved = _try_kb_resolve_detail_links(
        project_dir, pending, cookie, url, local_storage)
    if resolved:
        # 移除已解决的条目
        resolved_keys = {(r['group'], r['field']) for r in resolved}
        remaining = [p for p in pending
                     if (p.get('group'), p.get('field')) not in resolved_keys]
        if not remaining:
            os.remove(pending_file)
            print(f"[M20] 所有 detail-link 已通过 KB 模板解决 ({len(resolved)} 个)")
            return
        # 更新 pending 文件
        with open(pending_file, 'w', encoding='utf-8') as f:
            json.dump(remaining, f, ensure_ascii=False, indent=2)
        print(f"[M20] KB 解决 {len(resolved)} 个，剩余 {len(remaining)} 个待 Phase 6 预执行处理")
    else:
        print(f"[M20] KB 模板未匹配，{len(pending)} 个 detail-link 将在 Phase 6 预执行中处理")


# KB detail-link 模式（文本无关的 class-based 优先，文本依赖的兜底）
_KB_DETAIL_LINK_PATTERNS = [
    # 纯 class-based（不依赖文本，通用性最强）
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"common-href")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"link-style")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"click-list")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"resource-id")]',
    '//td[not(contains(@class,"is-hidden"))]//*[@class="edit-name"]/preceding-sibling::div[contains(@class,"link-style")]',
    # 文本依赖（需要 label 替换）
    '//td[not(contains(@class,"is-hidden"))]//*[contains(text(),"{label}")]',
    '//td[not(contains(@class,"is-hidden"))]//*[contains(@class,"link-style") or contains(@class,"click-list") or contains(@class,"resource-id") or contains(@class,"name")][contains(.,"{label}")]',
]


def _try_kb_resolve_detail_links(project_dir, pending, cookie, url,
                                   local_storage_override=None):
    """用 KB detail-link 模板在浏览器中直接探测 locator。

    返回已解决的条目列表 [{group, field, locator}, ...]，空列表表示全部失败。
    """
    if not pending:
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[M20-KB] playwright 未安装，跳过 KB 探测")
        return []

    resolved = []
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
        domain = urlparse(url).hostname
        cookies = parse_cookie(cookie, domain)
        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)

        # Inject localStorage (same logic as main verify)
        local_storage = {}
        config_path = os.path.join(project_dir, 'config.yaml')
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                if isinstance(cfg.get('local_storage'), dict):
                    for k, v in cfg['local_storage'].items():
                        local_storage[str(k)] = str(v)
            except Exception:
                pass
        if local_storage_override:
            try:
                override = json.loads(local_storage_override) if isinstance(
                    local_storage_override, str) else local_storage_override
                if isinstance(override, dict):
                    for k, v in override.items():
                        local_storage[str(k)] = str(v)
            except Exception:
                pass
        for c in cookies:
            if c['name'] in TOKEN_KEYS:
                local_storage[c['name']] = c['value']

        page = context.new_page()
        # Navigate + inject localStorage
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_dom_stable(page, timeout_ms=5000)

        # Check auth validity
        if '/login' in page.url:
            print("[M20-KB] Cookie 无效，跳过 KB 探测")
            return []

        # Try to get first row text for label substitution
        first_row_text = None
        try:
            first_row_text = page.evaluate("""() => {
                const row = document.querySelector('table tbody tr');
                if (!row) return null;
                const cells = row.querySelectorAll('td');
                for (const cell of cells) {
                    const t = (cell.textContent || '').trim();
                    if (t && t.length > 2 && t.length < 50) return t;
                }
                return null;
            }""")
        except Exception:
            pass

        # Try each pending entry
        for entry in pending:
            group = entry.get('group', '')
            field = entry.get('field', '')
            label = entry.get('label', '')

            for pattern in _KB_DETAIL_LINK_PATTERNS:
                # Substitute {label} if present
                xpath = pattern
                if '{label}' in xpath:
                    if not first_row_text and not label:
                        continue
                    xpath = xpath.replace('{label}', first_row_text or label)

                try:
                    count = page.locator(f'xpath={xpath}').count()
                    if count == 1:
                        locator = f'xpath={xpath}'
                        resolved.append({
                            'group': group,
                            'field': field,
                            'locator': locator,
                        })
                        print(f"[M20-KB] ✅ {group}.{field} → {locator[:60]}...")
                        break
                except Exception:
                    continue

        # Write back resolved locators to pages YAML
        if resolved:
            verified_locators = {}
            for r in resolved:
                ref = f"{r['group']}.{r['field']}"
                verified_locators[ref] = {
                    'locator': r['locator'],
                    'marker': '[KB-DETAIL-LINK]',
                    'container_type': None,
                    'is_new_field': False,
                }
            update_pages_yaml(project_dir, verified_locators)

    except Exception as e:
        print(f"[M20-KB] KB 探测异常: {e}")
    finally:
        try:
            pw.stop()
        except Exception:
            pass

    return resolved


# ============================================================================
# Phase 2: Gap Scan + Auto-Supplement
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Phase 6 运行时验证 — 按 case 流程执行，验证所有 locator'
    )
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--cookie', required=True, help='Cookie 字符串')
    parser.add_argument('--url', required=True, help='目标系统基础 URL')
    parser.add_argument('--discovery', default=None,
                        help='discovery JSON 文件路径（discover_page.py 输出）')
    parser.add_argument('--module', default=None,
                        help='只验证指定模块（默认全部）')
    parser.add_argument('--local-storage', default=None,
                        help='额外 localStorage 注入（JSON 对象字符串），合并 config.yaml 的 local_storage')
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告需要验证的 locator，不执行浏览器')
    parser.add_argument('--ai-probe', default=None,
                        help='AI 探测配置（JSON 字符串，由 pipeline 传入）')

    args = parser.parse_args()

    if not os.path.isdir(args.project_dir):
        print(f"[ERROR] 项目目录不存在: {args.project_dir}")
        sys.exit(1)

    # ── 管线自愈：Phase 2/3 缺失时自动补全，其余记日志不阻断 ──
    from _pipeline_guard import check_pipeline_state
    check_pipeline_state(args.project_dir, ["phase_5"], "verify_locators.py",
                          {"cookie": args.cookie})

    if args.dry_run:
        cases = load_cases(args.project_dir, args.module)
        pages = load_pages(args.project_dir, module=args.module)
        total = 0
        for case in cases:
            for step in case.get('steps', []):
                if step.get('keyword') not in NO_VERIFY_KEYWORDS:
                    total += 1
        print(f"[Dry-run] {len(cases)} cases, {total} steps to verify")
        print(f"[Dry-run] {len(pages)} page groups loaded")
        sys.exit(0)

    # M20: 自动消费 pending_detail_links.json（Phase 5 输出）
    _consume_pending_detail_links(args.project_dir, args.cookie, args.url,
                                   args.local_storage)

    result = verify_project(args.project_dir, args.cookie, args.url, args.discovery, args.module, args.local_storage)

    # P3f-2: 回写验证结果到 pages YAML + 生成 verify_result.json
    if result and not result.get('auth_error'):
        verified_locators = result.get('verified_locators', {})

        if verified_locators:
            print(f"\n[Writeback] Updating {len(verified_locators)} locators in pages YAML...")
            update_pages_yaml(args.project_dir, verified_locators, module=args.module)

        # 写入 verify_result.json（供阶段门禁检查）
        _write_verify_result(args.project_dir, result)

    # X-2 修复: 只有当存在完全无法解析的 locator（非 KB fallback）时才 exit(1)
    # 计数器关系（来自 verify_project()）:
    #   failed = fallback_count（KB best-guess + 完全失败的步骤）
    #   verified = verified_count（运行时验证通过的步骤）
    #   writeback_count = len(verified_locators)（所有回写到 pages YAML 的 locator）
    #   其中 writeback_count ≈ verified_count + KB_fallback_stored
    #   truly_unresolved = failed - KB_fallback_stored = failed - (writeback - verified)
    if result:
        failed = result.get('failed', 0)
        verified = result.get('verified', 0)
        writeback = result.get('writeback_count', 0)
        kb_fallback_stored = max(0, writeback - verified)  # KB 回退且成功回写的数量
        truly_unresolved = failed - kb_fallback_stored    # 完全无法解析的步骤数
    else:
        truly_unresolved = 0

    if truly_unresolved > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
