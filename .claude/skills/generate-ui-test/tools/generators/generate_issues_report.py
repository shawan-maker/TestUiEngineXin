#!/usr/bin/env python3
"""
Phase 8/9 联合问题报告生成器 (generate_issues_report.py)

整合三类问题源，生成单文件 HTML 报告（内嵌 CSS，可独立打开）：
  1. Phase 5 自检层：_case_generator.py 的 repair_log + remaining
  2. Phase 8 跨文件：validate_08_scripts.py 的 violations
  3. Phase 9 运行时：auto_learn_keywords 的 failure_patterns + 运行失败

数据来源：
  - {project}/_probe/repair_log.json        ← Phase 5 自检层
  - validate_08 命令行 JSON 输出            ← Phase 8（--json 模式）
  - {project}/_probe/learn_log.json         ← Phase 9 auto_learn
  - {project}/files/logs/*.log              ← Phase 9 运行日志（可选）

用法:
    # 从已有数据源生成报告
    python generate_issues_report.py {project_dir}

    # 显式指定数据源
    python generate_issues_report.py {project_dir} \\
        --repair-log {project}/_probe/repair_log.json \\
        --phase8-json {project}/_probe/phase8_violations.json \\
        --learn-log {project}/_probe/learn_log.json

输出:
    {project}/report/issues_report/issues_YYYYMMDD_HHMMSS.html
"""

import argparse
import glob
import json
import os
import re
import sys
import datetime

try:
    import yaml
except ImportError:
    yaml = None


# ============================================================================
# 数据加载
# ============================================================================

