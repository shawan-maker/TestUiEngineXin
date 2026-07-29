#!/usr/bin/env python3
"""Checkpoint B 自愈工具 — 语义一致性自动修复

自动修复 validate_08 --stage final 报告的部分问题：
- R4.7: case_refs 排序（按依赖层级排序）
- R4.20: case 步骤顺序与 Excel 不一致（标记建议，不自动修复）

安全性约束：
- R4.7 总是安全（按 ORDER_TIERS 排序，结果唯一）
- R4.20 不自动修复（需重新生成 case，风险高）

用法：
    python tools/auto_fix_checkpoint_b.py {project_dir} [--stage final] [--dry-run]
"""

import os
import re
import sys
import json
import shutil
import argparse
from typing import List, Dict, Optional

import yaml

# 共享工具函数（_get_case_tier 单一真相源）
_tools_dir = os.path.dirname(os.path.abspath(__file__))
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)
from core.tier_utils import get_case_tier as _get_case_tier, ORDER_TIERS


def load_violations(project_dir: str) -> List[Dict]:
    """Load violations from Phase 5 JSON output."""
    json_path = os.path.join(project_dir, '_probe', 'phase8_violations.json')
    if not os.path.exists(json_path):
        print(f"[ERROR] 未找到 violations JSON: {json_path}")
        print("        请先运行: python validators/validate_08_scripts.py {project_dir} --stage final")
        sys.exit(1)

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    # JSON 可能是 list 或 dict（取决于 validate_08 版本）
    if isinstance(data, list):
        return data
    return data.get('violations', [])


def auto_fix_r4_7(project_dir: str, violations: List[Dict]) -> int:
    """R4.7: 按 ORDER_TIERS 重新排序 suite 的 case_refs

    ⚠️ 当前禁用: yaml.dump() 会丢失 YAML 注释和格式。
    建议手动修复或使用 ruamel.yaml 替代。
    """
    r4_7_violations = [v for v in violations if v['rule'] == 'R4.7']

    for v in r4_7_violations:
        print(f"  [WARN] R4.7: {v['message']}")
        print(f"         建议手动排序 case_refs（自动修复会丢失 YAML 注释）")

    return 0  # 不自动修复


def handle_r4_20(project_dir: str, violations: List[Dict]) -> int:
    """R4.20: 标记建议，不自动修复（风险高）"""
    r4_20_violations = [v for v in violations if v['rule'] == 'R4.20']

    for v in r4_20_violations:
        print(f"  [WARN] R4.20: {v['message']}")
        print(f"         建议: {v['suggestion']}")

    return 0  # 不自动修复


def main():
    parser = argparse.ArgumentParser(
        description='Checkpoint B 自愈工具 — 语义一致性自动修复'
    )
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--stage', choices=['final'], default='final',
                        help='验证阶段（仅支持 final）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告问题，不执行修复')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[ERROR] 目录不存在: {project_dir}")
        sys.exit(1)

    # 加载 violations
    violations = load_violations(project_dir)

    # 过滤 final stage
    final_rules = {'R4.3', 'R4.7', 'R4.20', 'R4.33', 'R4.41', 'R4.42', 'R4.43',
                   'SUITE_REF', 'EXCEL_COMPLETE', 'PREREQUISITE'}
    final_violations = [v for v in violations if v['rule'] in final_rules]

    if not final_violations:
        print("[OK] Checkpoint B: 无问题需要修复")
        sys.exit(0)

    # 统计
    error_count = sum(1 for v in final_violations if v['severity'] == 'error')
    warn_count = sum(1 for v in final_violations if v['severity'] == 'warning')
    print(f"[INFO] Checkpoint B 发现 {error_count} errors + {warn_count} warnings")

    if args.dry_run:
        print("[DRY-RUN] 不执行修复")
        for v in final_violations:
            print(f"  [{v['severity'].upper()}] {v['rule']}: {v['message']}")
        sys.exit(0)

    # 执行修复
    print("\n[修复] 开始自动修复...")
    total_fixed = 0

    # R4.7 (case_refs 排序)
    fixed = auto_fix_r4_7(project_dir, final_violations)
    total_fixed += fixed
    if fixed:
        print(f"  R4.7: 修复了 {fixed} 个问题")

    # R4.20 (标记建议)
    handle_r4_20(project_dir, final_violations)

    # 报告不可自动修复的规则
    non_fixable = {'R4.3', 'R4.33', 'R4.41', 'R4.42', 'R4.43', 'SUITE_REF',
                   'EXCEL_COMPLETE', 'PREREQUISITE'}
    for rule in non_fixable:
        count = sum(1 for v in final_violations if v['rule'] == rule)
        if count:
            print(f"  [SKIP] {rule}: {count} 个问题需要人工介入")

    print(f"\n[完成] 自动修复了 {total_fixed}/{len(final_violations)} 个问题")

    # 建议重新验证
    if total_fixed > 0:
        print("\n[建议] 重新运行验证:")
        print(f"  python validators/validate_08_scripts.py {project_dir} --stage final")

    sys.exit(0 if total_fixed > 0 else 1)


if __name__ == '__main__':
    main()
