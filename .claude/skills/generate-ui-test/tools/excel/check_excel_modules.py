#!/usr/bin/env python3
"""检查 Excel 文件的所有模块"""

import openpyxl
from pathlib import Path

excel_path = "D:/PyProject/TestUiEngineXin/examples/webuic测试用例-天枢2-修正版.xlsx"
wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)

print("=" * 60)
print("Excel 文件结构")
print("=" * 60)

for ws in wb.worksheets:
    print(f"\nSheet: {ws.title}")
    rows = list(ws.iter_rows(values_only=True))

    if not rows:
        print("  (空)")
        continue

    headers = [str(h).strip() if h else "" for h in rows[0]]
    print(f"  Headers: {headers}")
    print(f"  Rows: {len(rows)}")

    # 查找模块列
    module_idx = None
    for idx, h in enumerate(headers):
        if h in ["模块", "功能模块", "所属模块"]:
            module_idx = idx
            break

    if module_idx is None:
        print(f"  ⚠️ 未找到模块列")
        continue

    # 统计所有模块
    modules = {}
    for row in rows[1:]:
        if len(row) > module_idx and row[module_idx]:
            module = str(row[module_idx]).strip()
            modules[module] = modules.get(module, 0) + 1

    print(f"  Module column index: {module_idx}")
    print(f"  Modules found ({len(modules)}):")
    for module, count in sorted(modules.items()):
        print(f"    - {module}: {count} cases")

wb.close()

print("\n" + "=" * 60)
