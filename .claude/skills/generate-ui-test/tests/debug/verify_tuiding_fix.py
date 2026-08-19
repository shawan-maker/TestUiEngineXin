"""直接调用 phase4 行按钮扫描函数，验证退订探测修复"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright
from probe.discover_page import _discover_row_buttons_with_hover

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml")
URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"


def run():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    cookie_str = config["cookie"]
    domain = config["cookie_domain"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            no_viewport=True,
            ignore_https_errors=True,
        )

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
        print(f"viewport: {page.evaluate('[window.innerWidth, window.innerHeight]')}")
        print("=" * 70)

        # 直接调用 phase4 的行按钮扫描函数
        row_buttons = _discover_row_buttons_with_hover(page, hover_delay_ms=500, max_rows=3)

        print(f"\nscan_row_buttons_with_hover returned {len(row_buttons)} items")

        # 查找退订
        tuiding = [b for b in row_buttons if "退订" in b["text"]]
        from_expand_all = [b for b in row_buttons if b.get("from_expand")]

        print(f"from_expand items: {len(from_expand_all)}")
        for b in from_expand_all:
            mark = " [TUIDING]" if "退订" in b["text"] else ""
            print(f"  - '{b['text']}'{mark} row={b.get('row_index')} disabled={b.get('disabled')}")

        print()
        if tuiding:
            print("[OK] Found tuiding (退订):")
            for b in tuiding:
                print(f"  text='{b['text']}' from_expand={b.get('from_expand')} locator={b.get('locator')}")
        else:
            print("[FAIL] tuiding (退订) NOT found")

        browser.close()
        return 0 if tuiding else 1


if __name__ == "__main__":
    sys.exit(run())
