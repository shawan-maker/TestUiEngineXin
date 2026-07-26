# UIEngine 项目配置模板

> 生成 UI 自动化测试工程前，请填写以下配置。
> 本文件用于 Phase 0 配置确认阶段，所有字段将自动填充到 config.yaml 和脚手架中。

## 基本信息

| 字段 | 值 | 说明 |
|------|-----|------|
| 项目名称 | | 英文小写+连字符，如 `tianshu-manager` |
| 目标系统 URL | | 必须以 http:// 或 https:// 开头 |
| 模块名称 | `common` | 默认 common，多模块用英文小写+连字符 |
| 浏览器类型 | `chromium` | 支持 chromium / firefox / webkit |

## 认证配置

| 字段 | 值 | 说明 |
|------|-----|------|
| 认证方式 | `none` | none / cookie / header / localStorage |
| Cookie | | 认证方式=cookie 时必填 |
| Cookie Domain | | 认证方式=cookie 时必填，如 `.example.com` |
| Token | | 认证方式=header 时必填 |
| localStorage | | 认证方式=localStorage 时必填（JSON 格式） |

## 输入来源

| 字段 | 值 | 说明 |
|------|-----|------|
| 输入类型 | `自然语言` | 自然语言 / Excel / CSV |
| 输入文件路径 | | Excel/CSV 时必填 |

## 示例

```yaml
# config.yaml 示例
project_name: tianshu-manager
target_url: http://100.71.19.25:30101
browser_type: chromium

# Cookie 认证（平铺结构，不使用嵌套 auth:）
cookie: "ud_token=eyJhbG...; session_id=abc123"
cookie_domain: ".example.com"  # 必填，用于 R0.2 验证

# 页面 URL 映射（必填，用于模块发现和 slug 映射）
page_urls:
  question-manage:
    - "http://100.71.19.25:30101/#/question-manage/list"
    - "http://100.71.19.25:30101/#/question-manage/detail"
  work-order:
    - "http://100.71.19.25:30101/#/work-order/list"
  overview:
    - "http://100.71.19.25:30101/#/overview"

# 或 localStorage 认证
# local_storage:
#   token: "eyJhbG..."
#   user_info: '{"name":"张三","id":1}'
```

## Cookie 获取方式

1. 打开目标系统，登录
2. F12 → Network → 选择任意请求 → Headers
3. 找到 Cookie 字段，整串复制粘贴
4. 确保格式为 `name1=value1; name2=value2`

## 验证

配置完成后，运行验证器检查：

```bash
python .claude/skills/generate-ui-test/validators/validate_00_config.py config.yaml
```
