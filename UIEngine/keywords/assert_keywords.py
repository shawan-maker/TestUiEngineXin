"""断言关键字

封装 Playwright expect() API，支持正则匹配和正向/反向断言。
"""
import re
import time
from playwright.sync_api import expect
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager


class AssertMixin(BaseBrowser):
    """断言相关的方法封装"""

    @KeyWordManager.register("assert_page_title", "断言标题")
    def assert_page_title(self, expect_results, is_equal=1):
        """
        断言页面的标题
        :param expect_results: 期望结果
        :param is_equal: 1=相等，0=不相等
        """
        if is_equal:
            expect(self.page).to_have_title(re.compile(expect_results))
        else:
            expect(self.page).not_to_have_title(re.compile(expect_results))

    @KeyWordManager.register("assert_page_url", "断言URL")
    def assert_page_url(self, expect_results, is_equal=1):
        """
        断言页面的 URL 地址
        :param expect_results: 期望结果
        :param is_equal: 1=相等，0=不相等
        """
        if is_equal:
            expect(self.page).to_have_url(re.compile(expect_results))
        else:
            expect(self.page).not_to_have_url(re.compile(expect_results))

    @KeyWordManager.register("except_to_have_value", "断言有值")
    def except_to_have_value(self, locator, expect_results, is_equal=1):
        """
        断言元素的 value 属性值
        :param locator: 元素定位表达式
        :param expect_results: 期望值
        :param is_equal: 1=相等，0=不相等
        """
        if is_equal:
            expect(self.page.locator(locator)).to_have_value(re.compile(expect_results))
        else:
            expect(self.page.locator(locator)).not_to_have_value(re.compile(expect_results))

    @KeyWordManager.register("except_to_have_text", "断言有文本")
    def except_to_have_text(self, locator, expect_results, is_equal=1):
        """
        断言元素的文本
        :param locator: 元素定位表达式
        :param expect_results: 期望文本
        :param is_equal: 1=相等，0=不相等
        """
        if is_equal:
            expect(self.page.locator(locator)).to_have_text(re.compile(expect_results))
        else:
            expect(self.page.locator(locator)).not_to_have_text(expect_results)

    @KeyWordManager.register("except_to_have_attribute", "断言有属性")
    def except_to_have_attribute(self, locator, name, value, is_equal=1):
        """
        断言元素的属性值
        :param locator: 定位表达式
        :param name: 属性名称
        :param value: 属性值
        :param is_equal: 1=相等，0=不相等
        """
        if is_equal:
            expect(self.page.locator(locator)).to_have_attribute(name, value)
        else:
            expect(self.page.locator(locator)).not_to_have_attribute(name, value)

    @KeyWordManager.register("except_to_be_visible", "断言可见")
    def except_to_be_visible(self, locator, index=1):
        """
        断言元素是否可见
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_visible()
        else:
            expect(self.page.locator(locator).first).to_be_visible()

    @KeyWordManager.register("except_to_be_hidden", "断言隐藏")
    def except_to_be_hidden(self, locator, index=1):
        """
        断言元素不可见
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_hidden()
        else:
            expect(self.page.locator(locator).first).to_be_hidden()

    @KeyWordManager.register("except_to_be_enabled", "断言可用")
    def except_to_be_enabled(self, locator, index=1):
        """
        断言元素是否可用
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_enabled()
        else:
            expect(self.page.locator(locator).first).to_be_enabled()

    @KeyWordManager.register("except_to_be_disabled", "断言不可用")
    def except_to_be_disabled(self, locator, index=1):
        """
        断言元素是否不可用
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_disabled()
        else:
            expect(self.page.locator(locator).first).to_be_disabled()

    @KeyWordManager.register("except_to_be_checked", "断言选中")
    def except_to_be_checked(self, locator, index=1):
        """
        断言元素是否被选中
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_checked()
        else:
            expect(self.page.locator(locator).first).to_be_checked()

    @KeyWordManager.register("except_to_be_empty", "断言为空")
    def except_to_be_empty(self, locator, index=1):
        """
        断言元素是否为空
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_empty()
        else:
            expect(self.page.locator(locator).first).to_be_empty()

    @KeyWordManager.register("except_to_be_editable", "断言可编辑")
    def except_to_be_editable(self, locator, index=1):
        """
        断言元素是否可编辑
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_editable()
        else:
            expect(self.page.locator(locator).first).to_be_editable()

    @KeyWordManager.register("except_to_be_focused", "断言聚焦")
    def except_to_be_focused(self, locator, index=1):
        """
        断言元素是否获取焦点
        :param locator: 元素定位表达式
        :param index: 定位到的第几个元素
        """
        if index > 1:
            expect(self.page.locator(locator).nth(index - 1)).to_be_focused()
        else:
            expect(self.page.locator(locator).first).to_be_focused()

    @KeyWordManager.register("except_element_count", "断言元素数量")
    def except_element_count(self, locator, min_count=1, timeout=10000):
        """断言匹配定位器的元素数量 >= min_count

        Playwright to_have_count 仅支持精确等于，因此使用轮询+assert 实现 >= 断言。
        轮询间隔 500ms，超时后 assert 失败。

        :param locator: 元素定位表达式
        :param min_count: 最少元素数量（默认 1）
        :param timeout: 超时时间（毫秒，默认 10000）
        """
        end_time = time.time() + timeout / 1000
        while time.time() < end_time:
            actual = self.page.locator(locator).count()
            if actual >= min_count:
                self.log.debug_log(
                    f"元素数量断言通过: {actual} >= {min_count}")
                return
            self.page.wait_for_timeout(500)

        actual = self.page.locator(locator).count()
        assert actual >= min_count, (
            f"元素数量不足: 期望>={min_count}, 实际={actual}, locator={locator}")
