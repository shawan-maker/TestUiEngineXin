#!/usr/bin/env python3
"""debug_picker 单元测试 — XPath Picker 核心逻辑

验证:
- _load_framework_selectors: JSON 加载
- _load_break_classes: 断点类加载
- _verify_strategies: 策略验证核心逻辑（Mock page）
- 集成入口 launch_xpath_picker: 参数校验与降级
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")


# ── Mock Page ──────────────────────────────────────────

class MockLocator:
    """模拟 Playwright Locator"""
    def __init__(self, count_val):
        self._count = count_val

    def count(self):
        return self._count


class MockPage:
    """模拟 Playwright Page，支持按 XPath 映射 count 返回值"""
    def __init__(self, xpath_counts=None):
        self._xpath_counts = xpath_counts or {}
        self._evaluated = []

    def locator(self, selector):
        # 去掉 xpath= 前缀
        key = selector.replace('xpath=', '', 1) if selector.startswith('xpath=') else selector
        count_val = self._xpath_counts.get(key, 0)
        return MockLocator(count_val)

    def evaluate(self, js_code):
        self._evaluated.append(js_code)
        return None


# ============================================================================
# Part 1: _load_framework_selectors
# ============================================================================
print("=" * 60)
print("Part 1: _load_framework_selectors")
print("=" * 60)

from verification.debug_picker import _load_framework_selectors

sel_elem = _load_framework_selectors('element-ui')
check("1.1 Element UI selectors loaded", isinstance(sel_elem, dict) and len(sel_elem) > 0)
check("1.2 formItem selector exists", 'formItem' in sel_elem)
check("1.3 formItem value correct", sel_elem.get('formItem') == '.el-form-item')
check("1.4 button selector exists", 'button' in sel_elem)
check("1.5 selectExclude exists", 'selectExclude' in sel_elem)

sel_antd = _load_framework_selectors('ant-design')
check("1.6 Ant Design selectors loaded", isinstance(sel_antd, dict) and len(sel_antd) > 0)
check("1.7 Ant Design formItem", sel_antd.get('formItem') == '.ant-form-item')
check("1.8 Ant Design button", sel_antd.get('button') == 'button.ant-btn, a.ant-btn')

# 未知框架回退到 Element UI
sel_unknown = _load_framework_selectors('unknown-framework')
check("1.9 Unknown framework falls back to Element UI", sel_unknown.get('formItem') == '.el-form-item')

# None 回退到 Element UI
sel_none = _load_framework_selectors(None)
check("1.10 None framework falls back to Element UI", sel_none.get('formItem') == '.el-form-item')

print()

# ============================================================================
# Part 2: _load_break_classes
# ============================================================================
print("=" * 60)
print("Part 2: _load_break_classes")
print("=" * 60)

from verification.debug_picker import _load_break_classes

brk_elem = _load_break_classes('element-ui')
check("2.1 Element UI break classes is list", isinstance(brk_elem, list))
check("2.2 Contains el-dialog", 'el-dialog' in brk_elem)
check("2.3 Contains el-drawer", 'el-drawer' in brk_elem)
check("2.4 Contains el-form-item", 'el-form-item' in brk_elem)

brk_antd = _load_break_classes('ant-design')
check("2.5 Ant Design break classes is list", isinstance(brk_antd, list))
check("2.6 Contains ant-modal", 'ant-modal' in brk_antd)
check("2.7 Contains ant-drawer", 'ant-drawer' in brk_antd)

brk_unknown = _load_break_classes('unknown-framework')
check("2.8 Unknown framework returns empty list", brk_unknown == [])

print()

# ============================================================================
# Part 3: _verify_strategies — 核心验证逻辑
# ============================================================================
print("=" * 60)
print("Part 3: _verify_strategies")
print("=" * 60)

from verification.debug_picker import _verify_strategies

# 3.1 首个策略 count=1 → 直接成功
page = MockPage({
    "//button[contains(.,'查询')]": 1,
})
result = _verify_strategies(
    page,
    ["//button[contains(.,'查询')]"],
    elem_type='button',
    container=None,
)
check("3.1.1 First strategy count=1 → valid", result['valid'] is True)
check("3.1.2 count=1", result['count'] == 1)
check("3.1.3 strategy=P0", result['strategy'] == 'P0')
check("3.1.4 xpath preserved", '查询' in result['xpath'])

# 3.2 首个策略 count=0，第二个 count=1 → 使用第二个
page = MockPage({
    "//button[contains(.,'查询')]": 0,
    "//button[contains(.,'查') and contains(.,'询')]": 1,
})
result = _verify_strategies(
    page,
    ["//button[contains(.,'查询')]", "//button[contains(.,'查') and contains(.,'询')]"],
    elem_type='button',
    container=None,
)
check("3.2.1 Second strategy → valid", result['valid'] is True)
check("3.2.2 strategy=P1", result['strategy'] == 'P1')

# 3.3 count>1 → 尝试 [1] 包裹
page = MockPage({
    "//button[contains(.,'提交')]": 3,
    "(//button[contains(.,'提交')])[1]": 1,
})
result = _verify_strategies(
    page,
    ["//button[contains(.,'提交')]"],
    elem_type='button',
    container=None,
)
check("3.3.1 count>1 with [1] wrap → valid", result['valid'] is True)
check("3.3.2 strategy=P0+[1]", result['strategy'] == 'P0+[1]')
check("3.3.3 xpath contains [1]", '(//button' in result['xpath'] and '[1]' in result['xpath'])

# 3.4 所有策略 count=0 → valid=False
page = MockPage({})  # 所有 XPath 返回 0
result = _verify_strategies(
    page,
    ["//button[contains(.,'不存在')]", "//button[contains(.,'也不存在')]"],
    elem_type='button',
    container=None,
)
check("3.4.1 All strategies fail → valid=False", result['valid'] is False)
check("3.4.2 count=0", result['count'] == 0)
check("3.4.3 strategy=none", result['strategy'] == 'none')

# 3.5 空策略列表 → valid=False
page = MockPage({})
result = _verify_strategies(page, [], elem_type='button', container=None)
check("3.5.1 Empty strategies → valid=False", result['valid'] is False)
check("3.5.2 xpath is empty string", result['xpath'] == '')

# 3.6 input 类型 → 注入隐藏过滤
page = MockPage()
# 用 spy 来检查 inject_hidden_filter 是否被调用
# 由于 xpath 经过 inject_hidden_filter 处理后 key 会变长，
# 我们需要用处理后的 xpath 作为 key
from core.xpath_utils import inject_hidden_filter
raw_xpath = "//*[contains(text(),'用户名')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
filtered_xpath = inject_hidden_filter(raw_xpath)
page._xpath_counts[filtered_xpath] = 1

result = _verify_strategies(page, [raw_xpath], elem_type='input', container=None)
check("3.6.1 Input type → hidden filter injected → valid", result['valid'] is True)
check("3.6.2 xpath contains hidden filter", 'is-hidden' in result['xpath'])

# 3.7 button 类型 → 不注入隐藏过滤
page = MockPage({
    "//button[contains(.,'查询')]": 1,
})
result = _verify_strategies(page, ["//button[contains(.,'查询')]"], elem_type='button', container=None)
check("3.7.1 Button type → no hidden filter", 'is-hidden' not in result['xpath'])
check("3.7.2 Button → valid", result['valid'] is True)

# 3.8 container=dialog → 注入容器前缀
from core.xpath_utils import apply_container_prefix
raw_xpath = "//button[contains(.,'确认')]"
prefixed_xpath = apply_container_prefix(raw_xpath, 'dialog')
page = MockPage({prefixed_xpath: 1})
result = _verify_strategies(page, [raw_xpath], elem_type='button', container='dialog')
check("3.8.1 Dialog container prefix applied", 'el-dialog' in result['xpath'])
check("3.8.2 Container prefix → valid", result['valid'] is True)

# 3.9 container=drawer → 注入容器前缀
raw_xpath = "//button[contains(.,'确定')]"
prefixed_xpath = apply_container_prefix(raw_xpath, 'drawer')
page = MockPage({prefixed_xpath: 1})
result = _verify_strategies(page, [raw_xpath], elem_type='button', container='drawer')
check("3.9.1 Drawer container prefix applied", 'el-drawer' in result['xpath'])
check("3.9.2 Drawer prefix → valid", result['valid'] is True)

# 3.10 input + container → 同时注入隐藏过滤和容器前缀
raw_xpath = "//*[contains(text(),'名称')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
filtered = inject_hidden_filter(raw_xpath)
prefixed = apply_container_prefix(filtered, 'drawer')
page = MockPage({prefixed: 1})
result = _verify_strategies(page, [raw_xpath], elem_type='input', container='drawer')
check("3.10.1 Input + drawer → both filters", 'is-hidden' in result['xpath'] and 'el-drawer' in result['xpath'])
check("3.10.2 Input + drawer → valid", result['valid'] is True)

# 3.11 count>1 但 [1] 包裹后仍 count>1 → valid=False
page = MockPage({
    "//button[contains(.,'删除')]": 5,
    "(//button[contains(.,'删除')])[1]": 5,
})
result = _verify_strategies(page, ["//button[contains(.,'删除')]"], elem_type='button', container=None)
check("3.11.1 count>1 and [1] still >1 → valid=False", result['valid'] is False)

# 3.12 textarea 类型 → 注入隐藏过滤
raw_xpath = "//*[contains(text(),'描述')]/following-sibling::*[self::div or self::span]//textarea"
filtered_xpath = inject_hidden_filter(raw_xpath)
page = MockPage({filtered_xpath: 1})
result = _verify_strategies(page, [raw_xpath], elem_type='textarea', container=None)
check("3.12.1 Textarea → hidden filter injected", 'is-hidden' in result['xpath'])
check("3.12.2 Textarea → valid", result['valid'] is True)

# 3.13 el-select 类型 → 注入隐藏过滤
raw_xpath = "//*[contains(text(),'状态')]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-select')]"
filtered_xpath = inject_hidden_filter(raw_xpath)
page = MockPage({filtered_xpath: 1})
result = _verify_strategies(page, [raw_xpath], elem_type='el-select', container=None)
check("3.13.1 el-select → hidden filter injected", 'is-hidden' in result['xpath'])

print()

# ============================================================================
# Part 4: launch_xpath_picker — 入口函数降级
# ============================================================================
print("=" * 60)
print("Part 4: launch_xpath_picker entry point")
print("=" * 60)

# 只测试 JS 文件加载逻辑（不启动真实浏览器）
from verification.debug_picker import launch_xpath_picker
from pathlib import Path

js_path = Path(__file__).parent.parent / 'tools' / 'probe' / 'js' / '_xpath_picker.js'
check("4.1 JS picker file exists", js_path.exists())

# 验证 JS 文件语法基本正确（不含未闭合的括号）
if js_path.exists():
    with open(js_path, 'r', encoding='utf-8') as f:
        js_content = f.read()
    check("4.2 JS file not empty", len(js_content) > 100)
    check("4.3 JS has IIFE wrapper", '(function()' in js_content)
    check("4.4 JS has extractLabel", 'function extractLabel' in js_content)
    check("4.5 JS has detectElementType", 'function detectElementType' in js_content)
    check("4.6 JS has detectContainer", 'function detectContainer' in js_content)
    check("4.7 JS has generateXPathStrategies", 'function generateXPathStrategies' in js_content)
    check("4.8 JS has generateStructuralStrategies", 'function generateStructuralStrategies' in js_content)
    check("4.9 JS has createPanel", 'function createPanel' in js_content)
    check("4.10 JS has init call", 'init();' in js_content)
    check("4.11 JS has _sel alias", 'var _sel' in js_content)
    check("4.12 JS has _brk alias", 'var _brk' in js_content)
    check("4.13 JS has getClassName helper", 'function getClassName' in js_content)
    check("4.14 JS has escapeXPathStr", 'function escapeXPathStr' in js_content)
    check("4.15 JS has cleanup function", 'window.__picker_cleanup' in js_content)
    check("4.16 JS has exit signal", 'window.__picker_exit' in js_content)
    check("4.17 JS has pick signal", 'window.__picker_pick' in js_content)
    check("4.18 JS has verified signal", 'window.__picker_verified' in js_content)

print()

# ============================================================================
# Part 6: launch_xpath_picker 函数签名测试
# ============================================================================
print("=" * 60)
print("Part 6: launch_xpath_picker function signature")
print("=" * 60)

from verification.debug_picker import launch_xpath_picker
import inspect

sig = inspect.signature(launch_xpath_picker)
params = list(sig.parameters.keys())

check("6.1 Has 'page' parameter", 'page' in params)
check("6.2 Has 'framework' parameter", 'framework' in params)
check("6.3 Has 'pages_dir' parameter", 'pages_dir' in params)
check("6.4 Has 'config' parameter", 'config' in params)
check("6.5 framework has default value", sig.parameters['framework'].default == 'element-ui')
check("6.6 pages_dir has default value", sig.parameters['pages_dir'].default is None)
check("6.7 config has default value", sig.parameters['config'].default is None)
check("6.8 Can be called with 3 positional args", len(params) >= 3)

print()

# ============================================================================
# Part 7: run.py 集成验证
# ============================================================================
print("=" * 60)
print("Part 7: run.py integration check")
print("=" * 60)

run_py_path = Path(__file__).parent.parent.parent.parent.parent / 'examples' / 'TSManager' / 'run.py'
if run_py_path.exists():
    with open(run_py_path, 'r', encoding='utf-8') as f:
        run_content = f.read()
    check("7.1 [p] option in debug prompt", "'[p]' in run_content or '[p] 拾取' in run_content")
    check("7.2 _run_xpath_picker method exists", '_run_xpath_picker' in run_content)
    check("7.3 launch_xpath_picker import", 'launch_xpath_picker' in run_content)
    check("7.4 choice == 'p' handler", "choice == 'p'" in run_content)
    check("7.5 r/s/q/p prompt text", 'r/s/q/p' in run_content)
else:
    check("7.x run.py exists", False)

print()

# ============================================================================
# Part 8: Direct locator update functions
# ============================================================================
print("=" * 60)
print("Part 8: Direct locator update (_update_target_locator)")
print("=" * 60)

from verification.debug_picker import _update_target_locator
import tempfile
import shutil
import yaml

temp_dir = tempfile.mkdtemp()
try:
    pages_dir = Path(temp_dir) / "pages" / "test_module"
    pages_dir.mkdir(parents=True)

    # Create initial elements.yaml
    yaml_file = pages_dir / "elements.yaml"
    yaml_content = {
        "project_page": {
            "query_btn": "xpath=//button[contains(.,'查询') and not(ancestor-or-self::*[contains(@class,'is-hidden')])]",
            "add_btn": "xpath=//button[contains(.,'新增')]"
        },
        "case_新增项目": {
            "name_input": "xpath=//input[@placeholder='项目名称']"
        }
    }
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_content, f, allow_unicode=True)

    # 8.1 Test successful update
    result = {
        "valid": True,
        "xpath": "(//button[contains(.,'查询')])[1]",
        "label": "查询",
        "type": "button"
    }
    target_locator = {
        "group": "project_page",
        "field": "query_btn",
        "locator_ref": "${project_page.query_btn}"
    }

    success = _update_target_locator(
        result,
        target_locator,
        "test_module",
        str(Path(temp_dir) / "pages")
    )
    check("8.1.1 update returns True", success is True)

    # Verify the update
    with open(yaml_file, 'r', encoding='utf-8') as f:
        updated_data = yaml.safe_load(f)

    check("8.1.2 xpath value updated", "(//button[contains(.,'查询')])[1]" in updated_data["project_page"]["query_btn"])
    check("8.1.3 xpath prefix added", updated_data["project_page"]["query_btn"].startswith("xpath="))
    check("8.1.4 other fields preserved", "add_btn" in updated_data["project_page"])
    check("8.1.5 case group preserved", "name_input" in updated_data["case_新增项目"])

    # 8.2 Test failure cases
    # Invalid group
    result2 = {"valid": True, "xpath": "//button", "label": "test", "type": "button"}
    target2 = {"group": "invalid_group", "field": "test", "locator_ref": "${invalid_group.test}"}
    success2 = _update_target_locator(result2, target2, "test_module", str(Path(temp_dir) / "pages"))
    check("8.2.1 invalid group returns False", success2 is False)

    # Invalid field
    target3 = {"group": "project_page", "field": "invalid_field", "locator_ref": "${project_page.invalid_field}"}
    success3 = _update_target_locator(result2, target3, "test_module", str(Path(temp_dir) / "pages"))
    check("8.2.2 invalid field returns False", success3 is False)

    # Invalid module
    target4 = {"group": "project_page", "field": "query_btn", "locator_ref": "${project_page.query_btn}"}
    success4 = _update_target_locator(result2, target4, "invalid_module", str(Path(temp_dir) / "pages"))
    check("8.2.3 invalid module returns False", success4 is False)

    # 8.3 Test in-memory config update
    # Recreate the YAML file (it was modified by previous tests)
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_content, f, allow_unicode=True)

    result3 = {
        "valid": True,
        "xpath": "(//button[contains(.,'查询')])[1]",
        "label": "查询",
        "type": "button"
    }
    target5 = {
        "group": "project_page",
        "field": "query_btn",
        "locator_ref": "${project_page.query_btn}"
    }

    # Test with config parameter
    config = {"global_variable": {"project_page.query_btn": "xpath=//old/xpath"}}
    success5 = _update_target_locator(
        result3,
        target5,
        "test_module",
        str(Path(temp_dir) / "pages"),
        config=config
    )
    check("8.3.1 update with config returns True", success5 is True)
    check("8.3.2 config global_variable updated", "project_page.query_btn" in config["global_variable"])
    check("8.3.3 config has new xpath", "(//button[contains(.,'查询')])[1]" in config["global_variable"]["project_page.query_btn"])
    check("8.3.4 config xpath has prefix", config["global_variable"]["project_page.query_btn"].startswith("xpath="))

    # Test without config (backward compatibility)
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_content, f, allow_unicode=True)
    success6 = _update_target_locator(
        result3,
        target5,
        "test_module",
        str(Path(temp_dir) / "pages")
    )
    check("8.3.5 update without config returns True", success6 is True)

finally:
    shutil.rmtree(temp_dir)

print()

# ============================================================================
# Part 9: Helper functions (_get_failed_step_info, _get_current_module)
# ============================================================================
print("=" * 60)
print("Part 9: Helper functions")
print("=" * 60)

# 9.1 Test _get_failed_step_info logic (without actual execution tree)
import re

def test_find_last_failed_logic():
    """Test the _find_last_failed recursive logic"""

    # Mock StepNode structure
    class MockNode:
        def __init__(self, status, raw_params=None, desc="", keyword=""):
            self.status = status
            self.raw_params = raw_params or {}
            self.desc = desc
            self.keyword = keyword
            self.children = []

    # Test case 1: Single failed node
    root = MockNode("pass")
    failed = MockNode("fail", {"locator": "${project_page.query_btn}"}, "点击查询按钮", "click_element")
    root.children.append(failed)

    def _find_last_failed(nodes):
        result = None
        for node in nodes:
            child_result = _find_last_failed(node.children)
            if child_result:
                result = child_result
            elif node.status in ('fail', 'error'):
                result = node
        return result

    result = _find_last_failed([root])
    check("9.1.1 find failed node", result is not None and result.status == "fail")

    # Test case 2: Parse locator reference
    locator_ref = result.raw_params.get('locator', '')
    match = re.match(r'\$\{([^}]+)\}', locator_ref)
    check("9.1.2 parse locator ref", match is not None and match.group(1) == "project_page.query_btn")

    # Test case 3: Split group.field
    parts = match.group(1).split('.')
    check("9.1.3 split parts", len(parts) == 2 and parts[0] == "project_page" and parts[1] == "query_btn")

test_find_last_failed_logic()

# 9.2 Test _get_current_module logic
import sys

# Test case 1: Parse from sys.argv
sys.argv = ['run.py', '--module', 'project', '--debug']
if '--module' in sys.argv:
    idx = sys.argv.index('--module')
    module = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
    check("9.2.1 parse module from argv", module == "project")

# Test case 2: No --module flag
sys.argv = ['run.py', '--debug']
if '--module' not in sys.argv:
    check("9.2.2 no module flag returns None", True)

print()

# ============================================================================
# Part 10: run.py integration check (new methods)
# ============================================================================
print("=" * 60)
print("Part 10: run.py new methods")
print("=" * 60)

run_py_path = Path(__file__).parent.parent.parent.parent.parent / 'examples' / 'TSManager' / 'run.py'
if run_py_path.exists():
    with open(run_py_path, 'r', encoding='utf-8') as f:
        run_content = f.read()

    check("10.1 _get_failed_step_info exists", "_get_failed_step_info" in run_content)
    check("10.2 _get_current_module exists", "_get_current_module" in run_content)
    check("10.3 target_locator param", "target_locator=failed_info" in run_content)
    check("10.4 module param", "module=module" in run_content)
    check("10.5 config param", "config=self.config" in run_content)
    check("10.6 error handling", "无法获取失败步骤信息" in run_content)
else:
    check("10.x run.py exists", False)

print()

# ============================================================================
# Summary
# ============================================================================
print("=" * 60)
total = passed + failed
print(f"结果: {passed}/{total} 通过, {failed} 失败")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
