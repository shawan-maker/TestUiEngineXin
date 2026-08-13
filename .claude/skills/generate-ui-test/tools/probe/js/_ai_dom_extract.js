(label, containerXpath) => {
    const results = [];
    const walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT, null
    );
    while (walker.nextNode()) {
        const textNode = walker.currentNode;
        if (!textNode.textContent.includes(label)) continue;
        const parent = textNode.parentElement;
        if (!parent) continue;
        let fieldRoot = parent;
        for (let i = 0; i < 4 && fieldRoot.parentElement; i++) {
            const p = fieldRoot.parentElement;
            // 框架感知的容器类检测
            const containerClasses = fwContainerClasses || [];
            const hasContainerClass = containerClasses.some(cc => p.classList.contains(cc));
            if (hasContainerClass || p.tagName === 'FORM') {
                fieldRoot = p;
                break;
            }
            fieldRoot = p;
        }
        const snippet = fieldRoot.outerHTML
            .replace(/style="[^"]*"/g, '')
            .replace(/>([^<]{30,})</g, '>[...]</')
            .substring(0, 1500);
        results.push({
            html: snippet,
            tag: fieldRoot.tagName.toLowerCase(),
            classes: (typeof fieldRoot.className === 'string') ? fieldRoot.className : '',
            parentTag: fieldRoot.parentElement?.tagName?.toLowerCase() || '',
            parentClasses: (typeof fieldRoot.parentElement?.className === 'string')
                          ? fieldRoot.parentElement.className : '',
        });
        if (results.length >= 5) break;
    }
    let container = null;
    if (containerXpath) {
        try {
            const cel = document.evaluate(
                containerXpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (cel) {
                container = {
                    tag: cel.tagName.toLowerCase(),
                    classes: cel.className || '',
                    children: Array.from(cel.children).slice(0, 10).map(c => ({
                        tag: c.tagName.toLowerCase(),
                        classes: (typeof c.className === 'string') ? c.className.substring(0, 80) : '',
                        text: (c.textContent || '').substring(0, 50).trim()
                    }))
                };
            }
        } catch(e) {}
    }
    return { matches: results, container: container };
}
