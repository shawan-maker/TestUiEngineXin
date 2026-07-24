"""流程控制关键字

新增关键字：
- set_variable / set_variable_from_element  — 变量管理
- if_element_visible / if_variable          — 条件执行
- for_each / retry_until                     — 循环
- goto_step                                  — 步骤跳转
- log                                        — 日志输出
"""
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager


class FlowMixin(BaseBrowser):
    """流程控制相关的操作"""

    @KeyWordManager.register("set_variable", "设置变量")
    def set_variable(self, name=None, value=None):
        """将值存入全局变量池，后续步骤通过 ${name} 引用"""
        if name is not None and value is not None:
            self.config.setdefault('runtime_variables', {})[name] = str(value)
            self.log.debug_log(f"设置变量: {name} = {value}")

    @KeyWordManager.register("set_variable_from_element", "从元素设置变量")
    def set_variable_from_element(self, locator=None, target_var=None, mode="text", timeout=3000):
        """从页面元素提取值存入变量

        :param locator: 元素的定位表达式
        :param target_var: 目标变量名
        :param mode: 提取模式，text=文本内容, attribute=属性值, value=输入框值
        :param timeout: 超时时间
        """
        el = self.page.locator(locator).first
        if mode == "text":
            val = el.text_content(timeout=timeout)
        elif mode == "attribute":
            val = el.get_attribute("value", timeout=timeout)
        elif mode == "value":
            val = el.input_value(timeout=timeout)
        else:
            val = el.text_content(timeout=timeout)
        self.config.setdefault('runtime_variables', {})[target_var] = str(val)
        self.log.debug_log(f"从元素提取变量: {target_var} = {val}")

    @KeyWordManager.register("append_variable", "追加变量")
    def append_variable(self, name=None, value=None):
        """将值追加到列表变量中（而非覆盖）

        :param name: 目标列表变量名
        :param value: 要追加的值
        """
        if name is None or value is None:
            return
        runtime_vars = self.config.setdefault('runtime_variables', {})
        if name not in runtime_vars or not isinstance(runtime_vars[name], list):
            runtime_vars[name] = []
        runtime_vars[name].append(str(value))
        self.log.debug_log(f"追加变量: {name} += {value} (当前 {len(runtime_vars[name])} 条)")

    @KeyWordManager.register("append_variable_from_element", "从元素追加变量")
    def append_variable_from_element(self, locator=None, target_var=None, mode="text", timeout=3000):
        """从页面元素提取值并追加到列表变量

        :param locator: 元素的定位表达式
        :param target_var: 目标列表变量名
        :param mode: 提取模式，text=文本内容, attribute=属性值, value=输入框值
        :param timeout: 超时时间
        """
        el = self.page.locator(locator).first
        if mode == "text":
            val = el.text_content(timeout=timeout)
        elif mode == "attribute":
            val = el.get_attribute("value", timeout=timeout)
        elif mode == "value":
            val = el.input_value(timeout=timeout)
        else:
            val = el.text_content(timeout=timeout)
        runtime_vars = self.config.setdefault('runtime_variables', {})
        if target_var not in runtime_vars or not isinstance(runtime_vars[target_var], list):
            runtime_vars[target_var] = []
        runtime_vars[target_var].append(str(val).strip())
        self.log.debug_log(f"从元素追加变量: {target_var} += {str(val).strip()[:80]}")

    @KeyWordManager.register("if_element_visible", "元素可见则执行")
    def if_element_visible(self, locator=None, then_steps=None, else_steps=None, timeout=3000):
        """元素可见时执行 then_steps，否则执行 else_steps

        :param locator: 元素的定位表达式
        :param then_steps: 元素可见时执行的步骤列表
        :param else_steps: 元素不可见时执行的步骤列表
        :param timeout: 等待元素可见的超时时间
        """
        try:
            is_visible = self.page.locator(locator).first.is_visible(timeout=timeout)
        except Exception:
            is_visible = False

        steps_to_run = then_steps if is_visible else else_steps
        if steps_to_run:
            for step in steps_to_run:
                self.perform(step)
        self.log.debug_log(f"条件执行: {locator} visible={is_visible}, 执行 {'then' if is_visible else 'else'} 分支")

    @KeyWordManager.register("if_variable", "变量满足条件则执行")
    def if_variable(self, name=None, operator="eq", compare_value=None, then_steps=None, else_steps=None):
        """变量比较后分支执行

        :param name: 变量名
        :param operator: 比较操作符 eq/ne/contains/gt/lt/ge/le
        :param compare_value: 比较值
        :param then_steps: 条件满足时执行的步骤列表
        :param else_steps: 条件不满足时执行的步骤列表
        """
        runtime_vars = self.config.get('runtime_variables', {})
        actual = runtime_vars.get(name, '')

        op_map = {
            'eq': lambda a, b: a == b,
            'ne': lambda a, b: a != b,
            'contains': lambda a, b: b in a,
            'gt': lambda a, b: float(a) > float(b),
            'lt': lambda a, b: float(a) < float(b),
            'ge': lambda a, b: float(a) >= float(b),
            'le': lambda a, b: float(a) <= float(b),
        }
        op_func = op_map.get(operator, op_map['eq'])
        condition_met = op_func(str(actual), str(compare_value or ''))

        steps_to_run = then_steps if condition_met else else_steps
        if steps_to_run:
            for step in steps_to_run:
                self.perform(step)
        self.log.debug_log(f"变量条件: {name}={actual} {operator} {compare_value} -> {condition_met}")

    @KeyWordManager.register("for_each", "遍历元素集合")
    def for_each(self, locator=None, steps=None, var_name="item", collect_to=None, collect=None):
        """对每个匹配元素执行步骤，当前元素引用存入 ${var_name}

        :param locator: 元素集合的定位表达式
        :param steps: 对每个元素执行的步骤列表
        :param var_name: 当前元素引用变量名，默认 item
        :param collect_to: 收集结果的目标变量名（如 "products"），不设则不收集
        :param collect: 每轮循环要收集的变量名列表（如 ["asin", "title", "price"]）
        """
        count = self.page.locator(locator).count()
        self.log.debug_log(f"遍历元素: {locator}, 共 {count} 个")

        collected = []
        runtime_vars = self.config.setdefault('runtime_variables', {})
        for i in range(count):
            current_locator = f"{locator} >> nth={i}"
            runtime_vars[var_name] = current_locator
            for step in steps:
                self.perform(step)
            # 每轮循环结束后，把指定变量快照收集起来
            if collect_to and collect:
                record = {key: runtime_vars.get(key, '') for key in collect}
                collected.append(record)

        if collect_to and collected:
            runtime_vars[collect_to] = collected
            self.log.debug_log(f"已收集 {len(collected)} 条记录到 ${{{collect_to}}}")

    @KeyWordManager.register("retry_until", "重试直到成功")
    def retry_until(self, steps=None, max_retry=3, interval=1000):
        """重试步骤直到无错误，最多 max_retry 次

        :param steps: 要重试的步骤列表
        :param max_retry: 最大重试次数
        :param interval: 重试间隔（毫秒）
        """
        for attempt in range(1, max_retry + 1):
            try:
                for step in steps:
                    self.perform(step)
                self.log.debug_log(f"重试成功: 第 {attempt} 次")
                return
            except Exception as e:
                if attempt == max_retry:
                    raise
                self.log.debug_log(f"重试: 第 {attempt} 次失败, {interval}ms 后重试")
                self.page.wait_for_timeout(interval)

    @KeyWordManager.register("goto_step", "跳转步骤")
    def goto_step(self, label=None):
        """标记步骤标签，配合条件分支使用

        :param label: 跳转标签名
        """
        self.log.debug_log(f"跳转标签: {label}")

    @KeyWordManager.register("log", "日志输出")
    def log_message(self, message=None):
        """输出日志信息，用于条件分支中标记用例状态

        :param message: 日志消息内容
        """
        self.log.debug_log(f"[用例日志] {message}")
