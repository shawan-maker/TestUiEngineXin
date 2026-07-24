#!/usr/bin/env python3
"""
Phase 5: 跨文件脚本验证器 (validate_05_scripts.py)

精简版：仅保留必须跨文件检查的 14 个规则。
单文件检查已前置到生成工具自检层（_case_generator.py / _pages_writer.py）。

保留规则:
  R4.1  四层目录模块名一致（跨 cases/pages/data/suites 目录集合）
  R4.3  el-select 选项文本 vs data 搜索值（跨 pages + data）
  R4.7  case_refs 排序（跨 case_refs + ORDER_TIERS）
  R4.20 步骤顺序与 Excel 一致（跨 _source_map.json）
  R4.31 变量引用存在性（跨 pages_keys + data_keys）
  R4.31s 变量引用模块作用域（跨 pages_groups_by_module）
  R4.33 容器上下文引用（跨 pages_keys 同名检测）
  R4.37 case ID 全局唯一（跨所有 case 文件）
  R4.41 详情入口 Pattern 12（跨 pages_locators 解析）
  R4.42 详情入口 probe 验证（跨 probe_knowledge_fields）
  R4.43 核心 locator probe 记录（跨 probe_knowledge_fields）
  PREREQUISITE 前置阶段执行证据
  SUITE_REF suite case_id 引用存在性
  EXCEL_COMPLETE Excel 用例转换完整性

用法:
    python validate_05_scripts.py <project_dir>

退出码: 0 = 全部通过, 1 = 有 error 级别违规
"""

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Dict, Set, Tuple, Optional

try:
    import yaml
except ImportError:
    print("[FATAL] 需要 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# 共享工具函数
_tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)
from _tier_utils import get_case_tier as _get_case_tier


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Violation:
    file: str        # 相对于 project_dir 的路径
    line: int        # 行号 (1-based)
    rule: str        # 规则编号 (如 "R4.1", "R4.13")
    severity: str    # "error" | "warning"
    message: str     # 描述
    suggestion: str  # 修复建议


# ============================================================================
# 工具函数
# ============================================================================

def discover_yaml_files(project_dir: str) -> Dict[str, List[str]]:
    """按类别发现 YAML 文件"""
    categories = ['cases', 'pages', 'data', 'suites']
    result = {}
    for cat in categories:
        cat_dir = os.path.join(project_dir, cat)
        files = []
        if os.path.isdir(cat_dir):
            for root, _, filenames in os.walk(cat_dir):
                for fn in sorted(filenames):
                    if fn.endswith(('.yaml', '.yml')):
                        files.append(os.path.join(root, fn))
        result[cat] = files
    return result


def load_yaml_with_lines(filepath: str) -> Tuple[Optional[dict], List[str]]:
    """加载 YAML 并保留原始行"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw = f.read()
        lines = raw.splitlines()
        data = yaml.safe_load(raw)
        return data, lines
    except Exception:
        return None, []


def find_line(lines: List[str], pattern: str, start: int = 0) -> int:
    """查找包含 pattern 的行号 (1-based)"""
    for i in range(start, len(lines)):
        if pattern in lines[i]:
            return i + 1
    return start + 1


def flatten_dict(d: dict, parent: str = '', sep: str = '.') -> Set[str]:
    """展平字典为 group.field 格式"""
    keys = set()
    if not isinstance(d, dict):
        return keys
    for k, v in d.items():
        full_key = f"{parent}{sep}{k}" if parent else k
        keys.add(full_key)
        if isinstance(v, dict):
            keys.update(flatten_dict(v, full_key, sep))
    return keys


def _extract_module_dirs(files_by_cat: Dict[str, List[str]]) -> Dict[str, Set[str]]:
    """提取四层目录的一级子目录名（模块名）"""
    module_dirs = {}
    for cat in ['cases', 'pages', 'data', 'suites']:
        modules = set()
        for f in files_by_cat.get(cat, []):
            parts = f.replace('\\', '/').split('/')
            for i, p in enumerate(parts):
                if p == cat and i + 1 < len(parts):
                    modules.add(parts[i + 1])
                    break
        module_dirs[cat] = modules
    return module_dirs


def build_context(files_by_cat: Dict[str, List[str]]) -> dict:
    """构建跨文件上下文"""
    pages_keys = set()
    pages_locators = {}  # R4.41: group.field → actual XPath value
    pages_groups_by_module = {}  # R4.31s: module_dir → set of group names
    data_keys = set()
    case_ids = set()
    data_search_values = {}
    pages_option_texts = {}
    el_select_fields = set()  # R4.3/R4.23: 含 el-select 的字段名

    _contains_re = re.compile(r"contains\(\.,'([^']+)'\)")

    for f in files_by_cat.get('pages', []):
        data, _ = load_yaml_with_lines(f)
        if data and isinstance(data, dict):
            pages_keys.update(flatten_dict(data))
            # R4.31s: 记录每个模块目录下的 group 名称
            norm_f = f.replace('\\', '/')
            pages_match = re.search(r'(?:^|[\\/])pages[\\/]([\w][\w-]*)[\\/]', norm_f)
            if pages_match:
                mod = pages_match.group(1)
                pages_groups_by_module.setdefault(mod, set()).update(data.keys())
            for group, fields in data.items():
                if isinstance(fields, dict):
                    for field, val in fields.items():
                        if isinstance(val, str):
                            pages_locators[f"{group}.{field}"] = val
                            if '_option' in field:
                                m = _contains_re.search(val)
                                if m:
                                    pages_option_texts.setdefault(f, []).append(
                                        (f"{group}.{field}", m.group(1)))
                            # 收集含 el-select 的字段（用于 R4.3/R4.23 定位器检测）
                            if 'el-select' in val.lower():
                                el_select_fields.add(f"{group}.{field}")

    for f in files_by_cat.get('data', []):
        data, _ = load_yaml_with_lines(f)
        if data and isinstance(data, dict):
            data_keys.update(flatten_dict(data))
            for group, fields in data.items():
                if isinstance(fields, dict):
                    for field, val in fields.items():
                        if isinstance(val, str) and '_search' in field:
                            data_search_values.setdefault(f, []).append(
                                (f"{group}.{field}", val))

    for f in files_by_cat.get('cases', []):
        data, _ = load_yaml_with_lines(f)
        if data and isinstance(data, dict) and 'id' in data:
            case_ids.add(data['id'])

    return {
        'pages_keys': pages_keys,
        'pages_locators': pages_locators,
        'pages_groups_by_module': pages_groups_by_module,
        'data_keys': data_keys,
        'case_ids': case_ids,
        'module_dirs': _extract_module_dirs(files_by_cat),
        'data_search_values': data_search_values,
        'pages_option_texts': pages_option_texts,
        'el_select_fields': el_select_fields,
    }


def rel_path(filepath: str, project_dir: str) -> str:
    """转为相对路径"""
    return os.path.relpath(filepath, project_dir)


def get_all_string_values(d) -> List[str]:
    """递归提取字典中所有字符串值"""
    results = []
    if isinstance(d, str):
        results.append(d)
    elif isinstance(d, dict):
        for v in d.values():
            results.extend(get_all_string_values(v))
    elif isinstance(d, list):
        for item in d:
            results.extend(get_all_string_values(item))
    return results


# 通用文本豁免列表
_EXEMPT_VALUES = {'成功', '失败', '确定', '取消', '是', '否', ''}


# ============================================================================
# 辅助加载函数
# ============================================================================

def _load_probe_knowledge_fields(project_dir: str) -> Dict[str, dict]:
    """加载 probe 结果中 from_knowledge=true 的字段（供 R4.42 使用）

    扫描 _probe/*.json，返回 {field_key: {type, strategy, from_knowledge}} 字典。
    仅包含通过 probe_with_knowledge() 探测的字段（from_knowledge: true）。
    """
    import glob as _glob
    probe_dir = os.path.join(project_dir, '_probe')
    result = {}
    if not os.path.isdir(probe_dir):
        return result

    for filepath in _glob.glob(os.path.join(probe_dir, '**/*.json'), recursive=True):
        basename = os.path.basename(filepath)
        if 'harvest' in basename or 'pending' in basename or '_map' in basename:
            continue
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue

        elements = []
        if isinstance(data, list):
            elements = data
        elif isinstance(data, dict):
            elements = data.get('elements', [])

        for el in elements:
            if not isinstance(el, dict):
                continue
            key = el.get('key', '')
            if key and el.get('from_knowledge'):
                result[key] = {
                    'type': el.get('type', ''),
                    'strategy': el.get('strategy', ''),
                    'verified': el.get('verified', False),
                }
    return result


