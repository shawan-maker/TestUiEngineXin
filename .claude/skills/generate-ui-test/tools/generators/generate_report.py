"""脚本生成报告生成器

输出 HTML 报告至 report/generate_report/generation_report.html
格式：自包含 HTML（内联 CSS + JS），模块/用例可收起，步骤为表格

表格列：步骤编号、关键字、描述、输入数据、实际数据、元素定位、实际定位器、探测结果、备注
"""
import yaml
import json
import glob
import os
import sys
from datetime import datetime


def load_probe_results(probe_dir):
    """加载探测结果"""
    probe_db = {}
    for f in glob.glob(os.path.join(probe_dir, "**/*.json"), recursive=True):
        try:
            data = json.load(open(f, encoding='utf-8'))
            if isinstance(data, list):
                for el in data:
                    key = el.get('key', '')
                    if key:
                        probe_db[key] = el
            elif isinstance(data, dict):
                for el in data.get('elements', []):
                    key = el.get('key', '')
                    if key:
                        probe_db[key] = el
        except Exception:
            pass
    return probe_db


def load_resources(project_dir):
    """加载 data/ 和 pages/ 下所有 YAML，展平为点分键字典

    用于解析步骤中的变量引用 ${group.key} 到实际值。
    """
    resources = {}
    for subdir in ('data', 'pages'):
        base = os.path.join(project_dir, subdir)
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                if not f.endswith('.yaml'):
                    continue
                try:
                    data = yaml.safe_load(
                        open(os.path.join(root, f), encoding='utf-8'))
                    if data and isinstance(data, dict):
                        resources.update(_flatten_dict(data))
                except Exception:
                    pass
    return resources


def _flatten_dict(d, parent_key='', sep='.'):
    """将嵌套字典展平为点分键"""
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items


def extract_input(step):
    """从步骤中提取输入数据（变量引用形式）"""
    params = step.get('params', {})
    inputs = []
    if 'value' in params:
        inputs.append(str(params['value']))
    if 'expect_results' in params:
        inputs.append(f"期望: {params['expect_results']}")
    if 'url' in params:
        inputs.append(params['url'])
    if 'timeout' in params:
        inputs.append(f"超时: {params['timeout']}ms")
    return ' | '.join(inputs) if inputs else '—'


def resolve_value(text, resources):
    """解析变量引用 ${group.key} 到实际值，无引用时返回 —"""
    if not text or not isinstance(text, str) or '${' not in text:
        return '—'
    import re
    parts = re.findall(r'\$\{(.+?)\}', text)
    if not parts:
        return '—'
    resolved = []
    for part in parts:
        val = resources.get(part)
        resolved.append(str(val) if val is not None else f'${{{part}}}')
    return ' | '.join(resolved)


def get_locator_ref(step):
    """获取步骤的元素定位器引用（原始变量引用形式）"""
    return step.get('params', {}).get('locator', '—')


