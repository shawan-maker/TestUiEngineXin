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

    @KeyWordManager.register("mouse_wheel", "鼠标滚轮")
    def mouse_wheel(self, delta_x=0, delta_y=300, times=1, delay=200, locator=None):
        """
        模拟鼠标滚轮滚动（用于触发虚拟滚动）
        :param delta_x: 水平滚动量（正数向右，负数向左）
        :param delta_y: 垂直滚动量（正数向下，负数向上）
        :param times: 滚动次数
        :param delay: 每次滚动间隔时间（毫秒）
        :param locator: 可选，滚动前先移动光标到该元素（确保滚轮事件命中正确容器）
        """
        import time
        self.log.debug_log(f"正在模拟鼠标滚轮：delta_x={delta_x}, delta_y={delta_y}, times={times}, delay={delay}ms"
                          + (f", locator={locator}" if locator else ""))
        if locator:
            loc = self.page.locator(locator).first
            self.log.debug_log(f"[mouse_wheel] 准备 hover 到: {locator}")
            try:
                loc.hover(timeout=3000)
                # 获取 hover 后的元素信息
                info = loc.evaluate("""(el) => ({
                    tag: el.tagName,
                    class: el.className,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    scrollTop: el.scrollTop,
                    textContent: el.textContent.substring(0, 200),
                    bodyHasC5k: document.body.innerText.includes('c5k'),
                    wrapperCount: document.querySelectorAll('.el-table__body-wrapper').length
                })""")
                self.log.debug_log(f"[mouse_wheel] hover 成功: {info}")
            except Exception as e:
                self.log.debug_log(f"[mouse_wheel] hover 失败: {e}")
        for i in range(times):
            self.page.mouse.wheel(delta_x, delta_y)
            if i < times - 1:
                time.sleep(delay / 1000.0)

        if locator:
            # 滚动后检查 scrollTop 变化
            try:
                info_after = loc.evaluate("""(el) => ({
                    scrollTop: el.scrollTop,
                    hasC5k: document.body.innerText.includes('c5k.large.2'),
                    bodyHasC5k: document.body.innerText.includes('c5k'),
                    c5kVariants: document.body.innerText.match(/c5k\\S+/g) || []
                })""")
                self.log.debug_log(f"[mouse_wheel] 滚动后: {info_after}")
            except:
                pass
