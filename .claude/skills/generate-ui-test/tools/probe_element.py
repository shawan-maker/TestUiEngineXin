"""按需元素探测工具 v3.1

增强能力：
  A. el-select 精确匹配：检测子串冲突时生成两步操作（展开+text-is精确点击）
  B. 表格感知重试：探测失败时自动检测表格上下文，尝试行级选择器，永不放弃
  C. 知识库探测：优先使用已验证的 XPath 模板，支持自学习
  D. 操作后观察：--observe 模式，检测点击后出现的抽屉/对话框/页面变化
  E. locator 直接验证：--verify 模式，验证已有 locator 是否可用

用法：
    # 探测元素（label 搜索策略）
    python probe_element.py <url> --cookie "..." \\
      --element "el-select:项目名称:project_name" \\
      --element "button:查询:query_btn" \\
      --output probe.json

    # 验证已有 locator（直接 count 检查）
    python probe_element.py <url> --cookie "..." \\
      --verify "confirm_btn=xpath=//button[contains(.,'确定')]" \\
      --output verify.json

    # 操作后观察（检测点击后出现什么）
    python probe_element.py <url> --cookie "..." \\
      --observe "click:.el-table__body-wrapper .el-table__row >> nth=0 >> td >> nth=3 >> .cell" \\
      --output observe.json

元素格式：type:label:key
  type  - el-select | button | input | textarea | checkbox | date_picker | dropdown-button
  label - 按钮文本 / 表单标签文本 / placeholder
  key   - pages YAML 中的变量名

验证格式：key=locator
  key     - pages YAML 中的变量名
  locator - 完整的 locator 字符串（xpath=... 或 //...）
"""
import json
import sys
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# 导入共享常量（容器前缀，统一维护在 xpath_utils.py）
sys.path.insert(0, os.path.dirname(__file__))
from xpath_utils import CONTAINER_XPATH, CONTAINER_CLASS_PATTERNS
from field_suffixes import DIALOG_CONFIRM_LABELS, CONTAINER_PRIORITY
from _element_types import normalize_type as _normalize_type


# ============================================================
# 通用常量
# ============================================================

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


def probe_with_knowledge(page, elem_type, label, key, container_types=None):
    """按知识库模板探测元素

    从 probe_knowledge.json v2.0 中查找匹配的元素类型。
    搜索顺序：single_step → multi_step → composite

    当 container_types 非空时，优先尝试容器作用域版本（正向容器前缀），
    再尝试无作用域版本。避免同名标签跨容器匹配错误元素。

    :param container_types: 当前可见容器类型列表，如 ["dialog"]
    :return: (result_dict, used_knowledge)  - used_knowledge 表示是否使用了知识库
    """
    db = load_knowledge()

    # v2.0 结构：搜索 single_step/multi_step/composite 各 sections
    category = None
    for section in ("single_step", "multi_step", "composite"):
        cats = db.get(section, {}).get("categories", {})
        if elem_type in cats:
            category = cats[elem_type]
            break

    if not category:
        return None, False

    # 提取 patterns：兼容 v1.0（flat patterns）和 v2.0（steps.expand.patterns）
    raw_patterns = []
    steps = category.get("steps", {})
    if steps:
        # v2.0 格式：优先取 expand 步骤，否则取第一个步骤
        expand_step = steps.get("expand", {})
        raw_patterns = expand_step.get("patterns", [])
        if not raw_patterns:
            # 没有 expand 步骤（如 dropdown-menu/tab-scoped），取第一个步骤
            first_step = next(iter(steps.values()), {})
            raw_patterns = first_step.get("patterns", [])
    if not raw_patterns:
        # v1.0 格式：patterns 直接在 category 下
        raw_patterns = category.get("patterns", [])
    if not raw_patterns:
        return None, False

    # 容器前缀映射（复用共享常量）

    def _make_result(locator, strategy, container_scoped=False, container_type=None):
        """构造标准结果字典（含级联选择器自动检测）"""
        r = {
            "key": key, "type": elem_type, "label": label,
            "locator": locator, "verified": True, "count": 1,
            "strategy": strategy, "from_knowledge": True,
        }
        if container_scoped:
            r["container_scoped"] = True
            r["container_type"] = container_type
        # 级联选择器自动检测
        if elem_type == "el-select":
            detected = _detect_component_type(page, label)
            if detected == "el-cascader":
                r["type"] = "el-cascader"
                r["recommended_operation"] = "cascader"
                r["component_detected"] = True
                r["note"] = "知识库匹配为 el-select，但 DOM 检测为 el-cascader：click input → 逐级 click 选项，禁止 fill_value"
        return r

    for pattern_str in raw_patterns:
        try:
            # H3 修复: 当 label 含单引号时，预处理模板中的 '{label}' 为 concat() 形式
            if "'" in label:
                escaped = _xpath_escape_label(label)
                pattern_str = pattern_str.replace("'{label}'", escaped)
                pattern_str = pattern_str.replace("'{tab_name}'", escaped)
                # R1 修复: 处理 char1/char2（按钮拆字模板中的占位符）
                if label and "'" in label[0]:
                    pattern_str = pattern_str.replace("'{char1}'", _xpath_escape_label(label[0]))
                if label and "'" in label[-1]:
                    pattern_str = pattern_str.replace("'{char2}'", _xpath_escape_label(label[-1]))

            # 安全格式化：只提供 label/tab_name/char1/char2，其余占位符保留原样
            fmt_vars = {
                'label': label,
                'tab_name': label,
                'char1': label[0] if label else "",
                'char2': label[-1] if label else "",
            }
            xpath = _safe_format(pattern_str, fmt_vars)

            # 跳过仍含未替换占位符的模板（如 {option_text}、{element_id}）
            if '{' in xpath and '}' in xpath:
                continue

            # ★ 优先尝试容器作用域版本（当 container_types 非空时）
            # reversed: detect_visible_containers() 按 DOM 查询顺序返回 [drawer, dialog, message-box]，
            # 倒序遍历使 dialog > drawer（与 CONTAINER_PRIORITY 一致），message-box 最先尝试
            if container_types:
                for ct in sorted(container_types, key=lambda c: CONTAINER_PRIORITY.get(c, 99)):
                    prefix = CONTAINER_XPATH.get(ct, "")
                    if not prefix:
                        continue
                    scoped_xpath = f"{prefix}{xpath}"
                    scoped_locator = f"xpath={scoped_xpath}"
                    scoped_count = safe_count(page, scoped_locator)
                    if scoped_count == 1:
                        return _make_result(
                            scoped_locator,
                            f"knowledge-{elem_type}+scoped({ct})",
                            container_scoped=True, container_type=ct,
                        ), True

            # 原有逻辑：无前缀版本
            locator = f"xpath={xpath}" if not xpath.startswith("xpath=") else xpath
            count = safe_count(page, locator)

            if count == 1:
                return _make_result(locator, f"knowledge-{elem_type}"), True
            elif count > 1:
                # 匹配多个，用 ()[1] 取第一个（纯 XPath，禁止 nth=0）
                first_locator = f"xpath=({xpath})[1]"
                first_count = safe_count(page, first_locator)
                if first_count == 1:
                    return _make_result(first_locator, f"knowledge-{elem_type}+first"), True
        except Exception:
            pass

    return None, False


def probe_element(page, etype, label, key, container_types=None):
    """统一元素探测入口：知识库模板 → 硬编码策略，保证所有模板都被尝试

    调用链（所有元素类型统一走此流程）：
    1. probe_with_knowledge() — 遍历知识库所有模板（按 probe_knowledge.json 中的顺序）
    2. 知识库全部失败 → 组件类型自动检测（el-select 可能是 el-cascader）
    3. 降级到硬编码策略（probe_button / probe_el_select / probe_input 等）

    所有调用点（observe 模式、normal 模式）统一使用此函数，
    避免 fallback 逻辑分散在多处导致遗漏。

    :param container_types: 当前可见容器类型列表，如 ["dialog", "drawer"]
    :return: result_dict（包含 verified, locator, strategy 等字段）
    """
    # Step 1: 知识库模板（内部已遍历所有 patterns）
    kb_result, used_kb = probe_with_knowledge(page, etype, label, key,
                                               container_types=container_types)
    if kb_result:
        # textarea 富文本检测（知识库不含此信息，需额外检测）
        if etype == "textarea" and kb_result.get("verified"):
            rich_result = _detect_rich_text(page, label)
            if rich_result["is_rich_text"]:
                kb_result["is_rich_text_editor"] = True
                kb_result["has_iframe"] = rich_result["has_iframe"]
                kb_result["has_contenteditable"] = rich_result["has_editable"]
                if rich_result["iframe_xpath"]:
                    kb_result["iframe_xpath"] = rich_result["iframe_xpath"]
                if rich_result["has_iframe"]:
                    kb_result["recommended_keyword"] = "frame_fill_value"
                    kb_result["note"] = kb_result.get("note", "") + " [textarea 在 iframe 内（富文本编辑器），必须用 frame_fill_value]"
        return kb_result

    # Step 2: 知识库全部失败 → 二级类型检测 + 组件类型自动检测
    if etype == "el-select":
        detected_type = _detect_component_type(page, label)
        if detected_type == "el-cascader":
            etype = "el-cascader"

    # 二级子类型检测（方案 B：保持粗分类入口，内部细分路由）
    actual_type = _detect_subtype(page, etype, label, key)

    # Step 3: 降级到硬编码策略（去重后仅保留 KB 未覆盖的场景）
    if actual_type == "el-select":
        return probe_el_select(page, label, key, container_types=container_types)
    elif actual_type == "el-cascader":
        return probe_el_cascader(page, label, key, container_types=container_types)
    elif actual_type in ("button", "search-button", "download-button"):
        return probe_button(page, label, key, container_types=container_types)
    elif actual_type == "table-action-button":
        return probe_table_action_button(page, label, key, container_types=container_types)
    elif actual_type in ("input", "textarea"):
        return probe_input(page, label, key, actual_type, container_types=container_types)
    elif actual_type == "checkbox":
        return probe_checkbox(page, label, key, container_types=container_types)
    elif actual_type == "checkbox-all":
        return probe_checkbox_all(page, label, key, container_types=container_types)
    elif actual_type == "date_picker":
        return probe_date_picker(page, label, key, container_types=container_types)
    elif actual_type == "menu-item":
        return probe_menu_item(page, label, key, container_types=container_types)
    elif actual_type == "tab":
        return probe_tab(page, label, key, container_types=container_types)
    elif actual_type == "tab-scoped":
        # 从 key 命名推断元素类型
        if key.endswith('_select') or key.endswith('_cascader'):
            _inner_type = 'el-select'
        elif key.endswith('_input') or key.endswith('_textarea'):
            _inner_type = 'input'
        else:
            _inner_type = 'button'
        return probe_tab_scoped(page, label, _inner_type, label, key,
                               container_types=container_types)
    elif actual_type == "detail-link":
        result = probe_text_element(page, "a", label, key,
                                    container_types=container_types)
    else:
        result = probe_text_element(page, actual_type, label, key,
                                    container_types=container_types)

    # Step 4: count=0 KB fallback — 用 KB 第一个 pattern 作为 locator
    if result and not result.get('verified') and result.get('count', 0) == 0:
        kb_fb = _kb_fallback(etype, label, key, actual_type=actual_type)
        if kb_fb:
            return kb_fb

    return result


