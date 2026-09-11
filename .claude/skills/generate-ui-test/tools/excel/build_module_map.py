#!/usr/bin/env python3
"""build_module_map.py — 构建中文模块名→英文 slug 映射（Phase 2.5）

从 Excel 模块列 + pages/ 目录结构 + YAML 注释 + discovery JSON 自动构建映射，
输出 _probe/module_map.json 供 Phase 4、Phase 5 使用。

用法:
    python build_module_map.py "{excel_file}" \
      --pages {project}/pages \
      --discovery-dir {project}/_probe \
      --output {project}/_probe/module_map.json \
      --module-map "总览查看=overview-mail,站内信查看=overview-mail"  # 可选覆盖
"""
import argparse
import glob
import json
import os
import re
import sys

try:
    import openpyxl
except ImportError:
    print("[ERROR] 缺少 openpyxl，请运行: pip install openpyxl", file=sys.stderr)
    sys.exit(1)

# 复用 read_excel.py 的列检测逻辑
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
try:
    from read_excel import detect_columns, COLUMN_ALIASES
except ImportError as e:
    print(f"[ERROR] 无法导入 read_excel.py: {e}", file=sys.stderr)
    print("[INFO] 请确保 read_excel.py 存在于 tools/ 目录", file=sys.stderr)
    sys.exit(1)


def _extract_excel_modules(excel_path):
    """从 Excel 提取所有唯一的中文模块名（模块列值）。

    遍历所有 sheet，检测"模块"列（自动适配列标题变体），收集非空值。
    如果 sheet 没有"模块"列，回退到 sheet 名称（与 read_excel.py extract_urls 修改7b 一致）。
    """
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    modules = set()
    for ws in wb.worksheets:
        headers = [str(c.value or '').strip() for c in ws[1]]
        col_map = detect_columns(headers)
        module_idx = col_map.get('module')
        if module_idx is None:
            # 回退到 sheet 名称（与 read_excel.py extract_urls 修改7b 一致）
            sheet_name = ws.title
            if sheet_name and sheet_name != 'Sheet':
                modules.add(sheet_name)
            continue
        for row in ws.iter_rows(min_row=2, values_only=True):
            if module_idx >= len(row):
                continue
            val = row[module_idx]
            if val and isinstance(val, str):
                name = val.strip()
                if name and name != '模块':
                    modules.add(name)
    wb.close()
    return sorted(modules)


def _scan_pages_dirs(pages_dir):
    """扫描 pages/ 目录，返回英文 slug 集合。

    过滤规则：
    - 排除 '.' 和 '_' 开头的目录
    - 排除包含中文字符的目录（历史污染数据）
    - 排除 'common' 目录（通用元素）
    """
    slugs = set()
    if not os.path.isdir(pages_dir):
        return slugs
    for entry in os.listdir(pages_dir):
        full = os.path.join(pages_dir, entry)
        # 基本过滤
        if not os.path.isdir(full):
            continue
        if entry.startswith(('.', '_')):
            continue
        if entry == 'common':
            continue
        # 过滤中文目录名（包含非ASCII字符）
        if any(ord(c) > 127 for c in entry):
            continue
        slugs.add(entry)
    return slugs


def _scan_yaml_comments(pages_dir):
    """扫描 pages/*/elements.yaml 注释，提取 `# 模块: XX` 映射。

    Returns: {中文名: slug}
    """
    mapping = {}
    if not os.path.isdir(pages_dir):
        return mapping
    for slug in os.listdir(pages_dir):
        yaml_path = os.path.join(pages_dir, slug, 'elements.yaml')
        if not os.path.isfile(yaml_path):
            continue
        try:
            with open(yaml_path, encoding='utf-8') as f:
                for line in f:
                    m = re.match(r'^#\s*模块:\s*(.+)', line)
                    if m:
                        cn_name = m.group(1).strip()
                        mapping[cn_name] = slug
                        break
        except Exception:
            continue
    return mapping


