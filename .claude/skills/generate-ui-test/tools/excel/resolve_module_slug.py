#!/usr/bin/env python3
"""resolve_module_slug.py — 统一的模块 slug 解析入口

解决 Excel 中文模块名（如"账户管理"）到英文 slug（如"account_manage"）的映射问题。

核心策略（5 优先级链）：
  1. CLI --module-map 覆盖（最高优先级）
  2. module_map.json 权威映射（已生成的历史数据）
  3. 多 URL 对比分析（≥2 个模块时，提取差异段）
  4. 单 URL 启发式提取（位置+语义双重过滤）
  5. 自动生成（ASCII 提取 / MD5 hash 兜底）

用法:
    from excel.resolve_module_slug import resolve_module_slug
    slug = resolve_module_slug("账户管理", module_urls, module_map, cli_overrides)
"""

import re
import hashlib


# 页面级关键词（从后往前跳过，这些通常是页面名而非模块名）
# 注意：不要加入 log/logs/order 等常见业务模块名
PAGE_KEYWORDS = {
    'list', 'detail', 'view', 'edit', 'add', 'create',
    'basic', 'info', 'message', 'manage', 'index', 'home',
    'query', 'search', 'result', 'config',
    'setting', 'settings', 'overview', 'dashboard',
}


def _validate_segment(seg):
    """校验 segment 是否为合法 slug 格式。

    规则：以字母开头，3-30 字符，只含小写字母、数字、下划线、连字符。
    """
    if not seg:
        return False
    return bool(re.match(r'^[a-z][a-z0-9_-]{2,29}$', seg.lower()))


def _is_page_keyword(seg):
    """判断 segment 是否为页面级关键词。"""
    return seg.lower() in PAGE_KEYWORDS


def _extract_path_segments(url):
    """从 URL 提取路径段列表。

    支持：
      - 普通路径：http://host/a/b/c → ['a', 'b', 'c']
      - Hash 路由：http://host/#/a/b → ['a', 'b']

    Returns: segments list 或 None
    """
    if not url:
        return None

    # Hash 路由优先
    hash_match = re.search(r'#/([^?#]*)', url)
    if hash_match:
        path = hash_match.group(1)
        return [s for s in path.split('/') if s]

    # 普通路径
    path_match = re.search(r'https?://[^/]+(/[^?#]*)', url)
    if path_match:
        path = path_match.group(1)
        return [s for s in path.split('/') if s]

    return None


def _extract_from_single_url(cn_name, module_urls):
    """单 URL 启发式提取：从后往前分析路径段，跳过页面级关键词和系统前缀。

    策略：
      1. 优先 hash 路由的第一个段
      2. 从后往前找第一个非页面级、非数字、长度 ≥ 3 的有效段
      3. 位置启发式：跳过前 1-2 段（系统前缀，如 /estack/web/）
      4. 回退到第一个有效段

    Args:
        cn_name: 中文模块名
        module_urls: {cn_name: {'urls': [...]}} 格式

    Returns: slug 字符串或 None
    """
    if not module_urls or cn_name not in module_urls:
        return None

    urls = module_urls[cn_name].get('urls', [])
    if not urls:
        return None

    url = urls[0]
    segments = _extract_path_segments(url)
    if not segments:
        return None

    # Hash 路由：取第一个段
    if '#/' in url:
        first_seg = segments[0].replace('-', '_').lower()
        if _validate_segment(first_seg):
            return first_seg
        return None

    # 普通路径：从后往前分析
    total = len(segments)
    for i in range(total - 1, -1, -1):
        seg = segments[i]

        # 跳过页面级关键词
        if _is_page_keyword(seg):
            continue

        # 跳过纯数字段（版本号如 v2, 123）
        if seg.isdigit():
            continue

        # 跳过太短的段（长度 < 3，如 web, api）
        if len(seg) < 3:
            continue

        # 位置启发式：前 2 段更可能是系统前缀（当总段数 > 3 时）
        if i < 2 and total > 3:
            continue

        # 验证格式
        normalized = seg.replace('-', '_').lower()
        if _validate_segment(normalized):
            return normalized

    # 回退：第一个有效段
    for seg in segments:
        normalized = seg.replace('-', '_').lower()
        if _validate_segment(normalized):
            return normalized

    return None


