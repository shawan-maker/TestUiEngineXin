#!/usr/bin/env python3
"""xpath_utils.py — XPath 定位器工具函数（共享模块）

被 _pages_writer.py、verify_locators.py 共同导入。
隐藏过滤注入逻辑只维护此一处，确保三处行为完全一致。

用法:
    from xpath_utils import inject_hidden_filter, has_hidden_filter

    locator = inject_hidden_filter("xpath=//button[contains(.,'查询')]")
    # → xpath=//button[contains(.,'查询') and not(ancestor::...) and not(ancestor::...)]
"""
import os
import re
from core.yaml_utils import escape_yaml_scalar

# ============================================================================
# 隐藏过滤属性（R4.11：排除 is-hidden / display:none 的不可见元素）
# ============================================================================

HIDDEN_FILTER = (
    " and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
    " and not(ancestor-or-self::*[contains(@style,'display: none')])"
)

# 按钮禁用状态过滤（排除 disabled 按钮）
DISABLED_FILTER = (
    " and not(@disabled)"
    " and not(ancestor-or-self::*[contains(@class,'is-disabled')])"
)

# 按钮类型集合（这些类型需要注入 disabled 过滤）
BUTTON_TYPES = {'button', 'search-button', 'table-action-button', 'close-button', 'download-button'}

# 新建 predicate 时，去掉开头的 " and "
HIDDEN_FILTER_NEW_PRED = re.sub(r'^\s*and\s+', '', HIDDEN_FILTER.strip())

# 豁免模式：这些 locator 不注入隐藏过滤
# Fix-5a: 第一条加 ^ 锚点，仅豁免以 //* [contains(., 开头的纯通用断言（如 success_text），
# 不误豁免 //tbody/tr[.//*[contains(.,...)]] 等复合 XPath（表格行计数、条件检查）。
EXEMPT_PATTERNS = [
    re.compile(r'^//\*\[contains\(\.,'),        # 通用断言 //* [contains(.,'...')]（仅匹配以 //*[ 开头的）
    re.compile(r'@x-placement'),                  # option 定位器（已有自己的可见性逻辑）
    re.compile(r'^text='),                        # Playwright text 选择器
    re.compile(r'^role='),                        # Playwright role 选择器
    re.compile(r'el-loading-mask'),               # loading 遮罩（用于等待消失）
]

# ============================================================================
# 容器前缀映射（共享常量，probe_element.py 和 _pages_writer.py 共同引用）
# ============================================================================

CONTAINER_XPATH = {
    "drawer": "//div[contains(@class,'el-drawer')]",
    "dialog": "//div[contains(@class,'el-dialog')]",
    "message-box": "//div[contains(@class,'el-message-box')]",  # R4 新增
    # Ant Design
    "ant-drawer": "//div[contains(@class,'ant-drawer')]",
    "ant-modal": "//div[contains(@class,'ant-modal')]",
}

CONTAINER_CLASS_PATTERNS = [
    "contains(@class,'el-drawer')",
    "contains(@class,'el-dialog')",
    "contains(@class,'el-message-box')",  # R4 新增
    # Ant Design
    "contains(@class,'ant-drawer')",
    "contains(@class,'ant-modal')",
]

# 外层包裹正则: (xpath)[1] / (xpath)[last()]
_OUTER_WRAP_RE = re.compile(r'^\(.*\)\[(\d+|last\(\))\]$')


_HIDDEN_FILTER_SIGNATURE = "not(ancestor-or-self::*[contains(@class,'is-hidden')])"

def has_hidden_filter(locator: str) -> bool:
    """检测 locator 是否已包含隐藏过滤属性（兼容新旧两种签名）

    使用完整的 not(ancestor-or-self::...) / not(ancestor::...) 签名匹配，
    避免 is-hidden 作为 class 名匹配时的子串误判。
    HIDDEN_FILTER 总是同时注入 is-hidden + display:none 两个条件，
    检测其中一个的完整签名即可。
    兼容旧版 ancestor:: 和新版 ancestor-or-self:: 两种写法。
    """
    if not locator or not isinstance(locator, str):
        return False
    return (_HIDDEN_FILTER_SIGNATURE in locator
            or "not(ancestor::*[contains(@class,'is-hidden')])" in locator)


