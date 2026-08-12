#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 fixed-right 行中的所有"更多"元素"""

import sys
import json
from playwright.sync_api import sync_playwright

sys.path.insert(0, '/home/user/projects/ui-test')

from tools.probe.discover_page import load_config, inject_cookie

URL = "https://console-estack.dw.cmecloud.cn/estack/web/ecm-compute-static/vm/list?productType=vm"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        config = load_config()
        inject_cookie(page, config)

        print(f"[1] 导航到 {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        print(f"[2] 检查 fixed-right 行[0] 中的所有'更多'元素")
        result = page.evaluate("""
            (() => {
                const fixedRows = document.querySelectorAll('.el-table__fixed-right tbody tr');
                if (fixedRows.length === 0) return {error: 'no fixed-right rows'};

                const row = fixedRows[0];
                const triggers = [];

                row.querySelectorAll('.el-button, .ec-button, button, [role="button"], .el-dropdown span.el-dropdown-link, .ec-dropdown span.el-dropdown-link, span.el-dropdown-link, .el-dropdown span[style*="cursor"], .ec-dropdown span[style*="cursor"]').forEach(el => {
                    const t = (el.textContent || '').trim();
                    if (!['更多', 'More', 'more', '...'].includes(t)) return;

                    const rect = el.getBoundingClientRect();

                    // 检查祖先链可见性
                    let hidden = false;
                    let hiddenReason = '';
                    let ancestorInfo = [];
                    let p = el;
                    let depth = 0;
                    while (p && depth < 10) {
                        const cn = typeof p.className === 'string' ? p.className : (p.className && p.className.baseVal || '');
                        const st = window.getComputedStyle(p);

                        ancestorInfo.push({
                            tag: p.tagName,
                            class: cn.substring(0, 80),
                            display: st.display,
                            visibility: st.visibility,
                            isHidden: cn.includes('is-hidden')
                        });

                        if (cn.includes('is-hidden')) {
                            hidden = true;
                            hiddenReason = 'is-hidden class at depth ' + depth;
                            break;
                        }
                        if (st.display === 'none' || st.visibility === 'hidden') {
                            hidden = true;
                            hiddenReason = st.display === 'none' ? 'display:none at depth ' + depth : 'visibility:hidden at depth ' + depth;
                            break;
                        }
                        p = p.parentElement;
                        depth++;
                    }

                    triggers.push({
                        text: t,
                        tag: el.tagName,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                        visible: rect.width > 0 && rect.height > 0 && !hidden,
                        hidden: hidden,
                        hiddenReason: hiddenReason,
                        ancestors: ancestorInfo
                    });
                });

                return {
                    triggerCount: triggers.length,
                    triggers: triggers
                };
            })()
        """)

        print(f"\\n[3] 结果: {result}")

        if 'triggers' in result:
            print(f"\\n[4] 找到 {result['triggerCount']} 个'更多'触发器:")
            for i, t in enumerate(result['triggers']):
                status = "✓ 可见" if t['visible'] else "✗ 隐藏"
                print(f"  [{i}] {status} - 位置: ({t['rect']['x']},{t['rect']['y']}) {t['rect']['w']}x{t['rect']['h']}")
                if t['hidden']:
                    print(f"      隐藏原因: {t['hiddenReason']}")
                print(f"      祖先链 (前5层):")
                for j, anc in enumerate(t['ancestors'][:5]):
                    hidden_mark = " [is-hidden]" if anc['isHidden'] else ""
                    print(f"        [{j}] <{anc['tag']}> class='{anc['class']}' display={anc['display']} visibility={anc['visibility']}{hidden_mark}")

        browser.close()

if __name__ == '__main__':
    main()
