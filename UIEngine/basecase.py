"""BaseCase 组合类

将所有 Mixin 组合为统一的测试用例基类。
包含关键字调度（perform）和变量替换功能。
所有 Mixin 方法在类定义后自动注册到 KeyWordManager。
"""
import os
import re

from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.keywords.page_keywords import PageMixin
from UIEngine.keywords.locator_keywords import LocatorMixin
from UIEngine.keywords.mouse_keywords import MouseMixin
from UIEngine.keywords.wait_keywords import WaitMixin
from UIEngine.keywords.iframe_keywords import IFrameMixin
from UIEngine.keywords.assert_keywords import AssertMixin
from UIEngine.keywords.flow_keywords import FlowMixin
from UIEngine.core.keyword_manager import KeyWordManager
from UIEngine.core.variable_resolver import VariableResolver
from UIEngine.core.exceptions import KeywordNotFoundError

# 断言类关键字集合 — 匹配 EN 名和 CN 别名
# perform() 中判断 keyword 是否在此集合中，决定是否自动截图
ASSERTION_KEYWORDS = frozenset({
    # assert_keywords.py
    'assert_page_title', '断言标题',
    'assert_page_url', '断言URL',
    'except_to_have_value', '断言有值',
    'except_to_have_text', '断言有文本',
    'except_to_have_attribute', '断言有属性',
    'except_to_be_visible', '断言可见',
    'except_to_be_hidden', '断言隐藏',
    'except_to_be_enabled', '断言可用',
    'except_to_be_disabled', '断言不可用',
    'except_to_be_checked', '断言选中',
    'except_to_be_empty', '断言为空',
    'except_to_be_editable', '断言可编辑',
    'except_to_be_focused', '断言聚焦',
    'except_element_count', '断言元素数量',
    # iframe_keywords.py
    'frame_except_to_be_visible', '框架断言可见',
    'frame_except_to_be_hidden', '框架断言隐藏',
    'frame_except_to_have_text', '框架断言文本',
})

# Windows 文件名非法字符正则（用于文件名消毒）
_FILENAME_INVALID_RE = re.compile(r'[<>:"/\\|?*]')


class BaseCase(PageMixin, LocatorMixin, MouseMixin, WaitMixin, IFrameMixin, AssertMixin, FlowMixin):
    """测试用例基类 - 组合所有关键字 Mixin

    继承链（MRO）：
    BaseCase → PageMixin → LocatorMixin → MouseMixin → WaitMixin
             → IFrameMixin → AssertMixin → FlowMixin → BaseBrowser
    """

    def __init__(self, config, log, tree_builder=None, **kwargs):
        super().__init__(config, log, **kwargs)
        self.variable_resolver = VariableResolver(config, log)
        self.tree_builder = tree_builder
        # ── 断言截图上下文（由 Runner 在 run_suite_case 前设置）──
        self._assertion_screenshot_dir = None  # 截图根目录（None 时不截图）
        self._current_module = None            # 当前用例模块名
        self._current_case_name = None         # 当前用例名称
        self._current_seq = 0                  # 当前用例序号
        self._assertion_counter = 0            # 当前用例的断言计数器

    def perform(self, step):
        """执行测试步骤

        支持两种执行模式：
        1. 关键字模式：通过 KeyWordManager.maps 查表调用（step 中使用 "keyword" 或 "method"）
        2. 直接调用模式：关键字未注册时，回退到 getattr(self, method) 直接调用

        模式 2 允许调用未注册为关键字的实例方法（如 open_browser, close, reset_browser_context 等）。

        当 tree_builder 不为 None 时，自动追踪关键字嵌套调用关系：
        - 进入 perform() 时 push 节点
        - 关键字内部再调用 perform() 时，子节点自动成为当前节点的 child
        - 退出 perform() 时 pop 节点并记录结果

        :param step: 测试步骤字典，包含 keyword/method、params、desc 等字段
        :return: 关键字函数的返回值（如 get_element_count 返回数量，get_text 返回文本）
        """
        keyword = step.get("keyword") or step.get("method")
        params = step.get("params", {})
        resolved_params = self.variable_resolver.resolve(params)

        # 推入执行树（记录开始时间，建立父子关系）
        # 传递 raw_params（未解析的原始参数），用于报告显示键名
        if self.tree_builder:
            self.tree_builder.push_step(step, resolved_params, raw_params=params)

        try:
            # 优先通过关键字注册表查找
            method = KeyWordManager.get_keyword_maps(keyword)
            if method:
                result = method(self, **resolved_params)
            elif hasattr(self, keyword):
                # 回退：直接调用实例方法（兼容未注册为关键字的方法）
                result = getattr(self, keyword)(**resolved_params)
            else:
                raise KeywordNotFoundError(f"{step.get('desc', '')}执行的关键字 '{keyword}' 不存在")

            # ★ 断言通过时截图（在 pop_step 之前，此时执行树栈顶就是当前节点）
            if keyword in ASSERTION_KEYWORDS:
                self._capture_assertion_screenshot()

            # 执行成功，弹出节点
            if self.tree_builder:
                self.tree_builder.pop_step()
            return result
        except Exception as e:
            # ★ 断言失败时截图（在 pop_step 之前捕获页面状态）
            if keyword in ASSERTION_KEYWORDS:
                self._capture_assertion_screenshot()

            # 执行失败，弹出节点并记录错误（异常继续上抛给 Runner 处理截图）
            if self.tree_builder:
                self.tree_builder.pop_step(error=e)
            raise

    def _capture_assertion_screenshot(self):
        """断言步骤截图（成功/失败均截）

        保存到 report/screenshots/{project}/{module}/{seq}-{case_name}-{idx}.png
        同时通过公共方法附加到执行树当前栈顶节点。
        截图失败时静默跳过，不影响测试执行。
        """
        # tree_builder 为 None 时，截图无法附加到报告，跳过（避免孤立文件）
        if not self._assertion_screenshot_dir or not self.tree_builder:
            return
        try:
            self._assertion_counter += 1
            module = self._current_module or 'default'
            case_name = self._current_case_name or 'unknown'
            seq = self._current_seq or 0

            # 文件名消毒（替换 Windows 非法字符）
            safe_name = _FILENAME_INVALID_RE.sub('_', case_name)

            # 构建目录: report/screenshots/{project}/{module}/
            module_dir = os.path.join(self._assertion_screenshot_dir, module)
            os.makedirs(module_dir, exist_ok=True)

            # 构建文件名: {seq:02d}-{case_name}-{assertion_idx:02d}.png
            filename = f"{seq:02d}-{safe_name}-{self._assertion_counter:02d}.png"
            full_path = os.path.join(module_dir, filename)

            # Playwright 截图
            if self.page:
                self.page.screenshot(path=full_path)

                # 使用公共方法附加到执行树（不访问私有 _stack）
                self.tree_builder.attach_assertion_screenshot(full_path)
        except Exception:
            pass  # 截图失败不影响测试执行


# 自动注册：将 BaseCase 的所有公共方法注册到关键字映射表
# 已通过 @register 装饰器注册的方法不会被覆盖
KeyWordManager.auto_register_methods(BaseCase)
