# UIEngine 关键字规范

生成脚本时，用此文件将用户自然语言步骤映射到引擎关键字。

## 匹配策略

1. **精确匹配**：步骤中包含关键字的中文/英文名
2. **常见表述匹配**：匹配下方"常见用户表述"列
3. **动作词推断**：提取动作词，匹配对应类别
4. **无法匹配**：标记 `[待确认]`，列出 2-3 个候选

## 动作词速查

| 用户动作词 | 对应关键字 |
|-----------|-----------|
| 点击、单击、按下 | `click_element` |
| 输入、填写、填入 | `fill_value`（普通输入框）或 `frame_fill_value`（富文本编辑器 TinyMCE/UEditor，pages YAML 有 `_iframe` 伴生定位器时使用） |
| 验证、检查、断言、期望 | `except_to_*` / `assert_*` |
| 等待、暂停、sleep | `wait_for_*` |
| 打开、访问、进入 | `open_url` |
| 选择（下拉） | `select_option`（原生 <select>）或 `click_select_option`（Element UI 等自定义下拉框） |
| 勾选、打勾 | `check` |
| 上传、导入文件 | `upload_file` |
| 下载、导出 | `download_file` |
| 刷新 | `refresh` |
| 返回、后退 | `go_back` |
| 拖拽 | `drag_and_drop` |
| 右键 | `right_click` |
| 双击 | `double_click` |
| 长按 | `long_click` |
| 清空、清除 | `clear` |
| 悬停、移到 | `hover` |

---

## 完整关键字表

### 浏览器与页面

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `open_browser` | - | `browser_type`（必填） | 打开浏览器、启动浏览器、开启Chrome |
| `open_url` | `打开页面` | `url`（必填）, `wait_until='load'`, `timeout=30000` | 打开网页、访问URL、进入页面、跳转到 |
| `refresh` | `刷新页面` | （无参数） | 刷新页面、重新加载、F5 |
| `go_back` | `返回上一页` | （无参数） | 返回上一页、后退 |
| `go_forward` | `前进下一页` | （无参数） | 前进、下一页 |
| `scroll_to_height` | `滚动到高度` | `height`（必填） | 滚动到顶部/底部 |
| `execute_script` | `执行脚本` | `script`（必填）, `*args` | 执行JS |
| `get_page_title` | `获取页面标题` | （无参数） | 获取页面标题 |
| `get_page_url` | `获取页面URL` | （无参数） | 获取当前URL |
| `set_viewport_size` | `设置窗口大小` | `width`（必填）, `height`（必填） | 设置窗口大小 |
| `set_cookie` | `设置Cookie` | `cookie`（必填）, `domain`（可选） | 注入Cookie |
| `download_file` | `下载文件` | `locator`（必填）, `save_path`（可选）, `timeout=30000` | 下载文件、点击导出 |
| `accept_dialog` | `接受弹窗` | `prompt_text`（可选） | 点击确定、确认弹窗 |
| `dismiss_dialog` | `关闭弹窗` | （无参数） | 点击取消、关闭弹窗 |
| `save_page_img` | `保存截图` | `name=''`（可选）, `path=''`（可选） | 页面截图、截图 |

