(scopeSelector) => {
    const results = { buttons: [], inputs: [], tabs: [], row_buttons: [], detail_links: [], checkboxes: [], menu_items: [] };

    // D2: scope to container DOM subtree, or full document
    let root;
    if (scopeSelector) {
        const candidates = document.querySelectorAll(scopeSelector);
        const visible = Array.from(candidates).filter(el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0
                && s.display !== 'none'
                && s.visibility !== 'hidden';
        });
        if (visible.length === 0) {
            return results;
        } else if (visible.length === 1) {
            root = visible[0];
        } else {
            // Multiple visible same-type containers → pick the one with most form fields
            root = visible.sort((a, b) =>
                b.querySelectorAll('input,select,textarea,' + fwSelectors.selectExclude).length
                - a.querySelectorAll('input,select,textarea,' + fwSelectors.selectExclude).length
            )[0];
        }
    } else {
        root = document;
    }
    if (!root) return results;

    function findAssociatedLabel(input) {
        function cleanLabel(t) {
            return t.trim().replace(/^\s*[*＊]\s*|\s*[*＊]\s*$/g, '');
        }

        // ── Route 1: form item → label ──
        const formItem = input.closest(fwSelectors.formItem);
        if (formItem) {
            const lbl = formItem.querySelector(fwSelectors.formItemLabel);
            if (lbl) return cleanLabel(lbl.textContent);
        }

        // ── Route 2: textarea special handling ──
        if (input.tagName === 'TEXTAREA') {
            // Route 2a: textarea wrapper → previousElementSibling
            const textareaWrap = input.closest(fwSelectors.textarea);
            if (textareaWrap) {
                const prev = textareaWrap.previousElementSibling;
                if (prev) {
                    const text = prev.textContent.trim();
                    if (text.length >= 1 && text.length <= 30) return cleanLabel(text);
                }
            }
            // Route 2b: walk up 8 levels to find form item → label
            let parent = input.parentElement;
            let depth = 0;
            while (parent && depth < 8) {
                const fi = parent.closest ? parent.closest(fwSelectors.formItem) : null;
                if (fi) {
                    const lbl = fi.querySelector(fwSelectors.formItemLabel);
                    if (lbl) return cleanLabel(lbl.textContent);
                }
                parent = parent.parentElement;
                depth++;
            }
        }

        // ── Route 3: input wrapper → previousElementSibling ──
        const prev = input.closest(fwSelectors.inputWrapper)?.previousElementSibling;
        if (prev) return cleanLabel(prev.textContent);

        // ── Fallback: placeholder ──
        return input.getAttribute('placeholder') || '';
    }

    function getText(el) {
        return (el.textContent || '').trim().slice(0, 100);
    }

    function isDisabled(el) {
        if (el.disabled || el.classList.contains('is-disabled')
            || el.getAttribute('aria-disabled') === 'true') return true;
        // D5: ancestor check (up to 5 levels)
        let parent = el.parentElement, depth = 0;
        while (parent && depth < 5) {
            if (parent.classList.contains('is-disabled')) return true;
            if (parent.getAttribute('aria-disabled') === 'true') return true;
            parent = parent.parentElement; depth++;
        }
        return false;
    }

    function isVisible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0
            && style.display !== 'none'
            && style.visibility !== 'hidden';
    }

    // D7+D8: noise filter functions
    function isBreadcrumb(el) {
        return !!el.closest(fwSelectors.breadcrumb + ', .breadcrumb, [class*="breadcrumb"]');
    }
    function isTopNav(el) {
        return el.getBoundingClientRect().top < 60;
    }
    function isUserDropdown(el) {
        return !!el.closest(fwSelectors.dropdown + ', .user-info, .header-right, [class*="user"]');
    }

    // C7: Button subtype detection
    function getButtonSubtype(el) {
        if (el.querySelector(fwSelectors.iconSearch) || /搜.*索|查.*询/.test(el.textContent))
            return 'search-button';
        if (el.classList && el.classList.contains('search-wrap'))
            return 'search-button';
        if (el.querySelector(fwSelectors.iconDownload) || /导出|下载/.test(el.textContent))
            return 'download-button';
        return 'button';
    }

    // 1. Buttons (excluding row buttons — toolbar scope)
    root.querySelectorAll(fwSelectors.button + ', button, [role="button"], div.search-wrap').forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('tbody')) return;  // skip row buttons here
        if (!scopeSelector) {
            // D7+D8: only filter noise on full-page scan (not container-scoped)
            if (isBreadcrumb(el)) return;
            if (isTopNav(el)) return;
            if (isUserDropdown(el)) return;
        }
        let text = getText(el);
        // 搜索图标容器：无文本时根据 class 推断合成标签
        if (!text && el.classList && el.classList.contains('search-wrap')) {
            text = '搜索图标';
        }
        if (!text) return;
        results.buttons.push({
            text: text,
            type: getButtonSubtype(el),  // C7: button subtype
            disabled: isDisabled(el),
            locator: null,  // will be generated by KB
            is_row_button: false  // §9.2 P1-A: mark as toolbar
        });
    });

    // 1b. Clickable custom elements (divs/spans acting as buttons)
    root.querySelectorAll(
        'div.flex-item, div.card-item, div.action-item, '
        + 'div[class*="btn-"], div[class*="-btn"], '
        + 'span[class*="btn-"], span[class*="-btn"]'
    ).forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('tbody')) return;  // skip row scope
        if (!scopeSelector) {
            if (isBreadcrumb(el)) return;
            if (isTopNav(el)) return;
            if (isUserDropdown(el)) return;
        }
        const text = getText(el);
        if (!text || text.length > 30) return;  // skip overly long text
        // Avoid duplicates with standard buttons already collected
        const alreadyExists = results.buttons.some(b => b.text === text);
        if (alreadyExists) return;
        results.buttons.push({
            text: text,
            type: getButtonSubtype(el),
            disabled: false,
            locator: null,
            is_row_button: false,
            is_custom_clickable: true,  // mark as non-standard button
            custom_class: el.className || ''  // preserve class for precise XPath
        });
    });

    // 2. Inputs (excluding select, date, cascader)
    root.querySelectorAll(fwSelectors.inputInner + ':not([type="hidden"])').forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest(fwSelectors.selectExclude)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'input', locator: null });
    });

    // 3. Select
    root.querySelectorAll(fwSelectors.selectInput).forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'el-select', locator: null });
    });

    // 4. textarea — Fix-3: 拓宽选择器，不依赖 class
    root.querySelectorAll('textarea').forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'textarea', locator: null });
    });

    // 4b. iframe 内全元素扫描（通用 iframe 支持）
    root.querySelectorAll('iframe').forEach((iframe, iframeIdx) => {
        try {
            const doc = iframe.contentDocument;
            if (!doc) return; // 跨域 iframe 由 Python 层处理

            // 生成 iframe CSS 选择器（用于 frame_locator）
            let iframeSelector = '';
            if (iframe.id) {
                iframeSelector = 'iframe#' + iframe.id;
            } else if (iframe.name) {
                iframeSelector = 'iframe[name="' + iframe.name + '"]';
            } else {
                iframeSelector = 'iframe:nth-of-type(' + (iframeIdx + 1) + ')';
            }

            // Helper: 从 iframe 父级查找 label
            function findIframeLabel(iframeEl) {
                let parent = iframeEl.parentElement;
                let depth = 0;
                while (parent && depth < 8) {
                    const formItem = parent.closest ? parent.closest(fwSelectors.formItem) : null;
                    if (formItem) {
                        const lbl = formItem.querySelector(fwSelectors.formItemLabel);
                        if (lbl) return lbl.textContent.trim()
                            .replace(/^\s*[*＊]\s*|\s*[*＊]\s*$/g, '');
                    }
                    parent = parent.parentElement;
                    depth++;
                }
                return '';
            }

            // 扫描按钮
            doc.querySelectorAll('button, [role="button"], ' + fwSelectors.iframeButton)
               .forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                if (!text || text.length > 30) return;
                results.buttons.push({
                    text: text,
                    type: getButtonSubtype(el),
                    disabled: isDisabled(el),
                    locator: null,
                    is_row_button: false,
                    iframe_context: iframeSelector,
                    iframe_index: iframeIdx,
                });
            });

            // 扫描 input/textarea
            doc.querySelectorAll('input:not([type="hidden"]), textarea')
               .forEach(el => {
                if (!isVisible(el)) return;
                if (el.closest(fwSelectors.selectExclude) || el.closest(fwSelectors.selectExclude)) return;
                const label = findAssociatedLabel(el) || findIframeLabel(iframe);
                if (!label) return;
                const inputType = el.tagName === 'TEXTAREA' ? 'textarea' : 'input';
                results.inputs.push({
                    label: label,
                    type: inputType,
                    locator: null,
                    iframe_context: iframeSelector,
                    iframe_index: iframeIdx,
                });
            });

            // 扫描 select
            doc.querySelectorAll(fwSelectors.selectInput).forEach(el => {
                if (!isVisible(el)) return;
                const label = findAssociatedLabel(el) || findIframeLabel(iframe);
                if (!label) return;
                results.inputs.push({
                    label: label,
                    type: 'el-select',
                    locator: null,
                    iframe_context: iframeSelector,
                    iframe_index: iframeIdx,
                });
            });

            // 富文本编辑器（保留现有逻辑）
            const editables = doc.querySelectorAll(
                '[contenteditable="true"], body.mce-content-body, body.ql-editor'
            );
            editables.forEach(el => {
                let label = findIframeLabel(iframe);
                if (!label) return;
                results.inputs.push({
                    label: label,
                    type: 'rich_text',
                    locator: null,
                    has_iframe: true,
                    recommended_keyword: 'frame_fill_value',
                    iframe_context: iframeSelector,
                    iframe_index: iframeIdx,
                });
            });

        } catch (e) {
            // cross-origin iframe — 静默跳过（Python 层补充处理）
        }
    });

    // 5. date picker
    root.querySelectorAll(fwSelectors.dateEditor).forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'date_picker', locator: null });
    });

    // 6. cascader
    root.querySelectorAll(fwSelectors.cascaderInput).forEach(el => {
        if (!isVisible(el)) return;
        const label = findAssociatedLabel(el);
        results.inputs.push({ label: label, type: 'el-cascader', locator: null });
    });

    // 7. Tabs (D3: add type='tab' marker)
    root.querySelectorAll('[role="tab"]').forEach(el => {
        if (!isVisible(el)) return;
        const name = getText(el);
        results.tabs.push({ name: name, type: 'tab', locator: null });
    });

    // 8. Row buttons (inside tbody) — C7: all typed as table-action-button
    root.querySelectorAll(fwSelectors.rowButton + ', tbody button').forEach(el => {
        if (!isVisible(el)) return;
        const text = getText(el);
        if (!text) return;
        results.row_buttons.push({
            text: text,
            type: 'table-action-button',  // C7: tbody buttons are table-actions
            disabled: isDisabled(el),
            locator: null,
            is_row_button: true
        });
    });

    // 9. Detail links / clickable text inside table cells — F-R5
    if (!results.detail_links) results.detail_links = [];
    const seenDetailLinks = new Set();
    // 9a: Inside table cells
    root.querySelectorAll([
        'tbody td a',
        'tbody td [style*="cursor: pointer"]',
        'tbody td .link',
        'tbody td .common-href',
        'tbody td .link-style',
        'tbody td .click-list',
        'tbody td .resource-id',
        'tbody td .edit-name'
    ].join(', ')).forEach(el => {
        if (!isVisible(el)) return;
        const text = getText(el);
        if (!text || text.length > 50) return;
        if (seenDetailLinks.has(text)) return;
        seenDetailLinks.add(text);
        results.detail_links.push({
            text: text,
            locator: null,
            is_detail_link: true,
            has_common_href: el.classList.contains('common-href')
        });
    });
    // 9b: .common-href outside table cells
    root.querySelectorAll('.common-href').forEach(el => {
        if (!isVisible(el)) return;
        if (el.closest('tbody td')) return;
        const text = getText(el);
        if (!text || text.length > 50) return;
        if (seenDetailLinks.has(text)) return;
        seenDetailLinks.add(text);
        results.detail_links.push({
            text: text,
            locator: null,
            is_detail_link: true,
            has_common_href: true
        });
    });

    // 10. Checkboxes (fwSelectors parameterized) — C5
    const checkboxResults = [];
    root.querySelectorAll(fwSelectors.checkboxInner).forEach(el => {
        if (!isVisible(el)) return;
        const isHeader = !!el.closest(fwSelectors.tableHeader);
        const isBody = !!el.closest(fwSelectors.tableBody);
        if (!isHeader && !isBody) return;
        checkboxResults.push({
            type: isHeader ? 'checkbox-all' : 'checkbox',
            name: isHeader ? '批量全选' : '第1行选择框',
            label: isHeader ? '批量全选' : '第1行选择框',
            locator: null,
            row_index: isBody ? 0 : -1
        });
    });
    // Dedup: one header checkbox, one body checkbox
    const seenCheckbox = new Set();
    results.checkboxes = checkboxResults.filter(c => {
        const key = c.type;
        if (seenCheckbox.has(key)) return false;
        seenCheckbox.add(key);
        return true;
    });

    // 11. Sidebar menu items — C6
    results.menu_items = [];
    root.querySelectorAll(fwSelectors.menuItem).forEach(el => {
        if (!isVisible(el)) return;
        const text = getText(el);
        if (!text) return;
        results.menu_items.push({
            type: 'menu-item',
            name: text,
            label: text,
            locator: null
        });
    });

    return results;
}
