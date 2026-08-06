#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本: 诊断 field_7ddbe1 字段缺失问题

检查:
1. case YAML 中引用了哪些 7ddbe1 字段
2. pages YAML 中是否存在这些字段
3. 如果缺失,追踪原因
"""

import os
import yaml
import re
import sys
import io

# 修复 Windows 编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def load_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)

def extract_refs(obj, refs=None):
    """递归提取所有 ${group.field} 引用"""
    if refs is None:
        refs = set()

    if isinstance(obj, str):
        # 匹配 ${group.field}
        matches = re.findall(r'\$\{([^}]+)\}', obj)
        refs.update(matches)
    elif isinstance(obj, dict):
        for v in obj.values():
            extract_refs(v, refs)
    elif isinstance(obj, list):
        for item in obj:
            extract_refs(item, refs)

    return refs

def main():
    print("=" * 80)
    print("调试: field_7ddbe1 字段缺失问题")
    print("=" * 80)

    # 1. 加载 case YAML
    case_path = r"D:\PyProject\TestUiEngineXin\examples\ecsCloud\cases\estack\01_计算-新增云主机.yaml"
    print(f"\n[1] 加载 case: {case_path}")
    case_data = load_yaml(case_path)

    # case YAML 可能是 list (多 case) 或 dict (单 case, steps 在顶层)
    if isinstance(case_data, list):
        cases = case_data
    elif isinstance(case_data, dict):
        if 'cases' in case_data:
            cases = case_data['cases']
        elif 'steps' in case_data:
            cases = [case_data]  # 单 case, 包装成 list
        else:
            cases = [case_data]
    else:
        cases = []
    print(f"    用例数: {len(cases)}")

    if not cases:
        print("    [ERROR] 没有找到用例!")
        return

    # 2. 提取所有引用
    print(f"\n[2] 提取所有 ${group.field} 引用...")
    all_refs = extract_refs(case_data)
    print(f"    总引用数: {len(all_refs)}")

    # 过滤出 7ddbe1 相关
    refs_7ddbe1 = [r for r in sorted(all_refs) if '7ddbe1' in r]
    print(f"    7ddbe1 引用数: {len(refs_7ddbe1)}")

    if refs_7ddbe1:
        print("\n    7ddbe1 引用列表:")
        for ref in refs_7ddbe1:
            print(f"      - {ref}")
    else:
        print("\n    [WARN] 没有找到 7ddbe1 引用!")
        # 检查是否有其他 el_select 相关引用
        refs_expand = [r for r in sorted(all_refs) if '_expand' in r]
        print(f"\n    _expand 引用数: {len(refs_expand)}")
        if refs_expand:
            print("\n    _expand 引用列表:")
            for ref in refs_expand:
                print(f"      - {ref}")

    # 3. 加载 pages YAML
    pages_path = r"D:\PyProject\TestUiEngineXin\examples\ecsCloud\pages\estack\elements.yaml"
    print(f"\n[3] 加载 pages: {pages_path}")

    if not os.path.exists(pages_path):
        print(f"    [ERROR] 文件不存在!")
        return

    pages_data = load_yaml(pages_path)

    # 4. 列出所有 groups
    print(f"\n[4] Pages YAML 中的 groups:")
    for group_name in sorted(pages_data.keys()):
        fields = pages_data[group_name]
        if isinstance(fields, dict):
            print(f"    {group_name}: {len(fields)} 字段")
        else:
            print(f"    {group_name}: (非 dict)")

    # 5. 检查 estack_vm_newpage_listpage_elements
    target_group = 'estack_vm_newpage_listpage_elements'
    print(f"\n[5] 检查目标 group: {target_group}")

    if target_group not in pages_data:
        print(f"    [ERROR] group 不存在!")
        print(f"    可用 groups: {list(pages_data.keys())}")
    else:
        group_fields = pages_data[target_group]
        print(f"    存在, {len(group_fields)} 字段")

        # 列出所有字段
        print(f"\n    字段列表:")
        for field_name in sorted(group_fields.keys()):
            locator = group_fields[field_name]
            if isinstance(locator, str):
                print(f"      {field_name}")
                print(f"        -> {locator[:80]}...")

        # 检查 7ddbe1 字段
        fields_7ddbe1 = {k: v for k, v in group_fields.items() if '7ddbe1' in k}
        print(f"\n    7ddbe1 字段数: {len(fields_7ddbe1)}")

        if fields_7ddbe1:
            print(f"\n    7ddbe1 字段详情:")
            for fname, fval in sorted(fields_7ddbe1.items()):
                print(f"      {fname}")
                print(f"        -> {fval}")
        else:
            print(f"\n    [ERROR] 没有找到 7ddbe1 字段!")

    # 6. 交叉检查: case 引用 vs pages 定义
    print(f"\n[6] 交叉检查: case 引用 vs pages 定义")

    missing_refs = []
    for ref in sorted(all_refs):
        if '.' not in ref:
            continue

        group, field = ref.split('.', 1)

        if group not in pages_data:
            missing_refs.append((ref, 'group 不存在'))
        else:
            group_fields = pages_data[group]
            if isinstance(group_fields, dict) and field not in group_fields:
                missing_refs.append((ref, '字段不存在'))

    if missing_refs:
        print(f"    [ERROR] 发现 {len(missing_refs)} 个缺失引用:")
        for ref, reason in missing_refs[:10]:  # 只显示前10个
            print(f"      - {ref} ({reason})")

        if len(missing_refs) > 10:
            print(f"      ... 还有 {len(missing_refs) - 10} 个")

        # 特别关注 7ddbe1
        missing_7ddbe1 = [(r, reason) for r, reason in missing_refs if '7ddbe1' in r]
        if missing_7ddbe1:
            print(f"\n    7ddbe1 缺失引用 ({len(missing_7ddbe1)} 个):")
            for ref, reason in missing_7ddbe1:
                print(f"      - {ref} ({reason})")
    else:
        print(f"    [OK] 所有引用都有定义")

    # 7. 检查 Phase 5 日志
    print(f"\n[7] 检查 Phase 5 日志...")
    log_path = r"D:\PyProject\TestUiEngineXin\examples\ecsCloud\_probe\phase_5_tool.log"

    if os.path.exists(log_path):
        with open(log_path, encoding='utf-8', errors='ignore') as f:
            log_content = f.read()

        # 搜索 7ddbe1
        if '7ddbe1' in log_content:
            print(f"    [OK] 日志中包含 7ddbe1")
            # 提取相关行
            lines = log_content.split('\n')
            relevant_lines = [l for l in lines if '7ddbe1' in l]
            print(f"    相关行数: {len(relevant_lines)}")
            if relevant_lines:
                print(f"\n    前5行:")
                for line in relevant_lines[:5]:
                    print(f"      {line.strip()}")
        else:
            print(f"    [WARN] 日志中不包含 7ddbe1")

        # 搜索 PagesWriter
        if 'PagesWriter' in log_content:
            print(f"\n    [OK] 日志中包含 PagesWriter")
        else:
            print(f"\n    [WARN] 日志中不包含 PagesWriter")
    else:
        print(f"    [WARN] 日志文件不存在")

    # 8. 总结
    print(f"\n" + "=" * 80)
    print("总结")
    print("=" * 80)

    if missing_refs:
        print(f"\n问题: {len(missing_refs)} 个字段在 pages YAML 中缺失")
        print(f"\n可能原因:")
        print(f"  1. PagesWriter 没有写入这些字段")
        print(f"  2. 安全网过滤器删除了这些字段")
        print(f"  3. case_generator 没有注册这些字段到 required_fields")
        print(f"\n建议:")
        print(f"  1. 检查 Phase 5 日志,看 generator.required_fields 是否包含这些字段")
        print(f"  2. 重新运行 Phase 5,添加调试输出")
        print(f"  3. 检查 _filter_single_pages_yaml 是否误删了字段")
    else:
        print(f"\n[OK] 所有字段都存在")

if __name__ == '__main__':
    main()
