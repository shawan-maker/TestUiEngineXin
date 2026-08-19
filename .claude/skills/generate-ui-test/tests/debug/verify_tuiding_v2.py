# -*- coding: utf-8 -*-
"""Verify tuiding locators with proper encoding"""
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

        # Hover and click "more" button
        page.evaluate("""(i) => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            if (i < fixedRows.length) {
                fixedRows[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                fixedRows[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }""", 1)
        page.wait_for_timeout(1000)

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

        # Get all popover items with detailed info
        result = page.evaluate("""
        (() => {
            const popovers = document.querySelectorAll('div[x-placement]');
            const results = [];

            for (const pop of popovers) {
                const rect = pop.getBoundingClientRect();
                const placement = pop.getAttribute('x-placement');
                const items = [];

                // Get all clickable items
                pop.querySelectorAll('div.clickClass, a, button, span[class*="link"], span[class*="click"]').forEach(el => {
                    const text = (el.textContent || '').trim();
                    if (text) {
                        items.push({
                            tag: el.tagName.toLowerCase(),
                            text: text,
                            class: el.className || '',
                            visible: el.getBoundingClientRect().width > 0
                        });
                    }
                });

                results.push({
                    placement: placement,
                    visible: rect.width > 0,
                    itemCount: items.length,
                    items: items.slice(0, 20)
                });
            }

            return results;
        })()
        """)

        print("Popover status:", file=sys.stderr)
        for i, pop in enumerate(result):
            print(f"  Popover[{i}]: placement={pop['placement']}, visible={pop['visible']}, items={pop['itemCount']}", file=sys.stderr)
            for j, item in enumerate(pop['items'][:10]):
                print(f"    [{j}] {item['tag']}: '{item['text'][:40]}' (visible={item['visible']})", file=sys.stderr)

        # Test locator 1: wrong button locator
        wrong_loc = "//button[contains(.,'退订') and ancestor::tbody]"
        count1 = page.locator(wrong_loc).count()
        print(f"TEST1_BUTTON_LOCATOR: {count1}", file=sys.stderr)

        # Test locator 2: correct x-placement locator
        correct_loc = "//*[@x-placement and not(@x-placement='')]//*[contains(text(),'退订') and not(ancestor-or-self::*[contains(@class,'is-hidden')])]"
        count2 = page.locator(correct_loc).count()
        print(f"TEST2_XPLACEMENT_LOCATOR: {count2}", file=sys.stderr)

        # Test locator 3: broader search
        broad_loc = "//*[contains(text(),'退订')]"
        count3 = page.locator(broad_loc).count()
        print(f"TEST3_BROAD_SEARCH: {count3}", file=sys.stderr)

        browser.close()


if __name__ == "__main__":
    run()
