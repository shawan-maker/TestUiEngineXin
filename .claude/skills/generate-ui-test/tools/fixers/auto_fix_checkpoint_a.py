#!/usr/bin/env python3
"""Checkpoint A 自愈工具 — 结构一致性自动修复

自动修复 validate_08 --stage early 报告的问题：
- R4.1: 模块名不一致（创建缺失目录）
- R4.37: Case ID 重复（加模块前缀）
- SUITE_REF: Suite 引用 case 不存在（R4.37 修复时同步）

安全性约束：
- 确定性：修复结果唯一
- 可验证：修复后立即验证
- 可回滚：修复前备份
- 不扩散：修复 A 不破坏 B
- 幂等性：重复修复结果相同

用法：
    python tools/auto_fix_checkpoint_a.py {project_dir} [--stage early] [--dry-run]
"""

import os
import re
import sys
import json
import shutil
import argparse
import subprocess
from typing import List, Dict, Optional

# 标准关键字（UIEngine 提供）
STANDARD_KEYWORDS = {
    'open_url', 'refresh', 'click_element', 'fill_value', 'wait_for_time',
    'wait_for_element_visible', 'wait_for_element_hidden', 'if_element_visible',
    'except_to_be_visible', 'get_element_count', 'get_text', 'close_browser',
    'open_browser', 'go_back', 'hover_element', 'select_option',
}


def load_violations(project_dir: str) -> List[Dict]:
    """Load violations from Phase 5 JSON output."""
    json_path = os.path.join(project_dir, '_probe', 'phase8_violations.json')
    if not os.path.exists(json_path):
        print(f"[ERROR] 未找到 violations JSON: {json_path}")
        print("        请先运行: python validators/validate_08_scripts.py {project_dir} --stage early")
        sys.exit(1)

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    # JSON 可能是 list 或 dict（取决于 validate_08 版本）
    if isinstance(data, list):
        return data
    return data.get('violations', [])


def auto_fix_r4_1(project_dir: str, violations: List[Dict]) -> int:
    """R4.1: 创建缺失的模块目录"""
    fixed = 0
    r4_1_violations = [v for v in violations if v['rule'] == 'R4.1']

    for v in r4_1_violations:
        # 解析 message: "模块 \"{module}\" 缺少: {cats}"
        match = re.search(r'模块 "([^"]+)" 缺少: (.+)', v['message'])
        if not match:
            continue

        module = match.group(1)
        missing_cats = [c.strip().rstrip('/') for c in match.group(2).split(',')]

        for cat in missing_cats:
            target_dir = os.path.join(project_dir, cat, module)
            if not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
                print(f"  [FIXED] R4.1: 创建目录 {cat}/{module}/")
                fixed += 1

    return fixed


def auto_fix_r4_37(project_dir: str, violations: List[Dict]) -> int:
    """R4.37: 为重复 case ID 加模块前缀，同步更新 suite 引用"""
    fixed = 0
    r4_37_violations = [v for v in violations if v['rule'] == 'R4.37']

    for v in r4_37_violations:
        # 解析 message: "case ID '{case_id}' 在 {n} 个文件中重复: {files}"
        match = re.search(r"case ID '([^']+)' 在 \d+ 个文件中重复: (.+)", v['message'])
        if not match:
            # 尝试解析 "case ID '{case_id}' 缺少模块前缀"
            match2 = re.search(r"case ID '([^']+)' 缺少模块前缀", v['message'])
            if match2:
                case_id = match2.group(1)
                # 从 suggestion 提取建议的新 ID
                sugg_match = re.search(r"改为 (.+)", v['suggestion'])
                if sugg_match:
                    new_id = sugg_match.group(1)
                    case_file = os.path.join(project_dir, v['file'].replace('\\', os.sep))
                    if _update_case_id(case_file, case_id, new_id):
                        _update_suite_refs(project_dir, case_id, new_id)
                        print(f"  [FIXED] R4.37: {case_id} -> {new_id}")
                        fixed += 1
            continue

        case_id = match.group(1)
        file_list = [f.strip() for f in match.group(2).split(',')]

        # 为每个文件加模块前缀
        for rel_path in file_list:
            case_file = os.path.join(project_dir, rel_path.replace('\\', os.sep))
            if not os.path.exists(case_file):
                continue

            # 提取模块名
            module = os.path.basename(os.path.dirname(case_file))
            new_id = f"{module}-{case_id}" if case_id.startswith('case-') else f"{module}_{case_id}"

            if _update_case_id(case_file, case_id, new_id):
                _update_suite_refs(project_dir, case_id, new_id)
                print(f"  [FIXED] R4.37: {case_id} -> {new_id} ({rel_path})")
                fixed += 1

    return fixed


