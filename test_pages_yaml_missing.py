#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 3: 诊断 pages YAML 中是否缺失 network 相关的 el-select 字段

问题假设:
- 原始 locator 引用 ${estack_vm_newpage_listpage_elements.field_7ddbe1_expand}
- 但 pages YAML 中该字段不存在 → resolve_locator 返回空字符串
- 空字符串 → Original locator skipped (len=0)
- 只有 KB 候选可用 → KB 候选无 [nth] → 第1个下拉框被点两次
"""

import sys
import os
import yaml

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_DIR = os.path.join(os.path.dirname(__file__), 'examples', 'ecsCloud')


def load_all_pages_yaml():
    """加载所有 pages YAML，返回 {group_name: {field_name: locator}}"""
    pages_dir = os.path.join(PROJECT_DIR, 'pages')
    all_pages = {}
    source_files = {}

    for root, dirs, files in os.walk(pages_dir):
        for f in files:
            if f.endswith('.yaml') or f.endswith('.yml'):
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, encoding='utf-8') as fh:
                        data = yaml.safe_load(fh)
                    if isinstance(data, dict):
                        for group_name, fields in data.items():
                            if isinstance(fields, dict):
                                all_pages[group_name] = fields
                                source_files[group_name] = filepath
                except Exception as e:
                    print(f"  [WARN] 无法加载 {filepath}: {e}")

    return all_pages, source_files


def load_case_yaml():
    """加载 case YAML，提取所有 locator 引用"""
    cases_dir = os.path.join(PROJECT_DIR, 'cases')
    all_refs = []

    for root, dirs, files in os.walk(cases_dir):
        for f in files:
            if f.endswith('.yaml') or f.endswith('.yml'):
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, encoding='utf-8') as fh:
                        content = fh.read()
                    # 提取所有 ${group.field} 引用
                    import re
                    refs = re.findall(r'\$\{([^}]+)\}', content)
                    for ref in refs:
                        all_refs.append((ref, filepath))
                except Exception:
                    pass

    return all_refs


def main():
    print("=" * 80)
    print("诊断: pages YAML 中 network 相关字段是否存在")
    print("=" * 80)

    # 1. 加载所有 pages YAML
    print("\n[1] 加载 pages YAML...")
    all_pages, source_files = load_all_pages_yaml()
    print(f"  共加载 {len(all_pages)} 个 group:")
    for group_name in sorted(all_pages.keys()):
        field_count = len(all_pages[group_name])
        src = source_files.get(group_name, '?')
        print(f"    - {group_name} ({field_count} fields) [{os.path.basename(src)}]")

    # 2. 检查 network 相关字段
    print("\n[2] 检查 network (7ddbe1) 相关字段...")
    target_group = 'estack_vm_newpage_listpage_elements'

    if target_group in all_pages:
        fields = all_pages[target_group]
        print(f"  Group '{target_group}' 存在，共 {len(fields)} 个字段:")

        # 查找 7ddbe1 字段
        network_fields = {k: v for k, v in fields.items() if '7ddbe1' in k}
        if network_fields:
            print(f"\n  找到 {len(network_fields)} 个 network (7ddbe1) 字段:")
            for fname, fval in sorted(network_fields.items()):
                print(f"    {fname}: {fval}")
        else:
            print(f"\n  ❌ 未找到任何 7ddbe1 字段!")
            print(f"  该 group 的所有字段:")
            for fname, fval in sorted(fields.items()):
                print(f"    {fname}: {fval[:80] if isinstance(fval, str) else fval}")
    else:
        print(f"  ❌ Group '{target_group}' 不存在!")
        print(f"  可用的 groups: {sorted(all_pages.keys())}")

    # 3. 加载 case YAML 引用
    print("\n[3] 检查 case YAML 中的 locator 引用...")
    all_refs = load_case_yaml()

    # 过滤出 7ddbe1 相关引用
    network_refs = [(ref, fp) for ref, fp in all_refs if '7ddbe1' in ref]
    print(f"  找到 {len(network_refs)} 个 network (7ddbe1) 引用:")
    for ref, fp in network_refs:
        print(f"    ${{{ref}}} [{os.path.basename(fp)}]")

    # 4. 交叉验证: case 引用 vs pages 定义
    print("\n[4] 交叉验证: case 引用 vs pages YAML 定义...")
    missing_refs = []
    for ref, fp in network_refs:
        parts = ref.split('.', 1)
        if len(parts) == 2:
            group, field = parts
            if group in all_pages:
                if field in all_pages[group]:
                    locator = all_pages[group][field]
                    print(f"  ✅ ${{{ref}}} → {locator[:80] if isinstance(locator, str) else locator}")
                else:
                    print(f"  ❌ ${{{ref}}} → 字段 '{field}' 不存在于 group '{group}'")
                    missing_refs.append(ref)
            else:
                print(f"  ❌ ${{{ref}}} → group '{group}' 不存在")
                missing_refs.append(ref)

    # 5. 总结
    print("\n" + "=" * 80)
    print("诊断结论")
    print("=" * 80)

    if missing_refs:
        print(f"\n❌ 发现 {len(missing_refs)} 个缺失引用:")
        for ref in missing_refs:
            print(f"  - ${{{ref}}}")
        print(f"""
根因链路:
1. case_generator.py 通过 _track_field() 注册了这些字段
2. PagesWriter 应该把它们写入 pages YAML
3. 但 pages YAML 中找不到这些字段
4. Phase 6 resolve_locator() 返回空字符串
5. 原始 locator 被跳过 (len=0)
6. 只剩 KB 候选（无 [nth] 索引）
7. 第1个和第2个下拉框的 KB 候选相同 → 第1个被点两次

下一步排查:
- 检查 _track_field 是否正确注册了字段
- 检查 PagesWriter 是否正确写入了 pages YAML
- 检查 pages YAML 文件是否被后续阶段覆盖/清理
""")
    else:
        print(f"\n✅ 所有 network 引用都有对应的 pages YAML 定义")
        print(f"问题可能不在 pages YAML 缺失，需要进一步排查 resolve_locator 逻辑")

    # 6. 额外检查: 所有 pages YAML 文件内容
    print("\n" + "=" * 80)
    print("附录: pages 目录下所有 YAML 文件")
    print("=" * 80)
    pages_dir = os.path.join(PROJECT_DIR, 'pages')
    for root, dirs, files in os.walk(pages_dir):
        for f in sorted(files):
            if f.endswith('.yaml') or f.endswith('.yml'):
                filepath = os.path.join(root, f)
                relpath = os.path.relpath(filepath, PROJECT_DIR)
                size = os.path.getsize(filepath)
                print(f"\n  {relpath} ({size} bytes)")
                try:
                    with open(filepath, encoding='utf-8') as fh:
                        data = yaml.safe_load(fh)
                    if isinstance(data, dict):
                        for gname, gfields in data.items():
                            if isinstance(gfields, dict):
                                print(f"    group: {gname} ({len(gfields)} fields)")
                                # 检查是否有 _expand 字段
                                expand_fields = [k for k in gfields if '_expand' in k]
                                if expand_fields:
                                    for ef in expand_fields:
                                        print(f"      {ef}: {gfields[ef][:80]}")
                            else:
                                print(f"    group: {gname} (not dict: {type(gfields).__name__})")
                except Exception as e:
                    print(f"    [ERROR] {e}")


if __name__ == '__main__':
    main()