def _load_l3_keyword_names(project_dir: str) -> Set[str]:
    """从三层 workflow 定义动态加载 L3 关键字名称集合

    加载顺序（与 compile_module_keywords.py 一致）:
      1. 系统级: skills/lib/system_workflows.yaml
      2. 技能级: skills/lib/_knowledge/*.yaml
      3. 项目级: {project}/_knowledge/*.yaml

    兼容 list 和 dict 两种 workflows 格式。
    返回: {keyword_name, chinese_name, ...}
    """
    names = set()

    # ── 层 1: 系统级 ──
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys_path = os.path.join(skill_dir, 'lib', 'system_workflows.yaml')
    _extract_names_from_yaml(sys_path, names)

    # ── 层 2: 技能级 _knowledge/*.yaml ──
    skill_kd = os.path.join(skill_dir, 'lib', '_knowledge')
    if os.path.isdir(skill_kd):
        for f in glob.glob(os.path.join(skill_kd, '*.yaml')):
            _extract_names_from_yaml(f, names)

    # ── 层 3: 项目级 ──
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if not os.path.isdir(knowledge_dir):
        return names

    for f in glob.glob(os.path.join(knowledge_dir, "*.yaml")):
        _extract_names_from_yaml(f, names)

    return names


def _extract_names_from_yaml(yaml_path: str, names: set):
    """从单个 YAML 文件提取 workflow 名称"""
    try:
        data = yaml.safe_load(open(yaml_path, encoding='utf-8'))
    except Exception:
        return
    if not data or not isinstance(data, dict):
        return

    workflows = data.get('workflows')
    if workflows is None:
        return

    if isinstance(workflows, list):
        for wf in workflows:
            if isinstance(wf, dict) and 'name' in wf:
                names.add(wf['name'])
                cn = wf.get('chinese_name', '')
                if cn:
                    names.add(cn)
    elif isinstance(workflows, dict):
        for wf_name, wf in workflows.items():
            names.add(wf_name)
            if isinstance(wf, dict):
                cn = wf.get('chinese_name', '')
                if cn:
                    names.add(cn)


# ============================================================================
# R4.1 四层目录模块名一致
# ============================================================================

def check_r4_1(filepath: str, data: dict, lines: List[str],
               ctx: dict) -> List[Violation]:
    """R4.1: 四层目录模块名一致性（项目级检查，仅触发一次）"""
    violations = []
    checked = ctx.setdefault('_r4_1_checked', False)
    if checked:
        return violations
    ctx['_r4_1_checked'] = True

    module_dirs = ctx.get('module_dirs', {})
    all_modules = set()
    for cat_modules in module_dirs.values():
        all_modules.update(cat_modules)

    for module in sorted(all_modules):
        missing_in = []
        for cat in ['pages', 'data', 'cases', 'suites']:
            if module not in module_dirs.get(cat, set()):
                missing_in.append(f"{cat}/")
        if missing_in:
            violations.append(Violation(
                file=f"{module}/", line=0, rule='R4.1', severity='warning',
                message=f"模块 \"{module}\" 缺少: {', '.join(missing_in)}",
                suggestion=f"确保 pages/、data/、cases/、suites/ 四个目录下都有 {module}/ 子目录",
            ))

    return violations


# ============================================================================
# R4.7 case_refs 排序（suite 级检查）
# ============================================================================

