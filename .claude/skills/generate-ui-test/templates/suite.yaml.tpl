# ============================================================
# 测试套件文件：{{suite_name}}
# ============================================================
# {{suite_description}}
#
# 文件结构说明：
#   id          - 套件唯一标识
#   name        - 套件名称（用于测试报告显示）
#   setup_step  - 公共前置步骤（所有用例执行前共享，如打开浏览器）
#   case_refs   - 用例引用列表（编排用例执行顺序，不含步骤）
#
# 重要规则：
#   - 套件只编排用例顺序，不定义具体步骤
#   - 步骤在 cases/ 目录的用例文件中定义
#   - case_refs 中的 case_id 必须与 cases/ 中用例的 id 字段匹配
#   - 可在套件级别覆盖 skip（跳过某条用例）或绑定数据集
# ============================================================

id: "{{suite_id}}"
name: "{{suite_name}}"

# 公共前置步骤（所有用例执行前共享）
setup_step:
  # 第一步：打开浏览器
  - desc: "打开浏览器"
    keyword: "open_browser"
    params:
      browser_type: "{{browser_type}}"

  # 第二步：导航到目标域（为 localStorage 注入做准备）
  - desc: "导航到目标域"
    keyword: "open_url"
    params:
      url: "${common_data.target_url}"

  # 第三步：注入认证信息
  #
  # Cookie 认证由引擎自动注入 HTTP 请求，无需在 setup_step 中操作。
  #
  # Cookie + localStorage 双重认证（常见于天枢等系统）：
  # 认证凭据统一在 config.yaml 中维护（cookie + local_storage 字段），
  # suite 通过 inject_local_storage 关键字读取，禁止在 suite 中硬编码。
  # inject_local_storage 会自动：
  #   1. 从 config.cookie 提取 token 字段合并到 localStorage
  #   2. 从 config.local_storage 读取全部用户身份字段批量写入
  # Cookie 更新时只需修改 config.yaml 一处，所有 suite 自动生效。
  #
  # 在 setup_step 中添加：
  #   - desc: "导航到目标域设置 localStorage"
  #     keyword: "open_url"
  #     params:
  #       url: "{target_url}/#{page_path}"
  #   - desc: "注入认证信息到 localStorage（从 config.yaml 读取）"
  #     keyword: "inject_local_storage"
  #   - desc: "刷新使 localStorage 生效"
  #     keyword: "refresh"
  #   - desc: "等待页面加载完成"
  #     keyword: "wait_for_element_hidden"
  #     params:
  #       locator: "xpath=//div[contains(@class,'el-loading-mask')]"
  #       timeout: 15000
  #
  # Header Token 认证（auth.method = header）：
  # - desc: "注入 Token 请求头"
  #   keyword: "inject_token_header"
  #
  # 用户名密码登录（auth.method = none）：无需注入步骤，在用例中编写登录操作即可

# 用例编排：按顺序引用 cases/ 中的用例（通过 case_id 关联）
case_refs:
  - case_id: "{{case_id_1}}"      # 第 1 条用例
  - case_id: "{{case_id_2}}"      # 第 2 条用例
  # - case_id: "{{case_id_3}}"    # 更多用例
  #   skip: true                  # 可在套件级别跳过某条用例
  #   data_binding: "dataset_1"   # 可绑定参数化数据集
