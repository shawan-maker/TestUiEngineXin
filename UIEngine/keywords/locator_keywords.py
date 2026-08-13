"""元素操作关键字

包含：输入、点击、悬停、拖拽、勾选、清空、状态查询等。
新增 Playwright 常用操作：double_click, check, uncheck, clear, upload_file 等。
"""
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager


class LocatorMixin(BaseBrowser):
    """页面元素相关的操作"""

    @KeyWordManager.register("fill_value", "输入值")
    def fill_value(self, locator, value, timeout=3000):
        """
        输入框填入值
        :param locator: 输入框的定位表达式
        :param value: 输入的值
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在定位元素:{locator}，输入值:{value}")
        self.page.locator(locator).fill(value, timeout=timeout)

    @KeyWordManager.register("click_element", "点击元素")
    def click_element(self, locator, timeout=3000, force=False):
        """
        点击元素
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        :param force: 是否强制点击（跳过 actionability 检查，用于被覆盖的元素）
        """
        self.log.debug_log(f"正在点击元素:{locator}")
        loc = self.page.locator(locator)
        try:
            loc.click(timeout=timeout, force=force)
        except Exception:
            # 元素可能在局部滚动容器内，先滚动到视口再重试一次
            self.log.debug_log(f"元素不在视口内，尝试滚动后重试:{locator}")
            loc.scroll_into_view_if_needed(timeout=timeout)
            loc.click(timeout=timeout, force=force)

    @KeyWordManager.register("hover", "悬停")
    def hover(self, locator, timeout=3000):
        """悬停到元素上方"""
        self.log.debug_log(f"正在悬停到元素:{locator}")
        loc = self.page.locator(locator)
        try:
            loc.hover(timeout=timeout)
        except Exception:
            # 元素可能在局部滚动容器内，先滚动到视口再重试一次
            self.log.debug_log(f"元素不在视口内，尝试滚动后重试:{locator}")
            loc.scroll_into_view_if_needed(timeout=timeout)
            loc.hover(timeout=timeout)

    @KeyWordManager.register("focus_element", "聚焦元素")
    def focus_element(self, locator, timeout=3000):
        """
        聚焦元素
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在聚焦元素:{locator}")
        self.page.locator(locator).focus(timeout=timeout)

    @KeyWordManager.register("select_option", "选择选项")
    def select_option(self, locator, value, timeout=3000):
        """
        选择下拉框的选项
        :param locator: 下拉框的定位表达式
        :param value: 选项的值
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在选择下拉框:{locator}，选项的值:{value}")
        self.page.locator(locator).select_option(value, timeout=timeout)

    @KeyWordManager.register("type_text", "输入文本")
    def type_text(self, locator, value, timeout=3000):
        """
        输入文本（模拟真人逐个字符键盘输入）
        :param locator: 输入框的定位表达式
        :param value: 输入的值
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在元素:{locator}，输入值:{value}")
        self.page.locator(locator).press_sequentially(value, timeout=timeout)

    @KeyWordManager.register("drag_and_drop", "拖拽")
    def drag_and_drop(self, start_selector, end_selector, timeout=3000):
        """
        拖拽元素
        :param start_selector: 拖拽的元素
        :param end_selector: 拖拽到的元素
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在拖拽元素:{start_selector}，拖拽到的元素:{end_selector}")
        self.page.locator(start_selector).drag_to(self.page.locator(end_selector))

    @KeyWordManager.register("double_click", "双击")
    def double_click(self, locator, timeout=3000):
        """
        双击元素
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在双击元素:{locator}")
        loc = self.page.locator(locator)
        try:
            loc.dblclick(timeout=timeout)
        except Exception:
            # 元素可能在局部滚动容器内，先滚动到视口再重试一次
            self.log.debug_log(f"元素不在视口内，尝试滚动后重试:{locator}")
            loc.scroll_into_view_if_needed(timeout=timeout)
            loc.dblclick(timeout=timeout)

    @KeyWordManager.register("check", "勾选")
    def check(self, locator, timeout=3000):
        """
        勾选复选框/单选框
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在勾选元素:{locator}")
        self.page.locator(locator).check(timeout=timeout)

    @KeyWordManager.register("uncheck", "取消勾选")
    def uncheck(self, locator, timeout=3000):
        """
        取消勾选复选框
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在取消勾选元素:{locator}")
        self.page.locator(locator).uncheck(timeout=timeout)

    @KeyWordManager.register("set_checked", "设置勾选")
    def set_checked(self, locator, checked, timeout=3000):
        """
        设置勾选状态
        :param locator: 元素的定位表达式
        :param checked: True 勾选，False 取消勾选
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在设置元素:{locator}，勾选状态:{checked}")
        self.page.locator(locator).set_checked(checked, timeout=timeout)

    @KeyWordManager.register("clear", "清空输入框")
    def clear(self, locator, timeout=3000):
        """
        清空输入框
        :param locator: 输入框的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在清空输入框:{locator}")
        self.page.locator(locator).clear(timeout=timeout)

    @KeyWordManager.register("get_text", "获取文本")
    def get_text(self, locator, timeout=3000):
        """
        获取元素的文本内容
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        :return: 元素文本
        """
        self.log.debug_log(f"正在获取元素文本:{locator}")
        return self.page.locator(locator).text_content(timeout=timeout)

    @KeyWordManager.register("get_attribute", "获取属性")
    def get_attribute(self, locator, name, target_var=None, timeout=3000):
        """
        获取元素的属性值
        :param locator: 元素的定位表达式
        :param name: 属性名称
        :param target_var: 可选，将结果存入运行时变量池（供后续步骤通过 ${target_var} 引用）
        :param timeout: 等待元素可见的最大超时时间
        :return: 属性值
        """
        self.log.debug_log(f"正在获取元素:{locator}的属性:{name}")
        value = self.page.locator(locator).get_attribute(name, timeout=timeout)
        if target_var is not None:
            self.config.setdefault('runtime_variables', {})[target_var] = str(value) if value else ''
            self.log.debug_log(f"属性值已存入变量: {target_var} = {value}")
        return value

    @KeyWordManager.register("get_input_value", "获取输入值")
    def get_input_value(self, locator, timeout=3000):
        """
        获取输入框的当前值
        :param locator: 输入框的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        :return: 输入框当前值
        """
        self.log.debug_log(f"正在获取输入框值:{locator}")
        return self.page.locator(locator).input_value(timeout=timeout)

    @KeyWordManager.register("is_visible", "是否可见")
    def is_visible(self, locator):
        """
        查询元素是否可见
        :param locator: 元素的定位表达式
        :return: True/False
        """
        self.log.debug_log(f"正在查询元素是否可见:{locator}")
        return self.page.locator(locator).is_visible()

    @KeyWordManager.register("is_hidden", "是否隐藏")
    def is_hidden(self, locator):
        """
        查询元素是否隐藏
        :param locator: 元素的定位表达式
        :return: True/False
        """
        self.log.debug_log(f"正在查询元素是否隐藏:{locator}")
        return self.page.locator(locator).is_hidden()

    @KeyWordManager.register("is_enabled", "是否可用")
    def is_enabled(self, locator):
        """
        查询元素是否可用（未被禁用）
        :param locator: 元素的定位表达式
        :return: True/False
        """
        self.log.debug_log(f"正在查询元素是否可用:{locator}")
        return self.page.locator(locator).is_enabled()

    @KeyWordManager.register("is_disabled", "是否不可用")
    def is_disabled(self, locator):
        """
        查询元素是否不可用
        :param locator: 元素的定位表达式
        :return: True/False
        """
        self.log.debug_log(f"正在查询元素是否不可用:{locator}")
        return self.page.locator(locator).is_disabled()

    @KeyWordManager.register("is_checked", "是否选中")
    def is_checked(self, locator):
        """
        查询元素是否被选中（复选框/单选框）
        :param locator: 元素的定位表达式
        :return: True/False
        """
        self.log.debug_log(f"正在查询元素是否选中:{locator}")
        return self.page.locator(locator).is_checked()

    @KeyWordManager.register("get_element_count", "获取元素数量")
    def get_element_count(self, locator):
        """
        获取匹配定位表达式的元素数量
        :param locator: 元素的定位表达式
        :return: 元素数量
        """
        self.log.debug_log(f"正在获取元素数量:{locator}")
        return self.page.locator(locator).count()

    @KeyWordManager.register("upload_file", "上传文件")
    def upload_file(self, locator, files, timeout=3000):
        """
        上传文件
        :param locator: 文件输入框的定位表达式
        :param files: 文件路径（str 或 list[str]）
        :param timeout: 超时时间
        """
        self.log.debug_log(f"正在上传文件:{files}到元素:{locator}")
        self.page.locator(locator).set_input_files(files, timeout=timeout)

    @KeyWordManager.register("select_multiple_options", "多选下拉")
    def select_multiple_options(self, locator, values, timeout=3000):
        """
        多选下拉框
        :param locator: 下拉框的定位表达式
        :param values: 选项值列表
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在多选下拉框:{locator}，选项值:{values}")
        self.page.locator(locator).select_option(values, timeout=timeout)

    @KeyWordManager.register("click_select_option", "点击选择选项")
    def click_select_option(self, locator, value, timeout=3000):
        """
        操作 Element UI / Ant Design 等自定义下拉框（非原生 <select>）

        通过"点击展开 → 点击选项"两步完成选择。
        适用于 el-select、a-select 等组件。

        :param locator: 下拉框容器的定位表达式（如 .el-select）
        :param value: 要选择的选项文本（精确匹配）
        :param timeout: 超时时间
        """
        self.log.debug_log(f"正在操作自定义下拉框:{locator}，选择选项:{value}")
        # 1. 点击下拉框容器，展开选项列表
        self.page.locator(locator).click(timeout=timeout)
        # 2. 在展开的下拉面板中，精确匹配选项文本
        #    Element UI 的下拉面板渲染在 body 层级，class 为 el-select-dropdown
        #    使用 get_by_text(exact=True) 避免 "云主机ECS" 误匹配 "大云-云主机ECS"
        option = self.page.locator(".el-select-dropdown:visible .el-select-dropdown__item").get_by_text(value, exact=True)
        option.click(timeout=timeout)
        self.log.debug_log(f"已选择选项:{value}")

    @KeyWordManager.register("scroll_to_element", "滚动到元素")
    def scroll_to_element(self, locator, timeout=3000):
        """
        滚动页面直到元素可见
        :param locator: 元素的定位表达式
        :param timeout: 超时时间
        """
        self.log.debug_log(f"正在滚动到元素:{locator}")
        self.page.locator(locator).scroll_into_view_if_needed(timeout=timeout)

    @KeyWordManager.register("highlight_element", "高亮元素")
    def highlight_element(self, locator, timeout=3000):
        """
        高亮元素（用于调试）
        :param locator: 元素的定位表达式
        :param timeout: 超时时间
        """
        self.log.debug_log(f"正在高亮元素:{locator}")
        self.page.locator(locator).highlight(timeout=timeout)
