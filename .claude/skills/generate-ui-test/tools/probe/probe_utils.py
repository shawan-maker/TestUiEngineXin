#!/usr/bin/env python3
"""probe_utils.py — 探针共享工具函数

从 probe_element.py 提取的已验证函数，供 discover_page.py / verify_locators.py 共用。
消除三份独立 KB 加载代码的重复维护。

来源: probe_element.py (v3 备份一致，2522 行)
提取策略: 直接拷贝 + 最小适配
"""

import json
import os
import re

from core.xpath_utils import CONTAINER_XPATH
from core.field_suffixes import DIALOG_CONFIRM_LABELS


# ============================================================
# ▼▼▼ 以下全部从 probe_element.py 直接拷贝，零修改 ▼▼▼
# ============================================================

# ---- 拷贝自 probe_element.py line 60 ----
# 知识库路径：tools/probe_knowledge.json（tools 目录，不是 tools/probe）
DEFAULT_KNOWLEDGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "probe_knowledge.json")
_knowledge_db = None


# ---- 拷贝自 probe_element.py line 64-76 ----
def load_knowledge(knowledge_path=None):
    """加载探针知识库"""
    global _knowledge_db
    if _knowledge_db is not None:
        return _knowledge_db

    path = knowledge_path or DEFAULT_KNOWLEDGE_PATH
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            _knowledge_db = json.load(f)
    else:
        _knowledge_db = {"version": "1.0", "categories": {}}
    return _knowledge_db


# ---- 拷贝自 probe_element.py line 78-90 ----
def _xpath_escape_label(label: str) -> str:
    """转义 label 中的单引号（XPath 1.0 兼容）

    处理: ' → concat('before', "'", 'after')
    不含单引号的 label 原样返回。
    """
    if not label or "'" not in label:
        return label
    parts = label.split("'")
    if len(parts) == 2:
        return f"""concat('{parts[0]}', "'", '{parts[1]}')"""
    segments = [f"'{p}'" if p else '"\'"' for p in parts]
    return f"concat({', '.join(segments)})"


# ---- 拷贝自 probe_element.py line 93-102 ----
def _contains_text(label: str) -> str:
    """生成 XPath contains(text(),...) 表达式，自动处理单引号"""
    escaped = _xpath_escape_label(label)
    if escaped == label:
        return f"contains(text(),'{label}')"
    return f"contains(text(),{escaped})"


# ---- 拷贝自 probe_element.py line 105-114 ----
def _contains_dot(label: str) -> str:
    """生成 XPath contains(.,...) 表达式，自动处理单引号"""
    escaped = _xpath_escape_label(label)
    if escaped == label:
        return f"contains(.,'{label}')"
    return f"contains(.,{escaped})"


# ---- 拷贝自 probe_element.py line 117-127 ----
def _safe_format(template, variables):
    """安全字符串格式化：未知占位符保留原样而非抛出 KeyError

    用于 probe_knowledge.json 模板替换，模板中可能包含 {option_text}、
    {element_id}、{keyword} 等探测阶段无法提供的占位符。
    """
    def replacer(match):
        key = match.group(1)
        return str(variables.get(key, match.group(0)))
    return re.sub(r'\{(\w+)\}', replacer, template)


# ---- 拷贝自 probe_element.py line 403-420 ----
def _get_expand_patterns(etype):
    """从 KB 中提取指定类型的 expand patterns"""
    db = load_knowledge()
    for section in ("single_step", "multi_step", "composite"):
        cats = db.get(section, {}).get("categories", {})
        if etype in cats:
            category = cats[etype]
            steps = category.get("steps", {})
            if steps:
                expand = steps.get("expand", {})
                patterns = expand.get("patterns", [])
                if not patterns:
                    first_step = next(iter(steps.values()), {})
                    patterns = first_step.get("patterns", [])
            else:
                patterns = category.get("patterns", [])
            return patterns
    return []


# ---- Re-export from _element_types (unified type system) ----
# KB_KEY_ALIAS: legacy raw type → KB canonical key
# Derived from DISCOVERY_TO_KB (only entries where raw ≠ canonical)
from core.element_types import DISCOVERY_TO_KB as _D2K
KB_KEY_ALIAS = {raw: canon for raw, canon in _D2K.items() if raw != canon}

# Fix-2: checkbox 硬编码兜底模板（KB 无 "checkbox" 键，只有 "checkbox-all"）
# 默认勾选表格第一行的 checkbox
CHECKBOX_HARDCODED = [
    '//div[contains(@class,"el-table__body-wrapper")]//tbody//tr[1]//*[@class="el-checkbox__inner"]',
    # Ant Design
    '//div[contains(@class,"ant-table-tbody")]//tr[contains(@class,"ant-table-row")][1]//span[contains(@class,"ant-checkbox-inner")]'
]


