"""自动学习模块 — 测试运行后自动记录成功/失败模式

由 run.py 在每次测试执行完毕后自动调用，无需手动运行命令。
学习数据存储在 {project}/_probe/learn_log.json。

功能：
  - 失败模式学习：从日志文件解析错误，记录失败的 locator+keyword 组合
  - 成功模式学习：从运行结果中提取成功的 locator+keyword 组合
  - 累计 3 次相同失败 → 自动标记"需人工确认"
"""
import json
import os
import re
import glob


# ============================================================================
# 失败模式分类
# ============================================================================

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
    'assertion_error': re.compile(
        r'(?:assert.*fail|except.*fail|expect.*fail|断言.*失败)',
        re.IGNORECASE
    ),
    'auth_error': re.compile(
        r'(?:401|403|unauthorized|forbidden|login.*redirect|token.*expired)',
        re.IGNORECASE
    ),
}


def _classify_error(error_text):
    for category, pattern in ERROR_PATTERNS.items():
        if pattern.search(error_text):
            return category
    return 'unknown'


def _extract_locator(line):
    for p in [
        re.compile(r'locator[=:]\s*["\']?([^"\'}\s,]+)'),
        re.compile(r'xpath[=:]\s*["\']?([^"\'}\s,]+)'),
        re.compile(r'\$\{([^}]+)\}'),
    ]:
        m = p.search(line)
        if m:
            return m.group(1)
    return None


def _extract_keyword(line):
    for p in [
        re.compile(r'keyword[=:]\s*["\']?(\w+)'),
        re.compile(r'\[(\w+)\]'),
    ]:
        m = p.search(line)
        if m:
            return m.group(1)
    return None


def _find_screenshot(project_dir, case_id, step_num):
    """查找关联截图文件（如果存在）

    截图路径约定: files/shortcuts/{case_id}_step{N}.png
    """
    if not case_id:
        return None
    shortcuts_dir = os.path.join(project_dir, 'files', 'shortcuts')
    if not os.path.isdir(shortcuts_dir):
        return None
    # 尝试几种常见命名模式
    for pattern in [
        f'{case_id}_step{step_num}.png',
        f'{case_id}_step{step_num}_error.png',
        f'{case_id}_{step_num}.png',
    ]:
        path = os.path.join(shortcuts_dir, pattern)
        if os.path.isfile(path):
            return os.path.relpath(path, project_dir)
    # 通配搜索
    matches = glob.glob(os.path.join(shortcuts_dir, f'{case_id}*step*{step_num}*.png'))
    if matches:
        return os.path.relpath(matches[0], project_dir)
    return None


# ============================================================================
# 学习记录管理
# ============================================================================

def _empty_log():
    return {
        "version": "1.0",
        "failure_patterns": [],
        "success_patterns": [],
        "user_corrections": [],
        "manual_review_needed": [],
    }


def _load(project_dir):
    path = os.path.join(project_dir, '_probe', 'learn_log.json')
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return _empty_log()


