"""iframe 操作关键字

包含：iframe 内的输入、点击、悬停、拖拽等操作。
修复：frame_focus_element 链式调用断裂。
新增：switch_to_frame / switch_to_main_frame 上下文切换。
新增：frame_except_to_be_visible / frame_except_to_be_hidden 断言。
"""
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager
from playwright.sync_api import expect


class IFrameMixin(BaseBrowser):
    """iframe 相关的操作"""

    @KeyWordManager.register("frame_fill_value", "框架输入")
    def frame_fill_value(self, frame, locator, value, timeout=3000):
        """
        iframe 内输入框填值
        :param frame: iframe 定位表达式
        :param locator: 输入框的定位表达式
        :param value: 输入的值
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在元素:{locator}，输入值:{value}")
        self.page.frame_locator(frame).locator(locator).fill(value, timeout=timeout)

    @KeyWordManager.register("frame_click_element", "框架点击")
    def frame_click_element(self, frame, locator, button='left', timeout=3000):
        """
        点击 iframe 内元素（Phase 6 兼容版本）

        等待策略与 Phase 6 verify_engine._try_find_in_iframes 对齐：
        1. 轮询 page.frames 确认 iframe 内容已加载（最多 5 次，间隔 1000ms）
        2. 通过 name/id/src 多策略匹配目标帧
        3. 元素超时 5000ms（与 Phase 6 一致）
        4. 点击后 smart wait（DOM 稳定检测）

        :param frame: iframe 定位表达式
        :param locator: 元素的定位表达式
        :param button: 鼠标按键 : "left", "middle", "right"
        :param timeout: 等待元素可见的最大超时时间
        """
        import re

        self.log.debug_log(f"正在点击元素:{locator}")

        # ── Phase 6 风格的 iframe 就绪检测 ──
        max_attempts = 5
        retry_interval = 1000  # ms
        target_frame = None

        for attempt in range(max_attempts):
            # 方式1：等待 iframe 元素附加到 DOM
            try:
                self.page.wait_for_selector('iframe', state='attached', timeout=timeout)
            except Exception as wait_err:
                self.log.debug_log(f"等待 iframe 附加 DOM 超时: {str(wait_err)[:80]}")

            # 方式2：轮询 page.frames 检测动态创建的 iframe
            frames = self.page.frames
            self.log.debug_log(f"page.frames 数量: {len(frames)}")

            if len(frames) > 1:  # 找到 iframe，开始匹配
                frame_selector = frame.replace('xpath=', '') if frame.startswith('xpath=') else frame

                for f in frames:
                    if f == self.page.main_frame:
                        continue

                    # 策略1：通过 name 属性匹配
                    if '@name=' in frame_selector:
                        name_match = re.search(r'@name="([^"]+)"', frame_selector)
                        if name_match and f.name == name_match.group(1):
                            target_frame = f
                            break

                    # 策略2：通过 id 属性匹配
                    elif '@id=' in frame_selector:
                        id_match = re.search(r'@id="([^"]+)"', frame_selector)
                        if id_match:
                            try:
                                iframe_el = f.frame_element()
                                if iframe_el.get_attribute('id') == id_match.group(1):
                                    target_frame = f
                                    break
                            except Exception:
                                pass

                    # 策略3：通过 src 包含匹配
                    elif 'src*="' in frame_selector:
                        src_pattern = frame_selector.split('src*="')[1].split('"')[0]
                        if f.url and src_pattern in f.url:
                            target_frame = f
                            break

                    # 策略4：name 子串匹配（兜底）
                    elif f.name and frame_selector in f.name:
                        target_frame = f
                        break

                if target_frame:
                    self.log.debug_log(f"找到目标 iframe: {target_frame.name or 'unnamed'}")
                    break

            # 未找到，等待后重试
            if attempt < max_attempts - 1:
                self.log.debug_log(f"iframe 未就绪，{retry_interval}ms 后重试...")
                self.page.wait_for_timeout(retry_interval)

        # ── 执行点击 ──
        if target_frame:
            element = target_frame.locator(locator)
            try:
                element.click(button=button, timeout=5000)
                self.log.debug_log(f"iframe 内点击成功: {locator[:80]}")
            except Exception as click_err:
                err_msg = str(click_err)
                # 被主页面的全屏 mask 拦截 → 等待 mask 消失后重试
                if 'intercepts pointer events' in err_msg:
                    mask_handled = self._wait_for_visible_mask(timeout=10000)
                    if mask_handled:
                        element.click(button=button, timeout=5000)  # 重试
                        self.log.debug_log(f"iframe 内点击成功（mask 重试后）: {locator[:80]}")
                    else:
                        raise  # 没有 mask，抛出原始异常
                else:
                    raise
        else:
            # 回退：使用 frame_locator 链式定位（原方法）
            self.log.debug_log(f"未找到目标 frame，回退使用 frame_locator")
            self.page.frame_locator(frame).locator(locator).click(button=button, timeout=timeout)

        # ── 点击后智能等待（与 Phase 6 _smart_wait_after_action 对齐）──
        self.page.wait_for_timeout(1000)

    @KeyWordManager.register("frame_hover", "框架悬停")
    def frame_hover(self, frame, locator, timeout=3000):
        """
        悬停到 iframe 内元素上方
        :param frame: iframe 定位表达式
        :param locator: 元素定位表达式
        :param timeout: 超时时间
        """
        self.log.debug_log(f"正在悬停到元素:{locator}")
        self.page.frame_locator(frame).locator(locator).hover(timeout=timeout)

    @KeyWordManager.register("frame_focus_element", "框架聚焦")
    def frame_focus_element(self, frame, locator, timeout=3000):
        """
        聚焦 iframe 内元素（修复：原链式调用断裂）
        :param frame: iframe 定位表达式
        :param locator: 元素的定位表达式
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在聚焦元素:{locator}")
        self.page.frame_locator(frame).locator(locator).focus(timeout=timeout)

    @KeyWordManager.register("frame_select_option", "框架选择")
    def frame_select_option(self, frame, locator, value, timeout=3000):
        """
        选择 iframe 内下拉框的选项
        :param frame: iframe 定位表达式
        :param locator: 下拉框的定位表达式
        :param value: 选项的值
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在选择下拉框:{locator}，选项的值:{value}")
        self.page.frame_locator(frame).locator(locator).select_option(value, timeout=timeout)

    @KeyWordManager.register("frame_type_value", "框架输入文本")
    def frame_type_value(self, frame, locator, value, timeout=3000):
        """
        iframe 内模拟键盘输入
        :param frame: iframe 定位表达式
        :param locator: 输入框定位表达式
        :param value: 输入的文本
        :param timeout: 超时时间
        """
        self.log.debug_log(f"正在输入元素:{locator}，输入的值:{value}")
        self.page.frame_locator(frame).locator(locator).press_sequentially(value, timeout=timeout)

    @KeyWordManager.register("frame_long_click_element", "框架长按")
    def frame_long_click_element(self, frame, locator, delay=0.1):
        """
        长按 iframe 内元素
        :param frame: iframe 定位表达式
        :param locator: 元素定位
        :param delay: 按住时间（秒）
        """
        self.log.debug_log(f"正在长按元素：{locator},按住时间：{delay}")
        self.page.frame_locator(frame).locator(locator).click(delay=int(delay * 1000))

    @KeyWordManager.register("frame_drag_and_drop", "框架拖拽")
    def frame_drag_and_drop(self, frame, start_selector, end_selector, timeout=3000):
        """
        拖拽 iframe 内元素
        :param frame: iframe 定位表达式
        :param start_selector: 拖拽的元素
        :param end_selector: 拖拽到的元素
        :param timeout: 等待元素可见的最大超时时间
        """
        self.log.debug_log(f"正在拖拽元素:{start_selector}，拖拽到的元素:{end_selector}")
        s_ele = self.page.frame_locator(frame).locator(start_selector, timeout=timeout)
        e_ele = self.page.frame_locator(frame).locator(end_selector, timeout=timeout)
        s_ele.drag_to(e_ele)

    @KeyWordManager.register("switch_to_frame", "切换iframe")
    def switch_to_frame(self, frame_locator_str):
        """
        切换到指定 iframe 上下文
        后续的非 frame_ 前缀操作将在此 iframe 内执行。
        :param frame_locator_str: iframe 的定位表达式
        """
        self.log.debug_log(f"切换到iframe:{frame_locator_str}")
        self._current_frame = frame_locator_str

    @KeyWordManager.register("switch_to_main_frame", "切回主页面")
    def switch_to_main_frame(self):
        """切换回主页面，清除 iframe 上下文"""
        self.log.debug_log("切换回主页面")
        self._current_frame = None

    # ============================================================
    # iframe 内断言关键字
    # ============================================================

    @KeyWordManager.register("frame_except_to_be_visible", "框架断言可见")
    def frame_except_to_be_visible(self, frame, locator, index=1, timeout=5000):
        """
        断言 iframe 内元素可见
        :param frame: iframe 定位表达式
        :param locator: 元素的定位表达式（在 iframe 内）
        :param index: 定位到的第几个元素
        :param timeout: 等待超时时间（毫秒）
        """
        self.log.debug_log(f"正在iframe内断言元素可见:{locator}")
        if index > 1:
            expect(self.page.frame_locator(frame).locator(locator).nth(index - 1)).to_be_visible(timeout=timeout)
        else:
            expect(self.page.frame_locator(frame).locator(locator).first).to_be_visible(timeout=timeout)

    @KeyWordManager.register("frame_except_to_be_hidden", "框架断言隐藏")
    def frame_except_to_be_hidden(self, frame, locator, index=1, timeout=5000):
        """
        断言 iframe 内元素不可见
        :param frame: iframe 定位表达式
        :param locator: 元素的定位表达式（在 iframe 内）
        :param index: 定位到的第几个元素
        :param timeout: 等待超时时间（毫秒）
        """
        self.log.debug_log(f"正在iframe内断言元素隐藏:{locator}")
        if index > 1:
            expect(self.page.frame_locator(frame).locator(locator).nth(index - 1)).to_be_hidden(timeout=timeout)
        else:
            expect(self.page.frame_locator(frame).locator(locator).first).to_be_hidden(timeout=timeout)

    @KeyWordManager.register("frame_except_to_have_text", "框架断言文本")
    def frame_except_to_have_text(self, frame, locator, expect_results, index=1, timeout=5000):
        """
        断言 iframe 内元素包含指定文本
        :param frame: iframe 定位表达式
        :param locator: 元素的定位表达式（在 iframe 内）
        :param expect_results: 期望包含的文本
        :param index: 定位到的第几个元素
        :param timeout: 等待超时时间（毫秒）
        """
        self.log.debug_log(f"正在iframe内断言元素文本:{locator}，期望:{expect_results}")
        if index > 1:
            expect(self.page.frame_locator(frame).locator(locator).nth(index - 1)).to_contain_text(expect_results, timeout=timeout)
        else:
            expect(self.page.frame_locator(frame).locator(locator).first).to_contain_text(expect_results, timeout=timeout)