### 元素操作

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `click_element` | `点击元素` | `locator`（必填）, `timeout=3000`, `force=False` | 点击、单击、按下XX按钮 |
| `double_click` | `双击` | `locator`（必填）, `timeout=3000` | 双击XX |
| `fill_value` | `输入值` | `locator`（必填）, `value`（必填）, `timeout=3000` | 输入、填写、在XX中输入XX |
| `type_text` | `输入文本` | `locator`（必填）, `value`（必填）, `timeout=3000` | 逐字输入、模拟输入 |
| `clear` | `清空输入框` | `locator`（必填）, `timeout=3000` | 清空、清除输入 |
| `hover` | `悬停` | `locator`（必填）, `timeout=3000` | 悬停、鼠标移到、hover |
| `focus_element` | `聚焦元素` | `locator`（必填）, `timeout=3000` | 聚焦、获取焦点 |
| `select_option` | `选择选项` | `locator`（必填）, `value`（必填）, `timeout=3000` | 选择下拉框（仅原生 \<select\>） |
| `click_select_option` | `点击选择选项` | `locator`（必填）, `value`（必填）, `timeout=3000` | Element UI/Ant Design 下拉框 |
| `select_multiple_options` | `多选下拉` | `locator`（必填）, `values`（必填）, `timeout=3000` | 多选下拉框 |
| `check` | `勾选` | `locator`（必填）, `timeout=3000` | 勾选、选中复选框、打勾 |
| `uncheck` | `取消勾选` | `locator`（必填）, `timeout=3000` | 取消勾选、去掉勾选 |
| `set_checked` | `设置勾选` | `locator`（必填）, `checked`（必填）, `timeout=3000` | 设置勾选状态 |
| `drag_and_drop` | `拖拽` | `start_selector`（必填）, `end_selector`（必填）, `timeout=3000` | 拖拽、拖动 |
| `upload_file` | `上传文件` | `locator`（必填）, `files`（必填）, `timeout=3000` | 上传文件、选择文件 |
| `scroll_to_element` | `滚动到元素` | `locator`（必填）, `timeout=3000` | 滚动到XX可见 |
| `highlight_element` | `高亮元素` | `locator`（必填）, `timeout=3000` | 高亮元素 |

### 元素查询

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `get_text` | `获取文本` | `locator`（必填）, `timeout=3000` | 获取文本、读取XX内容 |
| `get_attribute` | `获取属性` | `locator`（必填）, `name`（必填）, `target_var`（可选）, `timeout=3000` | 获取属性值、读取aria-controls |
| `get_input_value` | `获取输入值` | `locator`（必填）, `timeout=3000` | 获取输入框的值 |
| `get_element_count` | `获取元素数量` | `locator`（必填）（**⚠️ 无 timeout 参数**） | 获取元素个数 |
| `is_visible` | `是否可见` | `locator`（必填）（**⚠️ 无 timeout 参数**） | 检查是否可见 |
| `is_hidden` | `是否隐藏` | `locator`（必填）（**⚠️ 无 timeout 参数**） | 检查是否隐藏 |
| `is_enabled` | `是否可用` | `locator`（必填）（**⚠️ 无 timeout 参数**） | 检查是否可用 |
| `is_disabled` | `是否不可用` | `locator`（必填）（**⚠️ 无 timeout 参数**） | 检查是否禁用 |
| `is_checked` | `是否选中` | `locator`（必填）（**⚠️ 无 timeout 参数**） | 检查是否勾选 |

### 鼠标键盘

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `mouse_click` | `鼠标点击` | `x`（必填）, `y`（必填）, `button='left'`, `count=1` | 点击坐标 |
| `move_mouse` | `移动鼠标` | `x`（必填）, `y`（必填） | 鼠标移到坐标 |
| `mouse_down` | `鼠标按下` | `button='left'` | 鼠标按下 |
| `mouse_up` | `鼠标抬起` | `button='left'` | 松开鼠标 |
| `long_click` | `长按` | `locator`（必填）, `delay=500`, `timeout=3000` | 长按、按住XX |
| `right_click` | `右键点击` | `locator`（必填）, `timeout=3000` | 右键、右键点击 |
| `press_key` | `按键` | `key`（必填） | 按Enter、按Tab、快捷键 |
| `press_type` | `键盘输入` | `keys`（必填） | 键盘打字 |

### 等待

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `wait_for_time` | `强制等待` | `timeout=3000`（毫秒） | 等待X秒、暂停、sleep |
| `wait_for_load` | `等待加载` | （无参数） | 等待页面加载 |
| `wait_for_network` | `等待网络` | （无参数） | 等待网络请求完成 |
| `wait_for_element` | `等待元素` | `locator`（必填）, `timeout=3000` | 等待XX出现、等XX加载 |
| `wait_for_element_hidden` | `等待元素消失` | `locator`（必填）, `timeout=3000` | 等待XX消失、等loading消失 |
| `wait_for_url` | `等待URL` | `url_pattern`（必填）, `timeout=30000` | 等待页面跳转 |
| `set_default_timeout` | `设置超时` | `timeout=30000`（全局） | 设置超时时间 |

