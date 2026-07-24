#!/usr/bin/env python3
"""
generate_from_excel.py — 统一编排工具（v2: direct import）

从 Excel + discovery JSON 一次性生成 cases + pages + data。

v2 核心改进（vs v1 subprocess chain）：
  - 消除 subprocess 开销：直接 import _element_resolver, _case_generator, _pages_writer
  - 按需生成：CaseGenerator 记录 required_fields → PagesWriter 只写需要的元素
  - 组名唯一真相源：ElementResolver.get_group_name()（不再依赖 pages YAML 注释）
  - 模块中文名唯一来源：discovery JSON 的 cn_name 字段（design doc §六）

用法:
    python generate_from_excel.py "{excel_json}" \\
        --discovery-dir {project}/_probe/ \\
        --output-dir {project} \\
        [--module-map "中文=slug,..."]
"""

import argparse
import glob
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from _element_resolver import ElementResolver
from _case_generator import (
    CaseGenerator, generate_case_file, preflight_check,
    _batch_repair_case,
    _sync_l3_workflows_to_project,
)
from _pages_writer import PagesWriter


# ═══════════════════════════════════════════════════════════════
# 模块映射
# ═══════════════════════════════════════════════════════════════

def build_module_map(discovery_dir, module_map_str=''):
    """构建中文→英文模块映射。

    中文名唯一来源：discovery JSON 的 cn_name 字段（与 design doc §六 对齐）。

    Args:
        discovery_dir: discovery JSON 目录
        module_map_str: CLI --module-map 参数（可选覆盖）

    Returns: {cn_name: slug} dict
    """
    cn_to_slug = {}
    for disc_file in sorted(glob.glob(os.path.join(discovery_dir, 'discovery_*.json'))):
        try:
            with open(disc_file, encoding='utf-8') as f:
                disc = json.load(f)
        except Exception:
            continue
        slug = disc.get('module', '')
        cn = disc.get('cn_name', '')
        if cn and slug:
            cn_to_slug[cn] = slug

    # CLI 覆盖
    if module_map_str:
        for pair in module_map_str.split(','):
            pair = pair.strip()
            if '=' in pair:
                k, v = pair.split('=', 1)
                cn_to_slug[k.strip()] = v.strip()

    return cn_to_slug


def group_cases_by_module(excel_data, module_map_str, discovery_dir):
    """将 Excel 步骤按模块分组。

    3 级优先级匹配：
      P1: CLI --module-map 显式覆盖
      P2: discovery JSON cn_name 精确匹配（design doc 指定的唯一来源）
      P3: 未匹配 → 诊断退出

    Returns: {module_slug: [case_data, ...]}
    """
    cn_to_slug = build_module_map(discovery_dir, module_map_str)

    # Excel JSON 可以是 list（read_excel.py 输出）或 dict（兼容格式）
    if isinstance(excel_data, list):
        sheets = excel_data
    else:
        sheets = excel_data.get('sheets', [])

    # 从 cases 提取所有中文模块名（不用 sheet name — 一个 sheet 可能含多个模块）
    cn_names_from_excel = set()
    for sheet in sheets:
        for case in sheet.get('cases', []):
            m = case.get('module', '')
            if m:
                cn_names_from_excel.add(m)

    # 构建 cn → slug 映射（3 级优先级）
    mapping = {}
    for cn in cn_names_from_excel:
        slug = cn_to_slug.get(cn)
        if not slug:
            # 尝试 slug 直接匹配（Excel 中可能用英文 slug）
            for disc_slug in cn_to_slug.values():
                if cn == disc_slug or cn.replace('-', '_') == disc_slug.replace('-', '_'):
                    slug = disc_slug
                    break
        if not slug:
            print(f"[FATAL] 无法匹配模块: '{cn}'")
            print(f"  discovery JSON 中的 cn_name: {list(cn_to_slug.keys())}")
            print(f"  可能原因: discover_page.py 未写入 cn_name 字段")
            print(f"  解决: 重新运行 Phase 3 探测，或使用 --module-map \"{cn}=<slug>\"")
            sys.exit(1)
        mapping[cn] = slug

    # 按模块分组 cases
    cases_by_module = {}
    for sheet in sheets:
        sheet_module = sheet.get('sheet', '') or sheet.get('module', '')
        for case in sheet.get('cases', []):
            case_module = case.get('module', '') or sheet_module
            if not case_module:
                continue
            slug = mapping.get(case_module)
            if not slug:
                # 尝试 slug 直接匹配
                for cn, s in mapping.items():
                    if case_module == s or case_module.replace('-', '_') == s.replace('-', '_'):
                        slug = s
                        break
            if not slug:
                slug = case_module  # 兜底
            cases_by_module.setdefault(slug, []).append(case)

    return cases_by_module


