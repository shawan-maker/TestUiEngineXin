#!/usr/bin/env python3
"""
调试脚本：为什么 field_7ddbe1_2_expand 在 pages YAML 中缺失？

直接检查：
1. case YAML 中引用了哪些 field_7ddbe1 字段
2. pages YAML 中是否存在这些字段
3. 如果缺失，说明 PagesWriter 没有写入
"""

import os
import yaml

PROJECT = r"D:\PyProject\TestUiEngineXin\examples\ecsCloud"

def load_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)

def main():
    print("=" * 80)
    print("调试：field_7ddbe1 字段缺失问题")
    print("=" * 80)

    # 1. 加载 case YAML
    case_path = os.path.join(PROJECT, "cases", "estack", "01_计算-新增云主机.yaml")
    print(f"\n[1] 加载 case: {case_path}")
    case_data = load_yaml(case_path)
    print(f"    用例数: {len(case_data.get('cases', []))}")

    # 2. 提取所有 locator 引用
    print(f"\n[2] 提取 locator 引用...")
    refs_by_field = {}

    for case in case_data.get('cases', []):
        for step in case.get('steps', []):
            params = step.get('params', {})
            locator = params.get('locator', '')
            desc = step.get('desc', '')

            if '${' in locator:
                # 提取 ${group.field}
                import re
                matches = re.findall(r'\$\{([^}]+)\}', locator)
                for ref in matches:
                    if '7ddbe1' in ref:
                        refs_by_field[ref] = desc

    print(f"    找到 {len(refs_by_field)} 个 7ddbe1 引用:")
    for ref in sorted(refs_by_field.keys()):
        desc = refs_by_field[ref][:60]
        print(f"      {ref}")
        print(f"        → {desc}")

    # 3. 加载 pages YAML
    pages_path = os.path.join(PROJECT, "pages", "estack", "elements.yaml")
    print(f"\n[3] 加载 pages: {pages_path}")
    pages_data = load_yaml(pages_path)

    # 4. 检查 estack_vm_newpage_listpage_elements group
    group_name = 'estack_vm_newpage_listpage_elements'
    print(f"\n[4] 检查 group: {group_name}")

    if group_name not in pages_data:
        print(f"    ❌ group 不存在!")
        print(f"    可用的 groups: {list(pages_data.keys())}")
        return

    group_fields = pages_data[group_name]
    print(f"    存在 {len(group_fields)} 个字段:")
    for field_name in sorted(group_fields.keys()):
        locator = group_fields[field_name]
        print(f"      {field_name}")
        print(f"        → {locator[:80]}...")

    # 5. 检查缺失的字段
    print(f"\n[5] 检查缺失的 7ddbe1 字段...")
    missing = []

    for ref in sorted(refs_by_field.keys()):
        if '.' not in ref:
            continue

        group, field = ref.split('.', 1)

        if group == group_name:
            if field not in group_fields:
                missing.append(field)
                print(f"    ❌ 缺失: {field}")
                print(f"       引用: {refs_by_field[ref]}")

    if not missing:
        print(f"    ✅ 所有 7ddbe1 字段都存在")
        return

    # 6. 检查 _expand 字段
    print(f"\n[6] 检查 _expand 字段...")
    expand_fields = [f for f in group_fields.keys() if f.endswith('_expand')]
    print(f"    pages YAML 中有 {len(expand_fields)} 个 _expand 字段:")
    for f in sorted(expand_fields):
        print(f"      {f}")

    missing_expand = [f for f in missing if f.endswith('_expand')]
    if missing_expand:
        print(f"\n    ❌ 缺失的 _expand 字段:")
        for f in missing_expand:
            print(f"      {f}")

    # 7. 总结
    print(f"\n" + "=" * 80)
    print("总结")
    print("=" * 80)
    print(f"""
问题确认：
  - case YAML 引用了 {len(missing)} 个 7ddbe1 字段
  - pages YAML 中这些字段不存在
  - PagesWriter 没有写入这些字段

下一步：
  - 检查 Phase 5 日志，看 generator.required_fields 是否包含这些字段
  - 如果 required_fields 有但 pages YAML 没有，说明 PagesWriter 写入失败
  - 如果 required_fields 没有，说明 generator 没有注册这些字段

建议：
  - 查看 _probe/phase_5_tool.log，搜索 '7ddbe1'
  - 或者直接重新运行 Phase 5，观察输出
""")

if __name__ == '__main__':
    main()
