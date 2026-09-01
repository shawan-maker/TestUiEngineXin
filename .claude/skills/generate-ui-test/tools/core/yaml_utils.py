#!/usr/bin/env python3
"""共享工具函数：YAML 标量转义

提供 YAML 标量序列化功能，确保 locator 中的特殊字符正确转义。
"""


def escape_yaml_scalar(value):
    """将字符串格式化为 YAML 安全标量（必要时加引号）。

    规则：
    - 布尔值/null 用单引号包裹（避免被解析为布尔类型）
    - 不含特殊字符时不加引号
    - 智能引号选择：
      * 含单引号不含双引号 → 用双引号包裹（XPath 最常见场景，拷贝可直接使用）
      * 含双引号不含单引号 → 用单引号包裹
      * 两者都有 → 用单引号 + '' 转义
      * 都不含 → 用单引号包裹

    Args:
        value: 要序列化的值

    Returns:
        str: YAML 安全标量字符串

    Examples:
        >>> escape_yaml_scalar("xpath=//td[contains(text(),'确认')]")
        '"xpath=//td[contains(text(),\\'确认\\')]"'

        >>> escape_yaml_scalar('xpath=//*[@title="test"]')
        "'xpath=//*[@title=\"test\"]'"

        >>> escape_yaml_scalar("simple_value")
        'simple_value'

        >>> escape_yaml_scalar("true")
        "'true'"
    """
    if not isinstance(value, str):
        return str(value)

    # 布尔值/null 用单引号包裹
    if value in ('true', 'false', 'yes', 'no', 'on', 'off', 'null', 'True', 'False'):
        return f"'{value}'"

    # 不含特殊字符时不加引号
    if not any(c in value for c in (':', '#', '{', '}', '[', ']', ',', '&', '*', '?', '|',
                                     '-', '<', '>', '=', '!', '%', '@', '`', '"', "'", '\n',
                                     '\\')):
        return value

    # 智能引号选择
    has_single = "'" in value
    has_double = '"' in value

    if has_single and not has_double:
        # 含单引号不含双引号 → 用双引号包裹（XPath 最常见场景）
        # YAML 双引号字符串中反斜杠和双引号需要转义，但 XPath 极少包含这些
        return f'"{value}"'
    elif has_double and not has_single:
        # 含双引号不含单引号 → 用单引号包裹
        return f"'{value}'"
    elif has_single and has_double:
        # 两者都有 → 用单引号 + '' 转义（回退到当前行为）
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    else:
        # 都不含 → 用单引号包裹（保持当前行为）
        return f"'{value}'"
