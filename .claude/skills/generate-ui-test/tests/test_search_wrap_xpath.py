#!/usr/bin/env python3
"""验证 search-wrap KB XPath 能在浏览器中 count==1 匹配。

在真实页面上测试新增的 KB 模式：
  (//div[contains(@class,'search-wrap')])[1]

同时测试 hidden filter 注入后的完整 XPath。
"""

import os
import sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
sys.path.insert(0, TOOLS_DIR)

URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"
COOKIE = (
    "sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%7D%2C%22%24device_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%7D; "
    "__upayegisid=05f70a56-b8ce-43dc-a7f3-41904389f37fb5; "
    "estack_lang=zh-CN; platformTraffic=true; activeUserRatio=true; "
    "onlineUserCount=true; visitDuration=true; "
    "accessToken=d77df668-5d53-4da4-9d08-9c18fdf31423"
)


def main():
    from playwright.sync_api import sync_playwright
    from probe.probe_element import parse_cookie
    from probe.discover_page import _navigate_with_fallback
    from core.wait_utils import wait_for_dom_stable
    from core.xpath_utils import inject_hidden_filter
    from urllib.parse import urlparse
    from probe.probe_utils import get_all_patterns

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage', '--disable-gpu',
                  '--ignore-certificate-errors'],
        )
        domain = urlparse(URL).hostname
        cookies = parse_cookie(COOKIE, domain)
        context = browser.new_context(no_viewport=True, ignore_https_errors=True)
        context.add_cookies(cookies)

        local_storage = {}
        for c in cookies:
            if c['name'] == 'accessToken':
                local_storage['accessToken'] = c['value']

        page = context.new_page()
        root_url = f"{urlparse(URL).scheme}://{urlparse(URL).netloc}/"
        try:
            _navigate_with_fallback(page, root_url, timeout_ms=15000)
        except Exception:
            pass
        if local_storage:
            page.evaluate("""(items) => {
                for (let i = 0; i < items.length; i += 2) {
                    localStorage.setItem(items[i], items[i+1]);
                }
            }""", [k for kv in local_storage.items() for k in kv])

        _navigate_with_fallback(page, URL, timeout_ms=15000)
        wait_for_dom_stable(page, timeout_ms=5000)

        if local_storage:
            for k, v in local_storage.items():
                page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        print("=" * 70)
        print("[TEST] KB XPath count 验证 — search-wrap")
        print("=" * 70)

        # 1. 验证 KB 中 search-button 的所有 patterns
        patterns = get_all_patterns('search-button')
        print(f"\n[INFO] search-button KB patterns: {len(patterns)}")
        for i, p in enumerate(patterns):
            print(f"  [{i}] {p}")

        # 2. 测试新模式的原始 XPath
        raw_xpath = "(//div[contains(@class,'search-wrap')])[1]"
        count_raw = page.locator(f"xpath={raw_xpath}").count()
        print(f"\n[TEST] 原始 XPath: {raw_xpath}")
        print(f"  count = {count_raw}  {'PASS' if count_raw == 1 else 'FAIL'}")

        # 3. 测试 hidden filter 注入后的 XPath
        injected = inject_hidden_filter(f"xpath={raw_xpath}")
        print(f"\n[TEST] Hidden filter 注入后:")
        print(f"  {injected}")
        # 去掉 xpath= 前缀用于 count
        injected_xpath = injected.replace('xpath=', '', 1) if injected.startswith('xpath=') else injected
        count_injected = page.locator(f"xpath={injected_xpath}").count()
        print(f"  count = {count_injected}  {'PASS' if count_injected == 1 else 'FAIL'}")

        # 4. 测试其他 search-button patterns 是否也匹配（对比）
        print(f"\n[TEST] 其他 search-button patterns 对比:")
        test_patterns = [
            "//button[contains(.,'搜索图标')]",
            "(//i[@class='el-icon-search'])[last()]",
            "//i[@class='el-icon-search']",
            "//button[contains(@class,'search') and contains(.,'搜索图标')]",
        ]
        for p in test_patterns:
            try:
                c = page.locator(f"xpath={p}").count()
                print(f"  count={c:2d}  {p[:80]}")
            except Exception as e:
                print(f"  ERROR    {p[:60]}... ({e})")

        # 5. 验证不会误匹配其他元素
        print(f"\n[TEST] 误匹配检查:")
        # 确认 search-wrap 只匹配到搜索图标，不匹配到其他 div
        sw_class_check = page.evaluate("""() => {
            const el = document.querySelector('div.search-wrap');
            if (!el) return 'not_found';
            // 检查是否有 is-hidden 或 display:none
            const hidden = el.classList.contains('is-hidden');
            const style = window.getComputedStyle(el);
            const displayNone = style.display === 'none';
            return {hidden, displayNone, class: el.className};
        }""")
        print(f"  search-wrap 元素状态: {sw_class_check}")

        # 总结
        print(f"\n{'='*70}")
        all_pass = (count_raw == 1 and count_injected == 1)
        if all_pass:
            print("[PASS] search-wrap KB 模式验证全部通过！")
            print("  - 原始 XPath count==1")
            print("  - Hidden filter 注入后 count==1")
        else:
            print("[FAIL] 部分检查未通过")
        print("=" * 70)

    finally:
        browser.close()
        pw.stop()


if __name__ == '__main__':
    main()