def _scan_discovery_json(discovery_dir):
    """扫描 _probe/discovery_*.json，提取 cn_name 字段映射。

    Returns: {cn_name: slug}
    """
    mapping = {}
    if not os.path.isdir(discovery_dir):
        return mapping
    for disc_file in sorted(glob.glob(os.path.join(discovery_dir, 'discovery_*.json'))):
        try:
            with open(disc_file, encoding='utf-8') as f:
                disc = json.load(f)
        except Exception:
            continue
        slug = disc.get('module', '')
        cn = disc.get('cn_name', '')
        if cn and slug and cn != slug:
            mapping[cn] = slug
    return mapping


def _build_mapping(cn_modules, en_slugs, yaml_comments, discovery_map, cli_overrides, module_urls=None):
    """构建中文模块名→英文 slug 映射。

    匹配优先级（简化为 3 级）:
    1. CLI --module-map 显式覆盖
    2. 已有映射（discovery JSON / YAML 注释 / en_slugs）— 向后兼容
    3. AI 翻译（translate_module_names）— 首次运行的主要路径
    """
    from excel.translate_module_name import resolve_and_translate

    # 合并所有已有映射源
    existing_map = {}
    existing_map.update(discovery_map)
    existing_map.update(yaml_comments)
    for cn in cn_modules:
        if cn in en_slugs:
            existing_map.setdefault(cn, cn)

    # 调用统一入口
    return resolve_and_translate(
        cn_modules,
        cli_overrides=cli_overrides,
        module_map=existing_map,
    )


def main():
    parser = argparse.ArgumentParser(
        description='构建中文模块名→英文 slug 映射文件')
    parser.add_argument('excel', help='Excel 用例文件路径')
    parser.add_argument('--pages', required=True,
                        help='pages/ 目录路径')
    parser.add_argument('--discovery-dir', default=None,
                        help='_probe/ 目录路径（可选，兼容历史 discovery JSON）')
    parser.add_argument('--output', required=True,
                        help='输出 JSON 文件路径')
    parser.add_argument('--module-map', default='',
                        help='手动覆盖映射，格式: 中文名1=slug1,中文名2=slug2')
    parser.add_argument('--module-urls', default=None,
                        help='module_urls.json 路径（可选，用于从 URL 提取 slug）')

    args = parser.parse_args()

    # 验证输入
    if not os.path.isfile(args.excel):
        print(f"[ERROR] Excel 文件不存在: {args.excel}", file=sys.stderr)
        sys.exit(1)

    # 解析 CLI 覆盖
    cli_overrides = {}
    if args.module_map:
        for pair in args.module_map.split(','):
            pair = pair.strip()
            if '=' in pair:
                k, v = pair.split('=', 1)
                cli_overrides[k.strip()] = v.strip()

    # Step 1: 提取 Excel 中文模块名
    cn_modules = _extract_excel_modules(args.excel)
    print(f"[INFO] Excel 中发现 {len(cn_modules)} 个中文模块名: {cn_modules}")

    # Step 2: 扫描 pages/ 英文 slug
    en_slugs = _scan_pages_dirs(args.pages)
    print(f"[INFO] pages/ 中发现 {len(en_slugs)} 个英文 slug: {sorted(en_slugs)}")

    # Step 3: 扫描 YAML 注释
    yaml_comments = _scan_yaml_comments(args.pages)
    print(f"[INFO] YAML 注释映射: {yaml_comments}")

    # Step 4: 扫描 discovery JSON cn_name（可选）
    discovery_map = {}
    if args.discovery_dir:
        discovery_map = _scan_discovery_json(args.discovery_dir)
        print(f"[INFO] discovery JSON cn_name 映射: {discovery_map}")

    # Step 5: 构建映射（AI 翻译替代 URL 提取）
    mapping = _build_mapping(cn_modules, en_slugs, yaml_comments, discovery_map, cli_overrides)

    # Step 6: 输出
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 模块映射已写入: {args.output}")
    for cn, slug in mapping.items():
        print(f"  {cn} → {slug}")


if __name__ == '__main__':
    main()
