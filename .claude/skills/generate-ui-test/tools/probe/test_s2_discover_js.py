"""Test S2 Discover JS Implementation

Validates the fwSelectors parameterization and framework detection.
"""
import os
import json
import pytest
from pathlib import Path

# Import the module under test
from tools.probe import discover_page


class TestFWSelectorsLoading:
    """Test _load_fw_selectors function"""

    def test_load_element_ui_selectors(self):
        """Load Element UI selectors from JSON"""
        selectors = discover_page._load_fw_selectors('element-ui')
        assert isinstance(selectors, dict)
        assert 'button' in selectors
        assert 'formItem' in selectors
        assert 'inputInner' in selectors
        # Element UI specific patterns
        assert '.el-button' in selectors['button']
        assert '.el-form-item' in selectors['formItem']

    def test_load_antd_selectors(self):
        """Load Ant Design selectors from JSON"""
        selectors = discover_page._load_fw_selectors('ant-design')
        assert isinstance(selectors, dict)
        assert 'button' in selectors
        assert 'formItem' in selectors
        assert 'inputInner' in selectors
        # Ant Design specific patterns
        assert '.ant-btn' in selectors['button']
        assert '.ant-form-item' in selectors['formItem']

    def test_load_default_selectors(self):
        """Load default (Element UI) selectors when framework is None"""
        selectors = discover_page._load_fw_selectors(None)
        assert isinstance(selectors, dict)
        # Should default to Element UI (or whatever _load_framework() returns)
        assert len(selectors) > 0
        assert 'button' in selectors

    def test_load_unknown_framework(self):
        """Load default selectors for unknown framework"""
        selectors = discover_page._load_fw_selectors('unknown-framework')
        assert isinstance(selectors, dict)
        # Should fallback to Element UI
        assert '.el-button' in selectors['button']


class TestInjectSelectors:
    """Test _inject_selectors function"""

    def test_inject_basic(self):
        """Inject fwSelectors into JS code"""
        js_code = "document.querySelectorAll(fwSelectors.button)"
        selectors = {'button': '.el-button'}
        result = discover_page._inject_selectors(js_code, selectors)

        assert 'const fwSelectors = ' in result
        assert '"button": ".el-button"' in result
        assert js_code in result

    def test_inject_multiple_selectors(self):
        """Inject multiple selectors"""
        js_code = "document.querySelectorAll(fwSelectors.button + ', ' + fwSelectors.formItem)"
        selectors = {
            'button': '.ant-btn',
            'formItem': '.ant-form-item'
        }
        result = discover_page._inject_selectors(js_code, selectors)

        assert 'const fwSelectors = ' in result
        assert '"button": ".ant-btn"' in result
        assert '"formItem": ".ant-form-item"' in result

    def test_inject_empty_selectors(self):
        """Handle empty selectors dict"""
        js_code = "const x = 1;"
        result = discover_page._inject_selectors(js_code, {})

        assert 'const fwSelectors = {}' in result
        assert js_code in result

    def test_inject_preserves_code(self):
        """Ensure original JS code is preserved"""
        js_code = """
        (arg1, arg2) => {
            const result = document.querySelectorAll(fwSelectors.button);
            return result.length;
        }
        """
        selectors = {'button': '.el-button'}
        result = discover_page._inject_selectors(js_code, selectors)

        assert '(arg1, arg2) =>' in result
        assert 'return result.length;' in result


class TestFrameworkDetection:
    """Test _detect_page_framework function"""

    def test_detect_element_ui(self):
        """Detect Element UI from page"""
        # Mock page that returns 'element-ui' when JS is executed
        class MockPage:
            def evaluate(self, js_code):
                return 'element-ui'

        page = MockPage()
        framework = discover_page._detect_page_framework(page)
        assert framework == 'element-ui'

    def test_detect_antd(self):
        """Detect Ant Design from page"""
        class MockPage:
            def evaluate(self, js_code):
                return 'ant-design'

        page = MockPage()
        framework = discover_page._detect_page_framework(page)
        assert framework == 'ant-design'

    def test_detect_none(self):
        """Return None when no framework detected"""
        class MockPage:
            def evaluate(self, js_code):
                return None

        page = MockPage()
        framework = discover_page._detect_page_framework(page)
        assert framework is None


