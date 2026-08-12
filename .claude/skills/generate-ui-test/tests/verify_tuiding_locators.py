"""验证"更多"菜单中"退订"按钮的两个 locator"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud/config.yaml")
URL = "http://console-estack-rz.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"


def run():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    cookie_str = config["cookie"]
    domain = config["cookie_domain"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True, ignore_https_errors=True)

        # inject cookie
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": domain,
                    "path": "/",
                })
        context.add_cookies(cookies)

        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        print(f"URL: {page.url}")
        print("=" * 70)

        # 先 hover 一行，展开"更多"菜单
        page.evaluate("""(i) => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
            if (i < mainRows.length) {
                mainRows[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                mainRows[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
            if (i < fixedRows.length) {
                fixedRows[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                fixedRows[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }""", 1)
        page.wait_for_timeout(1000)

        # 点击"更多"按钮
        page.evaluate("""
        (() => {
            const dms = document.querySelectorAll('.dropdown-more');
            for (const dm of dms) {
                const rect = dm.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                let hidden = false;
                let p = dm;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn && cn.includes('is-hidden')) { hidden = true; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none') { hidden = true; break; }
                    p = p.parentElement;
                }
                if (hidden) continue;
                const trigger = dm.querySelector('.el-dropdown-link, .el-popover__reference');
                if (trigger) { trigger.click(); return; }
            }
        })()
        """)
        page.wait_for_timeout(2000)

        # 测试 Locator 1: 错误的 button locator
        print("\n[测试 1] 错误的 button locator:")
        print("  //button[contains(.,'退订 new') and ancestor::tbody]")
        wrong_locator = "//button[contains(.,'退订 new') and ancestor::tbody]"
        try:
            elements_1 = page.locator(wrong_locator).all()
            print(f"  找到 {len(elements_1)} 个元素")
            for i, el in enumerate(elements_1[:3]):
                text = el.text_content() or ""
                visible = el.is_visible()
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                print(f"    [{i}] tag={tag}, text='{text[:30]}', visible={visible}")
        except Exception as e:
            print(f"  错误: {e}")

        # 测试 Locator 2: 正确的 x-placement locator
        print("\n[测试 2] 正确的 x-placement locator:")
        print("  //*[@x-placement and not(@x-placement='')]//*[contains(text(),'退订')]")
        correct_locator = "//*[@x-placement and not(@x-placement='')]//*[contains(text(),'退订') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]"
        try:
            elements_2 = page.locator(correct_locator).all()
            print(f"  找到 {len(elements_2)} 个元素")
            for i, el in enumerate(elements_2[:3]):
                text = el.text_content() or ""
                visible = el.is_visible()
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                classes = el.evaluate("el => el.className")
                print(f"    [{i}] tag={tag}, text='{text[:30]}', visible={visible}, class='{classes[:50]}'")
        except Exception as e:
            print(f"  错误: {e}")

        # 检查 popover 是否存在
        print("\n[检查] Popover 状态:")
        popovers = page.evaluate("""
        (() => {
            const items = [];
            document.querySelectorAll('div[x-placement]').forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                const placement = el.getAttribute('x-placement');
                const text = (el.textContent || '').trim().substring(0, 100);
                items.push({ placement, visible, text });
            });
            return items;
        })()
        """)
        print(f"  找到 {len(popovers)} 个 popover")
        for i, p in enumerate(popovers[:5]):
            print(f"    [{i}] placement={p['placement']}, visible={p['visible']}, text='{p['text'][:60]}'")

        browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(run())