def _save(project_dir, log):
    probe_dir = os.path.join(project_dir, '_probe')
    os.makedirs(probe_dir, exist_ok=True)
    path = os.path.join(probe_dir, 'learn_log.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ============================================================================
# 核心学习函数
# ============================================================================

def learn_from_log_file(project_dir, log_file):
    """从日志文件学习失败模式"""
    log = _load(project_dir)

    if not os.path.isfile(log_file):
        return 0

    with open(log_file, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    error_keywords = ['ERROR', 'FAIL', 'error', 'fail', 'Error', 'Exception']
    new_patterns = []
    count = 0

    for i, line in enumerate(lines):
        if not any(kw in line for kw in error_keywords):
            continue

        error_type = _classify_error(line)
        locator = _extract_locator(line)
        keyword = _extract_keyword(line)

        # 提取 case_id 和 step 信息（用于截图关联）
        case_id = ''
        step_num = ''
        m_case = re.search(r'case[=:]\s*(\S+)', line, re.IGNORECASE)
        if m_case:
            case_id = m_case.group(1)
        m_step = re.search(r'step[=:]\s*(\d+)', line, re.IGNORECASE)
        if m_step:
            step_num = m_step.group(1)
        screenshot = _find_screenshot(project_dir, case_id, step_num)

        pattern_key = f"{error_type}|{keyword or '?'}|{locator or '?'}"

        context_start = max(0, i - 3)
        context_end = min(len(lines), i + 4)
        context = ''.join(lines[context_start:context_end]).strip()

        entry = {
            "pattern_key": pattern_key,
            "error_type": error_type,
            "keyword": keyword,
            "locator": locator,
            "case_id": case_id,
            "step": step_num,
            "screenshot": screenshot,
            "error_text": line.strip()[:200],
            "context": context[:500],
            "count": 1,
            "manual_review": False,
        }

        # 去重
        existing = None
        for fp in log['failure_patterns']:
            if fp.get('pattern_key') == pattern_key:
                existing = fp
                break

        if existing:
            existing['count'] = existing.get('count', 0) + 1
            count += 1
            if existing['count'] >= 3 and not existing.get('manual_review'):
                existing['manual_review'] = True
                log['manual_review_needed'].append({
                    'pattern_key': pattern_key,
                    'reason': f"相同失败模式累计 {existing['count']} 次",
                    'locator': locator,
                    'keyword': keyword,
                })
        else:
            new_patterns.append(entry)
            count += 1

    log['failure_patterns'].extend(new_patterns)
    _save(project_dir, log)
    return count


def learn_from_result(project_dir, result):
    """从运行结果学习成功模式"""
    if not result or not isinstance(result, dict):
        return 0

    log = _load(project_dir)
    success_count = 0
    existing_keys = {p['pattern_key'] for p in log['success_patterns']}

    run_cases = result.get('run_cases', [])
    for case in run_cases:
        if not isinstance(case, dict):
            continue
        case_status = case.get('status', '')
        if case_status not in ('pass', 'success', 'PASS'):
            continue

        steps = case.get('steps', [])
        for step in steps:
            if not isinstance(step, dict):
                continue
            locator = step.get('locator', '')
            keyword = step.get('keyword', '')
            if not locator or not keyword:
                continue

            pattern_key = f"{keyword}|{locator}"
            if pattern_key in existing_keys:
                for existing in log['success_patterns']:
                    if existing['pattern_key'] == pattern_key:
                        existing['count'] = existing.get('count', 0) + 1
                        break
            else:
                log['success_patterns'].append({
                    "pattern_key": pattern_key,
                    "keyword": keyword,
                    "locator": locator,
                    "case_id": case.get('id', ''),
                    "count": 1,
                })
                existing_keys.add(pattern_key)
                success_count += 1

    _save(project_dir, log)
    return success_count


# ============================================================================
# 入口函数（供 run.py 调用）
# ============================================================================

def auto_learn(project_dir, result=None):
    """测试运行后自动学习

    :param project_dir: 项目根目录
    :param result: Runner 返回的结果字典（可选）
    """
    project_dir = os.path.abspath(project_dir)

    # 1. 失败模式学习 — 从最新日志文件
    log_dir = os.path.join(project_dir, 'files', 'logs')
    log_files = sorted(glob.glob(os.path.join(log_dir, '*.log')),
                       key=os.path.getmtime, reverse=True)

    fail_count = 0
    if log_files:
        latest_log = log_files[0]
        fail_count = learn_from_log_file(project_dir, latest_log)

    # 2. 成功模式学习 — 从内存结果
    success_count = 0
    if result:
        success_count = learn_from_result(project_dir, result)

    # 3. 输出学习摘要
    if fail_count > 0 or success_count > 0:
        print(f"\n[自动学习] 失败模式: {fail_count} 个 | 成功模式: {success_count} 个")

    # 4. 检查需人工确认的模式
    log = _load(project_dir)
    reviews = log.get('manual_review_needed', [])
    if reviews:
        print(f"[自动学习] [WARN] {len(reviews)} 个失败模式累计 >=3 次，建议人工确认")
        for r in reviews[-3:]:  # 最多显示最近 3 个
            print(f"  - {r.get('pattern_key', '?')}: {r.get('reason', '?')}")

    return {"fail_patterns": fail_count, "success_patterns": success_count}


def register_auto_learn_keywords():
    """占位函数 — 保持与 auth_keywords / module_keywords 相同的注册模式"""
    pass