def find_discovery_json(discovery_dir, module_slug):
    """查找模块对应的 discovery JSON。

    匹配优先级：
      1. discovery_{slug}.json
      2. discovery_{slug}_merged.json
      3. 连字符↔下划线变体
      4. 子串模糊匹配
    """
    slug = module_slug.replace('-', '_')
    candidates = [
        f'discovery_{slug}.json',
        f'discovery_{slug}_merged.json',
        f'discovery_{module_slug}.json',
        f'discovery_{module_slug.replace("_", "-")}.json',
    ]
    for name in candidates:
        path = os.path.join(discovery_dir, name)
        if os.path.isfile(path):
            return path

    # 子串模糊匹配
    if os.path.isdir(discovery_dir):
        for f in os.listdir(discovery_dir):
            if f.startswith('discovery_') and f.endswith('.json'):
                if slug in f or module_slug in f:
                    return os.path.join(discovery_dir, f)
    return None


# ═══════════════════════════════════════════════════════════════
# Pages YAML 过滤（v1 遗留，v2 中保留作为安全网）
# ═══════════════════════════════════════════════════════════════

def step_filter_pages(output_dir):
    """过滤 pages YAML，移除 cases/data 未引用的元素（v1 遗留安全网）。"""
    pages_dir = os.path.join(output_dir, 'pages')
    cases_dir = os.path.join(output_dir, 'cases')
    data_dir = os.path.join(output_dir, 'data')

    if not os.path.isdir(pages_dir):
        return

    # 扫描所有 cases/data YAML，提取 ${group.field} 引用
    used_refs = set()
    ref_pattern = re.compile(r'\$\{([^}]+)\}')

    for scan_dir in [cases_dir, data_dir]:
        if not os.path.isdir(scan_dir):
            continue
        for root, _, files in os.walk(scan_dir):
            for fname in files:
                if not fname.endswith('.yaml'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding='utf-8') as f:
                        content = f.read()
                    for match in ref_pattern.finditer(content):
                        ref = match.group(1)
                        if '.' in ref and not ref.startswith('common_data.'):
                            used_refs.add(ref)
                except Exception:
                    continue

    if not used_refs:
        print("[INFO] 未找到 ${group.field} 引用，跳过过滤")
        return

    used_by_group = {}
    for ref in used_refs:
        parts = ref.split('.', 1)
        if len(parts) == 2:
            group, field = parts
            used_by_group.setdefault(group, set()).add(field)

    total_removed = 0
    for root, _, files in os.walk(pages_dir):
        for fname in files:
            if not fname.endswith('.yaml'):
                continue
            fpath = os.path.join(root, fname)
            removed = _filter_single_pages_yaml(fpath, used_by_group)
            total_removed += removed

    kept = sum(len(fields) for fields in used_by_group.values())
    print(f"\n[INFO] Pages YAML 过滤: 保留 {kept} 个引用字段, 移除 {total_removed} 个未使用字段")


def _filter_single_pages_yaml(filepath, used_by_group):
    """过滤单个 pages YAML 文件，移除未引用的 field。"""
    ALWAYS_KEEP_GROUPS = {'common_elements', 'page_urls'}

    try:
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
    except Exception:
        return 0

    new_lines = []
    current_group = None
    removed_count = 0

    for line in lines:
        stripped = line.rstrip()

        if stripped and not line[0].isspace() and stripped.endswith(':') and not stripped.startswith('#'):
            current_group = stripped[:-1].strip()
            new_lines.append(line)
            continue

        if current_group and line[0:2] == '  ' and ':' in line and not line.startswith('    '):
            field_key = line.strip().split(':')[0].strip()

            if current_group in ALWAYS_KEEP_GROUPS:
                new_lines.append(line)
                continue

            if field_key.startswith('_'):
                new_lines.append(line)
                continue

            if current_group in used_by_group and field_key in used_by_group[current_group]:
                new_lines.append(line)
            else:
                removed_count += 1
                continue
        else:
            new_lines.append(line)

    if removed_count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

    return removed_count


