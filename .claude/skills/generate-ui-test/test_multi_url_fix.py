#!/usr/bin/env python3
"""
多URL同名标签覆盖问题 - 自验证脚本

测试场景：
- 项目管理模块有2个URL（list页面和config页面）
- 两个URL都有"项目类型"字段，但locator不同
- 验证修改后不会覆盖，按page_slug精确匹配
"""

import sys
import json
import tempfile
import os
from pathlib import Path

# 添加tools目录到path
tools_dir = Path(__file__).parent / 'tools'
sys.path.insert(0, str(tools_dir))

from _element_resolver import ElementResolver
from _case_generator import CaseGenerator

def create_mock_discovery():
    """创建模拟的discovery JSON（2个URL，都有"项目类型"）"""
    return {
        "module": "project_manage",
        "cn_name": "项目管理",
        "pages": [
            {
                "name": "list",
                "url": "http://example.com/project/list",
                "list_page": {
                    "inputs": [
                        {
                            "label": "项目类型",
                            "locator": "xpath=//input[@id='type1']",
                            "verified": True,
                            "type": "input-generic"
                        }
                    ]
                },
                "containers": []
            },
            {
                "name": "config",
                "url": "http://example.com/project/config",
                "list_page": {
                    "inputs": [
                        {
                            "label": "项目类型",
                            "locator": "xpath=//input[@id='type2']",
                            "verified": True,
                            "type": "input-generic"
                        }
                    ]
                },
                "containers": []
            }
        ]
    }

def test_multi_url_no_overwrite():
    """测试：多URL同名标签不覆盖"""
    print("=" * 60)
    print("测试：多URL同名标签不覆盖")
    print("=" * 60)

    # 创建临时discovery文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        discovery_data = create_mock_discovery()
        json.dump(discovery_data, f, ensure_ascii=False, indent=2)
        discovery_path = f.name

    try:
        # 1. 加载ElementResolver
        resolver = ElementResolver([discovery_path])

        print(f"\n✓ ElementResolver加载成功")
        print(f"  - module_slug: {resolver.module_slug}")
        print(f"  - element_map大小: {len(resolver.get_element_map())}")
        print(f"  - page_element_map大小: {len(resolver.get_page_element_map())}")
        print(f"  - page_url_map: {resolver.get_page_url_map()}")

        # 2. 测试url_to_page_slug
        url1 = "http://example.com/project/list"
        url2 = "http://example.com/project/config"
        slug1 = resolver.url_to_page_slug(url1)
        slug2 = resolver.url_to_page_slug(url2)

        print(f"\n✓ url_to_page_slug测试:")
        print(f"  - {url1} → {slug1}")
        print(f"  - {url2} → {slug2}")
        assert slug1 == 'list', f"Expected 'list', got '{slug1}'"
        assert slug2 == 'config', f"Expected 'config', got '{slug2}'"

        # 3. 测试find_element_by_page
        e1 = resolver.find_element_by_page('list', 'list_page', '项目类型')
        e2 = resolver.find_element_by_page('config', 'list_page', '项目类型')

        print(f"\n✓ find_element_by_page测试:")
        print(f"  - list页面: {e1.locator}")
        print(f"  - config页面: {e2.locator}")

        assert e1 is not None, "list页面的元素应该存在"
        assert e2 is not None, "config页面的元素应该存在"
        assert e1.locator == "xpath=//input[@id='type1']", f"Expected type1, got {e1.locator}"
        assert e2.locator == "xpath=//input[@id='type2']", f"Expected type2, got {e2.locator}"
        assert e1.group == "project_manage_list_elements", f"Expected project_manage_list_elements, got {e1.group}"
        assert e2.group == "project_manage_config_elements", f"Expected project_manage_config_elements, got {e2.group}"

        # 4. 测试CaseGenerator的page-aware查找
        generator = CaseGenerator(resolver, 'project_manage')

        print(f"\n✓ CaseGenerator初始化成功")
        print(f"  - discovery_page_element_map大小: {len(generator._discovery_page_element_map)}")

        # 4.1 设置page context为list
        generator.set_page_context(url1)
        elem1 = generator._lookup_discovery_element('项目类型')
        print(f"\n✓ 设置context为list后查找'项目类型':")
        print(f"  - 结果: {elem1['locator'] if elem1 else 'None'}")
        assert elem1 is not None, "应该找到list页面的元素"
        assert elem1['locator'] == "xpath=//input[@id='type1']", f"Expected type1, got {elem1['locator']}"

        # 4.2 设置page context为config
        generator.set_page_context(url2)
        elem2 = generator._lookup_discovery_element('项目类型')
        print(f"\n✓ 设置context为config后查找'项目类型':")
        print(f"  - 结果: {elem2['locator'] if elem2 else 'None'}")
        assert elem2 is not None, "应该找到config页面的元素"
        assert elem2['locator'] == "xpath=//input[@id='type2']", f"Expected type2, got {elem2['locator']}"

        # 4.3 测试子串搜索也按page过滤
        generator.set_page_context(url1)
        elem3 = generator._discovery_lookup('项目类')  # 子串
        print(f"\n✓ 子串搜索'项目类'（list context）:")
        print(f"  - 结果: {elem3['locator'] if elem3 else 'None'}")
        assert elem3 is not None, "应该找到list页面的元素"
        assert elem3['locator'] == "xpath=//input[@id='type1']", f"Expected type1, got {elem3['locator']}"

        generator.set_page_context(url2)
        elem4 = generator._discovery_lookup('项目类')  # 子串
        print(f"\n✓ 子串搜索'项目类'（config context）:")
        print(f"  - 结果: {elem4['locator'] if elem4 else 'None'}")
        assert elem4 is not None, "应该找到config页面的元素"
        assert elem4['locator'] == "xpath=//input[@id='type2']", f"Expected type2, got {elem4['locator']}"

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！多URL同名标签覆盖问题已修复")
        print("=" * 60)

    finally:
        # 清理临时文件
        os.unlink(discovery_path)

if __name__ == '__main__':
    try:
        test_multi_url_no_overwrite()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 测试异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
