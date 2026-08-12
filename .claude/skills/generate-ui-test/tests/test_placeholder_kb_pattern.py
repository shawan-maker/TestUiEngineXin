#!/usr/bin/env python3
"""验证 input-generic KB 新增 placeholder pattern。

验证项：
  1. KB 加载：input-generic 返回 3 条 patterns
  2. 第3条 pattern 格式化后包含 @placeholder
  3. 真实页面 count 验证（eStack VM 列表页的搜索输入框）
  4. hidden filter 注入后 count 仍为 1
  5. 对比：前2条 pattern count=0，第3条 count=1
"""

import os
import sys

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
sys.path.insert(0, TOOLS_DIR)

URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"
COOKIE = (
    "sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%7D; "
    "__upayegisid=05f70a56-b8ce-43dc-a7f3-41904389f37fb5; "
    "estack_lang=zh-CN; platformTraffic=true; activeUserRatio=true; "
    "onlineUserCount=true; visitDuration=true; "
    "accessToken=d77df668-5d53-4da4-9d08-9c18fdf31423"
)


def test_kb_loading():
    """测试1-2: KB 加载验证"""
    from probe.probe_utils import get_all_patterns
    from probe.probe_element import _safe_format

    patterns = get_all_patterns('input-generic')
    print(f"\n[PASS] input-generic KB patterns: {len(patterns)}")
    for i, p in enumerate(patterns):
        print(f"  [{i}] {p}")

    assert len(patterns) == 3, f"Expected 3 patterns, got {len(patterns)}"

    # 第3条应包含 placeholder
    p3 = patterns[2]
    assert 'placeholder' in p3, f"3rd pattern missing placeholder: {p3}"
    print(f"\n[PASS] 3rd pattern contains @placeholder")

    # 格式化验证
    label = "选择实例属性项搜索，或输入关键字搜索"
    formatted = _safe_format(p3, {'label': label})
    assert '{' not in formatted, f"Unresolved placeholder: {formatted}"
    assert label in formatted, f"Label not in formatted: {formatted}"
    print(f"[PASS] Formatted: {formatted}")

    return True


def test_real_page():
    """测试3-5: 真实页面 count 验证"""
    from playwright.sync_api import sync_playwright
    from probe.probe_element import parse_cookie
    from probe.discover_page import _navigate_with_fallback
    from core.wait_utils import wait_for_dom_stable
    from core.xpath_utils import inject_hidden_filter
    from probe.probe_utils import get_all_patterns
    from probe.probe_element import _safe_format
    from urllib.parse import urlparse

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

        if '/login' in page.url:
            print("[SKIP] Cookie expired, cannot test real page")
            return None

        label = "选择实例属性项搜索，或输入关键字搜索"
        patterns = get_all_patterns('input-generic')

        print(f"\n{'='*60}")
        print(f"[TEST] Real page count verification")
        print(f"  URL: {page.url}")
        print(f"  Label: {label}")
        print(f"{'='*60}")

        results = []
        for i, p in enumerate(patterns):
            xpath = _safe_format(p, {'label': label})
            count = page.locator(f"xpath={xpath}").count()
            status = "PASS" if (i < 2 and count == 0) or (i == 2 and count == 1) else "FAIL"
            results.append((i, xpath, count, status))
            print(f"  [{i}] count={count} {status}  {xpath[:80]}")

        # 测试 hidden filter 注入
        p3_xpath = _safe_format(patterns[2], {'label': label})
        injected = inject_hidden_filter(f"xpath={p3_xpath}")
        injected_xpath = injected.replace('xpath=', '', 1) if injected.startswith('xpath=') else injected
        count_injected = page.locator(f"xpath={injected_xpath}").count()
        print(f"\n  Hidden filter injected:")
        print(f"  count={count_injected} {'PASS' if count_injected == 1 else 'FAIL'}")
        print(f"  {injected[:100]}")

        all_pass = (
            results[0][2] == 0 and
            results[1][2] == 0 and
            results[2][2] == 1 and
            count_injected == 1
        )

        if all_pass:
            print(f"\n[PASS] All real page tests passed!")
        else:
            print(f"\n[FAIL] Some tests failed")

        return all_pass

    finally:
        browser.close()
        pw.stop()


def main():
    print("=" * 60)
    print("input-generic placeholder pattern verification")
    print("=" * 60)

    # Test 1-2: KB loading (no browser needed)
    kb_ok = test_kb_loading()

    # Test 3-5: Real page (needs browser)
    page_ok = test_real_page()

    print(f"\n{'='*60}")
    if kb_ok and page_ok is not None:
        if page_ok:
            print("[PASS] All tests passed")
        else:
            print("[FAIL] Real page tests failed")
    elif page_ok is None:
        print("[PASS] KB tests passed, real page skipped (cookie expired)")
    else:
        print("[FAIL] Some tests failed")
    print("=" * 60)


if __name__ == '__main__':
    main()
