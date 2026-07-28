#!/usr/bin/env python3
"""
Phase 7: 自动生成 suite YAML 文件

从 cases/ 目录扫描所有 case ID，按依赖顺序生成 suite YAML。
消除 AI 手写 suite 的不稳定性（P-06/D5 缺口修复）。

用法:
    python generate_suites.py {project_dir} [--module {module} | --all-modules]

输出:
    suites/{module}/smoke.yaml — 包含所有 case 的标准套件文件
"""
import argparse
import glob
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("[FATAL] 需要 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ============================================================================
# 依赖排序规则（新增→编辑→详情→导出→查询→批量→删除）
# ============================================================================

DEPENDENCY_ORDER = [
    ('add', 'create', '新增', '新建', '创建'),       # 1. 新增
    ('edit', 'modify', 'update', '编辑', '修改'),     # 2. 编辑
    ('detail', 'view', '详情', '查看'),               # 3. 详情
    ('export', 'import', '导出', '导入'),             # 4. 导出/导入
    ('query', 'search', 'filter', '查询', '搜索', '筛选'),  # 5. 查询
    ('batch', '批量'),                                 # 6. 批量
    ('delete', 'remove', '删除', '清除', '批量删除'),    # 7. 删除（最后）
]


def _tokenize_case_id(case_id: str) -> list:
    """将 case_id 拆分为词段用于排序匹配

    拆分顺序：先按 _/- 分割（保留原始大小写），再对每段做 camelCase 拆分，最后转小写。

    示例:
      'add_and_delete'     → ['add', 'and', 'delete']
      'question_addIssue'  → ['question', 'add', 'issue']
      '新增问题'           → ['新增问题']
      'mail-case-01'       → ['mail', 'case', '01']
    """
    parts = re.split(r'[-_]', case_id)  # 保留原始大小写
    tokens = []
    for p in parts:
        # camelCase 拆分: addIssue → add, Issue（必须在 lower() 前执行）
        sub = re.sub(r'([a-z])([A-Z])', r'\1 \2', p).split()
        tokens.extend([s.lower() for s in sub] if sub else [p.lower()])
    return tokens


def _get_priority(case_id: str, filename: str = '') -> int:
    """根据 case_id 词段确定执行优先级

    策略：在所有词段和中文子串中，取最高层级（最具破坏性的操作）胜出。
    例: 'add_and_delete' 中 add(0) + delete(6) → 取 6（删除排最后）
    """
    tokens = _tokenize_case_id(case_id)
    max_tier = -1

    # 英文词段精确匹配 — 取最高层级
    for token in tokens:
        if not token or not token[0].isascii():
            continue
        for i, keywords in enumerate(DEPENDENCY_ORDER):
            for kw in keywords:
                if kw.isascii() and kw.lower() == token:
                    max_tier = max(max_tier, i)

    # 中文子串匹配 — 取最高层级（始终执行，中文可能层级更高）
    cid_lower = case_id.lower()
    for i, keywords in enumerate(DEPENDENCY_ORDER):
        for kw in keywords:
            if not kw.isascii() and len(kw) >= 2 and kw in cid_lower:
                max_tier = max(max_tier, i)

    return max_tier if max_tier >= 0 else 50  # 未知类型排中间


def _infer_auth_keyword(config: dict) -> str:
    """从 config.yaml 字段存在性推断认证关键字

    认证模式映射：
      cookie (无论是否有 localStorage)  → 'inject_local_storage'
          inject_local_storage 会自动从 cookie 提取 token 写入 localStorage，
          同时注入 config.local_storage 中的其他字段。
          这是天枢等系统的标准做法：cookie + localStorage 双重认证。
      local_storage (无 cookie)      → 'inject_local_storage'
          SPA 前端需要 localStorage 注入才能认证。
      token                 → 'inject_token_header'
      none                  → ''
    """
    has_cookie = bool(config.get('cookie'))
    has_token = bool(config.get('token'))
    has_local_storage = bool(config.get('local_storage'))

    if has_cookie or has_local_storage:
        return 'inject_local_storage'  # cookie 或 localStorage 模式
    if has_token:
        return 'inject_token_header'   # header token 模式
    return ''


def scan_cases(cases_dir: str, module: str) -> list:
    """扫描 cases/{module}/ 下所有 case YAML，返回 [(case_id, filename), ...]"""
    module_dir = os.path.join(cases_dir, module)
    if not os.path.isdir(module_dir):
        return []

    results = []
    for f in sorted(glob.glob(os.path.join(module_dir, '*.yaml'))):
        if f.endswith('_fallback.yaml'):
            continue  # 跳过回退定位器文件
        try:
            with open(f, encoding='utf-8') as fh:
                data = yaml.safe_load(fh)
            if data and isinstance(data, dict) and data.get('id'):
                results.append((data['id'], os.path.basename(f)))
        except Exception:
            continue

    return results


def generate_suite(cases: list, config: dict, module: str,
                   sort_by: str = 'filename') -> dict:
    """生成 suite YAML 字典

    Args:
        sort_by: 'filename' (M18 默认, 按文件编号) 或 'dependency' (按操作类型)
    """
    browser_type = config.get('browser_type', 'chromium')
    auth_keyword = _infer_auth_keyword(config)

    # M18: 按文件编号排序（默认）或按依赖顺序排序
    if sort_by == 'dependency':
        sorted_cases = sorted(cases, key=lambda c: _get_priority(c[0], c[1]))
    else:
        # 按文件名数字前缀排序（01_add → 02_edit → ...）
        def _filename_sort_key(c):
            fn = c[1] if len(c) > 1 else ''
            m = re.match(r'^(\d+)', fn)
            return int(m.group(1)) if m else 999
        sorted_cases = sorted(cases, key=_filename_sort_key)

    # 构建 setup_step
    setup_step = [
        {'desc': '打开浏览器', 'keyword': 'open_browser',
         'params': {'browser_type': browser_type}},
        {'desc': '导航到目标域', 'keyword': 'open_url',
         'params': {'url': '${common_data.target_url}'}},
    ]
    if auth_keyword:
        setup_step.append({
            'desc': '注入认证信息', 'keyword': auth_keyword,
        })
    setup_step.extend([
        {'desc': '刷新使认证生效', 'keyword': 'refresh'},
        {'desc': '等待页面加载完成', 'keyword': 'wait_for_loading_complete'},
    ])

    # 构建 case_refs
    case_refs = []
    for seq, (case_id, _) in enumerate(sorted_cases, 1):
        case_refs.append({'case_id': case_id, 'seq': seq})

    return {
        'id': f'{module}-smoke',
        'name': f'{module} 模块冒烟测试',
        'setup_step': setup_step,
        'case_refs': case_refs,
    }


def _write_suite(project_dir: str, config: dict, cases_dir: str, module: str,
                 sort_by: str = 'filename') -> bool:
    """为单个模块生成 suite，返回 True 表示成功生成"""
    cases = scan_cases(cases_dir, module)
    if not cases:
        print(f"  [SKIP] cases/{module}/ 中未找到任何 case 文件")
        return False

    print(f"  [{module}] 找到 {len(cases)} 个 case")

    suite = generate_suite(cases, config, module, sort_by=sort_by)

    suites_dir = os.path.join(project_dir, 'suites', module)
    os.makedirs(suites_dir, exist_ok=True)
    output_file = os.path.join(suites_dir, 'smoke.yaml')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# {module} 模块冒烟测试套件（自动生成）\n")
        f.write(f"# 由 generate_suites.py 生成，请勿手动编辑\n\n")
        yaml.dump(suite, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"  [{module}] 输出: {output_file} ({len(suite['case_refs'])} 条 case_refs)")
    for ref in suite['case_refs']:
        print(f"    [{ref['seq']:02d}] {ref['case_id']}")

    return True


def _discover_modules(cases_dir: str) -> list:
    """自动扫描 cases/ 下所有模块目录（排除 _ 和 . 前缀）"""
    if not os.path.isdir(cases_dir):
        return []
    return sorted([
        d for d in os.listdir(cases_dir)
        if os.path.isdir(os.path.join(cases_dir, d))
        and not d.startswith('_') and not d.startswith('.')
    ])


def _ensure_common_data(project_dir: str, config: dict):
    """确保 data/common/common_data.yaml 存在（供 suite ${common_data.target_url} 引用）

    如果文件不存在，从 config.yaml 的 target_url 自动创建。
    已存在则跳过（不覆盖手动修改）。
    """
    common_data_dir = os.path.join(project_dir, 'data', 'common')
    common_data_file = os.path.join(common_data_dir, 'common_data.yaml')

    if os.path.isfile(common_data_file):
        return  # 已存在，不覆盖

    target_url = config.get('target_url', '')
    if not target_url:
        return  # config 中无 target_url，无法生成

    os.makedirs(common_data_dir, exist_ok=True)
    with open(common_data_file, 'w', encoding='utf-8') as f:
        f.write(f"# 通用数据（由 generate_suites.py 自动生成）\n")
        f.write(f"# 修改 target_url 时请同步更新 config.yaml 和此文件\n")
        yaml.dump({'common_data': {'target_url': target_url}}, f, allow_unicode=True, default_flow_style=False)

    print(f"[INFO] 已自动创建 {os.path.relpath(common_data_file, project_dir)}")


def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='自动生成 suite YAML')
    parser.add_argument('project_dir', help='项目根目录')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--module', default='common', help='目标模块名')
    group.add_argument('--all-modules', action='store_true',
                       help='自动扫描 cases/ 下所有模块目录')
    parser.add_argument('--sort-by', default='filename',
                        choices=['filename', 'dependency'],
                        help='排序方式: filename(默认,按文件编号) 或 dependency(按操作类型)')
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    # 加载 config.yaml
    config_file = os.path.join(project_dir, 'config.yaml')
    if not os.path.exists(config_file):
        print(f"[FATAL] config.yaml 不存在: {config_file}", file=sys.stderr)
        sys.exit(2)
    with open(config_file, encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    # 确保 common_data.yaml 存在（供 suite 的 ${common_data.target_url} 引用）
    _ensure_common_data(project_dir, config)

    cases_dir = os.path.join(project_dir, 'cases')

    # 确定要处理的模块列表
    if args.all_modules:
        modules = _discover_modules(cases_dir)
        if not modules:
            print("[WARN] cases/ 下未找到任何模块目录")
            sys.exit(0)
        print(f"[INFO] --all-modules: 发现 {len(modules)} 个模块: {', '.join(modules)}")
    else:
        modules = [args.module]

    generated = 0
    for module in modules:
        if _write_suite(project_dir, config, cases_dir, module,
                        sort_by=args.sort_by):
            generated += 1

    if args.all_modules:
        print(f"\n[DONE] 共生成 {generated}/{len(modules)} 个 suite 文件")

    if generated == 0:
        sys.exit(0)


if __name__ == '__main__':
    main()
