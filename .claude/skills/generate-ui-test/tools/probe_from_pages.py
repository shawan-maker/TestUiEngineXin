#!/usr/bin/env python3
"""
probe_from_pages.py — 从 pages/cases YAML 反向补全探测覆盖（Phase 6）v2

核心作用：确保所有 pages YAML 和 cases 中的定位器都经过 probe 验证。
当 AI 手动添加/编辑 pages YAML 或在 case 中硬编码 locator 时，
这些定位器未经 probe_element.py 验证，导致 R3.10 报错。

本工具 v2 改造：
1. 按 pages YAML group 粒度组织探测批次（不再按容器类型合并）
2. L1/L2 可达性分类 + case 扫描触发链
3. URL 路由表（config page_urls + harvest 推断）
4. 使用 --verify 模式直接验证已有 locator（不再重新搜索策略）
5. _input 伴生字段处理

用法:
    python probe_from_pages.py <project_dir> [--cookie "..."] [--url "..."] [--dry-run]
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("[FATAL] 需要 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# 本工具路径（用于 subprocess 调用 probe_element.py）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROBE_SCRIPT = os.path.join(SCRIPT_DIR, 'probe_element.py')

# 共享隐藏过滤注入函数（Fix 6: 统一三处注入逻辑，修复原 _find_final_predicate_close bug）
sys.path.insert(0, SCRIPT_DIR)
from xpath_utils import inject_hidden_filter as add_hidden_filter, has_hidden_filter as _has_hidden_filter
from _yaml_utils import escape_yaml_scalar

# 不需要探测的关键字
NO_PROBE_KEYWORDS = {
    'open_url', 'refresh', 'wait_for_time',
    'wait_for_element_hidden', 'wait_for_element',
    'execute_script', 'inject_local_storage', 'inject_cookies',
    'set_variable', 'set_variable_from_element',
    'log', 'goto_step', 'open_browser',
    'wait_for_load', 'wait_for_network', 'wait_for_url',
    'set_default_timeout', 'scroll_to_height', 'scroll_to_element',
}

# key 后缀 → 元素类型推断 (canonical KB keys)
TYPE_SUFFIXES = {
    '_btn': 'button', '_button': 'button',
    '_select': 'el-select', '_dropdown': 'el-select',
    '_input': 'input-generic', '_textarea': 'textarea-generic',
    '_tab': 'tab', '_checkbox': 'checkbox',
    '_date': 'date-picker', '_picker': 'date-picker',
    '_option': 'option', '_first_option': 'option',
    '_link': 'detail-link', '_menu': 'menu-item',
    '_editable': 'el-select',  # el-select 条件分支伴随字段
}

# observe 触发器字段名集合
_OBSERVE_TRIGGERS = {
    'desc_link', 'first_order_link', 'first_project_link',
    'first_message', 'product_outbound_btn', 'first_row_link',
}


# ===========================================================================
# 配置加载
# ===========================================================================

def load_config(project_dir: str) -> dict:
    """从 config.yaml 加载 target_url、cookie、local_storage、page_urls"""
    config_path = os.path.join(project_dir, 'config.yaml')
    if not os.path.exists(config_path):
        return {}
    with open(config_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return {
        'target_url': cfg.get('target_url', ''),
        'cookie': cfg.get('cookie', ''),
        'cookie_domain': cfg.get('cookie_domain', ''),
        'local_storage': cfg.get('local_storage', {}),
        'page_urls': cfg.get('page_urls', {}),
        'viewport': cfg.get('viewport', {}),
    }


# ===========================================================================
# pages YAML 扫描
# ===========================================================================

def scan_pages_yaml(pages_dir: str) -> Tuple[dict, dict]:
    """扫描 pages/**/*.yaml，返回 (pages_data, source_files)

    pages_data: {group: {field: locator}}
    source_files: {group: filepath}
    """
    pages_data = {}
    source_files = {}

    if not os.path.isdir(pages_dir):
        return pages_data, source_files

    for root, _, files in os.walk(pages_dir):
        for f in sorted(files):
            if not f.endswith('.yaml'):
                continue
            filepath = os.path.join(root, f)
            try:
                with open(filepath, encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
            except Exception as e:
                print(f"[WARN] 跳过无法解析的 YAML: {filepath} — {str(e)[:120]}")
                continue
            if not data or not isinstance(data, dict):
                continue
            for group_name, fields in data.items():
                # BUG-1 审计修复: 排除 page_urls 元数据
                if group_name == 'page_urls':
                    continue
                if not isinstance(fields, dict):
                    continue
                if group_name not in pages_data:
                    pages_data[group_name] = {}
                source_files[group_name] = filepath
                for field_name, locator in fields.items():
                    if isinstance(locator, str):
                        pages_data[group_name][field_name] = locator

    return pages_data, source_files


# ===========================================================================
# cases YAML 扫描
# ===========================================================================

def _extract_locators_from_params(params: dict, pages_data: dict,
                                  source_file: str, result_vars: list,
                                  result_hard: list):
    """从 params 中提取 locator 引用"""
    if not isinstance(params, dict):
        return
    locator = params.get('locator', '')
    if not isinstance(locator, str) or not locator.strip():
        return

    var_match = re.findall(r'\$\{([^}]+)\}', locator)
    for ref in var_match:
        parts = ref.split('.')
        if len(parts) >= 2:
            group, field = parts[0], parts[-1]
            if '_data' in group:
                continue
            actual = ''
            if group in pages_data and field in pages_data[group]:
                actual = pages_data[group][field]
            result_vars.append({
                'key': field,
                'group': group,
                'locator': actual,
                'source_file': source_file,
                'ref': f'${{{ref}}}',
            })

    if '${' not in locator:
        stripped = locator.strip()
        if (stripped.startswith('xpath=') or stripped.startswith('//')
                or stripped.startswith('.') or stripped.startswith('text=')
                or stripped.startswith('role=')):
            result_hard.append({
                'locator': stripped,
                'source_file': source_file,
            })


def _scan_steps_recursive(steps: list, pages_data: dict,
                           source_file: str, result_vars: list,
                           result_hard: list):
    """递归扫描步骤列表"""
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        keyword = step.get('keyword', '')
        if keyword in NO_PROBE_KEYWORDS:
            continue
        params = step.get('params', {})
        _extract_locators_from_params(params, pages_data, source_file,
                                       result_vars, result_hard)
        for sub_key in ('then_steps', 'else_steps', 'steps'):
            if sub_key in params:
                _scan_steps_recursive(params[sub_key], pages_data,
                                       source_file, result_vars, result_hard)


def scan_cases_yaml(cases_dir: str, suites_dir: str, knowledge_dir: str,
                     pages_data: dict, data_dir: str = '') -> Tuple[list, list]:
    """扫描 cases + suites + _knowledge + data，返回 (variable_refs, hardcoded_locators)"""
    result_vars = []
    result_hard = []

    if os.path.isdir(cases_dir):
        for root, _, files in os.walk(cases_dir):
            for f in sorted(files):
                if not f.endswith('.yaml'):
                    continue
                filepath = os.path.join(root, f)
                with open(filepath, encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
                if not data or not isinstance(data, dict):
                    continue
                steps = data.get('steps', [])
                _scan_steps_recursive(steps, pages_data, filepath,
                                       result_vars, result_hard)

    if os.path.isdir(suites_dir):
        for root, _, files in os.walk(suites_dir):
            for f in sorted(files):
                if not f.endswith('.yaml'):
                    continue
                filepath = os.path.join(root, f)
                with open(filepath, encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
                if not data or not isinstance(data, dict):
                    continue
                setup = data.get('setup_step', [])
                _scan_steps_recursive(setup, pages_data, filepath,
                                       result_vars, result_hard)

    if os.path.isdir(knowledge_dir):
        for root, _, files in os.walk(knowledge_dir):
            for f in sorted(files):
                if not f.endswith('.yaml'):
                    continue
                filepath = os.path.join(root, f)
                with open(filepath, encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
                if not data or not isinstance(data, dict):
                    continue
                workflows = data.get('workflows', [])
                for wf in workflows:
                    if isinstance(wf, dict):
                        wf_steps = wf.get('steps', [])
                        _scan_steps_recursive(wf_steps, pages_data, filepath,
                                               result_vars, result_hard)

    # CROSS-8 fix: 扫描 data/ 目录中的 locator 引用
    if data_dir and os.path.isdir(data_dir):
        _VAR_REF_RE = re.compile(r'\$\{([^}]+)\}')
        for root, _, files in os.walk(data_dir):
            for f in sorted(files):
                if not f.endswith('.yaml'):
                    continue
                filepath = os.path.join(root, f)
                with open(filepath, encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
                if not data or not isinstance(data, dict):
                    continue
                for gname, fields in data.items():
                    # BUG-1 审计修复: 排除 page_urls 元数据
                    if gname == 'page_urls':
                        continue
                    if not isinstance(fields, dict):
                        continue
                    for fname, value in fields.items():
                        if not isinstance(value, str):
                            continue
                        for m in _VAR_REF_RE.finditer(value):
                            ref = m.group(1)
                            parts = ref.split('.')
                            if len(parts) >= 2 and parts[0] in pages_data:
                                result_vars.append({
                                    'ref': ref,
                                    'key': parts[1],
                                    'group': parts[0],
                                    'locator': f'${{{ref}}}',
                                    'source_file': filepath,
                                    'context': f"data:{gname}.{fname}",
                                })

    return result_vars, result_hard


# ===========================================================================
# 触发链扫描（从 case 中提取 group → trigger 映射）
# ===========================================================================

def _parse_var_ref(locator_str):
    """从 ${group.field} 中提取 (group, field)"""
    if not isinstance(locator_str, str):
        return None
    m = re.match(r'^\$\{([^}]+)\}$', locator_str.strip())
    if not m:
        return None
    parts = m.group(1).split('.')
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return None


def scan_trigger_chains(cases_dir: str, pages_data: dict) -> dict:
    """从 case YAML 中提取 group → trigger 映射

    扫描步骤序列，找模式：
      click ${A_group.xxx_btn}
      [wait 等非 click 步骤可跳过]
      fill/click/... ${B_group.yyy}

    → B_group 的 trigger = (mode, A_group, xxx_btn)

    返回: {target_group: (mode, trigger_group, trigger_field)}
    """
    chains = {}
    if not os.path.isdir(cases_dir):
        return chains

    for root, _, files in os.walk(cases_dir):
        for f in sorted(files):
            if not f.endswith('.yaml'):
                continue
            filepath = os.path.join(root, f)
            with open(filepath, encoding='utf-8') as fh:
                data = yaml.safe_load(fh)
            if not data or not isinstance(data, dict):
                continue
            steps = data.get('steps', [])
            _extract_chains_from_steps(steps, chains)

    return chains


def _extract_chains_from_steps(steps: list, chains: dict):
    """从步骤列表中提取触发链"""
    if not isinstance(steps, list):
        return

    last_click_ref = None  # (group, field)

    for step in steps:
        if not isinstance(step, dict):
            continue
        keyword = step.get('keyword', '')
        params = step.get('params', {})
        locator = params.get('locator', '')

        # 递归子步骤
        for sub_key in ('then_steps', 'else_steps', 'steps'):
            if sub_key in params:
                _extract_chains_from_steps(params[sub_key], chains)

        if keyword in ('click_element', 'click'):
            ref = _parse_var_ref(locator)
            if ref:
                last_click_ref = ref
            continue

        if keyword in ('fill_value', 'select_option', 'click_element',
                       'frame_fill_value', 'check_element', 'uncheck_element') and last_click_ref:
            ref = _parse_var_ref(locator)
            if ref and ref[0] != last_click_ref[0]:
                target_group = ref[0]
                if target_group not in chains:
                    trigger_field = last_click_ref[1]
                    mode = 'observe' if trigger_field in _OBSERVE_TRIGGERS else 'action'
                    chains[target_group] = (mode, last_click_ref[0], trigger_field)

        # wait 类步骤不重置 last_click_ref
        if keyword not in ('wait_for_time', 'wait_for_element',
                           'wait_for_element_hidden', 'wait_for_load'):
            if keyword in ('click_element', 'click'):
                pass  # click 已处理
            elif keyword in ('fill_value', 'select_option', 'frame_fill_value'):
                pass  # fill 不重置
            else:
                last_click_ref = None  # 其他操作重置


# ===========================================================================
# R4.11 隐藏过滤自动补齐
# ===========================================================================

# _is_exempt, _has_hidden_filter, _find_final_predicate_close, add_hidden_filter
# 已移至 xpath_utils.py 共享模块（通过顶部 import 引入，修复了原 _find_final_predicate_close bug）


def apply_hidden_filters(pages_dir: str, pages_data: dict,
                          source_files: dict) -> int:
    modified_count = 0
    file_changes = {}

    for group_name, fields in pages_data.items():
        for field_name, locator in fields.items():
            new_locator = add_hidden_filter(locator)
            if new_locator != locator:
                pages_data[group_name][field_name] = new_locator
                modified_count += 1
                src = source_files.get(group_name, '')
                if src:
                    file_changes.setdefault(src, []).append(
                        (locator, new_locator, field_name))

    for filepath, changes in file_changes.items():
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
        for old_val, new_val, field_name in changes:
            for i, line in enumerate(lines):
                # 行级精准替换：只在 YAML 值位置（冒号后）替换，避免污染注释或其他字段
                if ':' in line and old_val in line:
                    key_part, sep, val_part = line.partition(':')
                    # M1: 检查字段名精确匹配（防止后缀重叠的误替换）
                    if old_val in val_part and key_part.strip() == field_name:
                        lines[i] = key_part + sep + val_part.replace(old_val, new_val, 1)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    return modified_count


# ===========================================================================
# 清除 not(ancestor) 负向排除（R3.14：禁止负向排除，改用正向容器前缀）
# ===========================================================================

_NOT_ANCESTOR_RE = re.compile(
    r"\s+and\s+not\(ancestor::\*\[contains\(@class,'(?:el-drawer|el-dialog|el-message-box)'\)\]\)"
)


def _strip_not_ancestor_exclusion(locator: str) -> str:
    """移除 locator 中的 not(ancestor::*[contains(@class,'el-drawer')]) 等负向排除条件

    R3.14：禁止使用 not(ancestor::...) 负向排除。
    元素定位应使用正向容器前缀（如 //div[contains(@class,'el-drawer')]//button[...]），
    探测阶段会自动尝试有前缀 → 无前缀的降级策略。
    """
    return _NOT_ANCESTOR_RE.sub('', locator)


def strip_not_ancestor_exclusions(pages_dir: str, pages_data: dict,
                                   source_files: dict) -> int:
    """清除所有 locator 中的 not(ancestor::...) 负向排除条件

    替代原 apply_cross_group_exclusions()：不再注入负向排除，
    而是清除已有的负向排除，确保所有 locator 只使用正向容器前缀。

    返回清除的定位器数量。
    """
    modified_count = 0
    file_changes = {}

    for group_name, fields in pages_data.items():
        for field_name, locator in fields.items():
            if not isinstance(locator, str) or not locator.startswith('xpath='):
                continue
            new_locator = _strip_not_ancestor_exclusion(locator)
            if new_locator != locator:
                pages_data[group_name][field_name] = new_locator
                modified_count += 1
                src = source_files.get(group_name, '')
                if src:
                    file_changes.setdefault(src, []).append(
                        (locator, new_locator, field_name))

    # 回写文件
    for filepath, changes in file_changes.items():
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
        for old_val, new_val, field_name in changes:
            for i, line in enumerate(lines):
                # 行级精准替换：只在 YAML 值位置（冒号后）替换，避免污染注释或其他字段
                if ':' in line and old_val in line:
                    key_part, sep, val_part = line.partition(':')
                    # M1: 检查字段名匹配
                    if old_val in val_part and key_part.strip().endswith(field_name):
                        lines[i] = key_part + sep + val_part.replace(old_val, new_val, 1)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    return modified_count


# ===========================================================================
# probe DB 加载
# ===========================================================================

def load_probe_db(probe_dir: str) -> dict:
    """加载所有 probe JSON 到扁平 {key: element} 字典

    方案 A: 优先级排序 — supplement 最后加载（最高优先级），确保补探结果覆盖初始结果。
    消除 glob 遍历顺序的非确定性。
    """
    probe_db = {}
    if not os.path.isdir(probe_dir):
        return probe_db

    # 分三批加载，后加载的覆盖先加载的
    all_files = glob.glob(os.path.join(probe_dir, '**/*.json'), recursive=True)

    # 分类: initial(最低) → other → supplement(最高)
    # 使用 startswith 前缀匹配而非子串包含，避免 probe_reinitialize.json 等误分类
    initial_files = []
    supplement_files = []
    other_files = []
    for fp in all_files:
        basename = os.path.basename(fp)
        if 'harvest' in basename:
            continue
        if basename.startswith('probe_supplement'):
            supplement_files.append(fp)
        elif basename.startswith('probe_initial'):
            initial_files.append(fp)
        else:
            other_files.append(fp)

    # 按优先级顺序加载: initial → other → supplement
    ordered_files = sorted(initial_files) + sorted(other_files) + sorted(supplement_files)

    for filepath in ordered_files:
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            # L5: 不再静默吞掉 JSON 解码错误
            print(f"  [WARN] {os.path.basename(filepath)}: JSON 解析失败 — {e}")
            continue
        except Exception:
            continue
        if isinstance(data, list):
            for el in data:
                if not isinstance(el, dict):
                    continue
                key = el.get('key', '')
                if key:
                    probe_db[key] = el
        elif isinstance(data, dict):
            for el in data.get('elements', []):
                key = el.get('key', '')
                if key:
                    # N4: 冲突检测 — supplement 覆盖 verified=true 为 verified=false 时保留已验证结果
                    if key in probe_db and probe_db[key].get('verified') and not el.get('verified'):
                        print(f"  [INFO] {key}: 保留已验证结果（verified=true），不覆盖为 verified=false")
                    else:
                        probe_db[key] = el
    return probe_db


# ===========================================================================
# Harvest 缓存加载
# ===========================================================================

def load_harvest_cache(probe_dir: str) -> dict:
    """从 harvest_*.json 文件加载 URL 缓存 + 完整数据

    返回: {module_name: {url: "...", select_options: {...}, detected_patterns: {...}}}
    """
    cache = {}
    if not os.path.isdir(probe_dir):
        return cache

    for filepath in glob.glob(os.path.join(probe_dir, 'harvest*.json')):
        try:
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                url = data.get('url', '')
                if url:
                    # harvest_mail.json → "mail"
                    basename = os.path.basename(filepath)
                    name = basename.replace('harvest_', '').replace('.json', '')
                    if name == 'harvest':
                        name = 'default'
                    cache[name] = {
                        'url': url,
                        'select_options': data.get('select_options', {}),
                        'detected_patterns': data.get('detected_patterns', {}),
                    }
        except Exception:
            continue
    return cache


def cross_check_harvest_vs_pages(pages_data: dict, harvest_cache: dict,
                                  source_files: dict) -> list:
    """D4/P-20: 交叉检查 harvest DOM 数据与 pages YAML 的一致性

    检查项:
    1. el-select 选项覆盖: harvest 发现的 select_options 是否在 pages 中有对应 _option 字段
    2. 表格结构: harvest 检测到表格固定列但 pages 无 table_action_elements group → 警告
    3. 容器类型: pages 中 drawer/dialog 前缀与 harvest 的 container_type 是否一致

    返回: warning 列表 [(message, suggestion), ...]
    """
    warnings = []

    # 收集 pages 中所有 el-select 字段名（去掉 _select/_input/_option 后缀）
    pages_select_fields = set()
    pages_has_table_action = False
    pages_container_types = set()

    for group_name, fields in pages_data.items():
        if not isinstance(fields, dict):
            continue
        for field_name in fields:
            # el-select 相关字段
            if field_name.endswith('_select') or field_name.endswith('_input'):
                base = field_name.rsplit('_', 1)[0]
                pages_select_fields.add(base)
            # table action group
            if 'table_action' in group_name.lower():
                pages_has_table_action = True
        # 容器类型检测
        for field_name, locator in fields.items():
            if isinstance(locator, str):
                if 'el-drawer' in locator:
                    pages_container_types.add('drawer')
                elif 'el-dialog' in locator:
                    pages_container_types.add('dialog')

    # 收集 harvest 中所有 select_options 和 detected_patterns
    harvest_select_labels = set()
    harvest_has_table = False
    harvest_has_fixed_right = False
    harvest_container_type = None

    for module_name, harvest_data in harvest_cache.items():
        select_options = harvest_data.get('select_options', {})
        detected_patterns = harvest_data.get('detected_patterns', {})

        for key in select_options:
            # el-select:index_0 → "index_0", el-select:Please select → "Please select"
            if key.startswith('el-select:'):
                label = key.split(':', 1)[1]
                harvest_select_labels.add(label)

        dp = detected_patterns
        ts = dp.get('table_structure', {})
        if ts.get('has_table'):
            harvest_has_table = True
        if ts.get('has_fixed_right'):
            harvest_has_fixed_right = True
        ct = dp.get('container_type', 'none')
        if ct != 'none':
            harvest_container_type = ct

    # 检查 1: 表格结构
    if harvest_has_fixed_right and not pages_has_table_action:
        warnings.append((
            "[D4/P-20] harvest 检测到表格有固定右列（操作列），"
            "但 pages YAML 中无 table_action_elements group",
            "建议添加 table_action_elements group 来定义操作列按钮的定位器"
        ))

    # 检查 2: 容器类型一致性
    if harvest_container_type and pages_container_types:
        if harvest_container_type == 'drawer' and 'dialog' in pages_container_types and 'drawer' not in pages_container_types:
            warnings.append((
                f"[D4/P-20] harvest 检测到容器类型为 drawer，"
                f"但 pages YAML 中只有 dialog 前缀，无 drawer 前缀",
                "请确认容器类型是否正确（可能是 el-drawer 而非 el-dialog）"
            ))
        elif harvest_container_type == 'dialog' and 'drawer' in pages_container_types and 'dialog' not in pages_container_types:
            warnings.append((
                f"[D4/P-20] harvest 检测到容器类型为 dialog，"
                f"但 pages YAML 中只有 drawer 前缀，无 dialog 前缀",
                "请确认容器类型是否正确（可能是 el-dialog 而非 el-drawer）"
            ))

    return warnings


# ===========================================================================
# 覆盖检查（按 group 分组）
# ===========================================================================

def find_uncovered_by_group(variable_refs: list, hardcoded_locators: list,
                            probe_db: dict, pages_data: dict) -> dict:
    """找出未覆盖的元素，按 group 分组

    Gap 1 修复: 不仅检查 key 是否在 probe_db 中，还检查 verified 状态。
    KB-fallback (verified=False) 和 verified=False 的元素均判定为未覆盖，触发补探。

    返回: {group_name: {field: locator}}
    """
    uncovered = {}  # {group: {field: locator}}
    seen_keys = set()  # R2-M4: 改为 (group, key) 元组，避免跨 group 同名去重

    # 变量引用 — 按 key 名匹配
    for ref in variable_refs:
        key = ref['key']
        group = ref.get('group', '')
        seen_id = (group, key)
        if seen_id in seen_keys:
            continue
        seen_keys.add(seen_id)

        is_uncovered = False
        if key not in probe_db:
            # key 不存在 → 未覆盖
            is_uncovered = True
        elif not probe_db[key].get('verified', False):
            # Gap 1: verified=False（KB-fallback 或探测失败）→ 需补探确认
            is_uncovered = True

        if is_uncovered:
            locator = ref.get('locator', '')
            # 优先使用 probe_db 中的 locator（即使是 kb-fallback 也有一个初始值）
            if not locator and key in probe_db:
                locator = probe_db[key].get('locator', '')
            if not locator and group in pages_data and key in pages_data[group]:
                locator = pages_data[group][key]
            if group:
                uncovered.setdefault(group, {})[key] = locator
            else:
                uncovered.setdefault('_ungrouped', {})[key] = locator

    # 硬编码 locator — 按 locator 值匹配
    seen_locs = set()
    for hc in hardcoded_locators:
        loc = hc['locator']
        if loc in seen_locs:
            continue
        seen_locs.add(loc)
        found = False
        for el in probe_db.values():
            if el.get('locator', '') == loc:
                found = True
                break
        if not found:
            key = _make_key_from_locator(loc)
            uncovered.setdefault('_hardcoded', {})[key] = loc

    return uncovered


def _make_key_from_locator(locator: str) -> str:
    m = re.search(r"contains\(\.?,?['\"]([^'\"]+)['\"]\)", locator)
    if m:
        return f"hardcoded_{m.group(1)[:10]}"
    return f"hardcoded_{hash(locator) % 10000:04d}"


# ===========================================================================
# L1/L2 分类 + 触发器推断
# ===========================================================================

def classify_group(group_name: str, fields: dict) -> str:
    """判定 group 的可达性级别: L1 或 L2"""
    # L2 判定规则

    # 规则 1: group 名含容器/导航关键词
    L2_NAME_PATTERNS = [
        r'_drawer', r'_dialog', r'_update_', r'_filter_',
        r'_detail_', r'_new_', r'_dropdown_', r'_pmo_update',
    ]
    for pat in L2_NAME_PATTERNS:
        if re.search(pat, group_name):
            return 'L2'

    # 规则 2: 任一 locator 含容器前缀
    for field, locator in fields.items():
        if re.search(r"contains\(@class,'el-(drawer|dialog|message-box)'\)", locator):
            return 'L2'

    # 规则 3: locator 含 x_placement（下拉菜单选项）
    for field, locator in fields.items():
        if '@x-placement' in locator:
            return 'L2'

    return 'L1'


def _module_from_path(source_file: str) -> str:
    """从 pages YAML 路径推断模块名"""
    parts = source_file.replace('\\', '/').split('/')
    for i, p in enumerate(parts):
        if p == 'pages' and i + 1 < len(parts):
            return parts[i + 1]
    # 兜底：从文件名推断
    basename = os.path.basename(source_file).replace('.yaml', '')
    return basename


def _module_from_group(group_name: str, source_files: dict) -> str:
    """从 group 名 + source_files 推断模块名"""
    src = source_files.get(group_name, '')
    if src:
        return _module_from_path(src)
    # 从 group 名前缀推断
    for prefix in ['question_', 'project_', 'work_order_', 'mail_',
                   'overview_', 'impl_', 'delivery_', 'order_',
                   'common', 'first_row']:
        if group_name.startswith(prefix):
            return prefix.rstrip('_')
    return ''


def resolve_url(group_name: str, source_file: str, config: dict,
                harvest_cache: dict) -> str:
    """为 group 解析正确的 URL"""
    module = _module_from_path(source_file) if source_file else ''
    if not module:
        module = _module_from_group(group_name, {})

    # 1. config.yaml 的 page_urls
    page_urls = config.get('page_urls', {})
    if module in page_urls:
        return page_urls[module]

    # 2. harvest 缓存
    if module in harvest_cache:
        url = harvest_cache[module].get('url', '')
        if url:
            return url

    # 3. 兜底
    return config.get('target_url', '')


def find_trigger(group_name: str, module: str, pages_data: dict,
                  trigger_chains: dict, source_files: dict = None) -> Optional[tuple]:
    """为 L2 group 查找触发器

    返回: (mode, trigger_locator) 或 None
    """
    # 优先从 case 扫描结果获取
    if group_name in trigger_chains:
        mode, trigger_group, trigger_field = trigger_chains[group_name]
        locator = pages_data.get(trigger_group, {}).get(trigger_field, '')
        if locator:
            return (mode, locator)

    # 兜底：从 group 名推断，在同源文件的 group 中搜索触发按钮
    # 定义：group 名模式 → (mode, 要搜索的 trigger field 列表)
    _TRIGGER_SEARCH = [
        (r'_drawer',         'action',  ['add_btn']),
        (r'_dialog',         'action',  ['add_btn', 'delete_btn']),
        (r'_delete_',        'action',  ['delete_btn']),
        (r'_filter_',        'action',  ['advanced_filter_btn']),
        (r'_detail_',        'observe', ['desc_link', 'first_order_link', 'first_project_link']),
        (r'_new_',           'observe', ['add_btn', 'product_outbound_btn']),
        (r'_dropdown_',      'action',  ['more_btn']),
        (r'_update_',        'action',  ['progress_update_btn']),
        (r'_pmo_update',     'action',  ['pmo_update_btn']),
    ]

    for pattern, mode, trigger_fields in _TRIGGER_SEARCH:
        if re.search(pattern, group_name):
            # 在同源文件的所有 group 中搜索 trigger field
            if source_files:
                src = source_files.get(group_name, '')
                if src:
                    # 找同源文件中的其他 group
                    for other_group, other_src in source_files.items():
                        if other_src == src and other_group != group_name:
                            for field in trigger_fields:
                                locator = pages_data.get(other_group, {}).get(field, '')
                                if locator:
                                    return (mode, locator)

            # 最后兜底：在所有 group 中搜索（不限制同源文件）
            for other_group, fields in pages_data.items():
                if other_group == group_name:
                    continue
                for field in trigger_fields:
                    locator = fields.get(field, '')
                    if locator:
                        return (mode, locator)
            break

    return None


# ===========================================================================
# 批次构建
# ===========================================================================
# Phase 4 待探测项消费
# ===========================================================================

def _load_pending_detail_links(probe_dir: str) -> list:
    """加载 Phase 4 (_case_generator.py) 输出的 detail-link 待探测项

    文件位置: _probe/pending_detail_links.json
    格式: [{group, field, label, type, case_id}, ...]
    """
    pending_file = os.path.join(probe_dir, 'pending_detail_links.json')
    if not os.path.isfile(pending_file):
        return []
    try:
        with open(pending_file, 'r', encoding='utf-8') as f:
            items = json.load(f)
        if isinstance(items, list):
            print(f"[INFO] 加载 Phase 4 detail-link 待探测项: {len(items)} 项 ({pending_file})")
            return items
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] 无法加载 pending_detail_links.json: {e}", file=sys.stderr)
    return []


def build_batches(uncovered_by_group: dict, config: dict,
                   trigger_chains: dict, pages_data: dict,
                   source_files: dict, harvest_cache: dict,
                   probe_dir: str, suffix: str = '') -> list:
    """为每个有未覆盖元素的 group 生成探测批次

    返回: [{group, module, level, url, mode, actions, elements, output}]
    """
    batches = []

    # ── 消费 Phase 4 (_case_generator.py) 的 detail-link 待探测项 ──
    # 确保这些字段即使不在 probe_db 中也会被探测（走 --element 知识库遍历）
    pending_links = _load_pending_detail_links(probe_dir)
    pending_labels = {}  # field -> label（从 Phase 4 传入的中文标签）
    for item in pending_links:
        group = item.get('group', '')
        field = item.get('field', '')
        if not group or not field:
            continue
        # 合并到 uncovered_by_group（field → None 表示无已知 XPath，走 --element 模式）
        if group not in uncovered_by_group:
            uncovered_by_group[group] = {}
        if field not in uncovered_by_group[group]:
            uncovered_by_group[group][field] = None
            pending_labels[field] = item.get('label', '')
            print(f"  [PENDING] detail-link: {group}.{field} (label={item.get('label', '')})")

    for group_name, fields in uncovered_by_group.items():
        if not fields:
            continue

        module = _module_from_group(group_name, source_files)
        source_file = source_files.get(group_name, '')
        level = classify_group(group_name, fields)
        url = resolve_url(group_name, source_file, config, harvest_cache)

        batch = {
            'group': group_name,
            'module': module,
            'level': level,
            'url': url,
            'mode': 'direct',
            'actions': [],
            'elements': [],
            'output': os.path.join(probe_dir, f'probe_supplement{suffix}_{group_name}.json' if suffix else f'probe_supplement_{group_name}.json'),
        }

        # 填充 elements（优先 --verify 格式，detail-link 强制走 --element 知识库遍历）
        for field, locator in fields.items():
            etype = _infer_type(field, locator or '')
            if etype == 'detail-link':
                # detail-link 强制走知识库 Pattern 12 遍历（变体1→2→3→4 按顺序）
                # 不用 --verify，因为 --verify 只数元素个数，不验证 Pattern 12 合规性
                # label 优先级: pending_labels > XPath 文本提取 > 字段名
                if field in pending_labels and pending_labels[field]:
                    label = pending_labels[field]
                elif locator:
                    label = _extract_label(locator)
                else:
                    label = field.replace('_', ' ')
                batch['elements'].append(('element', 'detail-link', label, field))
            elif locator and (locator.startswith('xpath=') or locator.startswith('//')):
                batch['elements'].append(('verify', field, locator))
            else:
                # 非 XPath → 降级为 label 搜索
                label = _extract_label(locator) if locator else field
                etype = _infer_type(field, locator or '')
                batch['elements'].append(('element', etype, label, field))

        # L2: 找触发链
        if level == 'L2':
            trigger = find_trigger(group_name, module, pages_data, trigger_chains, source_files)
            if trigger:
                mode, trigger_locator = trigger
                batch['mode'] = mode
                raw = trigger_locator
                if raw.startswith('xpath='):
                    raw = raw[6:]
                batch['actions'].append(f"click:xpath={raw}")
            else:
                batch['mode'] = 'direct'
                batch['note'] = 'L2 但无法确定触发器'

        batches.append(batch)

    return batches


def _parse_concat_text(concat_inner: str) -> str:
    """解析 concat() XPath 内部的字符串片段

    concat('O', "'", 'Brien') → O'Brien
    """
    parts = []
    for segment in re.findall(r"'([^']*)'|\"([^\"]*)\"", concat_inner):
        parts.append(segment[0] or segment[1])
    return ''.join(parts)


def _extract_label(locator: str) -> str:
    if not locator:
        return ''
    # 优先匹配普通 contains 格式
    m = re.search(r"contains\(\.?,?['\"]([^'\"]+)['\"]\)", locator)
    if m:
        return m.group(1)
    # R3 修复: 匹配 concat() 格式（H3 修复后的输出）
    m = re.search(r"concat\((.+?)\)", locator)
    if m:
        return _parse_concat_text(m.group(1))
    # 回退: contains(text(),...) 格式
    m = re.search(r"contains\(text\(\),['\"]([^'\"]+)['\"]\)", locator)
    if m:
        return m.group(1)
    return ''


def _infer_type(key: str, locator: str) -> str:
    key_lower = key.lower()
    for suffix, etype in TYPE_SUFFIXES.items():
        if key_lower.endswith(suffix):
            return etype
    if 'el-select' in locator:
        return 'el-select'
    if 'textarea' in locator:
        return 'textarea'
    if '@role=\'tab\'' in locator or '@role="tab"' in locator:
        return 'tab'
    if 'el-checkbox' in locator or 'checkbox' in locator:
        return 'checkbox'
    return 'button'


# ===========================================================================
# 批次执行
# ===========================================================================

def run_batch_probe(batch: dict, cookie: str, viewport: dict = None) -> Optional[dict]:
    """执行一批探测/验证"""
    if not os.path.exists(PROBE_SCRIPT):
        print(f"[ERROR] probe_element.py 不存在: {PROBE_SCRIPT}",
              file=sys.stderr)
        return None

    url = batch['url']
    if not url:
        print(f"[WARN] {batch['group']}: URL 为空，跳过", file=sys.stderr)
        return None

    cmd = [sys.executable, PROBE_SCRIPT, url]
    # M1 修复: cookie 通过环境变量传递，避免在进程列表中暴露
    env = os.environ.copy()
    if cookie:
        env['_PROBE_COOKIE'] = cookie
    if viewport and viewport.get('width') and viewport.get('height'):
        cmd.extend(['--viewport', f"{viewport['width']}x{viewport['height']}"])

    # actions
    for action in batch.get('actions', []):
        cmd.extend(['--action', action])

    # elements
    has_any = False
    for item in batch['elements']:
        if item[0] == 'verify':
            _, key, locator = item
            cmd.extend(['--verify', f"{key}={locator}"])
            has_any = True
        elif item[0] == 'element':
            _, etype, label, key = item
            cmd.extend(['--element', f"{etype}:{label}:{key}"])
            has_any = True

    if not has_any:
        return None

    # observe 模式：把最后一个 action 改为 --observe
    if batch['mode'] == 'observe' and batch['actions']:
        # 找到最后一个 --action 参数，改为 --observe
        new_cmd = []
        last_action_idx = -1
        for idx in range(len(cmd)):
            if cmd[idx] == '--action':
                last_action_idx = idx
        if last_action_idx >= 0:
            for idx, c in enumerate(cmd):
                if idx == last_action_idx:
                    new_cmd.append('--observe')
                else:
                    new_cmd.append(c)
            cmd = new_cmd

    cmd.extend(['--output', batch['output']])

    n_elements = len(batch['elements'])
    # 方案 C: 超时自适应 — 基础 60s + 每元素 15s，L2 批次额外 +30s
    timeout = 60 + n_elements * 15
    if batch.get('level') == 'L2':
        timeout += 30

    print(f"  [CMD] {' '.join(cmd[:6])}... ({n_elements} 个元素, "
          f"mode={batch['mode']}, level={batch['level']}, timeout={timeout}s)")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=timeout, env=env)
        if result.returncode != 0:
            stderr_short = result.stderr[:200] if result.stderr else ''
            print(f"  [WARN] 退出码 {result.returncode}: {stderr_short}",
                  file=sys.stderr)

        if result.stdout:
            for line in result.stdout.strip().split('\n')[-5:]:
                print(f"    {line}")

        if os.path.exists(batch['output']):
            with open(batch['output'], encoding='utf-8') as f:
                result_data = json.load(f)
            # Fix 2: 注入 group 信息到结果中，供回写函数定位 pages YAML 文件
            if result_data:
                result_data['group'] = batch['group']
                for el in result_data.get('elements', []):
                    el['group'] = batch['group']
            return result_data
    except subprocess.TimeoutExpired:
        print(f"  [WARN] 超时 ({timeout}s): {batch['group']}", file=sys.stderr)
    except Exception as e:
        print(f"  [ERROR] {e}", file=sys.stderr)

    return None


def merge_supplement_results(results: list, probe_dir: str, suffix: str = '') -> str:
    all_elements = []
    total = 0
    verified = 0

    for r in results:
        if not r:
            continue
        elements = r.get('elements', [])
        all_elements.extend(elements)
        total += len(elements)
        verified += sum(1 for el in elements if el.get('verified'))

    output_path = os.path.join(probe_dir, f'probe_supplement{suffix}.json')
    supplement = {
        'url': results[0].get('url', '') if results else '',
        'actions': [],
        'elements': all_elements,
        'summary': {
            'total': total,
            'verified': verified,
            'failed': total - verified,
        },
        'supplemented_by': 'probe_from_pages.py v2',
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(supplement, f, ensure_ascii=False, indent=2)

    return output_path


def update_pages_yaml_with_supplement(results: list, source_files: dict,
                                       pages_data: dict, pages_dir: str) -> int:
    """Fix 2 + Gap 2 + Gap 3: 将补探成功的 locator 回写到 pages YAML

    处理逻辑：
    1. 遍历所有补探结果中 verified=true 的元素
    2. 定位对应的 pages YAML 文件（多级兜底策略）
    3. 行级精准替换旧 locator → 新 locator
    4. 清除 _meta 段中该字段的 unverified 标记
    5. 如果 _meta 段变为空，整个移除
    6. 同步更新 pages_data 内存对象（Gap 7）

    Args:
        results: 补探结果列表（每个 result 含 elements 数组）
        source_files: {group_name: filepath} 映射
        pages_data: {group_name: {field: locator}} 内存数据
        pages_dir: pages 目录路径（兜底搜索用）

    Returns:
        更新的字段数量
    """
    updated_count = 0
    # 按文件聚合变更: {filepath: [(old_locator, new_locator, field_key), ...]}
    file_changes = {}

    for result in results:
        if not result:
            continue
        batch_group = result.get('group', '')

        for el in result.get('elements', []):
            if not el.get('verified', False):
                continue

            key = el.get('key', '')
            new_locator = el.get('locator', '')
            el_group = el.get('group', batch_group)

            if not key or not new_locator:
                continue

            # Gap 3: 多级兜底策略定位 pages YAML 文件
            target_file = None
            old_locator = None
            target_group = None

            # 策略 1: 精确匹配 — source_files[el_group] 且该文件包含 key
            if el_group and el_group in source_files:
                candidate = source_files[el_group]
                if el_group in pages_data and key in pages_data[el_group]:
                    target_file = candidate
                    old_locator = pages_data[el_group][key]
                    target_group = el_group

            # 策略 2: 遍历所有 pages_data 找包含 key 的 group
            if not target_file:
                for grp, fields in pages_data.items():
                    if key in fields:
                        target_file = source_files.get(grp, '')
                        old_locator = fields[key]
                        target_group = grp
                        break

            # 策略 3: 扫描所有 pages YAML 文件查找 key
            if not target_file and os.path.isdir(pages_dir):
                for root, _, files in os.walk(pages_dir):
                    for fname in files:
                        if not fname.endswith('.yaml'):
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, encoding='utf-8') as fh:
                                fdata = yaml.safe_load(fh)
                            if fdata and isinstance(fdata, dict):
                                for grp, fields in fdata.items():
                                    if isinstance(fields, dict) and key in fields:
                                        target_file = fpath
                                        old_locator = fields[key]
                                        target_group = grp
                                        break
                        except Exception:
                            continue
                    if target_file:
                        break

            if not target_file or not os.path.exists(target_file):
                continue

            # 跳过 locator 相同的情况（无需更新）
            if old_locator == new_locator:
                continue

            file_changes.setdefault(target_file, []).append(
                (old_locator, new_locator, key, target_group or el_group))

    # 执行文件级回写
    for filepath, changes in file_changes.items():
        try:
            with open(filepath, encoding='utf-8') as f:
                lines = f.readlines()

            # 收集需要清除 _meta 的字段
            meta_clear_keys = set()

            for old_loc, new_loc, field_key, group_name in changes:
                replaced = False
                current_group = None  # M2: 追踪当前 YAML group 边界
                for i, line in enumerate(lines):
                    # M2: 检测 group 边界（顶层 key，无缩进）
                    stripped_line = line.rstrip()
                    if (stripped_line
                            and not line[0].isspace()
                            and not stripped_line.startswith('#')
                            and not stripped_line.startswith('---')
                            and stripped_line.endswith(':')):
                        current_group = stripped_line[:-1].strip()
                    if ':' not in line:
                        continue
                    # 精准匹配: 行必须包含 field_key 且值部分包含 old_loc
                    key_part, sep, val_part = line.partition(':')
                    if key_part.strip() != field_key:
                        continue
                    # M2: 校验 group 匹配（防止多 group 同名字段歧义）
                    if current_group and group_name and current_group != group_name:
                        continue
                    if old_loc and old_loc in val_part:
                        lines[i] = line.replace(old_loc, new_loc, 1)
                        replaced = True
                        # R2-M5: 回写后处理 — R4.32 安全网 + 隐藏过滤补齐
                        actual_loc = new_loc
                        if field_key.endswith('_select') and isinstance(actual_loc, str):
                            from _pages_writer import fix_el_select_div_to_input as _fix_el_select_div_to_input
                            fixed = _fix_el_select_div_to_input(actual_loc)
                            if fixed != actual_loc:
                                lines[i] = lines[i].replace(actual_loc, fixed, 1)
                                actual_loc = fixed
                        if (isinstance(actual_loc, str)
                                and actual_loc.startswith('xpath=')
                                and not _has_hidden_filter(actual_loc)):
                            filtered_loc = add_hidden_filter(actual_loc)
                            if filtered_loc != actual_loc:
                                lines[i] = lines[i].replace(actual_loc, filtered_loc, 1)
                        # 同时清除注释中的 [UNVERIFIED] 标记，保留中文标签
                        if '[UNVERIFIED]' in lines[i]:
                            # 只移除 [UNVERIFIED] 标记，保留其余注释内容
                            lines[i] = re.sub(r'\s*\[UNVERIFIED\]\s*', ' ', lines[i]).rstrip() + '\n'
                            # 清除后检查注释是否还有意义（至少2个连续中文字符）
                            after_hash = lines[i].split('#', 1)
                            if len(after_hash) > 1:
                                comment_text = after_hash[1].strip()
                                # 如果没有有效中文标签，移除整个注释
                                if not re.search(r'[一-鿿]{2,}', comment_text):
                                    lines[i] = after_hash[0].rstrip() + '\n'
                        meta_clear_keys.add(field_key)
                        # P2: 后处理完成后统一转义整行值
                        _key_part, _sep, _val_part = lines[i].partition(':')
                        _hash_idx = _val_part.find('#')
                        if _hash_idx >= 0:
                            _raw_val = _val_part[:_hash_idx].strip().strip("'\"")
                            _line_comment = '  ' + _val_part[_hash_idx:].rstrip()
                        else:
                            _raw_val = _val_part.strip().strip("'\"")
                            _line_comment = ''
                        lines[i] = f"{_key_part}: {escape_yaml_scalar(_raw_val)}{_line_comment}\n"
                        break
                    elif not old_loc and field_key in key_part:
                        # old_loc 为空但 key 匹配 → 替换整行值
                        # R2-M5: 回退路径也需要后处理
                        actual_loc = new_loc
                        if field_key.endswith('_select') and isinstance(actual_loc, str):
                            from _pages_writer import fix_el_select_div_to_input as _fix_el_select_div_to_input
                            fixed = _fix_el_select_div_to_input(actual_loc)
                            if fixed != actual_loc:
                                actual_loc = fixed
                        if (isinstance(actual_loc, str)
                                and actual_loc.startswith('xpath=')
                                and not _has_hidden_filter(actual_loc)):
                            actual_loc = add_hidden_filter(actual_loc)
                        new_line = f"  {field_key}: {escape_yaml_scalar(actual_loc)}\n"
                        lines[i] = new_line
                        replaced = True
                        meta_clear_keys.add(field_key)
                        break

                if not replaced:
                    # 策略 3b: 按 key 名匹配行（old_loc 可能已被其他操作修改）
                    current_group = None  # M2: 重置 group 追踪
                    for i, line in enumerate(lines):
                        # M2: 检测 group 边界
                        stripped_line = line.rstrip()
                        if (stripped_line
                                and not line[0].isspace()
                                and not stripped_line.startswith('#')
                                and not stripped_line.startswith('---')
                                and stripped_line.endswith(':')):
                            current_group = stripped_line[:-1].strip()
                        stripped = line.strip()
                        if stripped.startswith(f"{field_key}:"):
                            # M2: 校验 group 匹配
                            if current_group and group_name and current_group != group_name:
                                continue
                            # 提取原行注释（保留中文标签，移除 [UNVERIFIED]）
                            old_comment = ''
                            if '#' in line:
                                comment_part = line.split('#', 1)[1].strip()
                                # 清除 [UNVERIFIED] 标记
                                comment_part = re.sub(r'\s*\[UNVERIFIED\]\s*', ' ', comment_part).strip()
                                # 检查注释是否还有有效中文标签
                                if re.search(r'[一-鿿]{2,}', comment_part):
                                    old_comment = f'  # {comment_part}'
                            # R2-M5: 策略 3b 也需要后处理
                            actual_loc = new_loc
                            if field_key.endswith('_select') and isinstance(actual_loc, str):
                                from _pages_writer import fix_el_select_div_to_input as _fix_el_select_div_to_input
                                fixed = _fix_el_select_div_to_input(actual_loc)
                                if fixed != actual_loc:
                                    actual_loc = fixed
                            if (isinstance(actual_loc, str)
                                    and actual_loc.startswith('xpath=')
                                    and not _has_hidden_filter(actual_loc)):
                                actual_loc = add_hidden_filter(actual_loc)
                            # 替换整行（保留注释）
                            indent = line[:len(line) - len(line.lstrip())]
                            lines[i] = f"{indent}{field_key}: {escape_yaml_scalar(actual_loc)}{old_comment}\n"
                            meta_clear_keys.add(field_key)
                            break

            # Gap 2: 清除 _meta 段中已修复字段的 unverified 标记
            if meta_clear_keys:
                _clear_meta_keys(lines, meta_clear_keys)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            updated_count += len(changes)
            print(f"  [WRITEBACK] {os.path.basename(filepath)}: "
                  f"更新 {len(changes)} 个 locator")

        except Exception as e:
            print(f"  [ERROR] 回写 {filepath} 失败: {e}", file=sys.stderr)

    # Gap 7: 同步更新 pages_data 内存对象
    for filepath, changes in file_changes.items():
        for _, new_loc, field_key, group_name in changes:
            if group_name in pages_data:
                pages_data[group_name][field_key] = new_loc

    return updated_count


def _clear_meta_keys(lines: list, keys_to_clear: set):
    """从 YAML 文件中清除 _meta 段中指定字段的 unverified 标记

    行级操作：找到所有 _meta: 段，移除指定字段的小节。
    如果 _meta 段变为空，移除整个 _meta 段。

    支持多 group 文件：会扫描并处理文件中所有的 _meta: 段。
    """
    meta_sections = []  # [(meta_start, meta_end, meta_indent), ...]
    ranges_to_remove = []  # [(start_line, end_line), ...]

    # 扫描所有 _meta 段
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # 检测 _meta: 段开始
        if stripped.endswith('_meta:') or stripped.strip() == '_meta:':
            meta_start = i
            meta_indent = len(line) - len(line.lstrip())
            meta_end = i
            current_meta_key = None
            current_meta_key_start = -1

            i += 1
            # 扫描 _meta 段内容
            while i < len(lines):
                line = lines[i]
                stripped = line.rstrip()

                if not stripped:
                    # 空行 → 当前 _meta 段结束
                    # 保存最后一个 key 的范围
                    if current_meta_key and current_meta_key in keys_to_clear:
                        ranges_to_remove.append((current_meta_key_start, i - 1))
                    break

                line_indent = len(line) - len(line.lstrip())
                if line_indent <= meta_indent:
                    # 缩进回到 _meta 同级或更少 → _meta 段结束
                    if current_meta_key and current_meta_key in keys_to_clear:
                        ranges_to_remove.append((current_meta_key_start, i - 1))
                    break

                # 检测 meta 下的字段名（_meta 的直接子级）
                expected_child_indent = meta_indent + 2
                if line_indent == expected_child_indent and ':' in stripped:
                    # 保存上一个 meta key 的范围
                    if current_meta_key and current_meta_key in keys_to_clear:
                        ranges_to_remove.append((current_meta_key_start, i - 1))

                    field_name = stripped.split(':')[0].strip()
                    current_meta_key = field_name
                    current_meta_key_start = i
                elif line_indent > expected_child_indent:
                    # meta key 的子属性行，跳过
                    i += 1
                    continue
                else:
                    # 其他情况结束
                    if current_meta_key and current_meta_key in keys_to_clear:
                        ranges_to_remove.append((current_meta_key_start, i - 1))
                    break

                i += 1

            # 处理内层 while 循环因 EOF 退出的情况（未触发 break）
            if i >= len(lines) and current_meta_key and current_meta_key in keys_to_clear:
                ranges_to_remove.append((current_meta_key_start, len(lines) - 1))

            meta_end = i
            meta_sections.append((meta_start, meta_end, meta_indent))

        i += 1

    # 从后往前删除行（避免索引偏移）
    for start, end in sorted(ranges_to_remove, reverse=True):
        # 确保 end 不超过文件末尾
        actual_end = min(end, len(lines) - 1)
        # 找到实际结束行（跳过属于该 key 的行）
        while actual_end > start and actual_end < len(lines):
            line = lines[actual_end]
            stripped = line.strip()
            if not stripped:
                break
            # 检查是否还是子属性行
            line_indent = len(line) - len(line.lstrip())
            key_indent = len(lines[start]) - len(lines[start].lstrip())
            if line_indent > key_indent or actual_end == start:
                actual_end += 1
            else:
                break
        del lines[start:actual_end]

    # 检查所有 _meta 段是否还有内容，如果空了则移除
    # 重新扫描（因为删除行后位置已变化）
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if stripped.endswith('_meta:') or stripped.strip() == '_meta:':
            meta_indent_level = len(line) - len(line.lstrip())
            # 检查下一行是否还是 _meta 的子级
            has_children = False
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.strip() and not next_line.strip().startswith('#'):
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent > meta_indent_level:
                        has_children = True
            if not has_children:
                del lines[i]
                continue  # 不增加 i，因为删除后下一行移到了当前位置
        i += 1


def diagnose_unverified_containers(results: list) -> list:
    """对 count=0 且有容器前缀的元素，诊断可能的容器类型错误（R4.38）

    当元素验证失败（count=0）且 locator 有 el-drawer 或 el-dialog 前缀时，
    提示可能是容器类型错误。这类错误在运行时表现为 Timeout 超时。
    """
    warnings = []
    for r in results:
        if not r:
            continue
        group = r.get('group', r.get('url', ''))
        for el in r.get('elements', []):
            if el.get('verified'):
                continue
            if el.get('count', -1) != 0:
                continue
            locator = el.get('locator', '')
            key = el.get('key', '?')

            if 'el-drawer' in locator:
                alt = 'el-dialog'
                current = 'el-drawer'
            elif 'el-dialog' in locator:
                alt = 'el-drawer'
                current = 'el-dialog'
            elif 'el-message-box' in locator:  # R7-3 修复: 新增 message-box
                alt = 'el-dialog'
                current = 'el-message-box'
            else:
                continue

            warnings.append(
                f"  [R4.38] {group}.{key}: 当前前缀 {current}，"
                f"但探测未找到元素。可能原因：\n"
                f"    1. 容器未打开（需要多步交互才能到达）\n"
                f"    2. 容器类型应为 {alt}（R4.38 容器判定规则）"
            )
    return warnings


# ===========================================================================
# 主入口
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description='从 pages/cases YAML 反向补全探测覆盖（Phase 6）v2')
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--cookie', help='覆盖 config.yaml 中的 cookie')
    parser.add_argument('--url', help='覆盖 config.yaml 中的 target_url')
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告未覆盖，不执行探测')
    parser.add_argument('--skip-hidden-filter', action='store_true',
                        help='跳过 R4.11 隐藏过滤自动补齐')
    parser.add_argument('--output-suffix', default='',
                        help='输出文件后缀（如 "_fallback" → probe_supplement_fallback.json）')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[ERROR] 项目目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    print(f"{'='*60}")
    print(f"Phase 6: 探测覆盖补全 v2（按 group 批次）")
    print(f"项目: {project_dir}")
    print(f"{'='*60}")

    # Step 1: 加载配置
    config = load_config(project_dir)
    if args.cookie:
        config['cookie'] = args.cookie
    if args.url:
        config['target_url'] = args.url
    config['_project_dir'] = project_dir

    cookie = config.get('cookie', '')
    viewport = config.get('viewport', {})
    print(f"\n[Step 1] 配置加载")
    print(f"  target_url: {config.get('target_url', '(空)')}")
    print(f"  cookie: {'已配置' if cookie else '(空)'}")
    page_urls = config.get('page_urls', {})
    if page_urls:
        print(f"  page_urls: {len(page_urls)} 个路由")

    # Step 2: 扫描 pages YAML
    pages_dir = os.path.join(project_dir, 'pages')
    pages_data, source_files = scan_pages_yaml(pages_dir)
    total_fields = sum(len(v) for v in pages_data.values())
    print(f"\n[Step 2] pages YAML 扫描")
    print(f"  找到 {len(pages_data)} 个 group，共 {total_fields} 个定位器")

    # Step 3: 扫描 cases YAML + data YAML
    cases_dir = os.path.join(project_dir, 'cases')
    suites_dir = os.path.join(project_dir, 'suites')
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    data_dir = os.path.join(project_dir, 'data')
    variable_refs, hardcoded_locators = scan_cases_yaml(
        cases_dir, suites_dir, knowledge_dir, pages_data, data_dir=data_dir)
    print(f"\n[Step 3] cases/suites/knowledge/data 扫描")
    print(f"  变量引用: {len(variable_refs)} 个")
    print(f"  硬编码 locator: {len(hardcoded_locators)} 个")

    # Step 3b: 触发链扫描
    trigger_chains = scan_trigger_chains(cases_dir, pages_data)
    print(f"  触发链: {len(trigger_chains)} 个 group 映射")
    for g, (mode, tg, tf) in list(trigger_chains.items())[:5]:
        print(f"    {g} ← {tg}.{tf} ({mode})")

    # Step 4: 隐藏过滤补齐
    if not args.skip_hidden_filter:
        modified = apply_hidden_filters(pages_dir, pages_data, source_files)
        print(f"\n[Step 4] R4.11 隐藏过滤补齐")
        print(f"  补齐 {modified} 个定位器的隐藏过滤属性")
        # R3.14：清除 not(ancestor::...) 负向排除（替代原跨 group 排除注入）
        stripped = strip_not_ancestor_exclusions(pages_dir, pages_data, source_files)
        if stripped > 0:
            print(f"  R3.14: 清除 {stripped} 个定位器的 not(ancestor) 负向排除")
        if modified > 0 or stripped > 0:
            print(f"  已回写 pages YAML")
    else:
        print(f"\n[Step 4] R4.11 隐藏过滤补齐 (跳过)")

    # Step 5: 加载 probe DB + harvest 缓存
    probe_dir = os.path.join(project_dir, '_probe')
    probe_db = load_probe_db(probe_dir)
    harvest_cache = load_harvest_cache(probe_dir)
    print(f"\n[Step 5] probe DB + harvest 缓存加载")
    print(f"  已加载 {len(probe_db)} 个探测记录")
    print(f"  harvest 缓存: {len(harvest_cache)} 个模块")

    # Step 5b: D4/P-20 Harvest→Pages 交叉检查
    if harvest_cache:
        harvest_warnings = cross_check_harvest_vs_pages(
            pages_data, harvest_cache, source_files)
        if harvest_warnings:
            print(f"\n[Step 5b] Harvest→Pages 交叉检查: {len(harvest_warnings)} 个警告")
            for msg, suggestion in harvest_warnings:
                print(f"  [WARN] {msg}")
                print(f"         → {suggestion}")
        else:
            print(f"\n[Step 5b] Harvest→Pages 交叉检查: 无异常")

    # Step 6: 覆盖检查（按 group 分组）
    uncovered_by_group = find_uncovered_by_group(
        variable_refs, hardcoded_locators, probe_db, pages_data)
    total_uncovered = sum(len(v) for v in uncovered_by_group.values())
    print(f"\n[Step 6] 覆盖检查")
    print(f"  未覆盖: {total_uncovered} 个元素，分布在 {len(uncovered_by_group)} 个 group")

    if uncovered_by_group:
        print(f"\n  未覆盖元素清单:")
        for group_name, fields in uncovered_by_group.items():
            level = classify_group(group_name, fields)
            print(f"    [{level}] {group_name} ({len(fields)} 个):")
            for field in list(fields.keys())[:5]:
                print(f"      - {field}")
            if len(fields) > 5:
                print(f"      ... 及其他 {len(fields) - 5} 个")

    if not uncovered_by_group:
        print(f"\n{'='*60}")
        print(f"[PASS] 所有定位器已覆盖，无需补探")
        print(f"{'='*60}")
        sys.exit(0)

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"[DRY-RUN] 发现 {total_uncovered} 个未覆盖元素")
        print(f"去掉 --dry-run 参数可自动补探")
        print(f"{'='*60}")
        sys.exit(1)

    # Step 7: 构建批次
    if not config.get('target_url'):
        print(f"\n[ERROR] 无法补探: target_url 未配置", file=sys.stderr)
        sys.exit(1)

    batches = build_batches(uncovered_by_group, config, trigger_chains,
                            pages_data, source_files, harvest_cache,
                            probe_dir, suffix=args.output_suffix)
    print(f"\n[Step 7] 构建探测批次")
    print(f"  共 {len(batches)} 个批次:")
    for b in batches:
        note = b.get('note', '')
        trigger_info = f"trigger={b['actions'][0][:50]}" if b['actions'] else "no-trigger"
        print(f"    [{b['level']}] {b['group']}: {len(b['elements'])} 个元素, "
              f"mode={b['mode']}, {trigger_info}"
              + (f" ({note})" if note else ""))

    # Step 8: 逐批执行
    print(f"\n[Step 8] 逐批执行探测")
    results = []
    for batch in batches:
        print(f"\n  批次: {batch['group']} ({len(batch['elements'])} 个)")
        result = run_batch_probe(batch, cookie, viewport)
        if result:
            results.append(result)
            verified = result.get('summary', {}).get('verified', 0)
            total = result.get('summary', {}).get('total', 0)
            print(f"  结果: {verified}/{total} 验证通过")
        else:
            print(f"  结果: 执行失败或无输出")

    # Step 9: 容器前缀诊断（R4.38）
    if results:
        container_warnings = diagnose_unverified_containers(results)
        if container_warnings:
            print(f"\n[Step 9] 容器前缀诊断 (R4.38)")
            print(f"  发现 {len(container_warnings)} 个可能的容器类型问题：")
            for w in container_warnings:
                print(w)

    # Step 10: 合并结果
    if results:
        supplement_path = merge_supplement_results(results, probe_dir, suffix=args.output_suffix)
        print(f"\n[Step 10] 结果写入")
        print(f"  {supplement_path}")

        # Step 11: 回写成功的补探 locator 到 pages YAML（Fix 2）
        writeback_count = update_pages_yaml_with_supplement(
            results, source_files, pages_data, pages_dir)
        print(f"\n[Step 11] 回写 pages YAML")
        if writeback_count > 0:
            print(f"  已更新 {writeback_count} 个 locator（含清除 _meta.unverified 标记）")
        else:
            print(f"  无需回写（无新增 verified 元素或 locator 未变化）")

        # 重新检查覆盖率（Gap 7: pages_data 已在 Step 11 中更新）
        new_probe_db = load_probe_db(probe_dir)
        still_uncovered = find_uncovered_by_group(
            variable_refs, hardcoded_locators, new_probe_db, pages_data)
        still_total = sum(len(v) for v in still_uncovered.values())
        print(f"\n{'='*60}")
        if still_uncovered:
            print(f"[WARN] 补探后仍有 {still_total} 个未覆盖")
            for group_name, fields in still_uncovered.items():
                for field in list(fields.keys())[:3]:
                    print(f"  - {group_name}.{field}")
                if len(fields) > 3:
                    print(f"  ... 及其他 {len(fields) - 3} 个")
            sys.exit(1)
        else:
            print(f"[PASS] 所有定位器已覆盖")
            sys.exit(0)
    else:
        print(f"\n[WARN] 所有批次执行失败，未生成补充结果")
        sys.exit(1)


if __name__ == '__main__':
    main()
