// _xpath_picker.js — Debug XPath Picker 交互式浮层
// 注入方式: page.evaluate(wrapped_code)
// 依赖: fwSelectors, _brk 由 Python 端注入为 const
//
// 公共 API (window 上):
//   __picker_pick       — JS→Python: 用户点击的元素数据（读取后置 null）
//   __picker_verified    — Python→JS: 验证后的最终结果
//   __picker_last_valid  — 最后一个有效结果（单元素模式，覆盖而非累积）
//   __picker_writeback_request — 写回请求信号（JS→Python）
//   __picker_exit        — 退出信号
//   __picker_cleanup     — 清理函数（移除浮层+事件）

(function() {
    'use strict';

    // ═══════════════════════════════════════════════
    // 全局状态
    // ═══════════════════════════════════════════════
    window.__picker_pick = null;
    window.__picker_verified = null;
    window.__picker_last_valid = null;
    window.__picker_writeback_request = null;
    window.__picker_exit = false;

    let _pendingPick = null;      // 缓存当前拾取的 label/type（用于 pollVerified 读取）
    let _highlighted = null;       // 当前高亮元素
    let _locked = false;           // 是否锁定（等待验证）
    let _panel = null;             // 浮层 DOM
    let _styleEl = null;           // 注入的 CSS
    let _clickHandler = null;      // click 事件引用（用于移除）
    let _moveHandler = null;       // mousemove 事件引用
    let _keyHandler = null;        // keydown 事件引用
    let _dragging = false;         // 是否正在拖动面板
    let _dragStart = {x: 0, y: 0}; // 拖动起始鼠标位置
    let _panelStart = {x: 0, y: 0}; // 拖动起始面板位置
    let _dragMoveHandler = null;   // drag mousemove 事件引用
    let _dragUpHandler = null;     // drag mouseup 事件引用

    // ═══════════════════════════════════════════════
    // 工具函数
    // ═══════════════════════════════════════════════

    function cleanLabel(t) {
        if (!t) return '';
        return t.trim()
            .replace(/^\s*[*＊]\s*|\s*[*＊]\s*$/g, '')  // 去必填星号
            .replace(/\s+/g, ' ');                        // 空格归一化
    }

    function isVisible(el) {
        if (!el) return false;
        var rect = el.getBoundingClientRect();
        var style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0
            && style.display !== 'none'
            && style.visibility !== 'hidden';
    }

    function escapeXPathStr(s) {
        // XPath 1.0 中单引号转义: 拆为 concat('a', "'", 'b')
        if (s.indexOf("'") === -1) return "'" + s + "'";
        if (s.indexOf('"') === -1) return '"' + s + '"';
        return "concat('" + s.replace(/'/g, "',\"'\",'") + "')";
    }

    // 安全访问 fwSelectors/fwBreakClasses（防止未注入时 ReferenceError）
    // Python 端注入方式: const fwSelectors = {...}; const fwBreakClasses = [...];
    // 或: window.fwSelectors = {...}; window.fwBreakClasses = [...];
    var _sel = (typeof fwSelectors !== 'undefined') ? fwSelectors
             : (window.fwSelectors || {});
    var _brk = (typeof fwBreakClasses !== 'undefined') ? fwBreakClasses
             : (window.fwBreakClasses || []);

    // ═══════════════════════════════════════════════
    // Label 提取（复用 _discover_common.js 的 4 条路线）
    // ═══════════════════════════════════════════════

    function extractLabel(el) {
        // 优先从实际交互元素（input/textarea/select）查找
        var target = el;
        if (el.tagName === 'LABEL' || el.tagName === 'SPAN' || el.tagName === 'DIV') {
            // 用户可能点击了 label 本身，尝试找到关联的 input
            var formItem = el.closest(_sel.formItem || '.el-form-item');
            if (formItem) {
                var inp = formItem.querySelector('input, textarea, select');
                if (inp) target = inp;
            }
        }

        // Route 1: form-item → label
        var formItem = target.closest(_sel.formItem || '.el-form-item');
        if (formItem) {
            var lbl = formItem.querySelector(_sel.formItemLabel || '.el-form-item__label');
            if (lbl) return cleanLabel(lbl.textContent);
        }

        // Route 2: textarea special
        if (target.tagName === 'TEXTAREA') {
            var taWrap = target.closest(_sel.textarea || '.el-textarea');
            if (taWrap) {
                var prev = taWrap.previousElementSibling;
                if (prev) {
                    var t = prev.textContent.trim();
                    if (t.length >= 1 && t.length <= 30) return cleanLabel(t);
                }
            }
            var parent = target.parentElement;
            var depth = 0;
            while (parent && depth < 8) {
                var fi = parent.closest ? parent.closest(_sel.formItem || '.el-form-item') : null;
                if (fi) {
                    var lb = fi.querySelector(_sel.formItemLabel || '.el-form-item__label');
                    if (lb) return cleanLabel(lb.textContent);
                }
                parent = parent.parentElement;
                depth++;
            }
        }

        // Route 3: input wrapper → previousElementSibling
        var inputWrap = target.closest(_sel.inputWrapper || '.el-input');
        if (inputWrap) {
            var prevSib = inputWrap.previousElementSibling;
            if (prevSib) {
                var sibName = cleanLabel(prevSib.textContent);
                if (sibName.length >= 1 && sibName.length <= 30) return sibName;
            }
        }

        // Route 4: placeholder
        var ph = target.getAttribute('placeholder');
        if (ph && ph.length > 0 && ph.length <= 30) return cleanLabel(ph);

        // Route 5: 最近文本祖先（向上 6 层）
        var par = el.parentElement;
        var d = 0;
        while (par && d < 6) {
            var directText = '';
            for (var ci = 0; ci < par.childNodes.length; ci++) {
                if (par.childNodes[ci].nodeType === 3) {
                    directText += par.childNodes[ci].textContent.trim();
                }
            }
            if (directText.length >= 1 && directText.length <= 30) {
                return cleanLabel(directText);
            }
            par = par.parentElement;
            d++;
        }

        // 元素自身文本（按钮/链接/菜单项）
        var selfText = '';
        for (var ci2 = 0; ci2 < el.childNodes.length; ci2++) {
            if (el.childNodes[ci2].nodeType === 3) {
                selfText += el.childNodes[ci2].textContent.trim();
            }
        }
        if (selfText.length >= 1 && selfText.length <= 20) {
            return cleanLabel(selfText);
        }

        // 按钮类元素回退到 textContent
        if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' ||
            el.getAttribute('role') === 'tab' ||
            (getClassName(el).includes('menu-item'))) {
            var btnText = (el.textContent || '').trim();
            if (btnText.length >= 1 && btnText.length <= 20) return cleanLabel(btnText);
        }

        return null;
    }

    // ═══════════════════════════════════════════════
    // 元素类型检测
    // ═══════════════════════════════════════════════

    function getClassName(el) {
        if (!el) return '';
        if (typeof el.className === 'string') return el.className;
        if (el.className && el.className.baseVal) return el.className.baseVal;
        return '';
    }

    function detectElementType(el) {
        var tag = el.tagName.toLowerCase();
        var cls = getClassName(el);

        // 下拉类（必须在 input 之前）
        if (el.closest(_sel.selectExclude || '.el-select, .el-date-editor, .el-cascader')) {
            if (el.closest('.el-cascader')) return 'el-cascader';
            if (el.closest('.el-date-editor')) return 'date-picker';
            return 'el-select';
        }

        // 按钮类
        if (tag === 'button') return 'button';
        if (cls.includes('ec-button')) return 'button';

        // Tab
        if (el.getAttribute('role') === 'tab') return 'tab';

        // 菜单项
        if (cls.includes('el-menu-item') || cls.includes('ant-menu-item')) return 'menu-item';

        // 下拉菜单项
        if (el.closest('[x-placement]') && (tag === 'li' || tag === 'span' || tag === 'div')) return 'dropdown-menu-item';

        // 输入类
        if (tag === 'input') {
            if (cls.includes('el-input__inner')) return 'input';
            if (cls.includes('ant-input')) return 'input-antd';
            if (el.type === 'checkbox') return 'checkbox';
            return 'input';
        }

        // 文本域
        if (tag === 'textarea') return 'textarea';

        // 复选框
        if (el.closest('.el-checkbox') || el.closest('.ant-checkbox')) return 'checkbox';

        // 表格行按钮
        if (el.closest('tbody') && (tag === 'span' || tag === 'a' || tag === 'button')) return 'table-action-button';

        // 详情链接
        if (el.closest('td') && (tag === 'a' || cls.includes('link') || cls.includes('href'))) return 'detail-link';

        // 通用可点击
        if (tag === 'a' || el.getAttribute('role') === 'button') return 'clickable';

        return 'unknown';
    }

    // ═══════════════════════════════════════════════
    // 容器检测
    // ═══════════════════════════════════════════════

    function detectContainer(el) {
        var containers = [
            { type: 'dialog', selectors: ['.el-dialog__wrapper', '.el-dialog', '.ant-modal-wrap', '.ant-modal'] },
            { type: 'drawer', selectors: ['.el-drawer', '.ant-drawer'] },
            { type: 'message-box', selectors: ['.el-message-box'] },
        ];
        for (var i = 0; i < containers.length; i++) {
            for (var j = 0; j < containers[i].selectors.length; j++) {
                var c = el.closest(containers[i].selectors[j]);
                if (c && isVisible(c)) {
                    // 尝试提取容器标题
                    var titleEl = c.querySelector('.el-dialog__title, .el-drawer__header, .ant-modal-title');
                    var title = titleEl ? cleanLabel(titleEl.textContent) : null;
                    return { type: containers[i].type, label: title };
                }
            }
        }
        // Tab panel
        var tabPanel = el.closest('[role="tabpanel"]');
        if (tabPanel && isVisible(tabPanel)) {
            return { type: 'tab-panel', label: tabPanel.id || null };
        }
        return null;
    }

    // ═══════════════════════════════════════════════
    // Label-Based XPath 生成（策略列表）
    // ═══════════════════════════════════════════════

    function generateXPathStrategies(el, elemType, label) {
        var cls = getClassName(el).trim();
        var tag = el.tagName.toLowerCase();
        var strategies = [];

        if (!label) {
            return generateStructuralStrategies(el);
        }

        var escapedLabel = escapeXPathStr(label);

        // ─── 按钮 ───
        if (elemType === 'button') {
            strategies.push("//button[contains(., " + escapedLabel + ")]");
            if (label.length >= 2) {
                strategies.push(
                    "//button[contains(., " + escapeXPathStr(label[0]) + ") and contains(., " +
                    escapeXPathStr(label[label.length - 1]) + ")]"
                );
            }
        }

        // ─── 输入框 ───
        else if (elemType === 'input' || elemType === 'input-antd') {
            var inputClass = (elemType === 'input-antd') ? 'ant-input' : 'el-input__inner';
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//input[@class='" + inputClass + "']"
            );
            strategies.push(
                "//label[contains(., " + escapedLabel + ")]//following-sibling::*[self::div or self::span]//input[@class='" + inputClass + "']"
            );
            var ph = el.getAttribute('placeholder');
            if (ph && ph.length <= 30) {
                strategies.push("//input[contains(@placeholder, " + escapeXPathStr(ph) + ")]");
            }
        }

        // ─── 下拉选择 ───
        else if (elemType === 'el-select') {
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]"
            );
            strategies.push(
                "//label[contains(., " + escapedLabel + ")]//following-sibling::*[self::div or self::span]//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]"
            );
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
            );
        }

        // ─── 日期选择 ───
        else if (elemType === 'date-picker') {
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
            );
            strategies.push(
                "//label[contains(., " + escapedLabel + ")]//following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
            );
        }

        // ─── 级联选择 ───
        else if (elemType === 'el-cascader') {
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-cascader')]"
            );
            strategies.push(
                "//label[contains(., " + escapedLabel + ")]//following-sibling::*[self::div or self::span]//div[contains(@class,'el-cascader')]"
            );
        }

        // ─── 文本域 ───
        else if (elemType === 'textarea') {
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//textarea"
            );
            strategies.push(
                "//label[contains(., " + escapedLabel + ")]//following-sibling::*[self::div or self::span]//textarea"
            );
        }

        // ─── Tab ───
        else if (elemType === 'tab') {
            strategies.push("//*[contains(text(), " + escapedLabel + ") and @role='tab']");
        }

        // ─── 菜单项 ───
        else if (elemType === 'menu-item') {
            strategies.push("//*[contains(@class,'el-menu-item') and contains(., " + escapedLabel + ")]");
            strategies.push("//*[contains(@class,'ant-menu-item') and contains(., " + escapedLabel + ")]");
        }

        // ─── 表格行按钮 ───
        else if (elemType === 'table-action-button') {
            strategies.push(
                "//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//span[contains(., " + escapedLabel + ")]"
            );
            strategies.push(
                "//div[contains(@class,'el-table__body-wrapper')]//tbody/tr[1]//span[contains(., " + escapedLabel + ")]"
            );
            strategies.push(
                "//tbody/tr[1]//*[contains(., " + escapedLabel + ")]"
            );
        }

        // ─── 下拉菜单项 ───
        else if (elemType === 'dropdown-menu-item') {
            strategies.push(
                "//*[@x-placement and not(@x-placement='')]//*[contains(text(), " + escapedLabel + ")]"
            );
        }

        // ─── 详情链接 ───
        else if (elemType === 'detail-link') {
            strategies.push(
                "//td[not(contains(@class,'is-hidden'))]//*[contains(text(), " + escapedLabel + ")]"
            );
        }

        // ─── 复选框 ───
        else if (elemType === 'checkbox') {
            strategies.push(
                "//label[contains(@class,'el-checkbox') and contains(., " + escapedLabel + ")]"
            );
            strategies.push(
                "//span[contains(@class,'el-checkbox__label') and contains(text(), " + escapedLabel + ")]"
            );
        }

        // ─── 通用兜底 ───
        if (strategies.length === 0) {
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]/following-sibling::*[self::div or self::span]//" + tag +
                (cls ? "[@class='" + cls + "']" : "")
            );
            strategies.push(
                "//*[contains(text(), " + escapedLabel + ")]//" + tag +
                (cls ? "[@class='" + cls + "']" : "")
            );
        }

        // placeholder 兜底（对所有 input 类型）
        if (elemType !== 'button' && elemType !== 'table-action-button') {
            var ph2 = el.getAttribute('placeholder');
            if (ph2 && ph2.length > 0 && ph2.length <= 30) {
                strategies.push("//" + tag + "[@placeholder=" + escapeXPathStr(ph2) + "]");
            }
        }

        return strategies;
    }

    // ═══════════════════════════════════════════════
    // 结构路径降级（复用 _ai_xpath_from_elem.js 逻辑）
    // ═══════════════════════════════════════════════

    function generateStructuralStrategies(el) {
        var parts = [];
        var node = el;
        while (node && node.nodeType === 1 && node !== document.body) {
            if (node.id) {
                parts.unshift("//*[@id='" + node.id + "']");
                break;
            }
            var idx = 1;
            var sib = node.previousElementSibling;
            while (sib) {
                if (sib.tagName === node.tagName) idx++;
                sib = sib.previousElementSibling;
            }
            var t = node.tagName.toLowerCase();
            var c = node.className && typeof node.className === 'string'
                    ? node.className.trim().split(/\s+/)[0] : '';
            if (c && !c.match(/^[\d]/)) {
                parts.unshift(t + "[contains(@class,'" + c + "')]");
                var breakClasses = _brk || [];
                if (breakClasses.some(function(bc) { return c.startsWith(bc); })) {
                    break;
                }
            } else {
                parts.unshift(t + "[" + idx + "]");
            }
            node = node.parentElement;
            if (parts.length > 6) break;
        }
        return ['//' + parts.join('/')];
    }

    // ═══════════════════════════════════════════════
    // CSS 注入
    // ═══════════════════════════════════════════════

    function injectStyles() {
        _styleEl = document.createElement('style');
        _styleEl.id = 'xpath-picker-styles';
        _styleEl.textContent = [
            '#xp-picker { position:fixed; top:10px; right:10px; width:460px; max-height:80vh;',
            '  background:rgba(30,30,30,0.95); color:#e0e0e0; font-family:Consolas,monospace;',
            '  font-size:12px; border-radius:8px; box-shadow:0 4px 20px rgba(0,0,0,0.5);',
            '  z-index:2147483647; overflow:auto; user-select:text; }',
            '#xp-picker .xp-header { padding:8px 12px; background:rgba(60,60,60,0.8);',
            '  border-radius:8px 8px 0 0; display:flex; justify-content:space-between; align-items:center;',
            '  cursor:move; }',
            '#xp-picker .xp-title { font-weight:bold; color:#4CAF50; font-size:13px; }',
            '#xp-picker .xp-body { padding:8px 12px; }',
            '#xp-picker .xp-field { margin:4px 0; }',
            '#xp-picker .xp-label { color:#888; }',
            '#xp-picker .xp-value { color:#fff; }',
            '#xp-picker .xp-xpath { background:#1a1a2e; padding:6px 8px; border-radius:4px;',
            '  word-break:break-all; margin:4px 0; font-size:11px; max-height:100px; overflow:auto;',
            '  border:1px solid #333; }',
            '#xp-picker .xp-status { padding:4px 8px; border-radius:4px; margin:4px 0; font-size:11px; }',
            '#xp-picker .xp-status.ok { background:rgba(76,175,80,0.2); color:#4CAF50; }',
            '#xp-picker .xp-status.fail { background:rgba(244,67,54,0.2); color:#f44336; }',
            '#xp-picker .xp-status.wait { background:rgba(255,193,7,0.2); color:#FFC107; }',
            '#xp-picker .xp-list { max-height:180px; overflow-y:auto; margin:6px 0; }',
            '#xp-picker .xp-item { padding:3px 6px; border-bottom:1px solid #333; font-size:11px;',
            '  display:flex; justify-content:space-between; }',
            '#xp-picker .xp-item:hover { background:rgba(255,255,255,0.05); }',
            '#xp-picker .xp-btns { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }',
            '#xp-picker .xp-btn { padding:5px 12px; border:1px solid #555; border-radius:4px;',
            '  background:rgba(60,60,60,0.8); color:#e0e0e0; cursor:pointer; font-size:11px;',
            '  font-family:inherit; }',
            '#xp-picker .xp-btn:hover { background:rgba(80,80,80,0.9); }',
            '#xp-picker .xp-btn.primary { border-color:#4CAF50; color:#4CAF50; }',
            '#xp-picker .xp-btn.danger { border-color:#f44336; color:#f44336; }',
            '.xp-highlight { outline:2px solid #4CAF50 !important; outline-offset:2px !important; }',
            '.xp-highlight-locked { outline:3px solid #2196F3 !important; outline-offset:2px !important;',
            '  box-shadow:0 0 8px rgba(33,150,243,0.4) !important; }',
        ].join('\n');
        document.head.appendChild(_styleEl);
    }

    // ═══════════════════════════════════════════════
    // 浮层 UI 构建
    // ═══════════════════════════════════════════════

    function createPanel() {
        _panel = document.createElement('div');
        _panel.id = 'xp-picker';
        _panel.innerHTML = [
            '<div class="xp-header">',
            '  <span class="xp-title">🔍 XPath Picker</span>',
            '  <span id="xp-status-badge" style="font-size:11px;color:#888;">就绪</span>',
            '</div>',
            '<div class="xp-body">',
            '  <div class="xp-field"><span class="xp-label">状态: </span>',
            '    <span id="xp-mode" class="xp-value">🟢 拾取中</span>',
            '  </div>',
            '  <hr style="border-color:#444;margin:6px 0;">',
            '  <div id="xp-current">',
            '    <div class="xp-field"><span class="xp-label">标签: </span><span id="xp-cur-label" class="xp-value">—</span></div>',
            '    <div class="xp-field"><span class="xp-label">类型: </span><span id="xp-cur-type" class="xp-value">—</span>',
            '      <span style="margin-left:12px" class="xp-label">容器: </span><span id="xp-cur-container" class="xp-value">—</span></div>',
            '    <div class="xp-field"><span class="xp-label">XPath 预览:</span></div>',
            '    <div id="xp-cur-xpath" class="xp-xpath">hover 元素以预览…</div>',
            '    <div id="xp-verify-status" class="xp-status" style="display:none;"></div>',
            '  </div>',
            '  <hr style="border-color:#444;margin:6px 0;">',
            '  <div class="xp-field"><span class="xp-label">当前元素:</span></div>',
            '  <div id="xp-list" class="xp-list"><div style="color:#666;font-size:11px;">暂无</div></div>',
            '  <div class="xp-btns">',
            '    <button class="xp-btn primary" id="xp-btn-writeback">💾 写入 YAML</button>',
            '    <button class="xp-btn danger" id="xp-btn-exit">✕ 退出</button>',
            '  </div>',
            '  <div style="margin-top:6px;color:#555;font-size:10px;">提示: Esc 退出 | 点击元素拾取</div>',
            '</div>',
        ].join('\n');
        document.body.appendChild(_panel);

        // 按钮事件
        document.getElementById('xp-btn-writeback').addEventListener('click', function(e) {
            e.stopPropagation();
            writebackToYAML();
        });
        document.getElementById('xp-btn-exit').addEventListener('click', function(e) {
            e.stopPropagation();
            exitPicker();
        });
    }

    // ═══════════════════════════════════════════════
    // UI 更新函数
    // ═══════════════════════════════════════════════

    function updatePreview(label, type, container, xpathPreview) {
        var el;
        el = document.getElementById('xp-cur-label');
        if (el) el.textContent = label || '—';
        el = document.getElementById('xp-cur-type');
        if (el) el.textContent = type || '—';
        el = document.getElementById('xp-cur-container');
        if (el) el.textContent = container ? (container.type + (container.label ? ' (' + container.label + ')' : '')) : '—';
        el = document.getElementById('xp-cur-xpath');
        if (el) el.textContent = xpathPreview || 'hover 元素以预览…';
        el = document.getElementById('xp-verify-status');
        if (el) el.style.display = 'none';
    }

    function updateVerified(result) {
        var el = document.getElementById('xp-verify-status');
        if (!el) return;
        el.style.display = 'block';
        if (result.valid) {
            el.className = 'xp-status ok';
            el.textContent = '✅ count=' + result.count + '  策略: ' + result.strategy;
        } else {
            el.className = 'xp-status fail';
            el.textContent = '❌ count=' + result.count + '  所有策略均未匹配';
        }
        // 更新 XPath 显示为验证后的版本
        var xpathEl = document.getElementById('xp-cur-xpath');
        if (xpathEl && result.xpath) {
            xpathEl.textContent = result.xpath;
        }
    }

    function addToList(result) {
        // 单元素模式：替换而非追加
        var listEl = document.getElementById('xp-list');
        if (!listEl) return;

        // 清空并显示当前元素
        listEl.innerHTML = '';

        var item = document.createElement('div');
        item.className = 'xp-item';
        var icon = result.valid ? '✅' : '❌';
        item.innerHTML = '<span>' + icon + ' ' + (result.label || '?') +
            ' (' + (result.type || '?') + ')</span><span style="color:#888;">count=' + result.count + '</span>';
        listEl.appendChild(item);

        // 显示 XPath
        var xpathDiv = document.createElement('div');
        xpathDiv.className = 'xp-xpath';
        xpathDiv.style.marginTop = '4px';
        xpathDiv.textContent = result.xpath;
        listEl.appendChild(xpathDiv);
    }

    function writebackToYAML() {
        var lastValid = window.__picker_last_valid;
        if (!lastValid || !lastValid.valid) {
            alert('没有有效的拾取结果');
            return;
        }
        // 设置写回请求，Python 端会检测并处理
        window.__picker_writeback_request = {
            timestamp: Date.now()
        };
        // 视觉反馈
        var btn = document.getElementById('xp-btn-writeback');
        if (btn) {
            var orig = btn.textContent;
            btn.textContent = '⏳ 写入中...';
            setTimeout(function() { btn.textContent = orig; }, 2000);
        }
    }

    function exitPicker() {
        window.__picker_exit = true;
        cleanup();
    }

    // ═══════════════════════════════════════════════
    // 高亮与锁定
    // ═══════════════════════════════════════════════

    function setHighlight(el) {
        if (_highlighted && _highlighted !== el) {
            _highlighted.classList.remove('xp-highlight');
        }
        if (el) {
            el.classList.add('xp-highlight');
        }
        _highlighted = el;
    }

    function lockHighlight(el) {
        if (_highlighted) _highlighted.classList.remove('xp-highlight');
        el.classList.add('xp-highlight-locked');
        _highlighted = el;
        _locked = true;
    }

    function unlockHighlight() {
        if (_highlighted) {
            _highlighted.classList.remove('xp-highlight');
            _highlighted.classList.remove('xp-highlight-locked');
        }
        _highlighted = null;
    }

    // ═══════════════════════════════════════════════
    // 事件处理
    // ═══════════════════════════════════════════════

    function isInsidePanel(el) {
        return _panel && (_panel === el || _panel.contains(el));
    }

    // ═══════════════════════════════════════════════
    // 拖动面板
    // ═══════════════════════════════════════════════
    function onDragStart(e) {
        if (!_panel) return;
        _dragging = true;
        _dragStart = {x: e.clientX, y: e.clientY};

        // 获取面板当前位置（支持 top/right 或 top/left 两种布局）
        var rect = _panel.getBoundingClientRect();
        var computedStyle = window.getComputedStyle(_panel);

        // 如果使用了 right 定位，转换为 left 定位以便拖动
        if (computedStyle.right && computedStyle.right !== 'auto') {
            var panelLeft = window.innerWidth - rect.right;
            _panel.style.left = panelLeft + 'px';
            _panel.style.right = 'auto';
        }

        _panelStart = {
            x: parseInt(computedStyle.left) || rect.left,
            y: parseInt(computedStyle.top) || rect.top
        };

        e.preventDefault();
        e.stopPropagation();
    }

    function onDragMove(e) {
        if (!_dragging || !_panel) return;
        var dx = e.clientX - _dragStart.x;
        var dy = e.clientY - _dragStart.y;

        var newX = _panelStart.x + dx;
        var newY = _panelStart.y + dy;

        // 边界检查：确保面板不超出视口
        var panelWidth = _panel.offsetWidth;
        var panelHeight = _panel.offsetHeight;
        newX = Math.max(0, Math.min(newX, window.innerWidth - panelWidth));
        newY = Math.max(0, Math.min(newY, window.innerHeight - panelHeight));

        _panel.style.left = newX + 'px';
        _panel.style.top = newY + 'px';

        e.preventDefault();
    }

    function onDragEnd(e) {
        _dragging = false;
    }

    function onMove(e) {
        if (_locked) return;
        var el = e.target;
        if (isInsidePanel(el)) return;
        if (el === _highlighted) return;
        setHighlight(el);

        var label = extractLabel(el);
        var type = detectElementType(el);
        var container = detectContainer(el);
        var strategies = generateXPathStrategies(el, type, label);
        updatePreview(label, type, container, strategies[0] || '—');
    }

    function onClick(e) {
        // 如果点击的是面板内的元素，不处理
        if (isInsidePanel(e.target)) return;

        e.preventDefault();
        e.stopPropagation();

        if (_locked) {
            // 已锁定状态：解锁并拾取新元素
            unlockHighlight();
            _locked = false;
        }

        var el = _highlighted || e.target;
        if (!el || el === document.body || el === document.documentElement) return;

        var label = extractLabel(el);
        var type = detectElementType(el);
        var container = detectContainer(el);
        var strategies = generateXPathStrategies(el, type, label);

        lockHighlight(el);

        // 缓存当前拾取信息（用于 pollVerified 读取，解决 "? (?)" 问题）
        _pendingPick = {
            label: label,
            type: type,
            container: container ? container.type : null,
            container_label: container ? container.label : null,
            tagName: el.tagName.toLowerCase(),
            className: getClassName(el)
        };

        // 传递给 Python 端验证
        window.__picker_pick = {
            strategies: strategies,
            label: label,
            type: type,
            container: container ? container.type : null,
            container_label: container ? container.label : null,
            tagName: el.tagName.toLowerCase(),
            className: getClassName(el)
        };

        // 更新 UI 为等待验证状态
        var statusEl = document.getElementById('xp-verify-status');
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.className = 'xp-status wait';
            statusEl.textContent = '⏳ 验证中…';
        }
        var modeEl = document.getElementById('xp-mode');
        if (modeEl) modeEl.textContent = '⏳ 验证中';
    }

    function onKey(e) {
        if (e.key === 'Escape') {
            exitPicker();
        }
    }

    // ═══════════════════════════════════════════════
    // 轮询验证结果（Python 端写回后 JS 端读取并更新 UI）
    // ═══════════════════════════════════════════════

    function pollVerified() {
        var v = window.__picker_verified;
        if (v) {
            updateVerified(v);
            if (v.valid) {
                // 从 _pendingPick 缓存中补充 label/type/container（修复 "? (?)" 问题）
                var pick = _pendingPick || {};
                var result = {
                    xpath: v.xpath,
                    count: v.count,
                    strategy: v.strategy,
                    valid: v.valid,
                    label: v.label || pick.label || '?',
                    type: v.type || pick.type || '?',
                    container: v.container || pick.container || null,
                    container_label: v.container_label || pick.container_label || null
                };
                // 单元素模式：覆盖而非追加
                window.__picker_last_valid = result;
                addToList(result);
            }
            window.__picker_verified = null;
            _pendingPick = null;  // 清空缓存
            // 解锁，允许拾取下一个
            unlockHighlight();
            _locked = false;
            var modeEl = document.getElementById('xp-mode');
            if (modeEl) modeEl.textContent = '🟢 拾取中';
        }
        if (!window.__picker_exit) {
            setTimeout(pollVerified, 200);
        }
    }

    // ═══════════════════════════════════════════════
    // 清理
    // ═══════════════════════════════════════════════

    function cleanup() {
        if (_clickHandler) document.removeEventListener('click', _clickHandler, true);
        if (_moveHandler) document.removeEventListener('mousemove', _moveHandler);
        if (_keyHandler) document.removeEventListener('keydown', _keyHandler);
        if (_dragMoveHandler) document.removeEventListener('mousemove', _dragMoveHandler);
        if (_dragUpHandler) document.removeEventListener('mouseup', _dragUpHandler);
        if (_highlighted) {
            _highlighted.classList.remove('xp-highlight');
            _highlighted.classList.remove('xp-highlight-locked');
        }
        if (_panel && _panel.parentNode) _panel.parentNode.removeChild(_panel);
        if (_styleEl && _styleEl.parentNode) _styleEl.parentNode.removeChild(_styleEl);
        _panel = null;
        _styleEl = null;
    }
    window.__picker_cleanup = cleanup;

    // ═══════════════════════════════════════════════
    // 初始化
    // ═══════════════════════════════════════════════

    function init() {
        // 防止重复初始化
        if (_panel) cleanup();

        injectStyles();
        createPanel();

        _moveHandler = onMove;
        _clickHandler = onClick;
        _keyHandler = onKey;

        document.addEventListener('mousemove', _moveHandler);
        document.addEventListener('click', _clickHandler, true);  // capture phase
        document.addEventListener('keydown', _keyHandler);

        // 拖动面板：在标题栏 mousedown 时激活
        var header = _panel.querySelector('.xp-header');
        if (header) {
            header.addEventListener('mousedown', onDragStart);
        }
        _dragMoveHandler = onDragMove;
        _dragUpHandler = onDragEnd;
        document.addEventListener('mousemove', _dragMoveHandler);
        document.addEventListener('mouseup', _dragUpHandler);

        // 启动验证结果轮询
        setTimeout(pollVerified, 200);
    }

    init();
})();