### 断言（⚠️ 所有 except_to_* 均无 timeout 参数）

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `assert_page_title` | `断言标题` | `expect_results`（必填）, `is_equal=1` | 验证标题、标题应为XX |
| `assert_page_url` | `断言URL` | `expect_results`（必填）, `is_equal=1` | 验证URL、跳转到了XX |
| `except_to_have_text` | `断言有文本` | `locator`（必填）, `expect_results`（必填）, `is_equal=1`（**⚠️ 无 timeout**） | 验证文本、页面出现XX、提示XX |
| `except_to_have_value` | `断言有值` | `locator`（必填）, `expect_results`（必填）, `is_equal=1`（**⚠️ 无 timeout**） | 验证输入框的值 |
| `except_to_have_attribute` | `断言有属性` | `locator`（必填）, `name`（必填）, `value`（必填）, `is_equal=1`（**⚠️ 无 timeout**） | 验证属性值 |
| `except_to_be_visible` | `断言可见` | `locator`（必填）, `index=1`（**⚠️ 无 timeout，无 expect_results**） | 验证XX可见、提示出现 |
| `except_to_be_hidden` | `断言隐藏` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证XX隐藏 |
| `except_to_be_enabled` | `断言可用` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证按钮可点击 |
| `except_to_be_disabled` | `断言不可用` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证XX禁用 |
| `except_to_be_checked` | `断言选中` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证已勾选 |
| `except_to_be_empty` | `断言为空` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证为空 |
| `except_to_be_editable` | `断言可编辑` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证可编辑 |
| `except_to_be_focused` | `断言聚焦` | `locator`（必填）, `index=1`（**⚠️ 无 timeout**） | 验证获取焦点 |

### iframe

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `frame_click_element` | `框架点击` | `frame`（必填）, `locator`（必填）, `button='left'`, `count=1`, `timeout=3000` | iframe中点击 |
| `frame_fill_value` | `框架输入` | `frame`（必填）, `locator`（必填）, `value`（必填）, `timeout=3000` | iframe中输入 |
| `frame_hover` | `框架悬停` | `frame`（必填）, `locator`（必填）, `timeout=3000` | iframe中悬停 |
| `frame_focus_element` | `框架聚焦` | `frame`（必填）, `locator`（必填）, `timeout=3000` | iframe中聚焦 |
| `frame_select_option` | `框架选择` | `frame`（必填）, `locator`（必填）, `value`（必填）, `timeout=3000` | iframe中选择 |
| `frame_type_value` | `框架输入文本` | `frame`（必填）, `locator`（必填）, `value`（必填）, `timeout=3000` | iframe中逐字输入 |
| `frame_long_click_element` | `框架长按` | `frame`（必填）, `locator`（必填）, `delay=0.1`（秒） | iframe中长按 |
| `frame_drag_and_drop` | `框架拖拽` | `frame`（必填）, `start_selector`（必填）, `end_selector`（必填）, `timeout=3000` | iframe中拖拽 |
| `switch_to_frame` | `切换iframe` | `frame_locator_str`（必填） | 切换到iframe |
| `switch_to_main_frame` | `切回主页面` | （无参数） | 切回主页面 |
| `frame_except_to_be_visible` | `框架断言可见` | `frame`（必填）, `locator`（必填）, `index=1`, `timeout=5000` | iframe中断言元素可见 |
| `frame_except_to_be_hidden` | `框架断言隐藏` | `frame`（必填）, `locator`（必填）, `index=1`, `timeout=5000` | iframe中断言元素隐藏 |
| `frame_except_to_have_text` | `框架断言文本` | `frame`（必填）, `locator`（必填）, `expect_results`（必填）, `index=1`, `timeout=5000` | iframe中断言包含文本 |

