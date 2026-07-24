#!/usr/bin/env python3
"""
probe_missing_from_excel.py - Phase 4g: Excel 字段发现 + 补探

从 Excel 用例步骤推断 pages YAML 中应该存在但缺失的元素字段，
对缺失字段调用 probe_element.py 补探并写入 pages YAML。

用法:
    python probe_missing_from_excel.py {project_dir} \
        --excel {excel_json} \
        [--cookie "..."] [--url "..."] [--dry-run]

参数:
    project_dir     项目根目录
    --excel         read_excel.py 输出的 JSON 文件
    --cookie        覆盖 config.yaml 中的 cookie
    --url           覆盖 config.yaml 中的 target_url
    --dry-run       只报告缺失字段，不执行探测
    --module        只检查指定模块（可选）

退出码:
    0 = 无缺失字段
    1 = 有缺失字段（已补探或 dry-run 报告）
    2 = 补探后仍有未覆盖
"""

import argparse
import json
import os
import re
import subprocess
import sys
import glob

import yaml

# 导入 step_patterns（同目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import step_patterns
except ImportError:
    print("[ERROR] step_patterns.py 未找到", file=sys.stderr)
    sys.exit(2)


# ===========================================================================
# 步骤类型 → 需要的 pages 字段映射
# ===========================================================================

# 每种 step_patterns 类型需要的字段后缀列表
# 格式: {type: [(suffix, description), ...]}
TYPE_TO_SUFFIXES = {
    'el_select': [
        ('_select', 'el-select 下拉框'),
        ('_input', 'el-select 搜索输入框'),
        ('_option', 'el-select 选项'),
    ],
    'fill': [
        ('_input', '输入框'),
    ],
    'date_select': [
        ('_input', '日期输入框'),
    ],
    'click_btn': [
        ('_btn', '按钮'),
    ],
    'click': [
        ('_btn', '按钮'),
    ],
    'click_tab': [
        ('_tab', 'Tab 标签'),
    ],
    'click_table_row_btn': [
        ('_btn', '行操作按钮'),
    ],
    'click_table_action': [
        ('_btn', '表格操作按钮'),
    ],
    'confirm_dialog': [
        ('_btn', '确认按钮'),
    ],
    'confirm_delete': [
        ('_btn', '删除确认按钮'),
    ],
    'click_detail_link': [
        ('_link', '详情链接'),
    ],
    'click_navigate': [
        ('_link', '导航链接'),
    ],
}


def label_to_field_prefix(label: str) -> str:
    """将中文标签转为英文字段前缀（简单拼音/翻译映射）

    这是一个最佳努力映射。实际使用中，pages YAML 的字段名由
    _pages_writer.py 从 probe 结果生成，标签→字段名
    的映射已在 pages YAML 注释中记录。这里只做缺失检测的
    启发式推断。
    """
    # 去除常见后缀
    for suffix in ('按钮', '下拉框', '输入框', '文本框', '选择框',
                   '日期选择框', '链接', '标签', '文本', '区域',
                   '字段', '选项', '复选框', '开关'):
        if label.endswith(suffix):
            label = label[:-len(suffix)]
            break
    return label


def extract_needed_fields_from_excel(excel_json_path: str,
                                      module_filter: str = None) -> dict:
    """从 Excel JSON 提取所有需要的元素字段

    返回: {module_name: {field_prefix: [(suffix, step_type, raw_step), ...]}}
    """
    with open(excel_json_path, encoding='utf-8') as f:
        sheets = json.load(f)

    result = {}

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        sheet_name = sheet.get('sheet', '')

        for case in sheet.get('cases', []):
            if not isinstance(case, dict):
                continue
            case_module = case.get('module', '') or sheet_name

            if module_filter and case_module != module_filter:
                continue

            for step_text in case.get('steps', []):
                if not isinstance(step_text, str):
                    continue

                parsed = step_patterns.parse_step(step_text)
                step_type = parsed.get('type', 'unknown')
                args = parsed.get('args', ())

                if step_type not in TYPE_TO_SUFFIXES:
                    continue

                # 从 args 提取标签（通常是第一个参数）
                label = args[0] if args else ''
                if not label:
                    continue

                field_prefix = label_to_field_prefix(label)
                if not field_prefix:
                    continue

                module_key = case_module
                if module_key not in result:
                    result[module_key] = {}

                for suffix, desc in TYPE_TO_SUFFIXES[step_type]:
                    field_name = field_prefix + suffix
                    if field_name not in result[module_key]:
                        result[module_key][field_name] = []
                    result[module_key][field_name].append(
                        (suffix, step_type, step_text))

    return result