# ---- 拷贝自 probe_element.py line 1259-1386 ----
def _detect_rich_text(page, label):
    """检测 textarea 是否为富文本编辑器（TinyMCE/UEditor 等）。

    不依赖 .el-form-item 结构，而是：
    1. 通过 label 文本找到 textarea 元素
    2. 检查 textarea 是否被隐藏（aria-hidden / display:none）
    3. 如果隐藏，向上遍历父级（最多 8 层）查找 iframe
    4. 同时检查 contenteditable 元素

    Returns: dict with is_rich_text, has_iframe, has_editable, iframe_xpath, reason
    """
    result = {
        "is_rich_text": False,
        "has_iframe": False,
        "has_editable": False,
        "iframe_xpath": None,
        "reason": None,
    }
    try:
        info = page.evaluate("""(label) => {
            // H3 修复: XPath 1.0 不支持 \\' 转义，改用双引号包裹或 concat()
            let containsExpr;
            if (label.indexOf("'") === -1) {
                containsExpr = "contains(text(),'" + label + "')";
            } else if (label.indexOf('"') === -1) {
                containsExpr = 'contains(text(),"' + label + '")';
            } else {
                // 极端情况: 同时含单双引号，用 concat()
                const parts = label.split("'");
                const segs = [];
                for (let i = 0; i < parts.length; i++) {
                    segs.push("'" + parts[i] + "'");
                    if (i < parts.length - 1) segs.push("\\"'\\"");
                }
                containsExpr = "contains(text(),concat(" + segs.join(",") + "))";
            }
            // Step 1: 通过 label 文本找到 textarea
            const xpath = "//*[" + containsExpr + "]/following-sibling::*[self::div or self::span]//textarea";
            let ta = null;
            try {
                ta = document.evaluate(xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            } catch(e) {}
            if (!ta) {
                // fallback: 直接在页面中找所有 textarea，检查附近的 label
                const allTa = document.querySelectorAll('textarea');
                for (const t of allTa) {
                    let prev = t.parentElement;
                    for (let i = 0; i < 5 && prev; i++) {
                        if (prev.textContent && prev.textContent.includes(label)) {
                            ta = t;
                            break;
                        }
                        prev = prev.parentElement;
                    }
                    if (ta) break;
                }
            }
            if (!ta) return { is_rich_text: false };

            // Step 2: 检查 textarea 是否被隐藏
            const ariaHidden = ta.getAttribute('aria-hidden');
            const display = window.getComputedStyle(ta).display;
            const isHidden = ariaHidden === 'true' || display === 'none';
            const idContainsEditor = (ta.id || '').includes('tiny') ||
                                     (ta.id || '').includes('editor') ||
                                     (ta.id || '').includes('ueditor');
            const hasTinyMCE = typeof tinymce !== 'undefined';

            if (!isHidden && !(hasTinyMCE && idContainsEditor)) {
                return { is_rich_text: false };
            }

            // Step 3: textarea 被隐藏，向上遍历父级查找 iframe
            let parent = ta.parentElement;
            let iframe = null;
            let editable = null;
            let depth = 0;
            while (parent && depth < 8) {
                if (!iframe) iframe = parent.querySelector('iframe');
                if (!editable) editable = parent.querySelector('[contenteditable="true"]');
                if (iframe || editable) break;
                parent = parent.parentElement;
                depth++;
            }

            // Step 4: 生成 iframe 的 XPath（用于 frame_fill_value 的 frame 参数）
            let iframeXPath = null;
            if (iframe) {
                // 基于 label 构建 iframe XPath（使用 containsExpr）
                iframeXPath = "//*[" + containsExpr + "]/following-sibling::*[self::div or self::span]//iframe";
                // 验证 iframe XPath 能匹配到元素
                let found = null;
                try {
                    found = document.evaluate(iframeXPath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                } catch(e) {}
                if (!found) {
                    // fallback: 用 following-sibling::div//iframe
                    iframeXPath = "//*[" + containsExpr + "]/following-sibling::div//iframe";
                    try {
                        found = document.evaluate(iframeXPath, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    } catch(e) {}
                }
                if (!found) iframeXPath = null;
            }

            const reason = isHidden ? 'aria-hidden/display-none' :
                           iframe ? 'iframe-editor' : 'tinymce-detected';
            return {
                is_rich_text: true,
                has_iframe: !!iframe,
                has_editable: !!editable,
                iframe_xpath: iframeXPath,
                textarea_id: ta.id || '',
                reason: reason
            };
        }""", label)
        if info.get("is_rich_text"):
            result["is_rich_text"] = True
            result["has_iframe"] = info.get("has_iframe", False)
            result["has_editable"] = info.get("has_editable", False)
            result["iframe_xpath"] = info.get("iframe_xpath")
            result["reason"] = info.get("reason", "unknown")
    except Exception:
        pass
    return result


# ============================================================
# ▼▼▼ 以下拷贝+适配（保留核心逻辑，调整内部调用）▼▼▼
# ============================================================