def check_r4_7(filepath: str, data: dict, lines: List[str],
               ctx: dict) -> List[Violation]:
    """R4.7: case_refs 排序 — 用例应按依赖层级非递减排列

    层级: 新增(0) → 编辑(1) → 详情(2) → 导出(3) → 查询(4) → 批量(5) → 删除(6)
    未识别层级的 case（tier=-1）不参与排序检查。
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])

    case_refs = data.get('case_refs', [])
    if not isinstance(case_refs, list) or len(case_refs) < 2:
        return violations

    # 收集已识别层级的 case 及其位置
    tiered = []  # [(index, tier, case_id)]
    for i, ref in enumerate(case_refs):
        if not isinstance(ref, dict):
            continue
        case_id = str(ref.get('case_id', ''))
        tier = _get_case_tier(case_id)
        if tier >= 0:
            tiered.append((i, tier, case_id))

    if len(tiered) < 2:
        return violations

    # 检查层级是否非递减
    out_of_order = []
    for j in range(1, len(tiered)):
        prev_idx, prev_tier, prev_id = tiered[j - 1]
        curr_idx, curr_tier, curr_id = tiered[j]
        if curr_tier < prev_tier:
            tier_names = ['新增', '编辑', '详情', '导出', '查询', '批量', '删除']
            out_of_order.append(
                f"'{curr_id}'({tier_names[curr_tier]}) "
                f"排在 '{prev_id}'({tier_names[prev_tier]}) 之后"
            )

    if out_of_order:
        violations.append(Violation(
            file=rp, line=find_line(lines, 'case_refs'),
            rule='R4.7', severity='warning',
            message=f"case_refs 排序不符合依赖顺序: {'; '.join(out_of_order[:3])}",
            suggestion="推荐顺序: 新增→编辑→详情→导出→查询→批量→删除（破坏性操作排最后）",
        ))

    return violations


# ============================================================================
# R4.31 case/suite 中变量引用存在性检查
# ============================================================================

_VAR_REF_RE = re.compile(r'\$\{([^}]+)\}')

def check_r4_31(filepath: str, data: dict, lines: List[str],
                ctx: dict) -> List[Violation]:
    """R4.31: case/suite 中所有 ${group.field} 引用必须在 pages/data YAML 中存在

    检查 locator 和 value 参数中的变量引用，确保引用的 group.field
    在 pages YAML 或 data YAML 中有对应定义，避免运行时变量解析失败。
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])
    pages_keys = ctx.get('pages_keys', set())
    data_keys = ctx.get('data_keys', set())
    all_keys = pages_keys | data_keys

    def _check_params(params: dict, step_desc: str):
        if not isinstance(params, dict):
            return
        for param_key in ('locator', 'value', 'expect_results'):
            val = params.get(param_key, '')
            if not isinstance(val, str):
                continue
            for m in _VAR_REF_RE.finditer(val):
                ref = m.group(1)  # e.g. "question_search_elements.project_name_select"
                parts = ref.split('.')
                if len(parts) < 2:
                    continue
                group = parts[0]
                field = parts[-1]
                full_ref = f"{group}.{field}"

                # 跳过纯数据变量（如 ${data.xxx}）
                if group in ('data', 'env', 'global', 'config'):
                    continue

                # 检查是否存在
                if full_ref not in all_keys:
                    desc = step_desc or params.get('locator', '')[:40]
                    line = find_line(lines, desc) if desc else 1
                    # 判断应该是 pages 还是 data
                    if '_data' in group:
                        target = 'data'
                    elif '_elements' in group:
                        target = 'pages'
                    else:
                        target = 'pages/data'
                    violations.append(Violation(
                        file=rp, line=line, rule='R4.31', severity='error',
                        message=f"变量引用 ${{{ref}}} 在 {target}/ 中不存在",
                        suggestion=f"检查 {target} YAML 中 {group} 是否有字段 {field}，"
                                   f"或修正 case 中的引用名称",
                    ))

    def _scan_steps(steps):
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            desc = step.get('desc', '')
            params = step.get('params', {})
            _check_params(params, desc)
            # 递归子步骤
            for sub_key in ('then_steps', 'else_steps', 'steps'):
                if sub_key in params:
                    _scan_steps(params[sub_key])

    # 检查 steps
    _scan_steps(data.get('steps', []))
    # 检查 setup_step (suites)
    _scan_steps(data.get('setup_step', []))

    return violations


# ============================================================================
# R4.31s case 中变量引用的模块作用域检查（跨模块引用检测）
# ============================================================================

_MODULE_FROM_PATH_RE = re.compile(r'(?:^|[\\/])cases[\\/]([\w][\w-]*)[\\/]')