def _extract_by_comparison(cn_name, all_module_urls):
    """多 URL 对比分析：找公共前缀，提取差异段作为模块标识。

    算法：
      1. 提取所有模块的 URL 路径段
      2. 找公共前缀长度（所有模块在位置 i 的值相同）
      3. 对目标模块，取公共前缀之后的差异段
      4. 过滤页面级关键词，返回最有意义的段

    Args:
        cn_name: 目标中文模块名
        all_module_urls: {cn_name: {'urls': [...]}} 格式（所有模块）

    Returns: slug 字符串或 None
    """
    if not all_module_urls or len(all_module_urls) < 2:
        return None

    if cn_name not in all_module_urls:
        return None

    # 提取所有模块的路径段
    all_segments = {}
    for cn, data in all_module_urls.items():
        urls = data.get('urls', [])
        if not urls:
            continue
        segs = _extract_path_segments(urls[0])
        if segs:
            all_segments[cn] = segs

    if len(all_segments) < 2 or cn_name not in all_segments:
        return None

    # 找公共前缀长度
    seg_lists = list(all_segments.values())
    min_len = min(len(segs) for segs in seg_lists)
    common_prefix_len = 0
    for i in range(min_len):
        values_at_i = {segs[i] for segs in seg_lists}
        if len(values_at_i) == 1:
            common_prefix_len = i + 1
        else:
            break

    # 提取目标模块的差异段
    target_segments = all_segments[cn_name]
    unique_segments = target_segments[common_prefix_len:]

    if not unique_segments:
        return None

    # 从后往前找第一个非页面级的有效段
    for seg in reversed(unique_segments):
        if _is_page_keyword(seg):
            continue
        if seg.isdigit():
            continue
        normalized = seg.replace('-', '_').lower()
        if _validate_segment(normalized):
            return normalized

    # 回退：差异段中的第一个有效段
    for seg in unique_segments:
        normalized = seg.replace('-', '_').lower()
        if _validate_segment(normalized):
            return normalized

    return None


def _auto_generate_slug(cn_name):
    """从中文模块名自动生成英文 slug（兜底策略）。

    策略链：
      1. 提取 ASCII 部分（如 "PMO管理" → "pmo"），长度 ≥ 3 才采用
      2. MD5 hash 兜底（mod_ 前缀 + 8 位 hex）

    Returns: 合法 slug 字符串（永不为 None/空）
    """
    # 策略 1: ASCII 部分
    ascii_part = re.sub(r'[^a-zA-Z0-9]', '', cn_name).lower()
    if len(ascii_part) >= 3:
        return ascii_part

    # 策略 2: MD5 hash 兜底
    return 'mod_' + hashlib.md5(cn_name.encode('utf-8')).hexdigest()[:8]


def resolve_module_slug(cn_name, module_urls, module_map=None, cli_overrides=None):
    """统一的模块名解析入口。

    优先级链：
      1. CLI --module-map 覆盖
      2. module_map.json 权威映射
      3. 多 URL 对比分析（≥2 个模块时）
      4. 单 URL 启发式提取
      5. 自动生成（ASCII 提取 / MD5 hash）

    Args:
        cn_name: 中文模块名（如 "账户管理"）
        module_urls: module_urls.json 内容 {cn_name: {'urls': [...]}}
        module_map: module_map.json 内容 {cn_name: slug}（可选）
        cli_overrides: CLI --module-map 覆盖 {cn_name: slug}（可选）

    Returns: 英文 slug 字符串（永不返回 None）
    """
    # Priority 1: CLI override
    if cli_overrides and cn_name in cli_overrides:
        return cli_overrides[cn_name]

    # Priority 2: module_map.json
    if module_map and cn_name in module_map:
        return module_map[cn_name]

    # Priority 3: Multi-URL comparison
    if module_urls and len(module_urls) >= 2:
        slug = _extract_by_comparison(cn_name, module_urls)
        if slug:
            return slug

    # Priority 4: Single-URL heuristic
    if module_urls and cn_name in module_urls:
        slug = _extract_from_single_url(cn_name, module_urls)
        if slug:
            return slug

    # Priority 5: Auto-generate
    return _auto_generate_slug(cn_name)
