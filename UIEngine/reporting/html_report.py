"""HTML 测试报告生成器

生成静态 HTML 测试报告，包含：
- 套件执行概要（开始时间、总耗时、通过/失败/错误/跳过计数）
- 按模块分组、可折叠的用例列表
- 每个用例的完整执行树（关键字嵌套层级）
- 每个步骤的关键字、参数、状态、耗时、日志
- 失败步骤的错误原因和截图链接
"""
import os
import time
from collections import OrderedDict

try:
    import yaml
except ImportError:
    yaml = None


def generate_html_report(suite, result, report_path):
    """生成 HTML 测试报告

    :param suite: 测试套件数据（包含 cases 列表，每个 case 含 _module、_execution_tree）
    :param result: 测试结果字典（来自 TestResult.get_result()）
    :param report_path: HTML 报告文件路径
    """
    suite_name = _escape_html(suite.get('name') or suite.get('desc') or suite.get('id') or 'Unknown')
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    run_cases = result.get('run_cases', [])

    # 从报告路径推导工程根目录: {root}/report/run_report/xxx.html → {root}
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(report_path))))
    for case in run_cases:
        case.setdefault('_project_root', _project_root)

    # 按模块分组用例
    modules = _group_cases_by_module(run_cases)

    # 构建各部分 HTML
    summary_html = _render_summary(result)
    summary_table_html = _render_summary_table(modules)
    modules_html = ''
    for idx, (module_name, cases) in enumerate(modules.items()):
        modules_html += _render_module_section(module_name, cases, idx)

    # 如果没有执行任何用例
    if not modules_html:
        modules_html = '<p style="color: #999; text-align: center; padding: 40px;">无执行记录</p>'

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{suite_name} - 测试报告</title>
    <style>
        {_get_css_styles()}
    </style>
</head>
<body>
    <div class="report-container">
        <div class="report-header">
            <h1>{suite_name}</h1>
            <div class="header-meta">
                <span>开始时间: {result.get('start_time', '-')}</span>
                <span>总耗时: {result.get('duration', '-')}</span>
                <span>生成时间: {timestamp}</span>
            </div>
        </div>

        <div class="summary-cards">
            {_render_summary_cards(result)}
        </div>

        {summary_html}

        {summary_table_html}

        <div class="toolbar">
            <button onclick="expandAll()" class="btn">全部展开</button>
            <button onclick="collapseAll()" class="btn">全部折叠</button>
        </div>

        <h2 class="section-title">执行详情</h2>
        <div class="modules-container">
            {modules_html}
        </div>
    </div>

    <script>
        {_get_javascript()}
    </script>
