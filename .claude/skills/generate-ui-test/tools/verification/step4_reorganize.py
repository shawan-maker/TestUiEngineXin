#!/usr/bin/env python3
"""
step4_reorganize.py - Phase 6 后处理 Step ④: Pages YAML 重组与内联 Locator 注册

在 Phase 6 现有回写之后执行，将 pages YAML 从容器分组重组为 case 分组，
并将 case YAML 中的内联 xpath 注册到 pages YAML。

设计原则：
- 只加不改：不改 Phase 5 生成逻辑，不改 Phase 6 现有验证逻辑
- 追加执行：Step ④ 在现有回写之后执行
- 幂等安全：重跑 pipeline 不会重复处理

执行流程：
  4a. 重组：容器分组 → case 分组
  4b. 注册：内联 xpath → pages YAML
  4c. 映射：更新 case YAML 引用
"""

import os
import re
import sys

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Ensure tools/ is on sys.path
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from generation.case_utils import walk_all_steps, extract_pages_ref
from generation.pages_writer import build_ref_mapping
from verification.data_layer import load_cases, load_pages
from core.yaml_utils import escape_yaml_scalar as _yaml_scalar


def post_process_step4(project_dir, module_slug):
    """Phase 6 后处理 Step ④: 重组 pages YAML 并注册内联 locator。

    Args:
        project_dir: 项目根目录
        module_slug: 模块英文slug（如 'project'）
    """
    print(f"\n[Step ④] 开始 pages 重组与内联注册 (module={module_slug})")

    # Step 4a: 构建内存模型（容器分组 → case 分组），不写入文件
    model = _reorganize_pages_by_case(project_dir, module_slug)
    if model is None:
        print(f"[Step ④] 跳过：无 case 或 pages")
        return

    # Step 4b: 注册内联 locator 到内存模型 + 写回 case YAML
    _register_inline_locators(project_dir, module_slug, model)

    # Step 4c: 统一写入 pages YAML（4a 重组 + 4b 内联合并）
    _write_pages_yaml(project_dir, module_slug, model)

    # Step 4d: 更新 case YAML 中的引用（4a 的映射）
    _update_case_references(project_dir, module_slug, model['ref_mapping'])

    print(f"[Step ④] 完成 pages 重组和内联注册")


def _reorganize_pages_by_case(project_dir, module_slug):
    """Step 4a: 重组 pages YAML（容器分组 → case 分组）— 仅构建内存模型。

    Returns:
        dict: model = {
            'case_groups': {case_id: {field_name: xpath}},
            'shared_group': {field_name: xpath},
            'field_order': {group_name: {field_name: step_index}},
            'ref_mapping': {'${old_group.field}': '${new_group.field}'},
            'module_slug': str,
        } or None if no data.
    """
    # 1. 加载所有 case 和 pages
    cases = load_cases(project_dir, module=module_slug)
    pages = load_pages(project_dir, module=module_slug)

    if not cases or not pages:
        return None

    # 2. 扫描所有 case → 构建 field → case_id 映射 + 记录步骤顺序
    field_usage = {}   # {'group.field': [case_id1, case_id2, ...]}
    field_order = {}   # {case_id: {field_name: step_index}} 用于按步骤排序
    shared_field_order = {}  # {field_name: min_step_index} 共享字段的最小步骤序号

    for case in cases:
        case_id = case.get('id', '')
        if not case_id:
            continue
        steps = case.get('steps', [])
        case_field_order = {}
        for step_idx, step in enumerate(walk_all_steps(steps)):
            locator = step.get('params', {}).get('locator', '')
            ref_tuple = extract_pages_ref(locator)
            if ref_tuple:
                old_group, old_field = ref_tuple
                old_ref = f"{old_group}.{old_field}"
                field_usage.setdefault(old_ref, []).append(case_id)
                # 记录首次出现位置
                if old_field not in case_field_order:
                    case_field_order[old_field] = step_idx
        field_order[case_id] = case_field_order

    # 3. 按使用情况分组（保留原始 field name，含 hash 后缀）
    case_groups = {}   # {case_id: {field_name: xpath}}
    shared_group = {}  # {field_name: xpath}
    shared_group_name = f'{module_slug}_page'

    # 反向索引：old_ref → xpath
    field_xpath_map = {}
    for group_name, fields in pages.items():
        for field_name, xpath in fields.items():
            field_xpath_map[f"{group_name}.{field_name}"] = xpath

    for old_ref, case_ids in field_usage.items():
        parts = old_ref.split('.', 1)
        if len(parts) != 2:
            continue
        old_group, old_field = parts
        xpath = field_xpath_map.get(old_ref, '')
        if not xpath:
            continue

        # 保留原始 field name（含 hash 后缀）
        field_name = old_field

        unique_cases = list(set(case_ids))
        if len(unique_cases) == 1:
            # 只被 1 个 case 使用 → 归入该 case 的 group
            case_id = unique_cases[0]
            case_groups.setdefault(case_id, {})[field_name] = xpath
        else:
            # 被多个 case 使用 → 归入共享 group
            shared_group[field_name] = xpath
            # 记录共享字段的最小步骤序号
            for case_id in unique_cases:
                idx = field_order.get(case_id, {}).get(old_field, 999)
                if field_name not in shared_field_order or idx < shared_field_order[field_name]:
                    shared_field_order[field_name] = idx

    # 4. 处理孤儿 field（无 case 引用）→ 归入共享 group
    for old_ref, xpath in field_xpath_map.items():
        if old_ref not in field_usage:
            old_group, old_field = old_ref.split('.', 1)
            if old_field not in shared_group:
                shared_group[old_field] = xpath
                shared_field_order[old_field] = 999

    # 5. 构建引用映射
    ref_mapping = build_ref_mapping(field_usage, case_groups, shared_group, module_slug)

    # 6. 构建 field_order 映射（按 group 组织）
    order_map = {}
    order_map[shared_group_name] = shared_field_order
    for case_id, fo in field_order.items():
        # 只保留该 case group 中实际存在的字段
        group_name = f'case_{case_id}'
        case_fields = case_groups.get(case_id, {})
        order_map[group_name] = {fn: idx for fn, idx in fo.items() if fn in case_fields}

    model = {
        'case_groups': case_groups,
        'shared_group': shared_group,
        'field_order': order_map,
        'ref_mapping': ref_mapping,
        'module_slug': module_slug,
    }

    total_case = sum(len(f) for f in case_groups.values())
    print(f"[Step ④] 4a 重组: {len(case_groups)} case groups ({total_case} fields), "
          f"{len(shared_group)} shared fields")

    return model