def load_json(path):
    """安全加载 JSON，失败返回 None"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] 无法加载 {path}: {e}", file=sys.stderr)
        return None


def load_repair_log(project_dir):
    """加载 Phase 5 自检层修复日志"""
    path = os.path.join(project_dir, '_probe', 'repair_log.json')
    data = load_json(path)
    if not data:
        return {'repairs': [], 'remaining': []}
    return data


def load_phase8_violations(project_dir, explicit_path=None):
    """加载 Phase 8 violations

    优先使用 --phase8-json 显式路径；
    否则查找 {project}/_probe/phase8_violations.json
    """
    if explicit_path:
        data = load_json(explicit_path)
        return data if data else []

    path = os.path.join(project_dir, '_probe', 'phase8_violations.json')
    data = load_json(path)
    return data if data else []


def load_learn_log(project_dir):
    """加载 Phase 9 自学习日志"""
    path = os.path.join(project_dir, '_probe', 'learn_log.json')
    data = load_json(path)
    if not data:
        return {'failure_patterns': [], 'success_patterns': [], 'manual_review_needed': []}
    return data


def load_phase9_analysis(project_dir):
    """加载 Phase 9 结构化分析结果（validate_09 导出）"""
    path = os.path.join(project_dir, '_probe', 'phase9_analysis.json')
    return load_json(path) or {}


def load_runtime_failures(project_dir):
    """从最新运行日志中提取失败记录"""
    log_dir = os.path.join(project_dir, 'files', 'logs')
    log_files = sorted(glob.glob(os.path.join(log_dir, '*.log')),
                       key=os.path.getmtime, reverse=True)
    if not log_files:
        return []

    failures = []
    latest_log = log_files[0]
    error_keywords = ['ERROR', 'FAIL', 'Error', 'Exception', 'TimeoutError']

    try:
        with open(latest_log, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception:
        return []

    for i, line in enumerate(lines):
        if not any(kw in line for kw in error_keywords):
            continue

        # 提取 case/step 信息
        case_id = ''
        step_num = ''
        m_case = re.search(r'case[=:]\s*(\S+)', line, re.IGNORECASE)
        if m_case:
            case_id = m_case.group(1)
        m_step = re.search(r'step[=:]\s*(\d+)', line, re.IGNORECASE)
        if m_step:
            step_num = m_step.group(1)

        # 分类
        error_type = 'unknown'
        if re.search(r'timeout', line, re.IGNORECASE):
            error_type = 'timeout'
        elif re.search(r'element.*not.*found|locator.*error', line, re.IGNORECASE):
            error_type = 'locator_error'
        elif re.search(r'assert.*fail|except.*fail|expect', line, re.IGNORECASE):
            error_type = 'assertion_error'
        elif re.search(r'net::|page.*closed|navigation', line, re.IGNORECASE):
            error_type = 'navigation_error'

        failures.append({
            'error_type': error_type,
            'case_id': case_id,
            'step': step_num,
            'error_text': line.strip()[:200],
            'log_file': os.path.relpath(latest_log, project_dir),
        })

    return failures


# ============================================================================
# HTML 渲染
# ============================================================================

_CSS = """
body { font-family: -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
       margin: 20px; background: #fafafa; color: #333; }
h1 { border-bottom: 3px solid #1976d2; padding-bottom: 8px; }
h2 { margin-top: 32px; color: #1565c0; border-left: 4px solid #1976d2; padding-left: 12px; }
.summary { background: #fff; padding: 16px; border-radius: 6px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin: 16px 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0;
        background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
th { background: #f5f5f5; font-weight: 600; text-align: left; }
th, td { border: 1px solid #e0e0e0; padding: 8px 12px; font-size: 13px; }
tr:hover { background: #f9f9f9; }
.repaired { background: #e8f5e9; }
.remaining { background: #ffebee; }
.runtime-fail { background: #fff3e0; }
.error { color: #c62828; font-weight: 600; }
.warning { color: #ef6c00; }
.info { color: #1565c0; }
.ok { color: #2e7d32; font-weight: 600; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
         font-size: 11px; font-weight: 600; color: #fff; }
.badge-error { background: #c62828; }
.badge-warn { background: #ef6c00; }
.badge-info { background: #1565c0; }
.badge-ok { background: #2e7d32; }
.empty-msg { color: #888; font-style: italic; padding: 20px; text-align: center; }
details summary { cursor: pointer; font-weight: 600; padding: 4px 0; }
details summary:hover { color: #1565c0; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.stat-card { background: #fff; padding: 16px; border-radius: 6px; text-align: center;
             box-shadow: 0 1px 2px rgba(0,0,0,0.08); }
.stat-num { font-size: 28px; font-weight: 700; }
.stat-label { font-size: 12px; color: #666; margin-top: 4px; }
.footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e0e0e0;
          color: #999; font-size: 12px; }
"""


def _esc(text):
    """HTML 转义"""
    if not isinstance(text, str):
        text = str(text)
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def render_summary(repair_data, phase8_violations, runtime_failures, learn_log):
    """渲染概览统计"""
    repairs = repair_data.get('repairs', [])
    remaining = repair_data.get('remaining', [])
    p8_errors = [v for v in phase8_violations if v.get('severity') == 'error']
    p8_warnings = [v for v in phase8_violations if v.get('severity') == 'warning']
    fail_patterns = learn_log.get('failure_patterns', [])
    review_needed = learn_log.get('manual_review_needed', [])

    return f"""
    <div class="summary">
        <h2>概览</h2>
        <div class="stat-grid">
            <div class="stat-card">
                <div class="stat-num ok">{len(repairs)}</div>
                <div class="stat-label">Phase 5 自修复</div>
            </div>
            <div class="stat-card">
                <div class="stat-num warning">{len(remaining) + len(p8_errors)}</div>
                <div class="stat-label">待人工处理</div>
            </div>
            <div class="stat-card">
                <div class="stat-num error">{len(runtime_failures)}</div>
                <div class="stat-label">运行时失败</div>
            </div>
            <div class="stat-card">
                <div class="stat-num info">{len(review_needed)}</div>
                <div class="stat-label">需人工确认（累计≥3次）</div>
            </div>
        </div>

        <table style="margin-top: 16px;">
            <tr><th>来源</th><th>自修复</th><th>待人工</th><th>运行时失败</th></tr>
            <tr>
                <td>Phase 5 自检</td>
                <td class="ok">{len(repairs)}</td>
                <td class="warning">{len(remaining)}</td>
                <td>—</td>
            </tr>
            <tr>
                <td>Phase 8 跨文件</td>
                <td>—</td>
                <td class="{'error' if p8_errors else 'ok'}">{len(p8_errors)} errors + {len(p8_warnings)} warnings</td>
                <td>—</td>
            </tr>
            <tr>
                <td>Phase 9 运行</td>
                <td>—</td>
                <td>—</td>
                <td class="error">{len(runtime_failures)}</td>
            </tr>
            <tr style="font-weight: 600;">
                <td>合计</td>
                <td class="ok">{len(repairs)}</td>
                <td class="warning">{len(remaining) + len(p8_errors)}</td>
                <td class="error">{len(runtime_failures)}</td>
            </tr>
        </table>
    </div>
    """


def render_repairs(repair_data):
    """渲染 Phase 5 自修复记录"""
    repairs = repair_data.get('repairs', [])
    if not repairs:
        return """
        <h2>Phase 5 自修复记录</h2>
        <p class="empty-msg">无自修复记录（generate_cases 未检出问题或未运行自检层）</p>
        """

    rows = []
    for i, r in enumerate(repairs, 1):
        rows.append(f"""
            <tr class="repaired">
                <td>{i}</td>
                <td>{_esc(r.get('rule', ''))}</td>
                <td>{_esc(r.get('file', ''))}</td>
                <td>{_esc(r.get('action', ''))}</td>
                <td>{_esc(r.get('guarantee', ''))}</td>
            </tr>""")

    return f"""
    <h2>Phase 5 自修复记录（{len(repairs)} 项已修复）</h2>
    <table>
        <tr><th>#</th><th>规则</th><th>文件</th><th>操作</th><th>保障</th></tr>
        {''.join(rows)}
    </table>
    """


def render_remaining(repair_data):
    """渲染 Phase 5 未解决问题"""
    remaining = repair_data.get('remaining', [])
    if not remaining:
        return """
        <h2>Phase 5 未解决问题</h2>
        <p class="empty-msg">无未解决问题 ✓</p>
        """

    rows = []
    for i, r in enumerate(remaining, 1):
        rows.append(f"""
            <tr class="remaining">
                <td>{i}</td>
                <td>{_esc(r.get('rule', ''))}</td>
                <td>{_esc(r.get('file', ''))}</td>
                <td>{_esc(r.get('reason', ''))}</td>
                <td>{_esc(r.get('suggestion', ''))}</td>
            </tr>""")

    return f"""
    <h2>Phase 5 未解决问题（{len(remaining)} 项待人工）</h2>
    <table>
        <tr><th>#</th><th>规则</th><th>文件</th><th>原因</th><th>建议</th></tr>
        {''.join(rows)}
    </table>
    """


def render_phase8(phase8_violations):
    """渲染 Phase 8 跨文件检查问题"""
    if not phase8_violations:
        return """
        <h2>Phase 8 跨文件检查问题</h2>
        <p class="empty-msg">validate_08 未检出跨文件问题 ✓</p>
        """

    errors = [v for v in phase8_violations if v.get('severity') == 'error']
    warnings = [v for v in phase8_violations if v.get('severity') == 'warning']

    rows = []
    for i, v in enumerate(errors + warnings, 1):
        sev = v.get('severity', 'error')
        css_class = 'remaining' if sev == 'error' else ''
        badge = f'<span class="badge badge-{"error" if sev == "error" else "warn"}">{sev.upper()}</span>'
        rows.append(f"""
            <tr class="{css_class}">
                <td>{i}</td>
                <td>{_esc(v.get('rule', ''))}</td>
                <td>{badge}</td>
                <td>{_esc(v.get('file', ''))}</td>
                <td>{_esc(v.get('message', ''))}</td>
                <td>{_esc(v.get('suggestion', ''))}</td>
            </tr>""")

    return f"""
    <h2>Phase 8 跨文件检查问题（{len(errors)} errors + {len(warnings)} warnings）</h2>
    <table>
        <tr><th>#</th><th>规则</th><th>级别</th><th>文件</th><th>描述</th><th>建议</th></tr>
        {''.join(rows)}
    </table>
    """


def render_runtime(runtime_failures, phase9_analysis=None):
    """渲染 Phase 9 运行时失败（优先使用结构化数据，回退到日志扫描）"""
    phase9_analysis = phase9_analysis or {}

    # 优先使用 phase9_analysis 的结构化分类（未来格式）
    exec_errors = phase9_analysis.get('execution_errors', [])
    assert_errors = phase9_analysis.get('assertion_errors', [])
    # 当前 validate_09 输出格式：errors/warnings/info 列表
    p6_errors = phase9_analysis.get('errors', [])
    p6_warnings = phase9_analysis.get('warnings', [])

    if not runtime_failures and not exec_errors and not assert_errors and not p6_errors:
        return """
        <h2>Phase 9 运行时失败</h2>
        <p class="empty-msg">未检测到运行时失败（尚未运行测试或全部通过）</p>
        """

    sections = []

    # 结构化数据优先（未来格式）
    if exec_errors or assert_errors:
        rows = []
        idx = 1
        for e in exec_errors:
            rows.append(f"""
                <tr class="runtime-fail">
                    <td>{idx}</td>
                    <td>执行错误</td>
                    <td>{_esc(e.get('case_id', ''))}</td>
                    <td>{_esc(e.get('step', ''))}</td>
                    <td>{_esc(e.get('error', ''))}</td>
                    <td>{_esc(e.get('screenshot', ''))}</td>
                </tr>""")
            idx += 1
        for e in assert_errors:
            rows.append(f"""
                <tr class="runtime-fail">
                    <td>{idx}</td>
                    <td>断言失败</td>
                    <td>{_esc(e.get('case_id', ''))}</td>
                    <td>{_esc(e.get('step', ''))}</td>
                    <td>{_esc(e.get('error', ''))}</td>
                    <td>{_esc(e.get('screenshot', ''))}</td>
                </tr>""")
            idx += 1
        total = len(exec_errors) + len(assert_errors)
        sections.append(f"""
        <h2>Phase 9 运行时失败（{total} 项）</h2>
        <table>
            <tr><th>#</th><th>类型</th><th>Case</th><th>Step</th><th>错误</th><th>截图/日志</th></tr>
            {''.join(rows)}
        </table>""")
    elif runtime_failures:
        # 回退到日志扫描
        rows = []
        for i, f in enumerate(runtime_failures, 1):
            rows.append(f"""
                <tr class="runtime-fail">
                    <td>{i}</td>
                    <td>{_esc(f.get('error_type', ''))}</td>
                    <td>{_esc(f.get('case_id', ''))}</td>
                    <td>{_esc(f.get('step', ''))}</td>
                    <td>{_esc(f.get('error_text', ''))}</td>
                    <td>{_esc(f.get('log_file', ''))}</td>
                </tr>""")
        sections.append(f"""
        <h2>Phase 9 运行时失败（{len(runtime_failures)} 项）</h2>
        <table>
            <tr><th>#</th><th>类型</th><th>Case</th><th>Step</th><th>错误</th><th>日志</th></tr>
            {''.join(rows)}
        </table>""")

    # 当前格式：errors/warnings 列表
    if p6_errors or p6_warnings:
        rows = []
        for i, msg in enumerate(p6_errors, 1):
            rows.append(f'<tr class="runtime-fail"><td>{i}</td><td>error</td><td>{_esc(msg)}</td></tr>')
        for i, msg in enumerate(p6_warnings, 1):
            rows.append(f'<tr><td>{len(p6_errors)+i}</td><td>warning</td><td>{_esc(msg)}</td></tr>')
        sections.append(f"""
        <h3>Phase 9 分析摘要（{len(p6_errors)} errors + {len(p6_warnings)} warnings）</h3>
        <table>
            <tr><th>#</th><th>级别</th><th>描述</th></tr>
            {''.join(rows)}
        </table>""")

    return '\n'.join(sections) if sections else """
        <h2>Phase 9 运行时失败</h2>
        <p class="empty-msg">未检测到运行时失败</p>
        """


def render_learn_log(learn_log):
    """渲染累积失败模式（learn_log）"""
    failure_patterns = learn_log.get('failure_patterns', [])
    success_patterns = learn_log.get('success_patterns', [])
    review_needed = learn_log.get('manual_review_needed', [])

    if not failure_patterns and not success_patterns:
        return """
        <h2>累积失败模式（learn_log）</h2>
        <p class="empty-msg">无累积学习记录</p>
        """

    sections = []

    # 需人工确认的模式
    if review_needed:
        rows = []
        for i, r in enumerate(review_needed, 1):
            rows.append(f"""
                <tr class="remaining">
                    <td>{i}</td>
                    <td class="error">{_esc(r.get('pattern_key', ''))}</td>
                    <td>{_esc(r.get('reason', ''))}</td>
                    <td>{_esc(r.get('locator', ''))}</td>
                    <td>{_esc(r.get('keyword', ''))}</td>
                </tr>""")
        sections.append(f"""
        <details open>
            <summary>需人工确认（{len(review_needed)} 项，累计≥3次）</summary>
            <table>
                <tr><th>#</th><th>模式</th><th>原因</th><th>Locator</th><th>Keyword</th></tr>
                {''.join(rows)}
            </table>
        </details>""")

    # 全部失败模式
    if failure_patterns:
        rows = []
        for i, p in enumerate(failure_patterns, 1):
            count = p.get('count', 1)
            review = p.get('manual_review', False)
            css = 'remaining' if review else ''
            badge = f'<span class="badge badge-error">需确认</span>' if review else ''
            rows.append(f"""
                <tr class="{css}">
                    <td>{i}</td>
                    <td>{_esc(p.get('pattern_key', ''))} {badge}</td>
                    <td>{count}</td>
                    <td>{_esc(p.get('error_type', ''))}</td>
                </tr>""")
        sections.append(f"""
        <details>
            <summary>全部失败模式（{len(failure_patterns)} 项）</summary>
            <table>
                <tr><th>#</th><th>模式</th><th>次数</th><th>类型</th></tr>
                {''.join(rows)}
            </table>
        </details>""")

    # 成功模式统计
    if success_patterns:
        sections.append(f"""
        <details>
            <summary>成功模式（{len(success_patterns)} 项）</summary>
            <p class="info">共记录 {len(success_patterns)} 个成功的 keyword+locator 组合</p>
        </details>""")

    return f"""
    <h2>累积失败模式（learn_log）</h2>
    {''.join(sections)}
    """


def generate_html(project_dir, repair_data, phase8_violations,
                  runtime_failures, learn_log, timestamp, phase9_analysis=None):
    """组装完整 HTML"""
    project_name = os.path.basename(os.path.abspath(project_dir))

    body = ''.join([
        render_summary(repair_data, phase8_violations, runtime_failures, learn_log),
        render_repairs(repair_data),
        render_remaining(repair_data),
        render_phase8(phase8_violations),
        render_runtime(runtime_failures, phase9_analysis),
        render_learn_log(learn_log),
    ])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UIEngine 问题分析报告 — {project_name}</title>
    <style>{_CSS}</style>
</head>
<body>
    <h1>UIEngine 问题分析报告</h1>
    <p>项目: <strong>{_esc(project_name)}</strong> | 生成时间: {_esc(timestamp)}</p>
    {body}
    <div class="footer">
        <p>由 generate_issues_report.py 自动生成 | Phase 8/9 上游自修复架构</p>
        <p>此报告为纯分析产出，不再触发 AI 修复循环。待人工处理项请逐一排查。</p>
    </div>
</body>
</html>"""


# ============================================================================
# 主函数
# ============================================================================

def generate_issues_report(project_dir, repair_log_path=None,
                           phase8_json_path=None, learn_log_path=None,
                           timestamp=None):
    """生成 HTML 联合问题报告

    Args:
        project_dir: 项目根目录
        repair_log_path: Phase 5 修复日志路径（默认 _probe/repair_log.json）
        phase8_json_path: Phase 8 violations JSON 路径
        learn_log_path: Phase 9 学习日志路径（默认 _probe/learn_log.json）
        timestamp: 时间戳字符串（默认当前时间）

    Returns:
        生成的 HTML 文件路径
    """
    project_dir = os.path.abspath(project_dir)

    if timestamp is None:
        now = datetime.datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        display_ts = now.strftime('%Y-%m-%d %H:%M:%S')
    else:
        display_ts = timestamp

    # 加载数据
    repair_data = load_repair_log(project_dir) if not repair_log_path \
        else (load_json(repair_log_path) or {'repairs': [], 'remaining': []})
    phase8_violations = load_phase8_violations(project_dir, phase8_json_path)
    learn_log = load_learn_log(project_dir) if not learn_log_path \
        else (load_json(learn_log_path) or {})
    runtime_failures = load_runtime_failures(project_dir)
    phase9_analysis = load_phase9_analysis(project_dir)

    # 生成 HTML
    html = generate_html(project_dir, repair_data, phase8_violations,
                         runtime_failures, learn_log, display_ts, phase9_analysis)

    # 输出
    report_dir = os.path.join(project_dir, 'report', 'issues_report')
    os.makedirs(report_dir, exist_ok=True)
    output_file = os.path.join(report_dir, f'issues_{timestamp}.html')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    # 统计摘要
    repairs = repair_data.get('repairs', [])
    remaining = repair_data.get('remaining', [])
    p8_errors = len([v for v in phase8_violations if v.get('severity') == 'error'])

    print(f"[INFO] 问题分析报告: {output_file}")
    print(f"  自修复: {len(repairs)} | 待人工: {len(remaining) + p8_errors} | "
          f"运行时失败: {len(runtime_failures)}")

    return output_file


def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description='Phase 8/9 联合问题报告生成器'
    )
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--repair-log', help='Phase 5 repair_log.json 路径')
    parser.add_argument('--phase8-json', help='Phase 8 violations JSON 路径')
    parser.add_argument('--learn-log', help='Phase 9 learn_log.json 路径')
    parser.add_argument('--timestamp', help='时间戳（默认当前时间）')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    generate_issues_report(
        project_dir,
        repair_log_path=args.repair_log,
        phase8_json_path=args.phase8_json,
        learn_log_path=args.learn_log,
        timestamp=args.timestamp,
    )


if __name__ == '__main__':
    main()
