# -*- coding: utf-8 -*-
"""Debug: investigate popover DOM structure for 'tuiding' button
- Wait up to 60s for popover to fully load
- Dump full DOM structure of visible popover items
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud/config.yaml")
URL = "http://console-estack-rz.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"
OUTPUT_PATH = Path(__file__).parent / "tuiding_debug_result.json"


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

        sys.stderr.write("[1] Page loaded, hovering row 1...\n")

        # Hover row 1
        page.evaluate("""(i) => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            if (i < fixedRows.length) {
                fixedRows[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                fixedRows[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }""", 1)
        page.wait_for_timeout(1500)

        sys.stderr.write("[2] Clicking 'more' button...\n")

        # Click the "more" dropdown trigger
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
                if (trigger) { trigger.click(); return 'clicked'; }
            }
            return 'not found';
        })()
        """)

        sys.stderr.write("[3] Waiting for popover to load (polling every 2s, max 60s)...\n")

        # Poll for popover content with 'tuiding' text, wait up to 60s
        for attempt in range(30):  # 30 * 2s = 60s
            result = page.evaluate("""
            (() => {
                const popovers = document.querySelectorAll('div[x-placement]');
                const summary = [];
                for (const pop of popovers) {
                    const rect = pop.getBoundingClientRect();
                    const visible = rect.width > 0 && rect.height > 0;
                    const placement = pop.getAttribute('x-placement');
                    const html = pop.innerHTML.substring(0, 500);
                    const allText = (pop.textContent || '').trim();
                    // Check for tuiding in any form
                    const hasTuiding = allText.includes('\\u9000\\u8BA2');
                    // Count direct children items
                    const childCount = pop.querySelectorAll('div.clickClass, .dropdown-menu-item, a, li').length;
                    const totalElements = pop.querySelectorAll('*').length;

                    summary.push({
                        placement: placement,
                        visible: visible,
                        rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                        hasTuiding: hasTuiding,
                        allTextLength: allText.length,
                        allTextPreview: allText.substring(0, 300),
                        childCount: childCount,
                        totalElements: totalElements,
                        htmlPreview: html
                    });
                }
                return summary;
            })()
            """)

            has_tuiding = any(p.get('hasTuiding') for p in result)
            total_items = sum(p.get('childCount', 0) for p in result)

            sys.stderr.write(f"  [{attempt+1}] {len(result)} popover(s), "
                           f"items={total_items}, has_tuiding={has_tuiding}\n")

            if has_tuiding or (total_items > 5 and attempt > 5):
                # Popover is loaded enough to analyze
                break

            page.wait_for_timeout(2000)

        sys.stderr.write("\n[4] Analyzing popover DOM structure...\n")

        # Deep analysis of the popover
        deep_result = page.evaluate("""
        (() => {
            const popovers = document.querySelectorAll('div[x-placement]');
            const results = [];

            for (const pop of popovers) {
                const rect = pop.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;

                const popInfo = {
                    placement: pop.getAttribute('x-placement'),
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                            w: Math.round(rect.width), h: Math.round(rect.height) },
                    className: pop.className,
                    allItems: [],
                    tuidingItems: [],
                    tuidingAncestors: []
                };

                // Collect ALL direct children that look like menu items
                pop.querySelectorAll('*').forEach(el => {
                    const r = el.getBoundingClientRect();
                    const text = (el.textContent || '').trim();
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');

                    if (text && r.width > 0 && r.height > 0 && text.length < 50) {
                        popInfo.allItems.push({
                            tag: el.tagName.toLowerCase(),
                            className: (el.className || '').toString().substring(0, 80),
                            text: text.substring(0, 60),
                            directText: directText.substring(0, 60),
                            rect: { x: Math.round(r.x), y: Math.round(r.y),
                                    w: Math.round(r.width), h: Math.round(r.height) },
                            role: el.getAttribute('role') || '',
                            ariaLabel: el.getAttribute('aria-label') || ''
                        });
                    }

                    // Check if this element contains 'tuiding'
                    if (text.includes('\\u9000\\u8BA2')) {
                        popInfo.tuidingItems.push({
                            tag: el.tagName.toLowerCase(),
                            className: (el.className || '').toString().substring(0, 80),
                            text: text.substring(0, 60),
                            directText: directText.substring(0, 60),
                            visible: r.width > 0 && r.height > 0,
                            rect: { x: Math.round(r.x), y: Math.round(r.y),
                                    w: Math.round(r.width), h: Math.round(r.height) },
                            innerHTML: el.innerHTML.substring(0, 200),
                            outerHTML: el.outerHTML.substring(0, 300)
                        });

                        // Get ancestor chain
                        const ancestors = [];
                        let p = el.parentElement;
                        for (let i = 0; i < 8 && p; i++) {
                            ancestors.push({
                                tag: p.tagName.toLowerCase(),
                                className: (p.className || '').toString().substring(0, 80),
                                id: p.id || '',
                                hasXPlacement: p.hasAttribute('x-placement'),
                                xPlacement: p.getAttribute('x-placement') || '',
                                role: p.getAttribute('role') || ''
                            });
                            p = p.parentElement;
                        }
                        popInfo.tuidingAncestors.push(ancestors);
                    }
                });

                // Deduplicate items by text
                const seen = new Set();
                popInfo.allItems = popInfo.allItems.filter(item => {
                    const key = item.tag + ':' + item.text;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });

                results.push(popInfo);
            }

            return results;
        })()
        """)

        sys.stderr.write(f"\n[5] Found {len(deep_result)} visible popover(s)\n")

        for i, pop in enumerate(deep_result):
            sys.stderr.write(f"\n  Popover[{i}]: {pop['placement']} at ({pop['rect']['x']},{pop['rect']['y']}) "
                           f"{pop['rect']['w']}x{pop['rect']['h']}\n")
            sys.stderr.write(f"    className: {pop['className'][:80]}\n")
            sys.stderr.write(f"    Total items: {len(pop['allItems'])}\n")
            sys.stderr.write(f"    Tuiding items: {len(pop['tuidingItems'])}\n")

            # Print first 15 items
            for j, item in enumerate(pop['allItems'][:15]):
                sys.stderr.write(f"    [{j:2d}] <{item['tag']}> class='{item['className'][:40]}' "
                               f"text='{item['text'][:30]}' direct='{item['directText'][:30]}'\n")
            if len(pop['allItems']) > 15:
                sys.stderr.write(f"    ... ({len(pop['allItems']) - 15} more items)\n")

            if pop['tuidingItems']:
                sys.stderr.write(f"\n    === TUIDING items ===\n")
                for j, item in enumerate(pop['tuidingItems']):
                    sys.stderr.write(f"    [{j}] <{item['tag']}> class='{item['className']}'\n")
                    sys.stderr.write(f"        text='{item['text']}' direct='{item['directText']}'\n")
                    sys.stderr.write(f"        visible={item['visible']} rect=({item['rect']})\n")
                    sys.stderr.write(f"        outerHTML: {item['outerHTML'][:200]}\n")

            if pop['tuidingAncestors']:
                sys.stderr.write(f"\n    === TUIDING ancestor chains ===\n")
                for j, chain in enumerate(pop['tuidingAncestors']):
                    sys.stderr.write(f"    Chain[{j}]:\n")
                    for k, anc in enumerate(chain):
                        xp = f" x-placement={anc['xPlacement']}" if anc['hasXPlacement'] else ""
                        sys.stderr.write(f"      [{k}] <{anc['tag']}> class='{anc['className']}'{xp}\n")

        # Save full result to JSON
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(deep_result, f, indent=2, ensure_ascii=False)
        sys.stderr.write(f"\n[6] Full result saved to: {OUTPUT_PATH}\n")

        # Also test specific locators
        sys.stderr.write("\n[7] Testing specific locators:\n")
        locators = {
            "x-placement + text": "//*[@x-placement and not(@x-placement='')]//*[contains(text(),'\\u9000\\u8BA2')]",
            "x-placement + . (self)": "//*[@x-placement and not(@x-placement='')]//*[contains(.,'\\u9000\\u8BA2')]",
            "x-placement direct children": "//*[@x-placement and not(@x-placement='')]//*[string-length(normalize-space(text()))>0 and string-length(normalize-space(text()))<20]",
            "clickClass in popover": "//*[@x-placement]//div[contains(@class,'clickClass')]",
            "any div in popover": "//*[@x-placement]//div[string-length(normalize-space(text()))>0 and string-length(normalize-space(text()))<20]",
        }

        for name, loc in locators.items():
            try:
                count = page.locator(f"xpath={loc}").count()
                sys.stderr.write(f"  [{count:3d}] {name}\n")
            except Exception as e:
                sys.stderr.write(f"  [ERR] {name}: {e}\n")

        browser.close()


if __name__ == "__main__":
    run()
