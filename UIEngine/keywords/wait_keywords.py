"""等待操作关键字

包含：超时设置、强制等待、页面加载等待、网络等待、元素等待。
新增：wait_for_element_hidden（等待元素消失）、wait_for_url（等待 URL 变化）。
"""
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager


class WaitMixin(BaseBrowser):
    """等待相关的操作"""

    @KeyWordManager.register("set_default_timeout", "设置超时")
    def set_default_timeout(self, timeout=30000):
        """
        设置 page 全局默认的等待时间
        :param timeout: 超时时间（毫秒）
        """
        self.log.debug_log(f"正在设置默认等待时间：{timeout}")
        self.page.set_default_timeout(timeout)

    @KeyWordManager.register("wait_for_time", "强制等待")
    def wait_for_time(self, timeout=3000):
        """设置强制等待时间"""
        self.log.debug_log(f"正在进行强制等待，等待时间：{timeout}")
        self.page.wait_for_timeout(timeout)

    @KeyWordManager.register("wait_for_load", "等待加载")
    def wait_for_load(self, timeout=30000):
        """等待页面加载完成
        :param timeout: 超时时间（毫秒），默认 30000
        """
        self.log.debug_log(f"正在等待页面加载完成，超时: {timeout}")
        self.page.wait_for_load_state(state='load', timeout=timeout)

    @KeyWordManager.register("wait_for_network", "等待网络")
    def wait_for_network(self, timeout=30000):
        """等待网络请求完成
        :param timeout: 超时时间（毫秒），默认 30000
        """
        self.log.debug_log(f"正在等待网络请求完成，超时: {timeout}")
        self.page.wait_for_load_state(state='networkidle', timeout=timeout)

    @KeyWordManager.register("wait_for_element", "等待元素")
    def wait_for_element(self, locator, timeout=3000):
        """
        等待元素可见
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在等待元素:{locator}，可见")
        self.page.wait_for_selector(locator, timeout=timeout)

    @KeyWordManager.register("wait_for_element_hidden", "等待元素消失")
    def wait_for_element_hidden(self, locator, timeout=3000):
        """
        等待元素消失（不可见或从 DOM 中移除）
        :param locator: 元素的定位表达式
        :param timeout: 最大超时时间
        """
        self.log.debug_log(f"正在等待元素消失:{locator}")
        self.page.wait_for_selector(locator, state="hidden", timeout=timeout)

    @KeyWordManager.register("wait_for_url", "等待URL")
    def wait_for_url(self, url_pattern, timeout=30000):
        """
        等待页面 URL 匹配指定模式
        :param url_pattern: URL 匹配模式（字符串或正则）
        :param timeout: 最大超时时间
        """
        self.log.debug_log(f"正在等待URL匹配:{url_pattern}")
        self.page.wait_for_url(url_pattern, timeout=timeout)
