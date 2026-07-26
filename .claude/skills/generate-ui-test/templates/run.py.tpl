"""测试工程运行入口

依赖：pip install ui_engine_xin pyyaml openpyxl
用法：
    python run.py --all                           # 运行总套件（所有用例一次执行，一个报告）
    python run.py                                 # 运行所有套件（每个套件一个报告）
    python run.py --module <module>              # 运行指定模块
    python run.py suites/<module>/smoke.yaml    # 运行指定套件
"""
import sys
import os
import yaml
from UIEngine.runner.runner import Runner

# 注册认证关键字（Cookie/Token/localStorage 注入）
# 如果项目中没有 lib/auth_keywords.py 则静默跳过（兼容旧工程）
try:
    from lib.auth_keywords import register_auth_keywords
    register_auth_keywords()
except ImportError:
    pass

# 注册 L3 模块功能关键字（从 _knowledge/ 编译生成，含系统级+项目级跨项目关键字）
try:
    from lib.module_keywords import register_module_keywords
    register_module_keywords()
except ImportError:
    print("[WARN] lib/module_keywords.py 不存在，L3 关键字未注册", file=sys.stderr)
    print("[INFO] 请运行: python .claude/skills/generate-ui-test/tools/compile_module_keywords.py <project_dir>",
          file=sys.stderr)
except Exception as e:
    print(f"[ERROR] L3 module_keywords 加载失败: {e}", file=sys.stderr)

# 注册自动学习模块（测试运行后自动记录成功/失败模式）
try:
    from lib.auto_learn_keywords import auto_learn as _auto_learn
except ImportError:
    _auto_learn = None


def load_yaml(filepath):
    """加载单个 YAML 文件并返回解析后的字典"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def deep_merge(base, override):
    """深度合并两个字典，嵌套字典递归合并而非覆盖

    解决问题：多个 YAML 文件中存在同名顶层 key 时（如两个 pages 文件
    都定义了 login_page），浅合并会导致先加载的被完全覆盖。
    深度合并保留双方的子 key，冲突时后加载的覆盖先加载的同名子 key。

    Args:
        base: 基础字典（累加目标）
        override: 新增字典（要合并进来的数据）
    Returns:
        合并后的字典（即 base 本身，已就地修改）
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            # 双方都是字典 → 递归合并，保留各自的子 key
            deep_merge(base[key], value)
        else:
            # 新 key 或非字典值 → 直接赋值（冲突时后加载的优先）
            base[key] = value
    return base


def flatten_dict(d, parent_key='', sep='.'):
    """将嵌套字典展平为点分键的扁平字典

    UIEngine 的 VariableResolver 使用扁平字典查找，${page_group.element_name}
    会整体作为 key 查找，不支持嵌套字典的层级解析。此函数将嵌套结构转为扁平：
    {"page": {"btn": ".cls"}} → {"page.btn": ".cls"}

    Args:
        d: 要展平的字典
        parent_key: 父级 key 前缀（递归用）
        sep: 分隔符，默认 '.'
    Returns:
        展平后的字典
    """
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items


def load_yaml_recursive(directory):
    """递归加载目录下所有 YAML 文件，深度合并为统一字典

    遍历目录中所有 .yaml 文件，逐个加载后深度合并。
    不同文件中的同名顶层 key 会保留各自的子 key，不会相互覆盖。
    """
    result = {}
    if not os.path.isdir(directory):
        return result
    for root, dirs, files in os.walk(directory):
        for f in files:
            # F9: 跳过 _ 前缀文件（_probe/_knowledge 等内部数据，不参与运行时合并）
            # 注: fallback locator 已合并到 elements.yaml，不再生成 _fallback.yaml
            if f.endswith('.yaml') and not f.startswith('_'):
                data = load_yaml(os.path.join(root, f))
                if data:
                    # 使用深度合并，避免不同文件中同名 key 相互覆盖
                    deep_merge(result, data)
    return result


def load_cases(directory):
    """递归加载所有测试用例，以 case id 为 key 建立索引

    每个用例 YAML 文件必须包含 'id' 字段，加载后以 id 为 key
    存入字典，供后续套件解析时通过 case_id 查找对应用例。
    同时根据文件所在目录自动添加 _module 字段，用于报告按模块分组。
    """
    cases = {}
    if not os.path.isdir(directory):
        return cases
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith('.yaml'):
                data = load_yaml(os.path.join(root, f))
                if data and 'id' in data:
                    # 从目录路径推断模块名称（一级子目录即为模块名）
                    rel = os.path.relpath(root, directory)
                    data['_module'] = rel.split(os.sep)[0] if rel != '.' else 'default'
                    data['_source_file'] = f"cases/{rel}/{f}" if rel != '.' else f"cases/{f}"
                    cases[data['id']] = data
    return cases


