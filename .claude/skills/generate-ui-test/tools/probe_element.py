"""按需元素探测库 v3.2

核心能力：
  A. el-select 精确匹配：检测子串冲突时生成两步操作（展开+text-is精确点击）
  B. 表格感知重试：探测失败时自动检测表格上下文，尝试行级选择器，永不放弃
  C. 知识库探测：优先使用已验证的 XPath 模板，支持自学习
  D. 富文本检测：textarea 的 TinyMCE/UEditor/iframe 自动识别

主入口：probe_element(page, etype, label, key, container_types=None)

被以下模块调用：
  - verify_locators.py (R6 兜底)
  - discover_page.py (Phase 4 探测)
  - _case_generator.py (Phase 5 KB 查询)
"""
import json
import re
import sys
import os
from xpath_utils import CONTAINER_XPATH, _unwrap_positional, _rewrap_positional
from field_suffixes import DIALOG_CONFIRM_LABELS, CONTAINER_PRIORITY
from _element_types import normalize_type as _normalize_type


# ============================================================
# 通用常量
# ============================================================

# Cookie 中的 token 键名，用于自动同步到 localStorage
TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'auth_token', 'jwt_token'}

# el-select 排除下拉面板容器（防止匹配到已展开面板中的 el-select 元素）
_EXCL_DROPDOWN = " and not(contains(@class,'el-select-dropdown'))"


# ============================================================
# 知识库加载
# ============================================================

DEFAULT_KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "probe_knowledge.json")
_knowledge_db = None


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


def _contains_text(label: str) -> str:
    """生成 XPath contains(text(),...) 表达式，自动处理单引号

    无单引号 → contains(text(),'label')
    有单引号 → contains(text(),concat('before', "'", 'after'))
    """
    escaped = _xpath_escape_label(label)
    if escaped == label:
        return f"contains(text(),'{label}')"
    return f"contains(text(),{escaped})"


def _contains_dot(label: str) -> str:
    """生成 XPath contains(.,...) 表达式，自动处理单引号

    无单引号 → contains(.,'label')
    有单引号 → contains(.,concat('before', "'", 'after'))
    """
    escaped = _xpath_escape_label(label)
    if escaped == label:
        return f"contains(.,'{label}')"
    return f"contains(.,{escaped})"


def _safe_format(template, variables):
    """安全字符串格式化：未知占位符保留原样而非抛出 KeyError

    用于 probe_knowledge.json 模板替换，模板中可能包含 {option_text}、
    {element_id}、{keyword} 等探测阶段无法提供的占位符。
    """
    import re
    def replacer(match):
        key = match.group(1)
        return str(variables.get(key, match.group(0)))
    return re.sub(r'\{(\w+)\}', replacer, template)


# ============================================================
# 二级子类型检测（方案 B）
# ============================================================

def _detect_component_type(page, etype, label):
    """检测组件的二级子类型（如 el-select 是否为可编辑模式）"""
    if etype != 'el-select':
        return etype
    return etype


def _has_table_context(page):
    """检测当前页面是否存在可见表格（用于 button → table-action-button 路由）"""
    try:
        return page.evaluate("""() => {
            const tables = document.querySelectorAll('.el-table');
            for (const t of tables) {
                const rect = t.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return true;
            }
            return false;
        }""")
    except Exception:
        return False


# ============================================================
# count=0 KB fallback
# ============================================================

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


# ============================================================
# CLI 解析
# ============================================================

def parse_cookie(cookie_str, domain):
    if not cookie_str:
        return []
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name, value = name.strip(), value.strip()
        if name:
            cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
    return cookies


# ============================================================
# 容器检测和纠错辅助函数
# ============================================================

def detect_visible_containers(page):
    """检测页面上当前可见的容器类型（el-drawer, el-dialog, el-message-box）

    :param page: Playwright page
    :return: list of container types, e.g., ["dialog", "drawer", "message-box"]
    """
    try:
        return page.evaluate("""
            () => {
                const visible = [];
                // 检查 el-drawer
                const drawers = document.querySelectorAll('.el-drawer');
                for (const drawer of drawers) {
                    const rect = drawer.getBoundingClientRect();
                    const style = window.getComputedStyle(drawer);
                    if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                        visible.push('drawer');
                        break;
                    }
                }
                // 检查 el-dialog
                const dialogs = document.querySelectorAll('.el-dialog');
                for (const dialog of dialogs) {
                    const rect = dialog.getBoundingClientRect();
                    const style = window.getComputedStyle(dialog);
                    if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                        visible.push('dialog');
                        break;
                    }
                }
                // R4 修复: 检查 el-message-box
                const msgBoxes = document.querySelectorAll('.el-message-box');
                for (const mb of msgBoxes) {
                    const rect = mb.getBoundingClientRect();
                    const style = window.getComputedStyle(mb);
                    if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                        visible.push('message-box');
                        break;
                    }
                }
                return visible;
            }
        """)
    except Exception:
        return []


def _strip_container_prefix(xpath_expr):
    """剥离 XPath 表达式中的容器前缀

    支持两种格式：
    - 裸 XPath: //div[...]//button → //button
    - 包裹 XPath: (//div[...]//button)[1] → (//button)[1]
    """
    inner, wrap = _unwrap_positional(xpath_expr)
    pattern = r"^//div\[contains\(@class,'el-(drawer|dialog|message-box)'\)\]"
    stripped = re.sub(pattern, "", inner)
    return _rewrap_positional(stripped, wrap)


def _add_container_prefix(xpath_expr, container_type):
    """为 XPath 表达式添加容器前缀

    支持 (xpath)[N] 包裹格式：前缀注入到括号内部
    """
    prefix = CONTAINER_XPATH.get(container_type, "")
    if not prefix:
        return xpath_expr
    inner, wrap = _unwrap_positional(xpath_expr)
    return _rewrap_positional(prefix + inner, wrap)


# ============================================================
# 通用辅助函数
# ============================================================

def safe_count(page, selector):
    try:
        return page.locator(selector).count()
    except Exception:
        return -1


# ============================================================
# input/textarea 探测
# ============================================================

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


    return result


# ============================================================
# checkbox 探测（问题 B 增强）
    return result


# ============================================================
# 问题 D：操作后观察模式
    return result


    return result


# ============================================================
# checkbox-all 表头全选复选框探测
    return {"key": key, "type": "checkbox-all", "label": label, "verified": False, "count": 0}


# ============================================================
# table-action-button 表格操作列按钮探测
    return {"key": key, "type": "table-action-button", "label": label, "verified": False, "count": 0}


# ============================================================
# dropdown-menu 下拉菜单探测
# ============================================================


# ============================================================
# tab-scoped 多 tab 作用域内探测
    return {"key": key, "type": "tab-scoped", "label": label, "verified": False, "count": 0}
