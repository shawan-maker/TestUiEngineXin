"""对比 headless vs headed 模式下"更多"菜单中是否包含"退订"

运行方式：
    PYTHONIOENCODING=utf-8 python tests/debug_headed_vs_headless.py
"""
import json
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root.parent.parent.parent))

import yaml
from playwright.sync_api import sync_playwright


def load_config():
    config_path = Path('D:/PyProject/TestUiEngineXin/examples/ecsCloud2/config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def inject_auth(context, config):
    cookie_str = config.get('cookie', '')
    domain = config.get('cookie_domain', '')
    if cookie_str:
        cookies = []
        for item in cookie_str.split(';'):
            item = item.strip()
            if '=' in item:
                name, value = item.split('=', 1)
                cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': domain,
                    'path': '/',
                })
        if cookies:
            context.add_cookies(cookies)
            print(f"  [AUTH] Injected {len(cookies)} cookies")


def scan_popover(page, label):
    """展开第一个可见的'更多'并扫描 popover 内容"""
    # hover 第一行
    page.evaluate("""
    (rowIndex) => {
        const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
        const mainRows = document.querySelectorAll('.el-table__body-wrapper > table > tbody > tr');
        if (rowIndex < mainRows.length) {
            mainRows[rowIndex].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            mainRows[rowIndex].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
        }
        if (rowIndex < fixedRows.length) {
            fixedRows[rowIndex].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            fixedRows[rowIndex].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
        }
    }
    """, 0)
    page.wait_for_timeout(1000)

    # 找到可见的 dropdown-more 并点击"更多"
    click_result = page.evaluate("""
    (() => {
        const dms = document.querySelectorAll('.dropdown-more');
        for (const dm of dms) {
            const rect = dm.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            // 检查祖先是否有 is-hidden
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
            // 找到可见的 dropdown-more，点击其中的触发器
            const trigger = dm.querySelector('.el-dropdown-link, .el-popover__reference');
            if (trigger) {
                trigger.click();
                return {found: true, rect: {x: Math.round(rect.x), y: Math.round(rect.y)}};
            }
        }
        return {found: false};
    })()
    """)

    if not click_result.get('found'):
        print(f"  [{label}] [FAIL] 未找到可见的'更多'触发器")
        return []

    print(f"  [{label}] 点击了'更多' at ({click_result['rect']['x']},{click_result['rect']['y']})")
    page.wait_for_timeout(2000)

    # 扫描 popover 中所有 clickClass 元素
    items = page.evaluate("""
    (() => {
        const getCN = (el) => {
            if (!el.className) return '';
            return (typeof el.className === 'string' ? el.className : (el.className.baseVal || ''));
        };
        const items = [];
        // 搜索所有 x-placement 容器中的 clickClass
        document.querySelectorAll('div[x-placement] div.clickClass').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            // 检查祖先链可见性
            let ancestorHidden = false;
            let p = el.parentElement;
            while (p) {
                const ps = window.getComputedStyle(p);
                if (ps.display === 'none' || ps.visibility === 'hidden') {
                    ancestorHidden = true;
                    break;
                }
                p = p.parentElement;
            }
            const visible = rect.width > 0 && rect.height > 0
                && style.display !== 'none' && style.visibility !== 'hidden'
                && !ancestorHidden;
            const text = (el.textContent || '').trim().replace(/\\s*(new|hot)\\s*/gi, '').trim();
            if (!text) return;
            items.push({
                text: text,
                visible: visible,
                rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                       w: Math.round(rect.width), h: Math.round(rect.height)},
            });
        });
        return items;
    })()
    """)

    visible_items = [i for i in items if i['visible']]
    print(f"  [{label}] popover 中 clickClass 总数: {len(items)}, 可见: {len(visible_items)}")

    has_tuiding = False
    for idx, item in enumerate(visible_items):
        tag = '[TUIDING]' if '退订' in item['text'] else ''
        if '退订' in item['text']:
            has_tuiding = True
        print(f"    [{idx}] {tag} '{item['text']}' pos=({item['rect']['x']},{item['rect']['y']})")

    if has_tuiding:
        print(f"  [{label}] [OK] '退订' 存在于 popover 中")
    else:
        print(f"  [{label}] [MISS] '退订' 不存在于 popover 中")

    # 全局搜索"退订"
    tuiding_global = page.evaluate("""
    (() => {
        const results = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        while (walker.nextNode()) {
            const el = walker.currentNode;
            const directText = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('');
            if (directText === '退订') {
                const rect = el.getBoundingClientRect();
                let inPopover = false;
                let p = el;
                while (p) {
                    const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                    if (cn && (cn.includes('el-popover') || cn.includes('clickClass') || p.getAttribute('x-placement'))) {
                        inPopover = true;
                        break;
                    }
                    p = p.parentElement;
                }
                results.push({
                    tag: el.tagName,
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y),
                           w: Math.round(rect.width), h: Math.round(rect.height)},
                    inPopover: inPopover,
                });
            }
        }
        return results;
    })()
    """)

    print(f"  [{label}] 全局搜索'退订': {len(tuiding_global)} 个")
    for i, el in enumerate(tuiding_global):
        vis = "可见" if el['rect']['w'] > 0 else "隐藏"
        pop = "在popover中" if el['inPopover'] else "不在popover中"
        print(f"    [{i}] {vis} {pop} <{el['tag']}> rect=({el['rect']['x']},{el['rect']['y']},{el['rect']['w']}x{el['rect']['h']})")

    return visible_items