### 流程控制（⚠️ 参数名必须精确）

| 英文 | 中文 | 参数（含默认值） | 常见用户表述 |
|------|------|------|-------------|
| `set_variable` | `设置变量` | `name`（必填）, `value`（必填） | 设置变量、记录值 |
| `set_variable_from_element` | `从元素设置变量` | `locator`（必填）, `target_var`（必填）, `mode='text'`, `timeout=3000` | 从元素提取值存入变量 |
| `if_element_visible` | `元素可见则执行` | `locator`（必填）, **`then_steps`**（非 ~~then~~）, `else_steps`, `timeout=3000` | 如果看到XX就、可见时执行 |
| `if_variable` | `变量满足条件则执行` | `name`（必填）, `operator='eq'`, `compare_value`（必填）, **`then_steps`**（非 ~~then~~）, `else_steps` | 如果变量、当数量大于、条件判断 |
| `for_each` | `遍历元素集合` | `locator`（必填）, `steps`（必填）, `var_name='item'` | 遍历、逐个操作、循环每个 |
| `retry_until` | `重试直到成功` | `steps`（必填）, `max_retry=3`, `interval=1000` | 重试、反复尝试 |
| `goto_step` | `跳转步骤` | `label`（必填） | 跳转到指定步骤标签 |
| `log` | `日志输出` | `message`（必填） | 输出日志、记录信息 |

### 认证注入

由生成工程的 `auth_keywords.py` 提供，非引擎内置关键字。
用于跳过登录页面，直接在 setup_step 中注入认证信息。

| 英文 | 中文 | 参数 | 常见用户表述 |
|------|------|------|-------------|
| `inject_cookies` | `注入Cookie` | `cookies`(可选，默认读 config) | 注入Cookie、设置Cookie、用Cookie登录 |
| `inject_token_header` | `注入Token请求头` | `token`(可选，默认读 config) | 注入Token、设置Authorization、API认证 |
| `inject_local_storage` | `注入LocalStorage` | `key`,`value`,`navigate_url`(均可选) | 写入localStorage、存Token到本地 |

> **用户名密码登录**无需使用认证关键字，保持 `auth.method: none`，在用例步骤中正常编写登录操作即可。

> ⚠️ **Cookie name/value 拆分规则**：从浏览器 DevTools 复制的 Cookie 格式为 `name=value`（如 `ud_token=eyJhbGci...`），
> 必须以第一个 `=` 号为界拆分为 `name`（左边）和 `value`（右边）。
> **错误做法**：`name: "session_id"`, `value: "ud_token=eyJhbGci..."`（整条粘贴到 value）
> **正确做法**：`name: "ud_token"`, `value: "eyJhbGci..."`

---

## ⚠️ 禁止参数清单（生成时逐条检查）

以下参数在 YAML 中写了会直接报错 `got an unexpected keyword argument`，**绝对禁止使用**：

| 关键字 | ❌ 禁止参数 | 原因 | 替代方案 |
|--------|-----------|------|---------|
| **所有 `except_to_be_*`**（8个） | `timeout`, `expect_results` | 只检查可见性/状态，无 timeout 也无文本匹配 | 先 `wait_for_element` + `timeout`，再断言；文本用 `except_to_have_text` |
| **所有 `except_to_have_*`**（3个） | `timeout` | 断言关键字无 timeout | 先 `wait_for_element` + `timeout`，再断言 |
| `assert_page_title` | `timeout` | 页级断言无 timeout | 不加 timeout |
| `assert_page_url` | `timeout` | 页级断言无 timeout | 不加 timeout |
| `if_element_visible` | `then`, `else` | 参数名是 `then_steps` / `else_steps` | 用 `then_steps`, `else_steps` |
| `if_variable` | `then`, `else` | 同上 | 用 `then_steps`, `else_steps` |
| `for_each` | `then_steps`, `then`, `else_steps`, `else` | 参数名是 `steps` | 用 `steps` |
| `get_element_count` | `timeout` | 查询关键字无 timeout | 不加 timeout |
| `is_visible` | `timeout` | 查询关键字无 timeout | 不加 timeout |
| `is_hidden` | `timeout` | 查询关键字无 timeout | 不加 timeout |
| `is_enabled` | `timeout` | 查询关键字无 timeout | 不加 timeout |
| `is_disabled` | `timeout` | 查询关键字无 timeout | 不加 timeout |
| `is_checked` | `timeout` | 查询关键字无 timeout | 不加 timeout |

