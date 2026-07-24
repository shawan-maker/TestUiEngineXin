"""鼠标键盘操作关键字

包含：鼠标点击/移动/按下/抬起、键盘按键/输入。
新增：long_click（长按）、right_click（右键）。
"""
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager


class MouseMixin(BaseBrowser):
    """鼠标键盘相关的操作"""

    @KeyWordManager.register("mouse_click", "鼠标点击")
    def mouse_click(self, x, y, button='left', count=1):
        """
        模拟鼠标点击
        :param x: x 轴坐标
        :param y: y 轴坐标
        :param button: 鼠标按键 : "left", "middle", "right"
        :param count: 点击次数
        """
        self.log.debug_log(f"正在模拟鼠标点击：({x}, {y})")
        self.page.mouse.click(x, y, button=button, count=count)

    @KeyWordManager.register("move_mouse", "移动鼠标")
    def move_mouse(self, x, y):
        """模拟鼠标移动"""
        self.log.debug_log(f"正在模拟鼠标移动：({x}, {y})")
        self.page.mouse.move(x, y)

    @KeyWordManager.register("mouse_down", "鼠标按下")
    def mouse_down(self, button='left'):
        """模拟鼠标按下"""
        self.log.debug_log(f"正在模拟鼠标按下：{button}")
        self.page.mouse.down(button=button)

    @KeyWordManager.register("mouse_up", "鼠标抬起")
    def mouse_up(self, button='left'):
        """模拟鼠标抬起"""
        self.log.debug_log(f"正在模拟鼠标抬起：{button}")
        self.page.mouse.up(button=button)

    @KeyWordManager.register("press_key", "按键")
    def press_key(self, key):
        """模拟键盘按键"""
        self.log.debug_log(f"正在模拟键盘按键：{key}")
        self.page.keyboard.press(key)

    @KeyWordManager.register("press_type", "键盘输入")
    def press_type(self, keys):
        """模拟键盘输入文本"""
        self.log.debug_log(f"正在模拟键盘输入：{keys}")
        self.page.keyboard.type(keys)

    @KeyWordManager.register("long_click", "长按")
    def long_click(self, locator, delay=500, timeout=3000):
        """
        长按元素
        :param locator: 元素定位表达式
        :param delay: 按住时间（毫秒）
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在长按元素:{locator}，延迟:{delay}ms")
        self.page.locator(locator).click(delay=delay, timeout=timeout)

    @KeyWordManager.register("right_click", "右键点击")
    def right_click(self, locator, timeout=3000):
        """
        右键点击元素
        :param locator: 元素定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在右键点击元素:{locator}")
        self.page.locator(locator).click(button="right", timeout=timeout)
