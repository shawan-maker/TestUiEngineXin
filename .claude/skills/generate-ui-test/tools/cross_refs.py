#!/usr/bin/env python3
"""
cross_refs.py — 端到端引用验证

管线核心安全网：检查 case/data/pages/suites 之间的引用一致性。
在 Phase 5 完成后、Phase 6 运行前执行，防止无效引用进入运行时阶段。
"""

import os
import re
from pathlib import Path
from typing import Optional
import yaml


def validate_cross_refs(project_dir: str) -> dict:
    """端到端引用验证 — 管线核心安全网

    检查维度:
      1. case 中 ${group.field} → pages YAML 中存在（locator 引用）
      2. case 中 ${group.field} → data YAML 中存在（value 引用）
      3. pages YAML 中每个 field 至少有 1 个 case 引用（反向检查，warning）
      4. suite 中 case_refs → cases YAML 中存在对应 id
      5. L3 keyword 调用 → module_keywords.py 中存在

    Args:
        project_dir: 项目根目录

    Returns:
        dict with 'errors' and 'warnings' lists (structured result)
    """
    errors = []
    warnings = []

    project_path = Path(project_dir)

    # 1. 加载所有 pages YAML → 构建 {group: set(fields)}
    pages_refs = _load_all_pages_refs(project_path / "pages")

    # 2. 加载所有 data YAML → 构建 {group: set(fields)}
    data_refs = _load_all_data_refs(project_path / "data")

    # 3. 扫描所有 case YAML → 提取 ${group.field} 引用
    case_refs, locator_refs, data_value_refs = _scan_all_case_refs(project_path / "cases")

    # 4. 逐条检查 locator 引用
    for ref in locator_refs:
        group, field = ref.split(".", 1)
        if group not in pages_refs or field not in pages_refs[group]:
            errors.append(
                f"定位器引用缺失: ${{{ref}}} 在 pages/ 中不存在"
            )

    # 5. 逐条检查 data value 引用
    for ref in data_value_refs:
        group, field = ref.split(".", 1)
        if group not in data_refs or field not in data_refs[group]:
            errors.append(
                f"数据引用缺失: ${{{ref}}} 在 data/ 中不存在"
            )

    # 6. 反向检查：pages 字段是否被引用（warning，不阻断）
    all_referenced_fields = set()
    for ref in locator_refs:
        all_referenced_fields.add(ref)

    for group, fields in pages_refs.items():
        for field in fields:
            full_ref = f"{group}.{field}"
            if full_ref not in all_referenced_fields:
                warnings.append(
                    f"未引用字段: pages/{group}.{field} 未被任何 case 引用"
                )

    # 7. suite → case 引用检查
    suite_refs = _load_all_suite_refs(project_path / "suites")
    case_ids = _load_all_case_ids(project_path / "cases")
    for suite_ref in suite_refs:
        if suite_ref not in case_ids:
            errors.append(
                f"Suite 引用缺失: case_id '{suite_ref}' 在 cases/ 中不存在"
            )

    # 8. L3 keyword 调用检查（如果 module_keywords.py 存在）
    l3_keywords = _load_l3_keywords(project_path)
    if l3_keywords:
        l3_calls = _scan_l3_calls(project_path / "cases")
        for call in l3_calls:
            if call not in l3_keywords:
                errors.append(
                    f"L3 关键字缺失: '{call}' 在 module_keywords.py 中不存在"
                )

    # 输出报告
    if errors or warnings:
        print(f"\n{'='*60}")
        print(f"端到端引用验证报告")
        print(f"{'='*60}")

        if errors:
            print(f"\n❌ 错误 ({len(errors)}):")
            for err in errors[:20]:  # 最多显示 20 条
                print(f"  • {err}")
            if len(errors) > 20:
                print(f"  ... 还有 {len(errors) - 20} 条错误")

        if warnings:
            print(f"\n⚠️  警告 ({len(warnings)}):")
            for warn in warnings[:10]:  # 最多显示 10 条
                print(f"  • {warn}")
            if len(warnings) > 10:
                print(f"  ... 还有 {len(warnings) - 10} 条警告")

        print(f"\n{'='*60}\n")

    return {"errors": errors, "warnings": warnings}


# ─── 辅助函数 ───

def _load_all_pages_refs(pages_dir: Path) -> dict[str, set[str]]:
    """加载所有 pages YAML，返回 {group: set(fields)}"""
    refs = {}

    if not pages_dir.exists():
        return refs

    for yaml_file in pages_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                continue

            for group_name, group_data in data.items():
                if group_name.startswith('_'):
                    continue

                if isinstance(group_data, dict):
                    if group_name not in refs:
                        refs[group_name] = set()
                    refs[group_name].update(group_data.keys())

        except Exception as e:
            print(f"⚠️  无法加载 {yaml_file}: {e}")

    return refs


