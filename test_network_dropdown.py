#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断: 网络下拉框为什么第二个没有被正确点击"""
import os, sys, re, yaml, io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT = r"D:\PyProject\TestUiEngineXin\examples\ecsCloud"

def main():
    print("=" * 70)
    print("诊断: 网络下拉框问题")
    print("=" * 70)

    # 1. 读 case YAML
    case_path = os.path.join(PROJECT, "cases", "estack", "01_计算-新增云主机.yaml")
    with open(case_path, encoding='utf-8') as f:
        case_text = f.read()

    # 提取所有 7ddbe1 相关的引用
    refs = re.findall(r'\$\{([^}]*7ddbe1[^}]*)\}', case_text)
    print(f"\n[1] Case YAML 中 7ddbe1 引用 ({len(refs)} 个):")
    for r in sorted(set(refs)):
        print(f"  - {r}")

    # 2. 读 pages YAML
    pages_path = os.path.join(PROJECT, "pages", "estack", "elements.yaml")
    with open(pages_path, encoding='utf-8') as f:
        pages = yaml.safe_load(f)

    print(f"\n[2] Pages YAML groups:")
    for g in sorted(pages.keys()):
        fields = pages[g]
        if isinstance(fields, dict):
            count = len(fields)
            has_7ddbe1 = any('7ddbe1' in k for k in fields)
            marker = " <-- 7ddbe1" if has_7ddbe1 else ""
            print(f"  - {g}: {count} fields{marker}")

    # 3. 检查目标 group
    target = 'estack_vm_newpage_listpage_elements'
    print(f"\n[3] 检查 group: {target}")

    if target not in pages:
        print(f"  ERROR: group 不存在!")
        print(f"  这是问题的根因: pages YAML 没有写入这个 group")
    else:
        fields = pages[target]
        f7 = {k: v for k, v in fields.items() if '7ddbe1' in k}
        print(f"  7ddbe1 字段 ({len(f7)} 个):")
        for k, v in sorted(f7.items()):
            print(f"    {k}: {v[:80] if len(str(v)) > 80 else v}")

    # 4. 交叉检查
    print(f"\n[4] 交叉检查: case 引用 vs pages 定义")
    all_refs = set(re.findall(r'\$\{([^}]+)\}', case_text))
    missing = []
    for ref in sorted(all_refs):
        if '.' not in ref:
            continue
        grp, fld = ref.split('.', 1)
        if grp in ('estack_data',):
            continue  # data 引用跳过
        if grp not in pages:
            missing.append((ref, 'group missing'))
        elif isinstance(pages[grp], dict) and fld not in pages[grp]:
            missing.append((ref, 'field missing'))

    if missing:
        print(f"  ERROR: {len(missing)} 个引用缺失:")
        for ref, reason in missing:
            print(f"    - {ref} ({reason})")
    else:
        print(f"  OK: 所有引用都有定义")

    # 5. 检查 KB locators 是否有 [nth]
    print(f"\n[5] KB locators 是否包含 [nth]")
    sys.path.insert(0, r"D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools")
    from verification.data_layer import _get_kb_locators

    kb = _get_kb_locators('el-select', '网络')
    print(f"  KB 生成 {len(kb)} 个 locator:")
    for i, loc in enumerate(kb):
        has_nth = re.search(r'\]\)\[(\d+)\]', loc)
        nth_str = f"[{has_nth.group(1)}]" if has_nth else "无 [nth]"
        print(f"    [{i}] {nth_str} - {loc[:80]}")

    # 6. 总结
    print(f"\n{'=' * 70}")
    print("结论:")
    print(f"{'=' * 70}")
    if target not in pages:
        print(f"  1. pages YAML 缺少 {target} group (未写入)")
        print(f"  2. Phase 6 无法解析原始 locator -> 空字符串")
        print(f"  3. 只能使用 KB 候选 (无 [nth])")
        print(f"  4. 第1/2个下拉框的 KB 候选相同 -> 都点第1个")
    else:
        print(f"  pages YAML 存在, 问题在其他地方")

if __name__ == '__main__':
    main()
