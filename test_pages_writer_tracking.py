#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 4: 追踪 PagesWriter 为什么没有写入 el-select 字段

追踪点:
1. case_generator.py 是否调用了 _track_field 注册这些字段
2. PagesWriter.write_pages_yaml 是否收到了 required_fields
3. PagesWriter 为什么跳过了这些字段
"""

import sys
import os
import re

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_DIR = os.path.join(os.path.dirname(__file__), 'examples', 'ecsCloud')
SKILL_DIR = os.path.join(os.path.dirname(__file__), '.claude', 'skills', 'generate-ui-test')


def check_case_generator_tracking():
    """检查 case_generator.py 中 el-select 的 _track_field 调用"""
    print("=" * 80)
    print("[1] 检查 case_generator.py 的 _track_field 注册逻辑")
    print("=" * 80)

    case_gen_path = os.path.join(SKILL_DIR, 'tools', 'generation', 'case_generator.py')
    with open(case_gen_path, encoding='utf-8') as f:
        content = f.read()

    # 查找 _emit_el_select_steps 函数
    print("\n_emit_el_select_steps 函数中的 _track_field 调用:")

    # 提取函数体
    func_match = re.search(
        r'def _emit_el_select_steps\(self.*?\n(.*?)(?=\n    def |\Z)',
        content,
        re.DOTALL
    )

    if func_match:
        func_body = func_match.group(1)
        # 查找所有 _track_field 调用
        track_calls = re.findall(
            r"self\._track_field\(group,\s*f'\{field\}(_\w+)',\s*locator=f'xpath=\{(\w+)\}'",
            func_body
        )

        print(f"  找到 {len(track_calls)} 个 _track_field 调用:")
        for suffix, xpath_var in track_calls:
            print(f"    - field{suffix} ← xpath={{{xpath_var}}}")

        # 检查是否有条件跳过
        print("\n  检查是否有条件跳过逻辑:")
        if 'if ' in func_body and '_track_field' in func_body:
            # 查找 _track_field 前的 if 语句
            if_patterns = re.findall(
                r'if (.*?)[:\n].*?self\._track_field',
                func_body,
                re.DOTALL
            )
            if if_patterns:
                for pat in if_patterns[:3]:  # 只显示前3个
                    print(f"    - if {pat[:60]}")
            else:
                print(f"    ✓ 无条件跳过")
        else:
            print(f"    ✓ 无条件跳过")
    else:
        print("  ❌ 未找到 _emit_el_select_steps 函数")

    print()


def check_pages_writer_logic():
    """检查 PagesWriter 的写入逻辑"""
    print("=" * 80)
    print("[2] 检查 PagesWriter.write_pages_yaml 写入逻辑")
    print("=" * 80)

    writer_path = os.path.join(SKILL_DIR, 'tools', 'generation', 'pages_writer.py')
    with open(writer_path, encoding='utf-8') as f:
        content = f.read()

    # 查找 write_pages_yaml 函数
    func_match = re.search(
        r'def write_pages_yaml\(self.*?\n(.*?)(?=\n    def |\Z)',
        content,
        re.DOTALL
    )

    if func_match:
        func_body = func_match.group(1)

        print("\nwrite_pages_yaml 函数关键逻辑:")

        # 1. 检查 required_fields 参数处理
        print("\n  [1] required_fields 参数处理:")
        if 'required_fields' in func_body:
            print(f"    ✓ 接收 required_fields 参数")
            # 查找如何处理 required_fields
            if 'for ' in func_body and 'required_fields' in func_body:
                print(f"    ✓ 遍历 required_fields")
            else:
                print(f"    ❓ 未找到遍历逻辑")

        # 2. 检查是否有过滤条件
        print("\n  [2] 字段过滤条件:")
        filter_patterns = [
            (r'if not .*?locator', 'locator 为空时跳过'),
            (r'if .*?pending', 'pending group 处理'),
            (r'if .*?group.*?not in', 'group 不存在时跳过'),
            (r'if .*?skip', '显式跳过逻辑'),
        ]

        for pattern, desc in filter_patterns:
            if re.search(pattern, func_body):
                print(f"    - {desc}")

        # 3. 检查 YAML 写入逻辑
        print("\n  [3] YAML 写入逻辑:")
        if 'yaml.dump' in func_body or 'yaml.safe_dump' in func_body:
            print(f"    ✓ 使用 yaml.dump/safe_dump")
        elif 'write(' in func_body:
            print(f"    ✓ 手动写入 YAML")
        else:
            print(f"    ❓ 未找到写入逻辑")

        # 4. 检查 append 模式
        print("\n  [4] append 参数处理:")
        if 'append' in func_body:
            if 'append=True' in func_body or 'if append' in func_body:
                print(f"    ✓ 支持 append 模式（追加到现有文件）")
            else:
                print(f"    ❓ append 参数未使用")
        else:
            print(f"    ❌ 不支持 append 模式")

        # 5. 提取关键代码片段
        print("\n  [5] 关键代码片段（前 50 行）:")
        lines = func_body.split('\n')[:50]
        for i, line in enumerate(lines, 1):
            if line.strip() and not line.strip().startswith('#'):
                print(f"    {i:3d} {line}")

    else:
        print("  ❌ 未找到 write_pages_yaml 函数")

    print()


def check_pipeline_execution():
    """检查 pipeline 执行日志中的 PagesWriter 调用"""
    print("=" * 80)
    print("[3] 检查 pipeline 执行日志")
    print("=" * 80)

    probe_dir = os.path.join(PROJECT_DIR, '_probe')

    # 查找 Phase 5 日志
    phase5_logs = [
        'phase_5_generate_tool.log',
        'phase5_generate_tool.log',
        'phase_5_tool.log',
    ]

    for log_name in phase5_logs:
        log_path = os.path.join(probe_dir, log_name)
        if os.path.exists(log_path):
            print(f"\n找到 Phase 5 日志: {log_name}")

            with open(log_path, encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 查找 PagesWriter 相关日志
            print("\n  PagesWriter 相关日志:")
            writer_logs = [
                line for line in content.split('\n')
                if 'PagesWriter' in line or 'write_pages' in line or '_track_field' in line
            ]

            if writer_logs:
                for log in writer_logs[:20]:  # 显示前20行
                    print(f"    {log}")
            else:
                print(f"    ❌ 未找到 PagesWriter 日志")

            # 查找 el-select 相关日志
            print("\n  el-select 相关日志:")
            el_select_logs = [
                line for line in content.split('\n')
                if 'el-select' in line.lower() or '7ddbe1' in line
            ]

            if el_select_logs:
                for log in el_select_logs[:20]:
                    print(f"    {log}")
            else:
                print(f"    ❌ 未找到 el-select 日志")

            # 查找 field_7ddbe1 相关日志
            print("\n  field_7ddbe1 相关日志:")
            field_logs = [
                line for line in content.split('\n')
                if 'field_7ddbe1' in line
            ]

            if field_logs:
                for log in field_logs[:10]:
                    print(f"    {log}")
            else:
                print(f"    ❌ 未找到 field_7ddbe1 日志")

            break
    else:
        print("\n  ❌ 未找到 Phase 5 日志文件")

    print()


def check_required_fields_registration():
    """检查 required_fields 是否正确注册"""
    print("=" * 80)
    print("[4] 检查 required_fields 注册机制")
    print("=" * 80)

    # 检查 case_generator.py 中的 required_fields 属性
    case_gen_path = os.path.join(SKILL_DIR, 'tools', 'generation', 'case_generator.py')
    with open(case_gen_path, encoding='utf-8') as f:
        content = f.read()

    print("\nrequired_fields 属性定义:")
    if 'self.required_fields' in content:
        # 查找初始化
        init_match = re.search(
            r'self\.required_fields\s*=\s*(\{.*?\}|\w+\(.*?\))',
            content
        )
        if init_match:
            print(f"  初始化: self.required_fields = {init_match.group(1)[:80]}")

        # 查找 _track_field 中的注册逻辑
        print("\n_track_field 函数中的注册逻辑:")
        track_match = re.search(
            r'def _track_field\(self.*?\n(.*?)(?=\n    def |\Z)',
            content,
            re.DOTALL
        )
        if track_match:
            track_body = track_match.group(1)
            if 'required_fields' in track_body:
                print(f"  ✓ _track_field 更新 required_fields")
                # 提取关键行
                for line in track_body.split('\n')[:15]:
                    if 'required_fields' in line:
                        print(f"    {line.strip()}")
            else:
                print(f"  ❌ _track_field 未更新 required_fields")

    print()


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("PagesWriter 写入追踪诊断")
    print("=" * 80 + "\n")

    check_case_generator_tracking()
    check_pages_writer_logic()
    check_pipeline_execution()
    check_required_fields_registration()

    print("=" * 80)
    print("诊断完成")
    print("=" * 80)