def check_probe_status(step, probe_db, l3_keywords=None, is_conditional=False):
    """检查步骤的探测状态（✅/❌/⚠️/— 四种）

    ✅ 探测成功（probe verified=true）
    ❌ 探测失败（probe verified=false 或无 probe 记录）
    ⚠️ 待确认（条件分支内的 locator，依赖运行时状态）
    —  不需要探测（步骤无 locator，如 open_url/refresh/wait 等）

    所有涉及元素定位的步骤都必须探测，包括硬编码 XPath。
    is_conditional=True 时，未探测的 locator 标记为 ⚠️ 而非 ❌。
    """
    keyword = step.get('keyword', '')
    locator = step.get('params', {}).get('locator', '')

    # 不需要探测的步骤（无 locator 的操作）
    if keyword in ('open_url', 'refresh', 'wait_for_time',
                   'wait_for_element_hidden', 'execute_script',
                   'inject_local_storage', 'inject_cookies',
                   'set_variable'):
        return '—'

    # 条件检查关键字本身标记为 ⚠️
    if keyword in ('if_element_visible', 'if_element_not_visible',
                   'if_variable', 'if_text_visible'):
        return '⚠️'

    # L3 关键字：标记为 L3（内部子步骤各自独立标记）
    if l3_keywords and keyword in l3_keywords:
        return '✅(L3)'

    # 数据引用（${xxx_data.yyy}）不是 locator，不需要探测
    if isinstance(locator, str) and '_data.' in locator:
        return '—'

    # 没有 locator 参数的步骤
    if not locator or locator == '—':
        return '—'

    # 变量引用 ${group.field} → 查 probe DB
    if isinstance(locator, str) and '${' in locator:
        parts = locator.split('.')
        if len(parts) >= 2:
            var_name = parts[-1].strip('}"')
            if var_name in probe_db:
                return '✅' if probe_db[var_name].get('verified') else '❌'
            else:
                # _input 伴生兜底：xxx_input 无 probe 记录，但 xxx_select 已验证
                if var_name.endswith('_input'):
                    select_key = var_name[:-6] + '_select'
                    if select_key in probe_db and probe_db[select_key].get('verified'):
                        return '✅'
                # 条件分支内的 locator → ⚠️ 待确认
                if is_conditional:
                    return '⚠️'
                return '❌'  # 探测失败

    # 硬编码 locator（xpath=, css, //...）→ 也必须有 probe 记录
    if isinstance(locator, str) and locator.strip():
        # 在 probe DB 中搜索匹配的 locator
        for key, el in probe_db.items():
            if el.get('locator', '') == locator:
                return '✅' if el.get('verified') else '❌'
        # 条件分支内的 locator → ⚠️ 待确认
        if is_conditional:
            return '⚠️'
        return '❌'  # 硬编码但无 probe 记录 = 失败

    return '—'


def generate_remark(step, probe_db, case_file, l3_keywords=None):
    """生成备注（来源标注 + 失败修改建议）

    探测成功 → 标注来源（知识库/L3/AI生成）
    探测失败 → 给出修改文件路径
    不需要探测 → 空
    """
    keyword = step.get('keyword', '')
    locator = step.get('params', {}).get('locator', '')

    # 不需要探测的步骤
    if keyword in ('open_url', 'refresh', 'wait_for_time',
                   'wait_for_element_hidden', 'execute_script',
                   'inject_local_storage', 'inject_cookies',
                   'set_variable'):
        return ''

    # L3 关键字
    if l3_keywords and keyword in l3_keywords:
        return f'L3:{keyword}'

    # 数据引用
    if isinstance(locator, str) and '_data.' in locator:
        return ''

    # 没有 locator
    if not locator or locator == '—':
        return ''

    # 变量引用
    if isinstance(locator, str) and '${' in locator:
        parts = locator.split('.')
        if len(parts) >= 2:
            group = parts[-2] if len(parts) > 2 else ''
            var_name = parts[-1].strip('}"')

            if var_name in probe_db:
                el = probe_db[var_name]
                if el.get('verified'):
                    source = el.get('strategy', '')
                    if el.get('from_knowledge'):
                        return '知识库'
                    elif 'fallback' in source or 'any-tag' in source:
                        return 'AI生成'
                    elif 'direct-verify' in source:
                        return '直接验证'
                    else:
                        return source or '知识库'
                else:
                    module = os.path.basename(
                        os.path.dirname(case_file)) if os.sep in case_file else group
                    return f"探测失败，请检查 pages/{module}/ 中 {group}.{var_name} 的定位器"
            else:
                # _input 伴生兜底
                if var_name.endswith('_input'):
                    select_key = var_name[:-6] + '_select'
                    if select_key in probe_db and probe_db[select_key].get('verified'):
                        return '知识库（伴生）'
                module = os.path.basename(
                    os.path.dirname(case_file)) if os.sep in case_file else group
                return f"探测失败，请检查 pages/{module}/ 中 {group}.{var_name} 的定位器"

    # 硬编码 locator → 无 probe 记录 = 失败
    if isinstance(locator, str) and locator.strip():
        for key, el in probe_db.items():
            if el.get('locator', '') == locator and el.get('verified'):
                return '知识库'
        module = os.path.basename(
            os.path.dirname(case_file)) if os.sep in case_file else ''
        return f"探测失败，请补充探测并写入 pages/{module}/"

    return ''


