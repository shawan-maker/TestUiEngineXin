"""
单元测试：click_element 的 loading mask 重试功能

验证场景：
1. click 成功，无 mask → 只调用一次 click
2. click 被 mask 拦截 → mask 消失 → 重试成功
3. click 被 mask 拦截 → mask 消失 → 重试仍失败 → 滚动重试成功
4. click 失败但不是 mask 问题 → 走滚动重试成功
5. force=True 跳过 mask 检测（但仍走滚动重试）
6. frame_click 被 mask 拦截 → 等待 → 重试成功
"""
import pytest
from unittest.mock import Mock, call
from UIEngine.keywords.locator_keywords import LocatorMixin
from UIEngine.keywords.iframe_keywords import IFrameMixin


def _has_call(mock_obj, substring):
    """检查 mock 的调用记录中是否包含指定子串"""
    return any(substring in str(c) for c in mock_obj.call_args_list)


class TestClickElementMaskRetry:
    """测试 click_element 的 loading mask 重试功能"""

    @pytest.fixture
    def locator_mixin(self):
        """创建 LocatorMixin 实例（传入 mock config 和 log）"""
        mock_config = Mock()
        mock_log = Mock()
        mixin = LocatorMixin(config=mock_config, log=mock_log)
        mixin.page = Mock()
        return mixin

    def _make_mask_mock(self, count=1, visible=True):
        """创建 mask mock 辅助方法"""
        mock_mask = Mock()
        mock_mask.count.return_value = count
        mock_mask.first = Mock()
        mock_mask.first.is_visible.return_value = visible
        mock_mask.first.wait_for = Mock()
        return mock_mask

    def test_click_success_without_mask(self, locator_mixin):
        """场景1：click 成功，无 mask → 只调用一次 click"""
        mock_target = Mock()
        mock_target.click = Mock()  # 成功，不抛异常
        locator_mixin.page.locator = Mock(return_value=mock_target)

        locator_mixin.click_element(locator='//button[@id="test"]', timeout=3000, force=False)

        assert mock_target.click.call_count == 1
        mock_target.click.assert_called_once_with(timeout=3000, force=False)
        # mask-retry 日志不应出现
        assert not _has_call(locator_mixin.log.debug_log, 'mask-retry')

    def test_click_blocked_by_mask_retry_success(self, locator_mixin):
        """场景2：click 被 mask 拦截 → mask 消失 → 重试成功"""
        mock_target = Mock()
        mock_target.click = Mock(side_effect=[
            Exception('intercepts pointer events'),
            None  # 重试成功
        ])

        mock_mask = self._make_mask_mock(count=1, visible=True)

        def locator_side_effect(selector):
            if 'el-loading-mask' in selector:
                return mock_mask
            return mock_target

        locator_mixin.page.locator = Mock(side_effect=locator_side_effect)

        locator_mixin.click_element(locator='//button[@id="test"]', timeout=3000, force=False)

        # click 被调用 2 次（失败 + 重试成功）
        assert mock_target.click.call_count == 2
        # mask 被检测并等待消失
        mock_mask.first.wait_for.assert_called_once_with(state='hidden', timeout=10000)
        assert _has_call(locator_mixin.log.debug_log, 'mask-retry')

    def test_click_blocked_by_mask_retry_fail_then_scroll(self, locator_mixin):
        """场景3：click 被 mask 拦截 → mask 消失 → 重试仍失败 → 滚动重试成功"""
        mock_target = Mock()
        mock_target.click = Mock(side_effect=[
            Exception('intercepts pointer events'),  # 第1次
            Exception('intercepts pointer events'),  # mask 重试
            None  # 滚动重试成功
        ])
        mock_target.scroll_into_view_if_needed = Mock()

        mock_mask = self._make_mask_mock(count=1, visible=True)

        def locator_side_effect(selector):
            if 'el-loading-mask' in selector:
                return mock_mask
            return mock_target

        locator_mixin.page.locator = Mock(side_effect=locator_side_effect)

        locator_mixin.click_element(locator='//button[@id="test"]', timeout=3000, force=False)

        # click 被调用 3 次（失败 + mask 重试 + 滚动重试）
        assert mock_target.click.call_count == 3
        mock_target.scroll_into_view_if_needed.assert_called_once()
        assert _has_call(locator_mixin.log.debug_log, '滚动')

    def test_click_fail_not_mask_then_scroll(self, locator_mixin):
        """场景4：click 失败但不是 mask 问题 → 走滚动重试成功"""
        mock_target = Mock()
        mock_target.click = Mock(side_effect=[
            Exception('Element is not clickable'),  # 非 mask 问题
            None  # 滚动重试成功
        ])
        mock_target.scroll_into_view_if_needed = Mock()

        # 无 mask
        mock_mask = self._make_mask_mock(count=0, visible=False)

        def locator_side_effect(selector):
            if 'el-loading-mask' in selector:
                return mock_mask
            return mock_target

        locator_mixin.page.locator = Mock(side_effect=locator_side_effect)

        locator_mixin.click_element(locator='//button[@id="test"]', timeout=3000, force=False)

        # click 被调用 2 次（失败 + 滚动重试成功）
        assert mock_target.click.call_count == 2
        mock_target.scroll_into_view_if_needed.assert_called_once()

    def test_click_with_force_skips_mask_retry(self, locator_mixin):
        """场景5：force=True 被 mask 拦截 → 跳过 mask 检测，走滚动重试"""
        mock_target = Mock()
        mock_target.click = Mock(side_effect=[
            Exception('intercepts pointer events'),  # 第1次
            Exception('intercepts pointer events'),  # 滚动重试也失败
        ])
        mock_target.scroll_into_view_if_needed = Mock()

        mock_mask = self._make_mask_mock(count=1, visible=True)

        def locator_side_effect(selector):
            if 'el-loading-mask' in selector:
                return mock_mask
            return mock_target

        locator_mixin.page.locator = Mock(side_effect=locator_side_effect)

        # force=True 时，click 失败后跳过 mask 检测，直接走滚动重试
        with pytest.raises(Exception, match='intercepts pointer events'):
            locator_mixin.click_element(locator='//button[@id="test"]', timeout=3000, force=True)

        # click 被调用 2 次（初始失败 + 滚动重试失败）
        assert mock_target.click.call_count == 2
        # mask 检测被跳过（force=True）
        mock_mask.first.wait_for.assert_not_called()
        # mask-retry 日志不应出现
        assert not _has_call(locator_mixin.log.debug_log, 'mask-retry')

    def test_click_all_retries_fail_raises_original(self, locator_mixin):
        """场景5b：所有重试都失败 → 抛出原始异常"""
        original_err = Exception('original error: element detached')
        mock_target = Mock()
        mock_target.click = Mock(side_effect=[
            original_err,
            Exception('different error'),  # 滚动重试的不同异常
        ])
        mock_target.scroll_into_view_if_needed = Mock()

        mock_mask = self._make_mask_mock(count=0, visible=False)

        def locator_side_effect(selector):
            if 'el-loading-mask' in selector:
                return mock_mask
            return mock_target

        locator_mixin.page.locator = Mock(side_effect=locator_side_effect)

        with pytest.raises(Exception, match='original error'):
            locator_mixin.click_element(locator='//button[@id="test"]', timeout=3000, force=False)


