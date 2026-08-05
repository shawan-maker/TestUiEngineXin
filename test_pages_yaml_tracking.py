#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本：追踪 pages YAML 在管线中的变化

在以下关键节点记录 pages YAML 的内容：
1. Phase 5 开始前
2. PagesWriter 写入后
3. 安全网过滤后
4. Phase 6 开始前
5. Phase 6 writeback 后

用法：
1. 先运行此脚本记录当前状态（snapshot）
2. 重新运行管线：python pipeline.py run --project examples/ecsCloud --from-phase phase_5
3. 再次运行此脚本对比差异
"""

import os
import sys
import yaml
import json
from datetime import datetime

PROJECT_DIR = r"D:\PyProject\TestUiEngineXin\examples\ecsCloud"
PAGES_FILE = os.path.join(PROJECT_DIR, "pages", "estack", "elements.yaml")
SNAPSHOT_DIR = os.path.join(PROJECT_DIR, "_probe", "yaml_snapshots")

def count_fields_in_yaml(filepath):
    """统计 YAML 文件中的 group 和 field 数量"""
    if not os.path.exists(filepath):
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        return {"total_groups": 0, "total_fields": 0, "groups": {}}

    groups = {}
    total_fields = 0

    for group_name, fields in data.items():
        if isinstance(fields, dict):
            field_count = len(fields)
            groups[group_name] = {
                "field_count": field_count,
                "fields": list(fields.keys())
            }
            total_fields += field_count
        else:
            groups[group_name] = {
                "field_count": 0,
                "fields": []
            }

    return {
        "total_groups": len(data),
        "total_fields": total_fields,
        "groups": groups
    }

def save_snapshot(stage_name):
    """保存当前 pages YAML 的快照"""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_file = os.path.join(SNAPSHOT_DIR, f"{stage_name}_{timestamp}.json")

    stats = count_fields_in_yaml(PAGES_FILE)

    if stats is None:
        print(f"[{stage_name}] pages YAML 不存在: {PAGES_FILE}")
        return

    # 保存详细统计
    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(f"\n[{stage_name}] {timestamp}")
    print(f"  文件: {PAGES_FILE}")
    print(f"  Groups: {stats['total_groups']}")
    print(f"  Fields: {stats['total_fields']}")

    for group_name, info in sorted(stats['groups'].items()):
        print(f"    - {group_name}: {info['field_count']} fields")

        # 特别关注 el-select 相关字段
        el_select_fields = [f for f in info['fields'] if any(k in f for k in ['_expand', '_select', '_editable'])]
        if el_select_fields:
            print(f"      el-select 字段: {', '.join(el_select_fields[:5])}")
            if len(el_select_fields) > 5:
                print(f"      ... 还有 {len(el_select_fields) - 5} 个")

    print(f"  快照已保存: {snapshot_file}")
    return snapshot_file

def compare_snapshots(file1, file2):
    """对比两个快照的差异"""
    with open(file1, 'r', encoding='utf-8') as f:
        snap1 = json.load(f)
    with open(file2, 'r', encoding='utf-8') as f:
        snap2 = json.load(f)

    print(f"\n对比: {os.path.basename(file1)} vs {os.path.basename(file2)}")
    print(f"  Groups: {snap1['total_groups']} → {snap2['total_groups']}")
    print(f"  Fields: {snap1['total_fields']} → {snap2['total_fields']}")

    # 找出新增和删除的 groups
    groups1 = set(snap1['groups'].keys())
    groups2 = set(snap2['groups'].keys())

    added_groups = groups2 - groups1
    removed_groups = groups1 - groups2

    if added_groups:
        print(f"\n  新增 groups: {', '.join(added_groups)}")
    if removed_groups:
        print(f"\n  删除 groups: {', '.join(removed_groups)}")

    # 对比每个 group 的字段变化
    for group in groups1 & groups2:
        fields1 = set(snap1['groups'][group]['fields'])
        fields2 = set(snap2['groups'][group]['fields'])

        added = fields2 - fields1
        removed = fields1 - fields2

        if added or removed:
            print(f"\n  {group}:")
            print(f"    字段数: {len(fields1)} → {len(fields2)}")
            if added:
                print(f"    新增: {', '.join(list(added)[:10])}")
            if removed:
                print(f"    删除: {', '.join(list(removed)[:10])}")

if __name__ == "__main__":
    print("=" * 70)
    print("Pages YAML 变化追踪工具")
    print("=" * 70)

    if len(sys.argv) < 2:
        print("\n用法:")
        print("  python test_pages_yaml_tracking.py snapshot <stage_name>")
        print("  python test_pages_yaml_tracking.py compare <file1> <file2>")
        print("\n示例:")
        print("  python test_pages_yaml_tracking.py snapshot before_phase5")
        print("  # ... 运行管线 ...")
        print("  python test_pages_yaml_tracking.py snapshot after_phase5")
        print("  python test_pages_yaml_tracking.py compare before_phase5_xxx.json after_phase5_xxx.json")
        sys.exit(1)

    action = sys.argv[1]

    if action == "snapshot":
        if len(sys.argv) < 3:
            print("错误: 请指定 stage_name")
            sys.exit(1)
        stage_name = sys.argv[2]
        save_snapshot(stage_name)

    elif action == "compare":
        if len(sys.argv) < 4:
            print("错误: 请指定两个快照文件")
            sys.exit(1)
        file1 = sys.argv[2]
        file2 = sys.argv[3]

        # 如果不是完整路径，从 SNAPSHOT_DIR 查找
        if not os.path.isabs(file1):
            file1 = os.path.join(SNAPSHOT_DIR, file1)
        if not os.path.isabs(file2):
            file2 = os.path.join(SNAPSHOT_DIR, file2)

        compare_snapshots(file1, file2)

    else:
        print(f"未知操作: {action}")
        sys.exit(1)
