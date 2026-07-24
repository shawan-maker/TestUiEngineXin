# ============================================================
# 环境配置文件
# ============================================================
# 此文件由脚手架自动生成，模板变量来自 Step 1 用户确认。
# 可直接编辑修改配置，无需重新生成工程。
# ============================================================

# 浏览器类型（默认 chromium，支持 firefox / webkit）
browser_type: {{browser_type}}

# 调试模式开关
is_debug: true

# 被测系统根 URL（用例中 /login 等相对路径会拼接为完整 URL）
target_url: "{{target_url}}"

# 单套件最多保留的截图目录数（超出自动清理旧截图）
max_suite_screenshot_dirs: 10

# 全局变量（页面定位器和测试数据会在运行时自动注入）
global_variable: {}

# ============================================================
# 认证配置
# ============================================================
# Cookie 认证：引擎在 open_browser 时自动注入，无需在 setup_step 中手动调用。
# 字段说明：
#   cookie         — Cookie 请求头字符串，格式 "name1=value1; name2=value2"
#   cookie_domain  — Cookie 所属域名（不填则自动从 host 提取）
#
# ⚠️ 获取方式：浏览器 F12 → Network → 任意请求 → Headers → Cookie
#    直接复制整个 Cookie 值粘贴到下方即可。
# ============================================================

{{#if cookie_auth}}
cookie: "{{cookie_string}}"
cookie_domain: "{{cookie_domain}}"
{{/if}}

{{#if local_storage}}
# localStorage 全局配置（suite 通过 inject_local_storage 关键字读取，禁止在 suite 中硬编码）
# Cookie 中的 token 会自动提取并合并到 localStorage，无需重复配置。
local_storage:
{{#each local_storage_items}}
  {{key}}: "{{value}}"
{{/each}}
{{/if}}

# ============================================================
# Header Token 认证（可选，取消注释启用）
# ============================================================
# 如果被测系统使用 Bearer Token 认证，在 setup_step 中使用 inject_token_header 关键字。
# token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