def check_r4_31_scope(filepath: str, data: dict, lines: List[str],
                      ctx: dict) -> List[Violation]:
    """R4.31s: case 中 ${group.field} 的 group 必须属于当前模块

    防止 project-manage 的 case 引用 question_manage_search_elements。
    允许的 group 前缀: {module_prefix}_*, common_*, dropdown_menu_*
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])

    # 从文件路径推断模块
    norm_path = filepath.replace('\\', '/')
    m = _MODULE_FROM_PATH_RE.search(norm_path)
    if not m:
        return violations  # 不在 cases/{module}/ 下，跳过
    case_module = m.group(1)  # e.g. "project-manage"
    module_prefix = case_module.replace('-', '_')  # project_manage

    allowed_prefixes = (
        module_prefix,           # project_manage_xxx
        'common',                # common_elements, common_data
        'dropdown_menu',         # dropdown_menu_elements
    )

    # R4.31s: 同模块 pages YAML 中定义的 group 也允许引用
    pages_groups = ctx.get('pages_groups_by_module', {})
    same_module_groups = pages_groups.get(case_module, set())

    def _check_scope(params, step_desc):
        if not isinstance(params, dict):
            return
        for param_key in ('locator', 'value', 'expect_results'):
            val = params.get(param_key, '')
            if not isinstance(val, str):
                continue
            for m_ref in _VAR_REF_RE.finditer(val):
                ref = m_ref.group(1)
                parts = ref.split('.')
                if len(parts) < 2:
                    continue
                group = parts[0]
                field = parts[-1]

                # 跳过环境变量
                if group in ('data', 'env', 'global', 'config'):
                    continue

                # 检查 group 前缀是否属于当前模块
                if not any(group.startswith(p) for p in allowed_prefixes) \
                        and group not in same_module_groups:
                    desc = step_desc or val[:40]
                    line = find_line(lines, desc) if desc else 1
                    violations.append(Violation(
                        file=rp, line=line, rule='R4.31',
                        severity='error',
                        message=f"跨模块引用: case 属于 [{case_module}]，"
                                f"但 ${{{ref}}} 引用了 [{group}]",
                        suggestion=f"应使用 {module_prefix}_ 开头的 group，"
                                   f"或用 --strict-module 重新生成 case",
                    ))

    # 遍历所有步骤
    def _scan(steps):
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            _check_scope(step.get('params', {}), step.get('desc', ''))
            for sub in ('then_steps', 'else_steps', 'steps'):
                sub_steps = step.get('params', {}).get(sub, [])
                if isinstance(sub_steps, list):
                    _scan(sub_steps)

    _scan(data.get('steps', []))
    _scan(data.get('setup_step', []))

    return violations


# ============================================================================
# R4.33 容器上下文引用检查：打开抽屉后不应引用搜索区同名 group
# ============================================================================

_VAR_REF_RE_R33 = re.compile(r'\$\{([^}]+)\}')
_CONTAINER_OPEN_RE = re.compile(r'(?:add_btn|create_btn|new_btn|edit_btn)')
_SEARCH_GROUP_RE = re.compile(r'_search_elements$')


def check_r4_33(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """R4.33: 打开容器后引用了搜索区 group 的同名 field

    当 case 步骤 click ${xxx.add_btn} 打开抽屉/对话框后，
    后续步骤如果引用 ${search_group.field}，且该 field 在容器 group 中
    也有同名定义，说明应该引用容器 group 的版本。
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])
    pages_keys = ctx.get('pages_keys', set())

    steps = data.get('steps', [])
    if not isinstance(steps, list):
        return violations

    in_container = False
    container_groups = set()

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        kw = step.get('keyword', '')
        params = step.get('params', {})
        if not isinstance(params, dict):
            continue
        loc = params.get('locator', '')
        if not isinstance(loc, str):
            continue

        # 检测打开容器的步骤（click add_btn/edit_btn 等）
        if kw == 'click_element':
            for m in _VAR_REF_RE_R33.finditer(loc):
                ref = m.group(1)
                parts = ref.split('.')
                if len(parts) >= 2 and _CONTAINER_OPEN_RE.search(parts[-1]):
                    in_container = True
                    # 查找对应的容器 group（xxx_drawer_elements, xxx_dialog_elements）
                    field_name = parts[-1]
                    for pk in pages_keys:
                        if pk.endswith(('_drawer_elements', '_dialog_elements',
                                       '_detail_elements', '_new_elements')):
                            container_groups.add(pk.split('.')[0])
                    break

        # 在容器内检测引用
        if in_container and '${' in loc:
            for m in _VAR_REF_RE_R33.finditer(loc):
                ref = m.group(1)
                parts = ref.split('.')
                if len(parts) < 2:
                    continue
                ref_group = parts[0]
                ref_field = parts[-1]

                # 检查是否引用了搜索区 group
                if not _SEARCH_GROUP_RE.search(ref_group):
                    continue

                # 检查同名 field 是否在容器 group 中存在
                for cg in container_groups:
                    container_key = f"{cg}.{ref_field}"
                    if container_key in pages_keys:
                        desc = step.get('desc', '')
                        line = find_line(lines, desc) if desc else find_line(lines, ref)
                        violations.append(Violation(
                            file=rp, line=line, rule='R4.33', severity='error',
                            message=f"容器内引用了搜索区 group: ${{{ref}}}，"
                                    f"但 {cg}.{ref_field} 也存在（应引用容器版本）",
                            suggestion=f"将 ${{{ref}}} 改为 ${{{cg}.{ref_field}}}",
                        ))

    return violations


# ============================================================================
# R4.37 case ID 全局唯一性检查（跨文件）
# ============================================================================

def check_r4_37_cross_file(files_by_cat: dict, ctx: dict) -> List[Violation]:
    """R4.37: case ID 全局唯一 — 跨文件检查重复 ID"""
    violations = []
    project_dir = ctx['project_dir']

    id_map: Dict[str, List[str]] = {}
    for filepath in files_by_cat.get('cases', []):
        data, _ = load_yaml_with_lines(filepath)
        if data is None or not isinstance(data, dict):
            continue
        case_id = data.get('id', '')
        if case_id:
            id_map.setdefault(case_id, []).append(filepath)

    # 检查重复
    for case_id, files in id_map.items():
        if len(files) > 1:
            rp_list = [rel_path(f, project_dir) for f in files]
            violations.append(Violation(
                file=rp_list[0], line=1, rule='R4.37', severity='error',
                message=f"case ID '{case_id}' 在 {len(files)} 个文件中重复: {', '.join(rp_list)}",
                suggestion="case ID 必须包含模块标识: {module}_{action}（推荐）或 {module}-case-{NN}",
            ))

    # 多模块时检查缺少模块前缀
    module_dirs = set(
        os.path.basename(os.path.dirname(f))
        for f in files_by_cat.get('cases', [])
    )
    if len(module_dirs) > 1:
        for case_id, files in id_map.items():
            if case_id.startswith('case-') and '-' not in case_id.replace('case-', '', 1):
                rp = rel_path(files[0], project_dir)
                mod = os.path.basename(os.path.dirname(files[0]))
                violations.append(Violation(
                    file=rp, line=1, rule='R4.37', severity='warning',
                    message=f"case ID '{case_id}' 缺少模块前缀（当前 {len(module_dirs)} 个模块）",
                    suggestion=f"改为 {mod}-{case_id}",
                ))

    return violations


# ============================================================================
# R4.41 详情入口步骤必须使用知识库 Pattern 12 XPath
# ============================================================================

