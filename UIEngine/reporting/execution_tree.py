"""执行树数据结构

用于在测试用例执行期间构建层级化的执行记录。
通过 push/pop 栈模式，自动追踪关键字的嵌套调用关系。

节点层级示例：
  StepNode(fill_value)           # 用例的顶层步骤
    └─ StepNode(click_element)   # fill_value 内部调用的子关键字
         └─ StepNode(wait)       # click_element 内部再调用的子关键字
"""
import time


class StepNode:
    """执行树节点 — 表示一个测试步骤或关键字调用

    Attributes:
        keyword: 关键字名称 (如 "click_element")
        desc: 步骤描述 (来自 step['desc'])
        params: 解析后的参数 dict (${var} 已替换为实际值)
        status: "pass" | "fail" | "error" | "running"
        error_msg: 失败时的异常信息 (str | None)
        screenshot: 失败截图的相对路径 (str | None)
        start_time: 开始时间戳 (float, time.time())
        end_time: 结束时间戳 (float | None)
        duration_ms: 执行耗时 (毫秒)
        children: 子步骤列表 (关键字嵌套调用产生的子节点)
        log_entries: 该步骤执行期间的日志快照 [(level, msg), ...]
        depth: 嵌套深度 (0 = 用例顶层步骤)
        hide_in_report: HTML 报告中是否隐藏 (bool, 用于滚动等实现细节步骤)
    """
    __slots__ = (
        'keyword', 'desc', 'params', 'status', 'error_msg',
        'screenshot', 'start_time', 'end_time', 'duration_ms',
        'children', 'log_entries', 'depth', 'hide_in_report',
    )

    def __init__(self, keyword, desc, params, depth):
        self.keyword = keyword
        self.desc = desc
        self.params = params
        self.status = 'running'
        self.error_msg = None
        self.screenshot = None
        self.start_time = time.time()
        self.end_time = None
        self.duration_ms = None
        self.children = []
        self.log_entries = []
        self.depth = depth
        self.hide_in_report = False

    def to_dict(self):
        """转换为字典，便于序列化或报告生成"""
        return {
            'keyword': self.keyword,
            'desc': self.desc,
            'params': self.params,
            'status': self.status,
            'error_msg': self.error_msg,
            'screenshot': self.screenshot,
            'duration_ms': self.duration_ms,
            'depth': self.depth,
            'log_entries': self.log_entries,
            'children': [child.to_dict() for child in self.children],
            'hide_in_report': self.hide_in_report,
        }


class ExecutionTreeBuilder:
    """执行树构建器 — 通过 push/pop 模式在 perform() 调用期间构建树

    使用方式：
        builder = ExecutionTreeBuilder()
        builder.bind_log(log_handler)

        # 每个用例执行前重置
        builder.reset()

        # 在 BaseCase.perform() 中自动调用
        builder.push_step(step_dict, resolved_params)
        # ... 执行关键字 ...
        builder.pop_step()  # 或 builder.pop_step(error=exception)

        # 用例执行完成后获取树
        tree = builder.get_tree()
    """

    def __init__(self):
        self._stack = []       # 当前嵌套栈 (Stack of StepNode)
        self._roots = []       # 顶层节点列表
        self._log_ref = None   # CaseLogHandler 引用，用于日志快照
        self._log_start_idx = 0  # 日志起始索引 (用于截取当前步骤的日志)

    def bind_log(self, log_handler):
        """绑定 CaseLogHandler，用于按步骤截取日志快照"""
        self._log_ref = log_handler
        self._log_start_idx = len(log_handler.log_data)

    def reset(self):
        """重置状态 — 每个用例执行前调用"""
        self._stack.clear()
        self._roots.clear()
        if self._log_ref:
            self._log_start_idx = len(self._log_ref.log_data)

    def push_step(self, step_dict, resolved_params=None):
        """在 perform() 开始时调用 — 创建节点并推入栈

        :param step_dict: 原始步骤字典 (包含 desc, keyword/method, params)
        :param resolved_params: 变量替换后的参数 (可选，默认使用 step_dict['params'])
        :return: 创建的 StepNode
        """
        keyword = step_dict.get('keyword') or step_dict.get('method', '')
        desc = step_dict.get('desc', '')
        params = resolved_params if resolved_params is not None else step_dict.get('params', {})
        depth = len(self._stack)

        node = StepNode(keyword=keyword, desc=desc, params=params, depth=depth)
        node.hide_in_report = bool(step_dict.get('_hide_in_report'))

        # 建立父子关系：如果有栈顶节点，当前节点为其子节点
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self._roots.append(node)

        self._stack.append(node)
        return node

    def pop_step(self, error=None, screenshot=None):
        """在 perform() 结束时调用 — 弹出节点并记录结果

        :param error: 异常对象 (None 表示成功)
        :param screenshot: 截图路径 (可选)
        """
        if not self._stack:
            return

        node = self._stack.pop()
        node.end_time = time.time()
        node.duration_ms = (node.end_time - node.start_time) * 1000

        # 截取该步骤执行期间的日志
        if self._log_ref:
            current_len = len(self._log_ref.log_data)
            node.log_entries = list(self._log_ref.log_data[self._log_start_idx:current_len])
            # 更新起始索引，下一个步骤从当前位置开始截取
            self._log_start_idx = current_len

        # 记录状态
        if error:
            if isinstance(error, AssertionError):
                node.status = 'fail'
            else:
                node.status = 'error'
            node.error_msg = str(error)
        else:
            node.status = 'pass'

        if screenshot:
            node.screenshot = screenshot

    def attach_screenshot_to_failed(self, screenshot_path):
        """为最后一个失败的节点附加截图路径

        当 Runner 在用例级别捕获异常并截图后调用，
        将截图路径关联到执行树中最后一个失败的节点。

        :param screenshot_path: 截图的相对路径
        """
        # 优先从栈顶查找（如果还没 pop）
        for node in reversed(self._stack):
            if node.status in ('fail', 'error') and not node.screenshot:
                node.screenshot = screenshot_path
                return
        # 从所有根节点递归查找最后一个失败节点
        last_failed = self._find_last_failed(self._roots)
        if last_failed:
            last_failed.screenshot = screenshot_path

    def _find_last_failed(self, nodes):
        """递归查找最后一个失败的节点"""
        result = None
        for node in nodes:
            # 先递归子节点（后序遍历，最后访问的失败节点即最后一个）
            child_result = self._find_last_failed(node.children)
            if child_result:
                result = child_result
            elif node.status in ('fail', 'error'):
                result = node
        return result

    def get_tree(self):
        """返回构建完成的执行树 (顶层 StepNode 列表)"""
        return list(self._roots)

    @property
    def current_depth(self):
        """当前嵌套深度"""
        return len(self._stack)
