#!/usr/bin/env python3
"""
测试脚本：调试「项目」el-select 选择操作（增强版）

流程：
1. 打开页面
2. 点击项目下拉框（expand）
3. 检查是否可编辑（editable）
4. 如果可编辑，输入搜索 "Project-060f0629"
5. **暂停** - 手动检查 DOM 和 locator
6. 按回车继续，详细诊断选项元素
7. 尝试多种点击方式
"""

import sys
import os

# 添加 tools 目录到 path
TOOLS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'tools')
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from playwright.sync_api import sync_playwright

# 配置
URL = "http://console-estack-intel.cmecloud.cn/estack/web/op-compute-web/#/order/vm?orderSource=consoleList"
COOKIE = "sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%2C%22%24latest_referrer%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%7D; __upayegisid=fb946e77-10ad-4bcd-9835-4cc758c05f09aa; estack_lang=zh-CN; accessToken=4ee94445-5ac8-4e0b-93c3-69a19ef61951"

# Locators
LOCATOR_EXPAND = "xpath=(//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown')) and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"

LOCATOR_EDITABLE = "xpath=(//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//input[not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])][@class='el-input__inner'])[1][not(@readonly)]"

LOCATOR_SELECT_INPUT = "xpath=(//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"

LOCATOR_OPTION = "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start')]//li[contains(.,'Project-060f0629') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"

SEARCH_VALUE = "Project-060f0629"


