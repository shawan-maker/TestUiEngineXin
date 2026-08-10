#!/usr/bin/env python3
"""调试脚本：验证 iframe 定位器 YAML 引号问题"""
import sys
import os
import tempfile
import yaml

# 添加 skill 工具路径
SKILL_DIR = r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test'
sys.path.insert(0, os.path.join(SKILL_DIR, 'tools'))

from core.xpath_utils import inject_hidden_filter, apply_hidden_filters_to_pages
from core.yaml_utils import escape_yaml_scalar


def test_iframe_locator_escaping():
    """测试 iframe 定位器的完整生命周期"""
    print("=" * 70)
    print("测试场景：iframe 定位器包含双引号 + hidden filter 包含单引号")
    print("=" * 70)
    
    # 1. 模拟 verify_engine 发现的 iframe 定位器
    raw_locator = 'xpath=//iframe[@id="confirmIframe"]'
    print(f"\n[1] 原始定位器:\n    {raw_locator}")
    
    # 2. 模拟 pages_writer 写入时的转义
    escaped = escape_yaml_scalar(raw_locator)
    print(f"\n[2] escape_yaml_scalar 后:\n    {escaped}")
    
    # 3. 写入临时 YAML 文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write(f"test_group:\n")
        f.write(f"  iframe_field: {escaped}  # iframe 定位器\n")
        f.write(f"  other_field: 'xpath=//button'\n")
        yaml_path = f.name
    
    print(f"\n[3] 写入文件:\n    {yaml_path}")
    with open(yaml_path, encoding='utf-8') as f:
        print("    内容:")
        for line in f:
            print(f"      {line.rstrip()}")
    
    # 4. 验证文件可解析
    try:
        with open(yaml_path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        print(f"\n[4] YAML 解析成功:\n    {data}")
    except yaml.YAMLError as e:
        print(f"\n[4] YAML 解析失败: {e}")
        os.unlink(yaml_path)
        return False
    
    # 5. 模拟 apply_hidden_filters_to_pages 的注入
    pages_data = {'test_group': {'iframe_field': raw_locator}}
    source_files = {'test_group': yaml_path}
    
    print(f"\n[5] 调用 apply_hidden_filters_to_pages...")
    modified = apply_hidden_filters_to_pages(pages_data, source_files, '')
    print(f"    修改了 {modified} 个定位器")
    
    # 6. 检查修改后的文件内容
    print(f"\n[6] 修改后的文件内容:")
    with open(yaml_path, encoding='utf-8') as f:
        content = f.read()
        print("    " + "\n    ".join(content.splitlines()))
    
    # 7. 验证修改后的文件是否可解析
    try:
        with open(yaml_path, encoding='utf-8') as f:
            data_after = yaml.safe_load(f)
        print(f"\n[7] 修改后 YAML 解析成功:\n    {data_after}")
        
        # 8. 验证值是否正确
        actual = data_after['test_group']['iframe_field']
        expected_hidden = "and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
        if expected_hidden in actual:
            print(f"\n[8] [OK] Hidden filter 已正确注入")
            print(f"    最终值:\n    {actual}")
        else:
            print(f"\n[8] [FAIL] Hidden filter 未注入")
            print(f"    实际值:\n    {actual}")
            return False

    except yaml.YAMLError as e:
        print(f"\n[7] [FAIL] 修改后 YAML 解析失败!\n    {e}")
        print("\n" + "=" * 70)
        print("BUG 复现成功！")
        print("=" * 70)
        print("\n根因分析:")
        print("  apply_hidden_filters_to_pages 使用行级字符串替换，")
        print("  未考虑替换后的值需要重新 escape。")
        print("\n修复方案:")
        print("  替换后调用 escape_yaml_scalar() 重新转义")
        return False
    finally:
        os.unlink(yaml_path)
    
    return True


if __name__ == '__main__':
    success = test_iframe_locator_escaping()
    sys.exit(0 if success else 1)
