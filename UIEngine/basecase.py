"""BaseCase 组合类

将所有 Mixin 组合为统一的测试用例基类。
包含关键字调度（perform）和变量替换功能。
所有 Mixin 方法在类定义后自动注册到 KeyWordManager。
"""
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


class BaseCase(PageMixin, LocatorMixin, MouseMixin, WaitMixin, IFrameMixin, AssertMixin, FlowMixin):
    """测试用例基类 - 组合所有关键字 Mixin

    继承链（MRO）：
    BaseCase → PageMixin → LocatorMixin → MouseMixin → WaitMixin
             → IFrameMixin → AssertMixin → FlowMixin → BaseBrowser
    """

    def __init__(self, config, log, tree_builder=None, **kwargs):
        super().__init__(config, log, **kwargs)
        self.variable_resolver = VariableResolver(config, log)
        self.tree_builder = tree_builder  # ExecutionTreeBuilder 实例，None 时不追踪

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
        if self.tree_builder:
            self.tree_builder.push_step(step, resolved_params)

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

            # 执行成功，弹出节点
            if self.tree_builder:
                self.tree_builder.pop_step()
            return result
        except Exception as e:
            # 执行失败，弹出节点并记录错误（异常继续上抛给 Runner 处理截图）
            if self.tree_builder:
                self.tree_builder.pop_step(error=e)
            raise


# 自动注册：将 BaseCase 的所有公共方法注册到关键字映射表
# 已通过 @register 装饰器注册的方法不会被覆盖
KeyWordManager.auto_register_methods(BaseCase)
