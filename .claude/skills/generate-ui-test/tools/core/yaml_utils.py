#!/usr/bin/env python3
"""共享工具函数：YAML 标量转义

提供 YAML 标量序列化功能，确保 locator 中的特殊字符正确转义。
"""


def escape_yaml_scalar(value):
    """将字符串格式化为 YAML 安全标量（必要时加引号）。

    规则：
    - 含特殊字符（: # { } [ ] , & * ? | - < > = ! % @ ` " ' \\n）时用单引号包裹
    - 单引号本身用 '' 转义（YAML 单引号字符串的转义方式）
    - 布尔值/null 用单引号包裹（避免被解析为布尔类型）
    - 其他情况不加引号

    Args:
        value: 要序列化的值

    Returns:
        str: YAML 安全标量字符串

    Examples:
        >>> escape_yaml_scalar("xpath=//td[not(contains(@class,'is-hidden'))]")
        "'xpath=//td[not(contains(@class,''is-hidden''))]'"

        >>> escape_yaml_scalar("simple_value")
        'simple_value'

        >>> escape_yaml_scalar("true")
        "'true'"
    """
    if not isinstance(value, str):
        return str(value)

    # 含特殊字符时用单引号包裹，单引号本身用 '' 转义
    if any(c in value for c in (':', '#', '{', '}', '[', ']', ',', '&', '*', '?', '|',
                                 '-', '<', '>', '=', '!', '%', '@', '`', '"', "'", '\n',
                                 '\\')):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    # 布尔值/null 用单引号包裹
    if value in ('true', 'false', 'yes', 'no', 'on', 'off', 'null', 'True', 'False'):
        return f"'{value}'"

    return value
