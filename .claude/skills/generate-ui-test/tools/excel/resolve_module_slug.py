#!/usr/bin/env python3
"""resolve_module_slug.py — 模块 slug 解析（简化版）

仅保留 3 级优先级：
  1. CLI --module-map 覆盖
  2. module_map.json 权威映射
  3. _auto_generate_slug() 兜底

AI 翻译由 translate_module_name.py 负责（在 build_module_map.py 中调用），
翻译结果写入 module_map.json 后，本文件只读取已有映射。

保留 _auto_generate_slug() 作为最终兜底。
"""

import re
import hashlib


def _validate_segment(seg):
    """校验 segment 是否为合法 slug 格式。"""
    if not seg:
        return False
    return bool(re.match(r'^[a-z][a-z0-9_-]{2,29}$', seg.lower()))


def _auto_generate_slug(cn_name):
    """从中文模块名自动生成英文 slug（兜底策略）。

    策略链：
      1. 提取 ASCII 部分（如 "PMO管理" → "pmo"），长度 >= 3 才采用
      2. MD5 hash 兜底（mod_ 前缀 + 8 位 hex）

    Returns: 合法 slug 字符串（永不为 None/空，确保首次运行不阻断）。
    """
    ascii_part = re.sub(r'[^a-zA-Z0-9]', '', cn_name).lower()
    if len(ascii_part) >= 3:
        return ascii_part
    return 'mod_' + hashlib.md5(cn_name.encode('utf-8')).hexdigest()[:8]


def resolve_module_slug(cn_name, module_urls=None, module_map=None,
                         cli_overrides=None):
    """统一的模块名解析入口（简化版）。

    优先级链：
      1. CLI --module-map 覆盖
      2. module_map.json 权威映射
      3. _auto_generate_slug() 兜底

    Args:
        cn_name: 中文模块名
        module_urls: 已废弃，保留参数兼容
        module_map: module_map.json 内容 {cn_name: slug}
        cli_overrides: CLI 覆盖 {cn_name: slug}

    Returns: slug 字符串（永不返回 None）
    """
    # Priority 1: CLI override
    if cli_overrides and cn_name in cli_overrides:
        return cli_overrides[cn_name]

    # Priority 2: module_map.json
    if module_map and cn_name in module_map:
        return module_map[cn_name]

    # Priority 3: Auto-generate
    return _auto_generate_slug(cn_name)
