"""
调试脚本 v2：验证 token 是否有效 + 测试 userInfo 注入是否能修复问题
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import json


def debug_role_v2():
    print("=" * 80)
    print("调试 v2: 验证 token + userInfo 注入")
    print("=" * 80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # 收集网络响应
        api_responses = []

        def on_response(resp):
            url = resp.url
            if any(kw in url for kw in ['/api/', '/user', '/auth', '/login', '/token', '/info']):
                try:
                    body = resp.text()[:500]
                except:
                    body = "<binary>"
                api_responses.append(f"{resp.status} {resp.request.method} {url}\n  Body: {body}")

        page.on("response", on_response)

        cookie_str = "__upayegisid=69b36a24-4001-4d63-96de-40afa083657f46; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_search_keyword%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%2C%22%24latest_referrer%22%3A%22url%E7%9A%84domain%E8%A7%A3%E6%9E%90%E5%A4%B1%E8%B4%A5%22%7D%2C%22%24device_id%22%3A%221a00f422f341925-0218cad55e52bc2-4c657b58-3686400-1a00f422f3520c1%22%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMWEwMGY1MTBkZTgyNjM4LTAyNjUxNTQ3ZDkzYjM0ZS00YzY1N2I1OC0zNjg2NDAwLTFhMDBmNTEwZGU5Mjg4OSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%7D; JSESSIONID=C58240130D0FF1A70B6AFDDC925686D5; estack_lang=zh-CN; accessToken=80ec60f7-4788-4e8d-8cad-14a124b30503"

        # 注入 Cookie
        cookies = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies.append({"name": name.strip(), "value": value.strip(), "domain": "10.151.37.249", "path": "/"})
        context.add_cookies(cookies)
        print(f"\n[1] 已注入 {len(cookies)} 个 Cookie")

        # 导航到根 URL
        print("\n[2] 导航到根 URL...")
        page.goto("http://10.151.37.249/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        print(f"  URL: {page.url}, Title: {page.title()}")

        # 检查 localStorage 当前状态
        print("\n[3] 检查当前 localStorage 状态:")
        ls_data = page.evaluate("""() => {
            const keys = Object.keys(localStorage);
            const result = {};
            keys.forEach(k => {
                try {
                    result[k] = localStorage.getItem(k).substring(0, 200);
                } catch(e) {
                    result[k] = '<error>';
                }
            });
            return result;
        }""")
        for k, v in ls_data.items():
            print(f"  {k}: {v[:100]}...")

        # 手动注入 accessToken
        print("\n[4] 注入 accessToken 到 localStorage...")
        access_token = "80ec60f7-4788-4e8d-8cad-14a124b30503"
        page.evaluate(f"() => localStorage.setItem('accessToken', '{access_token}')")
        print(f"  OK accessToken 已注入")

        # 刷新看是否有 API 调用获取用户信息
        print("\n[5] 刷新页面，观察 API 调用...")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        print(f"\n  API responses captured: {len(api_responses)}")
        for r in api_responses:
            print(f"  {r}")

        # 再次检查 localStorage
        print("\n[6] 刷新后 localStorage 状态:")
        ls_data2 = page.evaluate("""() => {
            const keys = Object.keys(localStorage);
            const result = {};
            keys.forEach(k => {
                try {
                    result[k] = localStorage.getItem(k).substring(0, 300);
                } catch(e) {
                    result[k] = '<error>';
                }
            });
            return result;
        }""")
        for k, v in ls_data2.items():
            print(f"  {k}: {v[:150]}")

        # 尝试用 fetch API 测试 token 是否有效
        print("\n[7] 用 fetch API 测试 token 有效性...")
        test_result = page.evaluate("""async () => {
            const token = localStorage.getItem('accessToken');
            const urls = [
                '/estack/api/user/info',
                '/estack/api/auth/info',
                '/estack/user-center/api/user/info',
                '/estack/user-center/api/currentUser',
                '/api/user/info',
                '/estack/web/estack/api/user/info',
            ];
            const results = [];
            for (const url of urls) {
                try {
                    const resp = await fetch(url, {
                        headers: {
                            'Authorization': 'Bearer ' + token,
                            'accessToken': token
                        }
                    });
                    const text = await resp.text();
                    results.push(`${resp.status} ${url}: ${text.substring(0, 200)}`);
                } catch(e) {
                    results.push(`ERR ${url}: ${e.message}`);
                }
            }
            return results;
        }""")
        for r in test_result:
            print(f"  {r}")

        # 检查 SPA 正常登录后 localStorage 应该有哪些 key
        print("\n[8] 分析 SPA 需要哪些 localStorage key...")
        spa_analysis = page.evaluate("""() => {
            // 搜索所有 script 标签中关于 userInfo 的引用
            const scripts = document.querySelectorAll('script');
            let userInfoRefs = [];
            scripts.forEach(s => {
                if (s.textContent.includes('userInfo')) {
                    userInfoRefs.push('inline script references userInfo');
                }
            });

            // 检查 __NUXT__ 或 __INITIAL_STATE__
            return {
                hasNuxt: !!window.__NUXT__,
                hasInitialState: !!window.__INITIAL_STATE__,
                hasVueDevtools: !!window.__VUE_DEVTOOLS_GLOBAL_HOOK__,
                localStorageKeys: Object.keys(localStorage),
                sessionStorageKeys: Object.keys(sessionStorage),
            };
        }""")
        print(f"  localStorage keys: {spa_analysis['localStorageKeys']}")
        print(f"  sessionStorage keys: {spa_analysis['sessionStorageKeys']}")
        print(f"  Has __NUXT__: {spa_analysis['hasNuxt']}")
        print(f"  Has __INITIAL_STATE__: {spa_analysis['hasInitialState']}")
        print(f"  Has Vue Devtools: {spa_analysis['hasVueDevtools']}")

        # 截图
        screenshot_path = Path(__file__).parent / "debug_role_v2.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"\n  Screenshot saved: {screenshot_path}")

        print("\n" + "=" * 80)
        print("调试完成")
        print("=" * 80)
        browser.close()


if __name__ == "__main__":
    debug_role_v2()