def _load_all_data_refs(data_dir: Path) -> dict[str, set[str]]:
    """加载所有 data YAML，返回 {group: set(fields)}"""
    refs = {}

    if not data_dir.exists():
        return refs

    for yaml_file in data_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                continue

            for group_name, group_data in data.items():
                if group_name.startswith('_'):
                    continue

                if isinstance(group_data, dict):
                    if group_name not in refs:
                        refs[group_name] = set()
                    refs[group_name].update(group_data.keys())

        except Exception as e:
            print(f"⚠️  无法加载 {yaml_file}: {e}")

    return refs


def _scan_all_case_refs(cases_dir: Path) -> tuple[set[str], set[str], set[str]]:
    """扫描所有 case YAML，提取 ${group.field} 引用

    Returns:
        (all_refs, locator_refs, data_value_refs)
    """
    all_refs = set()
    locator_refs = set()
    data_value_refs = set()

    if not cases_dir.exists():
        return all_refs, locator_refs, data_value_refs

    pattern = re.compile(r'\$\{([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\}')

    for yaml_file in cases_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                content = f.read()

            matches = pattern.findall(content)
            for ref in matches:
                all_refs.add(ref)
                group, field = ref.split(".", 1)

                # 判断是 locator 引用还是 data value 引用
                # 规则：group 以 _data 结尾 → data 引用；否则 → locator 引用
                # 同时排除已知非 pages/data 的引用（如 common_data 中的 target_url）
                if group.endswith('_data'):
                    data_value_refs.add(ref)
                else:
                    locator_refs.add(ref)

        except Exception as e:
            print(f"⚠️  无法扫描 {yaml_file}: {e}")

    return all_refs, locator_refs, data_value_refs


def _load_all_suite_refs(suites_dir: Path) -> set[str]:
    """加载所有 suite YAML，返回 case_refs 集合"""
    refs = set()

    if not suites_dir.exists():
        return refs

    for yaml_file in suites_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                continue

            case_refs = data.get('case_refs', [])
            if isinstance(case_refs, list):
                refs.update(case_refs)

        except Exception as e:
            print(f"⚠️  无法加载 {yaml_file}: {e}")

    return refs


def _load_all_case_ids(cases_dir: Path) -> set[str]:
    """加载所有 case YAML，返回 case id 集合"""
    ids = set()

    if not cases_dir.exists():
        return ids

    for yaml_file in cases_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                continue

            case_id = data.get('id')
            if case_id:
                ids.add(case_id)

        except Exception as e:
            print(f"⚠️  无法加载 {yaml_file}: {e}")

    return ids


def _load_l3_keywords(project_dir: Path) -> set[str]:
    """从 module_keywords.py 加载 L3 关键字名称"""
    keywords = set()

    module_keywords_path = project_dir / "lib" / "module_keywords.py"
    if not module_keywords_path.exists():
        return keywords

    try:
        with open(module_keywords_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 简单正则提取 def keyword_name(self, ...)
        pattern = re.compile(r'^\s+def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', re.MULTILINE)
        matches = pattern.findall(content)

        for name in matches:
            if not name.startswith('_'):  # 排除私有方法
                keywords.add(name)

    except Exception as e:
        print(f"⚠️  无法加载 module_keywords.py: {e}")

    return keywords


def _scan_l3_calls(cases_dir: Path) -> set[str]:
    """扫描所有 case YAML，提取 l3_call 的 keyword 名称"""
    calls = set()

    if not cases_dir.exists():
        return calls

    for yaml_file in cases_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                continue

            steps = data.get('steps', [])
            if not isinstance(steps, list):
                continue

            for step in steps:
                if not isinstance(step, dict):
                    continue

                if step.get('keyword') == 'l3_call':
                    params = step.get('params', {})
                    if isinstance(params, dict):
                        kw_name = params.get('keyword')
                        if kw_name:
                            calls.add(kw_name)

        except Exception as e:
            print(f"⚠️  无法扫描 {yaml_file}: {e}")

    return calls


# ─── CLI 入口 ───

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python cross_refs.py <project_dir>")
        sys.exit(1)

    project_dir = sys.argv[1]
    result = validate_cross_refs(project_dir)
    errors = result.get("errors", [])

    if errors:
        print(f"\n❌ 端到端引用验证失败: {len(errors)} 个错误")
        sys.exit(1)
    else:
        print(f"\n✅ 端到端引用验证通过")
        sys.exit(0)
