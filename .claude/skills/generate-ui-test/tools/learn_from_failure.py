#!/usr/bin/env python3
"""
自学习脚本 (learn_from_failure.py)

从测试运行结果中学习失败/成功模式，维护 learn_log.json：
  - 失败模式学习：记录失败的定位器、关键字、错误信息
  - 成功模式学习：记录成功的定位器和操作序列
  - 用户纠正学习：委托给 learn_probe.py 更新知识库
  - 累计 3 次相同失败 → 自动标记"需人工确认"

数据存储：{project}/_probe/learn_log.json

用法:
    # 从运行日志中学习失败模式
    python learn_from_failure.py learn-failure <project_dir> <log_file>

    # 从运行结果中学习成功模式
    python learn_from_failure.py learn-success <project_dir> <result_file>

    # 记录用户纠正（委托给 learn_probe.py）
    python learn_from_failure.py user-correct <project_dir> <category_type> <category_name> <label> <xpath> <source_case>

    # 查看学习统计
    python learn_from_failure.py stats <project_dir>

    # 导出需人工确认的失败模式
    python learn_from_failure.py review <project_dir>
"""

import argparse
import glob
import json
import os
import re
import sys
from typing import Dict, List, Optional


# ============================================================================
# 数据结构
# ============================================================================

def empty_learn_log():
    """创建空的学习记录"""
    return {
        "version": "1.0",
        "failure_patterns": [],
        "success_patterns": [],
        "user_corrections": [],
        "manual_review_needed": [],
    }


def load_learn_log(project_dir: str) -> dict:
    """加载学习记录"""
    log_path = os.path.join(project_dir, '_probe', 'learn_log.json')
    if os.path.isfile(log_path):
        try:
            with open(log_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return empty_learn_log()


def save_learn_log(project_dir: str, log: dict):
    """保存学习记录"""
    probe_dir = os.path.join(project_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)
    log_path = os.path.join(probe_dir, 'learn_log.json')
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"学习记录已保存: {log_path}")


# ============================================================================
# 失败模式学习
# ============================================================================

# 错误分类正则
ERROR_PATTERNS = {
    'timeout': re.compile(r'timeout.*?(?:exceeded|waiting)', re.IGNORECASE),
    'element_not_found': re.compile(
        r'(?:element|locator|selector).*?not\s*(?:found|visible|attached)',
        re.IGNORECASE
    ),
    'locator_error': re.compile(
        r'(?:strict mode violation|locator.*?resolved to \d+)',
        re.IGNORECASE
    ),
    'navigation_error': re.compile(
        r'(?:net::|page.*?closed|target closed|navigation failed)',
        re.IGNORECASE
    ),
    'fill_error': re.compile(
        r'(?:element is not an.*?input|cannot type into|fill.*?failed)',
        re.IGNORECASE
    ),
}


def classify_error(error_text: str) -> str:
    """将错误文本分类为已知模式"""
    for category, pattern in ERROR_PATTERNS.items():
        if pattern.search(error_text):
            return category
    return 'unknown'


def extract_locator_from_log(line: str) -> Optional[str]:
    """从日志行中提取定位器"""
    # 匹配 locator=... 或 xpath=... 格式
    patterns = [
        re.compile(r'locator[=:]\s*["\']?([^"\'}\s,]+)'),
        re.compile(r'xpath[=:]\s*["\']?([^"\'}\s,]+)'),
        re.compile(r'\$\{([^}]+)\}'),
    ]
    for p in patterns:
        m = p.search(line)
        if m:
            return m.group(1)
    return None


def extract_keyword_from_log(line: str) -> Optional[str]:
    """从日志行中提取关键字名"""
    patterns = [
        re.compile(r'keyword[=:]\s*["\']?(\w+)'),
        re.compile(r'\[(\w+)\]'),
    ]
    for p in patterns:
        m = p.search(line)
        if m:
            return m.group(1)
    return None


