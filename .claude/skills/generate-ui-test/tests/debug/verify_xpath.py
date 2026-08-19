"""验证用户提供的 XPath，确认哪个 tbody 是可见的"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml")
URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"

# 用户提供的 XPath
XPATH_MORE_FIXED = "//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//*[contains(text(),'更多') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]"
XPATH_MORE_MAIN = "//div[contains(@class,'el-table__body-wrapper')]/table/tbody/tr[1]//*[contains(text(),'更多') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]"


def run():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    cookie_str = config["cookie"]

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
                    "domain": config["cookie_domain"],
                    "path": "/",
                })
        context.add_cookies(cookies)

        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        print(f"URL: {page.url}")
        print("=" * 70)

        # 1. 检查 tbody 数量和可见性
        tbody_info = page.evaluate("""
        (() => {
            const results = [];

            // 所有 tbody
            document.querySelectorAll('tbody').forEach((tbody, idx) => {
                const rect = tbody.getBoundingClientRect();
                const computedStyle = window.getComputedStyle(tbody);

                // 检查祖先链
                let ancestors = [];
                let hasIsHidden = false;
                let hasDisplayNone = false;
                let hasVisibilityHidden = false;

                let el = tbody;
                while (el && el !== document.body) {
                    const cn = typeof el.className === 'string' ? el.className : (el.className.baseVal || '');
                    const style = window.getComputedStyle(el);

                    if (cn.includes('is-hidden')) hasIsHidden = true;
                    if (style.display === 'none') hasDisplayNone = true;
                    if (style.visibility === 'hidden') hasVisibilityHidden = true;

                    ancestors.push({
                        tag: el.tagName,
                        class: cn.substring(0, 80),
                        display: style.display,
                        visibility: style.visibility
                    });

                    el = el.parentElement;
                }

                // 找到第一个 tr 中的"更多"
                const firstRow = tbody.querySelector('tr');
                let moreElement = null;
                if (firstRow) {
                    const moreEls = firstRow.querySelectorAll('.el-dropdown-link, .el-popover__reference, span');
                    for (const el of moreEls) {
                        if (el.textContent.trim() === '更多') {
                            const rect = el.getBoundingClientRect();
                            moreElement = {
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height
                            };
                            break;
                        }
                    }
                }

                results.push({
                    index: idx,
                    rowCount: tbody.querySelectorAll('tr').length,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    hasIsHidden,
                    hasDisplayNone,
                    hasVisibilityHidden,
                    visible: rect.width > 0 && rect.height > 0 && !hasIsHidden && !hasDisplayNone && !hasVisibilityHidden,
                    ancestors: ancestors.slice(0, 5),
                    hasMoreElement: !!moreElement,
                    moreElement
                });
            });

            return results;
        })()
        """)

        print(f"\n找到 {len(tbody_info)} 个 tbody:")
        for tb in tbody_info:
            vis = "VISIBLE" if tb['visible'] else "HIDDEN"
            reasons = []
            if tb['hasIsHidden']:
                reasons.append("is-hidden")
            if tb['hasDisplayNone']:
                reasons.append("display:none")
            if tb['hasVisibilityHidden']:
                reasons.append("visibility:hidden")

            reason_str = f" ({', '.join(reasons)})" if reasons else ""
            more_str = f", more@({tb['moreElement']['x']:.0f},{tb['moreElement']['y']:.0f})" if tb['hasMoreElement'] else ""

            print(f"  [{tb['index']}] {vis}{reason_str} - {tb['rowCount']} rows, rect=({tb['rect']['x']:.0f},{tb['rect']['y']:.0f},{tb['rect']['width']:.0f}x{tb['rect']['height']:.0f}){more_str}")

            print(f"      Ancestors:")
            for anc in tb['ancestors']:
                print(f"        <{anc['tag']}> class='{anc['class']}' display={anc['display']} visibility={anc['visibility']}")

        # 2. 验证用户提供的 XPath
        print("\n" + "=" * 70)
        print("验证用户提供的 XPath:")

        fixed_result = page.evaluate(f"""
        (() => {{
            const xpath = `{XPATH_MORE_FIXED}`;
            const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            const el = result.singleNodeValue;
            if (!el) return {{ found: false }};

            const rect = el.getBoundingClientRect();
            return {{
                found: true,
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            }};
        }})()
        """)

        main_result = page.evaluate(f"""
        (() => {{
            const xpath = `{XPATH_MORE_MAIN}`;
            const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            const el = result.singleNodeValue;
            if (!el) return {{ found: false }};

            const rect = el.getBoundingClientRect();
            return {{
                found: true,
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            }};
        }})()
        """)

        print(f"  fixed-right XPath: {fixed_result}")
        print(f"  main XPath:         {main_result}")

        if fixed_result['found'] and not main_result['found']:
            print("\n[OK] 用户确认：fixed-right 可见，main 隐藏（is-hidden）")
        elif main_result['found'] and not fixed_result['found']:
            print("\n[!] 实际情况相反：main 可见，fixed-right 隐藏")
        elif fixed_result['found'] and main_result['found']:
            print("\n[!] 两个都可见")
        else:
            print("\n[!] 两个都未找到")

        browser.close()


if __name__ == "__main__":
    run()
