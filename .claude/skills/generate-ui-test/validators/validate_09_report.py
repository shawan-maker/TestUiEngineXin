#!/usr/bin/env python3
"""
Phase 9: 报告生成验证器 (validate_09_report.py)

校验 generate_report.py 生成的报告是否符合 R5.x 规范：
  R5.1 报告路径正确 (report/generate_report/generation_report.html)
  R5.2 报告格式正确 (HTML 自包含、模块可收起、用例可收起、步骤表格 9 列)
  R5.3 探测结果标记完整 (✅/❌/—，仅三种状态)
  R5.4 探测来源标注 (知识库/L3/AI生成)
  R5.5 失败步骤备注建议 (包含文件路径)
  R5.6 实际数据/实际定位器列变量解析完整 (不含未解析的 ${group.field})

用法:
    python validate_09_report.py <project_dir>

退出码: 0 = 全部通过, 1 = 有 error 级别违规
"""

import argparse
import os
import re
import sys
from typing import List, Tuple


# ============================================================================
# R5.1 报告路径检查
# ============================================================================

def check_r5_1_report_path(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R5.1: 报告输出至 report/generate_report/generation_report.html"""
    errors = []
    warnings = []
    info = []

    expected_path = os.path.join(
        project_dir, 'report', 'generate_report', 'generation_report.html')

    if os.path.isfile(expected_path):
        size = os.path.getsize(expected_path)
        info.append(
            f"[R5.1] 报告文件存在: report/generate_report/"
            f"generation_report.html ({size} bytes)")
    else:
        # 检查是否有旧版 .md 报告
        md_path = expected_path.replace('.html', '.md')
        report_dir = os.path.join(project_dir, 'report')
        found = []
        if os.path.isdir(report_dir):
            for root, _, files in os.walk(report_dir):
                for f in files:
                    if f.startswith('generation_report'):
                        found.append(os.path.relpath(
                            os.path.join(root, f), project_dir))

        if os.path.isfile(md_path):
            warnings.append(
                "[R5.1] 发现旧版 MD 格式报告，请重新生成 HTML 格式报告至 "
                "report/generate_report/generation_report.html")
        elif found:
            warnings.append(
                f"[R5.1] 报告文件未在预期路径找到。"
                f"期望: generation_report.html，"
                f"实际找到: {', '.join(found[:3])}")
        else:
            errors.append(
                "[R5.1] 未找到生成报告。请先运行 generate_report.py "
                "生成报告至 report/generate_report/generation_report.html")

    return errors, warnings, info


# ============================================================================
# R5.2 报告格式检查
# ============================================================================

def check_r5_2_report_format(report_path: str) -> Tuple[List[str], List[str], List[str]]:
    """R5.2: 报告格式 — HTML 自包含、模块可收起、用例可收起、步骤表格"""
    errors = []
    warnings = []
    info = []

    if not os.path.isfile(report_path):
        return errors, warnings, info

    try:
        with open(report_path, encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        errors.append(f"[R5.2] 无法读取报告文件: {e}")
        return errors, warnings, info

    # 检查是否为 HTML
    if '<!DOCTYPE html>' not in content and '<html' not in content:
        errors.append("[R5.2] 报告不是 HTML 格式，请重新生成")
        return errors, warnings, info

    # 检查自包含（内联 CSS）
    if '<style>' not in content:
        warnings.append("[R5.2] 报告缺少内联 CSS（<style> 标签），可能不是自包含 HTML")

    # 检查标题
    if 'UIEngine' not in content and '脚本生成报告' not in content:
        warnings.append("[R5.2] 报告缺少主标题")

    # 检查模块级可收起
    module_details = len(re.findall(r'<details\s+class="module"', content))
    if module_details == 0:
        # 兼容旧的无 class 写法
        module_details = content.count('<details>')
        if module_details == 0:
            warnings.append("[R5.2] 报告缺少模块级 <details> 可收起标签")

    # 检查用例级可收起
    case_details = len(re.findall(r'<details\s+class="case"', content))

    # 检查步骤表格
    table_count = content.count('<table>')
    if table_count == 0:
        warnings.append("[R5.2] 报告缺少步骤表格 (<table>)")

    # 检查表头列数（应有 9 列）
    th_count = len(re.findall(r'<th>', content))
    # 每个用例表有 9 个 th，但多个用例共享一个 thead，所以 th 数应是 9 的倍数
    # 或者每个用例都有自己的表
    if th_count > 0 and th_count % 9 != 0:
        warnings.append(
            f"[R5.2] 步骤表格列数不是 9（找到 {th_count} 个 <th>，"
            f"期望每表 9 列：步骤/关键字/描述/输入数据/实际数据/"
            f"元素定位/实际定位器/探测结果/备注）")

    # 检查新增列存在
    if '实际数据' not in content:
        warnings.append("[R5.2] 步骤表格缺少 '实际数据' 列")
    if '实际定位器' not in content:
        warnings.append("[R5.2] 步骤表格缺少 '实际定位器' 列")

    info.append(
        f"[R5.2] 报告格式: {module_details} 个模块, "
        f"{case_details} 个用例, {table_count} 个步骤表格")

    return errors, warnings, info


# ============================================================================
# R5.3 探测结果标记检查
# ============================================================================

def check_r5_3_probe_marks(report_path: str) -> Tuple[List[str], List[str], List[str]]:
    """R5.3: 探测结果标记 — ✅/❌/—（仅三种状态）"""
    errors = []
    warnings = []
    info = []

    if not os.path.isfile(report_path):
        return errors, warnings, info

    try:
        with open(report_path, encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return errors, warnings, info

    success_marks = content.count('✅')
    fail_marks = content.count('❌')

    total_marks = success_marks + fail_marks
    if total_marks == 0:
        warnings.append("[R5.3] 报告中未发现探测结果标记 (✅/❌)")
    else:
        info.append(
            f"[R5.3] 探测结果标记: ✅={success_marks}, ❌={fail_marks}")

    # 检查探测结果列存在
    if '探测结果' not in content:
        warnings.append("[R5.3] 报告表格缺少 '探测结果' 列")

    return errors, warnings, info


# ============================================================================
# R5.4 不可信定位器标记检查
# ============================================================================

def check_r5_4_source_marks(report_path: str) -> Tuple[List[str], List[str], List[str]]:
    """R5.4: 探测成功的步骤应标注来源（知识库/L3/AI生成）"""
    errors = []
    warnings = []
    info = []

    if not os.path.isfile(report_path):
        return errors, warnings, info

    try:
        with open(report_path, encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return errors, warnings, info

    # 检查来源标注关键字是否存在
    has_source = any(kw in content for kw in
                     ['知识库', 'AI生成', 'L3:', 'knowledge'])
    if has_source:
        info.append("[R5.4] 报告包含探测来源标注")
    else:
        warnings.append("[R5.4] 报告缺少探测来源标注（知识库/L3/AI生成）")

    return errors, warnings, info


# ============================================================================
# R5.5 失败步骤备注检查
# ============================================================================

def check_r5_5_failure_remarks(report_path: str) -> Tuple[List[str], List[str], List[str]]:
    """R5.5: 探测失败的步骤必须在备注列提供修改建议"""
    errors = []
    warnings = []
    info = []

    if not os.path.isfile(report_path):
        return errors, warnings, info

    try:
        with open(report_path, encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return errors, warnings, info

    # 找到所有 st-fail 行，检查后续备注
    fail_rows = content.count('<td class="st-fail">❌</td>')

    # 统计有备注的失败行（备注列包含文本内容）
    # 匹配模式：<td class="st-fail">❌</td> 后面紧跟 <td>备注内容</td>
    fail_with_remark = len(re.findall(
        r'<td class="st-fail">.*?</td>\s*<td>[^<]+',
        content, re.DOTALL))

    if fail_rows > 0:
        info.append(
            f"[R5.5] 失败步骤: {fail_rows} 行, "
            f"{fail_with_remark} 行有备注")
        if fail_with_remark < fail_rows:
            warnings.append(
                f"[R5.5] {fail_rows - fail_with_remark} 个 ❌ "
                f"缺少备注 (应提供修改建议及文件路径)")

    return errors, warnings, info


# ============================================================================
# R5.6 实际数据/实际定位器列变量解析检查
# ============================================================================

def check_r5_6_resolved_columns(report_path: str) -> Tuple[List[str], List[str], List[str]]:
    """R5.6: '实际数据'和'实际定位器'列不应包含未解析的 ${group.field} 变量引用

    这两列应该显示从 data/pages YAML 解析后的实际值。
    如果仍然显示 ${...} 引用，说明变量解析失败（可能是 pages YAML 未加载、
    group 名不匹配、或报告生成器 bug）。
    """
    errors = []
    warnings = []
    info = []

    if not os.path.isfile(report_path):
        return errors, warnings, info

    try:
        with open(report_path, encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return errors, warnings, info

    # 按用例提取行数据
    # 结构: <summary>用例标题</summary> ... <tr>步骤行</tr> ...
    case_pattern = re.compile(
        r'<summary>.*?</summary>\s*<div class="case-body">\s*<table>.*?'
        r'<tbody>(.*?)</tbody>',
        re.DOTALL)
    row_pattern = re.compile(r'<tr(?:\s[^>]*)?>(.*?)</tr>', re.DOTALL)
    code_pattern = re.compile(r'<code>(.*?)</code>', re.DOTALL)

    unresolved_count = 0
    total_resolved = 0
    examples = []

    for case_match in case_pattern.finditer(content):
        tbody = case_match.group(1)
        # 从 summary 提取用例名
        case_name_match = re.search(
            r'—\s*(.*?)</summary>',
            content[max(0, case_match.start()-200):case_match.start()])
        case_name = case_name_match.group(1).strip() if case_name_match else '?'

        for row_match in row_pattern.finditer(tbody):
            row_html = row_match.group(1)
            codes = code_pattern.findall(row_html)

            # 行结构: [step_num, keyword, desc, input, resolved_input,
            #           locator, resolved_locator, status, remark]
            # codes 索引: 0=keyword, 1=input, 2=resolved_input,
            #             3=locator, 4=resolved_locator

            if len(codes) < 5:
                continue

            # 检查 resolved_input (索引 2) 和 resolved_locator (索引 4)
            for col_idx, col_name in [(2, '实际数据'), (4, '实际定位器')]:
                val = codes[col_idx]
                if val == '—' or not val:
                    continue
                total_resolved += 1
                if '${' in val:
                    unresolved_count += 1
                    if len(examples) < 5:
                        examples.append(f"{case_name} → {col_name}: {val[:60]}")

    if unresolved_count > 0:
        warnings.append(
            f"[R5.6] 报告中有 {unresolved_count} 处未解析的变量引用 "
            f"(共 {total_resolved} 个解析列)")
        for ex in examples:
            warnings.append(f"  例: {ex}")
        warnings.append(
            "  原因: generate_report.py 未能从 pages/data YAML 解析变量，"
            "请检查 YAML group 名是否与 ${group.field} 匹配")
    else:
        info.append(
            f"[R5.6] 变量解析正常: {total_resolved} 个解析列均无 ${'{'}...{'}'} 残留")

    return errors, warnings, info


# ============================================================================
# 主校验入口
# ============================================================================

def validate_report(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """Phase 9 主校验入口"""
    all_errors = []
    all_warnings = []
    all_info = []

    # R5.1: 报告路径
    e, w, i = check_r5_1_report_path(project_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # 确定报告路径
    report_path = os.path.join(
        project_dir, 'report', 'generate_report', 'generation_report.html')

    if os.path.isfile(report_path):
        # R5.2: 报告格式
        e, w, i = check_r5_2_report_format(report_path)
        all_errors.extend(e)
        all_warnings.extend(w)
        all_info.extend(i)

        # R5.3: 探测结果标记
        e, w, i = check_r5_3_probe_marks(report_path)
        all_errors.extend(e)
        all_warnings.extend(w)
        all_info.extend(i)

        # R5.4: 探测来源标注
        e, w, i = check_r5_4_source_marks(report_path)
        all_errors.extend(e)
        all_warnings.extend(w)
        all_info.extend(i)

        # R5.5: 失败步骤备注
        e, w, i = check_r5_5_failure_remarks(report_path)
        all_errors.extend(e)
        all_warnings.extend(w)
        all_info.extend(i)

        # R5.6: 实际数据/实际定位器变量解析完整性
        e, w, i = check_r5_6_resolved_columns(report_path)
        all_errors.extend(e)
        all_warnings.extend(w)
        all_info.extend(i)

    return all_errors, all_warnings, all_info


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description="UIEngine Phase 9 报告生成验证器")
    parser.add_argument('project_dir', help="项目根目录路径")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    errors, warnings, info = validate_report(project_dir)

    print("=" * 70)
    print("UIEngine Report Validation Report (Phase 9)")
    print(f"Project: {os.path.basename(project_dir)}")
    print("=" * 70)

    for msg in info:
        print(f"  [INFO] {msg}")
    for msg in warnings:
        print(f"  [WARN] {msg}")
    for msg in errors:
        print(f"  [ERR]  {msg}")

    print("-" * 70)
    print(f"Summary: {len(errors)} error(s), "
          f"{len(warnings)} warning(s), {len(info)} info")
    print("Checked: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6")
    print("=" * 70)

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
