#!/usr/bin/env python3
"""
最小复现：对比 authority-manage 和 role 的导航差异
"""
from playwright.sync_api import sync_playwright
import time

COOKIE = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; JSESSIONID=C58240130D0FF1A70B6AFDDC925686D5; estack_lang=zh-CN; accessToken=80ec60f7-4788-4e8d-8cad-14a124b30503"

COUNT_JS = """(() => {
    const forms = document.querySelectorAll('input.el-input__inner, textarea.el-textarea__inner, .el-select, .el-form-item, button').length;
    const rows = document.querySelectorAll('tbody tr').length;
    return { forms, rows };
})()"""

def count(page, label):
    c = page.evaluate(COUNT_JS)
    print(f"  [{label}] URL={page.url[:70]}  forms={c['forms']} rows={c['rows']}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(no_viewport=True)

    # 注入 cookie
    for item in COOKIE.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            context.add_cookies([{
                'name': name.strip(),
                'value': value.strip(),
                'domain': '10.151.37.249',
                'path': '/'
            }])

    page = context.new_page()

    # Step 1: 导航到 root URL
    print("=== Step 1: Navigate to root URL ===")
    page.goto('http://10.151.37.249/', wait_until='domcontentloaded', timeout=15000)
    count(page, 'root')

    # Step 2: 设置 localStorage
    print("\n=== Step 2: Set localStorage ===")
    page.evaluate("() => localStorage.setItem('accessToken', '80ec60f7-4788-4e8d-8cad-14a124b30503')")
    count(page, 'after localStorage')

    # Step 3: 导航到 role
    print("\n=== Step 3: Navigate to role ===")
    page.goto('http://10.151.37.249/estack/web/estack/user-center/user-manage/role',
              wait_until='domcontentloaded', timeout=15000)

    for i in range(8):
        page.wait_for_timeout(1000)
        count(page, f'{i}s')

    browser.close()
