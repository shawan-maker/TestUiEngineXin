"""
测试 iframe_keywords.IFrameMixin.frame_click_element 的 Phase 6 兼容性增强

覆盖场景:
1. iframe 立即可用时的正常点击
2. iframe 延迟加载时的轮询等待
3. iframe 未找到时的回退机制
4. 不同帧匹配策略（name/id/src）
5. 点击后的智能等待
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from UIEngine.keywords.iframe_keywords import IFrameMixin


class TestFrameClickElement:
    """测试 frame_click_element 方法的 Phase 6 兼容性"""

    @pytest.fixture
    def iframe_mixin(self):
        """创建 IFrameMixin 实例（传入 mock config 和 log）"""
        mock_config = Mock()
        mock_log = Mock()
        mixin = IFrameMixin(config=mock_config, log=mock_log)
        mixin.page = Mock()
        return mixin

    def test_frame_click_immediate_success(self, iframe_mixin):
        """测试场景1: iframe 立即可用，点击成功"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "testFrame"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()

        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="testFrame"]',
            locator='xpath=//button[@id="submit"]',
            button='left',
            timeout=3000
        )

        mock_target_frame.locator.assert_called_once_with('xpath=//button[@id="submit"]')
        mock_element.click.assert_called_once_with(button='left', timeout=5000)
        iframe_mixin.page.wait_for_timeout.assert_called_once_with(1000)
        iframe_mixin.log.debug_log.assert_any_call("找到目标 iframe: testFrame")
        iframe_mixin.log.debug_log.assert_any_call('iframe 内点击成功: xpath=//button[@id="submit"]')

    def test_frame_click_delayed_iframe(self, iframe_mixin):
        """测试场景2: iframe 延迟加载，轮询后成功"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "delayedFrame"
        mock_element = Mock()

        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()

        call_count = [0]

        def get_frames():
            call_count[0] += 1
            if call_count[0] < 3:
                return [mock_main_frame]
            else:
                return [mock_main_frame, mock_target_frame]

        type(iframe_mixin.page).frames = property(lambda self: get_frames())

        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="delayedFrame"]',
            locator='xpath=//button[@id="confirm"]',
            timeout=3000
        )

        assert iframe_mixin.page.wait_for_timeout.call_count == 3  # 重试了2次 + 点击后1次
        mock_target_frame.locator.assert_called_once()
        mock_element.click.assert_called_once_with(button='left', timeout=5000)
        iframe_mixin.log.debug_log.assert_any_call("iframe 未就绪，1000ms 后重试...")
        iframe_mixin.log.debug_log.assert_any_call("找到目标 iframe: delayedFrame")

    def test_frame_click_fallback_to_frame_locator(self, iframe_mixin):
        """测试场景3: 轮询超时后回退到 frame_locator"""
        mock_main_frame = Mock()
        mock_locator = Mock()
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        iframe_mixin.page.frame_locator = Mock(return_value=mock_locator)
        mock_locator.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@id="nonExistent"]',
            locator='xpath=//button[@id="submit"]',
            timeout=3000
        )

        iframe_mixin.page.frame_locator.assert_called_once_with('xpath=//iframe[@id="nonExistent"]')
        mock_locator.locator.assert_called_once_with('xpath=//button[@id="submit"]')
        mock_element.click.assert_called_once_with(button='left', timeout=3000)  # 使用原始 timeout
        iframe_mixin.log.debug_log.assert_any_call("未找到目标 frame，回退使用 frame_locator")
        assert iframe_mixin.page.wait_for_timeout.call_count == 5  # 重试了4次 + 点击后1次

    def test_frame_match_by_id(self, iframe_mixin):
        """测试场景4: 通过 id 属性匹配帧"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = None
        mock_iframe_element = Mock()
        mock_iframe_element.get_attribute = Mock(return_value="myIframe")
        mock_target_frame.frame_element = Mock(return_value=mock_iframe_element)
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@id="myIframe"]',
            locator='xpath=//input[@name="username"]',
            timeout=3000
        )

        mock_target_frame.frame_element.assert_called_once()
        mock_iframe_element.get_attribute.assert_called_with('id')
        iframe_mixin.log.debug_log.assert_any_call("找到目标 iframe: unnamed")

    def test_frame_match_by_src(self, iframe_mixin):
        """测试场景5: 通过 src 包含匹配帧"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = None
        mock_target_frame.url = "https://example.com/iframe/content.html"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[src*="example.com"]',
            locator='xpath=//a[@class="link"]',
            timeout=3000
        )

        mock_target_frame.locator.assert_called_once()
        iframe_mixin.log.debug_log.assert_any_call("找到目标 iframe: unnamed")

    def test_frame_click_with_right_button(self, iframe_mixin):
        """测试场景6: 使用右键点击"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "contextMenu"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="contextMenu"]',
            locator='xpath=//div[@id="target"]',
            button='right',
            timeout=3000
        )

        mock_element.click.assert_called_once_with(button='right', timeout=5000)

    def test_frame_match_by_name_substring(self, iframe_mixin):
        """测试场景7: 通过 name 子串匹配（兜底策略）"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "myIframe_123"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='myIframe',
            locator='xpath=//button',
            timeout=3000
        )

        iframe_mixin.log.debug_log.assert_any_call("找到目标 iframe: myIframe_123")

    def test_frame_click_logs_page_frames_count(self, iframe_mixin):
        """测试场景8: 验证日志记录 page.frames 数量"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "testFrame"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="testFrame"]',
            locator='xpath=//button',
            timeout=3000
        )

        iframe_mixin.log.debug_log.assert_any_call("page.frames 数量: 2")

    def test_frame_click_with_xpath_prefix_stripped(self, iframe_mixin):
        """测试场景9: xpath= 前缀被正确剥离"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "myFrame"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock()
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="myFrame"]',
            locator='xpath=//button',
            timeout=3000
        )

        iframe_mixin.log.debug_log.assert_any_call("找到目标 iframe: myFrame")

    def test_frame_click_timeout_exception_handling(self, iframe_mixin):
        """测试场景10: wait_for_selector 超时异常处理"""
        mock_main_frame = Mock()
        mock_target_frame = Mock()
        mock_target_frame.name = "testFrame"
        mock_element = Mock()

        iframe_mixin.page.frames = [mock_main_frame, mock_target_frame]
        iframe_mixin.page.main_frame = mock_main_frame
        iframe_mixin.page.wait_for_selector = Mock(side_effect=Exception("Timeout exceeded"))
        iframe_mixin.page.wait_for_timeout = Mock()
        mock_target_frame.locator = Mock(return_value=mock_element)
        mock_element.click = Mock()

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="testFrame"]',
            locator='xpath=//button',
            timeout=3000
        )

        iframe_mixin.log.debug_log.assert_any_call("等待 iframe 附加 DOM 超时: Timeout exceeded")
        mock_element.click.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
