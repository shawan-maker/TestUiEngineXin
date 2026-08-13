#!/usr/bin/env python3
"""
Phase 4: 元素探测验证器 (validate_04_probe.py)

校验内容：
  R3.1 定位器全部来自知识库
  R3.3 隐藏过滤自动处理（XPath 必须包含 is-hidden + display:none 过滤）
  R3.4 多步操作完整性（el-select 三步、级联多级、日期选择）
  R3.10 全量探测覆盖率 — case 中每个 locator（含 L3 内部）必须有 probe 记录

用法:
    python validate_04_probe.py <project_dir>

退出码: 0 = 全部通过, 1 = 有 error 级别违规
"""

import argparse
import glob
import json
import os
import re
import sys
from typing import List, Tuple, Dict, Optional

try:
    import yaml
except ImportError:
    print("[FATAL] 需要 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ============================================================================
# XPath 隐藏过滤正则 (R3.3)
# ============================================================================

# Element UI: is-hidden
# Ant Design: *-hidden (ant-modal-hidden, ant-drawer-hidden, ant-select-item-option-hidden)
HIDDEN_FILTER_CLASS = re.compile(
    r"contains\(@class,['\"]"
    r"(?:is-hidden|[\w-]*hidden)"  # is-hidden 或 *-hidden
    r"['\"]\)"
)
HIDDEN_FILTER_STYLE = re.compile(r"contains\(@style,['\"]display: none['\"]\)")

# 不需要隐藏过滤的定位器（通用存在性断言：//*[contains(.,'...')]）
NO_FILTER_NEEDED = re.compile(r'//\*\[contains\(\.,[\'"]')


# ============================================================================
# 工具函数
# ============================================================================

def check_hidden_filter(xpath: str) -> Tuple[bool, str]:
    """检查 XPath 的最终元素是否包含隐藏过滤

    规则：所有元素表达式的最后一个标签中必须加上属性：
    not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])

    例外：//*[contains(.,'xx')] 这类通用断言定位器不需要
    """
    xpath = xpath.replace('xpath=', '').strip()

    if NO_FILTER_NEEDED.search(xpath):
        return True, "通用断言定位器，不需要隐藏过滤"

    has_class_filter = bool(HIDDEN_FILTER_CLASS.search(xpath))
    has_style_filter = bool(HIDDEN_FILTER_STYLE.search(xpath))

    if has_class_filter and has_style_filter:
        return True, "OK"
    elif has_class_filter:
        return False, "缺少 display:none 过滤"
    elif has_style_filter:
        return False, "缺少 is-hidden 过滤"
    else:
        return False, "缺少隐藏过滤（is-hidden 和 display:none）"


def _has_keyword_recursive(steps: list, keyword: str) -> bool:
    """递归搜索步骤树（含 then_steps/else_steps）中是否存在指定 keyword"""
    if not steps:
        return False
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get('keyword') == keyword:
            return True
        # 递归搜索嵌套的条件分支
        params = s.get('params', {})
        if isinstance(params, dict):
            for sub_key in ('then_steps', 'else_steps'):
                sub_steps = params.get(sub_key, [])
                if _has_keyword_recursive(sub_steps, keyword):
                    return True
    return False


def check_el_select_three_steps(steps: list, step_index: int) -> List[str]:
    """检查 el-select 三步法是否完整（支持条件分支模式）"""
    issues = []

    # 检查条件分支模式：下一步是 if_element_visible + _editable
    if step_index + 1 < len(steps):
        next_step = steps[step_index + 1]
        if isinstance(next_step, dict) and next_step.get('keyword') == 'if_element_visible':
            if_params = next_step.get('params', {})
            if_loc = str(if_params.get('locator', ''))
            if '_editable' in if_loc:
                then_steps = if_params.get('then_steps', []) or []
                else_steps = if_params.get('else_steps', []) or []
                has_fill = _has_keyword_recursive(then_steps, 'fill_value')
                has_select = _has_keyword_recursive(then_steps, 'click_element')
                has_first = _has_keyword_recursive(else_steps, 'click_element')
                if not has_fill:
                    issues.append("条件分支 then_steps 缺少 fill_value 搜索步骤")
                if not has_select:
                    issues.append("条件分支 then_steps 缺少选择选项步骤")
                if not has_first:
                    issues.append("条件分支 else_steps 缺少选择第一项步骤")
                return issues  # 条件分支已验证

    # 旧三步法模式
    has_fill = False
    has_select = False

    for i in range(step_index + 1, min(step_index + 5, len(steps))):
        step = steps[i]
        if not isinstance(step, dict):
            continue
        keyword = step.get('keyword', '')
        desc = (step.get('desc', '') or '').lower()

        if keyword == 'fill_value':
            has_fill = True
        if keyword == 'click_element' and any(w in desc for w in ['选项', 'option', 'select']):
            has_select = True

    if not has_fill:
        issues.append("缺少 fill_value 搜索步骤")
    if not has_select:
        issues.append("缺少选择选项步骤")

    return issues


def check_cascader_steps(steps: list, step_index: int) -> List[str]:
    """检查级联选择器步骤是否完整"""
    issues = []
    has_select_level = False

    for i in range(step_index + 1, min(step_index + 6, len(steps))):
        step = steps[i]
        if not isinstance(step, dict):
            continue
        desc = (step.get('desc', '') or '').lower()
        if any(w in desc for w in ['勾选', '展开', '选择', '级联']):
            has_select_level = True

    if not has_select_level:
        issues.append("缺少级联选择步骤")

    return issues


def check_date_picker_steps(steps: list, step_index: int) -> List[str]:
    """检查日期选择器步骤是否完整"""
    issues = []
    has_select_date = False

    for i in range(step_index + 1, min(step_index + 4, len(steps))):
        step = steps[i]
        if not isinstance(step, dict):
            continue
        desc = (step.get('desc', '') or '').lower()
        if any(w in desc for w in ['今天', '此刻', '当月', '日期', 'date', 'time']):
            has_select_date = True

    if not has_select_date:
        issues.append("缺少选择日期/时间步骤")

    return issues


def load_probe_results(probe_dir: str) -> Dict[str, dict]:
    """加载所有 probe 结果（v1.1: 支持三种数据源）"""
    probe_db = {}
    if not os.path.isdir(probe_dir):
        return probe_db

    # 1. 旧格式 probe_*.json（向后兼容，优先级排序）
    all_files = glob.glob(os.path.join(probe_dir, "**/*.json"), recursive=True)

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
        elif basename.startswith('probe_'):
            other_files.append(fp)

    ordered_files = sorted(initial_files) + sorted(other_files) + sorted(supplement_files)

    for f in ordered_files:
        is_supplement = os.path.basename(f).startswith('probe_supplement')
        try:
            with open(f, encoding='utf-8') as fh:
                data = json.load(fh)
            elements = data if isinstance(data, list) else data.get('elements', [])
            for el in elements:
                key = el.get('key', '')
                if key:
                    # M4/N4: 冲突检测 — supplement 覆盖 verified=true 为 verified=false
                    if is_supplement and key in probe_db:
                        prev_verified = probe_db[key].get('verified', False)
                        curr_verified = el.get('verified', False)
                        if prev_verified and not curr_verified:
                            print(f"  [WARN] N4: {key}: supplement 覆盖 verified=true → false")
                    probe_db[key] = el
        except Exception:
            pass

    # 2. discovery_*.json（Phase 4 广撒网，v1.1 新增）
    for dj in glob.glob(os.path.join(probe_dir, 'discovery_*.json')):
        try:
            with open(dj, encoding='utf-8') as fh:
                data = json.load(fh)
            elements = _extract_discovery_elements(data)
            for elem in elements:
                key = elem.get('field_key', '') or elem.get('key', '')
                if key:
                    probe_db[key] = elem
        except Exception:
            continue

    # 3. verify_result.json（Phase 6 回写结果，v1.1 新增）
    vr_path = os.path.join(probe_dir, 'verify_result.json')
    if os.path.isfile(vr_path):
        try:
            with open(vr_path, encoding='utf-8') as fh:
                data = json.load(fh)
            for entry in data.get('verified', []):
                key = entry.get('field', '')
                if key:
                    probe_db[key] = {
                        'key': key,
                        'locator': entry.get('locator', ''),
                        'verified': True,
                        'source': 'from_browser'
                    }
        except Exception:
            pass

    return probe_db


def _extract_discovery_elements(data: dict) -> list:
    """从 discovery JSON 提取所有元素（v1.1: 支持三种格式）"""
    elements = []

    # 检测格式并只处理一种
    if 'pages' in data:
        # Format 1: V7 multi-page {pages: [{list_page: {...}, containers: [...]}]}
        for page in data.get('pages', []):
            lp = page.get('list_page', {})
            for section in ('buttons', 'inputs', 'row_buttons', 'tabs', 'detail_links', 'checkboxes', 'menu_items'):
                elements.extend(lp.get(section, []))
            for container in page.get('containers', []):
                elements.extend(container.get('elements', []))
    elif 'list_page' in data:
        # Format 2: Single-page {list_page: {...}, containers: [...]}
        lp = data.get('list_page', {})
        for section in ('buttons', 'inputs', 'row_buttons', 'tabs', 'detail_links', 'checkboxes', 'menu_items'):
            elements.extend(lp.get(section, []))
        for container in data.get('containers', []):
            elements.extend(container.get('elements', []))
    else:
        # Format 3: Old format {containers: [{elements: [...]}]}
        for container in data.get('containers', []):
            if 'elements' in container:
                elements.extend(container['elements'])

    return elements


def _load_pending_fields(pages_dir: str) -> set:
    """预扫描 pages YAML 找出所有 [待确认] 定位器（v1.1 F1 修复）"""
    pending = set()
    PENDING_LOCATOR = 'xpath=[待确认]'

    for f in glob.glob(os.path.join(pages_dir, '**/*.yaml'), recursive=True):
        try:
            with open(f, encoding='utf-8') as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                continue
            for group, fields in data.items():
                if not isinstance(fields, dict):
                    continue
                for field, locator in fields.items():
                    if isinstance(locator, str) and PENDING_LOCATOR in locator:
                        pending.add(f"{group}.{field}")
                        pending.add(field)  # bare name for var_name matching
        except Exception:
            continue

    return pending


def load_pages_fields(pages_dir: str) -> Dict[str, set]:
    """扫描 pages/**/*.yaml（含 _fallback.yaml），返回 {group: set(field_name)}"""
    result = {}
    if not os.path.isdir(pages_dir):
        return result

    for root, _, files in os.walk(pages_dir):
        for f in sorted(files):
            if not f.endswith('.yaml'):
                continue
            filepath = os.path.join(root, f)
            try:
                with open(filepath, encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
            except Exception:
                continue
            if not data or not isinstance(data, dict):
                continue
            for group_name, fields in data.items():
                # BUG-1 审计 1a: 排除 page_urls 元数据（不作为 group 处理）
                if group_name == 'page_urls':
                    continue
                if not isinstance(fields, dict):
                    continue
                if group_name not in result:
                    result[group_name] = set()
                for field_name in fields:
                    if field_name != '_meta':
                        result[group_name].add(field_name)
    return result


# ============================================================================
# R3.3 隐藏过滤检查
# ============================================================================

def check_r3_3_hidden_filter(pages_dir: str, project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R3.3: 检查 pages/ 中 XPath 是否包含隐藏过滤"""
    errors = []
    warnings = []
    info = []

    xpath_count = 0
    filter_fail_count = 0

    if not os.path.isdir(pages_dir):
        return errors, warnings, info

    for f in sorted(glob.glob(os.path.join(pages_dir, "**/*.yaml"), recursive=True)):
        try:
            with open(f, encoding='utf-8') as fh:
                pages = yaml.safe_load(fh)
        except Exception:
            continue

        if not pages or not isinstance(pages, dict):
            continue

        for group, locators in pages.items():
            if not isinstance(locators, dict):
                continue
            for name, xpath in locators.items():
                if isinstance(xpath, str) and ('xpath=' in xpath or xpath.startswith('//')):
                    xpath_count += 1
                    ok, msg = check_hidden_filter(xpath)
                    if not ok:
                        filter_fail_count += 1
                        rel = os.path.relpath(f, project_dir)
                        warnings.append(f"[R3.3] {rel}#{group}.{name}: {msg}")

    if xpath_count > 0:
        info.append(f"[R3.3] 隐藏过滤检查: {xpath_count - filter_fail_count}/{xpath_count} 通过")
    else:
        info.append("[R3.3] 未发现 XPath 定位器")

    return errors, warnings, info


# ============================================================================
# R3.4 多步操作完整性
# ============================================================================

def check_r3_4_multi_step(cases_dir: str, project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R3.4: 检查多步操作完整性（el-select/级联/日期选择器）"""
    errors = []
    warnings = []
    info = []

    if not os.path.isdir(cases_dir):
        return errors, warnings, info

    multi_step_count = 0
    multi_step_issues = 0

    for f in sorted(glob.glob(os.path.join(cases_dir, "**/*.yaml"), recursive=True)):
        try:
            with open(f, encoding='utf-8') as fh:
                case = yaml.safe_load(fh)
        except Exception:
            continue

        if not case or not isinstance(case, dict) or 'steps' not in case:
            continue

        steps = case.get('steps', [])
        if not isinstance(steps, list):
            continue

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            keyword = step.get('keyword', '')
            desc = (step.get('desc', '') or '').lower()
            params = step.get('params', {})
            if not isinstance(params, dict):
                params = {}
            locator = (params.get('locator', '') or '').lower()

            # 检测 el-select 展开步骤
            if keyword == 'click_element' and any(w in desc for w in ['展开', '下拉', 'select']):
                # M3: 扩展检测条件 — 显式匹配 _select 字段命名约定和 _editable companion
                if ('el-select' in locator or 'select' in locator or '下拉' in desc
                        or '_select' in locator or '_editable' in locator
                        or 'ant-select' in locator):
                    multi_step_count += 1
                    sub_issues = check_el_select_three_steps(steps, i)
                    for issue in sub_issues:
                        multi_step_issues += 1
                        rel = os.path.relpath(f, project_dir)
                        errors.append(f"[R3.4] {rel} 步骤{i+1} ({step.get('desc', '')}): {issue}")

            # 检测级联选择器展开
            if keyword == 'click_element' and any(w in desc for w in ['级联', 'cascader']):
                multi_step_count += 1
                sub_issues = check_cascader_steps(steps, i)
                for issue in sub_issues:
                    multi_step_issues += 1
                    rel = os.path.relpath(f, project_dir)
                    errors.append(f"[R3.4] {rel} 步骤{i+1} ({step.get('desc', '')}): {issue}")

            # 检测日期选择器展开
            if keyword == 'click_element' and any(w in desc for w in ['日期', '时间', 'date', 'time']):
                if 'date' in locator or 'time' in locator or 'picker' in locator:
                    multi_step_count += 1
                    sub_issues = check_date_picker_steps(steps, i)
                    for issue in sub_issues:
                        multi_step_issues += 1
                        rel = os.path.relpath(f, project_dir)
                        errors.append(f"[R3.4] {rel} 步骤{i+1} ({step.get('desc', '')}): {issue}")

    info.append(f"[R3.4] 多步操作检查: {multi_step_count} 个多步操作, {multi_step_issues} 个问题")

    return errors, warnings, info


# ============================================================================
# R3.1 + R3.6 + R3.7 探测覆盖率和知识库来源
# ============================================================================

def check_r3_coverage(cases_dir: str, probe_dir: str, project_dir: str,
                      probe_db: Dict[str, dict],
                      pages_fields: Dict[str, set] = None,
                      pending_fields: set = None) -> Tuple[List[str], List[str], List[str]]:
    """R3.1/R3.6/R3.7/R3.10: 全量探测覆盖率 + 知识库来源 + 失败记录

    R3.10: case 中每个 locator（含 L3 关键字内部）都必须有 probe 记录。
    KB 回退：字段不在 probe_db 但在 pages YAML（含 _fallback）中有定义 → warning。
    common_elements 组的通用定位器（loading_mask, success_text 等）免检。
    pending_fields: v1.1 F1 — 值为 xpath=[待确认] 的字段降级为 warning（→ Phase 6 填补）。
    """
    # common_elements 组的字段不需要探测（通用断言/等待定位器）
    _COMMON_GROUPS = {'common_elements', 'common', 'common_data'}
    _COMMON_FIELDS = {'loading_mask', 'success_text', 'error_text',
                      'confirm_btn', 'cancel_btn', 'close_btn'}

    if pending_fields is None:
        pending_fields = set()

    # 构建全量 pages 字段集合（用于 KB 回退检查）
    all_pages_fields = set()
    if pages_fields:
        for group, fields in pages_fields.items():
            if group not in _COMMON_GROUPS:
                all_pages_fields.update(fields)

    errors = []
    warnings = []
    info = []

    if not os.path.isdir(cases_dir):
        return errors, warnings, info

    if not probe_db:
        warnings.append("[R3.10] 未找到 probe 结果文件（_probe/**/*.json），请先运行探测")
        return errors, warnings, info

    # 加载 L3 知识库 workflows（用于展开 L3 关键字内部 locator）
    l3_locators = _load_l3_locators(project_dir)

    # 统计
    total_vars = 0
    covered_ok = 0
    covered_fail = 0
    kb_fallback_count = 0
    uncovered_list = []
    kb_fallback_list = []
    failed_list = []

    for f in sorted(glob.glob(os.path.join(cases_dir, "**/*.yaml"), recursive=True)):
        try:
            with open(f, encoding='utf-8') as fh:
                case = yaml.safe_load(fh)
        except Exception:
            continue

        if not case or not isinstance(case, dict) or 'steps' not in case:
            continue

        for step in case.get('steps', []):
            if not isinstance(step, dict):
                continue

            keyword = step.get('keyword', '')
            locator = step.get('params', {}).get('locator', '')

            # L3 关键字：检查 workflow 内部所有 locator
            if keyword in l3_locators:
                for sub_key, sub_locator in l3_locators[keyword]:
                    # 跳过 common 字段
                    if sub_key in _COMMON_FIELDS:
                        continue
                    total_vars += 1
                    if sub_key in probe_db:
                        el = probe_db[sub_key]
                        if el.get('verified'):
                            covered_ok += 1
                        else:
                            covered_fail += 1
                            failed_list.append({
                                'file': os.path.relpath(f, project_dir),
                                'var': sub_key,
                                'error': el.get('error', '探测失败'),
                            })
                    elif sub_key in all_pages_fields:
                        kb_fallback_count += 1
                        kb_fallback_list.append({
                            'file': os.path.relpath(f, project_dir),
                            'step': step.get('desc', ''),
                            'var': sub_key,
                        })
                    else:
                        uncovered_list.append({
                            'file': os.path.relpath(f, project_dir),
                            'step': step.get('desc', ''),
                            'var': sub_key,
                        })
                continue

            # 普通步骤：检查 locator
            if not isinstance(locator, str) or not locator.strip():
                continue

            # 数据引用跳过
            if '_data.' in locator:
                continue

            # 变量引用 ${group.field}
            if '${' in locator:
                parts = locator.split('.')
                if len(parts) < 2:
                    continue
                group_name = parts[0].strip('${')
                var_name = parts[-1].strip('}"')

                # 跳过 common 组和 common 字段
                if group_name in _COMMON_GROUPS or var_name in _COMMON_FIELDS:
                    continue

                total_vars += 1
                if var_name in probe_db:
                    el = probe_db[var_name]
                    if el.get('verified'):
                        covered_ok += 1
                    else:
                        covered_fail += 1
                        failed_list.append({
                            'file': os.path.relpath(f, project_dir),
                            'var': var_name,
                            'error': el.get('error', '探测失败'),
                        })
                elif var_name in all_pages_fields:
                    # KB 回退覆盖：字段在 pages YAML（含 _fallback）中有定义
                    kb_fallback_count += 1
                    kb_fallback_list.append({
                        'file': os.path.relpath(f, project_dir),
                        'step': step.get('desc', ''),
                        'var': var_name,
                    })
                else:
                    # 变量引用在 probe DB 和 pages YAML 中均无记录 → 未探测
                    uncovered_list.append({
                        'file': os.path.relpath(f, project_dir),
                        'step': step.get('desc', ''),
                        'var': var_name,
                    })
            else:
                # 硬编码 locator（xpath=, css, //...）也检查 probe_db
                if locator.strip() and ('xpath=' in locator or '//' in locator
                                        or locator.startswith('.')):
                    total_vars += 1
                    matched = False
                    for key, el in probe_db.items():
                        if el.get('locator', '') == locator:
                            if el.get('verified'):
                                covered_ok += 1
                            else:
                                covered_fail += 1
                                failed_list.append({
                                    'file': os.path.relpath(f, project_dir),
                                    'var': locator[:50],
                                    'error': el.get('error', '探测失败'),
                                })
                            matched = True
                            break
                    if not matched:
                        uncovered_list.append({
                            'file': os.path.relpath(f, project_dir),
                            'step': step.get('desc', ''),
                            'var': locator[:50],
                        })

    # R3.10: 未覆盖 → error（阻断 Phase 4）
    # v1.1 F1: 待确认字段降级为 warning（→ Phase 6 填补）
    pending_count = 0
    for item in uncovered_list:
        var = item['var']
        # 检查是否为待确认字段（bare name 或 group.field 格式）
        if var in pending_fields:
            pending_count += 1
            warnings.append(
                f"[R3.10] {item['file']}#{item['step']}: "
                f"定位器 {var} 引用了待确认定位器 → Phase 6 填补"
            )
        else:
            errors.append(
                f"[R3.10] {item['file']}#{item['step']}: "
                f"定位器 {var} 无 probe 记录，必须先探测再生成"
            )

    # R3.10 KB 回退：字段在 pages YAML 中有定义但无 probe → warning
    for item in kb_fallback_list:
        warnings.append(
            f"[R3.10-KB] {item['file']}#{item['step']}: "
            f"定位器 {item['var']} 由 KB 回退生成（pages YAML 有定义，建议补充探测确认）"
        )

    # R3.6: 探测失败 → error
    for item in failed_list:
        errors.append(
            f"[R3.6] {item['file']}: 定位器 {item['var']} 探测失败 — "
            f"{item['error']}（请修改对应 pages YAML）"
        )

    # 汇总
    info.append(
        f"[R3.10] Probe 覆盖率: {covered_ok}/{total_vars} 成功, "
        f"{covered_fail} 失败, {kb_fallback_count} KB回退, "
        f"{len(uncovered_list) - pending_count} 未探测, {pending_count} 待确认(降级)")
    info.append(f"[R3.10] probe DB 元素数: {len(probe_db)}, "
                f"pages YAML 字段数: {len(all_pages_fields)}, "
                f"待确认字段数: {len(pending_fields)}")

    if uncovered_list:
        info.append(
            "[HINT] 运行 Phase 6 可自动验证并补全未覆盖的定位器: "
            "python tools/verify_locators.py {project_dir} --cookie \"...\" --url \"...\""
        )

    return errors, warnings, info


def _load_l3_locators(project_dir: str) -> Dict[str, list]:
    """从 _knowledge/*.yaml 加载 L3 workflow 内部的 locator 引用

    兼容 list 和 dict 两种 workflows 格式。
    locators 优先从 workflow 内部读取（mail.yaml 风格），
    其次从顶层读取（旧格式兼容）。

    返回: {keyword_name: [(var_key, locator_str), ...]}
    """
    result = {}
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if not os.path.isdir(knowledge_dir):
        return result

    for f in glob.glob(os.path.join(knowledge_dir, "*.yaml")):
        try:
            with open(f, encoding='utf-8') as fh:
                data = yaml.safe_load(fh)
        except Exception:
            continue
        if not data or not isinstance(data, dict):
            continue

        # 顶层 locators（旧格式兼容）
        top_locators = data.get('locators', {})
        if not isinstance(top_locators, dict):
            top_locators = {}

        # 规范化 workflows 为 [(name, wf_dict), ...]
        raw_workflows = data.get('workflows', {})
        wf_list = []
        if isinstance(raw_workflows, list):
            for wf in raw_workflows:
                if isinstance(wf, dict) and 'name' in wf:
                    wf_list.append((wf['name'], wf))
        elif isinstance(raw_workflows, dict):
            for wf_name, wf in raw_workflows.items():
                if isinstance(wf, dict):
                    wf_list.append((wf_name, wf))

        # 从每个 workflow 提取 locator
        for wf_name, wf_def in wf_list:
            # workflow 内部 locators 优先
            wf_locators = wf_def.get('locators', top_locators)
            if not isinstance(wf_locators, dict):
                wf_locators = top_locators

            internal = []
            for step in _iter_workflow_steps(wf_def.get('steps', [])):
                loc = step.get('params', {}).get('locator', '')
                if isinstance(loc, str) and ('xpath=' in loc or '//' in loc):
                    # H2 修复: raw XPath 无法匹配 probe_db（key 格式不同），跳过
                    # raw XPath 由 R4.21 CSS 检查覆盖，不需要覆盖率检查
                    continue
                elif isinstance(loc, str) and '${' in loc:
                    parts = loc.split('.')
                    if len(parts) >= 2:
                        var_name = parts[-1].strip('}"')
                        internal.append((var_name, loc))
            if internal:
                result[wf_name] = internal

    return result


def _iter_workflow_steps(steps):
    """递归遍历 workflow steps（含 then_steps/else_steps）"""
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        yield step
        # 递归处理条件分支
        params = step.get('params', {})
        if isinstance(params, dict):
            for sub_key in ('then_steps', 'else_steps'):
                yield from _iter_workflow_steps(params.get(sub_key, []))


# ============================================================================
# R3.12: 模块内重复探测检测
# ============================================================================

def check_r3_12_duplicate_probe(probe_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R3.12: 检测同一模块同一上下文中标签被重复探测

    分析 _probe/ 下的 probe JSON 文件，检查同一 URL + 同一 container_type
    下是否有相同 label 被重复探测。跨模块重复（不同页面）是合理的，不检测。
    """
    errors = []
    warnings = []
    info = []

    if not os.path.isdir(probe_dir):
        return errors, warnings, info

    # 优先使用 probe_registry.json（如果存在）
    registry_path = os.path.join(probe_dir, 'probe_registry.json')
    if os.path.exists(registry_path):
        try:
            with open(registry_path, encoding='utf-8') as f:
                registry = json.load(f)
        except (json.JSONDecodeError, OSError):
            registry = None

        if registry:
            dup_count = 0
            for module, labels in registry.get('probed_labels', {}).items():
                seen = {}  # label -> (file, context)
                for label, entry in labels.items():
                    ctx = entry.get('context', 'initial')
                    key = f"{label}:{ctx}"
                    if key in seen:
                        warnings.append(
                            f"[R3.12] [{module}] 标签 \"{label}\" 在上下文 "
                            f"\"{ctx}\" 中被重复探测（{seen[key]} 和 {entry.get('file', '?')}）"
                        )
                        dup_count += 1
                    else:
                        seen[key] = entry.get('file', '?')

            if dup_count == 0:
                info.append("[R3.12] 注册表检查: 无模块内重复探测")
            else:
                info.append(f"[R3.12] 注册表检查: {dup_count} 个重复")
            return errors, warnings, info

    # 回退: 直接分析 probe JSON 文件
    probe_files = glob.glob(os.path.join(probe_dir, "probe_*.json"))
    if not probe_files:
        return errors, warnings, info

    # 按 URL + container_type 分组
    url_ctx_labels = {}  # (url, container_type) -> {label: [(file, key)]}
    for pf in probe_files:
        try:
            with open(pf, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        url = data.get('url', '')
        container = data.get('container_type') or 'initial'
        group_key = (url, container)

        for el in data.get('elements', []):
            label = el.get('label', '')
            key = el.get('key', '')
            if not label:
                continue
            if group_key not in url_ctx_labels:
                url_ctx_labels[group_key] = {}
            if label not in url_ctx_labels[group_key]:
                url_ctx_labels[group_key][label] = []
            url_ctx_labels[group_key][label].append((os.path.basename(pf), key))

    # 检测重复
    dup_count = 0
    for (url, ctx), labels in url_ctx_labels.items():
        for label, entries in labels.items():
            if len(entries) > 1:
                files = [f"{e[0]}({e[1]})" for e in entries]
                warnings.append(
                    f"[R3.12] 重复探测: \"{label}\" 在 {url} ({ctx}) 中被探测 {len(entries)} 次: "
                    f"{', '.join(files)}"
                )
                dup_count += 1

    if dup_count == 0:
        info.append("[R3.12] 无模块内重复探测")
    else:
        info.append(f"[R3.12] 检测到 {dup_count} 个重复探测")

    return errors, warnings, info


# ============================================================================
# R3.14: discovery JSON 完整性检查
# ============================================================================

def check_r3_14_discovery_integrity(probe_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R3.14: 验证 discovery JSON 完整性（v1.1: 支持三种格式）

    检查每个 discovery_*.json 的元素总数是否 > 0。
    空 discovery 意味着探测失败，会导致后续阶段无法生成有效定位器。
    """
    errors = []
    warnings = []
    info = []

    if not os.path.isdir(probe_dir):
        return errors, warnings, info

    discovery_files = glob.glob(os.path.join(probe_dir, 'discovery_*.json'))
    if not discovery_files:
        return errors, warnings, info

    for dj in discovery_files:
        try:
            with open(dj, encoding='utf-8') as fh:
                data = json.load(fh)
            elements = _extract_discovery_elements(data)
            total = len(elements)

            if total == 0:
                errors.append(
                    f"[R3.14] {os.path.basename(dj)}: 元素总数为 0，"
                    f"探测可能失败，请重新运行 Phase 4"
                )
            else:
                info.append(
                    f"[R3.14] {os.path.basename(dj)}: {total} 个元素"
                )
        except Exception as e:
            errors.append(
                f"[R3.14] {os.path.basename(dj)}: 读取失败 - {e}"
            )

    return errors, warnings, info


# ============================================================================
# 主校验入口
# ============================================================================

def validate_probe(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """Phase 4 主校验入口"""
    pages_dir = os.path.join(project_dir, 'pages')
    cases_dir = os.path.join(project_dir, 'cases')
    probe_dir = os.path.join(project_dir, '_probe')

    all_errors = []
    all_warnings = []
    all_info = []

    # ── 统一阶段门禁：检查前置阶段（Phase 2 已废弃，当前无前置要求） ──
    _sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _sys_path not in sys.path:
        sys.path.insert(0, _sys_path)
    try:
        from tools.infra.phase_registry import check_prerequisite_phases
        prereq_violations = check_prerequisite_phases(project_dir, 'validate_04')
        for pv in prereq_violations:
            all_warnings.append(f"[PREREQUISITE] {pv.message} → {pv.suggestion}")
    except ImportError:
        pass  # _phase_registry.py 不存在时静默跳过

    # R3.3: 隐藏过滤检查
    e, w, i = check_r3_3_hidden_filter(pages_dir, project_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R3.4: 多步操作完整性
    e, w, i = check_r3_4_multi_step(cases_dir, project_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R3.1/R3.6/R3.7: 探测覆盖率
    probe_db = load_probe_results(probe_dir)
    pages_fields = load_pages_fields(pages_dir)
    pending_fields = _load_pending_fields(pages_dir)  # v1.1 F1: 预扫描待确认字段
    e, w, i = check_r3_coverage(cases_dir, probe_dir, project_dir, probe_db,
                                pages_fields, pending_fields)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R3.12: 模块内重复探测检测
    e, w, i = check_r3_12_duplicate_probe(probe_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R3.14: discovery JSON 完整性检查（v1.1 新增）
    e, w, i = check_r3_14_discovery_integrity(probe_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    return all_errors, all_warnings, all_info


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description="UIEngine Phase 4 元素探测验证器"
    )
    parser.add_argument(
        'project_dir',
        help="项目根目录路径"
    )
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    errors, warnings, info = validate_probe(project_dir)

    print("=" * 70)
    print(f"UIEngine Probe Validation Report (Phase 4)")
    print(f"Project: {os.path.basename(project_dir)}")
    print("=" * 70)

    for msg in info:
        print(f"  [INFO] {msg}")

    for msg in warnings:
        print(f"  [WARN] {msg}")

    for msg in errors:
        print(f"  [ERR]  {msg}")

    print("-" * 70)
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s), {len(info)} info")
    print("Checked: R3.1, R3.3, R3.4, R3.6, R3.10, R3.12, R3.14")
    print("=" * 70)

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
