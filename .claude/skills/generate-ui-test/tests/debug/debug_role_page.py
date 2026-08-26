#!/usr/bin/env python3
"""
调试 role 页面加载问题
对比 authority-manage 和 role 两个页面的加载过程
"""
import json
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

COOKIE_STR = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; JSESSIONID=C58240130D0FF1A70B6AFDDC925686D5; estack_lang=zh-CN; accessToken=80ec60f7-4788-4e8d-8cad-14a124b30503"
TARGET_URL = "http://10.151.37.249"
AUTHORITY_URL = "http://10.151.37.249/estack/web/estack/user-center/user-manage/authority-manage"
ROLE_URL = "http://10.151.37.249/estack/web/estack/user-center/user-manage/role"

TOKEN_KEYS = {'accessToken', 'access_token', 'token', 'jwt', 'auth_token'}

def parse_cookie(cookie_str, domain):
    """解析 cookie 字符串为 Playwright 格式"""
    cookies = []
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': domain,
                'path': '/'
            })
    return cookies

def test_page(page, url, label):
    """测试单个页面的加载过程"""
    print(f"\n{'='*60}")
    print(f"测试: {label}")
    print(f"URL: {url}")
    print(f"{'='*60}")

    # 1. 导航到根 URL
    print("\n[1] 导航到根 URL...")
    root_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
    print(f"    Root URL: {root_url}")
    page.goto(root_url, wait_until='domcontentloaded', timeout=15000)
    print(f"    当前 URL: {page.url}")

    # 2. 检查初始 localStorage
    print("\n[2] 初始 localStorage...")
    ls = page.evaluate("() => Object.keys(localStorage)")
    print(f"    Keys: {ls}")

    # 3. 手动设置 localStorage
    print("\n[3] 设置 localStorage...")
    cookies = parse_cookie(COOKIE_STR, urlparse(url).hostname)
    local_storage = {}
    for c in cookies:
        if c['name'] in TOKEN_KEYS:
            local_storage[c['name']] = c['value']

    if local_storage:
        page.evaluate("""(items) => {
            for (let i = 0; i < items.length; i += 2) {
                localStorage.setItem(items[i], items[i+1]);
            }
        }""", [k for kv in local_storage.items() for k in kv])
        print(f"    设置: {list(local_storage.keys())}")

    # 验证设置
    ls_after = page.evaluate("() => Object.keys(localStorage)")
    print(f"    Keys after: {ls_after}")

    # 4. 检查 cookie
    print("\n[4] 当前 cookie...")
    cookies_after = page.context.cookies()
    print(f"    Cookie count: {len(cookies_after)}")
    for c in cookies_after:
        print(f"      {c['name']}: {c['value'][:30]}...")

    # 5. 导航到目标 URL
    print(f"\n[5] 导航到目标 URL...")
    print(f"    Target: {url}")
    page.goto(url, wait_until='domcontentloaded', timeout=15000)
    print(f"    当前 URL: {page.url}")

    # 6. 等待并检查页面状态
    print("\n[6] 页面状态检查...")
    for i in range(6):
        time.sleep(1)

        # 检查 URL 是否变化
        current_url = page.url
        url_changed = current_url != url

        # 检查表单元素
        forms = page.evaluate("""() => {
            return document.querySelectorAll('input, textarea, select, button').length;
        }""")

        # 检查表格行
        rows = page.evaluate("""() => {
            return document.querySelectorAll('table tbody tr, .el-table__row').length;
        }""")

        # 检查 loading 状态
        loading = page.evaluate("""() => {
            const mask = document.querySelector('.el-loading-mask');
            return mask && mask.style.display !== 'none';
        }""")

        # 检查页面标题
        title = page.title()

        print(f"    [{i}s] URL={current_url[:80]}...")
        print(f"         forms={forms}, rows={rows}, loading={loading}, title='{title}'")

        if url_changed:
            print(f"         [WARN] URL changed! (was: {url[:60]}...)")

        if forms > 0 and rows > 0 and not loading:
            print(f"    [OK] page loaded")
            break

    # 7. 截图保存
    screenshot_path = f"debug_{label}.png"
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"\n[7] 截图保存: {screenshot_path}")

    # 8. 检查关键元素
    print("\n[8] 关键元素检查...")

    # Element UI 框架检测
    el_ui = page.evaluate("""() => {
        return {
            'el-button': document.querySelectorAll('.el-button').length,
            'el-table': document.querySelectorAll('.el-table').length,
            'el-form': document.querySelectorAll('.el-form').length,
            'el-dialog': document.querySelectorAll('.el-dialog').length,
        };
    }""")
    print(f"    Element UI: {el_ui}")

    # 按钮列表
    buttons = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        return Array.from(btns).slice(0, 10).map(b => ({
            text: b.textContent.trim(),
            classes: b.className,
            visible: b.offsetParent !== null
        }));
    }""")
    print(f"    Buttons (前10个): {len(buttons)} total")
    for b in buttons:
        print(f"      '{b['text']}' visible={b['visible']} class={b['classes']}")

    return forms > 0 or rows > 0

def main():
    print("="*60)
    print("调试: role 页面加载问题")
    print("="*60)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,  # 有头模式，方便观察
            args=['--disable-dev-shm-usage', '--disable-gpu'],
            slow_mo=500
        )

        domain = urlparse(AUTHORITY_URL).hostname
        cookies = parse_cookie(COOKIE_STR, domain)

        print(f"\nCookie 解析:")
        print(f"  Domain: {domain}")
        print(f"  Cookie count: {len(cookies)}")
        for c in cookies:
            print(f"    {c['name']}: {c['value'][:30]}...")

        context = browser.new_context(
            no_viewport=True,
            ignore_https_errors=True
        )
        context.add_cookies(cookies)
        print(f"\n[OK] Cookie injected to context")

        # 测试 authority-manage
        page1 = context.new_page()
        success1 = test_page(page1, AUTHORITY_URL, "authority-manage")

        # 测试 role（同一个 context）
        page2 = context.new_page()
        success2 = test_page(page2, ROLE_URL, "role")

        print("\n" + "="*60)
        print("Result:")
        print(f"  authority-manage: {'SUCCESS' if success1 else 'FAILED'}")
        print(f"  role: {'SUCCESS' if success2 else 'FAILED'}")
        print("="*60)

        input("\nPress Enter to close browser...")
        browser.close()

if __name__ == '__main__':
    main()