def run():
    config = load_config()
    vm_list_url = 'http://console-estack-intel.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm'

    print(f"Target URL: {vm_list_url}")
    print("=" * 70)

    with sync_playwright() as pw:
        # ─── Test 1: Headless 模式 ───
        print("\n[Test 1] headless=True, no_viewport=True")
        print("-" * 70)
        browser_hl = pw.chromium.launch(headless=True)
        ctx_hl = browser_hl.new_context(no_viewport=True)
        inject_auth(ctx_hl, config)
        page_hl = ctx_hl.new_page()
        page_hl.goto(vm_list_url, wait_until='domcontentloaded', timeout=60000)
        page_hl.wait_for_timeout(6000)
        print(f"  UA: {page_hl.evaluate('navigator.userAgent')}")
        print(f"  viewport: {page_hl.evaluate('[window.innerWidth, window.innerHeight]')}")
        hl_items = scan_popover(page_hl, "headless")
        browser_hl.close()

        # ─── Test 2: Headed 模式 ───
        print("\n\n[Test 2] headless=False, no_viewport=True")
        print("-" * 70)
        browser_hd = pw.chromium.launch(headless=False)
        ctx_hd = browser_hd.new_context(no_viewport=True)
        inject_auth(ctx_hd, config)
        page_hd = ctx_hd.new_page()
        page_hd.goto(vm_list_url, wait_until='domcontentloaded', timeout=60000)
        page_hd.wait_for_timeout(6000)
        print(f"  UA: {page_hd.evaluate('navigator.userAgent')}")
        print(f"  viewport: {page_hd.evaluate('[window.innerWidth, window.innerHeight]')}")
        hd_items = scan_popover(page_hd, "headed")
        browser_hd.close()

        # ─── 对比 ───
        print("\n\n" + "=" * 70)
        print("[对比结果]")
        print("=" * 70)
        hl_texts = set(i['text'] for i in hl_items)
        hd_texts = set(i['text'] for i in hd_items)

        only_hl = hl_texts - hd_texts
        only_hd = hd_texts - hl_texts
        common = hl_texts & hd_texts

        print(f"  headless 可见项: {len(hl_items)}")
        print(f"  headed   可见项: {len(hd_items)}")
        print(f"  共同项: {len(common)}")
        print(f"  仅 headless: {sorted(only_hl) if only_hl else '(none)'}")
        print(f"  仅 headed:   {sorted(only_hd) if only_hd else '(none)'}")
        print(f"  headless 有'退订': {'退订' in hl_texts}")
        print(f"  headed   有'退订': {'退订' in hd_texts}")

        if '退订' in hd_texts and '退订' not in hl_texts:
            print(f"\n  [ROOT CAUSE CONFIRMED] headless 和 headed 渲染不同！")
            print(f"  '退订'仅在 headed 模式出现，说明服务端或前端对 headless 做了差异化处理。")
        elif '退订' not in hd_texts and '退订' not in hl_texts:
            print(f"\n  [结论] 两种模式都没有'退订'——可能是 cookie/权限问题")
        elif '退订' in hl_texts and '退订' in hd_texts:
            print(f"\n  [结论] 两种模式都有'退订'——之前探测失败可能是时序问题")

        print("\n[DIAG] 完成")


if __name__ == '__main__':
    run()