def _is_exempt(locator: str) -> bool:
    """检测 locator 是否属于豁免模式（不注入隐藏过滤）"""
    if not locator:
        return False
    stripped = locator.replace('xpath=', '').strip()
    return any(p.search(stripped) for p in EXEMPT_PATTERNS)


def _unwrap_positional(xpath: str) -> tuple:
    """解包 (xpath)[N] 格式，返回 (inner_xpath, wrap_suffix)

    例: (//button[contains(.,'查询')])[1] → (//button[contains(.,'查询')], [1])
    如无包裹 → (xpath, '')
    """
    m = _OUTER_WRAP_RE.match(xpath)
    if m and xpath.startswith('('):
        wrap = f'[{m.group(1)}]'
        wrap_len = len(wrap) + 1  # )[N] 的长度
        inner = xpath[1:-wrap_len]  # 去掉开头 ( 和结尾 )[N]
        return inner, wrap
    return xpath, ''


def _rewrap_positional(xpath: str, wrap_suffix: str) -> str:
    """重新包裹 (xpath)[N] 格式。如 wrap_suffix 非空返回 (xpath)[N]，否则原样返回"""
    if wrap_suffix:
        return f'({xpath}){wrap_suffix}'
    return xpath


def _find_final_segment_start(xpath: str) -> int:
    """找最终元素段的起始位置：最后一个不在 [] 内的 // 之后

    例: //div[contains(@class,'w')]//button → 返回 button 的起始位置
        //button → 返回 0（单段，无 // 分隔）
    """
    final_start = -1
    depth = 0
    i = 0
    while i < len(xpath):
        ch = xpath[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        elif depth == 0 and ch == '/' and i + 1 < len(xpath) and xpath[i + 1] == '/':
            final_start = i + 2
            i += 2
            continue
        i += 1
    return final_start if final_start >= 0 else 0


def _find_predicate_close_in_segment(segment: str) -> int:
    """在最终段中找 predicate 的 ] 位置（从右向左）

    返回 ] 在 segment 中的绝对位置，未找到返回 -1。
    仅匹配标签名后紧跟的 [...]，不匹配嵌套的子路径 predicate。
    """
    p_depth = 0
    paren_depth = 0
    for j in range(len(segment) - 1, -1, -1):
        ch = segment[j]
        if ch == ')':
            paren_depth += 1
        elif ch == '(':
            paren_depth -= 1
        elif paren_depth > 0:
            continue
        elif ch == ']':
            p_depth += 1
        elif ch == '[':
            p_depth -= 1
            if p_depth == 0:
                # 检查 [ 前是否是标签名（字母开头）
                k = j - 1
                while k >= 0 and segment[k] in ' \t':
                    k -= 1
                if k >= 0 and (segment[k].isalpha() or segment[k] == '*'):
                    # 找到对应的 ]
                    inner_d = 0
                    for m in range(j, len(segment)):
                        if segment[m] == '[':
                            inner_d += 1
                        elif segment[m] == ']':
                            inner_d -= 1
                            if inner_d == 0:
                                return m
                break
    return -1


# ============================================================================
# 容器前缀操作函数（P2 统一重构）
# ============================================================================

def has_container_prefix(xpath):
    """检查 XPath 是否已包含任意容器前缀（精确匹配）

    使用完整模式匹配（contains(@class,'el-drawer')），非子串匹配。

    Args:
        xpath: XPath 表达式（可含 xpath= 前缀，可含 (xpath)[N] 包裹）

    Returns:
        True 如果包含 el-drawer/el-dialog/el-message-box 前缀
    """
    if not xpath or not isinstance(xpath, str):
        return False
    return any(pattern in xpath for pattern in CONTAINER_CLASS_PATTERNS)


def apply_container_prefix(xpath, container_type):
    """为 XPath 添加容器前缀（幂等：已有前缀则跳过）

    特性：
    - 幂等：已含容器前缀则原样返回
    - BUG-13 保护：正确处理 (xpath)[N] 包裹格式
    - 相对路径保护：非 // 开头的 XPath 原样返回
    - 无效参数保护：container_type 无效或空值时原样返回

    Args:
        xpath: 原始 XPath 表达式（不含 xpath= 前缀）
        container_type: 容器类型 ('drawer'/'dialog'/'message-box'/None)

    Returns:
        添加前缀后的 XPath；如不适用则返回原值
    """
    if not xpath or not container_type:
        return xpath

    # 幂等：已有容器前缀则跳过
    if has_container_prefix(xpath):
        return xpath

    # 查找前缀模板
    prefix = CONTAINER_XPATH.get(container_type, "")
    if not prefix:
        return xpath

    # BUG-13 保护：解包 (xpath)[N]，前缀注入到括号内部
    inner, wrap = _unwrap_positional(xpath)

    # 相对路径保护：非 // 开头的 XPath 不添加前缀
    if not inner.startswith('//'):
        return xpath

    scoped = f"{prefix}{inner}"
    return _rewrap_positional(scoped, wrap)


def detect_container_type(locator):
    """从 locator 中精确检测容器类型

    使用完整模式匹配（contains(@class,'el-drawer')），非子串匹配。
    仅用于需要精确判断的场景。宽松的 'el-drawer' in locator 检查
    不应使用此函数（如 R4.38 警告检查、容器统计）。

    Args:
        locator: locator 字符串（可含 xpath= 前缀）

    Returns:
        'drawer' / 'dialog' / 'message-box' / None
    """
    if not locator or not isinstance(locator, str):
        return None
    for pattern, ctype in zip(CONTAINER_CLASS_PATTERNS, CONTAINER_XPATH.keys()):
        if pattern in locator:
            return ctype
    return None


def inject_hidden_filter(locator: str, in_iframe: bool = False, elem_type: str = None) -> str:
    """在 XPath 最终元素标签上注入隐藏过滤属性（R4.11）

    幂等：已有则跳过。非 XPath → 跳过。豁免模式 → 跳过。

    Args:
        locator: XPath locator 字符串
        in_iframe: 如果为 True，跳过注入（iframe 内元素的 XPath 相对于
                   iframe document，主页面的 hidden filter 语义不适用）。
                   _iframe companion 字段（指向主页面 iframe 元素）应设为 False。
                   （iframe 支持 2026-08-03 CI-3）
        elem_type: 元素类型（如 'button', 'input-generic' 等）。
                   当为按钮类型时，额外注入 disabled 状态过滤。

    注入位置：最后一个 // 之后的标签的 predicate 内。

    处理的情况：
      A: //tag[pred]       → //tag[pred and filter]
      B: //tag             → //tag[filter]
      C: //a[p]//b[q]     → //a[p]//b[q and filter]
      D: //a[p]//b         → //a[p]//b[filter]
      E: (//tag[p])[1]    → (//tag[p and filter])[1]
    """
    if in_iframe:
        return locator  # iframe 内元素不注入主页面 hidden filter
    if not locator or not isinstance(locator, str):
        return locator
    v = locator.strip()
    if not (v.startswith('xpath=') or v.startswith('//') or v.startswith('(')):
        return locator
    if has_hidden_filter(v):
        return locator
    if _is_exempt(v):
        return locator

    # 根据 elem_type 决定注入的过滤条件
    _filter = HIDDEN_FILTER
    _filter_new = HIDDEN_FILTER_NEW_PRED
    if elem_type and elem_type in BUTTON_TYPES:
        _filter = HIDDEN_FILTER + DISABLED_FILTER
        _filter_new = re.sub(r'^\s*and\s+', '', (HIDDEN_FILTER + DISABLED_FILTER).strip())

    has_prefix = v.startswith('xpath=')
    xpath = v[6:] if has_prefix else v

    # Step 1: 处理外层包裹 (xpath)[1] / (xpath)[last()]
    xpath, outer_wrap = _unwrap_positional(xpath)

    # Step 2: 找最终元素段
    final_start = _find_final_segment_start(xpath)
    final_segment = xpath[final_start:]

    # Step 3: 检测 XPath 轴（axis）模式
    # 常见轴: ancestor::, descendant::, following-sibling::, preceding-sibling:: 等
    # 轴名后不能直接加谓词，必须在 ::* 或 ::node_test 之后
    axis_match = re.match(r'^([a-z-]+)::(\*|[a-zA-Z][a-zA-Z0-9_-]*)', final_segment)

    if axis_match:
        # 情况 F/G: 轴表达式，谓词必须加在 ::* 或 ::node_test 之后
        axis_name = axis_match.group(1)  # e.g., "following-sibling"
        node_test = axis_match.group(2)  # e.g., "*" or "div"
        axis_end = axis_match.end()  # ::* 之后的位置

        # 检查 ::* 或 ::node_test 之后是否已有谓词
        rest = final_segment[axis_end:]
        if rest.startswith('['):
            # 情况 F: 已有谓词，在 ] 前追加 and filter
            # 使用简单的括号深度扫描找到匹配的 ]
            depth = 0
            close_pos = -1
            for i, ch in enumerate(rest):
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        close_pos = i
                        break
            if close_pos >= 0:
                abs_close = final_start + axis_end + close_pos
                new_xpath = xpath[:abs_close] + _filter + xpath[abs_close:]
            else:
                return locator  # 无法解析，原样返回
        else:
            # 情况 G: 没有谓词，在 ::node_test 后添加 [filter]
            abs_insert = final_start + axis_end
            new_xpath = (xpath[:abs_insert]
                        + '[' + _filter_new + ']'
                        + xpath[abs_insert:])
    else:
        # 原有逻辑：处理普通标签名
        # Step 3: 在最终段中找 predicate 的 ] 位置
        close_pos = _find_predicate_close_in_segment(final_segment)

        if close_pos >= 0:
            # 情况 A/C：在最终元素的 ] 前插入（追加 and filter）
            abs_close = final_start + close_pos
            new_xpath = xpath[:abs_close] + _filter + xpath[abs_close:]
        else:
            # 情况 B/D：最终元素没有 predicate，在标签名后追加 [filter]
            tag_match = re.match(r'([a-zA-Z*][a-zA-Z0-9_*-]*)', final_segment)
            if tag_match:
                tag_end = final_start + tag_match.end()
                new_xpath = (xpath[:tag_end]
                            + '[' + _filter_new + ']'
                            + xpath[tag_end:])
            else:
                return locator  # 无法解析，原样返回

    # Step 4: 重新包裹 + 恢复前缀
    prefix = 'xpath=' if has_prefix else ''
    return prefix + _rewrap_positional(new_xpath, outer_wrap)


# ============================================================================
# 批量页面处理函数（从 probe_from_pages.py 迁移）
# ============================================================================

def apply_hidden_filters_to_pages(pages_data: dict, source_files: dict, pages_dir: str) -> int:
    """批量补齐 pages YAML 中所有 locator 的隐藏过滤属性。

    遍历 pages_data 中的所有 group 和 field，对每个 locator 调用 inject_hidden_filter()。
    如果 locator 被修改，更新 pages_data 内存对象并回写到对应的 YAML 文件。

    Args:
        pages_data: {group_name: {field_name: locator}} 页面数据字典
        source_files: {group_name: filepath} group 到 YAML 文件的映射
        pages_dir: pages 目录路径（未使用，保留参数兼容性）

    Returns:
        修改的 locator 数量
    """
    modified_count = 0
    file_changes = {}

    for group_name, fields in pages_data.items():
        if not isinstance(fields, dict):
            continue
        for field_name, locator in fields.items():
            if not isinstance(locator, str):
                continue
            new_locator = inject_hidden_filter(locator)
            if new_locator != locator:
                pages_data[group_name][field_name] = new_locator
                modified_count += 1
                src = source_files.get(group_name, '')
                if src:
                    file_changes.setdefault(src, []).append(
                        (locator, new_locator, field_name))

    # 回写文件
    for filepath, changes in file_changes.items():
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
        for old_val, new_val, field_name in changes:
            for i, line in enumerate(lines):
                # 行级精准替换：只在 YAML 值位置（冒号后）替换，避免污染注释或其他字段
                if ':' in line and old_val in line:
                    key_part, sep, val_part = line.partition(':')
                    # 检查字段名精确匹配（防止后缀重叠的误替换）
                    if old_val in val_part and key_part.strip() == field_name:
                        # 提取注释部分（# 之后）
                        comment_suffix = ""
                        hash_pos = val_part.find('  #')
                        if hash_pos > 0:
                            comment_suffix = val_part[hash_pos:]
                        # 用 escape_yaml_scalar 重新转义新值，确保引号正确
                        re_escaped = escape_yaml_scalar(new_val)
                        lines[i] = f"{key_part}{sep} {re_escaped}{comment_suffix}\n"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    return modified_count


# R3.14：禁止使用 not(ancestor::...) 负向排除
_NOT_ANCESTOR_RE = re.compile(
    r"\s+and\s+not\(ancestor(?:-or-self)?::\*\[contains\(@class,'(?:el-drawer|el-dialog|el-message-box)'\)\]\)"
)


def _strip_not_ancestor_exclusion(locator: str) -> str:
    """移除 locator 中的 not(ancestor::*[contains(@class,'el-drawer')]) 等负向排除条件

    R3.14：禁止使用 not(ancestor::...) 负向排除。
    元素定位应使用正向容器前缀（如 //div[contains(@class,'el-drawer')]//button[...]），
    探测阶段会自动尝试有前缀 → 无前缀的降级策略。
    """
    return _NOT_ANCESTOR_RE.sub('', locator)


def strip_not_ancestor_from_pages(pages_data: dict, source_files: dict, pages_dir: str) -> int:
    """清除所有 locator 中的 not(ancestor::...) 负向排除条件

    替代原 apply_cross_group_exclusions()：不再注入负向排除，
    而是清除已有的负向排除，确保所有 locator 只使用正向容器前缀。

    Args:
        pages_data: {group_name: {field_name: locator}} 页面数据字典
        source_files: {group_name: filepath} group 到 YAML 文件的映射
        pages_dir: pages 目录路径（未使用，保留参数兼容性）

    Returns:
        清除的定位器数量
    """
    modified_count = 0
    file_changes = {}

    for group_name, fields in pages_data.items():
        if not isinstance(fields, dict):
            continue
        for field_name, locator in fields.items():
            if not isinstance(locator, str) or not locator.startswith('xpath='):
                continue
            new_locator = _strip_not_ancestor_exclusion(locator)
            if new_locator != locator:
                pages_data[group_name][field_name] = new_locator
                modified_count += 1
                src = source_files.get(group_name, '')
                if src:
                    file_changes.setdefault(src, []).append(
                        (locator, new_locator, field_name))

    # 回写文件
    for filepath, changes in file_changes.items():
        if not os.path.exists(filepath):
            continue
        with open(filepath, encoding='utf-8') as f:
            lines = f.readlines()
        for old_val, new_val, field_name in changes:
            for i, line in enumerate(lines):
                # 行级精准替换：只在 YAML 值位置（冒号后）替换，避免污染注释或其他字段
                if ':' in line and old_val in line:
                    key_part, sep, val_part = line.partition(':')
                    # 检查字段名精确匹配（防止后缀重叠的误替换）
                    if old_val in val_part and key_part.strip() == field_name:
                        # 提取注释部分（# 之后）
                        comment_suffix = ""
                        hash_pos = val_part.find('  #')
                        if hash_pos > 0:
                            comment_suffix = val_part[hash_pos:]
                        # 用 escape_yaml_scalar 重新转义新值，确保引号正确
                        re_escaped = escape_yaml_scalar(new_val)
                        lines[i] = f"{key_part}{sep} {re_escaped}{comment_suffix}\n"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    return modified_count
