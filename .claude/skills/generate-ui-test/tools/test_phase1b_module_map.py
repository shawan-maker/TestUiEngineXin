#!/usr/bin/env python3
"""验证 D方案：Phase 1b 完成后自动构建 module_map_str"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import PipelineContext

def test_phase1b_builds_module_map():
    """模拟 Phase 1b 完成后，module_map_str 应被构建"""

    # 创建 context
    ctx = PipelineContext(
        project_dir="D:/PyProject/TestUiEngineXin/examples/TSManager3",
        excel_path="D:/PyProject/TestUiEngineXin/examples/webuic测试用例-天枢2-修正版.xlsx",
        cookie="ud_token=test"
    )

    # Phase 0: 初始加载（此时 excel_parsed.json 不存在）
    print("=" * 60)
    print("Phase 0: update_from_config()")
    print("=" * 60)
    ctx.update_from_config()
    print(f"✓ excel_json_path: {ctx.excel_json_path}")
    print(f"✓ modules 数量: {len(ctx.modules)}")
    print(f"✓ module_map_str: '{ctx.module_map_str}' (应该为空)")

    assert ctx.module_map_str == "", "Phase 0 时 module_map_str 应该为空"

    # 模拟 Phase 1b: read_excel.py 生成 excel_parsed.json
    print("\n" + "=" * 60)
    print("模拟 Phase 1b: 生成 excel_parsed.json")
    print("=" * 60)

    probe_dir = Path(ctx.project_dir) / "_probe"
    probe_dir.mkdir(exist_ok=True)

    excel_parsed_path = probe_dir / "excel_parsed.json"

    # 创建模拟的 excel_parsed.json
    mock_data = [
        {
            "sheet": "问题管理",
            "cases": [
                {
                    "module": "问题管理",
                    "case_name": "新建问题",
                    "steps": [
                        "访问 http://100.71.19.25:30101/#/question-manage/deliveryIssues-list",
                        "点击新增按钮"
                    ]
                }
            ]
        },
        {
            "sheet": "总览查看",
            "cases": [
                {
                    "module": "总览查看",
                    "case_name": "查看总览",
                    "steps": [
                        "访问 http://100.71.19.25:30101/#/overview-page/base"
                    ]
                }
            ]
        },
        {
            "sheet": "工单管理",
            "cases": [
                {
                    "module": "工单管理",
                    "case_name": "新建工单",
                    "steps": [
                        "访问 http://100.71.19.25:30101/#/work-order/new-list"
                    ]
                }
            ]
        },
        {
            "sheet": "项目管理",
            "cases": [
                {
                    "module": "项目管理",
                    "case_name": "新建项目",
                    "steps": [
                        "访问 http://100.71.19.25:30101/#/project/overview-list"
                    ]
                }
            ]
        },
        {
            "sheet": "公有云问题管理",
            "cases": [
                {
                    "module": "公有云问题管理",
                    "case_name": "新建问题",
                    "steps": [
                        "访问 http://100.71.19.25:30101/#/cloud-question/list"
                    ]
                }
            ]
        }
    ]

    with open(excel_parsed_path, 'w', encoding='utf-8') as f:
        json.dump(mock_data, f, ensure_ascii=False, indent=2)

    print(f"✓ 创建: {excel_parsed_path}")

    # Phase 1b 完成后的操作（模拟管线代码）
    print("\n" + "=" * 60)
    print("Phase 1b 完成后: update_from_config() + _build_module_aliases()")
    print("=" * 60)

    ctx.update_from_config()
    print(f"✓ excel_json_path: {ctx.excel_json_path}")
    print(f"✓ module_map_str: '{ctx.module_map_str}'")

    # 验证结果
    assert ctx.excel_json_path is not None, "excel_json_path 应该被设置"
    assert ctx.module_map_str != "", "module_map_str 应该被构建"

    # 检查映射内容
    mappings = dict(item.split("=") for item in ctx.module_map_str.split(","))
    print(f"\n✓ 映射数量: {len(mappings)}")
    for cn, slug in sorted(mappings.items()):
        print(f"  - {cn} → {slug}")

    expected_mappings = {
        "问题管理": "question-manage",
        "总览查看": "overview",
        "工单管理": "work-order",
        "项目管理": "project",
        "公有云问题管理": "cloud-question"
    }

    for cn, slug in expected_mappings.items():
        assert mappings.get(cn) == slug, f"映射错误: {cn} 应该映射到 {slug}，实际是 {mappings.get(cn)}"

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！D方案生效")
    print("=" * 60)

if __name__ == "__main__":
    test_phase1b_builds_module_map()