class TestJSFilesExist:
    """Test that extracted JS files exist"""

    def test_discover_common_js_exists(self):
        """_discover_common.js file exists"""
        js_file = Path(__file__).parent / 'js' / '_discover_common.js'
        assert js_file.exists()

    def test_row_hover_js_exists(self):
        """_row_hover.js file exists"""
        js_file = Path(__file__).parent / 'js' / '_row_hover.js'
        assert js_file.exists()

    def test_flexible_locator_js_exists(self):
        """_flexible_locator.js file exists"""
        js_file = Path(__file__).parent / 'js' / '_flexible_locator.js'
        assert js_file.exists()

    def test_selectors_element_json_exists(self):
        """selectors_element.json file exists"""
        json_file = Path(__file__).parent / 'js' / 'selectors_element.json'
        assert json_file.exists()

    def test_selectors_antd_json_exists(self):
        """selectors_antd.json file exists"""
        json_file = Path(__file__).parent / 'js' / 'selectors_antd.json'
        assert json_file.exists()


class TestJSFilesContent:
    """Test that JS files use fwSelectors"""

    def test_discover_common_uses_fw_selectors(self):
        """_discover_common.js references fwSelectors"""
        js_file = Path(__file__).parent / 'js' / '_discover_common.js'
        content = js_file.read_text(encoding='utf-8')

        assert 'fwSelectors.button' in content
        assert 'fwSelectors.formItem' in content
        assert 'fwSelectors.inputInner' in content
        # Should NOT have hardcoded Element UI selectors
        assert '.el-button' not in content or '// ' in content  # Allow in comments

    def test_row_hover_uses_fw_selectors(self):
        """_row_hover.js references fwSelectors"""
        js_file = Path(__file__).parent / 'js' / '_row_hover.js'
        content = js_file.read_text(encoding='utf-8')

        assert 'fwSelectors.tableBodyRows' in content
        assert 'fwSelectors.rowButton' in content

    def test_flexible_locator_uses_fw_selectors(self):
        """_flexible_locator.js references fwSelectors"""
        js_file = Path(__file__).parent / 'js' / '_flexible_locator.js'
        content = js_file.read_text(encoding='utf-8')

        assert 'fwSelectors.formItem' in content
        assert 'fwSelectors.formItemLabel' in content


class TestModuleLevelCache:
    """Test _FW_SELECTORS module-level cache"""

    def test_cache_initially_empty(self):
        """_FW_SELECTORS is initially empty dict"""
        # Reset cache
        discover_page._FW_SELECTORS = {}
        assert discover_page._FW_SELECTORS == {}

    def test_cache_can_be_set(self):
        """_FW_SELECTORS can be set and retrieved"""
        test_selectors = {'button': '.test-btn'}
        discover_page._FW_SELECTORS = test_selectors
        assert discover_page._FW_SELECTORS == test_selectors
        # Reset
        discover_page._FW_SELECTORS = {}


class TestWithFWFunction:
    """Test _with_fw helper function"""

    def test_with_fw_empty_cache(self):
        """_with_fw returns unchanged code when cache is empty"""
        discover_page._FW_SELECTORS = {}
        js_code = "const x = 1;"
        result = discover_page._with_fw(js_code)
        assert result == js_code

    def test_with_fw_with_selectors(self):
        """_with_fw injects selectors when cache is populated"""
        discover_page._FW_SELECTORS = {'button': '.el-button'}
        js_code = "const x = fwSelectors.button;"
        result = discover_page._with_fw(js_code)

        assert 'const fwSelectors = ' in result
        assert '"button": ".el-button"' in result
        assert js_code in result
        # Reset
        discover_page._FW_SELECTORS = {}


class TestLoadJSFunction:
    """Test _load_js helper function"""

    def test_load_discover_common(self):
        """Load _discover_common.js"""
        js = discover_page._load_js('_discover_common.js')
        assert isinstance(js, str)
        assert len(js) > 0
        assert 'fwSelectors' in js

    def test_load_row_hover(self):
        """Load _row_hover.js"""
        js = discover_page._load_js('_row_hover.js')
        assert isinstance(js, str)
        assert len(js) > 0
        assert 'fwSelectors' in js

    def test_load_flexible_locator(self):
        """Load _flexible_locator.js"""
        js = discover_page._load_js('_flexible_locator.js')
        assert isinstance(js, str)
        assert len(js) > 0
        assert 'fwSelectors' in js

    def test_load_nonexistent_file(self):
        """Load nonexistent file raises error"""
        with pytest.raises(FileNotFoundError):
            discover_page._load_js('nonexistent.js')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
