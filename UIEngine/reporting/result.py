"""测试结果聚合

修复：no_run 计算只减了 success，应减去所有已执行状态。
"""
import time


class TestResult:
    """测试结果类"""

    def __init__(self):
        self.all = 0              # 用例总数
        self.success = 0          # 用例成功总数
        self.fail = 0             # 用例失败总数
        self.error = 0            # 用例错误总数
        self.skip = 0             # 用例跳过总数
        self.no_run = 0           # 未执行用例总数
        self.start_time = None    # 开始时间
        self.duration = None      # 执行时长
        self.suite_log = []       # 用例日志
        self.run_cases = []       # 执行用例列表
        self.no_run_cases = []    # 未执行的用例列表
        self.start_timestamp = None  # 开始时间戳

    def add_success(self, _case, log, img):
        """
        :param _case: 通过的用例
        :param log: 用例日志（应为快照副本，避免共享引用）
        :param img: 用例截图路径
        """
        self.success += 1
        _case['state'] = "success"
        _case['log_data'] = log
        _case['img'] = img
        self.run_cases.append(_case)

    def add_fail(self, _case, log, img):
        """
        :param _case: 失败的用例
        :param log: 用例日志（应为快照副本，避免共享引用）
        :param img: 用例截图路径
        """
        self.fail += 1
        _case['state'] = "fail"
        _case['log_data'] = log
        _case['img'] = img
        self.run_cases.append(_case)

    def add_error(self, _case, log, img):
        """
        :param _case: 错误的用例
        :param log: 用例日志（应为快照副本，避免共享引用）
        :param img: 用例截图路径
        """
        self.error += 1
        _case['state'] = "error"
        _case['log_data'] = log
        _case['img'] = img
        self.run_cases.append(_case)

    def add_skip(self, _case):
        """
        :param _case: 跳过的用例
        """
        self.skip += 1
        _case['state'] = "skip"
        self.run_cases.append(_case)

    def add_no_run(self, _case):
        """
        :param _case: 未执行的用例
        """
        self.no_run += 1
        self.no_run_cases.append(_case)

    def suite_start_run(self):
        """开始测试"""
        self.start_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        self.start_timestamp = time.time()

    def suite_end_run(self, suite, suite_log):
        """
        结束测试，并计算运行时长
        :param suite: 测试套件数据
        :param suite_log: 套件执行日志
        """
        # 获取运行时长
        if self.start_timestamp is not None:
            elapsed_time = time.time() - self.start_timestamp
            self.duration = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))
        else:
            self.duration = "00:00:00"
        # 保存套件日志信息
        self.suite_log = suite_log
        # 判断所有用例总数
        self.all = len(suite.get('cases', []))
        # 修复：no_run 应减去所有已执行的用例（success + fail + error + skip）
        executed = self.success + self.fail + self.error + self.skip
        if self.all != executed:
            self.no_run = self.all - executed
            # 获取所有已执行的用例 ID
            run_case_ids = [i.get('id') for i in self.run_cases]
            # 遍历套件中的所有用例，获取未执行的用例
            for case in suite.get('cases', []):
                if case.get('id') not in run_case_ids:
                    self.no_run_cases.append(case)

    def get_result(self, suite):
        """
        获取测试结果
        :param suite: 测试套件数据
        :return: 结果字典
        """
        return {
            "suite_id": suite.get('id'),
            "suite_name": suite.get('name'),
            "all": self.all,
            "success": self.success,
            "fail": self.fail,
            "error": self.error,
            "skip": self.skip,
            "no_run": self.no_run,
            "start_time": self.start_time,
            "duration": self.duration,
            "suite_log": self.suite_log,
            "run_cases": self.run_cases,
            "no_run_cases": self.no_run_cases
        }
