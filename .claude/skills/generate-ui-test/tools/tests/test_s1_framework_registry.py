"""Test S1 Framework Registry

Validates framework_registry.py data tables and query functions.
"""
import pytest
from pathlib import Path

# Import the module under test
from core import framework_registry as fw_reg


class TestDiscoverSelectors:
    """Test DISCOVER_SELECTORS data table"""

    def test_element_ui_selectors_complete(self):
        """Element UI has all required selector keys"""
        selectors = fw_reg.DISCOVER_SELECTORS.get('element-ui', {})
        required_keys = [
            'button', 'formItem', 'formItemLabel', 'inputInner',
            'selectInput', 'selectExclude', 'textareaInner',
            'dateEditor', 'cascaderInput', 'tableBodyRows',
            'tableFixedRows', 'rowButton', 'checkboxInner',
            'tableHeader', 'tableBody', 'menuItem', 'breadcrumb',
            'dropdown', 'iconSearch', 'iconDownload'
        ]
        for key in required_keys:
            assert key in selectors, f"Missing key: {key}"
            assert selectors[key], f"Empty value for key: {key}"

    def test_antd_selectors_complete(self):
        """Ant Design has all required selector keys"""
        selectors = fw_reg.DISCOVER_SELECTORS.get('ant-design', {})
        required_keys = [
            'button', 'formItem', 'formItemLabel', 'inputInner',
            'selectInput', 'selectExclude', 'textareaInner',
            'dateEditor', 'cascaderInput', 'tableBodyRows',
            'tableFixedRows', 'rowButton', 'checkboxInner',
            'tableHeader', 'tableBody', 'menuItem', 'breadcrumb',
            'dropdown', 'iconSearch', 'iconDownload'
        ]
        for key in required_keys:
            assert key in selectors, f"Missing key: {key}"
            assert selectors[key], f"Empty value for key: {key}"

    def test_element_ui_patterns(self):
        """Element UI selectors contain expected patterns"""
        selectors = fw_reg.DISCOVER_SELECTORS['element-ui']
        assert '.el-button' in selectors['button']
        assert '.el-form-item' in selectors['formItem']
        assert 'el-input' in selectors['inputInner']
        assert 'el-select' in selectors['selectInput']
        assert '.el-select' in selectors['selectExclude']  # Container exclusion selector

    def test_antd_patterns(self):
        """Ant Design selectors contain expected patterns"""
        selectors = fw_reg.DISCOVER_SELECTORS['ant-design']
        assert '.ant-btn' in selectors['button']
        assert '.ant-form-item' in selectors['formItem']
        assert 'ant-input' in selectors['inputInner']
        assert 'ant-select' in selectors['selectInput']
        assert '.ant-select' in selectors['selectExclude']  # Container exclusion selector


class TestContainerXPathMap:
    """Test CONTAINER_XPATH_MAP data table"""

    def test_element_ui_containers(self):
        """Element UI container XPaths"""
        containers = fw_reg.CONTAINER_XPATH_MAP.get('element-ui', {})
        assert 'drawer' in containers
        assert 'dialog' in containers
        assert 'message-box' in containers
        assert 'el-drawer' in containers['drawer']
        assert 'el-dialog' in containers['dialog']
        assert 'el-message-box' in containers['message-box']

    def test_antd_containers(self):
        """Ant Design container XPaths"""
        containers = fw_reg.CONTAINER_XPATH_MAP.get('ant-design', {})
        assert 'drawer' in containers
        assert 'dialog' in containers
        assert 'el-drawer' not in containers['drawer']
        assert 'ant-drawer' in containers['drawer']
        assert 'ant-modal' in containers['dialog']


class TestHiddenFilters:
    """Test HIDDEN_FILTERS data table"""

    def test_element_ui_hidden_filter(self):
        """Element UI hidden filter pattern"""
        filter_expr = fw_reg.HIDDEN_FILTERS.get('element-ui', '')
        assert 'is-hidden' in filter_expr
        assert 'display: none' in filter_expr

    def test_antd_hidden_filter(self):
        """Ant Design hidden filter pattern"""
        filter_expr = fw_reg.HIDDEN_FILTERS.get('ant-design', '')
        assert 'hidden' in filter_expr
        assert 'display: none' in filter_expr


class TestDisabledFilters:
    """Test DISABLED_FILTERS data table"""

    def test_element_ui_disabled_filter(self):
        """Element UI disabled filter pattern"""
        filter_expr = fw_reg.DISABLED_FILTERS.get('element-ui', '')
        assert 'disabled' in filter_expr.lower()

    def test_antd_disabled_filter(self):
        """Ant Design disabled filter pattern"""
        filter_expr = fw_reg.DISABLED_FILTERS.get('ant-design', '')
        assert 'disabled' in filter_expr.lower()


