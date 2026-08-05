#!/usr/bin/env python3
"""
测试脚本：重新运行 Phase 5 并收集追踪日志

此脚本会：
1. 清理现有的 pages YAML
2. 重新运行 Phase 5 (generate_from_excel.py)
3. 收集所有 [TRACE] 日志
4. 对比运行前后的 pages YAML 内容

用法:
    python test_rerun_phase5_with_trace.py
"""

import os
import sys
import io

# Windows 控制台 UTF-8 修复
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import subprocess
import json
from pathlib import Path
from datetime import datetime

def get_pages_yaml_stats(yaml_path):
    """读取 pages YAML 并统计 groups 和 fields"""
    if not os.path.exists(yaml_path):
        return {"exists": False, "groups": {}, "total_fields": 0}

    try:
        import yaml
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            return {"exists": True, "groups": {}, "total_fields": 0}

        groups = {}
        total_fields = 0
        for group_name, fields in data.items():
            if isinstance(fields, dict):
                groups[group_name] = list(fields.keys())
                total_fields += len(fields)
            else:
                groups[group_name] = []

        return {
            "exists": True,
            "groups": groups,
            "total_fields": total_fields,
            "total_groups": len(groups)
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}

def main():
    project_dir = Path(r"D:\PyProject\TestUiEngineXin\examples\ecsCloud")
    skill_dir = Path(r"D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools")

    # Phase 5 相关文件
    excel_json = project_dir / "_probe" / "excel_parsed.json"
    probe_dir = project_dir / "_probe"  # discovery-dir
    pages_yaml = project_dir / "pages" / "estack" / "elements.yaml"

    print("=" * 80)
    print("Phase 5 追踪日志测试")
    print("=" * 80)
    print()

    # 检查必要文件
    print("[检查] 验证输入文件...")
    if not excel_json.exists():
        print(f"  X 缺少 Excel JSON: {excel_json}")
        return 1
    if not probe_dir.exists():
        print(f"  X 缺少 Discovery 目录: {probe_dir}")
        return 1
    print(f"  OK Excel JSON: {excel_json}")
    print(f"  OK Discovery 目录: {probe_dir}")
    print()

    # 记录运行前状态
    print("[阶段1] 记录运行前状态...")
    before_stats = get_pages_yaml_stats(pages_yaml)
    print(f"  Pages YAML: {pages_yaml}")
    print(f"  运行前: {before_stats.get('total_groups', 0)} groups, {before_stats.get('total_fields', 0)} fields")
    if before_stats.get('groups'):
        for group, fields in before_stats['groups'].items():
            print(f"    - {group}: {len(fields)} fields")
    print()

    # 备份当前 pages YAML
    if pages_yaml.exists():
        backup_path = pages_yaml.with_suffix(f".yaml.backup.{datetime.now().strftime('%H%M%S')}")
        import shutil
        shutil.copy2(pages_yaml, backup_path)
        print(f"  备份: {backup_path}")
        print()

    # 运行 Phase 5
    print("[阶段2] 运行 Phase 5 (generate_from_excel.py)...")
    print()

    cmd = [
        sys.executable,
        str(skill_dir / "generation" / "generate_from_excel.py"),
        str(excel_json),
        "--discovery-dir", str(probe_dir),
        "--output-dir", str(project_dir)
    ]

    print(f"  命令: {' '.join(cmd)}")
    print()
    print("-" * 80)

    # 运行并捕获输出
    result = subprocess.run(
        cmd,
        cwd=str(skill_dir),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )

    # 打印所有输出
    stdout_text = result.stdout or ""
    stderr_text = result.stderr or ""

    if stdout_text:
        print(stdout_text)
    if stderr_text:
        print("STDERR:")
        print(stderr_text)

    print("-" * 80)
    print()

    # 提取 [TRACE] 日志
    trace_lines = []
    for line in stdout_text.split('\n'):
        if '[TRACE]' in line:
            trace_lines.append(line)

    print(f"[阶段3] 提取 [TRACE] 日志 ({len(trace_lines)} 行)")
    for line in trace_lines:
        print(f"  {line}")
    print()

    # 记录运行后状态
    print("[阶段4] 记录运行后状态...")
    after_stats = get_pages_yaml_stats(pages_yaml)
    print(f"  Pages YAML: {pages_yaml}")
    print(f"  运行后: {after_stats.get('total_groups', 0)} groups, {after_stats.get('total_fields', 0)} fields")
    if after_stats.get('groups'):
        for group, fields in after_stats['groups'].items():
            print(f"    - {group}: {len(fields)} fields")
    print()

    # 对比结果
    print("[阶段5] 对比分析...")
    before_count = before_stats.get('total_fields', 0)
    after_count = after_stats.get('total_fields', 0)
    print(f"  字段数变化: {before_count} → {after_count}")

    if after_count > before_count:
        print(f"  ✓ 新增 {after_count - before_count} 个字段")
    elif after_count < before_count:
        print(f"  ✗ 丢失 {before_count - after_count} 个字段")
    else:
        print(f"  = 字段数未变化")
    print()

    # 检查特定字段
    print("[阶段6] 检查 el-select 相关字段...")
    el_select_fields = []
    if after_stats.get('groups'):
        for group, fields in after_stats['groups'].items():
            for field in fields:
                if any(kw in field for kw in ['_expand', '_select', '_editable', '_first_option']):
                    el_select_fields.append(f"{group}.{field}")

    if el_select_fields:
        print(f"  找到 {len(el_select_fields)} 个 el-select 相关字段:")
        for field in el_select_fields[:10]:
            print(f"    - {field}")
        if len(el_select_fields) > 10:
            print(f"    ... 还有 {len(el_select_fields) - 10} 个")
    else:
        print(f"  ✗ 未找到任何 el-select 相关字段")
    print()

    # 返回状态码
    if result.returncode != 0:
        print(f"[结果] Phase 5 运行失败 (exit code: {result.returncode})")
        return result.returncode
    elif after_count == 0:
        print(f"[结果] Phase 5 运行成功，但 pages YAML 为空")
        return 1
    else:
        print(f"[结果] Phase 5 运行成功，pages YAML 包含 {after_count} 个字段")
        return 0

if __name__ == "__main__":
    sys.exit(main())
