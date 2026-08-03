#!/usr/bin/env python3
"""测试 Phase 1b 提取 page_urls 功能"""

import json
import sys
import tempfile
from pathlib import Path

# 添加 tools 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'tools'))

from pipeline import PipelineContext


def test_extract_page_urls():
    """测试从 excel_parsed.json 提取 page_urls"""

    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        probe_dir = project_dir / '_probe'
        probe_dir.mkdir()

        # 创建模拟的 excel_parsed.json
        excel_parsed = [
            {
                "sheet": "Sheet1",
                "cases": [
                    {
                        "module": "计算",
                        "steps": [
                            "1. 访问 https://example.com/compute",
                            "2. 点击创建按钮",
                            "3. 填写表单"
                        ]
                    },
                    {
                        "module": "计算",
                        "steps": [
                            "1. 访问 https://example.com/compute/list",
                            "2. 查看列表"
                        ]
                    },
                    {
                        "module": "存储",
                        "steps": [
                            "1. 访问 https://example.com/storage",
                            "2. 创建存储桶"
                        ]
                    }
                ]
            }
        ]

        excel_parsed_path = probe_dir / 'excel_parsed.json'
        with open(excel_parsed_path, 'w', encoding='utf-8') as f:
            json.dump(excel_parsed, f, ensure_ascii=False, indent=2)

        # 创建初始 config.yaml（没有 page_urls）
        config_path = project_dir / 'config.yaml'
        config_path.write_text("""
# 测试配置
project_name: test-project
browser_type: chromium
""", encoding='utf-8')

        # 创建 PipelineContext
        context = PipelineContext(
            project_dir=str(project_dir),
            excel_path=str(excel_parsed_path)
        )

        # 调用 extract_page_urls_from_excel
        print("=" * 60)
        print("测试: extract_page_urls_from_excel")
        print("=" * 60)

        page_urls = context.extract_page_urls_from_excel()

        # 验证结果
        print("\n验证结果:")
        print(f"  提取的模块数: {len(page_urls)}")
        print(f"  模块列表: {list(page_urls.keys())}")

        for module, urls in page_urls.items():
            print(f"\n  {module}:")
            for url in urls:
                print(f"    - {url}")

        # 验证 config.yaml 是否被更新
        print("\n验证 config.yaml 更新:")
        updated_config = config_path.read_text(encoding='utf-8')
        print(updated_config)

        # 断言检查
        assert len(page_urls) == 2, f"期望 2 个模块，实际 {len(page_urls)}"
        assert "计算" in page_urls, "缺少 '计算' 模块"
        assert "存储" in page_urls, "缺少 '存储' 模块"
        assert len(page_urls["计算"]) == 2, f"计算模块应有 2 个 URL，实际 {len(page_urls['计算'])}"
        assert len(page_urls["存储"]) == 1, f"存储模块应有 1 个 URL，实际 {len(page_urls['存储'])}"
        assert "page_urls:" in updated_config, "config.yaml 未被更新"

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)


def test_skip_when_exists():
    """测试当 config.yaml 已有 page_urls 时跳过"""

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        probe_dir = project_dir / '_probe'
        probe_dir.mkdir()

        # 创建 excel_parsed.json
        excel_parsed = [{
            "sheet": "Sheet1",
            "cases": [{
                "module": "新模块",
                "steps": ["1. 访问 https://new.example.com"]
            }]
        }]

        excel_parsed_path = probe_dir / 'excel_parsed.json'
        with open(excel_parsed_path, 'w', encoding='utf-8') as f:
            json.dump(excel_parsed, f, ensure_ascii=False, indent=2)

        # 创建已有 page_urls 的 config.yaml
        config_path = project_dir / 'config.yaml'
        config_path.write_text("""
# 测试配置
project_name: test-project
browser_type: chromium
page_urls:
  已有模块:
    - https://existing.example.com
""", encoding='utf-8')

        # 创建 PipelineContext
        context = PipelineContext(
            project_dir=str(project_dir),
            excel_path=str(excel_parsed_path)
        )

        # 调用 extract_page_urls_from_excel
        print("\n" + "=" * 60)
        print("测试: 当 page_urls 已存在时跳过")
        print("=" * 60)

        page_urls = context.extract_page_urls_from_excel()

        # 验证 config.yaml 未被修改
        updated_config = config_path.read_text(encoding='utf-8')
        print("\n验证 config.yaml 未被修改:")
        print(updated_config)

        # 断言检查
        assert "已有模块" in updated_config, "原有配置被修改"
        assert "新模块" not in updated_config, "应该跳过但实际写入了"
        assert "ℹ️" in str(page_urls) or page_urls, "应该返回提取的 URLs"

        print("\n" + "=" * 60)
        print("✅ 跳过测试通过！")
        print("=" * 60)


if __name__ == '__main__':
    try:
        test_extract_page_urls()
        test_skip_when_exists()
        print("\n" + "=" * 60)
        print("🎉 所有测试都通过了！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