class TestCheckboxHardcoded:
    """Test CHECKBOX_HARDCODED data table"""

    def test_element_ui_checkbox(self):
        """Element UI checkbox fallback XPath"""
        xpath = fw_reg.CHECKBOX_HARDCODED.get('element-ui', '')
        assert xpath
        assert 'checkbox' in xpath.lower()
        assert 'el-checkbox' in xpath

    def test_antd_checkbox(self):
        """Ant Design checkbox fallback XPath"""
        xpath = fw_reg.CHECKBOX_HARDCODED.get('ant-design', '')
        assert xpath
        assert 'checkbox' in xpath.lower()
        assert 'ant-checkbox' in xpath


class TestGeneratorLocators:
    """Test GENERATOR_LOCATORS data table"""

    def test_dropdown_menu_templates(self):
        """dropdown-menu locator templates"""
        locators = fw_reg.GENERATOR_LOCATORS.get('dropdown-menu', {})
        assert 'element-ui' in locators
        assert 'ant-design' in locators
        assert '{label}' in locators['element-ui']
        assert '{label}' in locators['ant-design']

    def test_more_button_templates(self):
        """more-button locator templates"""
        locators = fw_reg.GENERATOR_LOCATORS.get('more-button', {})
        assert 'element-ui' in locators
        assert 'ant-design' in locators

    def test_date_picker_month_templates(self):
        """date-picker-month locator templates"""
        locators = fw_reg.GENERATOR_LOCATORS.get('date-picker-month', {})
        assert 'element-ui' in locators
        assert 'ant-design' in locators
        assert '{month0}' in locators['element-ui']
        assert '{year}' in locators['ant-design']

    def test_option_xpath_templates(self):
        """option-xpath locator templates"""
        locators = fw_reg.GENERATOR_LOCATORS.get('option-xpath', {})
        assert 'element-ui' in locators
        assert 'ant-design' in locators
        assert '{option_text}' in locators['element-ui']
        assert '{option_text}' in locators['ant-design']

    def test_first_option_xpath_templates(self):
        """first-option-xpath locator templates"""
        locators = fw_reg.GENERATOR_LOCATORS.get('first-option-xpath', {})
        assert 'element-ui' in locators
        assert 'ant-design' in locators


