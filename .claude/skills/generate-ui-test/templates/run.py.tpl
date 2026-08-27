"""测试工程运行入口

依赖：pip install ui_engine_xin pyyaml openpyxl
用法：
    python run.py                                 # 运行总套件（优先 suites/master.yaml）
    python run.py --all                           # 运行总套件（内存聚合，含未引用用例）
    python run.py --module <module>              # 运行指定模块
    python run.py suites/<module>/smoke.yaml    # 运行指定套件

调试模式（用例失败后暂停交互，支持手工操作/重试/跳过）：
    python run.py --debug                        # 总套件 + 调试模式
    python run.py --all --debug                  # 内存聚合 + 调试模式
    python run.py --module <module> --debug      # 指定模块 + 调试模式
    python run.py --debug --max-retries 5        # 自定义最大重试次数（默认3）
"""
import sys
import os
import time
import yaml
from UIEngine.runner.runner import Runner
from UIEngine.utils.path_helper import get_project_dir


class DebugRunner(Runner):
    """调试模式执行器：用例失败后暂停交互，支持手工操作/重试/跳过/终止

    增强功能（仅 debug 模式）：
    - 用例失败时立即生成 HTML 报告到 report/run_report/debug_report/
    - 自动在浏览器中打开报告，方便用户实时分析
    - 每次失败覆盖同一份报告（文件名含固定时间戳）

    仅覆写 run_suite_case()，其余逻辑（run/setup/report）完全继承 Runner。
    """

    def __init__(self, config, max_retries=3):
        """
        :param config: 执行的环境配置
        :param max_retries: 每个用例的最大重试次数（默认3）
        """
        super().__init__(config)
        self.max_retries = max_retries
        # ── Debug 即时报告 ──
        self._debug_timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self._executed_cases = []  # 已执行用例快照（含成功/失败/跳过）
        self._debug_report_dir = None  # 延迟初始化
        self._debug_report_path = None  # 延迟初始化
        self._start_timestamp = None  # run() 调用时记录

    def run(self, suite):
        """覆写 run()：初始化 debug 报告路径，记录开始时间"""
        project_dir = get_project_dir(self.config)
        self._debug_report_dir = os.path.join(
            project_dir, 'report', 'run_report', 'debug_report'
        )
        suite_id = suite.get('id', 'suite')
        self._debug_report_path = os.path.join(
            self._debug_report_dir,
            f"{suite_id}_debug_{self._debug_timestamp}.html"
        )
        self._start_timestamp = time.time()
        self._executed_cases = []
        return super().run(suite)

    def run_suite_case(self, suite_name, cases):
        """覆写：失败时暂停交互 + 即时报告生成。

        关键保证：
        - TestResult 计数：每个 case 只调用一次 add_fail/add_success
        - 执行树：tree_builder.reset() 在每次尝试前调用
        - 浏览器会话：case 间不关闭，用户手工操作保持生效
        - 即时报告：失败时在 _debug_prompt 前生成报告并打开浏览器
        """
        self.log.info_log(f"测试套件名称 【{suite_name}】： 执行测试用例 [DEBUG 模式]")
        pic_path = self.screenshot_mgr.create_suite_dir(suite_name)
        project_dir = get_project_dir(self.config)

        for idx, case in enumerate(cases):
            case_name = case.get('name') or case.get('id') or f"case_{idx + 1}"

            if case.get("skip"):
                self.log.info_log(f"==============第{idx + 1}个测试用例 -【{case_name}】跳过执行==============")
                self.result.add_skip(case)
                continue

            # 重置执行树，为当前用例构建独立的执行记录
            case_start_time = time.time()

            # ── 重试循环 ──
            attempt = 0
            final_recorded = False  # 确保 result 只记录一次

            while attempt <= self.max_retries:
                self.tree_builder.reset()

                try:
                    if attempt == 0:
                        self.log.info_log(f"==============第{idx + 1}个测试用例 - 【{case_name}】开始执行==============")
                    else:
                        self.log.info_log(f"==============第{idx + 1}个测试用例 - 【{case_name}】第{attempt}次重试==============")
                    self.run_case(case)

                except AssertionError as e:
                    self.log.error_log(f"第{idx + 1}个测试用例 - 【{case_name}】断言失败,错误信息为：", e)
                    img = self.base_case.save_page_img(f"{case_name}_fail", pic_path)
                    img_rel = self._relative_screenshot_path(img, project_dir)
                    self.tree_builder.attach_screenshot_to_failed(img_rel)

                    # ── 记录执行树 + 生成即时报告（在交互暂停前） ──
                    case['_case_duration'] = time.time() - case_start_time
                    case['_case_start_time'] = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(case_start_time)
                    )
                    case['_execution_tree'] = self.tree_builder.get_tree()
                    case['state'] = 'fail'
                    self._record_debug_case(case, idx)
                    self._flush_debug_report(suite_name)
                    self._open_debug_report()

                    # ── 交互式暂停 ──
                    action = self._debug_prompt(case_name, e, idx + 1, attempt)

                    if action == 'retry':
                        attempt += 1
                        if attempt > self.max_retries:
                            # 重试耗尽，记录失败
                            print(f"  已达最大重试次数 ({self.max_retries})，记录失败")
                            self.result.add_fail(case, list(self.log.log_data), img)
                            final_recorded = True
                            break
                        # 重试前清除即时报告中的记录（会被新尝试覆盖）
                        self._remove_last_debug_case()
                        continue  # 重试

                    elif action == 'skip':
                        self.result.add_fail(case, list(self.log.log_data), img)
                        final_recorded = True
                        break  # 跳到下一个 case

                    elif action == 'quit':
                        self.result.add_fail(case, list(self.log.log_data), img)
                        final_recorded = True
                        return  # 终止全部执行

                except Exception as e:
                    self.log.error_log(f"第{idx + 1}个测试用例 - 【{case_name}】执行失败,错误信息为：", e)
                    img = self.base_case.save_page_img(f"{case_name}_error", pic_path)
                    img_rel = self._relative_screenshot_path(img, project_dir)
                    self.tree_builder.attach_screenshot_to_failed(img_rel)

                    # ── 记录执行树 + 生成即时报告（在交互暂停前） ──
                    case['_case_duration'] = time.time() - case_start_time
                    case['_case_start_time'] = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(case_start_time)
                    )
                    case['_execution_tree'] = self.tree_builder.get_tree()
                    case['state'] = 'error'
                    self._record_debug_case(case, idx)
                    self._flush_debug_report(suite_name)
                    self._open_debug_report()

                    # ── 交互式暂停 ──
                    action = self._debug_prompt(case_name, e, idx + 1, attempt)

                    if action == 'retry':
                        attempt += 1
                        if attempt > self.max_retries:
                            print(f"  已达最大重试次数 ({self.max_retries})，记录错误")
                            self.result.add_error(case, list(self.log.log_data), img)
                            final_recorded = True
                            break
                        self._remove_last_debug_case()
                        continue

                    elif action == 'skip':
                        self.result.add_error(case, list(self.log.log_data), img)
                        final_recorded = True
                        break

                    elif action == 'quit':
                        self.result.add_error(case, list(self.log.log_data), img)
                        final_recorded = True
                        return

                else:
                    # 执行成功（首次或重试后成功）
                    self.log.info_log(f"==============第{idx + 1}个测试用例 - 【{case_name}】执行成功==============")
                    img = self.base_case.save_page_img(f"{case_name}_success", pic_path)
                    self.result.add_success(case, list(self.log.log_data), img)
                    final_recorded = True
                    break  # 成功，下一个 case

            # 记录用例耗时和执行树（正常运行模式的记录，与即时报告互不冲突）
            case['_case_duration'] = time.time() - case_start_time
            case['_case_start_time'] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(case_start_time)
            )
            case['_execution_tree'] = self.tree_builder.get_tree()

    # ── Debug 即时报告辅助方法 ──

    def _record_debug_case(self, case, idx):
        """记录失败/错误用例快照到 _executed_cases（浅拷贝避免污染原字典）"""
        snapshot = {k: v for k, v in case.items() if k != 'steps'}
        snapshot['_seq'] = idx + 1
        snapshot['steps'] = case.get('steps', [])  # steps 单独保留引用（只读）
        self._executed_cases.append(snapshot)

    def _remove_last_debug_case(self):
        """重试时移除上次失败记录（将被新尝试覆盖）"""
        if self._executed_cases:
            self._executed_cases.pop()

    def _flush_debug_report(self, suite_name):
        """生成/覆盖 debug 即时报告"""
        if not self._debug_report_path:
            return
        try:
            os.makedirs(self._debug_report_dir, exist_ok=True)

            # 构造临时 suite（包含已执行用例）
            temp_suite = {
                'id': f'{self._debug_timestamp}_debug',
                'name': f'[DEBUG] {suite_name}',
                'cases': list(self._executed_cases),
            }

            # 构造临时 result
            executed = self._executed_cases
            success = sum(1 for c in executed if c.get('state') == 'success')
            fail = sum(1 for c in executed if c.get('state') == 'fail')
            error = sum(1 for c in executed if c.get('state') == 'error')
            skip = sum(1 for c in executed if c.get('state') == 'skip')
            elapsed = time.time() - (self._start_timestamp or time.time())
            duration_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))

            temp_result = {
                'all': len(executed),
                'success': success, 'fail': fail,
                'error': error, 'skip': skip,
                'no_run': 0,
                'start_time': time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(self._start_timestamp or time.time())
                ),
                'duration': duration_str,
                'run_cases': executed,
                'no_run_cases': [],
            }

            # 复用引擎的报告生成器
            from UIEngine.reporting.html_report import generate_html_report
            generate_html_report(temp_suite, temp_result, self._debug_report_path)

            rel_path = os.path.relpath(self._debug_report_path, get_project_dir(self.config))
            print(f"  📊 调试报告已更新: {rel_path}")
        except Exception as e:
            # 报告生成失败不影响调试流程
            print(f"  [WARN] 调试报告生成失败: {e}", file=sys.stderr)

    def _open_debug_report(self):
        """在浏览器中打开 debug 报告（非交互环境跳过）"""
        if not sys.stdin.isatty():
            return  # CI/CD 环境无 GUI
        if not self._debug_report_path or not os.path.isfile(self._debug_report_path):
            return
        try:
            import webbrowser
            url = 'file:///' + os.path.abspath(self._debug_report_path).replace('\\', '/')
            webbrowser.open(url)
        except Exception:
            pass  # 静默失败，不影响调试流程

    def _debug_prompt(self, case_name, error, case_idx, attempt):
        """交互式提示，返回 'retry' / 'skip' / 'quit'

        :param case_name: 用例名称
        :param error: 异常对象
        :param case_idx: 用例序号（1-based）
        :param attempt: 当前尝试次数（0=首次，1=第一次重试...）
        :return: 'retry' / 'skip' / 'quit'
        """
        # 非终端环境（CI/管道）自动降级
        if not sys.stdin.isatty():
            print(f"  [DEBUG] 非交互环境，自动跳过")
            return 'skip'

        while True:
            print(f"\n{'='*40}")
            print(f"用例 [{case_name}] 失败: {error}")
            if self._debug_report_path:
                rel_path = os.path.relpath(self._debug_report_path, get_project_dir(self.config))
                print(f"📊 调试报告已在浏览器中打开: {rel_path}")
            print(f"浏览器保持打开，你可以手工操作页面")
            print(f"  [r] 重试当前用例  [s] 跳过，继续下一个  [q] 终止全部执行")
            try:
                choice = input("请选择: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()  # 换行
                return 'skip'

            if choice == 'r':
                if attempt >= self.max_retries:
                    print(f"  已达最大重试次数 ({self.max_retries})")
                    continue  # 让用户重新选择
                return 'retry'
            elif choice == 's':
                return 'skip'
            elif choice == 'q':
                return 'quit'
            else:
                print("  请输入 r/s/q")

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
    _has_cookie = bool(config.get('cookie'))
    _has_ls = bool(config.get('local_storage'))
    _has_token = bool(config.get('token'))
    if _has_cookie or _has_ls:
        _auth_kw = 'inject_local_storage'
    elif _has_token:
        _auth_kw = 'inject_token_header'
    else:
        _auth_kw = ''

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


def run_suite(suite_path, config, all_cases, all_data, extra_cases=None,
              runner_class=None):
    """运行单个测试套件

    加载套件文件 → 解析 case_ref 引用 → 注入全局变量 → 交给 Runner 执行
    extra_cases: 需要合并到套件末尾的额外用例列表（用于 --module 自动补充）
    runner_class: Runner 类或 DebugRunner 类（默认 Runner）
    """
    suite = load_yaml(suite_path)
    suite = resolve_suite(suite, all_cases)
    if extra_cases:
        suite.setdefault('cases', []).extend(extra_cases)
    gv = config.setdefault('global_variable', {})
    gv.update(flatten_dict(all_data))
    return (runner_class or Runner)(config).run(suite)


def run_master_suite(suites_dir, config, all_cases, all_data, cases_dir=None,
                     runner_class=None):
    """运行总套件：聚合所有用例，一次执行生成一个报告

    runner_class: Runner 类或 DebugRunner 类（默认 Runner）
    """
    suite = build_master_suite(suites_dir, all_cases, config, cases_dir=cases_dir)
    suite = resolve_suite(suite, all_cases)
    gv = config.setdefault('global_variable', {})
    gv.update(flatten_dict(all_data))
    return (runner_class or Runner)(config).run(suite)


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

    # ── 解析调试模式参数 ──
    debug_mode = '--debug' in sys.argv
    max_retries = 3  # 默认值
    if '--max-retries' in sys.argv:
        try:
            idx = sys.argv.index('--max-retries')
            max_retries = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            print("[WARN] --max-retries 参数无效，使用默认值 3", file=sys.stderr)

    # 选择 Runner 类
    if debug_mode:
        runner_class = lambda config: DebugRunner(config, max_retries=max_retries)
        print(f"[DEBUG 模式] 已启用，最大重试次数: {max_retries}")
    else:
        runner_class = Runner

    # 过滤调试参数，避免干扰后续参数解析
    _clean_args = []
    _skip_next = False
    for _a in sys.argv[1:]:
        if _skip_next:
            _skip_next = False
            continue
        if _a == '--debug':
            continue
        if _a == '--max-retries':
            _skip_next = True
            continue
        _clean_args.append(_a)

    # 解析命令行参数，确定要运行的套件
    if len(_clean_args) > 0 and _clean_args[0] == '--all':
        # --all 模式：构建总套件，聚合所有用例一次执行
        print(f"\n{'='*60}")
        print("执行总套件：全部用例汇总")
        print(f"{'='*60}")
        result = run_master_suite(suites_dir, config, all_cases, all_data,
                                  cases_dir=cases_dir, runner_class=runner_class)
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

    if len(_clean_args) > 0 and _clean_args[0] == '--module':
        # --module 模式：运行指定模块下的所有套件
        module = _clean_args[1] if len(_clean_args) > 1 else 'common'
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
    elif len(_clean_args) > 0:
        # 直接指定套件文件路径
        suite_files = _clean_args
    else:
        # 无参数：优先运行 suites/master.yaml（存在时）
        # master.yaml 由 generate_suites.py --all-modules 生成，包含所有模块的全部用例
        master_suite_path = os.path.join(suites_dir, 'master.yaml')
        if os.path.isfile(master_suite_path):
            print(f"\n{'='*60}")
            print("执行总套件: suites/master.yaml")
            print(f"{'='*60}")
            result = run_suite(master_suite_path, config, all_cases, all_data,
                              runner_class=runner_class)
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

        # 回退：扫描并运行所有套件（老项目兼容，无 master.yaml）
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
            if len(_clean_args) > 0 and _clean_args[0] == '--module':
                # --module 模式：全部合并到最后一个套件
                if sp == suite_files[-1]:
                    _extra = _unreferenced
            elif len(_clean_args) == 0:
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
        result = run_suite(sp, config, all_cases, all_data, extra_cases=_extra, runner_class=runner_class)
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
