# ============================================================
# 页面元素定位器文件：{{page_name}}
# ============================================================
# {{page_description}}
#
# 文件结构说明：
#   顶层 key 为页面名称（如 login_page），作为命名空间
#   下级 key 为元素名称，value 为 XPath 定位表达式
#
# 使用方式：
#   在 case 的 params 中通过 ${group.field} 引用
#   例如：locator: "${login_page.username_input}"
#
# ⚠️ 嵌套变量引用（R4.0）：
#   支持最多 3 层嵌套解析（pages → data → 最终值），建议谨慎使用。
#   一层引用（case → pages）：正常使用。
#   两层引用（pages → data）：适用于断言定位器中的可变文本。
#
#   ✅ 正确：project_option: "xpath=//li[contains(.,'${data.project_name}')]"  # 引擎二次解析
#   ✅ 正确：project_option: "xpath=//li[contains(.,'实际项目名')]"  # 硬编码也可以
#
# 命名规范：
#   - 页面名使用 snake_case（如 login_page、dashboard_page）
#   - 元素名使用 snake_case（如 username_input、submit_btn）
#   - 不同页面文件中的同名页面会深度合并（保留各自元素）
# ============================================================

{{page_name}}:
  {{element_1_name}}: "{{element_1_locator}}"    # {{element_1_desc}}
  {{element_2_name}}: "{{element_2_locator}}"    # {{element_2_desc}}
  # ... 更多元素按相同格式添加
  # element_name: "xpath=//..."
