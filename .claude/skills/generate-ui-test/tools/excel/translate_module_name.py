#!/usr/bin/env python3
"""translate_module_name.py — 模块名统一入口（保留原始名）

核心原则：
  - 不翻译，输入什么就是什么
  - 只去除特殊字符（空格、连字符等），保留中文+英文+数字+下划线
  - 结果持久化到 module_map.json，后续所有阶段读取
  - 不依赖任何 AI API（OpenAI/Anthropic）
  - 所有模块名来源（Excel/NL/CLI）统一通过 resolve_and_translate() 处理

用法:
    from excel.translate_module_name import resolve_and_translate

    # Excel 模块列
    result = resolve_and_translate(["日志管理", "账户管理"])
    # → {"日志管理": "日志管理", "账户管理": "账户管理"}

    # 混合中英文
    result = resolve_and_translate(["ECS管理", "VPC网络"])
    # → {"ECS管理": "ECS管理", "VPC网络": "VPC网络"}
"""

import re
import sys


def resolve_and_translate(cn_names, cli_overrides=None, module_map=None,
                          ai_config=None):
    """统一模块名解析入口 — 保留原始名，只去除特殊字符。

    适用于：
      - build_module_map.py（Excel 模块列）
      - pipeline.py NL 路径（--module 参数）
      - pipeline.py post-phase_1b hook

    优先级链：
      1. cli_overrides（--module-map 显式指定）→ 直接采用
      2. module_map（已有映射）→ 直接采用
      3. 其他 → _sanitize() 保留原始名

    Args:
        cn_names: list[str] — 所有来源的模块名（中文或英文）
        cli_overrides: dict — CLI --module-map {"日志管理": "log"}
        module_map: dict — module_map.json 已有映射
        ai_config: dict — 保留参数兼容性，未使用

    Returns: dict — {cn_name: slug}，所有 cn_name 都有值（永不缺漏）
    """
    cli_overrides = cli_overrides or {}
    module_map = module_map or {}
    result = {}

    for cn in cn_names:
        if cn in cli_overrides:
            result[cn] = cli_overrides[cn]
        elif cn in module_map:
            result[cn] = module_map[cn]
        else:
            result[cn] = _sanitize(cn)

    # 碰撞检测
    seen_slugs = {}
    for cn, slug in list(result.items()):
        if slug in seen_slugs:
            original = slug
            for suffix in range(2, 100):
                candidate = f'{original}_{suffix}'
                if candidate not in seen_slugs and candidate not in result.values():
                    result[cn] = candidate
                    print(f"[COLLISION] {cn} → {candidate} (与 {seen_slugs[original]} 冲突)",
                          file=sys.stderr)
                    break
        seen_slugs[result[cn]] = cn

    return result


def _sanitize(name):
    """保留原始名，只去除特殊字符。

    规则：
      - 保留中文、英文、数字、下划线
      - 空格、连字符、点号等替换为下划线
      - 连续下划线合并为一个
      - 去除首尾下划线
    """
    # 保留 \w（字母+数字+下划线）和中文（一-鿿）
    slug = re.sub(r'[^\w一-鿿]', '_', name)
    slug = re.sub(r'_+', '_', slug).strip('_')
    return slug or name


def translate_module_names(cn_names, ai_config=None):
    """兼容入口 — 直接返回 sanitize 结果（不翻译）。

    保留此函数名以兼容调用方。
    """
    return {cn: _sanitize(cn) for cn in cn_names}
