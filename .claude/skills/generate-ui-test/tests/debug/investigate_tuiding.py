# -*- coding: utf-8 -*-
"""Investigate tuiding elements in detail"""
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

        # Get detailed info about all "退订" elements
        result = page.evaluate("""
        (() => {
            const elements = [];
            const xpath = "//*[contains(text(),'退订')]";
            const xpathResult = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);

            for (let i = 0; i < xpathResult.snapshotLength; i++) {
                const el = xpathResult.snapshotItem(i);
                const rect = el.getBoundingClientRect();
                const text = el.textContent || '';
                const innerText = el.innerText || '';
                const tag = el.tagName.toLowerCase();
                const className = el.className || '';
                const id = el.id || '';

                // Check ancestors
                let ancestorInfo = [];
                let p = el.parentElement;
                for (let j = 0; j < 5 && p; j++) {
                    ancestorInfo.push({
                        tag: p.tagName.toLowerCase(),
                        class: p.className || '',
                        id: p.id || '',
                        hasXPlacement: p.hasAttribute('x-placement'),
                        xPlacement: p.getAttribute('x-placement') || ''
                    });
                    p = p.parentElement;
                }

                elements.push({
                    tag: tag,
                    id: id,
                    className: className,
                    text: text.substring(0, 100),
                    innerText: innerText.substring(0, 100),
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
                    visible: rect.width > 0 && rect.height > 0,
                    ancestors: ancestorInfo
                });
            }

            return elements;
        })()
        """)

        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))

        browser.close()


if __name__ == "__main__":
    run()
