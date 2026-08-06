#!/usr/bin/env python3
"""
测试脚本2：无暂停，模拟 verify_orchestrator 的自动执行流程

目的：复现 fill → wait 1.5s → click 的失败场景
"""

import sys
import io
from playwright.sync_api import sync_playwright

# 自动记录日志到文件
LOG_FILE = "debug_project_select2.log"

class TeeWriter:
    """同时写入控制台和文件"""
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log_file = open(filename, 'w', encoding='utf-8')

    def write(self, message):
        # 控制台用 GBK 兼容方式，文件用 UTF-8
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            self.terminal.write(message.encode('gbk', errors='replace').decode('gbk', errors='replace'))
        self.log_file.write(message)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

# 重定向 stdout
sys.stdout = TeeWriter(LOG_FILE)


URL = "http://console-estack-intel.cmecloud.cn/estack/web/op-compute-web/#/order/vm?orderSource=consoleList"
COOKIE = "sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%2C%22%24latest_referrer%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%7D; __upayegisid=fb946e77-10ad-4bcd-9835-4cc758c05f09aa; estack_lang=zh-CN; accessToken=4ee94445-5ac8-4e0b-93c3-69a19ef61951"

LOCATOR_EXPAND = "xpath=(//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown')) and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
LOCATOR_SELECT_INPUT = "xpath=(//*[contains(text(),'项目')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"
LOCATOR_OPTION = "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start')]//li[contains(.,'Project-060f0629') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])])[1]"

SEARCH_VALUE = "Project-060f0629"


def run_test(page, test_name, expand_wait=1000, fill_wait=1500, use_wait_for=True):
    """运行一次完整的 el-select 操作流程"""
    print(f"\n{'='*60}")
    print(f"测试: {test_name}")
    print(f"  expand_wait={expand_wait}ms, fill_wait={fill_wait}ms, use_wait_for={use_wait_for}")
    print(f"{'='*60}")

    # 1. 展开
    page.locator(LOCATOR_EXPAND).first.click(timeout=5000)
    print(f"  [1] expand click OK")
    page.wait_for_timeout(expand_wait)

    # 2. fill
    page.locator(LOCATOR_SELECT_INPUT).first.fill(SEARCH_VALUE)
    print(f"  [2] fill OK")

    # 3. wait
    page.wait_for_timeout(fill_wait)
    print(f"  [3] wait {fill_wait}ms OK")

    # 4. 检查选项状态
    opt = page.locator(LOCATOR_OPTION).first
    count = opt.count()
    visible = opt.is_visible() if count > 0 else False
    print(f"  [4] option count={count}, is_visible={visible}")

    if count == 0:
        print(f"  ❌ count=0, 面板可能已关闭")
        # 检查下拉面板是否还在
        panel_count = page.locator("xpath=//div[@x-placement]").count()
        print(f"     x-placement panels: {panel_count}")
        return False

    # 5. 点击
    try:
        if use_wait_for:
            try:
                opt.wait_for(state='visible', timeout=8000)
                print(f"  [5a] wait_for(visible) OK")
            except Exception as e:
                print(f"  [5a] wait_for(visible) FAILED: {str(e)[:60]}")
            opt.click(timeout=5000)
        else:
            opt.click(timeout=5000)
        print(f"  [5] click OK ✅")
        return True
    except Exception as e:
        print(f"  ❌ click FAILED: {str(e)[:80]}")
        return False


def main():
    print("=" * 60)
    print("测试脚本2：模拟 verify_orchestrator 自动执行")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 注入 Cookie
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

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # 测试 A：和 verify_orchestrator 一样的参数（有 wait_for）
        run_test(page, "A: verify_orchestrator 原始流程 (wait_for=True)",
                 expand_wait=1000, fill_wait=1500, use_wait_for=True)

        page.wait_for_timeout(2000)

        # 测试 B：和 verify_orchestrator 一样但去掉 wait_for
        run_test(page, "B: 去掉 wait_for",
                 expand_wait=1000, fill_wait=1500, use_wait_for=False)

        page.wait_for_timeout(2000)

        # 测试 C：增加 fill 后等待时间
        run_test(page, "C: fill_wait=3000ms",
                 expand_wait=1000, fill_wait=3000, use_wait_for=False)

        page.wait_for_timeout(2000)

        # 测试 D：增加 expand 后等待时间
        run_test(page, "D: expand_wait=2000ms, fill_wait=1500ms",
                 expand_wait=2000, fill_wait=1500, use_wait_for=False)

        page.wait_for_timeout(2000)

        # 测试 E：不用 fill，用 keyboard.type
        print(f"\n{'='*60}")
        print(f"测试 E: 用 keyboard.type 替代 fill")
        print(f"{'='*60}")
        page.locator(LOCATOR_EXPAND).first.click(timeout=5000)
        print(f"  [1] expand click OK")
        page.wait_for_timeout(1000)

        input_elem = page.locator(LOCATOR_SELECT_INPUT).first
        input_elem.click()
        input_elem.fill('')
        page.keyboard.type(SEARCH_VALUE, delay=20)
        print(f"  [2] keyboard.type OK")
        page.wait_for_timeout(1500)

        opt = page.locator(LOCATOR_OPTION).first
        count = opt.count()
        visible = opt.is_visible() if count > 0 else False
        print(f"  [3] option count={count}, is_visible={visible}")

        try:
            opt.click(timeout=5000)
            print(f"  [4] click OK ✅")
        except Exception as e:
            print(f"  ❌ click FAILED: {str(e)[:80]}")

        page.wait_for_timeout(2000)

        # 测试 F：fill 后重新点击展开，再 click option
        print(f"\n{'='*60}")
        print(f"测试 F: fill 后重新点击 expand 恢复面板")
        print(f"{'='*60}")
        page.locator(LOCATOR_EXPAND).first.click(timeout=5000)
        print(f"  [1] expand click OK")
        page.wait_for_timeout(1000)

        page.locator(LOCATOR_SELECT_INPUT).first.fill(SEARCH_VALUE)
        print(f"  [2] fill OK")
        page.wait_for_timeout(500)

        # 重新点击 expand 恢复面板
        page.locator(LOCATOR_EXPAND).first.click(timeout=5000)
        print(f"  [3] re-click expand OK")
        page.wait_for_timeout(1000)

        opt = page.locator(LOCATOR_OPTION).first
        count = opt.count()
        visible = opt.is_visible() if count > 0 else False
        print(f"  [4] option count={count}, is_visible={visible}")

        try:
            opt.click(timeout=5000)
            print(f"  [5] click OK ✅")
        except Exception as e:
            print(f"  ❌ click FAILED: {str(e)[:80]}")

        print(f"\n{'='*60}")
        print("全部测试完成")
        print(f"{'='*60}")

        input("\n按回车关闭浏览器...")
        browser.close()


if __name__ == "__main__":
    main()
