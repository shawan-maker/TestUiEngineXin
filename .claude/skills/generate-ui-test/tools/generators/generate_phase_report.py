#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_phase_report.py — TSManager2 Phase 4/5/6 详细对比报告

输出到 docs/debug/tsmanager2_phase_report.md，包含：
  1. Phase 4 探测统计（按模块×URL）
  2. Phase 5 写入成功率（按用例）
  3. Phase 6 探测成功率（按用例）
  4. Phase 5 vs 6 对比表格（按用例，具体 locator 值）
"""

import json
import os
import re
import sys
import yaml
from pathlib import Path
from datetime import datetime

# Windows 控制台 UTF-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def load_json(path):
    """加载 JSON 文件"""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_yaml(path):
    """加载 YAML 文件"""
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def get_discovery_stats(project_dir):
    """Phase 4: 统计每个 discovery JSON 的探测结果"""
    probe_dir = Path(project_dir) / "_probe"
    stats = {}

    for disc_file in sorted(probe_dir.glob("discovery_*.json")):
        if disc_file.name.endswith('_merged.json'):
            continue
        module = disc_file.stem.replace('discovery_', '')
        try:
            disc = load_json(disc_file)
        except Exception:
            continue

        # 统计探测结果
        url = disc.get('url', '')
        list_page = disc.get('list_page', {})
        containers = disc.get('containers', [])

        # 输入框统计
        inputs = list_page.get('inputs', [])
        buttons = list_page.get('buttons', [])

        # 容器内按钮统计
        container_buttons = []
        dropdown_items = []
        for c in containers:
            ctype = c.get('type', '')
            cbtns = c.get('buttons', [])
            for b in cbtns:
                container_buttons.append({
                    'container_type': ctype,
                    'container_name': c.get('name', ''),
                    'button': b
                })
            # 下拉菜单项
            if ctype in ('dropdown-menu', 'more-menu'):
                for item in c.get('items', []):
                    dropdown_items.append({
                        'container_type': ctype,
                        'container_name': c.get('name', ''),
                        'item': item
                    })

        verified_count = 0
        unverified_count = 0
        failed_reasons = []

        for inp in inputs:
            if inp.get('verified'):
                verified_count += 1
            else:
                unverified_count += 1
                reason = inp.get('error', 'unknown')
                failed_reasons.append(f"input '{inp.get('label','?')}': {reason}")

        for btn in buttons:
            if btn.get('verified'):
                verified_count += 1
            else:
                unverified_count += 1
                reason = btn.get('error', 'unknown')
                failed_reasons.append(f"button '{btn.get('text','?')}': {reason}")

        for cb in container_buttons:
            b = cb['button']
            if b.get('verified'):
                verified_count += 1
            else:
                unverified_count += 1
                reason = b.get('error', 'unknown')
                failed_reasons.append(
                    f"container-btn '{cb['container_type']}/{b.get('text','?')}': {reason}")

        for di in dropdown_items:
            item = di['item']
            if item.get('verified'):
                verified_count += 1
            else:
                unverified_count += 1
                reason = item.get('error', 'unknown')
                failed_reasons.append(
                    f"dropdown-item '{di['container_type']}/{item.get('text','?')}': {reason}")

        stats[module] = {
            'url': url,
            'total': verified_count + unverified_count,
            'verified': verified_count,
            'unverified': unverified_count,
            'failed_reasons': failed_reasons,
            'inputs_count': len(inputs),
            'buttons_count': len(buttons),
            'container_buttons_count': len(container_buttons),
            'dropdown_items_count': len(dropdown_items),
            'containers_count': len(containers),
        }

    return stats


def extract_locator_steps(case_steps):
    """从用例步骤中提取需要 locator 的步骤（排除断言、等待等）"""
    locator_steps = []
    for step in case_steps:
        desc = step.get('desc', '')
        keyword = step.get('keyword', '')

        # 排除不需要 locator 的步骤
        skip_keywords = [
            'assert_element_visible', 'assert_text_contains',
            'wait_for_time', 'wait_for_element_hidden',
            'open_url', 'open_browser', 'refresh',
            'close_browser', 'screenshot',
        ]
        if keyword in skip_keywords:
            continue

        # 排除断言步骤
        if '断言' in desc:
            continue

        # 提取 locator
        params = step.get('params', {})
        locator = params.get('locator', '')
        if locator:
            locator_steps.append({
                'desc': desc,
                'keyword': keyword,
                'locator': locator,
                'step': step,
            })

        # 检查 then_steps / else_steps 中的子步骤
        then_steps = params.get('then_steps', [])
        else_steps = params.get('else_steps', [])
        for sub in (then_steps or []) + (else_steps or []):
            sub_params = sub.get('params', {})
            sub_locator = sub_params.get('locator', '')
            if sub_locator and sub.get('keyword') not in skip_keywords:
                locator_steps.append({
                    'desc': f"  → {sub.get('desc', '')}",
                    'keyword': sub.get('keyword', ''),
                    'locator': sub_locator,
                    'step': sub,
                    'is_sub_step': True,
                })

    return locator_steps


def get_phase5_stats(project_dir, excel_data):
    """Phase 5: 统计每个用例的 locator 写入状态"""
    cases_dir = Path(project_dir) / "cases"
    pages_dir = Path(project_dir) / "pages"

    # 加载所有 pages YAML
    pages_refs = {}
    for yaml_file in pages_dir.rglob("*.yaml"):
        try:
            data = load_yaml(yaml_file)
            if isinstance(data, dict):
                for group, fields in data.items():
                    if isinstance(fields, dict):
                        if group not in pages_refs:
                            pages_refs[group] = {}
                        pages_refs[group].update(fields)
        except Exception:
            pass

    case_stats = []

    for sheet in excel_data:
        sheet_name = sheet.get('sheet', '')
        for case_data in sheet.get('cases', []):
            case_name = case_data.get('case_name', '')
            module = case_data.get('module', '')
            steps = case_data.get('steps', [])

            # 查找对应的 case YAML
            case_file = _find_case_yaml(cases_dir, module, case_name)
            if not case_file:
                case_stats.append({
                    'sheet': sheet_name,
                    'module': module,
                    'case_name': case_name,
                    'total_locator_steps': 0,
                    'verified': 0,
                    'pending': 0,
                    'locator_details': [],
                    'case_file_found': False,
                })
                continue

            # 加载 case YAML
            try:
                case_yaml = load_yaml(case_file)
            except Exception:
                continue

            case_steps = case_yaml.get('steps', [])
            locator_steps = extract_locator_steps(case_steps)

            verified = 0
            pending = 0
            details = []

            for ls in locator_steps:
                locator = ls['locator']
                is_pending = '[待确认]' in locator or locator.startswith('xpath=//*[')

                if is_pending:
                    pending += 1
                    status = '待确认'
                else:
                    # 检查 locator 引用的 pages 元素是否存在
                    ref_match = re.search(r'\$\{([^}]+)\}', locator)
                    if ref_match:
                        ref = ref_match.group(1)
                        parts = ref.split('.', 1)
                        if len(parts) == 2:
                            group, field = parts
                            if group in pages_refs and field in pages_refs[group]:
                                resolved = pages_refs[group][field]
                                status = 'verify通过'
                                verified += 1
                                locator = resolved
                            else:
                                status = '待确认'
                                pending += 1
                        else:
                            status = '待确认'
                            pending += 1
                    else:
                        # 硬编码 locator
                        status = 'verify通过'
                        verified += 1

                details.append({
                    'desc': ls['desc'],
                    'keyword': ls['keyword'],
                    'locator': locator,
                    'status': status,
                    'is_sub_step': ls.get('is_sub_step', False),
                })

            case_stats.append({
                'sheet': sheet_name,
                'module': module,
                'case_name': case_name,
                'total_locator_steps': len(locator_steps),
                'verified': verified,
                'pending': pending,
                'locator_details': details,
                'case_file_found': True,
            })

    return case_stats


def get_phase6_stats(project_dir, excel_data):
    """Phase 6: 统计 verify_locators 后的结果"""
    verify_file = Path(project_dir) / "_probe" / "verify_result.json"
    if not verify_file.exists():
        return {}

    verify_data = load_json(verify_file)

    # verify_result.json 格式: {results: [{locator, status, ...}, ...]}
    results = verify_data.get('results', [])
    locator_map = {}
    for r in results:
        key = r.get('locator', '') or r.get('ref', '')
        locator_map[key] = {
            'status': r.get('status', 'unknown'),
            'resolved_locator': r.get('resolved', r.get('locator', '')),
            'method': r.get('method', ''),
            'error': r.get('error', ''),
        }

    return locator_map


def _find_case_yaml(cases_dir, module, case_name):
    """根据模块和用例名查找 case YAML 文件"""
    module_dir = cases_dir / module
    if not module_dir.exists():
        # 尝试常见变体
        for d in cases_dir.iterdir():
            if d.is_dir():
                for f in d.rglob("*.yaml"):
                    try:
                        data = load_yaml(f)
                        if data and data.get('name', '') == case_name:
                            return f
                    except Exception:
                        pass
        return None

    for f in module_dir.rglob("*.yaml"):
        try:
            data = load_yaml(f)
            if data and data.get('name', '') == case_name:
                return f
        except Exception:
            pass

    return None


def generate_report(project_dir, excel_data, output_path):
    """生成完整的 Phase 4/5/6 对比报告"""
    print("[1/4] 收集 Phase 4 探测统计...")
    discovery_stats = get_discovery_stats(project_dir)

    print("[2/4] 收集 Phase 5 写入统计...")
    phase5_stats = get_phase5_stats(project_dir, excel_data)

    print("[3/4] 收集 Phase 6 验证结果...")
    phase6_results = get_phase6_stats(project_dir, excel_data)

    print("[4/4] 生成 Markdown 报告...")

    lines = []
    lines.append(f"# TSManager2 Phase 4/5/6 详细报告")
    lines.append(f"")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"项目路径: `{project_dir}`")
    lines.append(f"")

    # ── Section 1: Phase 4 探测统计 ──
    lines.append(f"## 1. Phase 4 探测统计（按模块×URL）")
    lines.append(f"")

    total_verified = 0
    total_unverified = 0

    for module, stats in discovery_stats.items():
        total_verified += stats['verified']
        total_unverified += stats['unverified']

        lines.append(f"### 模块: {module}")
        lines.append(f"")
        lines.append(f"- **URL**: `{stats['url']}`")
        lines.append(f"- **总探测元素数**: {stats['total']}")
        lines.append(f"- **验证通过**: {stats['verified']}")
        lines.append(f"- **未验证**: {stats['unverified']}")
        if stats['total'] > 0:
            rate = stats['verified'] / stats['total'] * 100
            lines.append(f"- **验证率**: {rate:.1f}%")
        lines.append(f"- **输入框**: {stats['inputs_count']}")
        lines.append(f"- **列表按钮**: {stats['buttons_count']}")
        lines.append(f"- **容器按钮**: {stats['container_buttons_count']}")
        lines.append(f"- **下拉菜单项**: {stats['dropdown_items_count']}")
        lines.append(f"- **容器数**: {stats['containers_count']}")
        lines.append(f"")

        if stats['failed_reasons']:
            lines.append(f"**未验证原因**:")
            lines.append(f"")
            for reason in stats['failed_reasons']:
                lines.append(f"  - {reason}")
            lines.append(f"")

    lines.append(f"**Phase 4 汇总**:")
    lines.append(f"- 总探测元素: {total_verified + total_unverified}")
    lines.append(f"- 验证通过: {total_verified}")
    lines.append(f"- 未验证: {total_unverified}")
    total_all = total_verified + total_unverified
    if total_all > 0:
        lines.append(f"- 总体验证率: {total_verified/total_all*100:.1f}%")
    lines.append(f"")

    # ── Section 2: Phase 5 写入成功率 ──
    lines.append(f"## 2. Phase 5 写入成功率（按用例）")
    lines.append(f"")
    lines.append(f"统计口径: 排除断言、等待、open_url 等不需要 locator 的步骤")
    lines.append(f"")

    p5_total = 0
    p5_verified = 0
    p5_pending = 0

    lines.append(f"| # | Sheet | 用例名称 | 总步骤数 | 成功 | 待确认 | 成功率 |")
    lines.append(f"|---|-------|---------|---------|------|--------|--------|")

    for i, cs in enumerate(phase5_stats, 1):
        p5_total += cs['total_locator_steps']
        p5_verified += cs['verified']
        p5_pending += cs['pending']

        rate = f"{cs['verified']/cs['total_locator_steps']*100:.0f}%" if cs['total_locator_steps'] > 0 else "N/A"
        lines.append(
            f"| {i} | {cs['sheet']} | {cs['case_name']} | "
            f"{cs['total_locator_steps']} | {cs['verified']} | {cs['pending']} | {rate} |"
        )

    lines.append(f"")
    p5_rate = f"{p5_verified/p5_total*100:.1f}%" if p5_total > 0 else "N/A"
    lines.append(f"**Phase 5 汇总**:")
    lines.append(f"- 总 locator 步骤: {p5_total}")
    lines.append(f"- 成功写入: {p5_verified}")
    lines.append(f"- 待确认: {p5_pending}")
    lines.append(f"- 总体写入率: {p5_rate}")
    lines.append(f"")

    # ── Section 3: Phase 6 探测成功率 ──
    lines.append(f"## 3. Phase 6 探测成功率（按用例）")
    lines.append(f"")
    lines.append(f"统计口径: Phase 6 verify_locators 运行时验证结果")
    lines.append(f"")

    if not phase6_results:
        lines.append(f"**Phase 6 尚未执行或 verify_result.json 不存在**")
        lines.append(f"")
    else:
        lines.append(f"| # | 用例名称 | 探测总数 | 成功 | 失败/fallback | 成功率 |")
        lines.append(f"|---|---------|---------|------|-------------|--------|")

        for i, cs in enumerate(phase5_stats, 1):
            # 匹配 Phase 6 结果
            p6_total = 0
            p6_success = 0
            p6_fail = 0

            for detail in cs.get('locator_details', []):
                locator = detail.get('locator', '')
                # 在 phase6_results 中查找
                for key, val in phase6_results.items():
                    if locator in key or key in locator:
                        p6_total += 1
                        if val['status'] in ('success', 'verified', 'pass'):
                            p6_success += 1
                        else:
                            p6_fail += 1
                        break

            rate = f"{p6_success/p6_total*100:.0f}%" if p6_total > 0 else "N/A"
            lines.append(
                f"| {i} | {cs['case_name']} | {p6_total} | {p6_success} | {p6_fail} | {rate} |"
            )

        lines.append(f"")

    # ── Section 4: Phase 5 vs 6 详细对比表格 ──
    lines.append(f"## 4. Phase 5 vs Phase 6 详细对比（按用例）")
    lines.append(f"")

    for i, cs in enumerate(phase5_stats, 1):
        lines.append(f"### 4.{i} {cs['case_name']}")
        lines.append(f"")
        lines.append(f"- **Sheet**: {cs['sheet']}")
        lines.append(f"- **模块**: {cs['module']}")
        lines.append(f"")

        if not cs.get('case_file_found'):
            lines.append(f"  ⚠️ Case YAML 文件未找到")
            lines.append(f"")
            continue

        details = cs.get('locator_details', [])
        if not details:
            lines.append(f"  无需要 locator 的步骤")
            lines.append(f"")
            continue

        lines.append(f"| 步骤描述 | Phase5 locator | Phase5 状态 | Phase6 locator | Phase6 状态 |")
        lines.append(f"|---------|---------------|-------------|---------------|-------------|")

        for d in details:
            desc = d['desc'][:40] + ('...' if len(d['desc']) > 40 else '')
            p5_loc = d['locator'][:50] + ('...' if len(d['locator']) > 50 else '')
            p5_status = d['status']

            # Phase 6 状态查找
            p6_loc = "—"
            p6_status = "—"
            for key, val in phase6_results.items():
                if d['locator'] in key or key in d['locator']:
                    p6_loc = val.get('resolved_locator', '')[:50]
                    p6_status = val.get('status', 'unknown')
                    if p6_status in ('success', 'verified', 'pass'):
                        p6_status = '探测成功'
                    else:
                        p6_status = 'fallback'
                    break

            lines.append(f"| {desc} | `{p5_loc}` | {p5_status} | `{p6_loc}` | {p6_status} |")

        lines.append(f"")

    return '\n'.join(lines)


def main():
    project_dir = sys.argv[1] if len(sys.argv) > 1 else "D:/PyProject/TestUiEngineXin/examples/TSManager2"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "D:/PyProject/TestUiEngineXin/.claude/skills/generate-ui-test/docs/debug"

    # 加载 Excel 解析数据
    excel_path = Path(project_dir) / "_probe" / "excel_parsed.json"
    if not excel_path.exists():
        print(f"[FATAL] excel_parsed.json 不存在: {excel_path}")
        sys.exit(1)
    excel_data = load_json(excel_path)

    # 生成报告
    report = generate_report(project_dir, excel_data, output_dir)

    # 写入文件
    os.makedirs(output_dir, exist_ok=True)
    output_file = Path(output_dir) / "tsmanager2_phase_report.md"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n报告已生成: {output_file}")
    print(f"  Phase 4: 探测统计 ✓")
    print(f"  Phase 5: 写入成功率 ✓")
    print(f"  Phase 6: 探测成功率 ✓")
    print(f"  对比表格: ✓")


if __name__ == '__main__':
    main()
