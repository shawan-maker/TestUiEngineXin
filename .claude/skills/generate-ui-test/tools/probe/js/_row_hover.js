(rowIndex) => {
    const buttons = [];
    // BUG-11: 搜索双 tbody — fixed-right 优先（操作按钮在这里），主 tbody 补充
    const rowSelectors = [
        fwSelectors.tableFixedRows,
        fwSelectors.tableBodyRows
    ];
    for (const sel of rowSelectors) {
        const rows = document.querySelectorAll(sel);
        if (rowIndex >= rows.length) continue;
        const row = rows[rowIndex];
        if (!row) continue;
        // Fix-2: 增加 dropdown span（hover 展开的"更多"菜单按钮）
        row.querySelectorAll(fwSelectors.rowButton + ', button, [role="button"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            // Relaxed visibility: only reject truly hidden elements (§9.2 P4 fix)
            if (rect.width <= 0 || rect.height <= 0) return;
            if (style.display === 'none' || style.visibility === 'hidden') return;
            // Ancestor chain visibility: reject if any ancestor is display:none/hidden
            let ancestorHidden = false;
            let ap = el.parentElement;
            while (ap && ap !== document.body) {
                const as = window.getComputedStyle(ap);
                if (as.display === 'none' || as.visibility === 'hidden') { ancestorHidden = true; break; }
                ap = ap.parentElement;
            }
            if (ancestorHidden) return;
            const text = (el.textContent || '').trim().slice(0, 100);
            if (!text) return;
            // D5: Enhanced isDisabled with 5-level ancestor check (matches _DISCOVER_JS)
            let isDisabled = el.disabled || el.classList.contains('is-disabled')
                             || el.getAttribute('aria-disabled') === 'true';
            if (!isDisabled) {
                let p = el.parentElement;
                let depth = 0;
                while (p && depth < 5) {
                    if (p.classList && p.classList.contains('is-disabled')) {
                        isDisabled = true;
                        break;
                    }
                    p = p.parentElement;
                    depth++;
                }
            }
            buttons.push({
                text: text,
                type: 'table-action-button',  // C7: 与 _DISCOVER_JS 对齐
                disabled: isDisabled,
                row_index: rowIndex,
                locator: null,
                is_row_button: true
            });
        });
    }
    return buttons;
}
