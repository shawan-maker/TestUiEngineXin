#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XPath Picker - Interactive Debug Tool for Phase 9
==================================================

Provides an interactive element picker for debugging failed test cases.
Users can hover/click elements in the browser to generate XPath locators
that comply with project specifications (hidden filters, container prefixes, etc.)

Integration:
    - Injected into browser via page.evaluate()
    - Polls window.__picker_pick for user interactions
    - Verifies strategies using page.locator().count()
    - Applies inject_hidden_filter() and apply_container_prefix()
    - Returns verified XPath locator

Usage in DebugRunner._debug_prompt():
    if choice == 'p':
        from tools.verification.debug_picker import launch_xpath_picker
        result = launch_xpath_picker(self.base_case.page, framework='element-ui',
                                     pages_dir='...', target_locator={...}, module='project')
"""

import json
import time
from pathlib import Path


def launch_xpath_picker(page, framework='element-ui', pages_dir=None,
                        target_locator=None, module=None, config=None):
    """Launch interactive XPath picker in the browser.

    Single-element mode: user picks ONE element, the last valid result
    overwrites the previous one. On writeback, directly updates the target
    locator in pages YAML and the in-memory config.

    Args:
        page: Playwright Page object
        framework: UI framework name ('element-ui' or 'ant-design')
        pages_dir: pages directory path for writeback
        target_locator: dict {group, field, locator_ref, desc} from failed step
        module: current module name (e.g., 'project')
        config: test config dict with 'global_variable' for in-memory locator update

    Returns:
        dict or None: the last valid picked element, or None if no valid pick
    """
    # Validate: target_locator and module must be provided
    if not target_locator or not module:
        print("\n❌ 错误：无法获取失败步骤信息，请检查执行树")
        print("   建议：重新运行测试并查看调试报告")
        return None

    print(f"\n🔍 失败步骤: {target_locator.get('desc', '?')}")
    print(f"   目标: {target_locator.get('locator_ref', '?')}")

    # Load JS picker code
    js_path = Path(__file__).parent.parent / 'probe' / 'js' / '_xpath_picker.js'
    if not js_path.exists():
        print(f"[ERROR] XPath Picker JS not found: {js_path}")
        return None

    with open(js_path, 'r', encoding='utf-8') as f:
        picker_js = f.read()

    # Load framework-specific selectors
    selectors = _load_framework_selectors(framework)
    break_classes = _load_break_classes(framework)

    # Inject framework config + picker code
    init_code = f"""
    window.fwSelectors = {json.dumps(selectors)};
    window.fwBreakClasses = {json.dumps(break_classes)};
    {picker_js}
    """

    page.evaluate(init_code)
    print("\n🔍 XPath Picker 已激活")
    print(f"   目标元素: {target_locator.get('group', '?')}.{target_locator.get('field', '?')}")
    print("   - Click 元素拾取并验证（新选择覆盖旧的）")
    print("   - 💾 写入 YAML 按钮直接更新目标元素")
    print("   - Esc 退出拾取模式")
    print("   等待用户操作...")

    last_result = None

    # Polling loop: check for user interactions
    try:
        while True:
            # Check exit signal
            exit_flag = page.evaluate('window.__picker_exit')
            if exit_flag:
                print("\n✅ 退出拾取模式")
                break

            # Check for picked element
            pick_data = page.evaluate('window.__picker_pick')
            if pick_data:
                # Clear the pick signal
                page.evaluate('window.__picker_pick = null')

                # Verify strategies
                verified = _verify_strategies(
                    page,
                    pick_data['strategies'],
                    pick_data.get('type'),
                    pick_data.get('container')
                )

                # Build result
                result = {
                    'label': pick_data.get('label', ''),
                    'type': pick_data.get('type', ''),
                    'container': pick_data.get('container'),
                    'container_label': pick_data.get('container_label'),
                    'xpath': verified['xpath'],
                    'count': verified['count'],
                    'strategy': verified['strategy'],
                    'valid': verified['valid']
                }
                last_result = result

                # Display result
                status = '✅' if result['valid'] else '❌'
                container_info = ''
                if result['container']:
                    container_info = f" [{result['container']}]"
                    if result['container_label']:
                        container_info += f"({result['container_label']})"

                print(f"\n{status} 拾取: {result['label']}")
                print(f"   类型: {result['type']}{container_info}")
                print(f"   XPath: {result['xpath']}")
                print(f"   验证: count={result['count']}, 策略: {result['strategy']}")

                # Send verification result back to JS for UI update
                page.evaluate(f'window.__picker_verified = {json.dumps(verified)}')

            # Check for writeback request
            writeback_request = page.evaluate('window.__picker_writeback_request')
            if writeback_request:
                page.evaluate('window.__picker_writeback_request = null')

                # Read the last valid result from JS
                last_valid = page.evaluate('window.__picker_last_valid')
                if not last_valid:
                    last_valid = last_result

                if last_valid and last_valid.get('valid') and pages_dir:
                    success = _update_target_locator(
                        last_valid, target_locator, module, pages_dir, config
                    )
                    if success:
                        # Auto-exit: trigger exit signal so polling loop ends
                        page.evaluate('window.__picker_exit = true')
                        print("\n💾 写回完成，正在自动退出拾取模式...")
                        print("   提示：退出后按 r 重试用例（使用新定位器）")
                    else:
                        print("\n❌ 写回失败")
                else:
                    print("\n⚠️ 无有效结果可写入")

            time.sleep(0.3)  # Poll interval

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断拾取")

    # Cleanup: remove picker UI
    page.evaluate('window.__picker_cleanup && window.__picker_cleanup()')

    if last_result and last_result.get('valid'):
        print(f"\n📊 拾取结果: {last_result['label']} ({last_result['type']})")
    else:
        print("\n📊 无有效拾取结果")

    return last_result


def _verify_strategies(page, strategies, elem_type=None, container=None):
    """Verify XPath strategies and return the first one with count==1.

    Applies project-specific post-processing:
    - inject_hidden_filter() for input types
    - apply_container_prefix() for container scope
    - [1] wrapping for count > 1

    Args:
        page: Playwright Page object
        strategies: list of XPath strings to try
        elem_type: element type (e.g., 'input', 'button', 'el-select')
        container: container type (e.g., 'dialog', 'drawer')

    Returns:
        dict: {'xpath': str, 'count': int, 'strategy': str, 'valid': bool}
    """
    # Import post-processing functions
    try:
        from tools.core.xpath_utils import inject_hidden_filter, apply_container_prefix
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.xpath_utils import inject_hidden_filter, apply_container_prefix

    for idx, raw_xpath in enumerate(strategies):
        xpath = raw_xpath

        # Apply hidden filter for input types
        if elem_type in ['input', 'textarea', 'el-select', 'date-picker', 'el-cascader']:
            xpath = inject_hidden_filter(xpath)

        # Apply container prefix
        if container:
            xpath = apply_container_prefix(xpath, container)

        # Verify with Playwright
        try:
            selector = f"xpath={xpath}" if not xpath.startswith('xpath=') else xpath
            count = page.locator(selector).count()

            if count == 1:
                return {
                    'xpath': xpath,
                    'count': count,
                    'strategy': f"P{idx}",
                    'valid': True
                }
            elif count > 1:
                # Try wrapping with [1]
                wrapped = f"({xpath})[1]"
                selector_wrapped = f"xpath={wrapped}"
                count_wrapped = page.locator(selector_wrapped).count()
                if count_wrapped == 1:
                    return {
                        'xpath': wrapped,
                        'count': count_wrapped,
                        'strategy': f"P{idx}+[1]",
                        'valid': True
                    }
        except Exception as e:
            # Strategy failed, try next
            continue

    # All strategies failed
    return {
        'xpath': strategies[0] if strategies else '',
        'count': 0,
        'strategy': 'none',
        'valid': False
    }


def _load_framework_selectors(framework):
    """Load framework-specific CSS selectors from JSON file.

    Args:
        framework: 'element-ui' or 'ant-design'

    Returns:
        dict: selector name -> CSS selector string
    """
    js_dir = Path(__file__).parent.parent / 'probe' / 'js'

    if framework == 'ant-design':
        path = js_dir / 'selectors_antd.json'
    else:
        path = js_dir / 'selectors_element.json'

    if not path.exists():
        print(f"[WARN] Selectors file not found: {path}, using empty dict")
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _load_break_classes(framework):
    """Load framework-specific break classes for XPath generation.

    Args:
        framework: 'element-ui' or 'ant-design'

    Returns:
        list: break class prefixes
    """
    try:
        from tools.core.framework_registry import JS_BREAK_CLASSES
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.framework_registry import JS_BREAK_CLASSES

    return JS_BREAK_CLASSES.get(framework, [])


def _update_target_locator(result, target_locator, module, pages_dir, config=None):
    """Directly update the target element's XPath value in pages YAML and in-memory config.

    This is the core writeback function: replaces the old XPath with the
    newly picked one, without changing the element name or group.

    Args:
        result: picked element dict {xpath, count, valid, label, type}
        target_locator: {group: 'project_page', field: 'query_btn', locator_ref: '...'}
        module: module name (e.g., 'project')
        pages_dir: pages directory path
        config: optional config dict with 'global_variable' for in-memory update

    Returns:
        bool: True if update succeeded
    """
    import yaml

    yaml_file = Path(pages_dir) / module / 'elements.yaml'
    if not yaml_file.exists():
        print(f"[ERROR] YAML file not found: {yaml_file}")
        return False

    group = target_locator.get('group')
    field = target_locator.get('field')

    # Load YAML
    with open(yaml_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    # Validate group and field exist
    if group not in data:
        print(f"[ERROR] Group '{group}' not found in {yaml_file}")
        return False
    if field not in data.get(group, {}):
        print(f"[ERROR] Field '{field}' not found in group '{group}'")
        return False

    old_value = data[group][field]
    new_xpath = result['xpath']
    if not new_xpath.startswith('xpath='):
        new_xpath = f'xpath={new_xpath}'
    data[group][field] = new_xpath

    # Write back to disk
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # Display old → new (truncated for readability)
    old_display = old_value[:80] + '...' if len(old_value) > 80 else old_value
    new_display = new_xpath[:80] + '...' if len(new_xpath) > 80 else new_xpath

    print(f"\n💾 已更新: {group}.{field}")
    print(f"   旧值: {old_display}")
    print(f"   新值: {new_display}")

    # Update in-memory config (so retry uses new locator immediately)
    if config and 'global_variable' in config:
        key = f"{group}.{field}"
        config['global_variable'][key] = new_xpath
        print(f"   内存定位器已更新: {key}")

    return True


# Test entry point
if __name__ == '__main__':
    print("XPath Picker - Interactive Debug Tool")
    print("=" * 50)
    print("\nThis module is designed to be called from DebugRunner.")
    print("Usage:")
    print("  from tools.verification.debug_picker import launch_xpath_picker")
    print("  result = launch_xpath_picker(page, framework='element-ui',")
    print("      pages_dir='...', target_locator={...}, module='project')")