# ============================================================
# 二级子类型检测（方案 B）
# ============================================================

def _detect_subtype(page, etype, label, key):
    """根据 key 命名和 DOM 上下文推断更精确的子类型

    保持 --element 参数使用粗分类（button/checkbox 等），
    内部自动路由到 KB 中对应的细分类型。
    """
    if etype == 'button':
        # R6-3 修复: 确认/确定/取消 是普通对话框按钮，不路由为 table-action-button
        if label in DIALOG_CONFIRM_LABELS:
            return 'button'
        # key 命名约定
        key_lower = key.lower()
        if any(kw in key_lower for kw in ('search', 'query', 'sou')):
            return 'search-button'
        if any(kw in key_lower for kw in ('download', 'export', 'daochu')):
            return 'download-button'
        # 表格上下文检测
        if _has_table_context(page):
            return 'table-action-button'
        return 'button'

    elif etype == 'checkbox':
        key_lower = key.lower()
        if any(kw in key_lower for kw in ('all', 'batch', 'check_all', 'select_all')):
            return 'checkbox-all'
        return 'checkbox'

    elif etype in ('link', 'text'):
        key_lower = key.lower()
        if 'detail' in key_lower or 'link' in key_lower:
            return 'detail-link'
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


# Re-export from _element_types (unified type system)
from _element_types import DISCOVERY_TO_KB as _D2K
_KB_KEY_ALIAS = {raw: canon for raw, canon in _D2K.items() if raw != canon}

# Fix-2: checkbox 硬编码兜底模板（KB 无 "checkbox" 键，只有 "checkbox-all"）
# 默认勾选表格第一行的 checkbox
_CHECKBOX_HARDCODED = [
    '//div[contains(@class,"el-table__body-wrapper")]//tbody//tr[1]//*[@class="el-checkbox__inner"]'
]


