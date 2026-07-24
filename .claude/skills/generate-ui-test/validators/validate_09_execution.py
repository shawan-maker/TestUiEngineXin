#!/usr/bin/env python3
"""
Phase 9: 运行分析器 (validate_09_execution.py)

分析测试运行结果，分类记录问题，输出 JSON 供 HTML 联合报告消费。
**不再阻断管线**（始终 exit 0），纯分析+学习角色。

分析维度:
  R6.1 运行报告路径 (report/run_report/)
  R6.2 失败分类处理 (执行问题 vs 断言问题 vs 环境问题)
  R6.3 运行轮次统计（不再触发自动修复）
  R6.4 自学习记录 (失败/成功模式)

用法:
    python validate_09_execution.py <project_dir>

退出码: 始终 0（纯分析，不阻断）
"""

import argparse
import glob
import json
import os
import re
import sys
from typing import List, Tuple


# ============================================================================
# R6.1 运行报告路径检查
# ============================================================================

def check_r6_1_report_path(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R6.1: 运行报告输出至 report/run_report/ 目录"""
    errors = []
    warnings = []
    info = []

    run_report_dir = os.path.join(project_dir, 'report', 'run_report')

    if os.path.isdir(run_report_dir):
        # 统计报告文件
        report_files = []
        for ext in ('*.html', '*.md', '*.json', '*.txt'):
            report_files.extend(glob.glob(os.path.join(run_report_dir, ext)))

        if report_files:
            info.append(f"[R6.1] 运行报告目录存在，包含 {len(report_files)} 个报告文件")
            for f in sorted(report_files)[:5]:
                rel = os.path.relpath(f, project_dir)
                size = os.path.getsize(f)
                info.append(f"[R6.1]   {rel} ({size} bytes)")
        else:
            warnings.append(
                "[R6.1] report/run_report/ 目录存在但为空，请先运行测试"
            )
    else:
        # 检查是否有其他位置的运行报告
        report_dir = os.path.join(project_dir, 'report')
        if os.path.isdir(report_dir):
            subdirs = [d for d in os.listdir(report_dir)
                       if os.path.isdir(os.path.join(report_dir, d))]
            if subdirs:
                warnings.append(
                    f"[R6.1] report/ 下无 run_report/ 子目录，"
                    f"现有子目录: {', '.join(subdirs)}"
                )
            else:
                warnings.append("[R6.1] report/run_report/ 目录不存在，尚未运行过测试")
        else:
            info.append("[R6.1] report/ 目录不存在（首次运行前正常）")

    return errors, warnings, info


# ============================================================================
# R6.2 失败分类处理检查
# ============================================================================

def check_r6_2_failure_classification(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R6.2: 检查运行日志中的失败分类"""
    errors = []
    warnings = []
    info = []

    # 查找运行日志
    log_files = []
    for pattern in ['ui_log.txt', 'files/logs/*.log', 'report/run_report/*.log']:
        log_files.extend(glob.glob(os.path.join(project_dir, pattern)))

    if not log_files:
        info.append("[R6.2] 未找到运行日志，跳过失败分类检查")
        return errors, warnings, info

    # 分析日志内容
    execution_errors = []
    assertion_errors = []

    # 执行问题关键词
    exec_patterns = [
        re.compile(r'timeout', re.IGNORECASE),
        re.compile(r'element.?not.?found', re.IGNORECASE),
        re.compile(r'locator.*error', re.IGNORECASE),
        re.compile(r'waiting.*failed', re.IGNORECASE),
        re.compile(r'page.*closed', re.IGNORECASE),
        re.compile(r'net::', re.IGNORECASE),
        re.compile(r'全局变量中没有'),
        re.compile(r'variable.*not.*found', re.IGNORECASE),
        re.compile(r'关键字不在注册表'),
    ]

    # 断言问题关键词
    assert_patterns = [
        re.compile(r'assert.*fail', re.IGNORECASE),
        re.compile(r'except.*fail', re.IGNORECASE),
        re.compile(r'expect.*fail', re.IGNORECASE),
        re.compile(r'断言.*失败'),
        re.compile(r'text.*not.*found', re.IGNORECASE),
        re.compile(r'expected.*but.*got', re.IGNORECASE),
    ]

    for log_file in log_files:
        try:
            with open(log_file, encoding='utf-8', errors='replace') as f:
                for line_num, line in enumerate(f, 1):
                    for p in exec_patterns:
                        if p.search(line):
                            execution_errors.append({
                                'file': os.path.relpath(log_file, project_dir),
                                'line': line_num,
                                'text': line.strip()[:100],
                            })
                            break
                    for p in assert_patterns:
                        if p.search(line):
                            assertion_errors.append({
                                'file': os.path.relpath(log_file, project_dir),
                                'line': line_num,
                                'text': line.strip()[:100],
                            })
                            break
        except Exception:
            pass

    if execution_errors:
        info.append(f"[R6.2] 执行问题: {len(execution_errors)} 处（应自动修复）")
        for item in execution_errors[:3]:
            info.append(f"[R6.2]   {item['file']}:{item['line']} {item['text']}")
        if len(execution_errors) > 3:
            info.append(f"[R6.2]   ... 还有 {len(execution_errors) - 3} 处")

    if assertion_errors:
        warnings.append(
            f"[R6.2] 断言问题: {len(assertion_errors)} 处（应报告给用户，可能是系统 bug）"
        )
        for item in assertion_errors[:3]:
            warnings.append(f"[R6.2]   {item['file']}:{item['line']} {item['text']}")

    if not execution_errors and not assertion_errors:
        info.append("[R6.2] 运行日志中未发现失败（全部通过或未运行）")

    return errors, warnings, info


# ============================================================================
# R6.3 自动修复策略检查
# ============================================================================

def check_r6_3_auto_fix(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R6.3: 统计运行轮次（纯记录，不再触发自动修复）"""
    errors = []
    warnings = []
    info = []

    # 查找多轮运行日志
    log_pattern = os.path.join(project_dir, 'files', 'logs', '*.log')
    log_files = sorted(glob.glob(log_pattern))

    if len(log_files) <= 1:
        info.append("[R6.3] 未发现多轮修复记录（单轮或无日志）")
        return errors, warnings, info

    info.append(f"[R6.3] 发现 {len(log_files)} 个运行日志文件")

    if len(log_files) > 3:
        info.append(
            f"[R6.3] 运行轮次 ({len(log_files)}) 超过 3 轮，"
            f"建议人工排查根因（不再有自动修复）"
        )

    return errors, warnings, info


# ============================================================================
# R6.4 自学习记录检查
# ============================================================================

def check_r6_4_learning_records(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """R6.4: 检查自学习机制的记录文件"""
    errors = []
    warnings = []
    info = []

    probe_dir = os.path.join(project_dir, '_probe')

    # 检查学习日志
    learn_log = os.path.join(probe_dir, 'learn_log.json')
    if os.path.isfile(learn_log):
        try:
            with open(learn_log, encoding='utf-8') as f:
                learn_data = json.load(f)

            success_patterns = learn_data.get('success_patterns', [])
            failure_patterns = learn_data.get('failure_patterns', [])
            user_corrections = learn_data.get('user_corrections', [])

            info.append(
                f"[R6.4] 自学习记录: "
                f"{len(success_patterns)} 成功模式, "
                f"{len(failure_patterns)} 失败模式, "
                f"{len(user_corrections)} 用户纠正"
            )

            # 检查累计 3 次失败标记
            for pattern in failure_patterns:
                count = pattern.get('count', 0)
                if count >= 3 and not pattern.get('manual_review', False):
                    warnings.append(
                        f"[R6.4] 失败模式 \"{pattern.get('pattern', '?')}\" "
                        f"累计 {count} 次但未标记为'需人工确认'"
                    )
                elif count >= 3:
                    info.append(
                        f"[R6.4] 失败模式 \"{pattern.get('pattern', '?')}\" "
                        f"累计 {count} 次，已标记需人工确认 ✓"
                    )

        except Exception as e:
            warnings.append(f"[R6.4] 无法解析 learn_log.json: {e}")
    else:
        info.append("[R6.4] 未找到 learn_log.json（首次运行前正常）")

    # 检查项目级知识库更新
    project_kb = os.path.join(probe_dir, 'knowledge.json')
    if os.path.isfile(project_kb):
        try:
            with open(project_kb, encoding='utf-8') as f:
                kb_data = json.load(f)
            # 统计条目数
            total = 0
            for section in ('single_step', 'multi_step', 'composite'):
                items = kb_data.get(section, {})
                if isinstance(items, dict):
                    total += len(items)
            info.append(f"[R6.4] 项目级知识库: {total} 个模板条目")
        except Exception:
            pass

    return errors, warnings, info


# ============================================================================
# 主校验入口
# ============================================================================

def validate_execution(project_dir: str) -> Tuple[List[str], List[str], List[str]]:
    """Phase 9 主校验入口"""
    all_errors = []
    all_warnings = []
    all_info = []

    # R6.1: 运行报告路径
    e, w, i = check_r6_1_report_path(project_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R6.2: 失败分类
    e, w, i = check_r6_2_failure_classification(project_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R6.3: 自动修复策略
    e, w, i = check_r6_3_auto_fix(project_dir)
    all_errors.extend(e)
    all_warnings.extend(w)
    all_info.extend(i)

    # R6.4: 自学习记录
    e, w, i = check_r6_4_learning_records(project_dir)
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
        description="UIEngine Phase 9 运行验证器"
    )
    parser.add_argument(
        'project_dir',
        help="项目根目录路径"
    )
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    errors, warnings, info = validate_execution(project_dir)

    print("=" * 70)
    print(f"UIEngine Execution Analysis Report (Phase 9)")
    print(f"Project: {os.path.basename(project_dir)}")
    print("=" * 70)

    for msg in info:
        print(f"  [INFO] {msg}")

    for msg in warnings:
        print(f"  [WARN] {msg}")

    for msg in errors:
        print(f"  [ERR]  {msg}")

    print("-" * 70)
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s), {len(info)} info")
    print("Analyzed: R6.1, R6.2, R6.3, R6.4")
    print("=" * 70)

    # 输出 JSON 供 HTML 联合报告消费
    _export_phase9_json(project_dir, errors, warnings, info)

    # 纯分析模式：始终 exit 0，不阻断管线
    sys.exit(0)


def _export_phase9_json(project_dir, errors, warnings, info):
    """导出 Phase 9 分析结果到 JSON（供 generate_issues_report.py 消费）"""
    import json as _json

    phase9_data = {
        'errors': errors,
        'warnings': warnings,
        'info': info,
        'error_count': len(errors),
        'warning_count': len(warnings),
    }

    output_path = os.path.join(project_dir, '_probe', 'phase9_analysis.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            _json.dump(phase9_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # JSON 输出失败不影响主流程


if __name__ == '__main__':
    main()