def resolve_suite(suite, all_cases):
    """将套件中的 case_ref 引用替换为实际的用例定义

    遍历 suite 的 case_refs 列表，根据 case_id 从 all_cases 中
    查找对应用例，合并套件级别的覆盖配置（如 skip、data_binding）。

    Args:
        suite: 套件字典，包含 case_refs 列表
        all_cases: 所有用例的 id→用例 索引字典
    Returns:
        添加了 cases 字段的套件字典
    """
    resolved = []
    for idx, ref in enumerate(suite.get('case_refs', [])):
        case_id = ref.get('case_id')
        case = all_cases.get(case_id)
        if case:
            # 浅拷贝用例，避免修改原始定义
            merged = {**case}
            # 记录执行序号（对应 case_refs 列表顺序）
            merged['_seq'] = ref.get('seq', idx + 1)
            # 套件级别的 skip 覆盖用例本身的 skip
            if 'skip' in ref:
                merged['skip'] = ref['skip']
            # 数据绑定：套件指定参数化数据集
            if 'data_binding' in ref:
                merged['_data_binding'] = ref['data_binding']
            resolved.append(merged)
        else:
            print(f"  [WARN] 用例 {case_id} 未找到，跳过")
    suite['cases'] = resolved
    return suite


def _scan_unreferenced_subdirs(cases_dir, module, referenced, all_cases=None):
    """扫描 cases/<module>/ 子目录中未被 suite 引用的用例

    Args:
        cases_dir: cases/ 目录的绝对路径
        module: 模块名称
        referenced: 已被 suite case_refs 引用的 case_id 集合（会就地更新）
        all_cases: 传入时仅收集 case_id（供 --all 模式）；
                   不传时加载完整 case 数据并设置 _module（供逐个套件执行模式）
    Returns:
        all_cases 传入时: 子目录中的 case_id 列表
        all_cases 未传入时: 完整的 case 字典列表
    """
    result = []
    module_cases_dir = os.path.join(cases_dir, module)
    if not os.path.isdir(module_cases_dir):
        return result
    for root, dirs, files in os.walk(module_cases_dir):
        rel = os.path.relpath(root, module_cases_dir)
        if rel == '.':
            continue  # 跳过根目录，只扫描子目录
        for f in sorted(files):
            if not f.endswith('.yaml'):
                continue
            if all_cases is not None:
                # --all 模式：只需 case_id（all_cases 中已有完整数据）
                filepath = os.path.join(root, f)
                data = load_yaml(filepath)
                if data and 'id' in data and data['id'] not in referenced:
                    referenced.add(data['id'])
                    result.append(data['id'])
            else:
                # 逐个套件执行模式：加载完整数据，设置 _module 为子目录名
                cd = load_yaml(os.path.join(root, f))
                if cd and 'id' in cd and cd['id'] not in referenced:
                    cd['_module'] = rel
                    cd['_parent_module'] = module
                    result.append(cd)
                    referenced.add(cd['id'])
    return result


def build_master_suite(suites_dir, all_cases, config, cases_dir=None):
    """构建总套件：聚合所有套件的全部用例，一次执行生成一个报告

    按模块目录排序收集所有 case_refs，用最小化 setup_step（仅浏览器+认证）。
    每条用例自身已包含 open_url + refresh + wait 三步环境隔离，无需总套件重复。
    cases_dir: cases/ 目录路径，用于扫描子目录未引用用例

    Returns:
        合成的总套件字典
    """
    # 按模块分组收集所有 case_id，去重
    import re as _re
    module_case_ids = {}  # module -> {case_id: True}
    all_refs = []  # BUG-6 fix: 初始化引用列表
    for root, dirs, files in sorted(os.walk(suites_dir)):
        module = os.path.basename(root)
        if module not in module_case_ids:
            module_case_ids[module] = {}
        for f in sorted(files):
            if not f.endswith('.yaml'):
                continue
            suite = load_yaml(os.path.join(root, f))
            if not suite:
                continue
            for ref in suite.get('case_refs', []):
                case_id = ref.get('case_id')
                if case_id and case_id in all_cases and case_id not in module_case_ids[module]:
                    module_case_ids[module][case_id] = True

    # 按模块排序，模块内按 case 源文件序号排序（01_, 02_, ...）
    def _case_sort_key(case_id):
        src = all_cases[case_id].get('_source_file', '')
        m = _re.search(r'(\d+)_', os.path.basename(src))
        return int(m.group(1)) if m else 999

    for module in sorted(module_case_ids.keys()):
        for case_id in sorted(module_case_ids[module].keys(), key=_case_sort_key):
            all_refs.append({'case_id': case_id})

    target_url = '${common_data.target_url}'

    # 推断认证关键字（与 generate_suites.py _infer_auth_keyword 对齐）
    _has_ls = bool(config.get('local_storage'))
    _has_token = bool(config.get('token'))
    _auth_kw = 'inject_local_storage' if _has_ls else ('inject_token_header' if _has_token else '')

    _setup = [
        {'desc': '打开浏览器', 'keyword': 'open_browser',
         'params': {'browser_type': config.get('browser_type', 'chromium')}},
        {'desc': '导航到目标域', 'keyword': 'open_url',
         'params': {'url': target_url}},
    ]
    if _auth_kw:
        _setup.append({'desc': '注入认证信息', 'keyword': _auth_kw})
    _setup.extend([
        {'desc': '刷新使认证生效', 'keyword': 'refresh'},
        {'desc': '等待页面加载完成', 'keyword': 'wait_for_element_hidden',
         'params': {'locator': "${common_elements.loading_mask}", 'timeout': 15000}},
    ])

    # 补充各模块子目录中未被 suite 引用的用例
    if cases_dir is None:
        cases_dir = os.path.join(os.path.dirname(suites_dir), 'cases')
    _seen_ids = set()
    for _m in module_case_ids:
        _seen_ids.update(module_case_ids[_m].keys())
    for module in module_case_ids:
        sub_ids = _scan_unreferenced_subdirs(cases_dir, module, _seen_ids, all_cases=all_cases)
        for cid in sub_ids:
            all_refs.append({'case_id': cid})

    return {
        'id': 'master-suite',
        'name': '全部用例汇总',
        'setup_step': _setup,
        'case_refs': all_refs,
    }