def _register_inline_locators(project_dir, module_slug, model):
    """Step 4b: 扫描内联 xpath → 注册到内存模型 + 写回 case YAML。"""
    cases = load_cases(project_dir, module=module_slug)
    if not cases:
        return

    case_groups = model['case_groups']
    field_order = model['field_order']
    registered_count = 0

    for case in cases:
        case_id = case.get('id', '')
        if not case_id:
            continue

        case_file = case.get('_file', '')
        if not case_file:
            continue

        steps = case.get('steps', [])
        inline_locators = {}  # {xpath: field_name} 用于去重
        case_group_name = f'case_{case_id}'

        # 确保 case group 存在
        if case_id not in case_groups:
            case_groups[case_id] = {}

        # 确保 field_order 中有该 case 的记录
        if case_group_name not in field_order:
            field_order[case_group_name] = {}

        # 递归扫描所有步骤
        for step_idx, step in enumerate(walk_all_steps(steps)):
            locator = step.get('params', {}).get('locator', '')

            # 过滤条件
            if not locator or not isinstance(locator, str):
                continue
            if not locator.startswith('xpath='):
                continue
            keyword = step.get('keyword', '')
            if keyword == 'except_to_be_visible':
                continue  # 断言不回写

            # 生成 field name
            field_name = _generate_field_name(step, inline_locators)

            # 去重（同 case 内相同 xpath）
            xpath = locator
            if xpath in inline_locators:
                # 已注册，复用 field name
                new_ref = f'${{{case_group_name}.{inline_locators[xpath]}}}'
                step['params']['locator'] = new_ref
            else:
                # 新注册
                inline_locators[xpath] = field_name
                case_groups[case_id][field_name] = xpath
                field_order[case_group_name][field_name] = step_idx
                new_ref = f'${{{case_group_name}.{field_name}}}'
                step['params']['locator'] = new_ref
                registered_count += 1

        # 写回 case YAML
        with open(case_file, 'w', encoding='utf-8') as f:
            yaml.dump(case, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print(f"[Step ④] 4b 内联注册: {registered_count} 个 locator")


def _write_pages_yaml(project_dir, module_slug, model):
    """Step 4c: 统一写入 pages YAML（4a 重组 + 4b 内联合并）。

    按步骤顺序排序字段，不再使用字母排序。
    """
    case_groups = model['case_groups']
    shared_group = model['shared_group']
    field_order = model['field_order']
    shared_group_name = f'{module_slug}_page'

    pages_dir = os.path.join(project_dir, 'pages', module_slug)
    os.makedirs(pages_dir, exist_ok=True)
    output_path = os.path.join(pages_dir, 'elements.yaml')

    def _sort_by_order(fields_dict, order_dict):
        """按步骤序号排序，未记录的字段排最后。"""
        return sorted(fields_dict.items(), key=lambda x: order_dict.get(x[0], 999))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# {module_slug} - 页面元素定位器（Step ④ 重组）\n")
        f.write(f"# 模块: {module_slug}\n")
        f.write("# [WARN] 请勿手动修改 locator，修改后请重新运行工具\n\n")

        # 1. 共享 group（原 common_elements + project_page 合并）
        if shared_group:
            f.write(f"{shared_group_name}:\n")
            order = field_order.get(shared_group_name, {})
            for field_name, xpath in _sort_by_order(shared_group, order):
                scalar = _yaml_scalar(str(xpath))
                f.write(f"  {field_name}: {scalar}\n")
            f.write("\n")

        # 2. 各 case group（按步骤顺序排序）
        for case_id in sorted(case_groups.keys(), key=lambda x: _case_sort_key(x, case_groups)):
            fields = case_groups[case_id]
            if not fields:
                continue
            group_name = f'case_{case_id}'
            f.write(f"{group_name}:\n")
            order = field_order.get(group_name, {})
            for field_name, xpath in _sort_by_order(fields, order):
                scalar = _yaml_scalar(str(xpath))
                f.write(f"  {field_name}: {scalar}\n")
            f.write("\n")

    total_fields = len(shared_group) + sum(len(f) for f in case_groups.values())
    print(f"[Step ④] 4c 写入 pages YAML: {len(case_groups)} case groups + "
          f"1 shared group, {total_fields} fields total")


def _case_sort_key(case_id, case_groups):
    """case 排序：按 case_id 中的数字前缀排序（如 01_, 02_）。"""
    match = re.search(r'(\d+)', case_id)
    if match:
        return int(match.group(1))
    return 999


def _update_case_references(project_dir, module_slug, ref_mapping):
    """Step 4c: 更新所有 case YAML 中的引用。

    Args:
        ref_mapping: {'${old_group.field}': '${new_group.field}'}
    """
    if not ref_mapping:
        return

    cases = load_cases(project_dir, module=module_slug)
    updated_count = 0

    for case in cases:
        case_file = case.get('_file', '')
        if not case_file:
            continue

        steps = case.get('steps', [])
        case_updated = False

        for step in walk_all_steps(steps):
            locator = step.get('params', {}).get('locator', '')
            if not locator or '${' not in locator:
                continue

            # 替换引用
            new_locator = locator
            for old_ref, new_ref in ref_mapping.items():
                if old_ref in new_locator:
                    new_locator = new_locator.replace(old_ref, new_ref)

            if new_locator != locator:
                step['params']['locator'] = new_locator
                case_updated = True
                updated_count += 1

        if case_updated:
            with open(case_file, 'w', encoding='utf-8') as f:
                yaml.dump(case, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print(f"[Step ④] 引用更新: {updated_count} 个引用")


def _generate_field_name(step, existing):
    """生成 field name（按 elem_type 和 label）。

    Args:
        step: 步骤字典
        existing: {xpath: field_name} 用于去重

    Returns:
        str: field name
    """
    label = step.get('label', '')
    elem_type = step.get('elem_type', '')
    keyword = step.get('keyword', '')
    desc = step.get('desc', '')

    # 基础 name
    if elem_type == 'dropdown-menu-item':
        base_name = f"{label}_menu_item" if label else "menu_item"
    elif elem_type == 'date-picker':
        if '今天' in label or '今天' in desc:
            base_name = 'date_today_btn'
        else:
            base_name = f"date_picker_{label}" if label else "date_picker"
    elif elem_type == 'cascader':
        if 'level' in desc.lower():
            level = _extract_level_number(desc)
            base_name = f"{label}_level{level}" if label else f"cascader_level{level}"
        elif 'last' in desc.lower() or '末级' in desc:
            base_name = f"{label}_last_level" if label else "cascader_last_level"
        else:
            base_name = f"{label}_collapse" if label else "cascader_collapse"
    elif elem_type == 'checkbox':
        row = _extract_row_number(step.get('params', {}).get('locator', ''))
        base_name = f"row{row}_checkbox"
    elif keyword in ['click_element', 'wait_for_element']:
        # el-select option / close_btn / conditional
        if 'option' in desc.lower() or '选项' in desc:
            base_name = f"{label}_option_item" if label else "option_item"
        elif 'collapse' in desc.lower() or '收起' in desc:
            base_name = f"{label}_collapse" if label else "collapse"
        elif 'close' in label.lower() or '关闭' in label:
            base_name = f"{label}_close_btn"
        else:
            base_name = f"{label}_btn" if label else "btn"
    elif keyword == 'if_element_visible':
        base_name = f"{label}_check" if label else "check"
    else:
        base_name = f"{label}_element" if label else "element"

    # 去重
    if base_name not in existing.values():
        return base_name

    # 加序号
    counter = 2
    while f"{base_name}_{counter}" in existing.values():
        counter += 1
    return f"{base_name}_{counter}"


def _extract_level_number(desc):
    """从描述中提取层级数字。"""
    match = re.search(r'(\d+)', desc)
    if match:
        return match.group(1)
    return '1'


def _extract_row_number(locator):
    """从 locator 中提取行号。"""
    match = re.search(r'tr\[(\d+)\]', locator)
    if match:
        return match.group(1)
    return '1'


# ─── CLI 入口（用于单独测试）───
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Step ④: Pages 重组与内联注册')
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--module', required=True, help='模块英文slug')
    args = parser.parse_args()

    if not os.path.isdir(args.project_dir):
        print(f"[ERROR] 项目目录不存在: {args.project_dir}")
        sys.exit(1)

    post_process_step4(args.project_dir, args.module)