class TestQueryFunctions:
    """Test query functions"""

    def test_get_discover_selector(self):
        """get_discover_selector returns correct selectors"""
        # Element UI
        button = fw_reg.get_discover_selector('element-ui', 'button')
        assert '.el-button' in button

        # Ant Design
        button = fw_reg.get_discover_selector('ant-design', 'button')
        assert '.ant-btn' in button

        # Default fallback
        button = fw_reg.get_discover_selector(None, 'button')
        assert button  # Should return something

        # Unknown framework
        button = fw_reg.get_discover_selector('unknown', 'button')
        assert button  # Should fallback to element-ui

    def test_get_discover_selectors_json(self):
        """get_discover_selectors_json returns valid JSON"""
        import json
        json_str = fw_reg.get_discover_selectors_json('element-ui')
        data = json.loads(json_str)
        assert isinstance(data, dict)
        assert 'button' in data

        json_str = fw_reg.get_discover_selectors_json('ant-design')
        data = json.loads(json_str)
        assert isinstance(data, dict)
        assert 'button' in data

    def test_get_container_xpath(self):
        """get_container_xpath returns correct XPaths"""
        # Element UI
        drawer = fw_reg.get_container_xpath('drawer', 'element-ui')
        assert 'el-drawer' in drawer

        # Ant Design
        drawer = fw_reg.get_container_xpath('drawer', 'ant-design')
        assert 'ant-drawer' in drawer

        # Unknown container type
        unknown = fw_reg.get_container_xpath('unknown', 'element-ui')
        assert unknown == ''

    def test_get_hidden_filter(self):
        """get_hidden_filter returns correct filters"""
        # Element UI
        filter_expr = fw_reg.get_hidden_filter('element-ui')
        assert 'is-hidden' in filter_expr

        # Ant Design
        filter_expr = fw_reg.get_hidden_filter('ant-design')
        assert 'hidden' in filter_expr

        # Default
        filter_expr = fw_reg.get_hidden_filter(None)
        assert filter_expr  # Should return something

    def test_get_disabled_filter(self):
        """get_disabled_filter returns correct filters"""
        # Element UI
        filter_expr = fw_reg.get_disabled_filter('element-ui')
        assert 'disabled' in filter_expr.lower()

        # Ant Design
        filter_expr = fw_reg.get_disabled_filter('ant-design')
        assert 'disabled' in filter_expr.lower()

    def test_get_checkbox_hardcoded(self):
        """get_checkbox_hardcoded returns correct XPaths"""
        # Element UI
        xpath = fw_reg.get_checkbox_hardcoded('element-ui')
        assert 'el-checkbox' in xpath

        # Ant Design
        xpath = fw_reg.get_checkbox_hardcoded('ant-design')
        assert 'ant-checkbox' in xpath

    def test_get_framework_locator(self):
        """get_framework_locator formats templates correctly"""
        # dropdown-menu with label
        xpath = fw_reg.get_framework_locator('dropdown-menu', 'element-ui', label='确认')
        assert '确认' in xpath
        assert 'el-dropdown__item' in xpath

        xpath = fw_reg.get_framework_locator('dropdown-menu', 'ant-design', label='删除')
        assert '删除' in xpath
        assert 'ant-dropdown-menu-item' in xpath

        # date-picker-month with year/month
        xpath = fw_reg.get_framework_locator('date-picker-month', 'element-ui', month=8)
        assert '7' in xpath  # month0 = month - 1 = 7

        xpath = fw_reg.get_framework_locator('date-picker-month', 'ant-design', year=2026, month=8)
        assert '2026' in xpath
        assert '08' in xpath

        # option-xpath with option_text
        xpath = fw_reg.get_framework_locator('option-xpath', 'element-ui', option_text='选项A')
        assert '选项A' in xpath

        # Unknown key
        xpath = fw_reg.get_framework_locator('unknown-key', 'element-ui')
        assert xpath == ''

    def test_get_js_break_classes(self):
        """get_js_break_classes returns class lists"""
        # Element UI
        classes = fw_reg.get_js_break_classes('element-ui')
        assert isinstance(classes, list)
        assert len(classes) > 0
        assert any('el-' in c for c in classes)

        # Ant Design
        classes = fw_reg.get_js_break_classes('ant-design')
        assert isinstance(classes, list)
        assert len(classes) > 0

    def test_get_js_container_classes(self):
        """get_js_container_classes returns class lists"""
        # Element UI
        classes = fw_reg.get_js_container_classes('element-ui')
        assert isinstance(classes, list)
        assert len(classes) > 0

        # Ant Design
        classes = fw_reg.get_js_container_classes('ant-design')
        assert isinstance(classes, list)
        assert len(classes) > 0

    def test_get_prompt_templates(self):
        """get_prompt_templates returns template dicts"""
        # Element UI
        templates = fw_reg.get_prompt_templates('element-ui')
        assert isinstance(templates, dict)
        assert 'prefix_hints' in templates

        # Ant Design
        templates = fw_reg.get_prompt_templates('ant-design')
        assert isinstance(templates, dict)
        assert 'prefix_hints' in templates


class TestContainerMarkers:
    """Test CONTAINER_MARKERS_ALL"""

    def test_markers_complete(self):
        """CONTAINER_MARKERS_ALL includes both frameworks (group markers with underscores)"""
        markers = fw_reg.CONTAINER_MARKERS_ALL
        assert isinstance(markers, tuple)
        # Element UI group markers
        assert '_el-dialog_' in markers
        assert '_el-drawer_' in markers
        assert '_el-message-box_' in markers
        # Ant Design group markers
        assert '_ant-modal_' in markers
        assert '_ant-drawer_' in markers
        # Generic group markers (backward compatibility)
        assert '_drawer_' in markers
        assert '_dialog_' in markers


class TestRegexPatterns:
    """Test regex patterns"""

    def test_all_container_prefixes_re_pattern(self):
        """ALL_CONTAINER_PREFIXES_RE_PATTERN matches container XPath prefixes"""
        import re
        pattern = re.compile(fw_reg.ALL_CONTAINER_PREFIXES_RE_PATTERN)

        # Should match Element UI container XPaths
        assert pattern.search("//div[contains(@class,'el-dialog')]")
        assert pattern.search("//div[contains(@class,'el-drawer')]")
        assert pattern.search("//div[contains(@class,'el-message-box')]")

        # Should match Ant Design container XPaths
        assert pattern.search("//div[contains(@class,'ant-modal')]")
        assert pattern.search("//div[contains(@class,'ant-drawer')]")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