# ---- 拷贝自 probe_element.py line 437-510 ----
# 适配：内部调用的 _get_expand_patterns / _xpath_escape_label / _safe_format
# 改为调用本模块的同名函数（无需 import，同文件内直接可用）
def kb_fallback(etype, label, key, actual_type=None):
    """count=0 兜底：取 KB 该类型第一个可替换的 expand pattern 作为 locator

    KB pattern 结构正确（经验证），只是当前缺数据。
    运行时前序用例创建数据后，KB 的 XPath 大概率能命中。

    Fix-1: 查找链 actual_type → etype → KB_KEY_ALIAS[etype]，
    确保子类型（search-button 等）和别名类型（input→input-generic）都能命中。

    确认/取消按钮特殊处理：当所有探测失败时，默认加 el-dialog 前缀，
    因为 Element UI 确认对话框中的按钮通常在未弹出的 el-dialog 内。
    """
    # Fix-1: 构建候选查找链
    candidates = []
    if actual_type and actual_type != etype:
        candidates.append(actual_type)
    candidates.append(etype)
    if etype in KB_KEY_ALIAS:
        candidates.append(KB_KEY_ALIAS[etype])

    patterns = []
    matched_key = None
    for kb_key in candidates:
        patterns = _get_expand_patterns(kb_key)  # 本模块函数
        if patterns:
            matched_key = kb_key
            break

    # Fix-2: checkbox 硬编码兜底（KB 无此类型）
    if not patterns and etype == 'checkbox':
        patterns = CHECKBOX_HARDCODED
        matched_key = 'checkbox-hardcoded'

    fmt_vars = {
        'label': label,
        'tab_name': label,
        'char1': label[0] if label else "",
        'char2': label[-1] if label else "",
        # BUG-4 D2: 全拆字模式（审计 4b: 三文件同步）
        # 跳过单引号字符（XPath 语法安全）
        'chars_all': " and ".join(f"contains(.,'{c}')" for c in label if c != "'") if label else "",
    }
    for p in patterns:
        # H3 修复: 当 label 含单引号时，预处理模板
        if "'" in label:
            escaped = _xpath_escape_label(label)
            p = p.replace("'{label}'", escaped)
            p = p.replace("'{tab_name}'", escaped)
            # R1 修复: 处理 char1/char2（按钮拆字模板中的占位符）
            if label and "'" in label[0]:
                p = p.replace("'{char1}'", _xpath_escape_label(label[0]))
            if label and "'" in label[-1]:
                p = p.replace("'{char2}'", _xpath_escape_label(label[-1]))
        xpath = _safe_format(p, fmt_vars)
        if '{' not in xpath:  # 能完全替换的才用
            # 确认/取消按钮：强制加 el-dialog 前缀
            strategy = "kb-fallback"
            if matched_key and matched_key != etype:
                strategy = f"kb-fallback({matched_key})"
            if etype == "button" and label in DIALOG_CONFIRM_LABELS:
                dialog_prefix = CONTAINER_XPATH.get("dialog", "")
                xpath = dialog_prefix + xpath
                strategy = "kb-fallback+dialog-prefix"
            return {
                "key": key,
                "type": etype,
                "label": label,
                "locator": f"xpath={xpath}" if not xpath.startswith("xpath=") else xpath,
                "verified": False,
                "count": 0,
                "strategy": strategy,
                "from_knowledge_fallback": True,
            }
    return None


# ============================================================
# ▼▼▼ 以下新增（基于 probe_element.py 的搜索逻辑扩展）▼▼▼
# ============================================================

def get_kb_patterns(etype):
    """获取 KB 中指定类型的入口 patterns。

    搜索顺序：single_step → multi_step(expand) → composite
    等价于 probe_element.py probe_with_knowledge() line 130-253 的搜索逻辑。
    """
    db = load_knowledge()
    for section in ("single_step", "multi_step", "composite"):
        cats = db.get(section, {}).get("categories", {})
        if etype in cats:
            category = cats[etype]
            steps = category.get("steps", {})
            if steps:
                expand = steps.get("expand", {})
                patterns = expand.get("patterns", [])
                if not patterns:
                    first_step = next(iter(steps.values()), {})
                    patterns = first_step.get("patterns", [])
            else:
                patterns = category.get("patterns", [])
            return patterns
    return []


def get_all_patterns(etype):
    """获取 single_step/composite 的直接 patterns（不含 multi_step）。

    用于 Phase 6 构建完整 candidates 列表。
    """
    db = load_knowledge()
    for section in ("single_step", "composite"):
        cats = db.get(section, {}).get("categories", {})
        if etype in cats:
            return list(cats[etype].get("patterns", []))
    return []


def get_multi_step_patterns(etype, step_name=None):
    """获取 multi_step 指定步骤的 patterns。

    :param step_name: 指定步骤名（如 'expand', 'editable-check'）。
                      None 时返回所有步骤的 patterns。
    """
    db = load_knowledge()
    cats = db.get('multi_step', {}).get('categories', {})
    if etype not in cats:
        return []
    steps = cats[etype].get('steps', {})
    if step_name:
        return list(steps.get(step_name, {}).get('patterns', []))
    # 返回所有步骤的 patterns
    all_patterns = []
    for step in steps.values():
        all_patterns.extend(step.get('patterns', []))
    return all_patterns
