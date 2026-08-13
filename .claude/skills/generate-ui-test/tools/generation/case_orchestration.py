#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
case_orchestration.py - Case generation orchestration functions

Extracted from _case_generator.py. Contains the top-level functions that
wire together CaseGenerator, SelfCheckLayer, and utilities to produce
case YAML files.

Functions:
    - _load_l3_trigger_patterns: Load L3 trigger patterns from _knowledge/
    - _load_l3_keyword_names: Load L3 keyword names from project
    - save_repair_log: Save repair log to _probe/repair_log.json
    - _normalize_desc_quotes: Add Chinese quotes to known labels in desc
    - _ensure_desc_quotes: Ensure all [pending] descs have quotes
    - _sync_l3_workflows_to_project: Sync L3 workflows to project
    - _classify_steps_for_report: Classify steps by source type
    - generate_case_file: Generate a single case YAML file
    - preflight_check: Discovery coverage pre-check
    - _batch_repair_case: Batch repair log steps in case YAML
"""

import glob
import os
import re
import json
import yaml
from collections import defaultdict

from core.step_patterns import parse_step
from generation.case_utils import _detect_container_type, _debug_f7
from generation.case_generator import CaseGenerator
from generation.self_check import SelfCheckLayer, _SC_ENGINE_KEYWORDS


def _load_target_url(project_dir):
    """从 config.yaml 加载 target_url。

    Returns: target_url 字符串或 None
    """
    if not project_dir:
        return None
    config_path = os.path.join(project_dir, 'config.yaml')
    if not os.path.isfile(config_path):
        return None
    try:
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        return config.get('target_url')
    except Exception:
        return None


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

    # Fallback: 相对路径（以 / 开头）→ 拼接 config.yaml 的 target_url
    if not url:
        for step in raw_steps:
            m = re.search(r'访问\s+(/\S+)', step)
            if m:
                rel_path = m.group(1)
                target_url = _load_target_url(project_dir)
                if target_url:
                    url = target_url.rstrip('/') + rel_path
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
    url_step_consumed = False  # 追踪是否已跳过第一个"访问"步骤
    i = 0
    while i < len(raw_steps):
        step_text = raw_steps[i]

        # 跳过已被 preamble 处理的第一个"访问"步骤（同时匹配完整 URL 和相对路径）
        if re.search(r'^访问\s*(https?://|/\S+)', step_text) and not url_step_consumed:
            url_step_consumed = True
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

        # [DEBUG-TEMP] 临时调试日志：追踪 auto-add wait_for_loading_complete 逻辑
        is_btn = generator._is_button_action(parsed)
        no_wait = generator._next_needs_no_wait(raw_steps, i)
        should_add = is_btn and not no_wait
        print(f"    [DEBUG-TEMP] Step {i+1}: '{step_text[:30]}' | type={parsed['type']}, "
              f"is_button={is_btn}, next_no_wait={no_wait}, should_add_wait={should_add}")
        # [DEBUG-TEMP-END]

        if (generator._is_button_action(parsed)
                and not generator._next_needs_no_wait(raw_steps, i)):
            steps.append({
                'desc': '等待页面加载完成',
                'keyword': 'wait_for_loading_complete',
                'params': {},
            })
            # [DEBUG-TEMP]
            print(f"    [DEBUG-TEMP] [OK] added wait_for_loading_complete (Step {i+1})")
            # [DEBUG-TEMP-END]

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
