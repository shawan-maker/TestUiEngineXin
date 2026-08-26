"""
调试脚本：访问控制-角色管理-创建角色
问题：页面打开后没有元素内容（每次重复运行都这样）
目的：增加详细日志，诊断页面加载问题
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import time


def debug_role_creation():
    print("=" * 80)
    print("调试脚本：访问控制-角色管理-创建角色")
    print("=" * 80)

    with sync_playwright() as p:
        # 1. 打开浏览器（headed 模式）
        print("\n[Step 1] 打开浏览器（headed 模式）")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # 收集控制台错误
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # 收集网络请求失败
        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}"))

        # 收集所有网络响应（状态码非200）
        bad_responses = []
        page.on("response", lambda resp: bad_responses.append(
            f"{resp.request.method} {resp.url} -> {resp.status}"
        ) if resp.status >= 400 else None)

        print("  OK 浏览器已打开")

        # 2. 导航到目标域
        target_url = "http://10.151.37.249"
        print(f"\n[Step 2] 导航到目标域: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        print(f"  OK 当前 URL: {page.url}")
        print(f"  OK 页面标题: {page.title()}")

        # 3. 注入 Cookie
        print("\n[Step 3] 注入 Cookie")
        cookie_str = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; JSESSIONID=C58240130D0FF1A70B6AFDDC925686D5; estack_lang=zh-CN; accessToken=80ec60f7-4788-4e8d-8cad-14a124b30503"

        cookies = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": "10.151.37.249",
                    "path": "/"
                })
        context.add_cookies(cookies)
        print(f"  OK 已注入 {len(cookies)} 个 Cookie")

        # 4. 注入 localStorage
        print("\n[Step 4] 注入 localStorage")
        access_token = None
        for c in cookies:
            if c["name"] == "accessToken":
                access_token = c["value"]
                break

        if access_token:
            page.evaluate(f"""() => {{
                localStorage.setItem('accessToken', '{access_token}');
            }}""")
            print(f"  OK 已注入 localStorage: accessToken={access_token[:30]}...")

        # 5. 刷新页面
        print("\n[Step 5] 刷新页面使认证生效")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        print(f"  OK 页面已刷新, URL: {page.url}")

        # 6. 导航到角色管理页面
        role_url = "http://10.151.37.249/estack/web/estack/user-center/user-manage/role"
        print(f"\n[Step 6] 导航到角色管理页面: {role_url}")
        page.goto(role_url, wait_until="domcontentloaded", timeout=30000)
        print(f"  OK 当前 URL: {page.url}")
        print(f"  OK 页面标题: {page.title()}")

        # 7. 等待 loading 消失
        print("\n[Step 7] 等待 loading 消失")
        page.wait_for_timeout(5000)

        # 检查 loading mask
        loading_count = page.locator('[class*="el-loading-mask"]').count()
        visible_loading = page.locator('[class*="el-loading-mask"]:visible').count()
        print(f"  Loading masks total: {loading_count}, visible: {visible_loading}")

        # 8. 详细诊断
        print("\n[Step 8] 页面状态诊断")

        # 8.1 body 文本
        body_text = page.evaluate("() => document.body.innerText")
        print(f"  [8.1] Body text length: {len(body_text)}")
        if len(body_text) < 1000:
            print(f"       Body content:\n---\n{body_text}\n---")
        else:
            print(f"       Body preview (first 500 chars):\n---\n{body_text[:500]}\n---")

        # 8.2 检查是否被重定向到登录页
        current_url = page.url
        print(f"  [8.2] Current URL: {current_url}")
        if "login" in current_url.lower():
            print("       *** WARNING: 被重定向到登录页! ***")

        # 8.3 检查 #app 容器
        dom_info = page.evaluate("""() => {
            const app = document.querySelector('#app');
            const iframes = document.querySelectorAll('iframe');
            const tables = document.querySelectorAll('.el-table, table');
            const buttons = document.querySelectorAll('button');
            const forms = document.querySelectorAll('form, .el-form');
            const allElements = document.body.querySelectorAll('*');
            return {
                hasApp: !!app,
                appInnerHTML: app ? app.innerHTML.substring(0, 500) : 'N/A',
                appChildCount: app ? app.children.length : 0,
                iframeCount: iframes.length,
                tableCount: tables.length,
                buttonCount: buttons.length,
                formCount: forms.length,
                totalElements: allElements.length
            };
        }""")
        print(f"  [8.3] #app exists: {dom_info['hasApp']}")
        print(f"       #app children: {dom_info['appChildCount']}")
        print(f"       Total DOM elements: {dom_info['totalElements']}")
        print(f"       Tables: {dom_info['tableCount']}")
        print(f"       Buttons: {dom_info['buttonCount']}")
        print(f"       Forms: {dom_info['formCount']}")
        print(f"       Iframes: {dom_info['iframeCount']}")
        print(f"       #app innerHTML (first 500):\n       {dom_info['appInnerHTML']}")

        # 8.4 网络错误
        print(f"\n  [8.4] Failed requests: {len(failed_requests)}")
        for r in failed_requests[:10]:
            print(f"       {r[:150]}")

        print(f"\n  [8.5] Bad responses (4xx/5xx): {len(bad_responses)}")
        for r in bad_responses[:10]:
            print(f"       {r[:150]}")

        print(f"\n  [8.6] Console errors: {len(console_errors)}")
        for e in console_errors[:10]:
            print(f"       {e[:150]}")

        # 9. 再等 10 秒
        print("\n[Step 9] 再等 10 秒观察延迟加载...")
        page.wait_for_timeout(10000)

        body_text2 = page.evaluate("() => document.body.innerText")
        print(f"  Body text after 10s: {len(body_text2)} chars")
        dom_info2 = page.evaluate("""() => {
            const app = document.querySelector('#app');
            const tables = document.querySelectorAll('.el-table, table');
            const buttons = document.querySelectorAll('button');
            return {
                appChildCount: app ? app.children.length : 0,
                tableCount: tables.length,
                buttonCount: buttons.length,
                totalElements: document.body.querySelectorAll('*').length
            };
        }""")
        print(f"  DOM after 10s: children={dom_info2['appChildCount']}, tables={dom_info2['tableCount']}, buttons={dom_info2['buttonCount']}, total={dom_info2['totalElements']}")

        # 9.1 再次检查网络错误
        print(f"  New failed requests: {len(failed_requests)}")
        for r in failed_requests[10:]:
            print(f"       {r[:150]}")
        print(f"  New bad responses: {len(bad_responses)}")
        for r in bad_responses[10:]:
            print(f"       {r[:150]}")

        # 10. 尝试查找创建角色按钮
        print("\n[Step 10] 查找创建角色按钮")
        btn_xpath = "(//button[contains(.,'创') and contains(.,'建') and contains(.,'角') and contains(.,'色')])[1]"
        try:
            btn = page.locator(btn_xpath)
            count = btn.count()
            print(f"  Button match count: {count}")
            if count > 0:
                print(f"  Button visible: {btn.is_visible()}")
                print(f"  Button text: {btn.text_content()}")
        except Exception as e:
            print(f"  Button search failed: {e}")

        # 11. 尝试查找搜索框（角色列表页的标志元素）
        print("\n[Step 11] 查找搜索框")
        search_xpath = "//input[contains(@placeholder,'按角色名称搜索')]"
        try:
            search = page.locator(search_xpath)
            count = search.count()
            print(f"  Search input match count: {count}")
            if count > 0:
                print(f"  Search input visible: {search.is_visible()}")
        except Exception as e:
            print(f"  Search input search failed: {e}")

        # 12. 截图
        print("\n[Step 12] 保存截图")
        screenshot_path = Path(__file__).parent / "debug_role_page.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"  OK 截图已保存: {screenshot_path}")

        # 13. 尝试替代方案：通过首页菜单导航到角色管理
        print("\n[Step 13] 尝试替代方案：通过菜单导航")
        # 先回到首页
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # 检查侧边栏是否有菜单
        sidebar = page.evaluate("""() => {
            const menus = document.querySelectorAll('.el-menu, .el-submenu, [class*=sidebar], [class*=menu]');
            const menuItems = document.querySelectorAll('.el-menu-item, .el-submenu__title');
            return {
                menuCount: menus.length,
                menuItemCount: menuItems.length,
                menuTexts: Array.from(menuItems).slice(0, 20).map(el => el.textContent.trim().substring(0, 30))
            };
        }""")
        print(f"  Menus: {sidebar['menuCount']}, Menu items: {sidebar['menuItemCount']}")
        if sidebar['menuTexts']:
            for t in sidebar['menuTexts']:
                print(f"    - {t}")

        print("\n" + "=" * 80)
        print("调试完成，浏览器保持打开 15 秒...")
        print("=" * 80)
        page.wait_for_timeout(15000)
        browser.close()


if __name__ == "__main__":
    debug_role_creation()