---

## YAML 用法示例（易错关键字）

### 1. if_element_visible — 参数是 then_steps（不是 then）

```yaml
# ✅ 正确
- desc: "如果有消息则点击查看"
  keyword: "if_element_visible"
  params:
    locator: "${mail_elements.first_message}"
    then_steps:
      - desc: "点击第一条消息"
        keyword: "click_element"
        params:
          locator: "${mail_elements.first_message}"
      - desc: "等待详情加载"
        keyword: "wait_for_time"
        params:
          timeout: 2000
    else_steps:
      - desc: "无消息，跳过"
        keyword: "log"
        params:
          message: "当前tab无消息"

# ❌ 错误 — 'then' 不是有效参数名
- keyword: "if_element_visible"
  params:
    locator: "xxx"
    then:                    # ← 应为 then_steps
      - keyword: "click_element"
```

### 2. except_to_be_visible — 不接受 timeout

```yaml
# ✅ 正确 — 只有 locator
- desc: "断言成功提示可见"
  keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_toast}"

# ❌ 错误 — timeout 不是有效参数
- keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_toast}"
    timeout: 5000            # ← 报错：got an unexpected keyword argument 'timeout'
```

### 3. except_to_have_text — 不接受 timeout

```yaml
# ✅ 正确
- desc: "断言状态文本"
  keyword: "except_to_have_text"
  params:
    locator: "${order_elements.first_row_status}"
    expect_results: "${order_data.status_pending}"

# ❌ 错误
- keyword: "except_to_have_text"
  params:
    locator: "xxx"
    expect_results: "xxx"
    timeout: 5000            # ← 报错
```

### 4. 断言前需要等待时的正确做法

当需要在断言前等待元素出现时，**用 wait_for_element + 断言** 组合，不要在断言中加 timeout：

```yaml
# ✅ 正确 — 先等待，再断言
- desc: "等待成功提示出现"
  keyword: "wait_for_element"
  params:
    locator: "${common_elements.success_toast}"
    timeout: 10000
- desc: "断言成功提示可见"
  keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_toast}"

# ✅ 也正确 — 直接用 wait_for_element 即可（如果只需确认出现）
- desc: "等待成功提示出现"
  keyword: "wait_for_element"
  params:
    locator: "${common_elements.success_toast}"
    timeout: 10000
```

### 5. if_variable — 参数是 then_steps

```yaml
# ✅ 正确
- desc: "获取消息数量"
  keyword: "get_element_count"
  params:
    locator: "${mail_elements.message_list}"
- desc: "如果有消息则点击查看"
  keyword: "if_variable"
  params:
    name: "element_count"
    operator: "gt"
    compare_value: "0"
    then_steps:
      - desc: "点击第一条消息"
        keyword: "click_element"
        params:
          locator: "${mail_elements.first_message}"
```

### 6. for_each — 参数是 steps（不是 then_steps）

```yaml
# ✅ 正确
- desc: "遍历所有项目逐个操作"
  keyword: "for_each"
  params:
    locator: "${list_elements.project_rows}"
    var_name: "row"
    steps:
      - desc: "点击当前行"
        keyword: "click_element"
        params:
          locator: "${row}"

# ❌ 错误 — for_each 的参数是 steps，不是 then_steps
- keyword: "for_each"
  params:
    locator: "xxx"
    then_steps:             # ← 应为 steps
      - keyword: "click_element"
```