def scan_pages_fields(pages_dir: str) -> dict:
    """扫描 pages YAML，返回已有字段集合

    返回: {group_name: set(field_name)}
    """
    result = {}

    for root, dirs, files in os.walk(pages_dir):
        for fname in files:
            if not fname.endswith('.yaml') or fname.startswith('_'):
                continue
            filepath = os.path.join(root, fname)
            try:
                with open(filepath, encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for group_name, fields in data.items():
                # BUG-1 审计修复: 排除 page_urls 元数据
                if group_name == 'page_urls':
                    continue
                if not isinstance(fields, dict):
                    continue
                if group_name not in result:
                    result[group_name] = set()
                for field_name in fields:
                    if field_name != '_meta':
                        result[group_name].add(field_name)

    return result


def find_missing_fields(needed: dict, existing: dict,
                         label_map: dict = None) -> list:
    """对比 Excel 需要的字段和 pages 已有的字段，返回缺失列表

    needed: {module: {field_prefix_suffix: [(suffix, type, raw), ...]}}
    existing: {group_name: set(field_name)}

    返回: [(module, field_name, suffix, step_type, raw_step, label), ...]
    """
    # 收集所有已有的字段名（全量，跨 group）
    all_existing_fields = set()
    for fields in existing.values():
        all_existing_fields.update(fields)

    # 如果有 label_map，用它来做更精确的匹配
    existing_labels = set()
    if label_map:
        existing_labels = set(label_map.keys())

    missing = []

    for module, fields_dict in needed.items():
        for field_name, usages in fields_dict.items():
            # 检查字段是否在任何 group 中存在
            found = False
            for group_fields in existing.values():
                if field_name in group_fields:
                    found = True
                    break

            if not found:
                suffix, step_type, raw_step = usages[0]
                # 从 field_name 反推标签
                label = field_name
                for s in ('_select', '_input', '_option', '_btn', '_tab',
                          '_link', '_textarea', '_text'):
                    if field_name.endswith(s):
                        label = field_name[:-len(s)]
                        break
                missing.append((module, field_name, suffix, step_type,
                               raw_step, label))

    return missing


def load_config(project_dir: str) -> dict:
    """加载 config.yaml"""
    config_path = os.path.join(project_dir, 'config.yaml')
    if os.path.exists(config_path):
        with open(config_path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def load_label_map(pages_dir: str) -> dict:
    """从 pages YAML 注释中提取 中文标签→字段前缀 映射

    返回: {中文标签: [(group, field_prefix, container_type)]}
    """
    label_map = {}
    comment_suffixes = (
        '下拉框', '输入框', '文本框', '文本区域', '选择框',
        '时间选择框', '日期选择框', '按钮', '链接', '标签',
        '文本', '区域', '字段', '选项', '图标', '开关', '复选框',
    )
    field_re = re.compile(
        r'^\s+(\w+?)_(?:select|input|option|btn|text|textarea|link|area|field|count)\s*:'
    )

    for root, dirs, files in os.walk(pages_dir):
        for fname in files:
            if not fname.endswith('.yaml') or fname.startswith('_'):
                continue
            filepath = os.path.join(root, fname)
            try:
                with open(filepath, encoding='utf-8') as f:
                    raw_lines = f.readlines()
            except Exception:
                continue

            current_group = ''
            for i, line in enumerate(raw_lines):
                # 检测 group
                if line and not line[0].isspace() and ':' in line:
                    group_candidate = line.split(':')[0].strip()
                    if group_candidate and not group_candidate.startswith('#'):
                        current_group = group_candidate

                # 提取内联注释
                if '#' in line and ':' in line:
                    parts = line.split('#', 1)
                    comment = parts[1].strip()
                    for suffix in comment_suffixes:
                        if comment.endswith(suffix):
                            comment = comment[:-len(suffix)]
                            break
                    m = field_re.match(line)
                    if m and comment:
                        field_prefix = m.group(1)
                        container = ''
                        if 'el-drawer' in line:
                            container = 'drawer'
                        elif 'el-dialog' in line:
                            container = 'dialog'
                        if comment not in label_map:
                            label_map[comment] = []
                        label_map[comment].append(
                            (current_group, field_prefix, container))

                # 提取上一行注释
                if i > 0:
                    prev = raw_lines[i - 1].strip()
                    if prev.startswith('#') and not prev.startswith('#!'):
                        comment = prev[1:].strip()
                        for suffix in comment_suffixes:
                            if comment.endswith(suffix):
                                comment = comment[:-len(suffix)]
                                break
                        m = field_re.match(line)
                        if m and comment:
                            field_prefix = m.group(1)
                            container = ''
                            if 'el-drawer' in line:
                                container = 'drawer'
                            elif 'el-dialog' in line:
                                container = 'dialog'
                            if comment not in label_map:
                                label_map[comment] = []
                            label_map[comment].append(
                                (current_group, field_prefix, container))

    return label_map


def main():
    parser = argparse.ArgumentParser(
        description='Phase 4g: 从 Excel 发现 pages YAML 缺失字段并补探')
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--excel', required=True,
                        help='read_excel.py 输出的 JSON 文件')
    parser.add_argument('--cookie', help='覆盖 config.yaml 中的 cookie')
    parser.add_argument('--url', help='覆盖 config.yaml 中的 target_url')
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告缺失字段，不执行探测')
    parser.add_argument('--module', help='只检查指定模块')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[ERROR] 项目目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    if not os.path.exists(args.excel):
        print(f"[ERROR] Excel JSON 不存在: {args.excel}", file=sys.stderr)
        sys.exit(2)

    print(f"{'='*60}")
    print(f"Phase 4g: Excel 字段发现 + 补探")
    print(f"项目: {project_dir}")
    print(f"Excel: {args.excel}")
    print(f"{'='*60}")

    # Step 1: 从 Excel 提取需要的字段
    needed = extract_needed_fields_from_excel(args.excel, args.module)
    total_needed = sum(len(v) for v in needed.values())
    print(f"\n[Step 1] Excel 字段提取")
    print(f"  共 {total_needed} 个唯一字段，分布在 {len(needed)} 个模块")

    # Step 2: 扫描 pages YAML 已有字段
    pages_dir = os.path.join(project_dir, 'pages')
    existing = scan_pages_fields(pages_dir)
    total_existing = sum(len(v) for v in existing.values())
    print(f"\n[Step 2] pages YAML 扫描")
    print(f"  共 {total_existing} 个字段，分布在 {len(existing)} 个 group")

    # Step 3: 加载 label_map（中文标签→字段映射）
    label_map = load_label_map(pages_dir)
    print(f"\n[Step 3] 标签映射加载")
    print(f"  共 {len(label_map)} 个中文标签")

    # Step 4: 对比找缺失字段
    missing = find_missing_fields(needed, existing, label_map)
    print(f"\n[Step 4] 缺失字段检测")

    if not missing:
        print(f"  [PASS] 无缺失字段，所有 Excel 步骤所需的 pages 字段均已存在")
        sys.exit(0)

    print(f"  发现 {len(missing)} 个缺失字段:")
    for module, field_name, suffix, step_type, raw_step, label in missing[:20]:
        print(f"    [{module}] {field_name} ({step_type}) ← \"{raw_step[:50]}\"")
    if len(missing) > 20:
        print(f"    ... 及其他 {len(missing) - 20} 个")

    if args.dry_run:
        print(f"\n[DRY-RUN] 不执行探测，退出")
        sys.exit(1)

    # Step 5: 加载配置
    config = load_config(project_dir)
    cookie = args.cookie or config.get('cookie', '')
    url = args.url or config.get('target_url', '')
    if not cookie:
        print("[ERROR] 无 cookie，无法探测。请传 --cookie 或在 config.yaml 配置",
              file=sys.stderr)
        sys.exit(2)
    if not url:
        print("[ERROR] 无 URL，无法探测。请传 --url 或在 config.yaml 配置",
              file=sys.stderr)
        sys.exit(2)

    # Step 6: 按容器类型分组并调用 probe_element.py
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    probe_tool = os.path.join(skill_dir, 'probe_element.py')
    probe_dir = os.path.join(project_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)

    # 简单分组: initial vs container
    initial_elements = []
    container_elements = []
    for module, field_name, suffix, step_type, raw_step, label in missing:
        # 根据后缀推断元素类型
        if suffix == '_select':
            el_type = 'el-select'
        elif suffix == '_btn':
            el_type = 'button'
        elif suffix == '_input' or suffix == '_textarea':
            el_type = 'input'
        elif suffix == '_tab':
            el_type = 'tab'
        elif suffix == '_link':
            el_type = 'link'
        else:
            el_type = 'button'  # 默认

        initial_elements.append((el_type, label, field_name))

    probed_count = 0
    failed_count = 0

    if initial_elements:
        # 构建 --element 参数
        elements_args = []
        for el_type, label, key in initial_elements:
            elements_args.extend(['--element', f'{el_type}:{label}:{key}'])

        output_file = os.path.join(probe_dir, 'probe_missing_from_excel.json')
        cmd = [
            'python', probe_tool, url,
            '--cookie', cookie,
            '--output', output_file,
        ] + elements_args

        print(f"\n[Step 6] 探测缺失字段 ({len(initial_elements)} 个)")
        print(f"  命令: {' '.join(cmd[:6])}...")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=120)
            if result.returncode == 0:
                print(f"  [OK] 探测完成")
                # 读取结果，统计 verified
                if os.path.exists(output_file):
                    with open(output_file, encoding='utf-8') as f:
                        probe_result = json.load(f)
                    for el in probe_result.get('elements', []):
                        if el.get('verified'):
                            probed_count += 1
                        else:
                            failed_count += 1
                print(f"  verified: {probed_count}, failed: {failed_count}")
            else:
                print(f"  [ERROR] 探测失败: {result.stderr[:200]}",
                      file=sys.stderr)
                failed_count = len(initial_elements)
        except subprocess.TimeoutExpired:
            print(f"  [ERROR] 探测超时 (120s)", file=sys.stderr)
            failed_count = len(initial_elements)
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)
            failed_count = len(initial_elements)

    # 结果报告
    print(f"\n{'='*60}")
    print(f"[SUMMARY]")
    print(f"  缺失字段: {len(missing)}")
    print(f"  探测成功: {probed_count}")
    print(f"  探测失败: {failed_count}")
    print(f"{'='*60}")

    if failed_count > 0:
        print(f"\n[INFO] 探测失败的字段需要手动处理或调整探测策略")
        sys.exit(2)

    if probed_count > 0:
        print(f"\n[INFO] 探测结果已写入: {output_file}")
        print(f"[INFO] 请运行 generate_from_excel.py 将结果写入 pages YAML")
        sys.exit(1)

    sys.exit(1)


if __name__ == '__main__':
    main()