</body>
</html>'''

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return report_path


# ===================== 数据分组 =====================

def _group_cases_by_module(run_cases):
    """按 _module 字段分组用例，保持插入顺序

    :param run_cases: 已执行的用例列表
    :return: OrderedDict {module_name: [case_dicts]}
    """
    modules = OrderedDict()
    for case in run_cases:
        module = case.get('_module', 'default')
        modules.setdefault(module, []).append(case)
    return modules


# ===================== 渲染：概要 =====================

def _render_summary(result):
    """渲染执行概要统计行"""
    total = result.get('all', 0)
    success = result.get('success', 0)
    fail = result.get('fail', 0)
    error = result.get('error', 0)
    skip = result.get('skip', 0)
    no_run = result.get('no_run', 0)

    pass_rate = f"{(success / total * 100):.1f}%" if total > 0 else "N/A"

    return f'''<div class="overview-stats-row">
        <div class="summary-item">
            <span class="summary-label">用例总数</span>
            <span class="summary-value">{total}</span>
        </div>
        <div class="summary-item">
            <span class="summary-label">已执行</span>
            <span class="summary-value">{success + fail + error + skip}</span>
        </div>
        <div class="summary-item">
            <span class="summary-label">未执行</span>
            <span class="summary-value text-muted">{no_run}</span>
        </div>
        <div class="summary-item">
            <span class="summary-label">通过率</span>
            <span class="summary-value {_pass_rate_class(pass_rate)}">{pass_rate}</span>
        </div>
    </div>'''


def _render_summary_cards(result):
    """渲染概要卡片行"""
    return f'''
        <div class="card card-success">
            <div class="card-count">{result.get('success', 0)}</div>
            <div class="card-label">通过</div>
        </div>
        <div class="card card-fail">
            <div class="card-count">{result.get('fail', 0)}</div>
            <div class="card-label">失败</div>
        </div>
        <div class="card card-error">
            <div class="card-count">{result.get('error', 0)}</div>
            <div class="card-label">错误</div>
        </div>
        <div class="card card-skip">
            <div class="card-count">{result.get('skip', 0)}</div>
            <div class="card-label">跳过</div>
        </div>
    '''


def _pass_rate_class(rate_str):
    """根据通过率返回 CSS 类名"""
    try:
        rate = float(rate_str.strip('%'))
        if rate >= 90:
            return 'text-success'
        elif rate >= 70:
            return 'text-warning'
        else:
            return 'text-danger'
    except (ValueError, AttributeError):
        return ''


# ===================== 渲染：汇总表 =====================

def _render_summary_table(modules):
    """渲染用例结果汇总表 — 按模块分组，每行显示用例名、结果、失败原因、详情链接"""
    if not modules:
        return ''

    html_parts = ['<div class="summary-table-container">']
    html_parts.append('<h2 class="section-title">用例执行结果汇总</h2>')

    for mod_idx, (module_name, cases) in enumerate(modules.items()):
        module_id = f"summary-module-{mod_idx}"
        has_failure = any(c.get('state') in ('fail', 'error') for c in cases)
        default_open = 'open' if has_failure else ''

        html_parts.append(f'''<details class="summary-module" {default_open}>
            <summary class="summary-module-header">
                <span class="module-name">{_escape_html(module_name)}</span>
                <span class="module-badge">{len(cases)} 条用例</span>
            </summary>
            <table class="summary-table">
                <thead>
                    <tr>
                        <th style="width:40px">#</th>
                        <th>用例名称</th>
                        <th style="width:80px">结果</th>
                        <th>失败原因</th>
                        <th style="width:60px">详情</th>
                    </tr>
                </thead>
                <tbody>''')

        for case_idx, case in enumerate(cases):
            seq = case.get('_seq', case_idx + 1)
            case_name = _escape_html(case.get('name') or case.get('desc') or case.get('id') or 'Unknown')
            state = case.get('state', 'unknown')
            state_labels = {'success': 'PASS', 'fail': 'FAIL', 'error': 'ERROR', 'skip': 'SKIP'}
            state_label = state_labels.get(state, state.upper())
            state_class = f"state-{state}"

            # 提取失败原因（一句话）
            fail_reason = _extract_fail_reason(case)

            # 详情链接 — 跳转到下方详细区域并展开
            detail_target = f"module-{mod_idx}-case-{case_idx}-detail"
            module_target = f"module-{mod_idx}-content"
            module_arrow = f"module-{mod_idx}-arrow"

            html_parts.append(f'''<tr class="summary-row summary-row-{state}">
                        <td class="seq-cell">{seq}</td>
                        <td class="case-name-cell">{case_name}</td>
                        <td><span class="case-badge {state_class}">{state_label}</span></td>
                        <td class="fail-reason-cell">{fail_reason}</td>
                        <td><a href="javascript:void(0)" class="detail-link"
                               onclick="scrollToDetail('{detail_target}','{module_target}','{module_arrow}')">查看</a></td>
                    </tr>''')

        html_parts.append('''</tbody>
            </table>
        </details>''')

    html_parts.append('</div>')
    return '\n'.join(html_parts)


def _extract_fail_reason(case):
    """从用例的执行树中提取一句话失败原因"""
    state = case.get('state', '')
    if state not in ('fail', 'error'):
        return '-'

    # 递归查找执行树中第一个失败节点
    tree = case.get('_execution_tree', [])
    reason = _find_first_error_in_tree(tree)
    if reason:
        # 截断过长的错误信息
        if len(reason) > 120:
            reason = reason[:117] + '...'
        return _escape_html(reason)
    return '<span class="text-muted">未知错误</span>'


def _find_first_error_in_tree(nodes):
    """递归查找执行树中第一个失败节点的 error_msg"""
    if not nodes:
        return None
    for node in nodes:
        if hasattr(node, 'to_dict'):
            node = node.to_dict()
        status = node.get('status', '')
        if status in ('fail', 'error'):
            error_msg = node.get('error_msg', '')
            if error_msg:
                return error_msg
        # 递归检查子节点
        children = node.get('children', [])
        child_reason = _find_first_error_in_tree(children)
        if child_reason:
            return child_reason
    return None


# ===================== 渲染：模块区域 =====================

def _render_module_section(module_name, cases, idx):
    """渲染一个可折叠的模块区域"""
    module_display = _escape_html(module_name)
    module_id = f"module-{idx}"
    has_failure = any(c.get('state') in ('fail', 'error') for c in cases)

    # 统计模块内的通过/失败数
    pass_count = sum(1 for c in cases if c.get('state') == 'success')
    fail_count = sum(1 for c in cases if c.get('state') in ('fail', 'error'))
    skip_count = sum(1 for c in cases if c.get('state') == 'skip')

    # 包含失败的模块默认展开
    default_display = 'block' if has_failure else 'none'
    default_expanded = 'expanded' if has_failure else ''
    failure_class = 'module-has-failure' if has_failure else ''

    # 渲染模块内的所有用例
    cases_html = ''
    for case_idx, case in enumerate(cases):
        cases_html += _render_case_card(case, f"{module_id}-case-{case_idx}")

    return f'''<div class="module-section {failure_class}" data-content-id="{module_id}-content">
        <div class="module-header" onclick="toggleSection('{module_id}-content', '{module_id}-arrow')">
            <span class="toggle-arrow {default_expanded}" id="{module_id}-arrow">&#9654;</span>
            <span class="module-name">{module_display}</span>
            <span class="module-stats">
                <span class="stat-pass">{pass_count} 通过</span>
                {f'<span class="stat-fail">{fail_count} 失败</span>' if fail_count else ''}
                {f'<span class="stat-skip">{skip_count} 跳过</span>' if skip_count else ''}
                <span class="stat-total">共 {len(cases)} 条</span>
            </span>
        </div>
        <div class="module-content" id="{module_id}-content" style="display: {default_display};">
            {cases_html}
        </div>
    </div>'''


# ===================== 渲染：用例卡片 =====================

def _render_case_card(case, case_id):
    """渲染一个用例卡片"""
    case_name = _escape_html(case.get('name') or case.get('desc') or case.get('id') or 'Unknown')
    state = case.get('state', 'unknown')
    duration = case.get('_case_duration', 0)
    start_time = case.get('_case_start_time', '-')
    execution_tree = case.get('_execution_tree', [])
    img_path = case.get('img', '')

    # 状态标签
    state_class = f"state-{state}"
    state_labels = {'success': 'PASS', 'fail': 'FAIL', 'error': 'ERROR', 'skip': 'SKIP'}
    state_label = state_labels.get(state, state.upper())

    # 渲染执行树
    tree_html = ''
    if execution_tree:
        for node_idx, node in enumerate(execution_tree):
            tree_html += _render_step_node(node, case_id, node_idx, case)
    elif state == 'skip':
        tree_html = '<div class="step-info">用例已跳过，无执行记录</div>'
    else:
        tree_html = '<div class="step-info">无执行记录</div>'

    return f'''<div class="case-card">
        <div class="case-header" onclick="toggleSection('{case_id}-detail', '{case_id}-arrow')">
            <span class="toggle-arrow" id="{case_id}-arrow">&#9654;</span>
            <span class="case-name">{case_name}</span>
            <span class="case-badge {state_class}">{state_label}</span>
            <span class="case-duration">{duration:.1f}s</span>
        </div>
        <div class="case-detail" id="{case_id}-detail" style="display: none;">
            <div class="case-meta">
                <span>开始时间: {start_time}</span>
                <span>耗时: {duration:.2f}s</span>
            </div>
            <div class="execution-tree">
                {tree_html}
            </div>
        </div>
    </div>'''


# ===================== 渲染：执行树节点 =====================

def _render_step_node(node, parent_id, node_idx=None, case_context=None):
    """递归渲染执行树节点

    :param node: StepNode 对象（或 to_dict() 后的字典）
    :param parent_id: 父节点 HTML id 前缀
    :param node_idx: 节点在同级中的索引
    :param case_context: 用例字典（用于提取文件路径提示）
    """
    # 兼容 StepNode 对象和字典
    if hasattr(node, 'to_dict'):
        node = node.to_dict()

    keyword = _escape_html(node.get('keyword', ''))
    desc = _escape_html(node.get('desc', ''))
    params = node.get('params', {})
    status = node.get('status', 'unknown')
    error_msg = node.get('error_msg')
    screenshot = node.get('screenshot')
    duration_ms = node.get('duration_ms')
    depth = node.get('depth', 0)
    log_entries = node.get('log_entries', [])
    children = node.get('children', [])

    # 检查是否需要在报告中隐藏（滚动等实现细节步骤）
    if node.get('hide_in_report', False):
        return ''

    node_id = f"{parent_id}-n{node_idx or 0}"
    indent = depth * 24  # 每层缩进 24px

    # 状态图标和样式
    status_icons = {'pass': '✓', 'fail': '✗', 'error': '⚠', 'running': '⟳'}
    status_icon = status_icons.get(status, '?')
    status_class = f"step-{status}"

    # 参数格式化
    params_html = _render_params(params)

    # 耗时格式化
    duration_str = ''
    if duration_ms is not None:
        if duration_ms >= 1000:
            duration_str = f"{duration_ms / 1000:.2f}s"
        else:
            duration_str = f"{duration_ms:.0f}ms"

    # 错误信息
    error_html = ''
    if error_msg:
        error_html = f'<div class="step-error">错误: {_escape_html(error_msg)}</div>'

    # 截图链接
    screenshot_html = ''
    if screenshot:
        screenshot_html = f'<div class="step-screenshot">📷 <a href="{_escape_html(screenshot)}" target="_blank">查看失败截图</a></div>'

    # 源文件检查提示（仅失败步骤）
    source_hint_html = ''
    if status in ('fail', 'error'):
        source_hint_html = _render_source_hints(params, case_context)

    # 日志（可折叠）
    logs_html = ''
    if log_entries:
        log_lines = ''.join(
            f'<div class="log-line log-{_escape_html(level.lower())}">{_escape_html(msg)}</div>'
            for level, msg in log_entries
        )
        logs_html = f'''<div class="step-logs-toggle">
            <span class="log-toggle-btn" onclick="toggleSection('{node_id}-logs', null)">&#9654; 查看日志 ({len(log_entries)} 条)</span>
            <div class="step-logs" id="{node_id}-logs" style="display: none;">
                {log_lines}
            </div>
        </div>'''

    # 子节点（递归渲染）
    children_html = ''
    if children:
        for child_idx, child in enumerate(children):
            children_html += _render_step_node(child, node_id, child_idx, case_context)

    return f'''<div class="step-node {status_class}" style="margin-left: {indent}px;">
        <div class="step-header">
            <span class="step-status-icon">{status_icon}</span>
            <span class="step-desc">{desc}</span>
            <span class="step-keyword">{keyword}</span>
            <span class="step-duration">{duration_str}</span>
        </div>
        {params_html}
        {error_html}
        {screenshot_html}
        {source_hint_html}
        {logs_html}
        {children_html}
    </div>'''


# ===================== 渲染：参数 =====================

def _render_params(params):
    """格式化参数显示"""
    if not params:
        return ''

    # 过滤掉空值和过长的值
    items = []
    for key, value in params.items():
        str_val = str(value)
        # 截断过长的参数值
        if len(str_val) > 200:
            str_val = str_val[:200] + '...'
        items.append(f'<span class="param-item"><span class="param-key">{_escape_html(str(key))}</span>=<span class="param-value">{_escape_html(str_val)}</span></span>')

    if not items:
        return ''

    return f'<div class="step-params">参数: {" ".join(items)}</div>'


# ===================== 渲染：源文件检查提示 =====================

import re as _re

_VAR_PATTERN = _re.compile(r'\$\{([^}]+)\}')

def _render_source_hints(params, case_context=None):
    """为失败步骤生成源文件检查提示，帮助用户快速定位问题文件。

    始终显示该用例对应的三层文件路径：
    - 📄 pages/{module}/ — 定位器定义文件
    - 📊 data/{module}/data.yaml — 测试数据文件
    - 📋 cases/{module}/{case}.yaml — 用例步骤文件

    当参数中含有 ${group.field} 变量引用时（未解析的原始步骤），额外标注具体的组名和字段。
    """
    if not params and not case_context:
        return ''

    # 从 case_context 提取模块名和文件信息
    module = ''
    case_id = ''
    case_file = ''
    project_root = ''
    if case_context:
        module = case_context.get('_module', '')
        case_id = case_context.get('id', '')
        case_file = case_context.get('_source_file', '')
        project_root = case_context.get('_project_root', '')
        if not case_file and case_id and module:
            case_file = f"cases/{module}/{case_id}.yaml"

    # 如果既没有模块信息也没有参数，无法生成有意义的提示
    if not module and not params:
        return ''

    # 尝试从参数中提取变量引用（仅对未解析的原始步骤有效）
    page_refs = set()  # locator 中的变量引用 → pages/
    data_refs = set()  # value/url 中的变量引用 → data/
    if params:
        for key, value in params.items():
            str_val = str(value)
            matches = _VAR_PATTERN.findall(str_val)
            for ref in matches:
                if key in ('locator', 'frame'):
                    page_refs.add(ref)
                else:
                    data_refs.add(ref)

    hints = []

    # ── 📄 pages/ 定位器文件 ──
    if module:
        page_dir = f"pages/{module}/"

        # 尝试通过值匹配精确定位 locator 来源文件
        locator_source_info = ''
        if not page_refs and params and project_root:
            locator_value = params.get('locator', '')
            if isinstance(locator_value, str) and len(locator_value) > 5:
                source_matches = _find_locator_source(project_root, module, locator_value)
                if source_matches:
                    source_parts = []
                    for fname, group in source_matches:
                        source_parts.append(f'<code>{page_dir}{fname}</code>（<code>{group}</code> 组）')
                    locator_source_info = ' — ' + '、'.join(source_parts)

        if locator_source_info:
            # 精确匹配到文件和组
            hints.append(
                f'<div class="hint-item hint-page">📄 <b>定位器定义</b>{locator_source_info}</div>'
            )
        elif page_refs:
            # 有原始变量引用（未解析的步骤）
            page_groups = sorted({r.split('.')[0] for r in page_refs if '.' in r})
            refs_str = ', '.join(f'<code>${{{r}}}</code>' for r in sorted(page_refs))
            groups_str = ', '.join(f'<code>{g}</code>' for g in page_groups)
            detail = f'，检查组: {groups_str}（引用: {refs_str}）' if page_groups else f'（引用: {refs_str}）'
            files_info = ''
            if project_root:
                abs_page_dir = os.path.join(project_root, 'pages', module)
                files_info = _list_dir_yaml_files(abs_page_dir)
                abs_common_dir = os.path.join(project_root, 'pages', 'common')
                if os.path.isdir(abs_common_dir):
                    common_files = _list_dir_yaml_files(abs_common_dir)
                    if common_files:
                        files_info += f'；<code>pages/common/</code> {common_files}'
            if files_info:
                hints.append(
                    f'<div class="hint-item hint-page">📄 <b>定位器定义</b> — '
                    f'<code>{page_dir}</code> {files_info}{detail}</div>'
                )
            else:
                hints.append(
                    f'<div class="hint-item hint-page">📄 <b>定位器定义</b> — '
                    f'<code>{page_dir}</code>{detail}</div>'
                )
        else:
            # 降级：列出目录文件
            files_info = ''
            if project_root:
                abs_page_dir = os.path.join(project_root, 'pages', module)
                files_info = _list_dir_yaml_files(abs_page_dir)
                abs_common_dir = os.path.join(project_root, 'pages', 'common')
                if os.path.isdir(abs_common_dir):
                    common_files = _list_dir_yaml_files(abs_common_dir)
                    if common_files:
                        files_info += f'；<code>pages/common/</code> {common_files}'
            if files_info:
                hints.append(
                    f'<div class="hint-item hint-page">📄 <b>定位器定义</b> — '
                    f'<code>{page_dir}</code> {files_info}</div>'
                )
            else:
                hints.append(
                    f'<div class="hint-item hint-page">📄 <b>定位器定义</b> — '
                    f'<code>{page_dir}</code></div>'
                )

    # ── 📊 data/ 测试数据文件 ──
    if module:
        data_file = f"data/{module}/data.yaml"
        abs_data = os.path.join(project_root, data_file) if project_root else ''
        data_exists = abs_data and os.path.isfile(abs_data)
        if data_refs:
            data_groups = sorted({r.split('.')[0] for r in data_refs if '.' in r})
            refs_str = ', '.join(f'<code>${{{r}}}</code>' for r in sorted(data_refs))
            groups_str = ', '.join(f'<code>{g}</code>' for g in data_groups)
            detail = f'，检查组: {groups_str}（引用: {refs_str}）' if data_groups else f'（引用: {refs_str}）'
        else:
            detail = ''
        if data_exists:
            hints.append(
                f'<div class="hint-item hint-data">📊 <b>测试数据</b> — '
                f'<code>{data_file}</code>{detail}</div>'
            )
        else:
            hints.append(
                f'<div class="hint-item hint-data">📊 <b>测试数据</b> — '
                f'<code>data/{module}/</code>{detail}</div>'
            )

    # ── 📋 cases/ 用例步骤文件 ──
    if case_file:
        hints.append(f'<div class="hint-item hint-case">📋 <b>用例步骤</b> — <code>{case_file}</code></div>')
    elif module:
        hints.append(f'<div class="hint-item hint-case">📋 <b>用例步骤</b> — <code>cases/{module}/</code></div>')
    else:
        hints.append('<div class="hint-item hint-case">📋 <b>用例步骤</b> — <code>cases/</code></div>')

    return f'''<div class="source-hints">
        <div class="source-hints-header">🔍 建议检查以下文件：</div>
        {"".join(hints)}
    </div>'''


def _list_dir_yaml_files(directory):
    """列出目录中的 YAML 文件名，返回逗号分隔的 HTML code 字符串"""
    if not os.path.isdir(directory):
        return ''
    files = sorted(
        f for f in os.listdir(directory)
        if f.endswith(('.yaml', '.yml'))
    )
    if not files:
        return ''
    return ', '.join(f'<code>{f}</code>' for f in files)


def _find_locator_source(project_root, module, locator_value):
    """在 pages/{module}/ 目录中查找包含指定 locator 值的 YAML 文件和组名。

    通过子串匹配：pages YAML 中存的是基础 XPath，引擎运行时会注入隐藏过滤后缀，
    所以用 YAML 值作为子串去匹配解析后的完整 locator。

    :param project_root: 工程根目录
    :param module: 模块名
    :param locator_value: 解析后的 locator XPath 字符串
    :return: list of (filename, group_name) 匹配列表，空列表表示未找到
    """
    if not project_root or not module or not locator_value or yaml is None:
        return []

    matches = []
    seen = set()

    # 扫描 module 目录 + common 目录
    scan_dirs = [
        (os.path.join(project_root, 'pages', module), ''),
        (os.path.join(project_root, 'pages', 'common'), 'pages/common/'),
    ]

    for scan_dir, path_prefix in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith(('.yaml', '.yml')):
                continue
            fpath = os.path.join(scan_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    continue
                for group_name, fields in data.items():
                    if not isinstance(fields, dict):
                        continue
                    for _field, value in fields.items():
                        if (isinstance(value, str)
                                and len(value) > 5
                                and value in locator_value):
                            key = (fname, group_name)
                            if key not in seen:
                                seen.add(key)
                                display = f'{path_prefix}{fname}' if path_prefix else fname
                                matches.append((display, group_name))
                                break  # 同组命中一次即可
            except Exception:
                continue  # 文件读取/解析失败，静默跳过

    return matches


# ===================== HTML 转义 =====================

def _escape_html(text):
    """转义 HTML 特殊字符"""
    if text is None:
        return ''
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


# ===================== CSS 样式 =====================

def _get_css_styles():
    """返回内联 CSS 样式"""
    return '''
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f0f2f5;
            color: #333;
            line-height: 1.6;
        }
        .report-container {
            max-width: 1200px;
            margin: 20px auto;
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            padding: 30px;
        }

        /* 报告头部 */
        .report-header {
            border-bottom: 2px solid #1890ff;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }
        .report-header h1 {
            color: #1a1a1a;
            font-size: 24px;
            margin-bottom: 8px;
        }
        .header-meta {
            display: flex;
            gap: 20px;
            color: #888;
            font-size: 13px;
            flex-wrap: wrap;
        }

        /* 概要卡片 */
        .summary-cards {
            display: flex;
            gap: 15px;
            margin: 20px 0;
        }
        .card {
            flex: 1;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            color: #fff;
            min-width: 100px;
        }
        .card-count { font-size: 32px; font-weight: 700; }
        .card-label { font-size: 13px; opacity: 0.9; margin-top: 4px; }
        .card-success { background: #52c41a; }
        .card-fail { background: #ff4d4f; }
        .card-error { background: #fa8c16; }
        .card-skip { background: #8c8c8c; }

        /* 概要统计行 */
        .overview-stats-row {
            display: flex;
            gap: 30px;
            padding: 15px 20px;
            background: #fafafa;
            border-radius: 6px;
            margin: 15px 0;
            flex-wrap: wrap;
        }
        .summary-item { display: flex; flex-direction: column; }
        .summary-label { font-size: 12px; color: #888; }
        .summary-value { font-size: 20px; font-weight: 600; color: #333; }
        .text-success { color: #52c41a; }
        .text-warning { color: #faad14; }
        .text-danger { color: #ff4d4f; }
        .text-muted { color: #999; }

        /* 工具栏 */
        .toolbar {
            display: flex;
            gap: 10px;
            margin: 15px 0;
        }
        .btn {
            padding: 6px 16px;
            border: 1px solid #d9d9d9;
            border-radius: 4px;
            background: #fff;
            cursor: pointer;
            font-size: 13px;
            color: #555;
            transition: all 0.2s;
        }
        .btn:hover { border-color: #1890ff; color: #1890ff; }

        /* 模块区域 */
        .module-section {
            border: 1px solid #e8e8e8;
            border-radius: 6px;
            margin-bottom: 12px;
            overflow: hidden;
        }
        .module-has-failure { border-left: 3px solid #ff4d4f; }
        .module-header {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px 16px;
            background: #fafafa;
            cursor: pointer;
            user-select: none;
            transition: background 0.2s;
        }
        .module-header:hover { background: #f0f0f0; }
        .module-name { font-weight: 600; font-size: 15px; color: #1a1a1a; }
        .module-stats { margin-left: auto; display: flex; gap: 12px; font-size: 13px; }
        .stat-pass { color: #52c41a; }
        .stat-fail { color: #ff4d4f; font-weight: 600; }
        .stat-skip { color: #8c8c8c; }
        .stat-total { color: #999; }

        /* 折叠箭头 */
        .toggle-arrow {
            display: inline-block;
            transition: transform 0.2s;
            font-size: 12px;
            color: #999;
            width: 16px;
        }
        .toggle-arrow.expanded { transform: rotate(90deg); }

        /* 模块内容 */
        .module-content { padding: 0 16px 16px; }

        /* 用例卡片 */
        .case-card {
            border: 1px solid #f0f0f0;
            border-radius: 4px;
            margin-top: 8px;
            overflow: hidden;
        }
        .case-header {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            cursor: pointer;
            user-select: none;
            transition: background 0.2s;
        }
        .case-header:hover { background: #fafafa; }
        .case-name { font-weight: 500; font-size: 14px; flex: 1; }
        .case-badge {
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .state-success { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
        .state-fail { background: #fff2f0; color: #ff4d4f; border: 1px solid #ffa39e; }
        .state-error { background: #fff7e6; color: #fa8c16; border: 1px solid #ffd591; }
        .state-skip { background: #fafafa; color: #8c8c8c; border: 1px solid #d9d9d9; }
        .case-duration { color: #999; font-size: 13px; font-family: monospace; }

        /* 用例详情 */
        .case-detail { padding: 10px 14px; border-top: 1px solid #f0f0f0; }
        .case-meta {
            display: flex;
            gap: 20px;
            font-size: 12px;
            color: #888;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px dashed #f0f0f0;
        }

        /* 执行树 */
        .execution-tree { font-size: 13px; }

        /* 步骤节点 */
        .step-node {
            padding: 6px 10px;
            margin: 3px 0;
            border-radius: 4px;
            border-left: 3px solid transparent;
            transition: background 0.15s;
        }
        .step-node:hover { background: #fafafa; }
        .step-pass { border-left-color: #52c41a; }
        .step-fail { border-left-color: #ff4d4f; background: #fff2f0; }
        .step-error { border-left-color: #fa8c16; background: #fff7e6; }
        .step-running { border-left-color: #1890ff; }

        .step-header {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .step-status-icon {
            font-weight: 700;
            width: 18px;
            text-align: center;
        }
        .step-pass .step-status-icon { color: #52c41a; }
        .step-fail .step-status-icon { color: #ff4d4f; }
        .step-error .step-status-icon { color: #fa8c16; }
        .step-desc { font-weight: 500; color: #1a1a1a; }
        .step-keyword {
            font-family: "SFMono-Regular", Consolas, monospace;
            font-size: 12px;
            background: #f5f5f5;
            padding: 1px 6px;
            border-radius: 3px;
            color: #666;
        }
        .step-duration {
            margin-left: auto;
            font-family: monospace;
            font-size: 12px;
            color: #999;
        }

        /* 参数 */
        .step-params {
            margin: 4px 0 4px 26px;
            font-size: 12px;
            color: #666;
            line-height: 1.8;
        }
        .param-item { margin-right: 12px; }
        .param-key { color: #1890ff; }
        .param-value {
            color: #333;
            font-family: monospace;
            word-break: break-all;
        }

        /* 错误信息 */
        .step-error {
            margin: 6px 0 4px 26px;
            padding: 6px 10px;
            background: #fff2f0;
            border: 1px solid #ffa39e;
            border-radius: 4px;
            color: #cf1322;
            font-size: 12px;
            word-break: break-word;
        }

        /* 截图链接 */
        .step-screenshot {
            margin: 6px 0 4px 26px;
            font-size: 13px;
        }
        .step-screenshot a {
            color: #1890ff;
            text-decoration: none;
        }
        .step-screenshot a:hover { text-decoration: underline; }

        /* 日志 */
        .step-logs-toggle { margin: 4px 0 4px 26px; }
        .log-toggle-btn {
            cursor: pointer;
            font-size: 12px;
            color: #1890ff;
            user-select: none;
        }
        .log-toggle-btn:hover { text-decoration: underline; }
        .step-logs {
            margin-top: 6px;
            padding: 8px;
            background: #1e1e1e;
            border-radius: 4px;
            font-family: "SFMono-Regular", Consolas, monospace;
            font-size: 11px;
            line-height: 1.5;
            max-height: 400px;
            overflow-y: auto;
        }
        .log-line { color: #d4d4d4; padding: 1px 0; }
        .log-error { color: #f44747; }
        .log-warning { color: #cca700; }
        .log-debug { color: #888; }
        .log-critical { color: #ff0000; font-weight: 600; }

        /* 跳过提示 */
        .step-info {
            padding: 10px;
            color: #999;
            font-size: 13px;
            text-align: center;
        }

        /* 区域标题 */
        .section-title {
            font-size: 16px;
            color: #333;
            margin: 20px 0 12px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid #eee;
        }

        /* 汇总表 */
        .summary-table-container {
            margin: 20px 0;
        }
        .summary-module {
            border: 1px solid #e8e8e8;
            border-radius: 6px;
            margin-bottom: 10px;
            overflow: hidden;
        }
        .summary-module-header {
            padding: 10px 16px;
            background: #fafafa;
            cursor: pointer;
            user-select: none;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
        }
        .summary-module-header:hover { background: #f0f0f0; }
        .module-badge {
            font-size: 12px;
            color: #888;
            font-weight: normal;
        }
        .summary-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .summary-table thead th {
            background: #fafafa;
            padding: 8px 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 1px solid #e8e8e8;
            color: #555;
        }
        .summary-table tbody td {
            padding: 8px 12px;
            border-bottom: 1px solid #f0f0f0;
            vertical-align: middle;
        }
        .summary-row:hover { background: #f9f9f9; }
        .summary-row-fail { background: #fff8f8; }
        .summary-row-fail:hover { background: #fff0f0; }
        .summary-row-error { background: #fff8f0; }
        .seq-cell { color: #999; text-align: center; font-family: monospace; }
        .case-name-cell { font-weight: 500; }
        .fail-reason-cell {
            color: #cf1322;
            font-size: 12px;
            max-width: 400px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .detail-link {
            color: #1890ff;
            text-decoration: none;
            font-size: 12px;
        }
        .detail-link:hover { text-decoration: underline; }

        /* 源文件检查提示 */
        .source-hints {
            margin: 8px 0 4px 26px;
            padding: 8px 12px;
            background: #f6f8fa;
            border: 1px solid #e1e4e8;
            border-radius: 4px;
            font-size: 12px;
        }
        .source-hints-header {
            font-weight: 600;
            color: #333;
            margin-bottom: 4px;
        }
        .hint-item {
            padding: 2px 0;
            color: #555;
            line-height: 1.6;
        }
        .hint-item code {
            background: #e8ecf0;
            padding: 1px 4px;
            border-radius: 2px;
            font-size: 11px;
            color: #1890ff;
        }
        .hint-page { color: #0366d6; }
        .hint-data { color: #28a745; }
        .hint-case { color: #6f42c1; }

        /* 响应式 */
        @media (max-width: 768px) {
            .report-container { margin: 10px; padding: 15px; }
            .summary-cards { flex-wrap: wrap; }
            .card { min-width: 45%; }
            .overview-stats-row { gap: 15px; }
            .module-stats { flex-wrap: wrap; gap: 6px; }
        }
    '''


# ===================== JavaScript =====================

def _get_javascript():
    """返回内联 JavaScript"""
    return '''
        function toggleSection(contentId, arrowId) {
            var content = document.getElementById(contentId);
            if (!content) return;
            var arrow = arrowId ? document.getElementById(arrowId) : null;

            if (content.style.display === 'none' || content.style.display === '') {
                content.style.display = 'block';
                if (arrow) arrow.classList.add('expanded');
            } else {
                content.style.display = 'none';
                if (arrow) arrow.classList.remove('expanded');
            }
        }

        function expandAll() {
            document.querySelectorAll('.module-content, .case-detail').forEach(function(el) {
                el.style.display = 'block';
            });
            document.querySelectorAll('.toggle-arrow').forEach(function(el) {
                el.classList.add('expanded');
            });
        }

        function collapseAll() {
            document.querySelectorAll('.module-content, .case-detail').forEach(function(el) {
                el.style.display = 'none';
            });
            document.querySelectorAll('.toggle-arrow').forEach(function(el) {
                el.classList.remove('expanded');
            });
        }

        // 从汇总表跳转到用例详情：展开模块 → 展开用例 → 滚动定位
        function scrollToDetail(detailId, moduleContentId, moduleArrowId) {
            // 1. 确保模块展开
            var moduleContent = document.getElementById(moduleContentId);
            if (moduleContent && moduleContent.style.display === 'none') {
                toggleSection(moduleContentId, moduleArrowId);
            }
            // 2. 确保用例详情展开
            var detail = document.getElementById(detailId);
            if (detail && detail.style.display === 'none') {
                var caseArrowId = detailId.replace('-detail', '-arrow');
                toggleSection(detailId, caseArrowId);
            }
            // 3. 滚动到目标位置
            if (detail) {
                setTimeout(function() {
                    detail.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // 高亮闪烁效果
                    var card = detail.closest('.case-card');
                    if (card) {
                        card.style.transition = 'box-shadow 0.3s';
                        card.style.boxShadow = '0 0 0 3px #1890ff';
                        setTimeout(function() {
                            card.style.boxShadow = '';
                        }, 2000);
                    }
                }, 100);
            }
        }

        // 页面加载时，自动展开包含失败用例的模块
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('.module-has-failure').forEach(function(el) {
                var contentId = el.getAttribute('data-content-id');
                if (contentId) {
                    var content = document.getElementById(contentId);
                    if (content) content.style.display = 'block';
                }
            });
        });
    '''
