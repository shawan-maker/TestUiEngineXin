"""对比两种展开触发器查找方式，同一会话内确认根因"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import yaml
from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml")
URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"


def scan_popover_items(page):
    """扫描当前打开的 popover 中的菜单项"""
    return page.evaluate("""
    (() => {
        const items = [];
        document.querySelectorAll('div[x-placement] div.clickClass').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            let ancestorHidden = false;
            let p = el.parentElement;
            while (p) {
                const ps = window.getComputedStyle(p);
                if (ps.display === 'none' || ps.visibility === 'hidden') { ancestorHidden = true; break; }
                p = p.parentElement;
            }
            const visible = rect.width > 0 && rect.height > 0
                && style.display !== 'none' && style.visibility !== 'hidden'
                && !ancestorHidden;
            const text = (el.textContent || '').trim().replace(/\\s*(new|hot)\\s*/gi, '').trim();
            if (!text) return;
            items.push({ text, visible, rect: {x: Math.round(rect.x), y: Math.round(rect.y)} });
        });
        return items.filter(i => i.visible);
    })()
    """)


def close_popover(page):
    """关闭 popover"""
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    page.mouse.click(10, 10)
    page.wait_for_timeout(500)


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

        # Hover row 0
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

        # ─── 方法 A: discover_page.py 方式（fixedRows 优先 + 行内搜索） ───
        print("=" * 70)
        print("方法 A: discover_page.py（fixedRows 优先 + 行内搜索 + BUG-14 过滤）")
        print("=" * 70)

        result_a = page.evaluate("""
        (() => {
            const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
            const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
            const row = (0 < fixedRows.length) ? fixedRows[0]
                        : ((0 < mainRows.length) ? mainRows[0] : null);
            if (!row) return {error: 'no row'};

            // 统计 row 内所有 "更多" 候选
            const candidates = [];
            row.querySelectorAll('.el-button, .ec-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, span.el-dropdown-link, .el-dropdown span[style*="cursor"], .ec-dropdown span[style*="cursor"]').forEach(el => {
                const t = (el.textContent || '').trim();
                if (!['更多', 'More', 'more', '...'].includes(t)) return;
                const rect = el.getBoundingClientRect();
                let hidden = false;
                let reason = '';
                let p = el;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn.includes('is-hidden')) { hidden = true; reason = 'is-hidden'; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none') { hidden = true; reason = 'display:none'; break; }
                    if (st.visibility === 'hidden') { hidden = true; reason = 'visibility:hidden'; break; }
                    p = p.parentElement;
                }
                candidates.push({
                    text: t,
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    visible: rect.width > 0 && rect.height > 0 && !hidden,
                    hiddenReason: reason,
                    // 记录元素所在的 tbody 类型
                    tbodyType: el.closest('.el-table__fixed-right') ? 'fixed-right'
                              : el.closest('.el-table__fixed') ? 'fixed'
                              : el.closest('.el-table__body-wrapper') ? 'main'
                              : 'unknown',
                });
            });

            // BUG-14 过滤后的第一个可见
            let target = null;
            for (const c of candidates) {
                if (c.visible) { target = c; break; }
            }

            return { candidates, target };
        })()
        """)

        print(f"  候选数: {len(result_a.get('candidates', []))}")
        for c in result_a.get('candidates', []):
            vis = "[VIS]" if c['visible'] else f"[HID:{c['hiddenReason']}]"
            print(f"    {vis} '{c['text']}' in {c['tbodyType']} rect=({c['rect']['x']},{c['rect']['y']},{c['rect']['w']}x{c['rect']['h']})")

        if result_a.get('target'):
            t = result_a['target']
            print(f"  -> 选中的触发器: '{t['text']}' in {t['tbodyType']} at ({t['rect']['x']},{t['rect']['y']})")

            # 点击
            page.evaluate("""
            (() => {
                const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
                const row = (0 < fixedRows.length) ? fixedRows[0]
                            : ((0 < mainRows.length) ? mainRows[0] : null);
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

            items_a = scan_popover_items(page)
            has_tuiding_a = any('退订' in i['text'] for i in items_a)
            print(f"  popover 菜单项: {len(items_a)} 个, 有退订: {has_tuiding_a}")
            for item in items_a[:5]:
                print(f"    '{item['text']}' at ({item['rect']['x']},{item['rect']['y']})")
            if len(items_a) > 5:
                print(f"    ... ({len(items_a) - 5} more)")
        else:
            print(f"  [FAIL] 没有找到可见触发器")
            has_tuiding_a = False

        close_popover(page)

        # ─── 方法 B: debug_headed_vs_headless.py 方式（全局搜索 .dropdown-more） ───
        print()
        print("=" * 70)
        print("方法 B: debug_headed_vs_headless.py（全局搜索 .dropdown-more）")
        print("=" * 70)

        result_b = page.evaluate("""
        (() => {
            const dms = document.querySelectorAll('.dropdown-more');
            const candidates = [];
            for (const dm of dms) {
                const rect = dm.getBoundingClientRect();
                let hidden = false;
                let reason = '';
                let p = dm;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn && cn.includes('is-hidden')) { hidden = true; reason = 'is-hidden'; break; }
                    const st = window.getComputedStyle(p);
                    if (st.display === 'none') { hidden = true; reason = 'display:none'; break; }
                    p = p.parentElement;
                }
                candidates.push({
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    visible: rect.width > 0 && rect.height > 0 && !hidden,
                    hiddenReason: reason,
                    tbodyType: dm.closest('.el-table__fixed-right') ? 'fixed-right'
                              : dm.closest('.el-table__fixed') ? 'fixed'
                              : dm.closest('.el-table__body-wrapper') ? 'main'
                              : 'unknown',
                });
            }

            // 找第一个可见的
            let target = null;
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
                if (trigger) {
                    target = {
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y)},
                        triggerRect: {x: Math.round(trigger.getBoundingClientRect().x), y: Math.round(trigger.getBoundingClientRect().y)},
                    };
                    break;
                }
            }

            return { candidateCount: candidates.length, candidates: candidates.slice(0, 5), target };
        })()
        """)

        print(f"  .dropdown-more 总数: {result_b.get('candidateCount', 0)}")
        for c in result_b.get('candidates', []):
            vis = "[VIS]" if c['visible'] else f"[HID:{c['hiddenReason']}]"
            print(f"    {vis} in {c['tbodyType']} rect=({c['rect']['x']},{c['rect']['y']},{c['rect']['w']}x{c['rect']['h']})")

        if result_b.get('target'):
            t = result_b['target']
            print(f"  -> 选中: .dropdown-more at ({t['rect']['x']},{t['rect']['y']}), trigger at ({t['triggerRect']['x']},{t['triggerRect']['y']})")

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

            items_b = scan_popover_items(page)
            has_tuiding_b = any('退订' in i['text'] for i in items_b)
            print(f"  popover 菜单项: {len(items_b)} 个, 有退订: {has_tuiding_b}")
            for item in items_b[:5]:
                tag = " [TUIDING]" if '退订' in item['text'] else ""
                print(f"    '{item['text']}'{tag} at ({item['rect']['x']},{item['rect']['y']})")
            if len(items_b) > 5:
                print(f"    ... ({len(items_b) - 5} more)")
        else:
            print(f"  [FAIL] 没有找到可见触发器")
            has_tuiding_b = False

        close_popover(page)

        # ─── 总结 ───
        print()
        print("=" * 70)
        print("总结")
        print("=" * 70)
        print(f"  方法 A (行内搜索 fixedRows 优先): {'找到退订' if has_tuiding_a else '未找到退订'}")
        print(f"  方法 B (全局搜索 .dropdown-more):  {'找到退订' if has_tuiding_b else '未找到退订'}")

        if has_tuiding_b and not has_tuiding_a:
            print(f"\n  [ROOT CAUSE] 行内搜索方式点击了错误的触发器（可能点击了隐藏副本）")
            print(f"  修复方向: 改为全局搜索可见 .dropdown-more 后点击")

        browser.close()


if __name__ == "__main__":
    run()