def run_suite(suite_path, config, all_cases, all_data, extra_cases=None):
    """运行单个测试套件

    加载套件文件 → 解析 case_ref 引用 → 注入全局变量 → 交给 Runner 执行
    extra_cases: 需要合并到套件末尾的额外用例列表（用于 --module 自动补充）
    """
    suite = load_yaml(suite_path)
    suite = resolve_suite(suite, all_cases)
    if extra_cases:
        suite.setdefault('cases', []).extend(extra_cases)
    gv = config.setdefault('global_variable', {})
    gv.update(flatten_dict(all_data))
    return Runner(config).run(suite)


def run_master_suite(suites_dir, config, all_cases, all_data, cases_dir=None):
    """运行总套件：聚合所有用例，一次执行生成一个报告"""
    suite = build_master_suite(suites_dir, all_cases, config, cases_dir=cases_dir)
    suite = resolve_suite(suite, all_cases)
    gv = config.setdefault('global_variable', {})
    gv.update(flatten_dict(all_data))
    return Runner(config).run(suite)


def main():
    """主入口：加载配置和资源 → 确定要运行的套件 → 逐个执行 → 输出汇总"""
    # 定位工程根目录（run.py 所在目录）
    project_dir = os.path.dirname(os.path.abspath(__file__))
    config = load_yaml(os.path.join(project_dir, 'config.yaml'))

    # 各资源目录路径
    pages_dir = os.path.join(project_dir, 'pages')
    data_dir = os.path.join(project_dir, 'data')
    cases_dir = os.path.join(project_dir, 'cases')
    suites_dir = os.path.join(project_dir, 'suites')

    # 加载所有资源：页面定位器、测试数据、测试用例
    all_locators = load_yaml_recursive(pages_dir)
    all_data = load_yaml_recursive(data_dir)
    all_cases = load_cases(cases_dir)

    # 将页面定位器和测试数据展平为点分键后注入全局变量
    # UIEngine VariableResolver 以 ${group.key} 整体作为 key 查找
    gv = config.setdefault('global_variable', {})
    gv.update(flatten_dict(all_locators))
    gv.update(flatten_dict(all_data))

    # 截图和日志输出到工程本地 files/ 目录，避免写入引擎安装目录
    files_dir = os.path.join(project_dir, 'files')
    config['error_pic_path'] = os.path.join(files_dir, 'shortcuts')

    # 解析命令行参数，确定要运行的套件
    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        # --all 模式：构建总套件，聚合所有用例一次执行
        print(f"\n{'='*60}")
        print("执行总套件：全部用例汇总")
        print(f"{'='*60}")
        result = run_master_suite(suites_dir, config, all_cases, all_data, cases_dir=cases_dir)
        if result:
            tp = result.get('success', 0)
            tf = result.get('fail', 0)
            te = result.get('error', 0)
            ts = result.get('skip', 0)
            print(f"\n通过: {tp} | 失败: {tf} | 错误: {te} | 跳过: {ts}")
        # 自动学习：测试运行后记录成功/失败模式
        if _auto_learn:
            try:
                _auto_learn(project_dir, result)
            except Exception as e:
                print(f"[自动学习] 跳过（不影响测试结果）: {e}")
        return

    all_results = []
    _unreferenced = []

    if len(sys.argv) > 1 and sys.argv[1] == '--module':
        # --module 模式：运行指定模块下的所有套件
        module = sys.argv[2] if len(sys.argv) > 2 else 'common'
        module_dir = os.path.join(suites_dir, module)
        suite_files = []
        if os.path.isdir(module_dir):
            for root, dirs, files in os.walk(module_dir):
                for f in sorted(files):
                    if f.endswith('.yaml'):
                        suite_files.append(os.path.join(root, f))

        # 自动补充：只扫描 cases/<module>/ 的子目录（同级 case 未引用视为有意排除）
        _referenced = set()
        for _sf in suite_files:
            _sd = load_yaml(_sf)
            if _sd:
                for _ref in _sd.get('case_refs', []):
                    _cid = _ref.get('case_id')
                    if _cid:
                        _referenced.add(_cid)
        _module_cases_dir = os.path.join(cases_dir, module)
        if os.path.isdir(_module_cases_dir):
            for _root, _dirs, _files in os.walk(_module_cases_dir):
                _rel = os.path.relpath(_root, _module_cases_dir)
                if _rel == '.':
                    continue  # 跳过根目录，只扫描子目录
                for _f in sorted(_files):
                    if not _f.endswith('.yaml'):
                        continue
                    _cd = load_yaml(os.path.join(_root, _f))
                    if _cd and 'id' in _cd and _cd['id'] not in _referenced:
                        _cd['_module'] = _rel  # 用子目录名作为模块标识
                        _cd['_parent_module'] = module
                        _unreferenced.append(_cd)
                        _referenced.add(_cd['id'])
    elif len(sys.argv) > 1:
        # 直接指定套件文件路径
        suite_files = sys.argv[1:]
    else:
        # 无参数：扫描并运行所有套件
        suite_files = []
        for root, dirs, files in os.walk(suites_dir):
            for f in sorted(files):
                if f.endswith('.yaml'):
                    suite_files.append(os.path.join(root, f))
        # 按模块自动发现子目录用例
        _modules_seen = set()
        for _sf in suite_files:
            _m = os.path.relpath(os.path.dirname(_sf), suites_dir)
            _modules_seen.add(_m)
        for _m in _modules_seen:
            _refs_for_m = set()
            for _sf in suite_files:
                if os.path.relpath(os.path.dirname(_sf), suites_dir) == _m:
                    _sd = load_yaml(_sf)
                    if _sd:
                        for _ref in _sd.get('case_refs', []):
                            _cid = _ref.get('case_id')
                            if _cid:
                                _refs_for_m.add(_cid)
            _unreferenced.extend(
                _scan_unreferenced_subdirs(cases_dir, _m, _refs_for_m)
            )

    # 逐个执行套件并收集结果
    for sp in suite_files:
        print(f"\n{'='*60}")
        print(f"执行套件: {os.path.relpath(sp, project_dir)}")
        print(f"{'='*60}")
        # 将子目录自动发现的用例合并到对应模块的最后一个套件中执行
        _extra = None
        if _unreferenced:
            if len(sys.argv) > 1 and sys.argv[1] == '--module':
                # --module 模式：全部合并到最后一个套件
                if sp == suite_files[-1]:
                    _extra = _unreferenced
            elif len(sys.argv) <= 1:
                # 无参数模式：按模块匹配，合并到该模块的最后一个套件
                _sp_module = os.path.relpath(os.path.dirname(sp), suites_dir)
                _is_last_for_module = not any(
                    os.path.relpath(os.path.dirname(sf), suites_dir) == _sp_module
                    for sf in suite_files[suite_files.index(sp) + 1:]
                )
                if _is_last_for_module:
                    _extra = [c for c in _unreferenced if c.get('_parent_module') == _sp_module]
        if _extra:
            print(f"[auto] 合并 {len(_extra)} 个子目录用例到本套件")
        result = run_suite(sp, config, all_cases, all_data, extra_cases=_extra)
        if result:
            all_results.append(result)

    # 输出执行汇总
    print(f"\n{'='*60}")
    print("执行汇总")
    print(f"{'='*60}")
    tp = sum(r.get('success', 0) for r in all_results)
    tf = sum(r.get('fail', 0) for r in all_results)
    te = sum(r.get('error', 0) for r in all_results)
    ts = sum(r.get('skip', 0) for r in all_results)
    print(f"通过: {tp} | 失败: {tf} | 错误: {te} | 跳过: {ts}")

    # 自动学习：测试运行后记录成功/失败模式
    if _auto_learn:
        for result in all_results:
            try:
                _auto_learn(project_dir, result)
            except Exception as e:
                print(f"[自动学习] 跳过（不影响测试结果）: {e}")


if __name__ == '__main__':
    main()
