# Phase 0: 配置确认规则

## R0.1 URL 格式校验

目标系统 URL 必须以 `http://` 或 `https://` 开头，且包含有效域名或 IP 地址。

**正确示例**：
- `http://100.71.19.25:30101`
- `https://example.com`

**错误示例**：
- `100.71.19.25:30101`（缺少协议）
- `http://`（缺少域名）

## R0.2 认证方式有效性

认证方式必须为以下之一：`none` / `cookie` / `header` / `localStorage`

| 认证方式 | 必填字段 |
|---------|---------|
| none | 无 |
| cookie | cookie, cookie_domain |
| header | token |
| localStorage | local_storage |

## R0.3 Cookie 格式校验

Cookie 值必须符合 `name=value; name2=value2` 格式。

**正确示例**：`ud_token=eyJhbGci...; session_id=abc123`

**错误示例**：`eyJhbGci...`（缺少 name= 前缀）

## R0.4 文件路径存在性

Excel/CSV 输入文件路径必须存在且可读。

## R0.5 模块名命名规范

模块名必须使用小写字母和连字符，如 `problem-manage`、`instation-mail`。

**禁止**：
- 大写字母：`ProblemManage`
- 下划线：`problem_manage`
- 中文字符：`问题管理`
- 特殊字符：`problem@manage`
