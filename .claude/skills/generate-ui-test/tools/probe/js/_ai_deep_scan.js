/**
 * _ai_deep_scan.js — Deep Structural Scan for R6 Layer 0
 *
 * 在浏览器端执行：从 label 文本出发，定位作用域容器，
 * 按 elem_type 规则扫描目标元素，过滤后反推 XPath。
 *
 * 参数（通过 page.evaluate 传入）：
 *   [label, elemType, fwScanRulesJSON, fwBreakClassesJSON]
 *
 * 返回：
 *   {
 *     labelFound: bool,
 *     labelElement: {tag, class, text},
 *     container: {tag, class, found},
 *     candidates: [{tag, class, text, isHidden, isDisabled, isReadonly,
 *                   isInsideSelect, isInsideCascader, isInsideDatePicker,
 *                   textMatch, xpath}],
 *     bestMatch: int | null
 *   }
 */

(args) => {
    const [label, elemType, fwScanRulesJSON, fwBreakClassesJSON] = args;

    const fwScanRules = JSON.parse(fwScanRulesJSON);
    const fwBreakClasses = JSON.parse(fwBreakClassesJSON);

    // ═══ Helper: 反推 XPath（复用 _ai_xpath_from_elem.js 逻辑）═══
    function reverseXPath(el) {
        const parts = [];
        let node = el;
        while (node && node.nodeType === 1 && node !== document.body) {
            if (node.id) {
                parts.unshift(`//*[@id='${node.id}']`);
                break;
            }
            let idx = 1;
            let sib = node.previousElementSibling;
            while (sib) {
                if (sib.tagName === node.tagName) idx++;
                sib = sib.previousElementSibling;
            }
            const tag = node.tagName.toLowerCase();
            const cls = node.className && typeof node.className === 'string'
                        ? node.className.trim().split(/\s+/)[0] : '';
            if (cls && !cls.match(/^[\d]/)) {
                parts.unshift(`${tag}[contains(@class,'${cls}')]`);
                // 框架感知的中断条件
                if (fwBreakClasses.some(bc => cls.startsWith(bc))) {
                    break;
                }
            } else {
                parts.unshift(`${tag}[${idx}]`);
            }
            node = node.parentElement;
            if (parts.length > 6) break;
        }
        return '//' + parts.join('/');
    }

    // ═══ Helper: 检查元素是否隐藏 ═══
    function isElementHidden(el) {
        if (el.offsetParent === null) return true;
        if (el.closest('[style*="display: none"]')) return true;
        if (el.closest('.is-hidden')) return true;
        if (el.closest('.el-select-dropdown') &&
            !el.closest('.el-select-dropdown').classList.contains('is-visible')) {
            return true;
        }
        return false;
    }

    // ═══ Step 1: 在 DOM 中找到 label 文本节点 ═══
    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        null
    );

    let labelElem = null;
    let labelText = '';

    while (walker.nextNode()) {
        const textNode = walker.currentNode;
        const nodeText = textNode.textContent.trim();

        // 精确匹配或包含匹配
        if (nodeText === label || nodeText.includes(label)) {
            labelElem = textNode.parentElement;
            labelText = nodeText;
            break;
        }
    }

    if (!labelElem) {
        return {
            labelFound: false,
            labelElement: null,
            container: null,
            candidates: [],
            bestMatch: null
        };
    }

    // ═══ Step 2: 向上遍历，找到作用域容器 ═══
    // 扩展的 breakClasses：不仅 form-item，还包括 table-row / toolbar / dialog-footer 等
    const scanBreakClasses = fwBreakClasses.concat([
        'el-table__body', 'ant-table-tbody',    // 表格
        'el-table__fixed-right', 'ant-table-fixed-right',
        'el-form--inline', 'toolbar',            // 工具栏
        'el-tabs__nav', 'ant-tabs-nav',          // Tab 导航
        'el-dialog__footer', 'ant-modal-footer', // 弹窗底部
    ]);

    let container = labelElem;
    let containerFound = false;

    while (container && container !== document.body) {
        if (container.classList) {
            const hasBreakClass = scanBreakClasses.some(bc =>
                container.classList.contains(bc)
            );
            if (hasBreakClass) {
                containerFound = true;
                break;
            }
        }
        container = container.parentElement;
    }

    // 如果没找到特定容器，回退到 label 的父元素
    if (!containerFound) {
        container = labelElem.parentElement;
    }

    const containerInfo = {
        tag: container ? container.tagName.toLowerCase() : '',
        class: (container && typeof container.className === 'string')
               ? container.className.substring(0, 100) : '',
        found: containerFound
    };

    // ═══ Step 3: 按 elem_type 扫描目标元素 ═══
    const rule = fwScanRules[elemType] || fwScanRules['_default'];
    const selector = rule.scan;

    let elements = [];
    try {
        elements = Array.from(container.querySelectorAll(selector));
    } catch (e) {
        // 选择器无效
        elements = [];
    }

    // ═══ Step 4: 过滤 + 评分 ═══
    const candidates = [];

    for (const el of elements) {
        const tag = el.tagName.toLowerCase();
        const cls = (typeof el.className === 'string') ? el.className : '';
        const text = (el.textContent || '').substring(0, 50).trim();

        // 检查隐藏/禁用/只读
        const hidden = isElementHidden(el);
        const disabled = el.disabled ||
                        el.classList.contains('is-disabled') ||
                        el.classList.contains('ant-btn-disabled');
        const readonly = el.hasAttribute('readonly');

        // 检查是否在特殊组件内部
        const insideSelect = el.closest('.el-select, .ant-select') !== null;
        const insideCascader = el.closest('.el-cascader, .ant-cascader') !== null;
        const insideDatePicker = el.closest('.el-date-editor, .ant-picker') !== null;

        // 应用排除规则
        if (rule.excludeInsideSelect && insideSelect) continue;
        if (rule.excludeInsideCascader && insideCascader) continue;
        if (rule.excludeInsideDatePicker && insideDatePicker) continue;

        // 过滤隐藏和禁用
        if (hidden || disabled) continue;

        // 文本匹配（按钮类需要）
        let textMatch = false;
        if (rule.needTextMatch) {
            textMatch = text.includes(label) || label.includes(text);
            if (!textMatch) continue;
        }

        // 反推 XPath
        const xpath = reverseXPath(el);

        candidates.push({
            tag,
            class: cls.substring(0, 100),
            text: text,
            isHidden: hidden,
            isDisabled: disabled,
            isReadonly: readonly,
            isInsideSelect: insideSelect,
            isInsideCascader: insideCascader,
            isInsideDatePicker: insideDatePicker,
            textMatch,
            xpath
        });
    }

    // ═══ Step 5: 选择最佳匹配 ═══
    let bestMatch = null;

    if (candidates.length === 0) {
        bestMatch = null;
    } else if (candidates.length === 1) {
        bestMatch = 0;
    } else {
        // 多个候选时，优先选非 readonly 的
        // （el-select 的 input 通常是 readonly，独立 input 不是）
        const nonReadonlyIdx = candidates.findIndex(c => !c.isReadonly);
        if (nonReadonlyIdx !== -1) {
            bestMatch = nonReadonlyIdx;
        } else {
            bestMatch = 0;
        }
    }

    return {
        labelFound: true,
        labelElement: {
            tag: labelElem.tagName.toLowerCase(),
            class: (typeof labelElem.className === 'string')
                   ? labelElem.className.substring(0, 100) : '',
            text: labelText.substring(0, 100)
        },
        container: containerInfo,
        candidates,
        bestMatch
    };
}