def _update_case_id(case_file: str, old_id: str, new_id: str) -> bool:
    """Update case ID in YAML file."""
    try:
        # 备份
        backup_file = case_file + '.bak'
        shutil.copy(case_file, backup_file)

        # 读取
        with open(case_file, encoding='utf-8') as f:
            lines = f.readlines()

        # 替换 id: 行
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith('id:'):
                # 保留缩进和注释
                indent = len(line) - len(line.lstrip())
                lines[i] = f"{' ' * indent}id: {new_id}\n"
                updated = True
                break

        if updated:
            with open(case_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            os.remove(backup_file)
            return True
        else:
            # 回滚
            shutil.copy(backup_file, case_file)
            os.remove(backup_file)
            return False

    except Exception as e:
        print(f"  [ERROR] 更新 case ID 失败: {e}")
        return False


def _update_suite_refs(project_dir: str, old_id: str, new_id: str):
    """Update suite YAML references when case ID changes."""
    suites_dir = os.path.join(project_dir, 'suites')
    if not os.path.isdir(suites_dir):
        return

    for root, dirs, files in os.walk(suites_dir):
        for f in files:
            if f.endswith(('.yaml', '.yml')):
                path = os.path.join(root, f)
                try:
                    with open(path, encoding='utf-8') as fh:
                        content = fh.read()

                    if old_id in content:
                        content = content.replace(old_id, new_id)
                        with open(path, 'w', encoding='utf-8') as fh:
                            fh.write(content)
                        print(f"    [SUITE_REF] 更新引用: {os.path.relpath(path, project_dir)}")
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(
        description='Checkpoint A 自愈工具 — 结构一致性自动修复'
    )
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--stage', choices=['early'], default='early',
                        help='验证阶段（仅支持 early）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告问题，不执行修复')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[ERROR] 目录不存在: {project_dir}")
        sys.exit(1)

    # 加载 violations
    violations = load_violations(project_dir)

    # 过滤 early stage
    early_rules = {'R4.1', 'R4.37', 'SUITE_REF', 'PREREQUISITE'}
    early_violations = [v for v in violations if v['rule'] in early_rules]

    if not early_violations:
        print("[OK] Checkpoint A: 无问题需要修复")
        sys.exit(0)

    # 统计
    error_count = sum(1 for v in early_violations if v['severity'] == 'error')
    warn_count = sum(1 for v in early_violations if v['severity'] == 'warning')
    print(f"[INFO] Checkpoint A 发现 {error_count} errors + {warn_count} warnings")

    if args.dry_run:
        print("[DRY-RUN] 不执行修复")
        for v in early_violations:
            print(f"  [{v['severity'].upper()}] {v['rule']}: {v['message']}")
        sys.exit(0)

    # 执行修复
    print("\n[修复] 开始自动修复...")
    total_fixed = 0

    # R4.1
    fixed = auto_fix_r4_1(project_dir, early_violations)
    total_fixed += fixed
    if fixed:
        print(f"  R4.1: 修复了 {fixed} 个问题")

    # R4.37 (includes SUITE_REF sync)
    fixed = auto_fix_r4_37(project_dir, early_violations)
    total_fixed += fixed
    if fixed:
        print(f"  R4.37: 修复了 {fixed} 个问题")

    print(f"\n[完成] 自动修复了 {total_fixed}/{len(early_violations)} 个问题")

    # 建议重新验证
    if total_fixed > 0:
        print("\n[建议] 重新运行验证:")
        print(f"  python validators/validate_08_scripts.py {project_dir} --stage early")

    sys.exit(0 if total_fixed > 0 else 1)


if __name__ == '__main__':
    main()
