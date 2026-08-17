"""Test click type [1] wrapping protection

Validates that click-type elements (button, table-action-button, detail-link)
always get [1] wrapping to prevent strict mode violations at runtime.

Three code paths are tested:
1. _verify_count_or_first() — fallback verification function
2. verify_locator_candidates() — main verification path
3. Edge cases: already-wrapped, non-click types, None elem_type
"""
import pytest
from unittest.mock import Mock


class TestVerifyCountOrFirstClickWrap:
    """_verify_count_or_first: click types get [1] wrapping when count==1"""

    def _call(self, page, locator, elem_type=None):
        from verification.verify_engine import _verify_count_or_first
        return _verify_count_or_first(page, locator, elem_type=elem_type)

    def _mock_page(self, count):
        page = Mock()
        page.locator.return_value.count.return_value = count
        return page

    # --- click types: count==1 → [1] wrapping ---

    def test_button_count1_gets_wrapped(self):
        page = self._mock_page(1)
        result = self._call(page, "xpath=//button[contains(.,'confirm')]", elem_type='button')
        assert result is not None
        assert '[1]' in result

    def test_table_action_button_count1_gets_wrapped(self):
        page = self._mock_page(1)
        result = self._call(page, "xpath=//span[contains(.,'edit')]", elem_type='table-action-button')
        assert result is not None
        assert '[1]' in result

    def test_detail_link_count1_gets_wrapped(self):
        page = self._mock_page(1)
        result = self._call(page, "xpath=//a[contains(.,'detail')]", elem_type='detail-link')
        assert result is not None
        assert '[1]' in result

    # --- non-click types: count==1 → NO wrapping ---

    def test_input_generic_count1_no_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=//input[@class='el-input__inner']"
        result = self._call(page, locator, elem_type='input-generic')
        assert result is not None
        # No wrapping for non-click types
        assert '[1]' not in result

    def test_textarea_generic_count1_no_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=//textarea[contains(@class,'el-textarea')]"
        result = self._call(page, locator, elem_type='textarea-generic')
        assert result is not None
        assert '[1]' not in result

    def test_el_select_count1_no_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=//div[contains(@class,'el-select')]"
        result = self._call(page, locator, elem_type='el-select')
        assert result is not None
        assert '[1]' not in result

    def test_checkbox_count1_no_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=//label[contains(@class,'el-checkbox')]"
        result = self._call(page, locator, elem_type='checkbox')
        assert result is not None
        assert '[1]' not in result

    # --- already wrapped: no double wrapping ---

    def test_already_wrapped_no_double_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=(//button[contains(.,'confirm')])[1]"
        result = self._call(page, locator, elem_type='button')
        assert result is not None
        # Should not have double wrapping like ((xpath)[1])[1]
        assert '((' not in result

    def test_already_wrapped_last_no_double_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=(//button[contains(.,'confirm')])[last()]"
        result = self._call(page, locator, elem_type='button')
        assert result is not None
        # [last()] is a valid positional wrap, should not be re-wrapped
        assert '((' not in result

    def test_already_wrapped_index2_no_double_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=(//button[contains(.,'confirm')])[2]"
        result = self._call(page, locator, elem_type='button')
        assert result is not None
        assert '((' not in result

    # --- None elem_type ---

    def test_none_elem_type_count1_no_wrap(self):
        page = self._mock_page(1)
        locator = "xpath=//button[contains(.,'confirm')]"
        result = self._call(page, locator, elem_type=None)
        assert result is not None
        assert '[1]' not in result

    def test_no_elem_type_arg_count1_no_wrap(self):
        """Backward compat: calling without elem_type should work"""
        page = self._mock_page(1)
        locator = "xpath=//button[contains(.,'confirm')]"
        result = self._call(page, locator)
        assert result is not None
        assert '[1]' not in result

    # --- count==0: returns None for all types ---

    def test_count0_returns_none_button(self):
        page = self._mock_page(0)
        result = self._call(page, "xpath=//button[contains(.,'confirm')]", elem_type='button')
        assert result is None

    def test_count0_returns_none_input(self):
        page = self._mock_page(0)
        result = self._call(page, "xpath=//input[@name='test']", elem_type='input-generic')
        assert result is None

    def test_empty_locator_returns_none(self):
        page = self._mock_page(1)
        assert self._call(page, '', elem_type='button') is None
        assert self._call(page, None, elem_type='button') is None

    # --- count>1: narrowing for all types ---

    def test_count_gt1_button_gets_narrowed(self):
        page = Mock()
        # First call: count=3 (original), second call: count=1 (narrowed)
        loc_mock = Mock()
        loc_mock.count.side_effect = [3, 1]
        page.locator.return_value = loc_mock
        result = self._call(page, "xpath=//button[contains(.,'confirm')]", elem_type='button')
        assert result is not None
        assert '[1]' in result

    def test_count_gt1_input_gets_narrowed(self):
        """count>1 narrowing also applies to non-click types"""
        page = Mock()
        loc_mock = Mock()
        loc_mock.count.side_effect = [2, 1]
        page.locator.return_value = loc_mock
        result = self._call(page, "xpath=//input[@class='el-input__inner']", elem_type='input-generic')
        assert result is not None
        assert '[1]' in result


class TestVerifyLocatorCandidatesClickWrap:
    """verify_locator_candidates: click types get [1] wrapping in count==1 branch"""

    def _call(self, page, candidates, **kwargs):
        from verification.verify_engine import verify_locator_candidates
        return verify_locator_candidates(page, candidates, **kwargs)

    def _mock_page(self, count):
        page = Mock()
        page.locator.return_value.count.return_value = count
        return page

    def test_button_count1_gets_wrapped(self):
        page = self._mock_page(1)
        candidates = ["//button[contains(.,'confirm')]"]
        result = self._call(page, candidates, elem_type='button')
        assert result is not None
        # result[0] is the verified locator
        assert '[1]' in result[0]

    def test_table_action_button_count1_gets_wrapped(self):
        page = self._mock_page(1)
        candidates = ["//span[contains(.,'edit')]"]
        result = self._call(page, candidates, elem_type='table-action-button')
        assert result is not None
        assert '[1]' in result[0]

    def test_detail_link_count1_gets_wrapped(self):
        page = self._mock_page(1)
        candidates = ["//a[contains(.,'detail')]"]
        result = self._call(page, candidates, elem_type='detail-link')
        assert result is not None
        assert '[1]' in result[0]

    def test_input_generic_count1_no_wrap(self):
        page = self._mock_page(1)
        candidates = ["//input[@class='el-input__inner']"]
        result = self._call(page, candidates, elem_type='input-generic')
        assert result is not None
        assert '[1]' not in result[0]

    def test_el_select_count1_no_wrap(self):
        page = self._mock_page(1)
        candidates = ["//div[contains(@class,'el-select')]"]
        result = self._call(page, candidates, elem_type='el-select')
        assert result is not None
        assert '[1]' not in result[0]

    def test_already_wrapped_candidate_no_double_wrap(self):
        page = self._mock_page(1)
        candidates = ["(//button[contains(.,'confirm')])[1]"]
        result = self._call(page, candidates, elem_type='button')
        assert result is not None
        assert '((' not in result[0]

    def test_none_elem_type_no_wrap(self):
        page = self._mock_page(1)
        candidates = ["//button[contains(.,'confirm')]"]
        result = self._call(page, candidates, elem_type=None)
        assert result is not None
        assert '[1]' not in result[0]

    def test_count0_returns_none(self):
        page = self._mock_page(0)
        candidates = ["//button[contains(.,'confirm')]"]
        result = self._call(page, candidates, elem_type='button')
        assert result[0] is None

    def test_multiple_candidates_first_match_wrapped(self):
        """When first candidate matches count=1, it gets [1] wrapped for click types"""
        page = self._mock_page(1)
        candidates = [
            "//button[contains(.,'confirm') and contains(.,'ok')]",
            "//button[contains(.,'confirm')]",
        ]
        result = self._call(page, candidates, elem_type='button')
        assert result is not None
        assert '[1]' in result[0]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
