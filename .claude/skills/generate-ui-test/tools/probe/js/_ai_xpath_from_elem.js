el => {
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
            // 框架感知的中断条件：遇到容器或表单项时停止向上遍历
            const breakClasses = fwBreakClasses || [];
            if (breakClasses.some(bc => cls.startsWith(bc))) {
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
