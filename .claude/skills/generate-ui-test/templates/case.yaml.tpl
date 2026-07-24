# ============================================================
# 测试用例文件：{{case_name}}
# ============================================================
# {{case_description}}
#
# 文件结构说明：
#   id    - 用例唯一标识（格式: {module}_{action}，如 mail_readReminder）
#   name  - 用例名称（中文，用于测试报告显示）
#   skip  - 是否跳过此用例（true/false，套件级别也可覆盖）
#   steps - 用例步骤列表，每个步骤包含：
#     desc    - 步骤的自然语言描述（必填，用于日志和报告）
#     keyword - 引擎关键字（AI 从自然语言映射，如 click_element）
#     params  - 关键字参数（如 locator、value 等，按关键字定义填写）
#
# 注意：
#   - 每个 step 必须有 desc 字段
#   - params 中使用 ${group.field} 引用全局变量（页面定位器、测试数据）
#   - 结构相似的用例应使用参数化（见 data/ 目录）
#   - 每条 case 开头使用 open_url + refresh + wait 三步组合确保环境干净：
#     1. open_url → 访问目标页面
#     2. refresh → 刷新页面重置所有残留状态（抽屉/对话框/遮罩层）
#     3. wait_for_element_hidden → 等待加载完成
#     不要使用 execute_script 隐藏元素，refresh 更可靠
#
# ⚠️ 关键字参数常见错误（会导致运行时崩溃）：
#   - if_element_visible / if_variable 的参数是 then_steps（不是 then）
#   - for_each 的参数是 steps（不是 then_steps）
#   - 所有 except_to_* 断言关键字不接受 timeout 参数
#     需要等待时，前置 wait_for_element + timeout，再跟断言
# ============================================================

id: "{{case_id}}"
name: "{{case_name}}"
skip: false
steps:
  # 步骤 1：{{step_1_desc}}
  - desc: "{{step_1_desc}}"
    keyword: "{{step_1_keyword}}"
    params:
      {{step_1_params}}
  # ... 更多步骤按相同格式添加
  # - desc: "步骤描述"
  #   keyword: "引擎关键字"
  #   params:
  #     参数名: "参数值"
