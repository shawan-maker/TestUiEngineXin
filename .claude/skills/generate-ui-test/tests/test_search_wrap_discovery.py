#!/usr/bin/env python3
"""验证 search-wrap 元素是否能被 Phase 4 探测发现。

独立脚本：直接控制 Playwright 浏览器（忽略 HTTPS 错误），
调用 discover_page 的 JS 扫描逻辑验证 search-wrap 发现能力。

用法:
    cd .claude/skills/generate-ui-test
    python tests/test_search_wrap_discovery.py
"""

import json
import os
import sys

# Ensure tools/ is on sys.path
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
sys.path.insert(0, TOOLS_DIR)

URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"
COOKIE = (
    "sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%7D%2C%22%24device_id%22%3A%2219f8deb566317b8-096a7938f589068-4c657b58-3686400-19f8deb56641354%22%7D; "
    "__upayegisid=05f70a56-b8ce-43dc-a7f3-41904389f37fb5; "
    "estack_lang=zh-CN; "
    "platformTraffic=true; "
    "activeUserRatio=true; "
    "onlineUserCount=true; "
    "visitDuration=true; "
    "accessToken=d77df668-5d53-4da4-9d08-9c18fdf31423"
)
MODULE = "compute_vm"


def main():
    from playwright.sync_api import sync_playwright
    from probe.discover_page import discover_all_elements, _navigate_with_fallback
    from probe.probe_element import parse_cookie
    from urllib.parse import urlparse
    from core.wait_utils import wait_for_dom_stable as _wait_for_dom_stable

    print("=" * 70)
    print("[TEST] search-wrap 探测验证")
    print(f"  URL: {URL}")
    print(f"  Module: {MODULE}")
    print("=" * 70)

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage', '--disable-gpu',
                  '--ignore-certificate-errors'],
        )
        domain = urlparse(URL).hostname
        cookies = parse_cookie(COOKIE, domain)

        # 关键：ignore_https_errors=True 处理内网/测试环境证书问题
        context = browser.new_context(no_viewport=True, ignore_https_errors=True)
        context.add_cookies(cookies)

        # 注入 localStorage token
        local_storage = {}
        for c in cookies:
            if c['name'] == 'accessToken':
                local_storage['accessToken'] = c['value']
                break

        page = context.new_page()

        # 先导航到根 URL 注入 localStorage
        root_url = f"{urlparse(URL).scheme}://{urlparse(URL).netloc}/"
        print(f"[TEST] Navigating to root: {root_url}")
        try:
            _navigate_with_fallback(page, root_url, timeout_ms=15000)
        except Exception as e:
            print(f"[WARN] Root navigation failed: {e}")

        if local_storage:
            print(f"[TEST] Injecting {len(local_storage)} localStorage keys")
            page.evaluate("""(items) => {
                for (let i = 0; i < items.length; i += 2) {
                    localStorage.setItem(items[i], items[i+1]);
                }
            }""", [k for kv in local_storage.items() for k in kv])

        # 导航到目标 URL
        print(f"[TEST] Navigating to target: {URL}")
        _navigate_with_fallback(page, URL, timeout_ms=15000)
        _wait_for_dom_stable(page, timeout_ms=5000)

        # 检查认证
        if '/login' in page.url:
            print(f"[ERROR] 被重定向到登录页 — Cookie 无效或过期")
            browser.close()
            pw.stop()
            return

        print(f"[TEST] 页面已加载: {page.url}")

        # 二次注入 localStorage（导航后可能被清空）
        if local_storage:
            for k, v in local_storage.items():
                page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])

        # 先手动检查页面上是否有 search-wrap 元素
        print("\n[TEST] === 预检查：DOM 中是否存在 search-wrap ===")
        search_wrap_count = page.evaluate("""() => {
            return document.querySelectorAll('div.search-wrap').length;
        }""")
        print(f"  div.search-wrap count: {search_wrap_count}")

        if search_wrap_count > 0:
            # 检查 search-wrap 元素的可见性和内容
            search_wrap_info = page.evaluate("""() => {
                const els = document.querySelectorAll('div.search-wrap');
                return Array.from(els).map(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return {
                        html: el.outerHTML.slice(0, 200),
                        text: (el.textContent || '').trim().slice(0, 50),
                        class: el.className,
                        visible: rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden',
                        rect: {w: rect.width, h: rect.height, t: rect.top, l: rect.left},
                        hasSearchIcon: !!el.querySelector('.el-icon-search'),
                        children: el.children.length,
                    };
                });
            }""")
            for i, info in enumerate(search_wrap_info):
                print(f"  [{i}] class='{info['class']}', "
                      f"text='{info['text']}', "
                      f"visible={info['visible']}, "
                      f"hasSearchIcon={info['hasSearchIcon']}, "
                      f"rect={info['rect']}")
                print(f"       html={info['html'][:150]}")
        else:
            print("  页面没有 div.search-wrap 元素！")
            # 搜索类似的搜索相关元素
            print("\n[TEST] 搜索相关元素扫描：")
            search_related = page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('[class*="search"]').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        results.push({
                            tag: el.tagName,
                            class: el.className.slice(0, 100),
                            text: (el.textContent || '').trim().slice(0, 50),
                        });
                    }
                });
                document.querySelectorAll('.el-icon-search').forEach(el => {
                    results.push({
                        tag: el.tagName,
                        class: el.className,
                        parent: el.parentElement ? el.parentElement.className.slice(0, 80) : 'none',
                        parentTag: el.parentElement ? el.parentElement.tagName : 'none',
                    });
                });
                return results;
            }""")
            for i, item in enumerate(search_related):
                print(f"  [{i}] {item}")

        # 调用 discover_all_elements 进行完整扫描
        print("\n[TEST] === 调用 discover_all_elements ===")
        list_elements = discover_all_elements(page)

        buttons = list_elements.get('buttons', [])
        print(f"\n[TEST] buttons 总数: {len(buttons)}")

        # 查找 search-button 类型
        search_buttons = [b for b in buttons if b.get('type') == 'search-button']
        print(f"[TEST] search-button 类型: {len(search_buttons)}")

        # 查找含搜索/搜索图标文本的
        search_text = [b for b in buttons if '搜索' in b.get('text', '') or '查询' in b.get('text', '')]
        print(f"[TEST] 含'搜索/查询'文本: {len(search_text)}")

        # 打印所有 search 相关条目
        all_search = set()
        for b in search_buttons + search_text:
            all_search.add(id(b))
            text = b.get('text', '')
            btype = b.get('type', '')
            locator = b.get('locator', '')
            verified = b.get('verified', False)
            print(f"\n  [FOUND] text='{text}', type='{btype}', "
                  f"verified={verified}")
            if locator:
                print(f"           locator='{locator[:120]}'")

        if not (search_buttons or search_text):
            print("\n[WARN] 未发现任何搜索相关按钮")
            print("\n[DEBUG] 所有 buttons 列表（前 30 个）:")
            for i, btn in enumerate(buttons[:30]):
                print(f"  [{i}] text='{btn.get('text', '')}', "
                      f"type='{btn.get('type', '')}'")

        # 保存完整结果
        output_dir = os.path.join(os.path.dirname(__file__), '..', '_probe')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, 'test_search_wrap_discovery.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(list_elements, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] Full result saved to: {output_path}")

    finally:
        browser.close()
        pw.stop()


if __name__ == '__main__':
    main()
