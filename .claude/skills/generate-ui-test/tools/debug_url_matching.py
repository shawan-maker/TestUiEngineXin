#!/usr/bin/env python3
"""调试脚本：检查 Excel 步骤中的 URL 提取"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.pipeline import PipelineContext

# 创建 context
ctx = PipelineContext(
    project_dir="D:/PyProject/TestUiEngineXin/examples/TSManager3",
    excel_path="D:/PyProject/TestUiEngineXin/examples/webuic测试用例-天枢2-修正版.xlsx",
    cookie="ud_token=test"
)

# 加载配置
ctx.update_from_config()

print("=" * 60)
print("调试：URL 匹配过程")
print("=" * 60)

# 手动调用 _build_module_aliases 并打印中间过程
from urllib.parse import urlparse

def normalize_url(url):
    """URL 规范化"""
    try:
        parsed = urlparse(url.strip())
        result = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.fragment:
            result += f"#{parsed.fragment}"
        return result
    except Exception:
        return url.strip()

# 1. 从 config 提取 URL
print("\n[1] 从 config.yaml page_urls 提取:")
slug_urls = {}
for mod_info in ctx.modules:
    slug = mod_info.get("slug", "")
    urls = mod_info.get("urls", [])
    if slug and urls:
        normalized = {normalize_url(u) for u in urls}
        slug_urls[slug] = normalized
        print(f"  {slug}:")
        for url in normalized:
            print(f"    - {url}")

# 2. 从 Excel 提取 URL
print("\n[2] 从 Excel 提取:")
import openpyxl

wb = openpyxl.load_workbook(ctx.excel_path, read_only=True, data_only=True)
cn_name_urls = {}

for ws in wb.worksheets:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        continue

    headers = [str(h).strip() if h else "" for h in rows[0]]
    module_idx = None
    case_name_idx = None
    steps_idx = None

    for idx, h in enumerate(headers):
        if h in ["模块", "功能模块", "所属模块"]:
            module_idx = idx
        elif h in ["用例名称", "测试用例名称", "用例标题"]:
            case_name_idx = idx
        elif h in ["用例步骤", "测试步骤", "步骤描述"]:
            steps_idx = idx

    if module_idx is None or case_name_idx is None or steps_idx is None:
        continue

    print(f"\n  Sheet: {ws.title}")
    print(f"    Headers: {headers}")
    print(f"    module_idx={module_idx}, case_name_idx={case_name_idx}, steps_idx={steps_idx}")

    for row in rows[1:3]:  # 只看前 2 行
        if len(row) <= max(module_idx, case_name_idx, steps_idx):
            continue

        module = str(row[module_idx]).strip() if row[module_idx] else ""
        case_name = str(row[case_name_idx]).strip() if row[case_name_idx] else ""
        steps_text = str(row[steps_idx]).strip() if row[steps_idx] else ""

        print(f"\n    Module: {module}")
        print(f"    Case: {case_name}")
        print(f"    Steps text (first 200 chars): {steps_text[:200]}")

        # 提取 URL
        urls_found = []
        for step_line in steps_text.split("\n"):
            step_line = step_line.strip()
            if step_line:
                for part in step_line.split():
                    if part.startswith("http://") or part.startswith("https://"):
                        normalized = normalize_url(part)
                        urls_found.append(normalized)
                        if module not in cn_name_urls:
                            cn_name_urls[module] = set()
                        cn_name_urls[module].add(normalized)

        if urls_found:
            print(f"    URLs found: {len(urls_found)}")
            for url in urls_found[:3]:  # 只显示前 3 个
                print(f"      - {url}")

wb.close()

print("\n[3] 匹配结果:")
print(f"  slug_urls 数量: {len(slug_urls)}")
print(f"  cn_name_urls 数量: {len(cn_name_urls)}")

print("\n[4] 交叉匹配:")
aliases = {}
for cn_name, cn_urls in cn_name_urls.items():
    print(f"\n  中文模块: {cn_name} ({len(cn_urls)} URLs)")
    matched = False
    for slug, s_urls in slug_urls.items():
        intersection = cn_urls & s_urls
        if intersection:
            print(f"    ✓ 匹配到: {slug} (交集: {len(intersection)} URLs)")
            for url in list(intersection)[:2]:
                print(f"      - {url}")
            aliases[cn_name] = slug
            matched = True
            break
    if not matched:
        print(f"    ✗ 未匹配")

print("\n[5] 最终映射:")
for cn, slug in aliases.items():
    print(f"  {cn} → {slug}")

print("\n" + "=" * 60)
print(f"结果: 匹配了 {len(aliases)}/{len(cn_name_urls)} 个模块")
print("=" * 60)
