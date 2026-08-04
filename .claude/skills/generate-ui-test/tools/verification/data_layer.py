"""
data_layer.py - 数据加载与查询层

从 verify_locators.py 提取的数据层函数：
- KB 定位器生成
- Discovery 数据匹配
- YAML 文件加载
- 变量解析
"""

import os
import re
import sys

# Ensure tools/ is on sys.path for cross-module imports
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

from probe.probe_element import _xpath_escape_label, _safe_format
from probe.probe_utils import (
    get_kb_patterns, get_all_patterns, get_multi_step_patterns,
    KB_KEY_ALIAS
)
from core.element_types import (
    TYPE_TO_SECTIONS as _TYPE_COMPATIBLE_SECTIONS,
    ALL_LIST_SECTIONS as _ALL_LIST_SECTIONS,
    infer_discovery_section as _infer_discovery_section,
)

# click_element 步骤可能匹配多种元素类型，按精确度降序遍历
CLICK_EXPAND_TYPES = ['button', 'table-action-button', 'detail-link']


# ============================================================================
# KB locators
# ============================================================================

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
# Discovery matching helpers
# ============================================================================

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
        flat_value = pages_dict.get(ref)
        if flat_value:
            return str(flat_value)
        # Variable not resolved - return empty string instead of unresolved reference
        # This prevents passing ${...} to Playwright which causes CSS parse errors
        return ''
    return locator
