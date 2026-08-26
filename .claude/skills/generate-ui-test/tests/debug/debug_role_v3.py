"""
调试脚本 v3：验证修复方案 — 先访问 estack 主页让 SPA 初始化，再导航到角色管理
"""
from playwright.sync_api import sync_playwright
from pathlib import Path


def debug_role_v3():
    print("=" * 80)
    print("调试 v3: 验证修复方案 — SPA 预热")
    print("=" * 80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        cookie_str = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; JSESSIONID=C58240130D0FF1A70B6AFDDC925686D5; estack_lang=zh-CN; accessToken=968c37f7-6c31-49eb-9289-f2f3012f26f2; JSESSIONID=D49E08DE10E9AAF2C8EFDB078D428097"

        # 注入 Cookie
        cookies = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies.append({"name": name.strip(), "value": value.strip(), "domain": "10.151.37.249", "path": "/"})
        context.add_cookies(cookies)
        print(f"[1] 已注入 {len(cookies)} 个 Cookie")

        # === 方案：先访问 estack 主页让 SPA 初始化 ===
        estack_home = "http://10.151.37.249/estack/web/estack/"
        print(f"\n[2] 方案: 先访问 estack 主页让 SPA 初始化: {estack_home}")
        page.goto(estack_home, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)
        print(f"  URL: {page.url}, Title: {page.title()}")

        # 检查 SPA 是否自己填充了 userInfo
        print("\n[3] SPA 初始化后 localStorage 状态:")
        ls_data = page.evaluate("""() => {
            const keys = Object.keys(localStorage);
            const result = {};
            keys.forEach(k => {
                try {
                    const val = localStorage.getItem(k);
                    result[k] = val.substring(0, 300);
                } catch(e) {
                    result[k] = '<error>';
                }
            });
            return result;
        }""")
        for k, v in ls_data.items():
            print(f"  {k}: {v[:150]}")

        # 检查是否有 userInfo
        has_user_info = 'userInfo' in ls_data
        print(f"\n  Has userInfo: {has_user_info}")

        if not has_user_info:
            # 尝试通过 estack API 获取用户信息
            print("\n[4] SPA 未自动填充 userInfo，尝试通过 API 获取...")
            user_info_result = page.evaluate("""async () => {
                const token = localStorage.getItem('accessToken') || '';
                const urls = [
                    '/estack/web/estack/api/user-center/user/info',
                    '/estack/web/estack/api/user/info',
                    '/estack/web/estack/user-center/api/user/current',
                    '/estack/web/estack/user-center/user/info',
                    '/estack/web/estack/api/v1/user/info',
                ];
                const results = [];
                for (const url of urls) {
                    try {
                        const resp = await fetch(url, {
                            headers: {
                                'Authorization': 'Bearer ' + token,
                                'accessToken': token,
                                'Content-Type': 'application/json'
                            },
                            credentials: 'include'
                        });
                        const text = await resp.text();
                        results.push(`${resp.status} ${url}: ${text.substring(0, 300)}`);
                        if (resp.status === 200 && text.includes('{')) {
                            return { found: true, url: url, status: resp.status, body: text.substring(0, 500) };
                        }
                    } catch(e) {
                        results.push(`ERR ${url}: ${e.message}`);
                    }
                }
                return { found: false, attempts: results };
            }""")
            print(f"  Result: {user_info_result}")

        # 现在导航到角色管理页面
        role_url = "http://10.151.37.249/estack/web/estack/user-center/user-manage/role"
        print(f"\n[5] 导航到角色管理页面: {role_url}")
        page.goto(role_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        # 检查结果
        body_text = page.evaluate("() => document.body.innerText")
        print(f"\n[6] 页面状态:")
        print(f"  URL: {page.url}")
        print(f"  Body text length: {len(body_text)}")
        if len(body_text) < 1000:
            print(f"  Body:\n---\n{body_text}\n---")
        else:
            print(f"  Body preview:\n---\n{body_text[:500]}\n---")

        # 查找按钮和表格
        btn_count = page.locator("button").count()
        table_count = page.locator(".el-table").count()
        search_input = page.locator("//input[contains(@placeholder,'按角色名称搜索')]").count()
        create_btn = page.locator("(//button[contains(.,'创') and contains(.,'建') and contains(.,'角') and contains(.,'色')])[1]").count()

        print(f"\n  Buttons: {btn_count}")
        print(f"  Tables: {table_count}")
        print(f"  Search input: {search_input}")
        print(f"  Create button: {create_btn}")

        # 截图
        screenshot_path = Path(__file__).parent / "debug_role_v3.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"\n  Screenshot: {screenshot_path}")

        if create_btn > 0:
            print("\n  *** SUCCESS: 创建角色按钮已找到! ***")
        else:
            print("\n  *** FAIL: 创建角色按钮未找到 ***")
            # 再试方案B：手动注入 userInfo
            print("\n[7] 尝试方案B: 手动构造 userInfo 注入...")
            page.evaluate("""() => {
                // 构造最小化 userInfo
                const userInfo = JSON.stringify({
                    userId: 'test-user',
                    username: 'test',
                    realName: 'Test User',
                    roles: ['admin'],
                    permissions: []
                });
                localStorage.setItem('userInfo', userInfo);
            }""")
            # 重新导航
            page.goto(role_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(5000)

            create_btn2 = page.locator("(//button[contains(.,'创') and contains(.,'建') and contains(.,'角') and contains(.,'色')])[1]").count()
            print(f"  After manual userInfo injection - Create button: {create_btn2}")

            screenshot_path2 = Path(__file__).parent / "debug_role_v3b.png"
            page.screenshot(path=str(screenshot_path2), full_page=True)
            print(f"  Screenshot: {screenshot_path2}")

        print("\n" + "=" * 80)
        browser.close()


if __name__ == "__main__":
    debug_role_v3()