# ═══════════════════════════════════════════════════════════════
# Gap 1: 翻译质量报告（_match_report.json）
# ═══════════════════════════════════════════════════════════════

def _build_match_report(all_case_stats, module_slug, cn_name=''):
    """聚合所有 case 的步骤来源统计，生成模块级 match_report。

    Args:
        all_case_stats: [{case_id, case_name, seq, total_steps,
                          source_counts, pending_fields, source_map}, ...]
        module_slug: 模块英文标识
        cn_name: 模块中文名

    Returns: dict — 写入 _probe/_match_report_{module}.json
    """
    # 聚合来源计数
    agg_counts = {
        'pending': 0, 'discovery': 0, 'l3_call': 0,
        'static': 0, 'other': 0,
    }
    all_pending = []
    total_steps = 0

    for stat in all_case_stats:
        total_steps += stat['total_steps']
        for src, cnt in stat.get('source_counts', {}).items():
            agg_counts[src] = agg_counts.get(src, 0) + cnt
        for pf in stat.get('pending_fields', []):
            all_pending.append({
                'case_id': stat['case_id'],
                'case_name': stat['case_name'],
                **pf,
            })

    pending_rate = agg_counts['pending'] / total_steps if total_steps > 0 else 0

    # 构建 case 级摘要（不含 source_map 详情，保持报告精简）
    cases_summary = []
    for stat in all_case_stats:
        cases_summary.append({
            'case_id': stat['case_id'],
            'case_name': stat['case_name'],
            'total_steps': stat['total_steps'],
            'source_counts': stat.get('source_counts', {}),
            'pending_count': len(stat.get('pending_fields', [])),
        })

    return {
        'module': module_slug,
        'cn_name': cn_name,
        'summary': {
            'total_cases': len(all_case_stats),
            'total_steps': total_steps,
            'by_source': agg_counts,
            'pending_fields': all_pending,
            'pending_rate': pending_rate,
        },
        'cases': cases_summary,
    }