def main():
    print("=" * 80)
    print("测试脚本：调试「项目」el-select 选择操作（增强版）")
    print("=" * 80)

    with sync_playwright() as p:
        print("\n[1] 启动浏览器（headed 模式）...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Step 1: 先注入 Cookie，再访问页面
        print("\n[2] 先注入 Cookie（必须在访问页面前）...")
        from urllib.parse import urlparse
        domain = urlparse(URL).hostname
        cookies = []
        for item in COOKIE.split('; '):
            if '=' in item:
                name, value = item.split('=', 1)
                cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': domain,
                    'path': '/'
                })
        context.add_cookies(cookies)
        print(f"    注入 {len(cookies)} 个 cookie")

        print(f"\n[3] 打开页面: {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)  # 等待 5 秒确保页面完全加载和渲染

        # Step 1: 点击展开
        print("\n[4] 点击「项目」下拉框（expand）...")
        print(f"    Locator: {LOCATOR_EXPAND[:100]}...")
        expand_elem = page.locator(LOCATOR_EXPAND).first
        expand_count = expand_elem.count()
        print(f"    count: {expand_count}")

        if expand_count == 0:
            print("    ❌ 未找到 expand 元素，退出")
            input("\n按回车关闭浏览器...")
            browser.close()
            return

        expand_elem.click(timeout=5000)
        print("    ✅ 点击成功")
        page.wait_for_timeout(1000)

        # Step 2: 检查是否可编辑
        print("\n[5] 检查是否可编辑（editable）...")
        print(f"    Locator: {LOCATOR_EDITABLE[:100]}...")
        editable_elem = page.locator(LOCATOR_EDITABLE).first
        editable_count = editable_elem.count()
        print(f"    count: {editable_count}")

        if editable_count == 0:
            print("    ❌ 不可编辑，进入 else 分支（未实现）")
            input("\n按回车关闭浏览器...")
            browser.close()
            return

        print("    ✅ 可编辑，进入 then 分支")

        # Step 3: 输入搜索
        print(f"\n[6] 输入搜索: '{SEARCH_VALUE}'...")
        print(f"    Locator: {LOCATOR_SELECT_INPUT[:100]}...")
        input_elem = page.locator(LOCATOR_SELECT_INPUT).first
        input_count = input_elem.count()
        print(f"    count: {input_count}")

        if input_count == 0:
            print("    ❌ 未找到输入框，退出")
            input("\n按回车关闭浏览器...")
            browser.close()
            return

        input_elem.fill(SEARCH_VALUE)
        print("    ✅ fill() 成功")

        # 等待搜索结果
        print("\n[7] 等待搜索结果加载（1.5 秒）...")
        page.wait_for_timeout(1500)

        # 暂停
        print("\n" + "=" * 80)
        print("⏸️  程序暂停 - 请手动检查以下内容：")
        print("=" * 80)
        print("\n1. 打开浏览器 DevTools (F12)")
        print("2. 检查输入框是否有文本:", SEARCH_VALUE)
        print("3. 检查下拉面板是否仍然可见（el-select-dropdown）")
        print("4. 检查 li 选项是否存在：")
        print(f"   {LOCATOR_OPTION[:100]}...")
        print("\n5. 在 Console 中执行以下代码检查 li count：")
        print("   document.evaluate(\"(//div[(@x-placement='bottom-start' or @x-placement='top-start')]//li[contains(.,'Project-060f0629')])[1]\", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue")
        print("\n6. 检查是否有 is-hidden 或 display:none 的祖先元素")
        print("\n" + "=" * 80)

        input("\n按回车继续（将进行详细诊断）...")

        # Step 4: 详细诊断选项元素
        print("\n[8] 详细诊断选项元素...")
        print(f"    Locator: {LOCATOR_OPTION[:100]}...")

        option_locator = page.locator(LOCATOR_OPTION).first
        option_count = option_locator.count()
        print(f"    count: {option_count}")

        if option_count == 0:
            print("    ❌ 未找到选项，退出")
            input("\n按回车关闭浏览器...")
            browser.close()
            return

        # 检查可见性
        is_visible = option_locator.is_visible()
        print(f"    is_visible(): {is_visible}")

        # 检查元素属性
        try:
            elem = option_locator.element_handle()

            # 检查 bounding box
            bbox = option_locator.bounding_box()
            print(f"    bounding_box: {bbox}")

            # 检查各种 CSS 属性
            opacity = elem.evaluate("el => window.getComputedStyle(el).opacity")
            display = elem.evaluate("el => window.getComputedStyle(el).display")
            visibility = elem.evaluate("el => window.getComputedStyle(el).visibility")
            pointer_events = elem.evaluate("el => window.getComputedStyle(el).pointerEvents")

            print(f"    opacity: {opacity}")
            print(f"    display: {display}")
            print(f"    visibility: {visibility}")
            print(f"    pointer-events: {pointer_events}")

            # 检查 disabled 属性
            disabled = elem.evaluate("el => el.disabled")
            print(f"    disabled: {disabled}")

            # 检查 aria-disabled
            aria_disabled = elem.evaluate("el => el.getAttribute('aria-disabled')")
            print(f"    aria-disabled: {aria_disabled}")

        except Exception as e:
            print(f"    ❌ 获取属性失败: {e}")

        # Step 5: 尝试多种点击方式
        print("\n[9] 尝试多种点击方式...")

        # 方式 1: 普通 click
        print("\n  [9.1] 普通 click (timeout=5000)...")
        try:
            option_locator.click(timeout=5000)
            print("      ✅ 成功")
        except Exception as e:
            print(f"      ❌ 失败: {str(e)[:100]}")

        # 重新打开下拉面板
        print("\n  重新打开下拉面板...")
        expand_elem.click(timeout=5000)
        page.wait_for_timeout(1000)
        input_elem.fill(SEARCH_VALUE)
        page.wait_for_timeout(1500)

        # 方式 2: force click
        print("\n  [9.2] force click (跳过 actionability 检查)...")
        try:
            option_locator.click(force=True, timeout=5000)
            print("      ✅ 成功")
        except Exception as e:
            print(f"      ❌ 失败: {str(e)[:100]}")

        # 重新打开下拉面板
        print("\n  重新打开下拉面板...")
        expand_elem.click(timeout=5000)
        page.wait_for_timeout(1000)
        input_elem.fill(SEARCH_VALUE)
        page.wait_for_timeout(1500)

        # 方式 3: JavaScript click
        print("\n  [9.3] JavaScript click...")
        try:
            elem = option_locator.element_handle()
            elem.evaluate("el => el.click()")
            print("      ✅ 成功")
        except Exception as e:
            print(f"      ❌ 失败: {str(e)[:100]}")

        # 重新打开下拉面板
        print("\n  重新打开下拉面板...")
        expand_elem.click(timeout=5000)
        page.wait_for_timeout(1000)
        input_elem.fill(SEARCH_VALUE)
        page.wait_for_timeout(1500)

        # 方式 4: dispatch_event
        print("\n  [9.4] dispatch_event('click')...")
        try:
            option_locator.dispatch_event('click')
            print("      ✅ 成功")
        except Exception as e:
            print(f"      ❌ 失败: {str(e)[:100]}")

        # 重新打开下拉面板
        print("\n  重新打开下拉面板...")
        expand_elem.click(timeout=5000)
        page.wait_for_timeout(1000)
        input_elem.fill(SEARCH_VALUE)
        page.wait_for_timeout(1500)

        # 方式 5: 检查是否有其他元素遮挡
        print("\n  [9.5] 检查遮挡元素...")
        try:
            bbox = option_locator.bounding_box()
            if bbox:
                x = bbox['x'] + bbox['width'] / 2
                y = bbox['y'] + bbox['height'] / 2
                print(f"      中心点: ({x}, {y})")

                # 检查该坐标上是否有其他元素
                covering_elem = page.evaluate(f"""
                    () => {{
                        const elem = document.elementFromPoint({x}, {y});
                        return elem ? elem.outerHTML.substring(0, 200) : null;
                    }}
                """)
                print(f"      该坐标上的元素: {covering_elem}")

                # 检查是否是选项元素本身
                option_elem_html = option_locator.evaluate("el => el.outerHTML.substring(0, 200)")
                print(f"      选项元素 HTML: {option_elem_html}")

                if covering_elem and option_elem_html[:50] not in covering_elem:
                    print("      ⚠️  有遮挡！中心点上的元素不是选项元素")
        except Exception as e:
            print(f"      ❌ 失败: {str(e)[:100]}")

        print("\n" + "=" * 80)
        print("测试完成")
        print("=" * 80)

        input("\n按回车关闭浏览器...")
        browser.close()


if __name__ == "__main__":
    main()
