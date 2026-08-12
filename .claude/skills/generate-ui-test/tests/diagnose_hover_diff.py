"""精细诊断：两种方法的 hover 和 popover 差异"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml")
URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"


def scan_popover_full(page):
    """扫描 popover 完整信息"""
    return page.evaluate("""
    (() => {
        const poppers = document.querySelectorAll('.el-popover[x-placement], div[x-placement].el-popper');
        const results = [];

        for (const popper of poppers) {
            const rect = popper.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;

            const items = [];
            popper.querySelectorAll('div.clickClass').forEach(el => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const visible = r.width > 0 && r.height > 0
                    && style.display !== 'none'
                    && style.visibility !== 'hidden';
                const text = (el.textContent || '').trim().replace(/\\s*(new|hot)\\s*/gi, '').trim();
                if (text) {
                    items.push({ text, visible, rect: {x: Math.round(r.x), y: Math.round(r.y)} });
                }
            });

            results.push({
                popperRect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                itemCount: items.length,
                visibleCount: items.filter(i => i.visible).length,
                items: items.filter(i => i.visible)
            });
        }

        return results;
    })()
    """)


def run():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True, ignore_https_errors=True)
        cookies = []
        for part in config["cookie"].split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                cookies.append({"name": name.strip(), "value": value.strip(),
                                "domain": config["cookie_domain"], "path": "/"})
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # ─── 测试 1: 只 hover fixed row，然后用行内搜索点击 ───
        print("=" * 70)
        print("测试 1: 只 hover fixed row + 行内搜索")
        print("=" * 70)

        page.evaluate("""(i) => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            if (i < fixedRows.length) {
                fixedRows[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                fixedRows[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }""", 0)
        page.wait_for_timeout(1000)

        page.evaluate("""
        (() => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            const row = fixedRows[0];
            if (!row) return;
            let target = null;
            row.querySelectorAll('.el-button, .ec-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, span.el-dropdown-link, .el-dropdown span[style*="cursor"], .ec-dropdown span[style*="cursor"]').forEach(el => {
                const t = (el.textContent || '').trim();
                if (!['更多', 'More', 'more', '...'].includes(t)) return;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return;
                let hidden = false;
                let p = el;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn.includes('is-hidden')) { hidden = true; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none' || st.visibility === 'hidden') { hidden = true; break; }
                    p = p.parentElement;
                }
                if (hidden) return;
                if (!target) target = el;
            });
            if (target) target.click();
        })()
        """)
        page.wait_for_timeout(2000)

        poppers_1 = scan_popover_full(page)
        print(f"  Popover 数量: {len(poppers_1)}")
        for i, p in enumerate(poppers_1):
            has_tuiding = any('退订' in item['text'] for item in p['items'])
            print(f"  [{i}] rect=({p['popperRect']['x']},{p['popperRect']['y']},{p['popperRect']['w']}x{p['popperRect']['h']}) items={p['itemCount']} visible={p['visibleCount']} 退订={has_tuiding}")
            for item in p['items'][:5]:
                tag = " [TUIDING]" if '退订' in item['text'] else ""
                print(f"      '{item['text']}'{tag} at ({item['rect']['x']},{item['rect']['y']})")

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.mouse.click(10, 10)
        page.wait_for_timeout(500)

        # ─── 测试 2: 同时 hover main + fixed row，然后用全局搜索点击 ───
        print()
        print("=" * 70)
        print("测试 2: 同时 hover main + fixed row + 全局搜索 .dropdown-more")
        print("=" * 70)

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
        }""", 0)
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

        poppers_2 = scan_popover_full(page)
        print(f"  Popover 数量: {len(poppers_2)}")
        for i, p in enumerate(poppers_2):
            has_tuiding = any('退订' in item['text'] for item in p['items'])
            print(f"  [{i}] rect=({p['popperRect']['x']},{p['popperRect']['y']},{p['popperRect']['w']}x{p['popperRect']['h']}) items={p['itemCount']} visible={p['visibleCount']} 退订={has_tuiding}")
            for item in p['items'][:5]:
                tag = " [TUIDING]" if '退订' in item['text'] else ""
                print(f"      '{item['text']}'{tag} at ({item['rect']['x']},{item['rect']['y']})")

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.mouse.click(10, 10)
        page.wait_for_timeout(500)

        # ─── 测试 3: 只 hover fixed row，但用全局搜索点击 ───
        print()
        print("=" * 70)
        print("测试 3: 只 hover fixed row + 全局搜索 .dropdown-more")
        print("=" * 70)

        page.evaluate("""(i) => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            if (i < fixedRows.length) {
                fixedRows[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                fixedRows[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
            }
        }""", 0)
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

        poppers_3 = scan_popover_full(page)
        print(f"  Popover 数量: {len(poppers_3)}")
        for i, p in enumerate(poppers_3):
            has_tuiding = any('退订' in item['text'] for item in p['items'])
            print(f"  [{i}] rect=({p['popperRect']['x']},{p['popperRect']['y']},{p['popperRect']['w']}x{p['popperRect']['h']}) items={p['itemCount']} visible={p['visibleCount']} 退订={has_tuiding}")
            for item in p['items'][:5]:
                tag = " [TUIDING]" if '退订' in item['text'] else ""
                print(f"      '{item['text']}'{tag} at ({item['rect']['x']},{item['rect']['y']})")

        browser.close()


if __name__ == "__main__":
    run()
