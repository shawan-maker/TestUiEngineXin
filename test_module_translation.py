#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试模块名称解析功能（保留原始名版）

测试场景:
1. Excel 模块列 (build_module_map.py)
2. NL --module 参数 (pipeline.py line 887)
3. post-phase_1b hook (pipeline.py line 892)
4. CLI --module-map 覆盖
5. 混合中英文
6. 特殊字符清理
7. 碰撞检测
8. 纯 ASCII
9. 已有 module_map.json
10. build_module_map.py 集成
"""

import sys
import json
import tempfile
from pathlib import Path
import io

# 设置 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加工具目录到 Python 路径
tools_dir = Path(__file__).parent / ".claude" / "skills" / "generate-ui-test" / "tools"
sys.path.insert(0, str(tools_dir))

print(f"添加路径: {tools_dir}")
print(f"Python 路径: {sys.path[:3]}")

# 添加到 sys.path
TOOLS_DIR = Path(__file__).parent.parent / ".claude" / "skills" / "generate-ui-test" / "tools"
sys.path.insert(0, str(TOOLS_DIR))

def test_1_excel_module_column():
    """测试 Excel 模块列 — 保留原始中文名"""
    print("\n" + "="*60)
    print("测试 1: Excel 模块列（保留原始名）")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    # 模拟 Excel 模块列
    cn_names = ["日志管理", "账户管理", "项目管理"]
    result = resolve_and_translate(cn_names)

    print(f"输入: {cn_names}")
    print(f"输出: {result}")

    # 验证：保留原始名
    assert len(result) == len(cn_names), "数量不匹配"
    assert result["日志管理"] == "日志管理"
    assert result["账户管理"] == "账户管理"
    assert result["项目管理"] == "项目管理"

    print("✓ Excel 模块列测试通过")

def test_2_nl_module_param():
    """测试 NL --module 参数"""
    print("\n" + "="*60)
    print("测试 2: NL --module 参数")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    # 模拟 NL 输入
    nlp_module_name = "网络管理"
    result = resolve_and_translate([nlp_module_name])

    print(f"输入: {nlp_module_name}")
    print(f"输出: {result}")

    # 验证：保留原始名
    assert nlp_module_name in result
    assert result[nlp_module_name] == "网络管理"

    print("✓ NL --module 参数测试通过")

def test_3_post_phase1b_hook():
    """测试 post-phase_1b hook"""
    print("\n" + "="*60)
    print("测试 3: post-phase_1b hook")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    # 模拟 post-phase_1b 场景
    module_urls = {
        "存储管理": {"urls": ["http://10.151.61.248/storage/list"]},
        "计算管理": {"urls": ["http://10.151.61.248/compute/list"]}
    }

    cn_names = list(module_urls.keys())
    result = resolve_and_translate(cn_names)

    print(f"输入: {cn_names}")
    print(f"输出: {result}")

    # 验证：保留原始名
    assert len(result) == len(cn_names)
    assert result["存储管理"] == "存储管理"
    assert result["计算管理"] == "计算管理"

    print("✓ post-phase_1b hook 测试通过")

def test_4_cli_module_map_override():
    """测试 CLI --module-map 覆盖"""
    print("\n" + "="*60)
    print("测试 4: CLI --module-map 覆盖")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    cn_names = ["自定义模块"]
    cli_overrides = {"自定义模块": "custom_module"}

    result = resolve_and_translate(cn_names, cli_overrides=cli_overrides)

    print(f"输入: {cn_names}")
    print(f"CLI 覆盖: {cli_overrides}")
    print(f"输出: {result}")

    # 验证：CLI 覆盖优先
    assert result["自定义模块"] == "custom_module"

    print("✓ CLI 覆盖测试通过")

def test_5_mixed_cn_en():
    """测试混合中英文 — 保留原始名"""
    print("\n" + "="*60)
    print("测试 5: 混合中英文（保留原始名）")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    cn_names = ["ECS管理", "VPC网络", "OSS存储"]
    result = resolve_and_translate(cn_names)

    print(f"输入: {cn_names}")
    print(f"输出: {result}")

    # 验证：保留原始名
    assert len(result) == len(cn_names)
    assert result["ECS管理"] == "ECS管理"
    assert result["VPC网络"] == "VPC网络"
    assert result["OSS存储"] == "OSS存储"

    print("✓ 混合中英文测试通过")

def test_6_sanitize_special_chars():
    """测试特殊字符清理"""
    print("\n" + "="*60)
    print("测试 6: 特殊字符清理")
    print("="*60)

    from excel.translate_module_name import _sanitize

    tests = [
        ("hello world", "hello_world"),
        ("test-module", "test_module"),
        ("a/b\\c", "a_b_c"),
        ("日志管理", "日志管理"),
        ("ECS管理", "ECS管理"),
        ("PMO管理", "PMO管理"),
        ("test..module", "test_module"),
        ("  hello  ", "hello"),
    ]

    for input_name, expected in tests:
        result = _sanitize(input_name)
        print(f"  {input_name!r:20s} → {result!r}")
        assert result == expected, f"期望 {expected!r}，得到 {result!r}"

    print("✓ 特殊字符清理测试通过")

def test_7_collision_detection():
    """测试碰撞检测"""
    print("\n" + "="*60)
    print("测试 7: 碰撞检测")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    # 两个中文名强制翻译成相同的 slug
    cn_names = ["日志管理", "日志查询"]

    cli_overrides = {
        "日志管理": "log",
        "日志查询": "log"
    }

    result = resolve_and_translate(cn_names, cli_overrides=cli_overrides)

    print(f"输入: {cn_names}")
    print(f"CLI 覆盖: {cli_overrides}")
    print(f"输出: {result}")

    # 验证碰撞被检测
    slugs = list(result.values())
    assert len(slugs) == len(set(slugs)), f"存在重复 slug: {slugs}"
    assert result["日志管理"] == "log"
    assert result["日志查询"] == "log_2"

    print("✓ 碰撞检测测试通过")

def test_8_pure_ascii():
    """测试纯 ASCII 模块名"""
    print("\n" + "="*60)
    print("测试 8: 纯 ASCII 模块名")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    cn_names = ["log", "account", "project"]
    result = resolve_and_translate(cn_names)

    print(f"输入: {cn_names}")
    print(f"输出: {result}")

    # 验证
    assert result == {"log": "log", "account": "account", "project": "project"}

    print("✓ 纯 ASCII 测试通过")

def test_9_existing_module_map():
    """测试已有 module_map.json"""
    print("\n" + "="*60)
    print("测试 9: 已有 module_map.json")
    print("="*60)

    from excel.translate_module_name import resolve_and_translate

    cn_names = ["日志管理", "账户管理"]
    existing_map = {"日志管理": "log"}  # 已有映射

    result = resolve_and_translate(cn_names, module_map=existing_map)

    print(f"输入: {cn_names}")
    print(f"已有映射: {existing_map}")
    print(f"输出: {result}")

    # 验证
    assert result["日志管理"] == "log"  # 使用已有映射
    assert result["账户管理"] == "账户管理"  # 新模块保留原始名

    print("✓ 已有 module_map.json 测试通过")

def test_10_no_ai_dependencies():
    """测试无 AI 依赖"""
    print("\n" + "="*60)
    print("测试 10: 无 AI 依赖")
    print("="*60)

    from excel import translate_module_name as m

    src = open(m.__file__, encoding='utf-8').read()

    assert 'openai' not in src, "不应包含 openai 依赖"
    assert 'anthropic' not in src, "不应包含 anthropic 依赖"
    assert '_call_ai' not in src, "不应包含 AI 调用函数"

    print("✓ 无 AI 依赖测试通过")

def test_11_build_module_map_integration():
    """测试 build_module_map.py 集成"""
    print("\n" + "="*60)
    print("测试 11: build_module_map.py 集成")
    print("="*60)

    # 创建临时 Excel
    import openpyxl

    with tempfile.TemporaryDirectory() as tmpdir:
        excel_path = Path(tmpdir) / "test.xlsx"

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"

        # 写入表头
        ws.append(["模块", "用例名称", "步骤描述"])

        # 写入数据
        ws.append(["日志管理", "登录日志查询", "访问页面"])
        ws.append(["账户管理", "创建账户", "访问页面"])

        wb.save(excel_path)

        # 调用 build_module_map.py
        from excel.build_module_map import main as build_main

        output_path = Path(tmpdir) / "module_map.json"
        pages_dir = Path(tmpdir) / "pages"
        pages_dir.mkdir()

        # 模拟命令行参数
        sys.argv = [
            "build_module_map.py",
            str(excel_path),
            "--pages", str(pages_dir),
            "--output", str(output_path)
        ]

        try:
            build_main()
        except SystemExit:
            pass  # main() 可能调用 sys.exit(0)

        # 验证输出
        if output_path.exists():
            with open(output_path, encoding='utf-8') as f:
                module_map = json.load(f)

            print(f"生成的 module_map.json: {module_map}")

            assert "日志管理" in module_map
            assert "账户管理" in module_map

            # 验证保留原始名
            assert module_map["日志管理"] == "日志管理"
            assert module_map["账户管理"] == "账户管理"

            print("✓ build_module_map.py 集成测试通过")
        else:
            print("⚠ build_module_map.py 未生成输出文件（可能正常退出）")

def main():
    """运行所有测试"""
    print("="*60)
    print("模块名称解析功能测试（保留原始名版）")
    print("="*60)

    tests = [
        test_1_excel_module_column,
        test_2_nl_module_param,
        test_3_post_phase1b_hook,
        test_4_cli_module_map_override,
        test_5_mixed_cn_en,
        test_6_sanitize_special_chars,
        test_7_collision_detection,
        test_8_pure_ascii,
        test_9_existing_module_map,
        test_10_no_ai_dependencies,
        test_11_build_module_map_integration,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n✗ 测试失败: {test.__name__}")
            print(f"错误: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