# Pattern 12 合法 XPath 特征（满足任一即合规）
_R4_41_LEGAL_PATTERNS = [
    re.compile(r"contains\(@class,'link-style'\)"),
    re.compile(r"contains\(@class,'click-list'\)"),
    re.compile(r"contains\(@class,'resource-id'\)"),
    re.compile(r"contains\(@class,'name'\)"),
    re.compile(r"@class='edit-name'"),
    re.compile(r"contains\(@class,'common-href'\)"),     # Fix-R431: TSManager 系统 detail-link
    re.compile(r"el-table__body-wrapper.*tr\[1\].*//a"),  # Fix-R431: 表格首行链接通用模式
    re.compile(r"el-table__body-wrapper.*//a.*\)\[1\]"),   # Fix-R431: 表格首行链接变体 (//a)[1]
]

# Pattern 12 禁止的 XPath 模式
_R4_41_FORBIDDEN_PATTERNS = [
    (re.compile(r"string-length\(normalize-space\(\)\)"), "string-length(normalize-space()) 泛化长度匹配"),
    (re.compile(r"//td\[1\]\s*//"), "//td[1] 硬编码列位置"),
]

# 详情入口步骤触发关键词
_R4_41_DETAIL_TRIGGERS = re.compile(r'进入详情|详情页面|问题描述|描述链接|点击.*描述')


def check_r4_41(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """R4.41: 详情入口步骤必须使用知识库 Pattern 12 的 XPath 变体

    当 step.desc 含"进入详情"/"问题描述"等语义，且 keyword 为 click_element 时，
    其 locator（解析后的 XPath）必须匹配 Pattern 12 的 4 种变体之一，
    禁止使用 string-length(normalize-space()) 等泛化匹配。

    Pattern 12 变体：
      ① contains(@class,'link-style'|'click-list'|'resource-id'|'name') + text
      ② contains(@class,'link-style'|...) only
      ③ contains(text(),'xxx') 文本匹配
      ④ @class='edit-name' + preceding-sibling::div[contains(@class,'link-style')]
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])
    pages_locators = ctx.get('pages_locators', {})

    steps = data.get('steps', [])
    if not isinstance(steps, list):
        return violations

    def _scan_steps(steps_list):
        for i, step in enumerate(steps_list):
            if not isinstance(step, dict):
                continue
            desc = str(step.get('desc', ''))
            keyword = step.get('keyword', '')

            # 检测详情入口语义
            if keyword == 'click_element' and _R4_41_DETAIL_TRIGGERS.search(desc):
                params = step.get('params', {})
                locator_ref = params.get('locator', '')

                # 解析 ${group.field} 引用到实际 XPath
                resolved = locator_ref
                for m in _VAR_REF_RE.finditer(locator_ref):
                    ref = m.group(1)
                    if ref in pages_locators:
                        resolved = pages_locators[ref]
                        break

                if not resolved or resolved == locator_ref:
                    continue  # 无法解析，R4.31 会捕获

                # 去掉 xpath= 前缀
                xpath = resolved
                if xpath.startswith('xpath='):
                    xpath = xpath[6:]

                # 检查禁止模式
                for forbidden_re, forbidden_desc in _R4_41_FORBIDDEN_PATTERNS:
                    if forbidden_re.search(xpath):
                        line = find_line(lines, desc[:20]) or (i + 1)
                        violations.append(Violation(
                            file=rp, line=line, rule='R4.41', severity='error',
                            message=(
                                f"详情入口步骤 '{desc}' 使用了禁止的 XPath: "
                                f"{forbidden_desc}"
                            ),
                            suggestion=(
                                "必须使用知识库 Pattern 12 的 XPath 变体探测：\n"
                                "  ① //td[...]//*[contains(@class,'link-style') or "
                                "contains(@class,'click-list')][contains(.,'{text}')]\n"
                                "  ② //td[...]//*[contains(text(),'{text}')]\n"
                                "用 probe_element.py --element \"detail-link:{label}:{key}\" 重新探测"
                            ),
                        ))
                        break

                # 检查是否包含至少一个合法 class 特征
                has_legal = any(p.search(xpath) for p in _R4_41_LEGAL_PATTERNS)
                # 变体③：纯文本匹配也算合法
                has_text_match = bool(re.search(r"contains\((text\(\)|\.),\s*['\"]", xpath))

                if not has_legal and not has_text_match and not any(
                    fr.search(xpath) for fr, _ in _R4_41_FORBIDDEN_PATTERNS
                ):
                    # 不含禁止模式也不含合法模式 — 可能是其他非标准写法
                    line = find_line(lines, desc[:20]) or (i + 1)
                    violations.append(Violation(
                        file=rp, line=line, rule='R4.41', severity='error',
                        message=(
                            f"详情入口步骤 '{desc}' 的 locator 未匹配 "
                            f"Pattern 12 的任何变体"
                        ),
                        suggestion=(
                            "使用 probe_element.py --element \"detail-link:{label}:{key}\" "
                            "按知识库 Pattern 12 重新探测"
                        ),
                    ))

            # 递归子步骤
            params = step.get('params', {})
            for sub_key in ('then_steps', 'else_steps', 'steps'):
                if sub_key in params:
                    _scan_steps(params[sub_key])

    _scan_steps(steps)
    return violations


# ============================================================================
# R4.42 detail-link 字段必须有 probe_with_knowledge 验证记录
# ============================================================================

def check_r4_42(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """R4.42: 详情入口步骤的 locator 必须经过 probe_with_knowledge 验证

    当 step.desc 含"进入详情"等语义（复用 R4.41 触发条件）时，
    其 locator 引用的 ${group.field} 必须在 probe 结果中出现，
    且 from_knowledge=true（即通过 probe_element.py 知识库遍历生成），
    而非手写或仅通过 --verify 模式验证。

    这是 R4.41 的补充：R4.41 检查 XPath 模式合规性，
    R4.42 检查该字段是否经过工具链探测（防止手写绕过知识库）。
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])
    probe_kb = ctx.get('probe_knowledge_fields', {})
    pages_locators = ctx.get('pages_locators', {})

    # 无 probe 数据时跳过（项目可能未执行探测阶段）
    if not probe_kb:
        return violations

    steps = data.get('steps', [])
    if not isinstance(steps, list):
        return violations

    def _scan_steps(steps_list):
        for i, step in enumerate(steps_list):
            if not isinstance(step, dict):
                continue
            desc = str(step.get('desc', ''))
            keyword = step.get('keyword', '')

            # 复用 R4.41 的触发条件
            if keyword == 'click_element' and _R4_41_DETAIL_TRIGGERS.search(desc):
                params = step.get('params', {})
                locator_ref = params.get('locator', '')

                # 解析 ${group.field} → 提取 field
                field_match = _VAR_REF_RE.search(locator_ref)
                if not field_match:
                    continue  # 非变量引用，R4.2/R4.41 会捕获
                ref = field_match.group(1)
                parts = ref.split('.', 1)
                if len(parts) != 2:
                    continue
                group, field = parts

                # 仅检查 _link 后缀字段（detail-link 类型）
                if not field.endswith('_link'):
                    continue

                # 检查 probe 结果中是否有此字段且 from_knowledge=true
                if field not in probe_kb:
                    # 尝试从 locator 中提取 label 用于建议
                    resolved = pages_locators.get(ref, locator_ref)
                    label = '测试数据'
                    m = re.search(r"contains\(\.?,?['\"]([^'\"]+)['\"]\)", resolved)
                    if m:
                        label = m.group(1)

                    line = find_line(lines, desc[:20]) or (i + 1)
                    violations.append(Violation(
                        file=rp, line=line, rule='R4.42', severity='error',
                        message=(
                            f"详情入口步骤 '{desc}' 的 locator "
                            f"${{{ref}}} 未经 probe_with_knowledge 验证"
                        ),
                        suggestion=(
                            f"运行 probe_from_pages.py 补探，或手动执行：\n"
                            f"  python tools/probe_element.py \"{{url}}\" "
                            f"--cookie \"...\" "
                            f"--element \"detail-link:{label}:{field}\" "
                            f"--output _probe/probe_detail_link.json\n"
                            f"知识库 Pattern 12 会按变体1→2→3→4 顺序自动探测"
                        ),
                    ))

            # 递归子步骤
            params = step.get('params', {})
            for sub_key in ('then_steps', 'else_steps', 'steps'):
                if sub_key in params:
                    _scan_steps(params[sub_key])

    _scan_steps(steps)
    return violations


