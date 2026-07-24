#!/usr/bin/env python3
"""xpath_utils.py — XPath 定位器工具函数（共享模块）

被 _pages_writer.py、probe_from_pages.py 共同导入。
隐藏过滤注入逻辑只维护此一处，确保三处行为完全一致。

用法:
    from xpath_utils import inject_hidden_filter, has_hidden_filter

    locator = inject_hidden_filter("xpath=//button[contains(.,'查询')]")
    # → xpath=//button[contains(.,'查询') and not(ancestor::...) and not(ancestor::...)]
"""
import re

# ============================================================================
# 隐藏过滤属性（R4.11：排除 is-hidden / display:none 的不可见元素）
# ============================================================================

HIDDEN_FILTER = (
    " and not(ancestor::*[contains(@class,'is-hidden')])"
    " and not(ancestor::*[contains(@style,'display: none')])"
)

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
}

CONTAINER_CLASS_PATTERNS = [
    "contains(@class,'el-drawer')",
    "contains(@class,'el-dialog')",
    "contains(@class,'el-message-box')",  # R4 新增
]

# 外层包裹正则: (xpath)[1] / (xpath)[last()]
_OUTER_WRAP_RE = re.compile(r'^\(.*\)\[(\d+|last\(\))\]$')


_HIDDEN_FILTER_SIGNATURE = "not(ancestor::*[contains(@class,'is-hidden')])"

def has_hidden_filter(locator: str) -> bool:
    """检测 locator 是否已包含隐藏过滤属性（精确签名匹配）

    使用完整的 not(ancestor::...) 签名匹配，避免 is-hidden 作为
    class 名匹配（如 contains(@class,'is-hidden')）时的子串误判。
    HIDDEN_FILTER 总是同时注入 is-hidden + display:none 两个条件，
    检测其中一个的完整签名即可。
    """
    if not locator or not isinstance(locator, str):
        return False
    return _HIDDEN_FILTER_SIGNATURE in locator


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


def inject_hidden_filter(locator: str) -> str:
    """在 XPath 最终元素标签上注入隐藏过滤属性（R4.11）

    幂等：已有则跳过。非 XPath → 跳过。豁免模式 → 跳过。

    注入位置：最后一个 // 之后的标签的 predicate 内。

    处理的情况：
      A: //tag[pred]       → //tag[pred and filter]
      B: //tag             → //tag[filter]
      C: //a[p]//b[q]     → //a[p]//b[q and filter]
      D: //a[p]//b         → //a[p]//b[filter]
      E: (//tag[p])[1]    → (//tag[p and filter])[1]
    """
    if not locator or not isinstance(locator, str):
        return locator
    v = locator.strip()
    if not (v.startswith('xpath=') or v.startswith('//') or v.startswith('(')):
        return locator
    if has_hidden_filter(v):
        return locator
    if _is_exempt(v):
        return locator

    has_prefix = v.startswith('xpath=')
    xpath = v[6:] if has_prefix else v

    # Step 1: 处理外层包裹 (xpath)[1] / (xpath)[last()]
    xpath, outer_wrap = _unwrap_positional(xpath)

    # Step 2: 找最终元素段
    final_start = _find_final_segment_start(xpath)
    final_segment = xpath[final_start:]

    # Step 3: 在最终段中找 predicate 的 ] 位置
    close_pos = _find_predicate_close_in_segment(final_segment)

    if close_pos >= 0:
        # 情况 A/C：在最终元素的 ] 前插入（追加 and filter）
        abs_close = final_start + close_pos
        new_xpath = xpath[:abs_close] + HIDDEN_FILTER + xpath[abs_close:]
    else:
        # 情况 B/D：最终元素没有 predicate，在标签名后追加 [filter]
        tag_match = re.match(r'([a-zA-Z*][a-zA-Z0-9_*-]*)', final_segment)
        if tag_match:
            tag_end = final_start + tag_match.end()
            new_xpath = (xpath[:tag_end]
                         + '[' + HIDDEN_FILTER_NEW_PRED + ']'
                         + xpath[tag_end:])
        else:
            return locator  # 无法解析，原样返回

    # Step 4: 重新包裹 + 恢复前缀
    prefix = 'xpath=' if has_prefix else ''
    return prefix + _rewrap_positional(new_xpath, outer_wrap)