# ---------------------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UIEngine 脚本生成报告 - {project}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#f5f6fa;color:#2c3e50;line-height:1.6;padding:20px 30px}}
.header{{background:linear-gradient(135deg,#2c3e50,#3498db);color:#fff;
  padding:24px 30px;border-radius:8px;margin-bottom:20px}}
.header h1{{font-size:22px;margin-bottom:6px}}
.header p{{opacity:.85;font-size:13px}}
.summary{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
.card{{background:#fff;padding:14px 22px;border-radius:8px;
  box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center;min-width:110px}}
.card .num{{font-size:26px;font-weight:700}}
.card .label{{font-size:12px;color:#7f8c8d}}
.card.ok .num{{color:#27ae60}}
.card.fail .num{{color:#e74c3c}}
.card.warn .num{{color:#f39c12}}
.card.total .num{{color:#2c3e50}}
.module{{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);
  margin-bottom:14px;overflow:hidden}}
.module>summary{{padding:14px 20px;font-size:15px;font-weight:600;cursor:pointer;
  background:#ecf0f1;list-style:none;display:flex;align-items:center;gap:8px}}
.module>summary::-webkit-details-marker{{display:none}}
.module>summary::before{{content:'▶';font-size:10px;transition:transform .2s}}
.module[open]>summary::before{{transform:rotate(90deg)}}
.module-body{{padding:10px 20px 18px}}
.case{{margin-bottom:8px;border:1px solid #e8e8e8;border-radius:6px}}
.case>summary{{padding:8px 14px;cursor:pointer;font-size:13px;
  background:#fafbfc;list-style:none;display:flex;align-items:center;gap:6px}}
.case>summary::-webkit-details-marker{{display:none}}
.case>summary::before{{content:'▶';font-size:9px;transition:transform .2s}}
.case[open]>summary::before{{transform:rotate(90deg)}}
.case-body{{padding:4px 14px 10px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f8f9fa;padding:6px 8px;text-align:left;font-weight:600;
  border-bottom:2px solid #dee2e6;white-space:nowrap}}
td{{padding:5px 8px;border-bottom:1px solid #eee;vertical-align:top;max-width:220px;
  word-break:break-all}}
tr:hover{{background:#f8f9fa}}
tr.l3-sub td{{padding-left:20px;background:#f8f9fc;font-size:11px}}
tr.l3-sub td:first-child{{color:#7f8c8d}}
code{{background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:11px;
  word-break:break-all}}
.st-ok{{color:#27ae60;font-weight:700}}
.st-fail{{color:#e74c3c;font-weight:700}}
.st-warn{{color:#f39c12;font-weight:700}}
.st-skip{{color:#95a5a6}}
.badge{{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
  font-weight:600}}
.badge-ok{{background:#d5f5e3;color:#27ae60}}
.badge-fail{{background:#fadbd8;color:#e74c3c}}
.btn-expand{{background:#3498db;color:#fff;border:none;padding:6px 14px;
  border-radius:4px;cursor:pointer;font-size:12px;margin-bottom:10px}}
.btn-expand:hover{{background:#2980b9}}
</style>
</head>
<body>

<div class="header">
  <h1>UIEngine 脚本生成报告</h1>
  <p>项目：{project} &nbsp;|&nbsp; 生成时间：{timestamp}</p>
</div>

<div class="summary">
  <div class="card total"><div class="num">{total_cases}</div><div class="label">总用例</div></div>
  <div class="card total"><div class="num">{total_steps}</div><div class="label">总步骤</div></div>
  <div class="card ok"><div class="num">{success_steps}</div><div class="label">探测成功</div></div>
  <div class="card fail"><div class="num">{fail_steps}</div><div class="label">探测失败</div></div>
  <div class="card warn"><div class="num">{warn_steps}</div><div class="label">待确认</div></div>
</div>

{modules_html}

<script>
function expandAll(){{
  document.querySelectorAll('details').forEach(d=>d.open=true);
}}
function collapseAll(){{
  document.querySelectorAll('details').forEach(d=>d.open=false);
}}
</script>
<div style="margin-top:12px">
  <button class="btn-expand" onclick="expandAll()">展开全部</button>
  <button class="btn-expand" onclick="collapseAll()" style="background:#95a5a6">收起全部</button>
</div>

</body>
</html>"""


def _esc(text):
    """HTML 转义"""
    if not isinstance(text, str):
        text = str(text)
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;'))


def _status_class(status):
    if '✅' in status:
        return 'st-ok'
    if '❌' in status:
        return 'st-fail'
    if '⚠' in status:
        return 'st-warn'
    return 'st-skip'


def _module_badge(fail):
    if fail > 0:
        return '<span class="badge badge-fail">❌</span>'
    return '<span class="badge badge-ok">✅</span>'


def _extract_module_cn_name(module_name, cases):
    """从用例描述中提取模块中文名

    策略：从第一个用例的 desc 中提取前缀作为模块中文名。
    例如 "访问交付问题列表，新增一条问题记录" → "交付问题列表"
    如果无法提取，返回空字符串。
    """
    if not cases:
        return ''

    # 尝试从 suite YAML 的 desc 中获取（通过 project_dir 读取）
    # 先从第一个用例的 name（即 desc）中推断
    first_name = cases[0].get('name', '')
    if not first_name:
        return ''

    # 匹配模式：从 "访问/检查/验证 XX列表/页面/模块" 中提取 XX
    import re
    m = re.search(r'(?:访问|检查|验证|操作)([^\s,，、]+?(?:列表|页面|模块|中心|管理))', first_name)
    if m:
        return m.group(1)

    # 回退：用模块目录名的中文映射
    MODULE_CN_MAP = {
        'delivery-issues': '交付问题',
        'demo': '演示',
        'instationmail': '站内信',
        'workorder': '工单',
        'overview-page': '总览页',
    }
    return MODULE_CN_MAP.get(module_name, '')


def _generate_html(project, timestamp, total_cases, total_steps,
                   success_steps, fail_steps, warn_steps, modules):
    """生成完整 HTML 字符串"""
    parts = []
    for module_name, cases in modules.items():
        m_fail = sum(1 for c in cases
                     for s in c['steps'] if '❌' in s['probe_status'])
        badge = _module_badge(m_fail)

        # 从用例描述中提取模块中文名（取第一个用例描述的前缀）
        module_cn = _extract_module_cn_name(module_name, cases)
        module_display = f"{module_cn} - {module_name}" if module_cn else module_name

        case_summaries = []
        for case in cases:
            c_fail = sum(1 for s in case['steps']
                         if '❌' in s['probe_status'])
            c_badge = _module_badge(c_fail)
            case_summaries.append(
                f'{c_badge} {_esc(case["name"])} — {_esc(case["file"])}')

        parts.append(f"""<details class="module"{' open' if m_fail > 0 else ''}>
<summary>{badge} {_esc(module_display)} ({len(cases)} 用例)</summary>
<div class="module-body">
{''.join(_render_case(c) for c in cases)}
</div>
</details>""")

    modules_html = '\n'.join(parts)

    return HTML_TEMPLATE.format(
        project=_esc(project),
        timestamp=_esc(timestamp),
        total_cases=total_cases,
        total_steps=total_steps,
        success_steps=success_steps,
        fail_steps=fail_steps,
        warn_steps=warn_steps,
        modules_html=modules_html,
    )


def _render_case(case):
    """渲染单个用例的 HTML（details + table）"""
    c_fail = sum(1 for s in case['steps'] if '❌' in s['probe_status'])
    badge = _module_badge(c_fail)
    is_open = ' open' if c_fail > 0 else ''

    rows = []
    for s in case['steps']:
        sc = _status_class(s['probe_status'])
        remark_html = _esc(s['remark']) if s['remark'] else ''
        is_sub = s.get('is_l3') is False and '.' in str(s.get('number', ''))
        row_cls = ' class="l3-sub"' if is_sub else ''
        kw_display = _esc(s['keyword']) if is_sub else s['keyword']
        rows.append(f"""<tr{row_cls}>
<td>{s['number']}</td>
<td><code>{kw_display}</code></td>
<td>{_esc(s['desc'])}</td>
<td>{_esc(s['input'])}</td>
<td>{_esc(s['resolved_input'])}</td>
<td><code>{_esc(s['locator'])}</code></td>
<td><code>{_esc(s['resolved_locator'])}</code></td>
<td class="{sc}">{s['probe_status']}</td>
<td>{remark_html}</td>
</tr>""")

    return f"""<details class="case"{is_open}>
<summary>{badge} {_esc(case['name'])} — {_esc(case['file'])}</summary>
<div class="case-body">
<table>
<thead><tr>
<th>步骤</th><th>关键字</th><th>描述</th>
<th>输入数据</th><th>实际数据</th>
<th>元素定位</th><th>实际定位器</th>
<th>探测结果</th><th>备注</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</div>
</details>
"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_report(project_dir, output_path):
    """生成脚本生成报告（HTML 格式）"""
    cases_dir = os.path.join(project_dir, 'cases')
    probe_dir = os.path.join(project_dir, '_probe')

    probe_db = load_probe_results(probe_dir)
    resources = load_resources(project_dir)
    l3_keywords = _load_l3_keyword_names(project_dir)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project = os.path.basename(project_dir)

    total_cases = 0
    total_steps = 0
    success_steps = 0
    fail_steps = 0
    warn_steps = 0

    modules = {}

    for module in sorted(os.listdir(cases_dir)):
        module_dir = os.path.join(cases_dir, module)
        if not os.path.isdir(module_dir):
            continue

        module_cases = []
        for case_file in sorted(glob.glob(os.path.join(module_dir, "*.yaml"))):
            # M19: 确保按文件名数字前缀排序（与 Excel 行号顺序一致）
            try:
                case_data = yaml.safe_load(
                    open(case_file, encoding='utf-8'))
            except Exception:
                continue
            if not case_data or 'steps' not in case_data:
                continue

            total_cases += 1
            steps = []
            step_num = 0
            for step in case_data.get('steps', []):
                step_num += 1
                total_steps += 1
                status = check_probe_status(step, probe_db, l3_keywords)
                if '✅' in status:
                    success_steps += 1
                elif '❌' in status:
                    fail_steps += 1
                elif '⚠' in status:
                    warn_steps += 1

                locator_ref = get_locator_ref(step)
                input_text = extract_input(step)

                steps.append({
                    "number": str(step_num),
                    "keyword": step.get('keyword', ''),
                    "desc": step.get('desc', ''),
                    "input": input_text,
                    "resolved_input": resolve_value(input_text, resources),
                    "locator": locator_ref,
                    "resolved_locator": resolve_value(
                        locator_ref, resources),
                    "probe_status": status,
                    "remark": generate_remark(
                        step, probe_db, case_file, l3_keywords),
                    "is_l3": step.get('keyword', '') in l3_keywords,
                })

                # L3 关键字：展开内部子步骤
                if step.get('keyword', '') in l3_keywords:
                    sub_steps = _expand_l3_steps(
                        step, probe_db, resources, case_file, l3_keywords)
                    for sub_idx, sub in enumerate(sub_steps, 1):
                        total_steps += 1
                        sub_status = sub['probe_status']
                        if '✅' in sub_status:
                            success_steps += 1
                        elif '❌' in sub_status:
                            fail_steps += 1
                        elif '⚠' in sub_status:
                            warn_steps += 1
                        sub['number'] = f"{step_num}.{sub_idx}"
                        sub['is_l3'] = False
                        steps.append(sub)

                # 条件分支（if_element_visible 等）：展开 then_steps/else_steps
                kw = step.get('keyword', '')
                if kw in ('if_element_visible', 'if_element_not_visible',
                          'if_variable', 'if_text_visible'):
                    params = step.get('params', {})
                    for branch_key in ('then_steps', 'else_steps'):
                        branch_steps = params.get(branch_key, [])
                        if not isinstance(branch_steps, list):
                            continue
                        branch_label = 'then' if branch_key == 'then_steps' else 'else'
                        for sub_idx, sub_step in enumerate(branch_steps, 1):
                            if not isinstance(sub_step, dict):
                                continue
                            total_steps += 1
                            sub_status = check_probe_status(
                                sub_step, probe_db, l3_keywords,
                                is_conditional=True)
                            if '✅' in sub_status:
                                success_steps += 1
                            elif '❌' in sub_status:
                                fail_steps += 1
                            elif '⚠' in sub_status:
                                warn_steps += 1
                            sub_locator_ref = get_locator_ref(sub_step)
                            sub_input = extract_input(sub_step)
                            steps.append({
                                "number": f"{step_num}.{branch_label}{sub_idx}",
                                "keyword": sub_step.get('keyword', ''),
                                "desc": sub_step.get('desc', ''),
                                "input": sub_input,
                                "resolved_input": resolve_value(sub_input, resources),
                                "locator": sub_locator_ref,
                                "resolved_locator": resolve_value(
                                    sub_locator_ref, resources),
                                "probe_status": sub_status,
                                "remark": generate_remark(
                                    sub_step, probe_db, case_file, l3_keywords),
                                "is_l3": False,
                            })

            module_cases.append({
                "file": os.path.basename(case_file),
                "id": case_data.get('id', ''),
                "name": case_data.get('name') or case_data.get('desc', ''),
                "steps": steps,
            })

        if module_cases:
            modules[module] = module_cases

    html = _generate_html(
        project, timestamp, total_cases, total_steps,
        success_steps, fail_steps, warn_steps, modules)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"报告已生成: {output_path}")
    print(f"总计: {total_cases} 用例, {total_steps} 步骤, "
          f"成功 {success_steps}, 失败 {fail_steps}, 待确认 {warn_steps}")


def _load_l3_keyword_names(project_dir):
    """从 _knowledge/*.yaml 加载 L3 关键字名称集合（兼容 list/dict 格式）"""
    names = set()
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if not os.path.isdir(knowledge_dir):
        return names
    for f in glob.glob(os.path.join(knowledge_dir, "*.yaml")):
        try:
            data = yaml.safe_load(open(f, encoding='utf-8'))
            if data and isinstance(data, dict):
                workflows = data.get('workflows', {})
                if isinstance(workflows, list):
                    for wf in workflows:
                        if isinstance(wf, dict) and 'name' in wf:
                            names.add(wf['name'])
                elif isinstance(workflows, dict):
                    for wf_name in workflows:
                        names.add(wf_name)
        except Exception:
            pass
    return names


def _expand_l3_steps(step, probe_db, resources, case_file, l3_keywords):
    """展开 L3 关键字为内部子步骤"""
    keyword = step.get('keyword', '')
    knowledge_dir = os.path.join(
        os.path.dirname(case_file), '..', '..', '_knowledge')

    # 从 _knowledge/ 中找到定义该 workflow 的文件
    workflow_steps = []
    for f in glob.glob(os.path.join(knowledge_dir, "*.yaml")):
        try:
            data = yaml.safe_load(open(f, encoding='utf-8'))
            if not data or not isinstance(data, dict):
                continue
            workflows = data.get('workflows', {})
            wf = None
            if isinstance(workflows, list):
                for item in workflows:
                    if isinstance(item, dict) and item.get('name') == keyword:
                        wf = item
                        break
            elif isinstance(workflows, dict):
                wf = workflows.get(keyword)
            if wf and isinstance(wf, dict):
                workflow_steps = wf.get('steps', [])
                break
        except Exception:
            continue

    # 将 workflow 内部步骤转为报告步骤格式
    result = []
    for sub in _iter_wf_steps(workflow_steps):
        sub_locator = sub.get('params', {}).get('locator', '—')
        sub_input = extract_input(sub)
        sub_status = check_probe_status(sub, probe_db, l3_keywords)
        sub_remark = generate_remark(sub, probe_db, case_file, l3_keywords)

        result.append({
            "keyword": f"└ {sub.get('keyword', '')}",
            "desc": sub.get('desc', ''),
            "input": sub_input,
            "resolved_input": resolve_value(sub_input, resources),
            "locator": sub_locator,
            "resolved_locator": resolve_value(sub_locator, resources),
            "probe_status": sub_status,
            "remark": sub_remark or f'L3:{keyword}',
        })
    return result


def _iter_wf_steps(steps):
    """递归遍历 workflow steps（含 then_steps/else_steps）"""
    if not isinstance(steps, list):
        return
    for s in steps:
        if not isinstance(s, dict):
            continue
        yield s
        params = s.get('params', {})
        if isinstance(params, dict):
            for sub_key in ('then_steps', 'else_steps'):
                yield from _iter_wf_steps(params.get(sub_key, []))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <project_dir> [output_path]")
        print("示例: python generate_report.py TSManager")
        sys.exit(1)

    project_dir = sys.argv[1]
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        output_path = os.path.join(
            project_dir, 'report', 'generate_report',
            'generation_report.html')
    generate_report(project_dir, output_path)