# ============================================================================
# R4.43 全量覆盖门禁：核心 locator 字段必须有 probe 验证记录
# ============================================================================

# 核心操作字段后缀 — 这些字段必须经过 probe_with_knowledge 验证
_R4_43_CORE_SUFFIXES = ('_btn', '_button', '_select', '_input', '_textarea',
                        '_link', '_tab', '_checkbox', '_date', '_picker')

# 豁免 group 前缀 — 通用/详情页元素不需要逐字段探测
_R4_43_EXEMPT_GROUPS = ('common_elements', 'detail_page_elements')

# 豁免 companion 字段后缀 — 这些是主字段的附属，不需要单独探测
_R4_43_EXEMPT_SUFFIXES = ('_editable', '_first_option', '_iframe', '_body')


def check_r4_43(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """R4.43: 核心 locator 字段必须有 probe_with_knowledge 验证记录

    泛化 R4.42：不限于 detail-link，覆盖所有核心操作类型。
    扫描 case 中所有 ${group.field} 引用，检查 field 是否在 probe 结果中
    且 from_knowledge=true。

    仅检查核心后缀字段（_btn/_select/_input/_textarea/_link/_tab），
    豁免 common_elements、detail_page_elements 和 companion 字段。

    这是"缺失元素必须回退探测"的硬关卡：
    未探测的核心字段 → ERROR → 阻断 Phase 4 → 必须回到 Phase 3f 补探。
    """
    violations = []
    rp = rel_path(filepath, ctx['project_dir'])
    probe_kb = ctx.get('probe_knowledge_fields', {})

    # 无 probe 数据时跳过（项目可能未执行探测阶段）
    if not probe_kb:
        return violations

    steps = data.get('steps', [])
    if not isinstance(steps, list):
        return violations

    seen_fields = set()  # 去重：同一字段只报一次

    def _scan_steps(steps_list):
        for i, step in enumerate(steps_list):
            if not isinstance(step, dict):
                continue

            params = step.get('params', {})
            if isinstance(params, dict):
                _check_params(params, i, steps_list)

            # 递归子步骤
            for sub_key in ('then_steps', 'else_steps', 'steps'):
                if sub_key in params and isinstance(params[sub_key], list):
                    _scan_steps(params[sub_key])

    def _check_params(params, step_idx, steps_list):
        """检查 params 中所有 locator 引用"""
        for param_key in ('locator',):
            locator_ref = params.get(param_key, '')
            if not isinstance(locator_ref, str):
                continue

            for m in _VAR_REF_RE.finditer(locator_ref):
                ref = m.group(1)
                if ref in seen_fields:
                    continue

                parts = ref.split('.', 1)
                if len(parts) != 2:
                    continue
                group, field = parts

                # 豁免检查
                if any(group.startswith(eg) or group == eg for eg in _R4_43_EXEMPT_GROUPS):
                    continue
                if any(field.endswith(es) for es in _R4_43_EXEMPT_SUFFIXES):
                    continue

                # 仅检查核心后缀字段
                is_core = any(field.endswith(suffix) for suffix in _R4_43_CORE_SUFFIXES)
                if not is_core:
                    continue

                seen_fields.add(ref)

                # 检查 probe 结果
                if field not in probe_kb:
                    desc = ''
                    if isinstance(steps_list, list) and 0 <= step_idx < len(steps_list):
                        s = steps_list[step_idx]
                        if isinstance(s, dict):
                            desc = str(s.get('desc', ''))
                    line = find_line(lines, desc[:20]) if desc else (step_idx + 1)

                    violations.append(Violation(
                        file=rp, line=line, rule='R4.43', severity='error',
                        message=(
                            f"核心 locator 字段 ${{{ref}}} 未经 "
                            f"probe_with_knowledge 验证"
                        ),
                        suggestion=(
                            f"运行 Phase 3f 补探：\n"
                            f"  python tools/probe_from_pages.py "
                            f"{{project_dir}} --cookie \"...\" --url \"...\"\n"
                            f"或手动探测：\n"
                            f"  python tools/probe_element.py \"{{url}}\" "
                            f"--cookie \"...\" "
                            f"--element \"{{type}}:{{label}}:{field}\" "
                            f"--output _probe/probe_{field}.json"
                        ),
                    ))

    _scan_steps(steps)
    return violations




# ============================================================================
# SUITE_REF: suite case_id 引用存在性
# ============================================================================

def check_suite_case_refs(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """SUITE_REF: 检查 suite case_refs 引用的 case_id 是否存在"""
    violations = []
    if '/suites/' not in filepath.replace('\\', '/'):
        return violations
    for ref in data.get('case_refs', []):
        case_id = ref.get('case_id', '')
        if case_id and case_id not in ctx.get('case_ids', set()):
            violations.append(Violation(
                file=rel_path(filepath, ctx['project_dir']),
                line=0, rule='SUITE_REF', severity='error',
                message=f"suite 引用了不存在的 case_id: '{case_id}'",
                suggestion=f"请确认 cases/ 中是否有 id: '{case_id}' 的用例文件",
            ))
    return violations


# ============================================================================
# EXCEL_COMPLETE: Excel 用例转换完整性
# ============================================================================

def check_excel_completeness(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """EXCEL_COMPLETE: 检查 Excel 用例转换完整性"""
    violations = []
    project_dir = ctx.get('project_dir', '')
    for module_dir in ctx.get('module_dirs', {}).get('cases', set()):
        map_file = os.path.join(project_dir, 'cases', module_dir, '_excel_case_map.json')
        if not os.path.exists(map_file):
            continue
        try:
            with open(map_file, encoding='utf-8') as f:
                case_map = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        total = case_map.get('total_excel_cases', 0)
        generated = case_map.get('generated_cases', 0)
        failed = case_map.get('failed_cases', [])
        skipped = case_map.get('skipped_cases', [])
        all_missing = failed + skipped
        if all_missing:
            names = [str(s.get('name', '?')) for s in all_missing[:5]]
            violations.append(Violation(
                file=rel_path(map_file, project_dir),
                line=0, rule='EXCEL_COMPLETE', severity='error',
                message=f"Excel 有 {total} 条用例，仅生成 {generated} 条，"
                        f"{len(all_missing)} 条未完成（{len(failed)} 熔断+{len(skipped)} 跳过）: {names}",
                suggestion="检查 failed/skipped 的 reason，修复后重新生成",
            ))
    return violations


# ============================================================================
# R4.20 步骤顺序与 Excel 一致
# ============================================================================

def check_r4_20(filepath: str, data: dict, lines: List[str], ctx: dict) -> List[Violation]:
    """R4.20: 检查 case 步骤顺序与 Excel 原始顺序一致（基于 _source_map.json）

    读取 _source_map.json，验证每个 case 的 excel_step 序列单调递增。
    手写 case（无 _source_map.json）自动跳过。
    """
    violations = []
    project_dir = ctx.get('project_dir', '')
    for module_dir in ctx.get('module_dirs', {}).get('cases', set()):
        map_file = os.path.join(project_dir, 'cases', module_dir, '_source_map.json')
        if not os.path.exists(map_file):
            continue
        try:
            with open(map_file, encoding='utf-8') as f:
                source_map = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        for case_id, mappings in source_map.items():
            if not isinstance(mappings, list) or len(mappings) < 2:
                continue
            excel_steps = [m.get('excel_step', 0) for m in mappings]
            for j in range(1, len(excel_steps)):
                if excel_steps[j] < excel_steps[j - 1]:
                    violations.append(Violation(
                        file=rel_path(map_file, project_dir),
                        line=0, rule='R4.20', severity='error',
                        message=f"case '{case_id}': 步骤顺序与 Excel 不一致 "
                                f"(excel_step[{j}]={excel_steps[j]} < "
                                f"excel_step[{j-1}]={excel_steps[j-1]})",
                        suggestion="重新使用 generate_from_excel.py 生成，保持与 Excel 原始顺序一致",
                    ))
                    break  # 每个 case 只报第一个违规
    return violations


# ============================================================================
# 报告与主函数
# ============================================================================

# 检查的规则编号列表（仅保留 14 个跨文件规则）
CHECKED_RULES = [
    'R4.1', 'R4.3', 'R4.7', 'R4.20', 'R4.31', 'R4.31s', 'R4.33', 'R4.37',
    'R4.41', 'R4.42', 'R4.43',
    'PREREQUISITE', 'SUITE_REF', 'EXCEL_COMPLETE',
]


def format_report(violations: List[Violation], project_dir: str) -> str:
    """生成违规报告"""
    rules_str = ', '.join(CHECKED_RULES)

    if not violations:
        return (
            "======================================================================\n"
            f"UIEngine Cross-File Validation Report (Phase 5)\n"
            f"Project: {os.path.basename(project_dir)}\n"
            "======================================================================\n"
            "\n"
            "  ✓ All checks passed! No rule violations found.\n"
            "\n"
            f"Summary: 0 errors, 0 warnings\n"
            f"Checked: {rules_str}\n"
            "======================================================================\n"
        )

    # 按文件分组
    by_file: Dict[str, List[Violation]] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)

    lines = [
        "======================================================================",
        "UIEngine Cross-File Validation Report (Phase 5)",
        f"Project: {os.path.basename(project_dir)}",
        "======================================================================",
        "",
    ]

    error_count = 0
    warning_count = 0

    for filepath in sorted(by_file.keys()):
        file_violations = sorted(by_file[filepath], key=lambda v: v.line)
        lines.append(f"{filepath}:")
        for v in file_violations:
            severity_tag = "[ERROR]" if v.severity == 'error' else "[WARN] "
            if v.severity == 'error':
                error_count += 1
            else:
                warning_count += 1

            lines.append(
                f"  Line {v.line:<5} {severity_tag} {v.rule}: {v.message}"
            )
            lines.append(
                f"  {'':>12} Suggestion: {v.suggestion}"
            )
        lines.append("")

    lines.append("-" * 70)
    lines.append(
        f"Summary: {error_count} error(s), {warning_count} warning(s) "
        f"across {len(by_file)} file(s)"
    )
    lines.append(f"Checked: {rules_str}")
    lines.append("Not checked (single-file): moved to generation tool self-check layers")
    lines.append("=" * 70)
    lines.append("")

    return "\n".join(lines)


# ============================================================================
# JSON 导出（供 generate_issues_report.py 消费）
# ============================================================================

def _export_phase5_json(project_dir: str, violations: List[Violation]):
    """导出 Phase 5 violations 到 JSON（供 HTML 联合报告消费）"""
    data = [
        {
            'file': v.file, 'line': v.line, 'rule': v.rule,
            'severity': v.severity, 'message': v.message,
            'suggestion': v.suggestion,
        }
        for v in violations
    ]
    output_path = os.path.join(project_dir, '_probe', 'phase5_violations.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================================
# 主函数
# ============================================================================

def main():
    # 确保 Windows 终端输出 UTF-8
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description="UIEngine Phase 5 跨文件脚本验证器"
    )
    parser.add_argument(
        'project_dir',
        help="项目根目录路径（包含 cases/pages/data/suites 的目录）"
    )
    parser.add_argument(
        '--stage', choices=['all', 'early', 'final'], default='all',
        help="验证阶段: early=结构一致性, final=语义一致性, all=全部（默认）"
    )
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    # 发现文件
    files_by_cat = discover_yaml_files(project_dir)
    total_files = sum(len(v) for v in files_by_cat.values())

    if total_files == 0:
        print(f"[WARN] 项目目录中未找到 YAML 文件: {project_dir}")
        sys.exit(0)

    # 构建上下文
    ctx = build_context(files_by_cat)
    ctx['project_dir'] = project_dir

    # 加载 probe 结果（供 R4.42/R4.43 验证）
    ctx['probe_knowledge_fields'] = _load_probe_knowledge_fields(project_dir)

    # ── 统一阶段门禁：检查前置阶段执行证据 ──
    _sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _sys_path not in sys.path:
        sys.path.insert(0, _sys_path)
    from tools._phase_registry import check_prerequisite_phases
    prereq_violations = check_prerequisite_phases(project_dir, 'validate_05')
    all_violations: List[Violation] = list(prereq_violations)

    # 加载 L3 模块关键字（保留供上下文使用）
    ctx['l3_keywords'] = _load_l3_keyword_names(project_dir)
    if ctx['l3_keywords']:
        print(f"[INFO] L3 关键字: {', '.join(sorted(ctx['l3_keywords']))}")

    # ── 跨文件 checker（对 cases 逐文件执行，不含项目级检查）──
    cross_file_checkers = [
        check_r4_1,        # R4.1 四层目录模块名一致
        check_r4_31,       # R4.31 变量引用存在性
        check_r4_31_scope, # R4.31s 变量引用模块作用域
        check_r4_33,       # R4.33 容器上下文引用
        check_r4_41,       # R4.41 详情入口 Pattern 12
        check_r4_42,       # R4.42 详情入口 probe 验证
        check_r4_43,       # R4.43 核心 locator probe 记录
    ]

    # Cases: apply cross-file checkers
    for filepath in files_by_cat.get('cases', []):
        data, raw_lines = load_yaml_with_lines(filepath)
        if data is None or not isinstance(data, dict):
            continue
        for checker in cross_file_checkers:
            violations = checker(filepath, data, raw_lines, ctx)
            all_violations.extend(violations)

    # Suites: R4.7 + SUITE_REF + R4.31 (项目级 + 跨文件)
    for filepath in files_by_cat.get('suites', []):
        data, raw_lines = load_yaml_with_lines(filepath)
        if data is None or not isinstance(data, dict):
            continue
        for checker in [check_r4_7, check_suite_case_refs, check_r4_31]:
            violations = checker(filepath, data, raw_lines, ctx)
            all_violations.extend(violations)

    # R4.3 cross-file: el-select option text vs data search value
    all_search_vals = set()
    for entries in ctx.get('data_search_values', {}).values():
        for _, val in entries:
            all_search_vals.add(val)

    for pages_file, entries in ctx.get('pages_option_texts', {}).items():
        for field_name, option_text in entries:
            found = any(option_text in sv or sv in option_text for sv in all_search_vals)
            if not found:
                rp = rel_path(pages_file, project_dir)
                all_violations.append(Violation(
                    file=rp, line=0, rule='R4.3', severity='error',
                    message=f"{field_name} 选项文本 '{option_text}' 在 data/ 搜索值中未找到匹配",
                    suggestion="选项 XPath 的 contains 文本必须与 data/ 中对应的 _search 值一致，禁止从 probe select_options 随意取值",
                ))

    # R4.37 cross-file: case ID uniqueness
    r437_violations = check_r4_37_cross_file(files_by_cat, ctx)
    all_violations.extend(r437_violations)

    # R4.20 + EXCEL_COMPLETE (cross-file, execute once)
    all_violations.extend(check_r4_20('', {}, [], ctx))
    all_violations.extend(check_excel_completeness('', {}, [], ctx))

    # NO pages checks (moved to _pages_writer.py self-check layer)
    # NO data checks (moved upstream)

    # ── Stage-based filtering ──
    # EARLY rules: 结构一致性（不依赖 Phase 3f 结果）
    EARLY_RULES = {'R4.1', 'R4.31', 'R4.31s', 'R4.37', 'PREREQUISITE'}
    # FINAL rules: 语义一致性（依赖 Phase 3f 结果）
    FINAL_RULES = {'R4.3', 'R4.7', 'R4.20', 'R4.33', 'R4.41', 'R4.42', 'R4.43',
                   'SUITE_REF', 'EXCEL_COMPLETE', 'PREREQUISITE'}

    if args.stage == 'early':
        all_violations = [v for v in all_violations if v.rule in EARLY_RULES]
    elif args.stage == 'final':
        all_violations = [v for v in all_violations if v.rule in FINAL_RULES]
    # 'all' = no filtering (default behavior)

    # 输出报告
    report = format_report(all_violations, project_dir)
    print(report)

    # 导出 JSON 供 HTML 联合报告消费
    _export_phase5_json(project_dir, all_violations)

    # 退出码
    has_errors = any(v.severity == 'error' for v in all_violations)
    sys.exit(1 if has_errors else 0)


if __name__ == '__main__':
    main()
