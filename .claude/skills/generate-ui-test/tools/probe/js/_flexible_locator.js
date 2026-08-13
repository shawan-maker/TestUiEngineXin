(label, elemType) => {
    // Determine target elements by type
    let targets;
    switch(elemType) {
        case 'el-select':
            targets = document.querySelectorAll(fwSelectors.selectInput);
            break;
        case 'textarea':
            targets = document.querySelectorAll(fwSelectors.textareaInner);
            break;
        case 'date_picker':
        case 'date-picker':
            targets = document.querySelectorAll(fwSelectors.dateEditor);
            break;
        case 'el-cascader':
            targets = document.querySelectorAll(fwSelectors.cascaderInput);
            break;
        case 'menu-item':
        case 'tab':
        case 'detail-link':
            // These types don't use input-based locator strategy
            return null;
        default:
            targets = document.querySelectorAll(fwSelectors.inputInner + ':not([type="hidden"])');
    }

    for (const el of targets) {
        // Strategy 1: via form item label
        const formItem = el.closest(fwSelectors.formItem);
        if (formItem) {
            const lbl = formItem.querySelector(fwSelectors.formItemLabel);
            if (lbl && lbl.textContent.trim().includes(label)) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className;
                return "//*[contains(text(),'" + label + "')]//following-sibling::*[self::div or self::span]//"
                    + tag + "[@class='" + cls + "']";
            }
        }

        // Strategy 2: via placeholder
        const ph = el.getAttribute('placeholder');
        if (ph && ph.includes(label)) {
            return "//*[@placeholder='" + ph + "']";
        }

        // Strategy 3: via nearest text-bearing ancestor
        let parent = el.parentElement;
        let depth = 0;
        while (parent && depth < 6) {
            const text = parent.textContent?.trim();
            if (text && text.includes(label) && text.length < 50) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className;
                return "//*[contains(text(),'" + label + "')]//" + tag + "[@class='" + cls + "']";
            }
            parent = parent.parentElement;
            depth++;
        }
    }
}