def _kb_fallback(etype, label, key, actual_type=None):
    """count=0 兜底：取 KB 该类型第一个可替换的 expand pattern 作为 locator

    KB pattern 结构正确（经验证），只是当前缺数据。
    运行时前序用例创建数据后，KB 的 XPath 大概率能命中。

    Fix-1: 查找链 actual_type → etype → _KB_KEY_ALIAS[etype]，
    确保子类型（search-button 等）和别名类型（input→input-generic）都能命中。

    确认/取消按钮特殊处理：当所有探测失败时，默认加 el-dialog 前缀，
    因为 Element UI 确认对话框中的按钮通常在未弹出的 el-dialog 内。
    """
    # 确认对话框按钮：探测不到时默认假设在 el-dialog 内
    # DIALOG_CONFIRM_LABELS 从 field_suffixes.py 导入

    # Fix-1: 构建候选查找链
    candidates = []
    if actual_type and actual_type != etype:
        candidates.append(actual_type)
    candidates.append(etype)
    if etype in _KB_KEY_ALIAS:
        candidates.append(_KB_KEY_ALIAS[etype])

    patterns = []
    matched_key = None
    for kb_key in candidates:
        patterns = _get_expand_patterns(kb_key)
        if patterns:
            matched_key = kb_key
            break

    # Fix-2: checkbox 硬编码兜底（KB 无此类型）
    if not patterns and etype == 'checkbox':
        patterns = _CHECKBOX_HARDCODED
        matched_key = 'checkbox-hardcoded'

    fmt_vars = {
        'label': label,
        'tab_name': label,
        'char1': label[0] if label else "",
        'char2': label[-1] if label else "",
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


def parse_element(element_str):
    parts = element_str.split(":")
    if len(parts) < 3:
        return None
    result = {"type": parts[0], "label": parts[1], "key": parts[2]}
    # tab-scoped 需要第 4 段指定元素类型: tab-scoped:tab名:元素key:元素类型
    if parts[0] == "tab-scoped" and len(parts) >= 4:
        result["element_type"] = parts[3]  # button/input/el-select
    return result


def parse_verify(verify_str):
    """解析 --verify 参数: key=locator

    格式: "confirm_btn=xpath=//button[contains(.,'确定')]"
    返回: {"key": "confirm_btn", "locator": "xpath=//button[...]"} 或 None
    """
    eq_pos = verify_str.find('=')
    if eq_pos <= 0:
        return None
    key = verify_str[:eq_pos].strip()
    locator = verify_str[eq_pos + 1:].strip()
    if not key or not locator:
        return None
    return {"key": key, "locator": locator}


def verify_locators(page, verify_items):
    """直接验证已有 locator 是否在页面上可用（支持容器前缀自动纠错）

    :param page: Playwright page
    :param verify_items: [{"key": "...", "locator": "..."}, ...]
    :return: [{"key", "locator", "verified", "count", "strategy"}, ...]
    """
    results = []
    visible_containers_cache = None  # 延迟检测

    for item in verify_items:
        key = item["key"]
        locator = item["locator"]

        # 构建 Playwright selector
        sel = locator
        if locator.startswith('xpath='):
            sel = locator
        elif locator.startswith('//'):
            sel = f"xpath={locator}"

        error_msg = None
        result = None

        # === 第一层：原始验证 ===
        try:
            count = page.locator(sel).count()
        except Exception as e:
            count = 0
            error_msg = str(e)[:200]

        verified = False
        if count == 1:
            try:
                visible = page.locator(sel).first.is_visible()
                if not visible:
                    try:
                        page.locator(sel).first.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(500)
                        visible = page.locator(sel).first.is_visible()
                    except Exception:
                        pass
                verified = visible
            except Exception:
                verified = False

        # === 第二层：容器前缀纠错 ===
        if not verified and locator.startswith('xpath='):
            # 延迟检测可见容器
            if visible_containers_cache is None:
                visible_containers_cache = detect_visible_containers(page)

            # 检测当前 locator 的容器前缀
            xpath_part = locator[6:]  # 去掉 xpath=
            has_prefix, current_prefix_type = _detect_container_prefix(xpath_part)

            # 构建尝试列表（优先有前缀，再无前缀）
            attempts = []

            if has_prefix:
                # 有前缀：优先尝试各种前缀，最后尝试无前缀
                # 1. 尝试其他可见容器前缀
                xpath_core = _strip_container_prefix(xpath_part)
                for container_type in visible_containers_cache:
                    if container_type != current_prefix_type:
                        new_xpath = _add_container_prefix(xpath_core, container_type)
                        attempts.append((container_type, f"xpath={new_xpath}"))

                # 2. 最后尝试无前缀
                attempts.append(("no-prefix", f"xpath={xpath_core}"))
            else:
                # 无前缀：优先尝试添加前缀，最后尝试无前缀
                # 1. 尝试添加每个可见容器前缀
                for container_type in visible_containers_cache:
                    new_xpath = _add_container_prefix(xpath_part, container_type)
                    attempts.append((container_type, f"xpath={new_xpath}"))

                # 2. 最后尝试无前缀（原始）
                attempts.append(("no-prefix", sel))

            # 依次尝试
            for attempt_type, attempt_sel in attempts:
                try:
                    attempt_count = page.locator(attempt_sel).count()
                    if attempt_count == 1:
                        attempt_visible = page.locator(attempt_sel).first.is_visible()
                        if not attempt_visible:
                            try:
                                page.locator(attempt_sel).first.scroll_into_view_if_needed(timeout=3000)
                                page.wait_for_timeout(500)
                                attempt_visible = page.locator(attempt_sel).first.is_visible()
                            except Exception:
                                pass

                        if attempt_visible:
                            # 找到有效的纠正
                            locator = attempt_sel
                            sel = attempt_sel
                            count = attempt_count
                            verified = True

                            result = {
                                "key": key,
                                "locator": locator,
                                "verified": True,
                                "count": count,
                                "strategy": "direct-verify",
                            }

                            # 记录纠正信息
                            if attempt_type != "no-prefix" or has_prefix:
                                result["original_locator"] = item["locator"]
                                result["corrected_locator"] = locator
                                result["actual_container"] = attempt_type
                                print(f"  [FIX] {key:30s} -> {current_prefix_type or 'none'} → {attempt_type}")
                            break
                except Exception:
                    continue

        # === 构建结果 ===
        if not verified:
            result = {
                "key": key,
                "locator": locator,
                "verified": False,
                "count": count,
                "strategy": "direct-verify",
            }
            if error_msg:
                result["error"] = error_msg
            print(f"  [FAIL] {key:30s} -> count={count}")
        else:
            if result is None:
                result = {
                    "key": key,
                    "locator": locator,
                    "verified": True,
                    "count": count,
                    "strategy": "direct-verify",
                }
            print(f"  [OK] {key:30s} -> verified")

        results.append(result)

    return results


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


def _detect_container_prefix(xpath_expr):
    """检测 XPath 表达式中的容器前缀类型

    :param xpath_expr: XPath 表达式（不含 xpath= 前缀）
    :return: (has_prefix, prefix_type) - prefix_type 为 'drawer'/'dialog'/'message-box' 或 None
    """
    if "contains(@class,'el-drawer')" in xpath_expr:
        return True, "drawer"
    elif "contains(@class,'el-dialog')" in xpath_expr:
        return True, "dialog"
    elif "contains(@class,'el-message-box')" in xpath_expr:  # R4 新增
        return True, "message-box"
    return False, None


def _strip_container_prefix(xpath_expr):
    """剥离 XPath 表达式中的容器前缀

    :param xpath_expr: XPath 表达式（不含 xpath= 前缀）
    :return: 剥离前缀后的 XPath
    """
    # 匹配 //div[contains(@class,'el-drawer')] / el-dialog / el-message-box
    import re
    pattern = r"^//div\[contains\(@class,'el-(drawer|dialog|message-box)'\)\]"
    return re.sub(pattern, "", xpath_expr)


def _add_container_prefix(xpath_expr, container_type):
    """为 XPath 表达式添加容器前缀

    :param xpath_expr: XPath 表达式（不含 xpath= 前缀）
    :param container_type: 容器类型 'drawer'/'dialog'/'message-box'
    :return: 添加前缀后的 XPath
    """
    prefix = CONTAINER_XPATH.get(container_type, "")
    return prefix + xpath_expr


# ============================================================
# 通用辅助函数
# ============================================================

def safe_count(page, selector):
    try:
        return page.locator(selector).count()
    except Exception:
        return -1

def check_first_visible(page, selector):
    """检查定位器匹配的元素中是否至少有一个可见（含祖先链检查）

    使用 Playwright locator API 检查可见性（支持 CSS 和 xpath），
    然后用 JS 检查祖先链是否有 display:none / hidden class。

    :return: True 表示至少有一个匹配元素完全可见
    """
    try:
        loc = page.locator(selector)
        count = loc.count()
        if count == 0:
            return False
        # 检查每个匹配元素（最多检查前5个）
        for i in range(min(count, 5)):
            el = loc.nth(i)
            # Playwright 自身可见性检查
            if not el.is_visible():
                continue
            # 祖先链隐藏检查（JS）
            ancestor_hidden = el.evaluate("""(node) => {
                let n = node.parentElement;
                while (n && n !== document.body) {
                    const style = window.getComputedStyle(n);
                    if (style.display === 'none') return true;
                    if (style.visibility === 'hidden') return true;
                    const cls = (n.className || '').toString().toLowerCase();
                    if (cls.split(/\\s+/).includes('is-hidden')) return true;
                    if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return true;
                    n = n.parentElement;
                }
                return false;
            }""")
            if not ancestor_hidden:
                return True
        return False
    except Exception:
        return False


def pick_best(attempts):
    """选择最佳定位器：verified(count==1) > partial(count>0) > not found(0)"""
    for a in attempts:
        if a.get("verified"):
            return a
    # 退而求其次：count > 0 且 visible 的（R7-1 修复: descending 取 count 最大的）
    for a in sorted(attempts, key=lambda x: x.get("count", 0), reverse=True):
        if a.get("count", 0) > 0 and a.get("visible", True):
            return a
    return attempts[0] if attempts else None


# ============================================================
# 组件类型自动检测（el-select vs el-cascader）
# ============================================================

def _detect_component_type(page, label):
    """检测表单控件的实际组件类型

    通过 JS 向上遍历 DOM 树，查找 input 最近的 .el-select 或 .el-cascader 祖先。
    返回: "el-select" | "el-cascader" | "unknown"
    """
    try:
        return page.evaluate("""(label) => {
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                if (el.children.length === 0 && el.textContent.trim() === label) {
                    const sibling = el.nextElementSibling;
                    if (!sibling) continue;
                    const input = sibling.querySelector('input.el-input__inner');
                    if (!input) continue;
                    let parent = input.parentElement;
                    while (parent && parent !== document.body) {
                        if (parent.classList.contains('el-cascader')) return 'el-cascader';
                        if (parent.classList.contains('el-select')) return 'el-select';
                        parent = parent.parentElement;
                    }
                }
            }
            return 'unknown';
        }""", label)
    except Exception:
        return "unknown"


# ============================================================
# el-select 探测（问题 A 增强）
# ============================================================

def probe_el_select(page, label, key, container_types=None):
    """探测 el-select 元素 — 去重后仅保留后处理逻辑

    KB 已覆盖：following-sibling input locator（含容器前缀）。
    L2 仅补充后处理：readonly 检测、选项收集、子串冲突检测、two_step 操作。
    如果 L2 也未找到 locator，dispatch 层会用 KB fallback 提供默认 locator。
    """
    attempts = []

    # 唯一保留策略：following-sibling input（与 KB 相同，作为 L2 最后尝试）
    sel = f"xpath=//*[{_contains_text(label)}]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
    c = safe_count(page, sel)
    if c == 1:
        attempts.append({"locator": sel, "verified": True, "count": c, "strategy": "xpath-input-sibling"})
    elif c > 1:
        inner = sel.replace('xpath=', '', 1)
        attempts.append({"locator": f"xpath=({inner})[1]", "verified": True, "count": 1, "strategy": "xpath-input-sibling+first"})

    best = pick_best(attempts)

    # 检测 input 是否 readonly（不可搜索的 el-select → 两步法）
    is_readonly = False
    if best and best.get("count", 0) >= 1:
        try:
            is_readonly = page.evaluate("""(selector) => {
                const xpath = selector.replace('xpath=', '');
                const result = document.evaluate(
                    xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                );
                const input = result.singleNodeValue;
                return input ? (input.hasAttribute('readonly') || input.readOnly === true) : false;
            }""", best["locator"])
        except Exception:
            pass

    # 展开下拉框采集选项
    options = []
    needs_exact = False
    conflicts = []
    two_step = None

    if best and best.get("count", 0) >= 1:
        try:
            page.locator(best["locator"]).first.click()
            page.wait_for_timeout(800)

            # 采集所有可见下拉面板的选项（R7-5 修复: CSS → XPath）
            _opt_xpath = ("xpath=//div[contains(@class,'el-select-dropdown')"
                          " and not(contains(@style,'display: none'))]"
                          "//li[contains(@class,'el-select-dropdown__item')]")
            options = [t.strip() for t in page.locator(_opt_xpath).all_text_contents() if t.strip()]

            # 检测子串冲突（用 JS 精确检查）
            conflict_result = page.evaluate("""(opts) => {
                const conflicts = {};
                for (let i = 0; i < opts.length; i++) {
                    for (let j = 0; j < opts.length; j++) {
                        if (i !== j && opts[j].includes(opts[i]) && opts[i] !== opts[j]) {
                            if (!conflicts[opts[i]]) conflicts[opts[i]] = [];
                            conflicts[opts[i]].push(opts[j]);
                        }
                    }
                }
                return conflicts;
            }""", options)

            conflicts = conflict_result  # dict: {option_text: [conflicting_options]}
            needs_exact = len(conflicts) > 0

            # 关闭下拉
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:
            pass

    # 为有冲突的选项生成两步操作信息
    if needs_exact and best:
        two_step = {
            "step1_expand": {
                "keyword": "click_element",
                "locator": best["locator"],
                "desc": f"点击{label}下拉框展开选项"
            },
            "step2_select_pattern": {
                "keyword": "execute_script",
                "script_pattern": "var ds=document.querySelectorAll('.el-select-dropdown');for(var d=0;d<ds.length;d++){if(ds[d].offsetHeight>0){var items=ds[d].querySelectorAll('.el-select-dropdown__item');for(var i=0;i<items.length;i++){if(items[i].textContent.trim()==='选项值'){items[i].click();break}}break}}",
                "desc": "用JS遍历所有下拉面板，在可见面板中精确匹配选项文本并点击"
            },
            "conflicting_options": conflicts,
            "note": "必须使用 execute_script（JS点击），不要用 CSS 选择器：:visible 对 Element UI 下拉面板无效，text-is 对长文本不稳定",
        }

    return {
        "key": key, "type": "el-select", "label": label,
        "locator": best["locator"] if best else "",
        "verified": best.get("verified", False) if best else False,
        "count": best.get("count", 0) if best else 0,
        "strategy": best.get("strategy", "") if best else "",
        "select_options": options[:20],  # 只保留前20个
        "select_options_total": len(options),
        "needs_exact_match": needs_exact,
        "option_conflicts": conflicts,
        "two_step": two_step,
        "readonly": is_readonly,
    }


# ============================================================
# el-cascader 级联选择器探测
# ============================================================

def probe_el_cascader(page, label, key, container_types=None):
    """探测级联选择器元素

    级联选择器操作法（多步）：
    1. click input 展开级联面板
    2. 逐级勾选/展开选项（每级两种 pattern）：
       - 勾选：//li[@role='menuitem' and contains(.,'{text}')]//span[@class='el-checkbox__inner']
       - 展开：//li[@role='menuitem']//span[contains(text(),'{text}')]
    """
    attempts = []

    # ★ 容器作用域策略优先（当 container_types 非空时）
    if container_types:
        for ct in sorted(container_types, key=lambda c: CONTAINER_PRIORITY.get(c, 99)):
            prefix = CONTAINER_XPATH.get(ct, "")
            if not prefix:
                continue
            sel = f"xpath={prefix}//*[{_contains_text(label)}]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
            c = safe_count(page, sel)
            if c == 1:
                attempts.append({"locator": sel, "verified": True, "count": c,
                                 "strategy": f"xpath-cascader-scoped({ct})",
                                 "container_scoped": True, "container_type": ct})

    # 策略 1：following-sibling → input
    sel = f"xpath=//*[{_contains_text(label)}]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
    c = safe_count(page, sel)
    if c == 1:
        attempts.append({"locator": sel, "verified": True, "count": c, "strategy": "cascader-xpath-input"})
    elif c > 1:
        inner = sel.replace('xpath=', '', 1)
        attempts.append({"locator": f"xpath=({inner})[1]", "verified": True, "count": 1, "strategy": "cascader-xpath-input+first"})

    # 策略 2：作用域限定（drawer/dialog/message-box）— 复用共享常量
    for prefix_xpath in CONTAINER_XPATH.values():
        sel2 = f"xpath={prefix_xpath}//*[{_contains_text(label)}]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
        c2 = safe_count(page, sel2)
        if c2 == 1:
            attempts.append({"locator": sel2, "verified": True, "count": c2, "strategy": "cascader-scoped"})
            break
        elif c2 > 1:
            inner2 = sel2.replace('xpath=', '', 1)
            attempts.append({"locator": f"xpath=({inner2})[1]", "verified": True, "count": 1, "strategy": "cascader-scoped+first"})
            break

    best = pick_best(attempts)
    if best:
        best.update({
            "key": key, "type": "el-cascader", "label": label,
            "recommended_operation": "cascader",
            "operation_steps": [
                {
                    "step": "expand-panel",
                    "keyword": "click_element",
                    "desc": "点击展开级联面板"
                },
                {
                    "step": "select-level",
                    "keyword": "click_element",
                    "patterns": [
                        "//li[@role='menuitem' and contains(.,'{option_text}')]//span[@class='el-checkbox__inner']",
                        "//li[@role='menuitem']//span[contains(text(),'{option_text}')]"
                    ],
                    "desc": "逐级勾选/展开（每级用 option_text 替换实际值，可重复多步）"
                }
            ],
            "note": "级联选择器：click input → 逐级 click 选项，禁止 fill_value"
        })

        # 选项收集 + 级数检测 + checkbox 检测
        if best.get("verified"):
            try:
                page.locator(best["locator"]).first.click()
                page.wait_for_timeout(1000)

                # 收集第一级选项
                items = page.locator("li[role='menuitem'] span").all_text_contents()
                best['cascader_options_level1'] = [t.strip() for t in items if t.strip()][:20]

                # 检测级数：点击第一项看是否有第二级
                if best['cascader_options_level1']:
                    page.locator("li[role='menuitem'] span").first.click()
                    page.wait_for_timeout(500)
                    level2 = page.locator("li[role='menuitem'] span").all_text_contents()
                    if level2 and set(level2) != set(best['cascader_options_level1']):
                        best['detected_levels'] = 2
                        best['cascader_options_level2'] = [t.strip() for t in level2 if t.strip()][:20]
                    else:
                        best['detected_levels'] = 1

                # 检测是否有 checkbox
                checkbox_count = page.locator("li[role='menuitem'] span.el-checkbox__inner").count()
                best['has_checkbox'] = checkbox_count > 0

            except Exception as e:
                best['option_collection_error'] = str(e)
            finally:
                try:
                    page.keyboard.press('Escape')
                except Exception:
                    pass

        return best

    return {"key": key, "type": "el-cascader", "label": label, "verified": False, "count": 0}


# ============================================================
# menu-item 侧边菜单探测
# ============================================================

def probe_menu_item(page, label, key, container_types=None):
    """探测侧边菜单项 — 去重后仅保留 KB 未覆盖的 submenu-child

    KB 已覆盖：el-menu-item class 匹配。
    L2 仅补充：el-submenu 嵌套子菜单场景。
    """
    attempts = []

    # Strategy: el-submenu 子项（KB 未覆盖的二级菜单场景）
    xpath2 = f"xpath=//li[contains(@class,'el-submenu')]//li[{_contains_dot(label)}]"
    c2 = safe_count(page, xpath2)
    if c2 >= 1:
        is_vis = check_first_visible(page, xpath2)
        if is_vis:
            final2 = f"xpath=({xpath2.replace('xpath=', '')})[1]" if c2 > 1 else xpath2
            attempts.append({"locator": final2, "verified": c2 == 1, "count": c2,
                             "strategy": "submenu-child"})

    best = pick_best(attempts)
    if best:
        best.update({"key": key, "type": "menu-item", "label": label})
        return best
    return {"key": key, "type": "menu-item", "label": label, "verified": False, "count": 0}


# ============================================================
# tab 探测
# ============================================================

def probe_tab(page, label, key, container_types=None):
    """探测 Tab 元素 — 去重后仅保留 KB 未覆盖的 el-tabs__item class 回退

    KB 已覆盖：@role='tab' + 文本匹配。
    L2 仅补充：@role='tab' 缺失时用 el-tabs__item class 匹配。
    """
    attempts = []

    # Strategy: el-tabs__item class（@role='tab' 缺失时的回退）
    xpath2 = f"xpath=//*[contains(@class,'el-tabs__item') and {_contains_dot(label)}]"
    c2 = safe_count(page, xpath2)
    if c2 >= 1:
        is_vis = check_first_visible(page, xpath2)
        if is_vis:
            final2 = f"xpath=({xpath2.replace('xpath=', '')})[1]" if c2 > 1 else xpath2
            attempts.append({"locator": final2, "verified": c2 == 1, "count": c2,
                             "strategy": "tabs-item-class"})

    best = pick_best(attempts)

    # 探测 aria-controls 属性（用于 tab-scoped 模式）
    if best and best.get("verified"):
        try:
            aria = page.locator(best["locator"]).first.get_attribute('aria-controls')
            if aria:
                best['aria_controls'] = aria
                best['tab_scoped'] = True
        except Exception:
            pass

    if best:
        best.update({"key": key, "type": "tab", "label": label})
        return best
    return {"key": key, "type": "tab", "label": label, "verified": False, "count": 0}


# ============================================================
# button 探测（问题 B 增强：表格重试）
# ============================================================

def probe_button(page, text, key, container_types=None):
    """探测按钮 — 去重后仅保留 KB 未覆盖的策略

    KB 已覆盖：全文匹配、拆字匹配、通配标签匹配、容器前缀。
    L2 仅补充：
    - dialog-last-scope: 多 dialog 叠放取 [last()]
    - normalize-space: 精确文本匹配（KB 的 contains 太宽泛时兜底）
    """
    attempts = []

    # 策略 1：dialog 叠放 — (//div[contains(@class,'el-dialog')])[last()] 取最顶层
    # R6-1 修复: @role='dialog' → contains(@class,'el-dialog')，与容器前缀系统一致
    try:
        has_dialog = page.evaluate("""() => {
            return document.querySelectorAll('.el-dialog').length > 0;
        }""")
        if has_dialog:
            chars = [c for c in text.strip() if c.strip()]
            if chars:
                conditions = " and ".join([_contains_dot(c) for c in chars])
            else:
                conditions = _contains_dot(text)
            dialog_sel = f"xpath=(//div[contains(@class,'el-dialog')])[last()]//button[{conditions}]"
            c_dialog = safe_count(page, dialog_sel)
            if c_dialog >= 1:
                is_vis = check_first_visible(page, dialog_sel)
                if is_vis:
                    attempts.append({
                        "locator": dialog_sel, "verified": True, "count": 1,
                        "strategy": "dialog-last-scope",
                    })
    except Exception:
        pass

    # 策略 2：normalize-space 精确匹配（覆盖按钮文本含特殊空白的场景）
    # H3 修复: 用 _xpath_escape_label 处理单引号
    _ns_label = _xpath_escape_label(text)
    if _ns_label == text:
        _ns_expr = f"'{text}'"
    else:
        _ns_expr = _ns_label
    ns_sel = f"xpath=//button[normalize-space(.)={_ns_expr}]"
    c_ns = safe_count(page, ns_sel)
    if c_ns >= 1:
        is_vis = check_first_visible(page, ns_sel)
        if is_vis:
            final_ns = f"xpath=(//button[normalize-space(.)={_ns_expr}])[1]" if c_ns > 1 else ns_sel
            attempts.append({
                "locator": final_ns, "verified": c_ns == 1, "count": c_ns,
                "strategy": "normalize-space",
            })

    best = pick_best(attempts)

    pitfalls = []
    if best and best.get("count", 0) > 1:
        pitfalls.append(f"找到 {best['count']} 个匹配按钮")

    result = {
        "key": key, "type": "button", "label": text,
        "locator": best["locator"] if best else "",
        "verified": best.get("verified", False) if best else False,
        "count": best.get("count", 0) if best else 0,
        "strategy": best.get("strategy", "") if best else "",
        "is_table_pattern": False,
        "pitfalls": pitfalls,
    }
    return result


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


def probe_input(page, label, key, tag="input", container_types=None):
    """探测输入框 — 去重后仅保留 KB 未覆盖的策略

    KB 已覆盖：following-sibling::div/span input（含容器前缀）。
    L2 仅补充：
    - xpath-span-sibling: label 后是 span 的布局
    - placeholder: 通过 placeholder 属性匹配（转 XPath）
    - rich-text: textarea 富文本编辑器检测（后处理）
    """
    attempts = []
    css_tag = "textarea" if tag == "textarea" else "input[contains(@class,'el-input__inner')]"

    # ⚠️ 检查 textarea 是否被富文本编辑器（TinyMCE/UEditor 等）替换
    is_rich_text = False
    rich_has_iframe = False
    rich_has_editable = False
    rich_iframe_xpath = None
    if tag == "textarea":
        rich_result = _detect_rich_text(page, label)
        if rich_result["is_rich_text"]:
            is_rich_text = True
            rich_has_iframe = rich_result["has_iframe"]
            rich_has_editable = rich_result["has_editable"]
            rich_iframe_xpath = rich_result["iframe_xpath"]
            reason = rich_result["reason"]
            # contenteditable 定位器（转 XPath）
            editable_xpath = (f"xpath=//div[contains(@class,'el-form-item')]"
                              f"[.//*[contains(@class,'el-form-item__label') and {_contains_dot(label)}]]"
                              f"//*[@contenteditable='true']")
            c = safe_count(page, editable_xpath)
            if c >= 1:
                attempts.append({
                    "locator": editable_xpath, "verified": c == 1, "count": c,
                    "strategy": "rich-text-contenteditable",
                    "note": f"textarea 被富文本编辑器替换({reason})，改用 contenteditable 区域"
                })

    # 如果不是富文本编辑器，正常探测
    if not is_rich_text:
        # 策略 1：xpath-span-sibling（KB 只有 following-sibling::div/span，span 是补充）
        sel2 = f"xpath=//*[{_contains_text(label)}]/following-sibling::span//{css_tag}"
        c2 = safe_count(page, sel2)
        if c2 == 1:
            attempts.append({"locator": sel2, "verified": True, "count": c2, "strategy": "xpath-span-sibling"})
        elif c2 > 1:
            base2 = sel2.replace('xpath=', '')
            attempts.append({"locator": f"xpath=({base2})[1]", "verified": True, "count": 1, "strategy": "xpath-span-sibling+nth"})

        # 策略 2：placeholder 属性匹配（原 CSS 转 XPath）
        ph_tag = "textarea" if tag == "textarea" else "*[contains(@class,'el-input__inner')]"
        _ph_label = _xpath_escape_label(label)
        _ph_expr = f"'{label}'" if _ph_label == label else _ph_label
        sel5 = f"xpath=//{ph_tag}[contains(@placeholder,{_ph_expr})]"
        c5 = safe_count(page, sel5)
        if c5 == 1:
            attempts.append({"locator": sel5, "verified": True, "count": c5, "strategy": "placeholder"})

    best = pick_best(attempts)
    result = {
        "key": key, "type": tag, "label": label,
        "locator": best["locator"] if best else "",
        "verified": best.get("verified", False) if best else False,
        "count": best.get("count", 0) if best else 0,
        "strategy": best.get("strategy", "") if best else "",
    }
    if is_rich_text:
        result["is_rich_text_editor"] = True
        result["has_iframe"] = rich_has_iframe
        result["has_contenteditable"] = rich_has_editable
        if rich_iframe_xpath:
            result["iframe_xpath"] = rich_iframe_xpath
        if rich_has_iframe:
            # 有 iframe（TinyMCE/UEditor iframe 模式）→ 必须用 frame_fill_value
            result["recommended_keyword"] = "frame_fill_value"
            if not result.get("note"):
                result["note"] = "textarea 在 iframe 内（富文本编辑器），必须用 frame_fill_value"
        elif rich_has_editable:
            # 无 iframe 但有 contenteditable → 用 fill_value + contenteditable 定位器
            result["recommended_keyword"] = "fill_value"
            if not result.get("note"):
                result["note"] = "textarea 被 contenteditable 元素替换（无 iframe），用 fill_value + contenteditable 定位器"
        else:
            # textarea 被隐藏但无 iframe 也无 contenteditable → 降级用 execute_script
            result["recommended_keyword"] = "execute_script"
            if not result.get("note"):
                result["note"] = "textarea 被隐藏(aria-hidden)但无 iframe/contenteditable，需降级用 execute_script"
    if best and best.get("note"):
        result["note"] = best["note"]
    return result


# ============================================================
# checkbox 探测（问题 B 增强）
# ============================================================

def probe_checkbox(page, label, key, container_types=None):
    """探测复选框 — 去重后仅保留 XPath 格式

    KB 已覆盖：单 checkbox 的 el-checkbox class 匹配。
    L2 仅补充：XPath 格式的 checkbox 定位器（KB 匹配失败时兜底）。
    """
    attempts = []

    # XPath checkbox 定位器（替代原 CSS .el-checkbox:has-text）
    sel = f"xpath=//label[contains(@class,'el-checkbox') and {_contains_dot(label)}]"
    c = safe_count(page, sel)
    if c == 1:
        is_vis = check_first_visible(page, sel)
        if is_vis:
            attempts.append({"locator": sel, "verified": True, "count": c, "strategy": "checkbox-xpath"})

    best = pick_best(attempts)

    result = {
        "key": key, "type": "checkbox", "label": label,
        "locator": best["locator"] if best else "",
        "verified": best.get("verified", False) if best else False,
        "count": best.get("count", 0) if best else 0,
        "strategy": best.get("strategy", "") if best else "",
    }
    if best and best.get("note"):
        result["note"] = best["note"]
    return result


# ============================================================
# 问题 D：操作后观察模式
# ============================================================

def observe_after_action(page, action_str):
    """执行操作后观察页面变化

    :param action_str: 操作描述，如 "click:button:has-text('新增')"
    :return: 观察结果
    """
    # 记录操作前状态
    before = _snapshot_page_state(page)

    # 执行操作
    action_type, action_selector, _extra = _parse_action(action_str)
    # 解析知识库类型前缀（如 tab:任务提醒 → XPath）
    action_selector = _resolve_action_selector(page, action_selector)
    click_success = False
    if action_type == "click":
        try:
            page.locator(action_selector).first.click()
            click_success = True
        except Exception as e:
            return {"error": f"点击失败: {e}", "action": action_str}

    page.wait_for_timeout(2000)

    # 记录操作后状态
    after = _snapshot_page_state(page)

    # 比较差异
    changes = _compare_states(before, after)

    result = {
        "action": action_str,
        "click_success": click_success,
        "changes": changes,
        "after_state": after,
    }

    # 如果抽屉打开了，探测抽屉内的元素
    if changes.get("drawer_opened"):
        drawer_elements = _probe_drawer_elements(page)
        result["drawer_elements"] = drawer_elements

    return result


def _snapshot_page_state(page):
    """记录页面当前状态"""
    state = {
        "url": page.url,
        "has_drawer": False,
        "has_dialog": False,
        "has_message_box": False,  # R7-2 修复: 新增 message-box 检测
        "visible_drawer_count": 0,
        "visible_dialog_count": 0,
    }
    try:
        state["has_drawer"] = page.evaluate("""() => {
            const drawers = document.querySelectorAll('.el-drawer');
            return Array.from(drawers).some(d => d.offsetHeight > 0 && d.style.display !== 'none');
        }""")
        state["visible_drawer_count"] = page.evaluate("""() => {
            const drawers = document.querySelectorAll('.el-drawer');
            return Array.from(drawers).filter(d => d.offsetHeight > 0 && d.style.display !== 'none').length;
        }""")
    except Exception:
        pass
    try:
        state["has_dialog"] = page.evaluate("""() => {
            const dialogs = document.querySelectorAll('.el-dialog__wrapper');
            return Array.from(dialogs).some(d => d.style.display !== 'none');
        }""")
    except Exception:
        pass
    # R7-2 修复: 检测 message-box
    try:
        state["has_message_box"] = page.evaluate("""() => {
            const boxes = document.querySelectorAll('.el-message-box');
            return Array.from(boxes).some(b => b.offsetHeight > 0 && b.style.display !== 'none');
        }""")
    except Exception:
        pass
    return state


def _compare_states(before, after):
    """比较两个状态的差异"""
    changes = {}
    if not before.get("has_drawer") and after.get("has_drawer"):
        changes["drawer_opened"] = True
    if not before.get("has_dialog") and after.get("has_dialog"):
        changes["dialog_opened"] = True
    # R7-2 修复: 检测 message-box 弹出
    if not before.get("has_message_box") and after.get("has_message_box"):
        changes["message_box_opened"] = True
    if before.get("url") != after.get("url"):
        changes["url_changed"] = {"from": before["url"], "to": after["url"]}
    return changes


def probe_text_element(page, tag, text, key, container_types=None):
    """通用文本元素探测 — 去重后仅保留 KB 未覆盖的 contains(text()) 变体

    KB 已覆盖：tag + contains(.,'text')、不限 tag 的 contains(.,'text')、容器前缀。
    L2 仅补充：
    - contains(text(),'text')：只匹配直接子文本节点（KB 的 contains(.,) 匹配所有后代）
    """
    attempts = []

    # Strategy: tag + contains(text(),'text')（KB 未覆盖的直接文本匹配）
    _ct_expr = _contains_text(text)
    sel2 = f"xpath=//{tag}[{_ct_expr}]"
    c2 = safe_count(page, sel2)
    if c2 >= 1:
        is_vis = check_first_visible(page, sel2)
        if is_vis:
            final = f"xpath=(//{tag}[{_ct_expr}])[1]" if c2 > 1 else sel2
            attempts.append({
                "locator": final, "verified": c2 == 1, "count": c2,
                "strategy": f"{tag}-contains-text",
            })

    best = pick_best(attempts)

    pitfalls = []
    if best and best.get("count", 0) > 1:
        pitfalls.append(f"找到 {best['count']} 个匹配元素，建议用 XPath [1] 限定")

    result = {
        "key": key, "type": tag, "label": text,
        "locator": best["locator"] if best else "",
        "verified": best.get("verified", False) if best else False,
        "count": best.get("count", 0) if best else 0,
        "strategy": best.get("strategy", "") if best else "",
        "pitfalls": pitfalls,
    }
    if best and best.get("note"):
        result["note"] = best["note"]
    return result


def _resolve_action_selector(page, action_selector):
    """解析 action 中的选择器，支持知识库类型前缀（如 tab:任务提醒 → XPath）

    如果 action_selector 是 "type:label" 格式（如 "tab:任务提醒"），
    则通过知识库解析为实际 XPath；否则原样返回。

    :return: Playwright 可用的 locator 字符串
    """
    if not action_selector or ':' not in action_selector:
        return action_selector
    # 检查是否是知识库类型前缀（不以 xpath=、//、. 开头）
    if action_selector.startswith(('xpath=', '//', '.', '#', '[')):
        return action_selector
    parts = action_selector.split(':', 1)
    if len(parts) == 2:
        elem_type, label = parts
        # 尝试通过知识库解析
        result, used = probe_with_knowledge(page, elem_type, label, '_action_tmp')
        if result and result.get('locator'):
            return result['locator']
    # 无法解析，原样返回
    return action_selector


def _parse_action(action_str):
    """解析操作字符串，返回 (type, selector, extra)

    支持格式：
    - click:selector          — 点击元素
    - wait:ms                 — 强制等待
    - fill:selector:value     — 填写输入框
    """
    if action_str.startswith("click:"):
        return "click", action_str[6:], None
    elif action_str.startswith("wait:"):
        try:
            ms = int(action_str[5:])
        except ValueError:
            ms = 1000
        return "wait", str(ms), None
    elif action_str.startswith("fill:"):
        # 从右侧分割：最后一个 : 后面是 value，前面是 selector
        # 避免 XPath 中的 :: (如 following-sibling::) 被误切
        rest = action_str[5:]  # 去掉 "fill:" 前缀
        colon_idx = rest.rfind(":")
        if colon_idx > 0:
            return "fill", rest[:colon_idx], rest[colon_idx + 1:]
        return "unknown", action_str, None
    return "unknown", action_str, None


def _probe_drawer_elements(page):
    """探测抽屉内可见的表单元素"""
    elements = []
    try:
        # 等待抽屉内容渲染完成
        page.wait_for_timeout(1000)
        labels = page.evaluate("""() => {
            // 查找所有可能的抽屉容器
            const selectors = [
                '.el-drawer__body',
                '.el-drawer',
                '.el-drawer__wrapper .el-drawer'
            ];
            for (const sel of selectors) {
                const containers = document.querySelectorAll(sel);
                for (const container of containers) {
                    // 跳过隐藏的
                    if (container.offsetParent === null && container.style.display === 'none') continue;
                    // 查找表单标签
                    const items = container.querySelectorAll('.el-form-item__label');
                    if (items.length > 0) {
                        return Array.from(items).map(l => (l.textContent || '').trim()).filter(t => t);
                    }
                    // 如果没有 form-item，尝试找所有文本元素
                    const allText = container.querySelectorAll('label, .label, th, dt');
                    if (allText.length > 0) {
                        return Array.from(allText).map(l => (l.textContent || '').trim()).filter(t => t);
                    }
                }
            }
            return [];
        }""")
        elements = labels
    except Exception as e:
        elements = [f"探测出错: {e}"]
    return elements


# ============================================================
# date_picker 探测（规则28）
# ============================================================

def probe_date_picker(page, label, key, container_types=None):
    """探测日期选择器，检测面板类型 + x-placement 方向 + today/now 单元格定位"""
    attempts = []

    # ★ 容器作用域策略优先（当 container_types 非空时）
    if container_types:
        for ct in sorted(container_types, key=lambda c: CONTAINER_PRIORITY.get(c, 99)):
            prefix = CONTAINER_XPATH.get(ct, "")
            if not prefix:
                continue
            input_ct = f"xpath={prefix}//*[{_contains_text(label)}]/following-sibling::div//input[@class='el-input__inner']"
            c_ct = safe_count(page, input_ct)
            if c_ct == 0:
                input_ct = f"xpath={prefix}//*[{_contains_text(label)}]/following-sibling::span//input[@class='el-input__inner']"
                c_ct = safe_count(page, input_ct)
            if c_ct == 1:
                attempts.append({"locator": input_ct, "verified": True, "count": c_ct,
                                 "strategy": f"date-picker-input-{ct}",
                                 "container_scoped": True, "container_type": ct})

    # 先点击日期输入框打开面板（含隐藏过滤）
    input_sel = f"xpath=//*[{_contains_text(label)}]/following-sibling::div//input[@class='el-input__inner']"
    c = safe_count(page, input_sel)
    if c == 0:
        input_sel = f"xpath=//*[{_contains_text(label)}]/following-sibling::span//input[@class='el-input__inner']"
        c = safe_count(page, input_sel)
    if c == 0:
        input_sel = f"xpath=//*[{_contains_text(label)}]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']"
        c = safe_count(page, input_sel)

    if c >= 1:
        try:
            page.locator(input_sel).first.click()
            page.wait_for_timeout(1000)
        except Exception:
            pass

    # 检测面板类型
    date_type = 'date'
    has_today = False
    has_now = False
    try:
        # R5 修复: CSS → XPath（规则一致性）
        has_now = safe_count(page, "xpath=//button[contains(.,'此刻')]") > 0
        has_today = safe_count(page, "xpath=//td[contains(@class,'today')]") > 0
        has_month = safe_count(page, "xpath=//table[contains(@class,'el-month-table')]") > 0
        has_range = safe_count(page, "xpath=//div[contains(@class,'el-date-range-picker')]") > 0
        date_type = (
            'datetime-range' if has_range and has_now else
            'date-range' if has_range else
            'datetime' if has_now else
            'month' if has_month else
            'date'
        )
    except Exception:
        pass

    # 检测 x-placement
    x_placement = None
    try:
        x_placement = page.evaluate("""() => {
            const panels = document.querySelectorAll('.el-picker-panel');
            for (const p of panels) {
                const wrapper = p.closest('[x-placement]');
                if (wrapper) return wrapper.getAttribute('x-placement');
                const popper = p.closest('.el-popper');
                if (popper) return popper.getAttribute('x-placement');
            }
            const visiblePanels = document.querySelectorAll('.el-date-picker');
            for (const dp of visiblePanels) {
                const popper = dp.closest('[x-placement]');
                if (popper && popper.getBoundingClientRect().width > 0) {
                    return popper.getAttribute('x-placement');
                }
            }
            return null;
        }""")
    except Exception:
        pass

    # 检查 today 单元格是否存在
    for placement in [x_placement, "top-start", "bottom-start"]:
        if not placement:
            continue
        today_sel = f"xpath=//div[@x-placement='{placement}']//table[not(contains(@style,'display: none'))]//td[contains(@class,'today')]"
        c_today = safe_count(page, today_sel)
        if c_today >= 1:
            attempts.append({
                "locator": today_sel,
                "verified": True,
                "count": c_today,
                "strategy": f"date-picker-{placement}",
                "note": f"日期选择器 x-placement={placement}, type={date_type}"
            })
            break

    # 检测 now 按钮（此刻）
    if has_now:
        now_sel = "xpath=//button[contains(.,'此刻')]"
        c_now = safe_count(page, now_sel)
        if c_now >= 1:
            attempts.append({
                "locator": now_sel,
                "verified": True,
                "count": c_now,
                "strategy": "date-picker-now",
                "note": "datetime 类型，存在'此刻'按钮"
            })

    best = pick_best(attempts)
    result = {
        "key": key, "type": "date_picker", "label": label,
        "locator": best["locator"] if best else "",
        "verified": best.get("verified", False) if best else False,
        "count": best.get("count", 0) if best else 0,
        "strategy": best.get("strategy", "") if best else "",
        "x_placement": x_placement,
        "date_type": date_type,
        "has_today": has_today,
        "has_now": has_now,
    }
    if best and best.get("note"):
        result["note"] = best["note"]
    if not x_placement:
        result["note"] = result.get("note", "") + " [WARNING: 未能检测 x-placement，需手动确认]"

    # 关闭面板
    try:
        page.keyboard.press('Escape')
    except Exception:
        pass

    return result


# ============================================================
# checkbox-all 表头全选复选框探测
# ============================================================

def probe_checkbox_all(page, label, key, container_types=None):
    """探测表头全选复选框"""
    attempts = []

    # Strategy 1: KB 标准模式（优先）
    xpath = "xpath=//div[@class='el-table__header-wrapper']//span[@class='el-checkbox__inner']"
    c = safe_count(page, xpath)
    if c >= 1:
        is_vis = check_first_visible(page, xpath)
        if is_vis:
            attempts.append({"locator": xpath, "verified": c == 1, "count": c,
                             "strategy": "kb-header-wrapper"})

    # Strategy 2: th 表头中的 el-checkbox
    # M9: 使用 /span 而非 //span，限定为 label 的直接子元素，避免非 el-checkbox label 误匹配
    xpath2 = (f"xpath=//th//label[contains(@class,'el-checkbox')"
             f"]"
             f"/span[@class='el-checkbox__inner']")
    c2 = safe_count(page, xpath2)
    if c2 >= 1:
        is_vis = check_first_visible(page, xpath2)
        if is_vis:
            attempts.append({"locator": xpath2, "verified": c2 == 1, "count": c2,
                             "strategy": "th-checkbox"})

    # Strategy 3: el-table__header-wrapper 作用域
    xpath3 = (f"xpath=//div[@class='el-table__header-wrapper']"
              f"//th[1]//span[@class='el-checkbox__inner'"
              f"]")
    c3 = safe_count(page, xpath3)
    if c3 >= 1:
        is_vis = check_first_visible(page, xpath3)
        if is_vis:
            attempts.append({"locator": xpath3, "verified": c3 == 1, "count": c3,
                             "strategy": "table-header-first-th"})

    best = pick_best(attempts)
    if best:
        best.update({"key": key, "type": "checkbox-all", "label": label})
        return best
    return {"key": key, "type": "checkbox-all", "label": label, "verified": False, "count": 0}


# ============================================================
# table-action-button 表格操作列按钮探测
# ============================================================

def probe_table_action_button(page, label, key, container_types=None):
    """探测表格操作列按钮（编辑/删除/详情等）"""
    attempts = []

    table_containers = [
        ("el-table__fixed-right", 'fixed-right'),
        ("el-table__body-wrapper", 'body-wrapper'),
        ("el-table__fixed-body-wrapper", 'fixed-body'),
    ]

    for cls, strategy_name in table_containers:
        xpath = (f"xpath=//div[contains(@class,'{cls}')]"
                 f"//tbody/tr[1]//span[{_contains_dot(label)}"
                 f"]")
        c = safe_count(page, xpath)
        if c >= 1:
            is_vis = check_first_visible(page, xpath)
            if is_vis:
                attempts.append({"locator": xpath, "verified": c == 1, "count": c,
                                 "strategy": f"table-{strategy_name}"})
                break

    # tabpanel 内的表格
    xpath_tp = (f"xpath=//div[@role='tabpanel' and not(contains(@style,'display: none'))]"
                f"//div[contains(@class,'el-table__fixed-right')]"
                f"//tbody/tr[1]//span[{_contains_dot(label)}"
                f"]")
    c_tp = safe_count(page, xpath_tp)
    if c_tp >= 1:
        is_vis = check_first_visible(page, xpath_tp)
        if is_vis:
            attempts.append({"locator": xpath_tp, "verified": c_tp == 1, "count": c_tp,
                             "strategy": "tabpanel-table"})

    best = pick_best(attempts)
    if best:
        best.update({"key": key, "type": "table-action-button", "label": label})
        return best
    return {"key": key, "type": "table-action-button", "label": label, "verified": False, "count": 0}


# ============================================================
# dropdown-menu 下拉菜单探测
# ============================================================

def probe_dropdown_menu(page, label, key, container_types=None):
    """探测'更多'下拉菜单中的菜单项"""
    attempts = []

    # 先点击"更多"按钮展开菜单
    more_xpaths = [
        "xpath=//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//span[contains(.,'更多')]",
        "xpath=//div[contains(@class,'el-table__body-wrapper')]//tbody/tr[1]//span[contains(.,'更多')]",
        "xpath=//div[contains(@class,'el-table__fixed-body-wrapper')]//tbody/tr[1]//span[contains(.,'更多')]",
        "xpath=//div[@role='tabpanel' and not(contains(@style,'display: none'))]//div[@class='el-table__fixed-right']//tbody/tr[1]//span[contains(.,'更多')]",
    ]
    expanded = False
    for more_xpath in more_xpaths:
        more_count = safe_count(page, more_xpath)
        if more_count > 0:
            try:
                page.locator(more_xpath).first.click()
                page.wait_for_timeout(500)
                expanded = True
                break
            except Exception:
                continue

    if expanded:
        # 探测菜单项
        xpath = (f"xpath=//*[(@x-placement='top-end' or @x-placement='bottom-end')]"
                 f"//*[{_contains_text(label)}"
                 f"]")
        c = safe_count(page, xpath)
        if c >= 1:
            is_vis = check_first_visible(page, xpath)
            if is_vis:
                attempts.append({"locator": xpath, "verified": c == 1, "count": c,
                                 "strategy": "dropdown-menu-item"})

        try:
            page.keyboard.press('Escape')
        except Exception:
            pass

    best = pick_best(attempts)
    if best:
        best.update({"key": key, "type": "dropdown-menu", "label": label})
        return best
    return {"key": key, "type": "dropdown-menu", "label": label, "verified": False, "count": 0}


# ============================================================
# tab-scoped 多 tab 作用域内探测
# ============================================================

def probe_tab_scoped(page, tab_name, element_type, label, key, container_types=None):
    """探测多 tab 作用域内的元素

    三步法：点击 tab → 获取 aria-controls → 在 //div[@id='aria_id'] 作用域内探测元素。
    如果 tab panel 在 drawer/dialog 内，自动叠加容器前缀。
    """
    attempts = []

    # Step 1: 点击 tab
    tab_xpath = (f"xpath=//*[{_contains_text(tab_name)} and @role='tab'"
                 f"]")
    try:
        page.locator(tab_xpath).first.click()
        page.wait_for_timeout(500)

        # Step 2: 获取 aria-controls
        tab_el = page.locator(tab_xpath).first
        aria_id = tab_el.get_attribute('aria-controls')
        if aria_id:
            scope = f"//div[@id='{aria_id}']"

            # 构建容器前缀变体（含无容器版本）
            scope_variants = [scope]
            if container_types:
                for ct in sorted(container_types, key=lambda c: CONTAINER_PRIORITY.get(c, 99)):
                    prefix = CONTAINER_XPATH.get(ct, "")
                    if prefix:
                        scope_variants.insert(0, f"{prefix}{scope}")

            for sc in scope_variants:
                if element_type == 'button':
                    xpath = (f"xpath={sc}//button[{_contains_dot(label)}"
                             f"]")
                elif element_type in ('input', 'el-select'):
                    xpath = (f"xpath={sc}//*[{_contains_text(label)}]"
                             f"/following-sibling::*[self::div or self::span]"
                             f"//input[@class='el-input__inner'"
                             f"]")
                else:
                    xpath = (f"xpath={sc}//*[{_contains_text(label)}"
                             f"]")

                c = safe_count(page, xpath)
                if c >= 1:
                    is_vis = check_first_visible(page, xpath)
                    if is_vis:
                        entry = {"locator": xpath, "verified": c == 1, "count": c,
                                 "strategy": f"tab-scoped-{element_type}"}
                        if sc != scope:
                            entry["container_scoped"] = True
                        attempts.append(entry)
                        break  # 找到即用，不再尝试其他 scope

            result = pick_best(attempts)
            if result:
                result.update({"key": key, "type": "tab-scoped", "label": label,
                               "tab_id": aria_id, "tab_name": tab_name})
                return result
    except Exception:
        pass

    return {"key": key, "type": "tab-scoped", "label": label, "verified": False, "count": 0}


# ============================================================
# 主探测流程
# ============================================================

def probe_page(url, cookie_str=None, actions=None, elements=None, browser_type="chromium", local_storage=None, viewport_width=1920, viewport_height=1080):
    """打开页面，执行前置操作序列，逐个探测元素"""
    pw = sync_playwright().start()
    browser = getattr(pw, browser_type).launch(headless=True)
    context = browser.new_context(viewport={"width": viewport_width, "height": viewport_height})

    if cookie_str:
        domain = urlparse(url).hostname
        if domain:
            cookies = parse_cookie(cookie_str, domain)
            context.add_cookies(cookies)

            # 自动同步：将 cookie 中的 token 类字段注入 localStorage
            TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'auth_token', 'jwt_token'}
            if local_storage is None:
                local_storage = {}
            for c in cookies:
                if c['name'] in TOKEN_KEYS and c['name'] not in local_storage:
                    local_storage[c['name']] = c['value']

    page = context.new_page()
    page.goto(url, wait_until="networkidle", timeout=30000)

    # 注入 localStorage（如果有）并重新导航到目标 URL
    if local_storage:
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
        page.goto(url, wait_until="networkidle", timeout=30000)

    page.wait_for_timeout(2000)

    # 执行前置操作序列（支持多步）
    for action in (actions or []):
        action_type, action_selector, extra = _parse_action(action)
        action_selector = _resolve_action_selector(page, action_selector)
        try:
            if action_type == "click":
                page.locator(action_selector).first.click()
                page.wait_for_timeout(2000)
            elif action_type == "wait":
                page.wait_for_timeout(int(action_selector))
            elif action_type == "fill":
                page.locator(action_selector).first.fill(extra or "")
                page.wait_for_timeout(500)
            else:
                print(f"  [WARN] 未知操作类型: {action}", file=sys.stderr)
        except Exception as e:
            print(f"  [WARN] 前置操作失败: {action} -> {e}", file=sys.stderr)

    # 前置操作后检测可见容器（drawer/dialog/message-box）
    # 传入 probe_element() 使容器作用域版本优先尝试
    container_types = []
    try:
        visible_containers = detect_visible_containers(page)  # R4 修复: 复用共享函数，含 message-box
        if visible_containers:
            container_types = visible_containers
            print(f"[INFO] 检测到可见容器: {container_types}")
    except Exception as e:
        print(f"  [WARN] 容器检测失败: {e}", file=sys.stderr)

    # 逐个探测元素（统一使用 probe_element()，传入 container_types）
    results = []
    for elem in (elements or []):
        result = probe_element(page, elem["type"], elem["label"], elem["key"],
                               container_types=container_types or None)
        results.append(result)

    # 抽屉/对话框作用域自动检测与修正（安全网）
    # 当 probe_element 已经处理了容器作用域，这里只处理漏网的元素
    # 纯 XPath 容器前缀（R4.21：禁止 CSS 选择器）— 复用共享常量

    # 使用已检测的 container_types 作为全局 fallback
    global_container_type = container_types[0] if container_types else None
    if actions and container_types:

        # Step 2: 对每个元素做 DOM 向上遍历，找到实际容器（fallback 到全局检测）
        def _detect_element_container(page, xpath_expr):
            """从元素向上遍历 DOM 祖先链，找到最近的容器类型"""
            try:
                return page.evaluate(f"""(xpathExpr) => {{
                    let el;
                    try {{
                        el = document.evaluate(xpathExpr, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    }} catch(e) {{ return null; }}
                    if (!el) return null;
                    let parent = el.parentElement;
                    let depth = 0;
                    while (parent && depth < 30) {{
                        const cl = parent.classList;
                        if (cl && cl.contains('el-dialog')) return 'dialog';
                        if (cl && cl.contains('el-drawer')) return 'drawer';
                        if (cl && cl.contains('el-message-box')) return 'message-box';  // R4 修复
                        parent = parent.parentElement;
                        depth++;
                    }}
                    return null;
                }}""", xpath_expr)
            except Exception:
                return None

        # 始终执行元素级容器检测（不依赖全局检测结果）
        for result in results:
            loc = result.get("locator", "")
            if not loc:
                continue
            # 仅处理 xpath= 开头的定位器
            if not loc.startswith("xpath="):
                continue
            xpath_part = loc[6:]
            # 已有容器前缀 → 跳过
            if any(p in xpath_part for p in CONTAINER_CLASS_PATTERNS):
                continue

            # 元素级 DOM 向上遍历检测
            actual_type = _detect_element_container(page, xpath_part)
            effective_type = actual_type or global_container_type

            if effective_type:
                prefix = CONTAINER_XPATH[effective_type]
                result["locator"] = f"xpath={prefix}{xpath_part}"
                result["container_scoped"] = True
                result["container_type"] = effective_type
                src = "元素级DOM遍历" if actual_type else "全局fallback"
                result["note"] = result.get("note", "") + f" [已添加 {effective_type} 作用域 ({src})]"

    container_type = global_container_type

    browser.close()
    pw.stop()
    return results, container_type


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法: python probe_element.py <url> [options]")
        print("选项:")
        print("  --cookie 'name=value;...'          认证 Cookie")
        print("  --local-storage 'k1=v1;k2=v2'      注入 localStorage")
        print("  --action 'click:selector'           前置操作（可多次使用，按顺序执行）")
        print("  --action 'wait:2000'                前置等待（毫秒）")
        print("  --action 'fill:selector:value'      前置填写")
        print("  --element 'type:label:key'          探测元素（可多次使用）")
        print("  --verify 'key=locator'             验证已有 locator（可多次使用）")
        print("  --knowledge file.json               知识库路径（可选，默认内置）")
        print("  --observe 'click:selector'          操作后观察模式")
        print("  --output file.json                  输出文件")
        print("  --viewport 2560x1600                视口尺寸（宽x高，默认 1920x1080）")
        sys.exit(1)

    url = sys.argv[1]
    cookie_str = None
    actions = []
    elements = []
    verify_items = []
    output_file = None
    observe_action = None
    local_storage = None
    knowledge_path = None
    viewport_width = 1920
    viewport_height = 1080

    i = 2
    args = sys.argv
    while i < len(args):
        if args[i] == "--cookie" and i + 1 < len(args):
            cookie_str = args[i + 1]
            i += 2
        elif args[i] == "--viewport" and i + 1 < len(args):
            # 格式: --viewport 2560x1600 或 --viewport 2560,1600
            vp = args[i + 1].replace(",", "x").split("x")
            if len(vp) == 2:
                viewport_width = int(vp[0])
                viewport_height = int(vp[1])
            i += 2
        elif args[i] == "--local-storage" and i + 1 < len(args):
            local_storage = {}
            for item in args[i + 1].split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    local_storage[k.strip()] = v.strip()
            i += 2
        elif args[i] == "--action" and i + 1 < len(args):
            actions.append(args[i + 1])
            i += 2
        elif args[i] == "--element" and i + 1 < len(args):
            elem = parse_element(args[i + 1])
            if elem:
                elements.append(elem)
            i += 2
        elif args[i] == "--verify" and i + 1 < len(args):
            v = parse_verify(args[i + 1])
            if v:
                verify_items.append(v)
            i += 2
        elif args[i] == "--knowledge" and i + 1 < len(args):
            knowledge_path = args[i + 1]
            load_knowledge(knowledge_path)
            i += 2
        elif args[i] == "--observe" and i + 1 < len(args):
            observe_action = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        else:
            i += 1

    # M1 修复: cookie 优先从环境变量读取（probe_from_pages.py 传递）
    if cookie_str is None:
        cookie_str = os.environ.get('_PROBE_COOKIE')

    # 操作后观察模式
    if observe_action:
        print(f"操作后观察模式: {url}")
        print(f"操作: {observe_action}")
        if elements:
            print(f"同时探测元素: {len(elements)} 个")
        if verify_items:
            print(f"同时验证 locator: {len(verify_items)} 个")
        pw = sync_playwright().start()
        browser = getattr(pw, "chromium").launch(headless=True)
        context = browser.new_context(viewport={"width": viewport_width, "height": viewport_height})
        if cookie_str:
            domain = urlparse(url).hostname
            if domain:
                cookies = parse_cookie(cookie_str, domain)
                context.add_cookies(cookies)
                # 自动同步 token 到 localStorage
                TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'auth_token', 'jwt_token'}
                if local_storage is None:
                    local_storage = {}
                for c in cookies:
                    if c['name'] in TOKEN_KEYS and c['name'] not in local_storage:
                        local_storage[c['name']] = c['value']
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        # 注入 localStorage（如果有）并重新导航到目标 URL 使生效
        if local_storage:
            for k, v in local_storage.items():
                page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
            page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # 如果同时有 --element 或 --verify，先执行元素探测/验证
        probe_results = []
        if elements or verify_items:
            # 先执行前置操作
            if actions:
                for action in actions:
                    at, sel, val = _parse_action(action)
                    sel = _resolve_action_selector(page, sel)
                    try:
                        if at == "click":
                            page.locator(sel).first.click()
                        elif at == "wait":
                            page.wait_for_timeout(int(sel))
                        elif at == "fill":
                            page.locator(sel).first.fill(val or "")
                    except Exception as e:
                        print(f"  前置操作失败 ({action}): {e}")
                    page.wait_for_timeout(500)
            # 执行元素探测（--element）— 统一使用 probe_element()
            # observe 模式也需要容器检测
            obs_visible_containers = detect_visible_containers(page)
            for elem in elements:
                result = probe_element(page, elem['type'], elem['label'], elem['key'],
                                       container_types=obs_visible_containers or None)
                probe_results.append(result)
                status = "OK" if result.get('verified') else "FAIL"
                print(f"  [{status}] {elem['key']:30s} -> {result.get('locator', '')[:80]}")
            # 执行 locator 验证（--verify）
            if verify_items:
                verify_results = verify_locators(page, verify_items)
                probe_results.extend(verify_results)

        # 执行 observe 动作
        result = observe_after_action(page, observe_action)

        browser.close()
        pw.stop()

        output = {"mode": "observe", "url": url, "result": result}
        if probe_results:
            output["elements"] = probe_results
            output["actions"] = actions or []
            verified = sum(1 for r in probe_results if r.get('verified'))
            print(f"\n元素探测/验证: {verified}/{len(probe_results)} 个已验证")
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存到: {output_file}")
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 元素探测模式 / locator 验证模式
    if not elements and not verify_items:
        print("错误: 至少需要一个 --element 或 --verify 参数")
        sys.exit(1)

    print(f"探测页面: {url}")
    if actions:
        print(f"前置操作: {len(actions)} 步")
    if elements:
        print(f"探测元素: {len(elements)} 个")
    if verify_items:
        print(f"验证 locator: {len(verify_items)} 个")
    print()

    # 打开页面
    pw = sync_playwright().start()
    browser = getattr(pw, "chromium").launch(headless=True)
    context = browser.new_context(viewport={"width": viewport_width, "height": viewport_height})

    if cookie_str:
        domain = urlparse(url).hostname
        if domain:
            cookies = parse_cookie(cookie_str, domain)
            context.add_cookies(cookies)
            TOKEN_KEYS = {'ud_token', 'token', 'access_token', 'auth_token', 'jwt_token'}
            if local_storage is None:
                local_storage = {}
            for c in cookies:
                if c['name'] in TOKEN_KEYS and c['name'] not in local_storage:
                    local_storage[c['name']] = c['value']

    page = context.new_page()
    page.goto(url, wait_until="networkidle", timeout=30000)

    if local_storage:
        for k, v in local_storage.items():
            page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
        page.goto(url, wait_until="networkidle", timeout=30000)

    page.wait_for_timeout(2000)

    # 执行前置操作序列
    for action in (actions or []):
        action_type, action_selector, extra = _parse_action(action)
        action_selector = _resolve_action_selector(page, action_selector)
        try:
            if action_type == "click":
                page.locator(action_selector).first.click()
                page.wait_for_timeout(2000)
            elif action_type == "wait":
                page.wait_for_timeout(int(action_selector))
            elif action_type == "fill":
                page.locator(action_selector).first.fill(extra or "")
                page.wait_for_timeout(500)
            else:
                print(f"  [WARN] 未知操作类型: {action}", file=sys.stderr)
        except Exception as e:
            print(f"  [WARN] 前置操作失败: {action} -> {e}", file=sys.stderr)

    # 检测当前可见的容器（el-drawer / el-dialog）
    visible_containers = detect_visible_containers(page)
    if visible_containers:
        print(f"[容器检测] 当前可见容器: {', '.join(visible_containers)}")

    # 执行元素探测（--element）— 统一使用 probe_element()
    results = []
    for elem in (elements or []):
        result = probe_element(page, elem["type"], elem["label"], elem["key"],
                               container_types=visible_containers)
        results.append(result)

    # 执行 locator 验证（--verify）
    if verify_items:
        verify_results = verify_locators(page, verify_items)
        results.extend(verify_results)

    browser.close()
    pw.stop()

    verified_count = sum(1 for r in results if r.get("verified"))
    print(f"\n探测完成: {verified_count}/{len(results)} 个元素已验证")
    for r in results:
        status = "OK" if r.get("verified") else "FAIL"
        loc = r.get("locator", "(无)")
        extra = ""
        if r.get("select_options_total"):
            extra = f"  选项:{r['select_options_total']}个"
        if r.get("needs_exact_match"):
            extra += "  需精确匹配"
        if r.get("two_step"):
            extra += "  [两步操作]"
        if r.get("is_table_pattern"):
            extra += "  [表格模式]"
        if r.get("note"):
            extra += f"  ({r['note']})"
        if r.get("strategy") == "direct-verify" and r.get("count", 0) != 1:
            extra += f"  count={r.get('count', 0)}"
        print(f"  [{status}] {r['key']:30s} -> {loc[:80]}{extra}")

    output = {
        "url": url, "actions": actions,
        "container_type": visible_containers[0] if visible_containers else None,
        "elements": results,
        "summary": {
            "total": len(results),
            "verified": verified_count,
            "failed": len(results) - verified_count,
        },
    }

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_file}")
    else:
        print("\n--- JSON 输出 ---")
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
