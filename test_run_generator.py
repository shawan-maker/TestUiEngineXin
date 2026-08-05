#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 6: 实际运行 CaseGenerator，追踪 required_fields 中 7ddbe1 字段的完整链路
不猜测，只看真实数据
"""

import sys
import os
import json
import copy

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_DIR = os.path.join(os.path.dirname(__file__), 'examples', 'ecsCloud')
SKILL_DIR = os.path.join(os.path.dirname(__file__), '.claude', 'skills', 'generate-ui-test')
TOOLS_DIR = os.path.join(SKILL_DIR, 'tools')
sys.path.insert(0, TOOLS_DIR)


def run_test():
    # 1. 加载 Excel JSON
    excel_json_path = os.path.join(PROJECT_DIR, '_probe', 'excel_parsed.json')
    print(f"[1] 加载 Excel JSON: {excel_json_path}")
    with open(excel_json_path, encoding='utf-8') as f:
        excel_data = json.load(f)
    # Excel JSON 可能是 list 或 dict
    if isinstance(excel_data, list):
        cases = excel_data
    else:
        cases = excel_data.get('cases', [])
    print(f"    共 {len(cases)} 条用例")

    # 2. 加载 discovery
    disc_path = os.path.join(PROJECT_DIR, '_probe', 'discovery_estack.json')
    print(f"\n[2] 加载 discovery: {disc_path}")
    with open(disc_path, encoding='utf-8') as f:
        disc_data = json.load(f)
    lp = disc_data.get('list_page', {})
    print(f"    list_page: {len(lp.get('buttons', []))} buttons, "
          f"{len(lp.get('inputs', []))} inputs, "
          f"{len(lp.get('tabs', []))} tabs")

    # 3. 创建 Resolver
    print(f"\n[3] 创建 Resolver...")
    from generation.resolver import ElementResolver
    resolver = ElementResolver(disc_data, module='estack')
    print(f"    Resolver: {len(resolver.groups)} groups")

    # 4. 创建 CaseGenerator
    print(f"\n[4] 创建 CaseGenerator...")
    from generation.case_generator import CaseGenerator
    generator = CaseGenerator(resolver, module='estack')

    # 5. 处理 case01 (新增云主机)
    cases = excel_data.get('cases', [])
    case01 = None
    for c in cases:
        name = c.get('name', '') or c.get('case_name', '')
        if '新增' in name or '创建' in name:
            case01 = c
            break
    if not case01:
        case01 = cases[0]

    print(f"\n[5] 处理用例: {case01.get('name', case01.get('case_name', '?'))}")
    steps = case01.get('steps', [])
    print(f"    共 {len(steps)} 个步骤")

    # 找网络相关步骤
    print(f"\n    网络相关步骤:")
    for i, step in enumerate(steps):
        desc = step.get('description', '') or step.get('desc', '')
        if '网络' in desc:
            print(f"      Step {i}: {desc[:60]}")

    # 6. 运行 process_steps 生成 case steps
    print(f"\n[6] 运行 generator.process_steps()...")
    result_steps = generator.process_steps(steps, case_id='case01', seq=1)
    print(f"    生成 {len(result_steps)} 个步骤")

    # 7. 检查 required_fields
    print(f"\n[7] 检查 required_fields...")
    required_fields = generator.get_required_fields()
    print(f"    总共 {len(required_fields)} 个 required_fields")

    # 按 group 分组
    fields_by_group = {}
    for (group, field), info in sorted(required_fields.items()):
        fields_by_group.setdefault(group, {})[field] = info

    print(f"    共 {len(fields_by_group)} 个 groups:")
    for g in sorted(fields_by_group.keys()):
        fields = fields_by_group[g]
        print(f"      {g}: {len(fields)} fields")

    # 8. 检查 7ddbe1 字段
    print(f"\n[8] 检查 7ddbe1 (网络) 字段...")
    fields_7ddbe1 = {}
    for (group, field), info in sorted(required_fields.items()):
        if '7ddbe1' in field:
            fields_7ddbe1[(group, field)] = info

    if fields_7ddbe1:
        print(f"    找到 {len(fields_7ddbe1)} 个 7ddbe1 字段:")
        for (group, field), info in sorted(fields_7ddbe1.items()):
            locator = info.get('locator', '')
            label = info.get('label', '')
            comment = info.get('comment', '')
            print(f"\n    [{group}].[{field}]")
            print(f"      locator: {locator[:100]}{'...' if len(locator) > 100 else ''}")
            print(f"      label:   {label}")
            print(f"      comment: {comment}")
    else:
        print(f"    ❌ 未找到任何 7ddbe1 字段!")

        # 查找所有包含 el-select 或 _expand 的字段
        print(f"\n    所有 _expand 字段:")
        for (group, field), info in sorted(required_fields.items()):
            if '_expand' in field:
                locator = info.get('locator', '')
                print(f"      {group}.{field}: {locator[:80]}")

        print(f"\n    所有 el-select 相关字段:")
        for (group, field), info in sorted(required_fields.items()):
            locator = info.get('locator', '')
            if 'el-select' in locator or 'el-input__inner' in locator:
                print(f"      {group}.{field}: {locator[:80]}")

    # 9. 检查生成的 steps 中的网络步骤
    print(f"\n[9] 检查生成的 case steps 中的网络步骤...")
    for i, step in enumerate(result_steps):
        desc = step.get('desc', '')
        if '网络' in desc:
            locator = step.get('params', {}).get('locator', '')
            keyword = step.get('keyword', '')
            print(f"\n    Step {i}: {desc}")
            print(f"      keyword: {keyword}")
            print(f"      locator: {locator}")

    # 10. 模拟 PagesWriter 写入（只检查输入，不实际写入文件）
    print(f"\n[10] 检查 PagesWriter 写入输入...")
    from generation.pages_writer import PagesWriter
    writer = PagesWriter(resolver)

    # 模拟 write_pages_yaml 的 group 构建逻辑
    from collections import OrderedDict
    groups = OrderedDict()
    skip_count = 0
    skip_reasons = {}
    for (group, field), info in sorted(required_fields.items()):
        if group.endswith('_data') or group == 'common_elements':
            skip_count += 1
            skip_reasons.setdefault('ends_with_data_or_common', []).append(f"{group}.{field}")
            continue
        if group not in groups:
            groups[group] = OrderedDict()
        locator = info.get('locator', '')
        comment = info.get('label', '')
        groups[group][field] = (locator, comment)

    print(f"    跳过: {skip_count} 个字段 (ends_with_data_or_common)")
    print(f"    写入: {len(groups)} 个 groups")
    for g in sorted(groups.keys()):
        fields = groups[g]
        print(f"      {g}: {len(fields)} fields")
        # 检查 7ddbe1
        has_7ddbe1 = any('7ddbe1' in f for f in fields)
        if has_7ddbe1:
            print(f"        ✅ 包含 7ddbe1 字段!")
            for f in sorted(fields.keys()):
                if '7ddbe1' in f:
                    loc = fields[f][0]
                    print(f"        {f}: {loc[:80]}")

    # 11. 实际运行 PagesWriter 写入临时文件，检查结果
    print(f"\n[11] 实际运行 PagesWriter 写入临时文件...")
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as tmp:
        tmp_path = tmp.name

    try:
        writer.write_pages_yaml(required_fields, tmp_path, 'estack', '计算', append=False)

        with open(tmp_path, encoding='utf-8') as f:
            yaml_content = f.read()

        print(f"    写入文件: {tmp_path} ({len(yaml_content)} bytes)")

        # 检查 7ddbe1 是否在写入结果中
        if '7ddbe1' in yaml_content:
            print(f"    ✅ 7ddbe1 字段存在于写入结果中!")
            # 提取包含 7ddbe1 的行
            for line in yaml_content.split('\n'):
                if '7ddbe1' in line:
                    print(f"      {line.strip()}")
        else:
            print(f"    ❌ 7ddbe1 字段不存在于写入结果中!")

            # 检查写入的 groups
            import re
            written_groups = re.findall(r'^(\w[\w-]*):', yaml_content, re.MULTILINE)
            print(f"\n    写入的 groups: {written_groups}")

            # 检查写入的 fields
            written_fields = re.findall(r'^  (\w[\w-]*):', yaml_content, re.MULTILINE)
            print(f"    写入的 fields: {len(written_fields)} 个")

            # 检查 _expand 字段
            expand_fields = [f for f in written_fields if '_expand' in f]
            if expand_fields:
                print(f"\n    _expand 字段 ({len(expand_fields)}):")
                for f in expand_fields:
                    print(f"      {f}")
            else:
                print(f"\n    ❌ 没有任何 _expand 字段!")

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    print(f"\n{'=' * 80}")
    print("测试完成")
    print(f"{'=' * 80}")


if __name__ == '__main__':
    try:
        run_test()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