def _process_single_module(module_slug, case_list, discovery_dir, output_dir,
                           cases_dir_base, data_dir_base, args):
    """H8: 单模块处理（从 main 循环体提取）。

    Steps: 2a-2k (discovery→resolver→cases→data→pages→L3→reports)
    """
    import yaml as _yaml

    print(f"\n{'='*60}")
    print(f"[STEP 2] 处理模块: {module_slug} ({len(case_list)} 条用例)")
    print('='*60)

    # 2a. 查找 discovery JSON
    disc_path = find_discovery_json(discovery_dir, module_slug)
    if not disc_path:
        print(f"[WARN] 未找到 {module_slug} 的 discovery JSON，跳过")
        return

    print(f"[INFO] Discovery: {os.path.basename(disc_path)}")

    # 2b. 加载 discovery JSON
    with open(disc_path, encoding='utf-8') as f:
        disc_data = json.load(f)

    # 2c. ElementResolver 构建 element_map
    resolver = ElementResolver([disc_path], project_dir=output_dir)
    resolver._module_slug = module_slug
    cn_name = disc_data.get('cn_name', '')
    print(f"[INFO] Resolver: {len(resolver.get_groups())} groups, "
          f"{len(resolver.get_element_map())} elements")

    # 2d. Discovery 覆盖率预检
    disc_labels = set()
    for (ctx, label) in resolver.get_element_map():
        disc_labels.add(label)
    preflight_result = preflight_check(case_list, disc_labels, module_slug)
    print(f"[INFO] Discovery 覆盖率: {preflight_result.get('final_hit_rate', 'N/A')}")

    # 2e. CaseGenerator 生成 cases + data + required_fields
    generator = CaseGenerator(resolver, module_slug, project_dir=output_dir)

    cases_dir = os.path.join(output_dir, 'cases', module_slug)
    os.makedirs(cases_dir, exist_ok=True)

    source_maps = []
    repair_cases = []
    all_case_stats = []
    for seq, case_data in enumerate(case_list, start=1):
        filepath, source_map, info = generate_case_file(
            case_data, generator, seq=seq,
            output_dir=cases_dir,
            module=module_slug,
            project_dir=output_dir,
        )
        source_maps.append(source_map)
        all_case_stats.append({
            'case_id': info.get('case_id', f'{module_slug}-case-{seq:02d}'),
            'case_name': info['case_name'],
            'seq': seq,
            'total_steps': info['total_steps'],
            'source_counts': info.get('source_counts', {}),
            'pending_fields': info.get('pending_fields', []),
            'source_map': source_map,
        })
        if info.get('repair_needed'):
            repair_cases.append((filepath, info))

    # 写入 data YAML
    data_dir = os.path.join(output_dir, 'data', module_slug)
    os.makedirs(data_dir, exist_ok=True)
    if generator.data_entries:
        for data_group, entries in generator.data_entries.items():
            data_path = os.path.join(data_dir, f'{data_group}.yaml')
            with open(data_path, 'w', encoding='utf-8') as f:
                _yaml.dump({data_group: entries}, f,
                           allow_unicode=True, default_flow_style=False,
                           sort_keys=False)
            print(f"[INFO] Data: {data_path} ({len(entries)} 条目)")

    # 2e.5 批量修复高 log 占比的 case
    if repair_cases:
        print(f"\n[INFO] 批量修复 {len(repair_cases)} 个高 log 占比 case...")
        for case_file, info in repair_cases:
            repaired = _batch_repair_case(case_file, generator)
            if repaired:
                print(f"  {os.path.basename(case_file)}: 修复 {repaired} 个 log 步骤")

    # 2f. 收集 required_fields
    required_fields = generator.get_required_fields()
    print(f"[INFO] Required fields: {len(required_fields)} 个")

    # 2g. PagesWriter 生成 pages YAML
    if not args.skip_pages:
        pages_dir = os.path.join(output_dir, 'pages', module_slug)
        os.makedirs(pages_dir, exist_ok=True)
        pages_path = os.path.join(pages_dir, 'elements.yaml')

        writer = PagesWriter(resolver)
        writer.write_pages_yaml(required_fields, pages_path,
                                 module_slug, cn_name)
        writer.write_common_elements(pages_path)

        page_url_map = resolver.get_page_url_map()
        if page_url_map:
            writer.write_page_urls(pages_path, page_url_map)

        print(f"[INFO] Pages: {pages_path}")
    else:
        print("[SKIP] Pages YAML 生成 (--skip-pages)")

    # 2h. V4: 同步 L3 workflows
    _sync_l3_workflows_to_project(output_dir, cases_dir)

    # 2i. detail-link 待探测项
    if generator.pending_detail_links:
        print(f"[INFO] Detail-link 待探测: {len(generator.pending_detail_links)} 项")
        probe_dir = os.path.join(output_dir, '_probe')
        os.makedirs(probe_dir, exist_ok=True)
        dl_path = os.path.join(probe_dir, 'pending_detail_links.json')
        with open(dl_path, 'w', encoding='utf-8') as f:
            json.dump(generator.pending_detail_links, f,
                      ensure_ascii=False, indent=2)

    # 2j. match report
    probe_dir = os.path.join(output_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)
    match_report = _build_match_report(all_case_stats, module_slug, cn_name)
    mr_path = os.path.join(probe_dir, f'_match_report_{module_slug}.json')
    with open(mr_path, 'w', encoding='utf-8') as f:
        json.dump(match_report, f, ensure_ascii=False, indent=2)
    pending_total = match_report['summary']['by_source'].get('pending', 0)
    pending_rate = match_report['summary']['pending_rate']
    print(f"[INFO] Match report: {mr_path}")
    print(f"       步骤来源: discovery={match_report['summary']['by_source'].get('discovery', 0)}"
          f", pending={pending_total}, static={match_report['summary']['by_source'].get('static', 0)}"
          f", l3={match_report['summary']['by_source'].get('l3_call', 0)}"
          f" (pending_rate={pending_rate:.1%})")

    # 2k. source map
    source_map_dict = {}
    for stat in all_case_stats:
        source_map_dict[stat['case_id']] = stat['source_map']
    sm_path = os.path.join(cases_dir, '_source_map.json')
    with open(sm_path, 'w', encoding='utf-8') as f:
        json.dump(source_map_dict, f, ensure_ascii=False, indent=2)

    print(f"[DONE] {module_slug}: {len(case_list)} cases, "
          f"{len(required_fields)} fields")


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='统一编排工具（v2）：从 Excel + discovery JSON 生成 cases + pages + data')
    parser.add_argument('excel_json',
                        help='Excel 解析后的 JSON 文件（read_excel.py 输出）')
    parser.add_argument('--discovery-dir', required=True,
                        help='discovery JSON 目录（通常是 {project}/_probe/）')
    parser.add_argument('--output-dir', required=True,
                        help='项目根目录')
    parser.add_argument('--module-map', default='',
                        help='中文→英文模块映射（逗号分隔，如 "问题管理=question"）')
    parser.add_argument('--module-slug', default=None,
                        help='限定处理的模块 slug（调试用）')
    parser.add_argument('--skip-pages', action='store_true',
                        help='跳过 pages YAML 生成（假设已存在）')
    parser.add_argument('--skip-filter', action='store_true',
                        help='（v2 中无效：按需生成无多余元素。保留向后兼容）')
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    discovery_dir = os.path.abspath(args.discovery_dir)

    print(f"[CONFIG] Excel JSON: {args.excel_json}")
    print(f"[CONFIG] Discovery:  {discovery_dir}")
    print(f"[CONFIG] Output:     {output_dir}")
    print(f"[CONFIG] v2 mode:    direct import (no subprocess)")

    # === Step 1: 解析 Excel JSON + 按模块分组 ===
    print(f"\n{'='*60}")
    print("[STEP 1] 解析 Excel JSON + 构建模块映射")
    print('='*60)

    with open(args.excel_json, encoding='utf-8') as f:
        excel_data = json.load(f)

    cases_by_module = group_cases_by_module(
        excel_data, args.module_map, discovery_dir)

    # 限定模块（调试用）
    if args.module_slug:
        slug = args.module_slug
        if slug in cases_by_module:
            cases_by_module = {slug: cases_by_module[slug]}
        else:
            print(f"[FATAL] --module-slug '{slug}' 不在 Excel 数据中")
            print(f"  可用模块: {list(cases_by_module.keys())}")
            sys.exit(1)

    total_cases = sum(len(v) for v in cases_by_module.values())
    print(f"[INFO] 共 {len(cases_by_module)} 个模块, {total_cases} 条用例")
    for slug, cases in cases_by_module.items():
        print(f"  {slug}: {len(cases)} 条")

    # === Step 2: 对每个模块生成 cases + pages + data ===
    # H8: 模块级错误隔离 — 单个模块异常不阻断后续模块
    _module_errors = []
    for module_slug, case_list in cases_by_module.items():
        try:
            _process_single_module(
                module_slug, case_list, discovery_dir, output_dir,
                None, None, args)
        except Exception as _mod_err:
            import traceback
            _module_errors.append((module_slug, str(_mod_err)))
            print(f"\n[ERROR] 模块 {module_slug} 处理失败: {_mod_err}")
            traceback.print_exc()
            print(f"[INFO] 跳过 {module_slug}，继续处理下一个模块...")
            continue

    if _module_errors:
        print(f"\n{'='*60}")
        print(f"[WARN] H8: {len(_module_errors)} 个模块处理失败:")
        for slug, err in _module_errors:
            print(f"  - {slug}: {err}")
        print('='*60)

    # === Step 3: 安全网过滤（v1 遗留，v2 中通常无效果）===
    if not args.skip_filter:
        print(f"\n{'='*60}")
        print("[STEP 3] Pages YAML 安全网过滤")
        print('='*60)
        step_filter_pages(output_dir)
    else:
        print("\n[SKIP] Step 3: Pages YAML 过滤 (--skip-filter)")

    # === 完成 ===
    print(f"\n{'='*60}")
    print("[DONE] 生成完成")
    print(f"  pages:  {os.path.join(output_dir, 'pages')}")
    print(f"  cases:  {os.path.join(output_dir, 'cases')}")
    print(f"  data:   {os.path.join(output_dir, 'data')}")
    print('='*60)


if __name__ == '__main__':
    main()
