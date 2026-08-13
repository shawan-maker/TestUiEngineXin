() => {
    const fields = [];
    // 框架感知的表单项选择器
    const formItemSelector = fwSelectors.formItem || '.el-form-item';
    const labelSelector = fwSelectors.formItemLabel || '.el-form-item__label';
    const inputSelector = 'input, textarea, ' + (fwSelectors.selectInput || '.el-select');

    document.querySelectorAll(formItemSelector).forEach(item => {
        const label = item.querySelector(labelSelector);
        const input = item.querySelector(inputSelector);
        if (label) {
            fields.push({
                label: label.textContent.trim().substring(0, 30),
                inputTag: input?.tagName?.toLowerCase() || 'none',
                inputClass: (typeof input?.className === 'string')
                           ? input.className.substring(0, 60) : ''
            });
        }
    });
    return fields.slice(0, 20);
}