class TestFrameClickElementMaskRetry:
    """测试 frame_click_element 的 loading mask 重试功能"""

    @pytest.fixture
    def iframe_mixin(self):
        """创建 IFrameMixin 实例"""
        mock_config = Mock()
        mock_log = Mock()
        mixin = IFrameMixin(config=mock_config, log=mock_log)
        mixin.page = Mock()
        mixin.page.main_frame = Mock()
        return mixin

    def test_frame_click_blocked_by_mask_retry_success(self, iframe_mixin):
        """场景6：frame_click 被 mask 拦截 → 等待 → 重试成功"""
        # 模拟 iframe
        mock_frame = Mock()
        mock_frame.name = 'testFrame'
        iframe_mixin.page.frames = [iframe_mixin.page.main_frame, mock_frame]

        # iframe 内的元素：第1次失败，第2次成功
        mock_element = Mock()
        mock_element.click = Mock(side_effect=[
            Exception('intercepts pointer events'),
            None  # 重试成功
        ])
        mock_frame.locator = Mock(return_value=mock_element)

        # 主页面的 mask
        mock_mask = Mock()
        mock_mask.count.return_value = 1
        mock_mask.first = Mock()
        mock_mask.first.is_visible.return_value = True
        mock_mask.first.wait_for = Mock()

        def locator_side_effect(selector):
            if 'el-loading-mask' in selector:
                return mock_mask
            return mock_element

        iframe_mixin.page.locator = Mock(side_effect=locator_side_effect)

        iframe_mixin.frame_click_element(
            frame='xpath=//iframe[@name="testFrame"]',
            locator='//button[@id="test"]',
            button='left',
            timeout=3000
        )

        # click 被调用 2 次（失败 + 重试成功）
        assert mock_element.click.call_count == 2
        # mask 被检测并等待消失
        mock_mask.first.wait_for.assert_called_once_with(state='hidden', timeout=10000)
        assert _has_call(iframe_mixin.log.debug_log, 'mask-retry')
        assert _has_call(iframe_mixin.log.debug_log, 'mask')
