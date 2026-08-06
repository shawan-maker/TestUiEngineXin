#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 5: 重跑 Phase 5 的"安全网过滤"逻辑，对比过滤前后的 pages YAML

目标: 确认是过滤删掉了 field_7ddbe1_* 字段，还是 PagesWriter 根本没写入
"""

import sys
import os
import re
import shutil

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_DIR = os.path.join(os.path.dirname(__file__), 'examples', 'ecsCloud')
SKILL_DIR = os.path.join(os.path.dirname(__file__), '.claude', 'skills', 'generate-ui-test')


def step1_check_current_pages_yaml():
    """Step 1: 检查当前 pages YAML 内容"""
    print("=" * 80)
    print("[Step 1] 当前 pages YAML 内容")
    print("=" * 80)

    pages_file = os.path.join(PROJECT_DIR, 'pages', 'estack', 'elements.yaml')
    if os.path.exists(pages_file):
        with open(pages_file, encoding='utf-8') as f:
            content = f.read()
        print(f"\n文件: {pages_file}")
        print(f"大小: {os.path.getsize(pages_file)} bytes")
        print(f"内容:")
        print("-" * 40)
        print(content)
        print("-" * 40)

        # 统计 group
        groups = re.findall(r'^(\w[\w-]*):', content, re.MULTILINE)
        print(f"\nGroups: {groups}")

        # 统计 field
        fields = re.findall(r'^  (\w[\w-]*):', content, re.MULTILINE)
        print(f"Fields: {len(fields)} 个")
        for f in fields:
            print(f"  - {f}")
    else:
        print(f"  ❌ 文件不存在: {pages_file}")

    print()


def step2_scan_case_yaml_refs():
    """Step 2: 扫描 case/data YAML 中的 ${group.field} 引用"""
    print("=" * 80)
    print("[Step 2] 扫描 case/data YAML 引用")
    print("=" * 80)

    cases_dir = os.path.join(PROJECT_DIR, 'cases')
    data_dir = os.path.join(PROJECT_DIR, 'data')
    ref_pattern = re.compile(r'\$\{([^}]+)\}')
    used_refs = set()

    for scan_dir in [cases_dir, data_dir]:
        if not os.path.isdir(scan_dir):
            print(f"  [SKIP] 目录不存在: {scan_dir}")
            continue
        for root, _, files in os.walk(scan_dir):
            for fname in files:
                if not fname.endswith('.yaml'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding='utf-8') as f:
                        content = f.read()
                    refs = ref_pattern.findall(content)
                    for ref in refs:
                        if '.' in ref and not ref.startswith('common_data.'):
                            used_refs.add(ref)
                    print(f"  {os.path.relpath(fpath, PROJECT_DIR)}: {len(refs)} refs")
                except Exception as e:
                    print(f"  [ERROR] {fpath}: {e}")

    print(f"\n总引用数: {len(used_refs)}")

    # 按 group 分组
    used_by_group = {}
    for ref in sorted(used_refs):
        parts = ref.split('.', 1)
        if len(parts) == 2:
            group, field = parts
            used_by_group.setdefault(group, set()).add(field)

    print(f"\n按 group 分组 ({len(used_by_group)} groups):")
    for group in sorted(used_by_group.keys()):
        fields = sorted(used_by_group[group])
        print(f"\n  {group} ({len(fields)} fields):")
        for f in fields:
            print(f"    - {f}")

    # 检查 7ddbe1 是否在引用中
    print(f"\n--- 7ddbe1 引用检查 ---")
    refs_7ddbe1 = [r for r in used_refs if '7ddbe1' in r]
    if refs_7ddbe1:
        print(f"  ✅ 找到 {len(refs_7ddbe1)} 个 7ddbe1 引用:")
        for r in sorted(refs_7ddbe1):
            print(f"    - ${{{r}}}")
    else:
        print(f"  ❌ 未找到 7ddbe1 引用!")

    print()
    return used_by_group


def step3_simulate_filter(used_by_group):
    """Step 3: 模拟过滤逻辑（不修改文件，只输出结果）"""
    print("=" * 80)
    print("[Step 3] 模拟安全网过滤")
    print("=" * 80)

    pages_file = os.path.join(PROJECT_DIR, 'pages', 'estack', 'elements.yaml')
    if not os.path.exists(pages_file):
        print(f"  ❌ 文件不存在")
        return

    with open(pages_file, encoding='utf-8') as f:
        lines = f.readlines()

    print(f"\n原始文件: {len(lines)} 行")

    ALWAYS_KEEP_GROUPS = {'common_elements', 'page_urls'}
    new_lines = []
    current_group = None
    kept = 0
    removed = 0
    removed_fields = []

    for line_num, line in enumerate(lines, 1):
        stripped = line.rstrip()

        # Group header 检测
        if stripped and not line[0].isspace() and stripped.endswith(':') and not stripped.startswith('#'):
            current_group = stripped[:-1].strip()
            new_lines.append(line)
            print(f"\n  [GROUP] L{line_num}: '{current_group}'")
            continue

        # Field 检测 (2空格缩进 + 冒号 + 不4空格缩进)
        if current_group and len(line) >= 2 and line[0:2] == '  ' and ':' in line and not line.startswith('    '):
            field_key = line.strip().split(':')[0].strip()

            if current_group in ALWAYS_KEEP_GROUPS:
                new_lines.append(line)
                kept += 1
                print(f"    [KEEP-ALWAYS] L{line_num}: {field_key} (always-keep group)")
                continue

            if field_key.startswith('_'):
                new_lines.append(line)
                kept += 1
                print(f"    [KEEP-UNDER] L{line_num}: {field_key} (underscore prefix)")
                continue

            if current_group in used_by_group and field_key in used_by_group[current_group]:
                new_lines.append(line)
                kept += 1
                print(f"    [KEEP] L{line_num}: {field_key}")
            else:
                removed += 1
                removed_fields.append((current_group, field_key))
                in_group = current_group in used_by_group
                print(f"    [REMOVE] L{line_num}: {field_key} "
                      f"(group_in_refs={in_group}, "
                      f"field_in_refs={field_key in used_by_group.get(current_group, set())})")
        else:
            new_lines.append(line)

    print(f"\n--- 过滤结果 ---")
    print(f"  保留: {kept}")
    print(f"  移除: {removed}")
    if removed_fields:
        print(f"  被移除的字段:")
        for g, f in removed_fields:
            print(f"    - {g}.{f}")

    print()


def step4_check_filter_before_after():
    """Step 4: 检查 generate_from_excel.py 中 filter 调用的上下文"""
    print("=" * 80)
    print("[Step 4] 检查 filter 调用上下文")
    print("=" * 80)

    gen_path = os.path.join(SKILL_DIR, 'tools', 'generation', 'generate_from_excel.py')
    with open(gen_path, encoding='utf-8') as f:
        lines = f.readlines()

    # 找 Step 3 过滤的调用位置
    for i, line in enumerate(lines):
        if '安全网过滤' in line or '_filter_unused_pages_fields' in line:
            # 输出上下文
            start = max(0, i - 5)
            end = min(len(lines), i + 15)
            print(f"\n  代码上下文 (L{start+1}-L{end}):")
            for j in range(start, end):
                marker = ">>>" if j == i else "   "
                print(f"    {marker} L{j+1}: {lines[j].rstrip()}")

    print()


def step5_check_pages_writer_output():
    """Step 5: 检查 PagesWriter 写入前的 required_fields 内容"""
    print("=" * 80)
    print("[Step 5] 检查 _match_report 中的 pending 字段")
    print("=" * 80)

    import json
    report_path = os.path.join(PROJECT_DIR, '_probe', '_match_report_estack.json')
    if os.path.exists(report_path):
        with open(report_path, encoding='utf-8') as f:
            report = json.load(f)

        # 查找 pending 字段
        pending = report.get('all_pending', [])
        print(f"\n_match_report: {len(pending)} 个 pending 字段")

        # 按 group 分组
        pending_by_group = {}
        for p in pending:
            group = p.get('group', '?')
            field = p.get('field', '?')
            pending_by_group.setdefault(group, []).append(field)

        for group in sorted(pending_by_group.keys()):
            fields = sorted(pending_by_group[group])
            print(f"\n  {group} ({len(fields)} pending):")
            for f in fields:
                print(f"    - {f}")

        # 检查 7ddbe1 是否在 pending 中
        pending_7ddbe1 = [p for p in pending if '7ddbe1' in p.get('field', '')]
        if pending_7ddbe1:
            print(f"\n--- 7ddbe1 在 pending 中 ---")
            for p in pending_7ddbe1:
                print(f"  group={p.get('group')}, field={p.get('field')}, "
                      f"label={p.get('label')}")
        else:
            print(f"\n--- 7ddbe1 不在 pending 中 ---")

        # 检查 source_map 中的 7ddbe1
        source_map = report.get('source_map', {})
        if source_map:
            print(f"\n--- source_map 中的 7ddbe1 ---")
            for case_id, case_map in source_map.items():
                for step_desc, source_info in case_map.items():
                    if '7ddbe1' in str(source_info) or '网络' in step_desc:
                        print(f"  [{case_id}] {step_desc[:50]} → {source_info}")
    else:
        print(f"  ❌ 文件不存在: {report_path}")

    print()


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("Pages YAML 过滤诊断")
    print("=" * 80 + "\n")

    step1_check_current_pages_yaml()
    used_by_group = step2_scan_case_yaml_refs()
    step3_simulate_filter(used_by_group)
    step4_check_filter_before_after()
    step5_check_pages_writer_output()

    print("=" * 80)
    print("诊断完成")
    print("=" * 80)