def learn_from_failure_log(project_dir: str, log_file: str):
    """从运行日志中学习失败模式"""
    log = load_learn_log(project_dir)

    if not os.path.isfile(log_file):
        print(f"[ERR] 日志文件不存在: {log_file}")
        sys.exit(1)

    # 解析日志
    failure_count = 0
    new_patterns = []

    with open(log_file, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # 扫描错误行
    error_keywords = ['ERROR', 'FAIL', 'error', 'fail', 'Error', 'Exception']
    for i, line in enumerate(lines):
        if not any(kw in line for kw in error_keywords):
            continue

        error_type = classify_error(line)
        locator = extract_locator_from_log(line)
        keyword = extract_keyword_from_log(line)

        # 构建失败模式签名
        pattern_key = f"{error_type}|{keyword or '?'}|{locator or '?'}"

        # 检查上下文（前后 3 行）获取更多细节
        context_start = max(0, i - 3)
        context_end = min(len(lines), i + 4)
        context = ''.join(lines[context_start:context_end]).strip()

        pattern_entry = {
            "pattern_key": pattern_key,
            "error_type": error_type,
            "keyword": keyword,
            "locator": locator,
            "error_text": line.strip()[:200],
            "context": context[:500],
            "count": 1,
            "manual_review": False,
            "source_log": os.path.basename(log_file),
        }

        # 去重：相同 pattern_key 累加计数
        existing = None
        for fp in log['failure_patterns']:
            if fp.get('pattern_key') == pattern_key:
                existing = fp
                break

        if existing:
            existing['count'] = existing.get('count', 0) + 1
            existing['last_seen'] = os.path.basename(log_file)
            failure_count += 1

            # 累计 3 次 → 标记需人工确认
            if existing['count'] >= 3 and not existing.get('manual_review'):
                existing['manual_review'] = True
                log['manual_review_needed'].append({
                    'pattern_key': pattern_key,
                    'reason': f"相同失败模式累计 {existing['count']} 次",
                    'locator': locator,
                    'keyword': keyword,
                })
                print(f"  [!] 失败模式累计 {existing['count']} 次，已标记为'需人工确认': {pattern_key}")
            else:
                print(f"  [+] 已有失败模式计数 +1 (count={existing['count']}): {pattern_key}")
        else:
            new_patterns.append(pattern_entry)
            failure_count += 1
            print(f"  [NEW] 新失败模式: {pattern_key}")

    # 添加新模式
    log['failure_patterns'].extend(new_patterns)

    save_learn_log(project_dir, log)
    print(f"\n失败学习完成: 处理了 {failure_count} 个失败, "
          f"新增 {len(new_patterns)} 个模式")


# ============================================================================
# 成功模式学习
# ============================================================================

def learn_from_success_result(project_dir: str, result_file: str):
    """从运行结果中学习成功模式"""
    log = load_learn_log(project_dir)

    if not os.path.isfile(result_file):
        print(f"[ERR] 结果文件不存在: {result_file}")
        sys.exit(1)

    # 尝试解析 JSON 格式的运行结果
    results = None
    try:
        with open(result_file, encoding='utf-8') as f:
            results = json.load(f)
    except Exception:
        # 尝试逐行解析
        pass

    success_count = 0
    new_patterns = []

    if isinstance(results, dict):
        # 结构化运行结果
        for case_id, case_result in results.items():
            if not isinstance(case_result, dict):
                continue
            if case_result.get('status') != 'pass':
                continue

            steps = case_result.get('steps', [])
            for step in steps:
                if not isinstance(step, dict):
                    continue
                locator = step.get('locator', '')
                keyword = step.get('keyword', '')
                if locator and keyword:
                    pattern_key = f"{keyword}|{locator}"
                    new_patterns.append({
                        "pattern_key": pattern_key,
                        "keyword": keyword,
                        "locator": locator,
                        "case_id": case_id,
                        "count": 1,
                    })
                    success_count += 1
    elif isinstance(results, list):
        # 列表格式
        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get('status') in ('pass', 'PASS', 'success'):
                locator = item.get('locator', '')
                keyword = item.get('keyword', '')
                if locator and keyword:
                    pattern_key = f"{keyword}|{locator}"
                    new_patterns.append({
                        "pattern_key": pattern_key,
                        "keyword": keyword,
                        "locator": locator,
                        "count": 1,
                    })
                    success_count += 1

    if not new_patterns:
        print("未从结果文件中提取到成功模式（可能格式不匹配或无成功用例）")
        return

    # 去重合并
    existing_keys = {p['pattern_key'] for p in log['success_patterns']}
    added = 0
    for pattern in new_patterns:
        if pattern['pattern_key'] in existing_keys:
            # 计数+1
            for existing in log['success_patterns']:
                if existing['pattern_key'] == pattern['pattern_key']:
                    existing['count'] = existing.get('count', 0) + 1
                    break
        else:
            log['success_patterns'].append(pattern)
            existing_keys.add(pattern['pattern_key'])
            added += 1

    save_learn_log(project_dir, log)
    print(f"\n成功学习完成: 处理了 {success_count} 个成功步骤, "
          f"新增 {added} 个模式, 更新 {success_count - added} 个已有模式")


# ============================================================================
# 用户纠正学习
# ============================================================================

def learn_user_correction(project_dir: str, category_type: str,
                          category_name: str, label: str,
                          corrected_xpath: str, source_case: str,
                          option_text: str = None):
    """用户纠正直接更新知识库（委托给 learn_probe.py）"""
    # 记录到 learn_log
    log = load_learn_log(project_dir)
    log['user_corrections'].append({
        'category_type': category_type,
        'category_name': category_name,
        'label': label,
        'xpath': corrected_xpath[:200],
        'source_case': source_case,
    })
    save_learn_log(project_dir, log)

    # 委托给 learn_probe.py 更新知识库
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    learn_probe_path = os.path.join(skill_dir, 'tools', 'learn_probe.py')

    # 确定知识库路径（优先项目级，否则全局）
    project_kb = os.path.join(project_dir, '_probe', 'knowledge.json')
    global_kb = os.path.join(skill_dir, 'tools', 'probe_knowledge.json')
    kb_path = project_kb if os.path.isfile(project_kb) else global_kb

    args = [sys.executable, learn_probe_path, kb_path,
            category_type, category_name, label, corrected_xpath, source_case]
    if option_text:
        args.append(option_text)

    print(f"调用 learn_probe.py 更新知识库: {kb_path}")
    import subprocess
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8')
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode == 0:
        print(f"用户纠正已学习: [{category_type}/{category_name}] from {source_case}")
    else:
        print(f"[WARN] learn_probe.py 返回非零: {result.returncode}")


# ============================================================================
# 统计和审查
# ============================================================================

def show_stats(project_dir: str):
    """显示学习统计"""
    log = load_learn_log(project_dir)

    print("=" * 60)
    print(f"UIEngine 自学习统计 - {os.path.basename(project_dir)}")
    print("=" * 60)

    # 失败模式统计
    failures = log.get('failure_patterns', [])
    print(f"\n失败模式: {len(failures)} 个")
    if failures:
        # 按类型分组
        by_type = {}
        for fp in failures:
            t = fp.get('error_type', 'unknown')
            by_type.setdefault(t, []).append(fp)
        for t, items in sorted(by_type.items()):
            total_count = sum(p.get('count', 0) for p in items)
            review_count = sum(1 for p in items if p.get('manual_review'))
            print(f"  {t}: {len(items)} 个模式, 累计 {total_count} 次, "
                  f"{review_count} 个需人工确认")

    # 成功模式统计
    successes = log.get('success_patterns', [])
    print(f"\n成功模式: {len(successes)} 个")
    if successes:
        total_count = sum(p.get('count', 0) for p in successes)
        print(f"  累计成功: {total_count} 次")

    # 用户纠正统计
    corrections = log.get('user_corrections', [])
    print(f"\n用户纠正: {len(corrections)} 次")
    if corrections:
        for c in corrections[-5:]:
            print(f"  [{c.get('category_type')}/{c.get('category_name')}] "
                  f"{c.get('label', '?')} from {c.get('source_case', '?')}")

    # 需人工确认
    reviews = log.get('manual_review_needed', [])
    print(f"\n需人工确认: {len(reviews)} 个")
    if reviews:
        for r in reviews:
            print(f"  [!] {r.get('pattern_key', '?')}")
            print(f"      原因: {r.get('reason', '?')}")

    print("=" * 60)


def export_review(project_dir: str):
    """导出需人工确认的失败模式"""
    log = load_learn_log(project_dir)
    reviews = log.get('manual_review_needed', [])

    if not reviews:
        print("当前无需人工确认的失败模式 ✓")
        return

    print("=" * 60)
    print(f"需人工确认的失败模式 ({len(reviews)} 个)")
    print("=" * 60)

    for i, r in enumerate(reviews, 1):
        print(f"\n{i}. {r.get('pattern_key', '?')}")
        print(f"   原因: {r.get('reason', '?')}")
        if r.get('locator'):
            print(f"   定位器: {r['locator']}")
        if r.get('keyword'):
            print(f"   关键字: {r['keyword']}")
        print(f"   建议: 检查对应 pages YAML 中的定位器是否正确")

    print("\n" + "=" * 60)
    print("处理方式:")
    print("  1. 修正定位器后重新运行测试")
    print("  2. 使用 user-correct 命令记录纠正")
    print("  3. 确认为系统问题后标记为已知")
    print("=" * 60)


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description="UIEngine 自学习工具 — 从运行结果中学习失败/成功模式"
    )
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # learn-failure
    p_fail = subparsers.add_parser('learn-failure', help='从运行日志学习失败模式')
    p_fail.add_argument('project_dir', help='项目根目录')
    p_fail.add_argument('log_file', help='运行日志文件路径')

    # learn-success
    p_success = subparsers.add_parser('learn-success', help='从运行结果学习成功模式')
    p_success.add_argument('project_dir', help='项目根目录')
    p_success.add_argument('result_file', help='运行结果文件路径 (JSON)')

    # user-correct
    p_correct = subparsers.add_parser('user-correct', help='记录用户纠正')
    p_correct.add_argument('project_dir', help='项目根目录')
    p_correct.add_argument('category_type', choices=['single_step', 'multi_step', 'composite'])
    p_correct.add_argument('category_name', help='分类名称')
    p_correct.add_argument('label', help='元素标签')
    p_correct.add_argument('xpath', help='纠正后的 XPath')
    p_correct.add_argument('source_case', help='来源用例')
    p_correct.add_argument('--option-text', help='选项文本（多步模板用）')

    # stats
    p_stats = subparsers.add_parser('stats', help='查看学习统计')
    p_stats.add_argument('project_dir', help='项目根目录')

    # review
    p_review = subparsers.add_parser('review', help='导出需人工确认的失败模式')
    p_review.add_argument('project_dir', help='项目根目录')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'learn-failure':
        project_dir = os.path.abspath(args.project_dir)
        learn_from_failure_log(project_dir, args.log_file)

    elif args.command == 'learn-success':
        project_dir = os.path.abspath(args.project_dir)
        learn_from_success_result(project_dir, args.result_file)

    elif args.command == 'user-correct':
        project_dir = os.path.abspath(args.project_dir)
        learn_user_correction(
            project_dir, args.category_type, args.category_name,
            args.label, args.xpath, args.source_case,
            option_text=args.option_text
        )

    elif args.command == 'stats':
        project_dir = os.path.abspath(args.project_dir)
        show_stats(project_dir)

    elif args.command == 'review':
        project_dir = os.path.abspath(args.project_dir)
        export_review(project_dir)


if __name__ == '__main__':
    main()
