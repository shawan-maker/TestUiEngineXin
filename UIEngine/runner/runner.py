"""UI 自动化测试执行器

设计原则：
- __init__ 只加载配置，不创建执行时对象
- run() 组装完整执行上下文（log/result/base_case/screenshot_mgr/tree_builder）
- 同一个 Runner 实例可复用于多个套件，每次 run() 独立隔离
"""
import os
import time
from UIEngine.basecase import BaseCase
from UIEngine.caseLog import CaseLogHandler
from UIEngine.reporting.result import TestResult
from UIEngine.reporting.html_report import generate_html_report
from UIEngine.reporting.execution_tree import ExecutionTreeBuilder
from UIEngine.runner.screenshot_manager import ScreenshotManager
from UIEngine.utils.path_helper import get_project_dir


class Runner:
    """UI 自动化测试执行器"""

    def __init__(self, config):
        """
        初始化执行器（仅加载配置）
        :param config: 执行的环境配置（dict 或 YAML 文件路径）
        """
        self.config = self._load_config(config)

    @staticmethod
    def _load_config(config):
        """加载配置：支持 dict 和 YAML 文件路径

        :param config: dict 或 YAML 文件路径字符串
        :return: 配置字典
        """
        if isinstance(config, dict):
            return config
        if isinstance(config, str):
            if os.path.isfile(config):
                try:
                    import yaml
                    with open(config, 'r', encoding='utf-8') as f:
                        return yaml.safe_load(f)
                except ImportError:
                    raise ImportError("需要安装 pyyaml 库：pip install pyyaml")
            else:
                raise FileNotFoundError(f"配置文件不存在：{config}")
        raise ValueError(f"不支持的配置类型：{type(config)}")

    def run(self, suite):
        """执行测试的入口函数

        每次调用 run() 都会为当前套件创建独立的执行上下文，
        保证多套件执行时日志和结果互不干扰。

        :param suite: 测试套件数据
        :return: 测试结果字典
        """
        # --- 组装本次执行的完整上下文 ---
        suite_id = suite.get('id', 'unknown')
        self.log = CaseLogHandler(name=f"suite_{suite_id}")
        self.result = TestResult()

        # 创建执行树构建器，绑定日志，传入 BaseCase
        self.tree_builder = ExecutionTreeBuilder()
        self.tree_builder.bind_log(self.log)
        self.base_case = BaseCase(self.config, self.log, tree_builder=self.tree_builder)

        # 使用项目目录（而非引擎目录）存储日志和截图
        project_dir = get_project_dir(self.config)
        files_dir = os.path.join(project_dir, 'files')
        default_pic_path = os.path.join(files_dir, 'shortcuts')
        self.screenshot_mgr = ScreenshotManager(
            self.config.get("error_pic_path", default_pic_path),
            self.log,
            max_dirs=self.config.get("max_suite_screenshot_dirs", 10)
        )

        # 配置日志文件输出到项目目录
        log_dir = os.path.join(files_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{suite_id}_{self._timestamp()}.log")
        self.log.add_file_handler(filepath=log_file)

        # --- 执行测试 ---
        self.result.suite_start_run()
        try:
            # 1、执行测试套件的公共前置步骤
            if suite.get("setup_step"):
                setup_steps = suite.get("setup_step")
                self.log.info_log(f"==============测试套件名称 【{suite.get('name')}】： 执行公共前置步骤==============")
                self.run_suite_setup(setup_steps)
            # 2、遍历执行测试套件的测试用例
            cases = suite.get("cases", [])
            if not cases:
                self.log.error_log("测试套件没有测试用例，本次执行结束")
                return
            suite_name = suite.get('name') or suite.get('id') or 'unnamed'
            self.run_suite_case(suite_name, cases)
        except Exception as e:
            self.log.error_log("执行测试套件失败，错误信息为：", e)
        finally:
            # 关闭浏览器
            self.base_case.close()
            # 记录测试套件的结束时间
            self.result.suite_end_run(suite, self.log.log_data)
            result = self.result.get_result(suite)

            # 清理旧报告（保留最近 3 天）
            report_dir = os.path.join(project_dir, 'report', 'run_report')
            os.makedirs(report_dir, exist_ok=True)
            self._cleanup_old_reports(report_dir, max_days=3)

            # 生成 HTML 测试报告
            report_file = os.path.join(report_dir, f"{suite_id}_{self._timestamp()}.html")
            generate_html_report(suite, result, report_file)
            self.log.info_log(f"HTML 测试报告已生成: {report_file}")

            return result

    @staticmethod
    def _timestamp():
        """生成时间戳字符串"""
        return time.strftime("%Y%m%d_%H%M%S", time.localtime())

    @staticmethod
    def _cleanup_old_reports(report_dir, max_days=3):
        """清理旧的 HTML 报告文件，保留最近 max_days 天的报告

        :param report_dir: 报告目录路径
        :param max_days: 保留天数（默认 3 天）
        """
        if not os.path.isdir(report_dir):
            return
        cutoff = time.time() - max_days * 86400
        for filename in os.listdir(report_dir):
            if filename.endswith('.html'):
                filepath = os.path.join(report_dir, filename)
                try:
                    if os.path.getmtime(filepath) < cutoff:
                        os.remove(filepath)
                except OSError:
                    pass

    def _relative_screenshot_path(self, img_full_path, project_dir):
        """计算截图相对于报告目录的路径

        :param img_full_path: 截图的完整路径
        :param project_dir: 项目根目录
        :return: 相对路径（使用正斜杠，适配 HTML）
        """
        if not img_full_path:
            return ''
        report_dir = os.path.join(project_dir, 'report', 'run_report')
        try:
            rel = os.path.relpath(img_full_path, report_dir)
            return rel.replace('\\', '/')
        except ValueError:
            return img_full_path

    def run_suite_setup(self, setup_steps):
        """执行测试套件的公共前置步骤"""
        try:
            for idx, step in enumerate(setup_steps):
                self.log.info_log(f"==============前置第{idx + 1}步：{step.get('desc')}==============")
                self.base_case.perform(step)
        except Exception as e:
            self.log.error_log("执行公共前置步骤失败,本次执行结束")
            self.log.error_log(e)
            return

    def run_suite_case(self, suite_name, cases):
        """执行测试套件中的所有用例

        :param suite_name: 测试套件名称
        :param cases: 测试用例列表
        """
        self.log.info_log(f"测试套件名称 【{suite_name}】： 执行测试用例")
        pic_path = self.screenshot_mgr.create_suite_dir(suite_name)
        project_dir = get_project_dir(self.config)

        for idx, case in enumerate(cases):
            # 兼容：优先用 name 字段，无则 fallback 到 id 或序号
            case_name = case.get('name') or case.get('id') or f"case_{idx + 1}"

            if case.get("skip"):
                self.log.info_log(f"==============第{idx + 1}个测试用例 -【{case_name}】跳过执行==============")
                self.result.add_skip(case)
                continue

            # 重置执行树，为当前用例构建独立的执行记录
            self.tree_builder.reset()
            case_start_time = time.time()

            try:
                self.log.info_log(f"==============第{idx + 1}个测试用例 - 【{case_name}】开始执行==============")
                self.run_case(case)
            except AssertionError as e:
                self.log.error_log(f"第{idx + 1}个测试用例 - 【{case_name}】断言失败,错误信息为：", e)
                img = self.base_case.save_page_img(f"{case_name}_fail", pic_path)
                # 为失败节点附加截图的相对路径
                img_rel = self._relative_screenshot_path(img, project_dir)
                self.tree_builder.attach_screenshot_to_failed(img_rel)
                # 传递日志快照副本（而非共享引用）
                self.result.add_fail(case, list(self.log.log_data), img)
            except Exception as e:
                self.log.error_log(f"第{idx + 1}个测试用例 - 【{case_name}】执行失败,错误信息为：", e)
                img = self.base_case.save_page_img(f"{case_name}_error", pic_path)
                img_rel = self._relative_screenshot_path(img, project_dir)
                self.tree_builder.attach_screenshot_to_failed(img_rel)
                self.result.add_error(case, list(self.log.log_data), img)
            else:
                self.log.info_log(f"==============第{idx + 1}个测试用例 - 【{case_name}】执行成功==============")
                img = self.base_case.save_page_img(f"{case_name}_success", pic_path)
                self.result.add_success(case, list(self.log.log_data), img)

            # 记录用例耗时和执行树
            case['_case_duration'] = time.time() - case_start_time
            case['_case_start_time'] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(case_start_time)
            )
            case['_execution_tree'] = self.tree_builder.get_tree()

    def run_case(self, case):
        """执行单条测试用例"""
        case_steps = case.get("steps", [])
        if not case_steps:
            self.log.error_log(f"测试用例【{case.get('name')}】没有步骤，跳过执行")
            return
        for idx, step in enumerate(case_steps):
            self.log.info_log(f"==============用例【{case.get('name')}】第{idx + 1}步：{step.get('desc')}==============")
            self.base_case.perform(step)
