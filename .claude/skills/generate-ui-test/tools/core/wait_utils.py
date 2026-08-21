#!/usr/bin/env python3
"""共享等待工具函数 — verify_locators.py 和 discover_page.py 共用

提供 DOM 稳定性检测，替代固定 sleep，确保 Vue/React 渲染完成。
"""


def wait_for_dom_stable(page, timeout_ms=3000, interval_ms=500, debug=False):
    """等待 DOM 表单元素 + 表格行数同时稳定。

    用于 Vue/React 渲染周期完成检测，替代固定 sleep。
    适用于所有页面类型（列表页、容器、首页、详情页）。

    稳定判据（必须同时满足）：
      - forms_ok:  表单元素计数连续两次相同且 > 0
      - rows_ok:   表格行数连续两次相同且 > 0，或页面无表格(rows=0)
      - not loading: 当前无可见 loading mask

    通过 loading 状态变化（True→False）打破连续一致性，防止在 loading
    刚消失时就误判为"空表格稳定"。只有 loading 消失后再经过一次采样确认
    rows 不变，才认为真正稳定。

    四种场景：
      - 有数据表格: loading→loading消失(rows=0,打破一致)→rows出现→rows不变 → 返回
      - 空表格:     loading→loading消失(rows=0,打破一致)→rows仍0+无loading → 返回
      - 无表格页面: rows始终=0 → 仅看表单稳定 → 快速返回（行为不变）
      - 慢API:      loading持续 → 等到数据出现并稳定

    Args:
        page: Playwright page 对象
        timeout_ms: 最大等待时间（ms），超时不报错
        interval_ms: 采样间隔（ms）
        debug: 启用采样日志输出
    """
    _count_js = """
        (() => {
            const forms = document.querySelectorAll(
                'input.el-input__inner, textarea.el-textarea__inner, '
              + '.el-select, .el-form-item, button').length;
            const rows = document.querySelectorAll('tbody tr').length;
            const loading = document.querySelectorAll(
                '.el-loading-mask:not([style*="display: none"]), '
              + '.ant-btn-loading, '
              + '.ant-btn-loading-icon, '
              + '.ant-spin-spinning'
            ).length > 0;
            return { forms: forms, rows: rows, loading: loading };
        })()
    """
    prev = None
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            curr = page.evaluate(_count_js)
        except Exception:
            break  # page.evaluate 失败（如页面已关闭）→ 退出等待

        if debug:
            tag = "LOADING" if curr.get('loading') else "idle"
            print(f"  [DOM-STABLE] {elapsed}ms: forms={curr['forms']}, "
                  f"rows={curr['rows']}, {tag}")

        if prev:
            forms_ok = (curr['forms'] == prev['forms']) and (curr['forms'] > 0)

            # rows_ok:
            #   rows > 0 + 连续不变 → True (数据已渲染且稳定)
            #   rows == 0 + loading → False (正在加载，不算稳定)
            #   rows == 0 + 无loading → True (无表格页面 或 空结果)
            if curr['rows'] > 0:
                rows_ok = (curr['rows'] == prev['rows'])
            else:
                rows_ok = not curr.get('loading')

            # loading 状态变化打破一致性:
            #   loading 从 True→False 时, curr.loading != prev.loading
            #   → loading_stable = False → 整体不稳定 → 继续采样
            #   下一次采样如果 loading 仍为 False + rows 不变 → 稳定
            loading_stable = (curr.get('loading') == prev.get('loading'))

            if forms_ok and rows_ok and loading_stable and not curr.get('loading'):
                if debug:
                    print(f"  [DOM-STABLE] stable @ {elapsed}ms "
                          f"(forms={curr['forms']}, rows={curr['rows']})")
                return

        prev = curr
        try:
            page.wait_for_timeout(interval_ms)
        except Exception as e:
            # Page crashed (e.g., memory exhausted on heavy pages)
            # Return False to signal DOM stability check failed
            if debug:
                print(f"  [DOM-STABLE] page crashed at {elapsed}ms: {type(e).__name__}")
            return False
        elapsed += interval_ms

    # timeout 到达
    if debug and prev:
        print(f"  [DOM-STABLE] timeout @ {elapsed}ms "
              f"(forms={prev['forms']}, rows={prev['rows']})")
