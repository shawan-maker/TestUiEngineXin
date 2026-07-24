# Phase 5: 脚本生成规则

## R4.0 嵌套变量引用（引擎已支持，建议谨慎使用）

UIEngine 的 VariableResolver 支持**最多 3 层嵌套变量解析**：case 中的 `${pages_group.locator_name}` 被替换为 pages YAML 中的字符串值后，如果该字符串中仍包含 `${data_group.field}`，引擎会继续解析。

**现在可以使用嵌套变量**：

```yaml
# pages/ — 定位器可以引用 data/ 变量（引擎会二次解析）
common_elements:
  success_text: "xpath=//*[contains(.,'${common_data.success_keyword}')]"

# data/ — 定义断言关键词
common_data:
  success_keyword: "成功"

# case/ — 引用 pages 定位器，引擎自动解析两层变量
- keyword: except_to_be_visible
  params: {locator: "${common_elements.success_text}"}
# 解析链: ${common_elements.success_text}
#       → xpath=//*[contains(.,'${common_data.success_keyword}')]
#       → xpath=//*[contains(.,'成功')]
```

**建议**：
- 一层引用（case → pages/data）：正常使用
- 两层引用（pages → data）：适用于断言定位器中的可变文本
- 三层以上：支持但不推荐，调试困难

## R4.1 四层目录模块名一致

pages/、data/、cases/、suites/ 四个目录下的模块子目录名必须完全对应。

## R4.2 case 全变量引用

case 中所有 locator 引用 pages/（`${group.field}`），所有 value/expect_results 引用 data/（`${group.field}`）。

**禁止硬编码**：
- ❌ 硬编码 XPath 定位器
- ❌ 硬编码业务文本（项目名、选项文本、期望值）

**允许硬编码**：
- ✅ timeout 毫秒数
- ✅ 浏览器类型
- ✅ 关键字名称
- ✅ 步骤描述文本

## R4.3 el-select 条件分支法全变量化

el-select 下拉框使用条件分支法，每一步的参数都必须引用变量：

| 步骤 | 关键字 | 参数来源 |
|------|--------|---------|
| Step 1 展开 | `click_element` | locator → `${pages_group.field_select}` |
| Step 2 判断 | `if_element_visible` | locator → `${pages_group.field_editable}`，timeout: 500 |
| then: 搜索 | `fill_value` | value → `${data_group.field_search}` |
| then: 选择 | `click_element` | locator → `${pages_group.field_option}` |
| else: 首项 | `click_element` | locator → `${pages_group.field_first_option}` |

> 旧 pages YAML（无 `_editable`/`_first_option` 字段）降级为旧三步法（click + fill + click option），验证器两种模式均接受。

## R4.4 断言统一使用 except_to_be_visible

所有**文本/可见性**断言（成功提示、字段值验证、数据校验）**统一使用 `except_to_be_visible` + 通用文本定位器**。

**例外**：**数量**断言使用 `except_element_count`（断言元素数量 ≥ N）。

**禁止使用**：`except_to_have_text`、`except_to_have_value`、`except_to_have_attribute`。

```yaml
# ✅ 唯一允许的断言方式
- keyword: except_to_be_visible
  params: {locator: "${common_elements.success_text}"}

# ❌ 禁止
- keyword: except_to_have_text
  params: {locator: "...", expect_results: "..."}
```

## R4.5 case 文件名含执行序号

case 文件命名格式：`{seq:02d}_{case_slug}.yaml`

- 两位数字，从 01 开始
- 同一模块内编号必须全局连续
- 与 suite 的 case_refs 列表顺序严格对应
- **多来源合并**：多个 Excel/自然语言来源归入同一模块时，编号从已有最大值 +1 继续，禁止每个来源从 01 重新开始

## R4.6 变量引用必须使用 ${group.field} 格式

case 文件中引用变量时，**必须使用完整的 `${group.field}` 格式**，不可省略 group 前缀。

## R4.7 用例间数据依赖排序

case_refs 顺序必须保证数据流正确：新增 → 编辑 → 详情 → 导出 → 筛选 → 删除。

删除用例必须排在最后（破坏性操作）。

## R4.8 认证信息集中管理

Cookie 和 localStorage 认证信息统一在 `config.yaml` 中维护，suite 通过 `inject_local_storage` 关键字读取。

禁止在 suite 的 setup_step 中硬编码认证信息。

## R4.9 每条 case 开头环境隔离

每个用例的前 3 步必须是：
1. `open_url` → 访问目标页面
2. `refresh` → 刷新页面重置状态
3. `wait_for_element_hidden` → 等待加载完成

## R4.10 原则上不使用 execute_script

`execute_script` 是最后手段，仅在以下关键字都无法实现时才允许使用：
- 元素点击 → `click_element`
- 元素输入 → `fill_value`
- 条件性操作 → `if_element_visible`
- 遍历操作 → `for_each`
- 重试逻辑 → `retry_until`
- 数据读取 → `get_text` / `get_attribute` / `get_element_count`

**execute_script JS 语法强制要求**：必须使用 IIFE 包裹 `(function(){...})()`，禁止裸 return。

---

## 跨阶段通用规则（由 validate_08_scripts.py 检查）

以下规则不限于 Phase 4 生成阶段，适用于所有 pages/cases/suites YAML 文件。

## R4.11 XPath 定位器必须包含隐藏过滤

pages YAML 中所有 XPath 定位器的**最终元素标签**中必须加上隐藏过滤属性：

```xpath
and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])
```

**例外**：`//*[contains(.,'xx')]` 这类通用文本匹配断言定位器不需要。

**来源**：probe_element.py 产出的 locator 已自动包含此过滤。使用 `generate_pages_from_probe.py` 可确保属性不丢失。

## R4.12 el-select 选项定位器双向面板兼容

el-select 的下拉面板可能出现在输入框上方（`top-start`）或下方（`bottom-start`）。选项 XPath 必须使用 `or` 匹配两种位置：

```yaml
# ✅ 正确 — 匹配双向面板
option: "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start') and not(ancestor::*[contains(@style,'display: none')])]//li[contains(.,'选项文本')])[1]"

# ❌ 错误 — 只匹配下方面板
option: "xpath=//div[@x-placement='bottom-start']//li[contains(.,'选项文本')]"
```

## R4.13 关键字注册检查

case 中使用的所有 `keyword` 值必须在引擎注册清单中。禁止发明不存在的关键字。

**常见错误替代**：

| ❌ 禁止 | ✅ 替代 |
|---------|---------|
| `assert_text` | `except_to_be_visible` + 通用文本定位器 |
| `assert_visible` | `except_to_be_visible` |
| `assert_not_visible` | `except_to_be_hidden` |
| `verify_text` | `except_to_be_visible` + 通用文本定位器 |
| `check_element` | `except_to_be_visible` |
| `click_text` | `click_element` + XPath text 定位 |
| `except_to_have_text` | `except_to_be_visible` + 通用文本定位器 |
| `except_to_have_value` | `except_to_be_visible` |
| `except_to_have_attribute` | `except_to_be_visible` |

完整关键字清单见 `knowledge/keyword_spec.md`。

## R4.14 关键字参数名必须精确

参数名错误会导致用例直接崩溃（`unexpected keyword argument`）。

**参数名对照表**

| 关键字 | 正确参数名 | ❌ 常见错误 |
|--------|-----------|------------|
| `except_to_be_visible` | `locator`（可选 `index`） | ~~`selector`~~ ~~`timeout`~~ ~~`expect_results`~~ |
| `wait_for_element` | `locator` + `timeout` | ~~`wait_time`~~ |
| `wait_for_element_hidden` | `locator` + `timeout` | ~~`wait_time`~~ |
| `wait_for_time` | `timeout` | ~~`time`~~ ~~`ms`~~ ~~`duration`~~ |
| `if_element_visible` | `locator` + **`then_steps`** + `else_steps` | ~~`then`~~ ~~`else`~~ |
| `if_variable` | `name` + `operator` + `compare_value` + **`then_steps`** | ~~`then`~~ ~~`else`~~ |
| `for_each` | `locator` + **`steps`** + `var_name` | ~~`then_steps`~~ |

**禁止参数清单（写了直接报错）**

**所有 `except_to_*` 断言关键字均不接受 `timeout` 参数。** 所有 `except_to_be_*` 不接受 `expect_results`。

| 关键字 | ❌ 禁止参数 | 替代方案 |
|--------|-----------|---------|
| 所有 `except_to_be_*`（8个） | `timeout`, `expect_results` | 先 `wait_for_element` + `timeout`，再断言 |
| ~~`except_to_have_*`（3个）~~ | — | **已被 R4.4/R4.22 完全禁止使用** |
| `assert_page_title` / `assert_page_url` | `timeout` | 先 wait 再断言 |
| `if_element_visible` / `if_variable` | `then`, `else` | 用 `then_steps`, `else_steps` |
| `for_each` | `then_steps`, `then`, `else_steps`, `else` | 用 `steps` |
| `get_element_count` / `is_*`（6个） | `timeout` | 无 timeout 参数 |

## R4.15 链式选择器使用 >> 分隔

Playwright 的链式选择器必须使用 `>>` 分隔，禁止用空格（空格会被解析为后代选择器，导致超时）。`>>` 两侧**都必须是 XPath 格式**：

```yaml
# ✅ 正确 — XPath >> XPath
locator: "${form.project_name_select} >> xpath=.//input"

# ✅ 正确 — 纯 XPath 位置限定（取第一个匹配）
locator: "xpath=(//div[contains(@class,'el-table__body-wrapper')]//tr)[1]"

# ❌ 错误 — 空格被解析为后代选择器
locator: "${var} xpath=.//div[contains(@class,'el-select')]"

# ❌ 错误 — >> 右侧使用 CSS 标签选择器
locator: "${var} >> input"

# ❌ 错误 — CSS >> XPath 混合
locator: ".el-select >> xpath=.//input"

# ❌ 错误 — Playwright nth=0（用 XPath [1] 替代）
locator: "${delivery_elements.add_btn} >> nth=0"
```

## R4.16 点击定位器精确匹配

点击操作的定位器必须精确到目标元素，禁止盲目取第一个（`[1]`），除非用例明确要求操作第一条记录。

## R4.17 定位器技术细节正确

检查定位器的技术实现是否正确：
- 固定列容器内不应有多余的表格体包装层
- XPath 中 `contains()` 函数参数格式正确
- XPath 表达式语法合法

## R4.18 data YAML 中 URL 必须是完整 URL

data YAML 中所有 URL 字段**必须是完整 URL**（以 `http://` 或 `https://` 开头），与 `config.yaml` 的 `target_url` 格式一致。

**URL 来源**：从 harvest/probe 结果 JSON 中的 `"url"` 字段直接提取，禁止手动拼接或使用相对路径。

```yaml
# ✅ 正确 — 从 harvest.json 的 url 字段提取的完整 URL
delivery_url: "http://100.71.19.25:30101/#/question-manage/deliveryIssues-list"

# ❌ 错误 — 相对路径，open_url 无法导航
delivery_url: "/deliveryIssues-list"
delivery_url: "#/question-manage/deliveryIssues-list"
```

**原因**：`open_url` 关键字调用 Playwright 的 `page.goto()`，相对路径会触发 `Protocol error: Cannot navigate to invalid URL`。

**与定位器的关系**：URL 和 XPath 定位器一样，都是从 harvest/probe 结果中提取的"技术细节"，case 通过 `${group.field}` 引用，禁止在 case 中硬编码。

## R4.19 pages YAML 定位器禁止包含位置选择后缀

pages YAML 中存储的是**基础定位器**，禁止包含 `>> nth=N` 或 Playwright 位置操作符。如需取第一个匹配元素，直接在 XPath 中使用 `[1]`：

```yaml
# ✅ 正确 — XPath 内嵌位置限定
first_row: 'xpath=(//div[contains(@class,''el-table__body-wrapper'')]//tr)[1]'

# ✅ 正确 — 基础定位器（不取特定位置）
add_btn: 'xpath=//button[contains(.,''新增'')]'

# ❌ 禁止 — Playwright nth=0 后缀
locator: "${delivery_elements.add_btn} >> nth=0"
```

**generate_pages_from_probe.py 已自动剥离**：工具在写入 pages YAML 时会自动移除 probe 结果中的 `>> nth=N` 后缀。

## R4.20 严格遵循用例步骤顺序（⚠️ 关键规则）

case YAML 的步骤顺序**必须与源文件（Excel / 自然语言）的步骤编号严格对应**，禁止 AI 自行归类或调整步骤顺序。

### 禁止行为

- ❌ 将不同 UI 区域的步骤按"区域"重新分组排序（如把抽屉内字段提前到列表页操作）
- ❌ 将"选择项目名称"从抽屉内移到"点击新增"之前，仅因为列表页也有同名字段
- ❌ 将断言步骤集中放到最后（除非源文件本身就是这个顺序）
- ❌ 基于"效率"或"逻辑"自行调整步骤先后关系

### 正确做法

1. **逐步对照**：生成 case 时，逐条对照源文件的步骤编号，按 1→2→3→... 的顺序翻译为 YAML 步骤
2. **保留容器切换信号**：源文件中的"点击新增"/"等待窗口加载"等步骤标志着 UI 区域切换，**必须原样保留在该位置**，后续步骤自动继承新的容器上下文
3. **同名字段按上下文区分**：如果"项目名称"在列表页和抽屉中都出现，根据源文件步骤的上下文决定使用哪个 scope 的定位器：
   - 在"点击新增"之前出现 → 列表页 scope（无抽屉容器前缀）
   - 在"点击新增"之后出现 → 抽屉 scope（带 `//div[contains(@class,'el-drawer')]` 前缀）
4. **环境隔离步骤例外**：R4.9 要求的前 3 步（open_url → refresh → wait_for_element_hidden）是引擎基础设施，**不计入源文件步骤编号**，固定插入到 case 开头

### 自检方法

生成 case 后，逐条核对：

```
源文件步骤 1 → case 步骤 4（+3 环境隔离）  ✓ 顺序一致
源文件步骤 2 → case 步骤 5                  ✓
源文件步骤 3 → case 步骤 6                  ✓
...
```

如果发现任何步骤的位置与源文件顺序不一致，**必须立即修正**。

## R4.21 定位器全部使用 XPath（⚠️ 高优先级规则）

所有定位器**必须统一使用 XPath 格式**。禁止在 pages YAML、case YAML、AI 生成、路径补齐中出现任何 CSS 选择器。

### 禁止的格式

| 禁止类型 | 示例 | 说明 |
|---------|------|------|
| 纯 CSS | `.el-drawer`、`.el-loading-mask`、`button.btn-primary` | 禁止任何 CSS 类选择器 |
| CSS >> XPath 混合 | `.el-drawer >> xpath=.//...` | 前缀是 CSS，后面是 XPath |
| Playwright CSS | `button:has-text('新增')`、`input[placeholder='...']` | Playwright 扩展 CSS 也禁止 |
| Playwright 操作符 | `nth=0`、`nth=1` | 用 XPath `[1]`、`[2]` 替代 |
| `css=` 前缀 | `css=.el-table__row` | 显式 CSS 前缀 |

### 正确的格式

```yaml
# ✅ 容器限定 — 纯 XPath
issue_type_select: 'xpath=//div[contains(@class,''el-drawer'')]//*[contains(text(),''问题类型'')]/following-sibling::*//div[contains(@class,''el-select'')]'

# ✅ 取第一个匹配 — 纯 XPath [1]
first_row: 'xpath=(//div[contains(@class,''el-table__body-wrapper'')]//tr)[1]'

# ✅ 加载遮罩 — 纯 XPath
loading_mask: 'xpath=//div[contains(@class,''el-loading-mask'')]'

# ✅ 按钮 — 纯 XPath
add_btn: 'xpath=//button[contains(.,''新增'')]'
```

### 路径补齐规则

路径补齐（取特定位置的元素）**必须使用 XPath 位置限定**，禁止 Playwright 操作符：

```yaml
# ✅ 正确 — XPath [1]
locator: "xpath=(//div[contains(@class,'el-table__body-wrapper')]//tr)[1]"

# ❌ 禁止 — Playwright nth=0
locator: "${pages_group.field} >> nth=0"

# ❌ 禁止 — CSS >> nth=0
locator: ".el-select >> nth=0"
```

### 容器作用域 XPath 前缀对照表

| 容器类型 | XPath 前缀 |
|---------|------------|
| el-drawer | `//div[contains(@class,'el-drawer')]` |
| el-dialog | `//div[contains(@class,'el-dialog')]` |
| el-form-item | `//div[contains(@class,'el-form-item') and .//*[...]]` |
| el-table | `//div[contains(@class,'el-table')]` |
| el-message-box | `//div[contains(@class,'el-message-box')]` |

### 适用范围

- **probe_element.py** 工具已修改为默认输出纯 XPath
- **AI 手写定位器**时必须使用纯 XPath
- **generate_pages_from_probe.py** 生成的定位器必须是纯 XPath
- **模板文件**中的默认定位器使用纯 XPath
- **知识库文档**中的示例全部使用纯 XPath

### 理由

1. **团队习惯** — 项目组成员习惯使用 XPath，统一降低认知成本
2. **一致性** — 所有定位器格式统一，便于审查和维护
3. **隐藏过滤统一** — 纯 XPath 可以在每层都加上 `not(ancestor::*[contains(@class,'is-hidden')])` 过滤
4. **精确度** — XPath 可以加更多限定条件，CSS 类选择器过于宽泛

## R4.22 断言策略：统一 except_to_be_visible

所有**文本/可见性**断言**统一使用 `except_to_be_visible` + 通用文本定位器**，不要求精确匹配到唯一元素。

**例外**：**数量**断言使用 `except_element_count`（断言记录行数 ≥ N）。

**禁止使用**：`except_to_have_text`、`except_to_have_value`、`except_to_have_attribute`。用户无法给出准确的校验项 XPath，统一用可见性断言。

### 断言定位器模式（详见 `knowledge/locator-patterns.md` 第十四章）

| 断言场景 | 关键字 | 定位器模式 |
|---------|--------|-----------|
| 操作成功提示 | `except_to_be_visible` | `xpath=//*[contains(.,'xx成功')]` |
| 操作失败提示 | `except_to_be_visible` | `xpath=//*[contains(.,'xx失败')]` |
| 检查第一行内容 | `except_to_be_visible` | `xpath=//tbody/tr[1]//*[contains(.,'测试数据')]` |
| 检查某字段的值 | `except_to_be_visible` | `xpath=//*[contains(text(),'字段名')]/following-sibling::*[self::div or self::span]//*[contains(.,'期望值')]` |
| 记录数量 ≥ N | `except_element_count` | `xpath=//tbody/tr[.//*[contains(.,'XX')]]`（自动注入隐藏过滤） |

> **断言定位器是隐藏过滤的例外** — `//*[contains(.,'xx')]` 通用文本匹配不需要加隐藏过滤属性。

### pages YAML 中定义

```yaml
common_elements:
  success_text: "xpath=//*[contains(.,'成功')]"
  error_text: "xpath=//*[contains(.,'失败')]"
  # 按操作类型细化（可选）
  export_success: "xpath=//*[contains(.,'导出成功')]"
  delete_success: "xpath=//*[contains(.,'删除成功')]"
```

**文本处理**：断言定位器中的文本可以直接硬编码在 pages YAML 中，也可以通过嵌套变量引用 data/ 中的值（R4.0 已支持最多 3 层嵌套变量解析）。建议默认硬编码以保持简洁，仅在断言文本需要按用例变化时使用嵌套变量。

### case YAML 中引用

```yaml
# ✅ 正确 — except_to_be_visible + 通用文本定位器
- keyword: except_to_be_visible
  params: {locator: '${common_elements.success_text}'}

# ❌ 禁止 — except_to_have_text + 特定 class 定位器
- keyword: except_to_have_text
  params: {locator: '${common_elements.success_toast}', expect_results: '成功'}
```

### 禁止的做法

| 禁止 | 原因 |
|------|------|
| `except_to_have_text` + `.el-message--success` | 依赖特定组件 class，不同页面可能不一致 |
| `except_to_have_text` + 精确文本匹配 | 只需验证存在，不需要精确到唯一元素 |
| `assert_text` / `assert_visible` | 不存在的关键字（R4.13） |

### 理由

1. `except_to_be_visible` 只检查定位器匹配的元素中**至少有一个可见**，不要求唯一匹配
2. `//*[contains(.,'成功')]` 能捕获任何包含目标文本的可见元素（toast、弹窗文字、页面内嵌提示等）
3. 不同页面可能使用不同的提示组件（Element UI Message、Notification、自定义提示），特定 class 不可靠

## R4.23 el-select 条件分支法中 fill_value 在 then_steps 内不可省略

el-select 条件分支法中，`then_steps`（可编辑分支）的 fill_value 步骤**不可省略**：fill_value 触发 el-select 的内部过滤机制，确保选项面板正确更新。

`else_steps`（readonly 分支）不需要 fill_value，直接点击 `_first_option`。

**禁止**：
- ❌ 用 execute_script 展开 el-select（必须用 click_element）
- ❌ then_steps 中跳过 fill_value 直接 click 选项（选项面板可能未更新）
- ❌ 抽屉内的 el-select 用 JS 事件触发
- ❌ 去掉 if_element_visible 条件分支，直接写死三步或两步（运行时状态可能变化）

## R4.24 pages YAML 必须通过工具生成或手动标记

pages YAML 文件头部必须包含以下标记之一，表明定位器来源可靠：
1. `generate_pages_from_probe.py` — 工具自动生成
2. `# [手动]` — 手动添加的定位器（需经 probe --verify 验证）

未标记的 pages YAML 会被校验器报告为 error。

> **补充说明**：el-cascader 与 el-select 的 DOM 结构不同（el-cascader 不含 `el-select` 类名），生成前必须通过 probe 确认组件类型，用错三步法会 Timeout。

## R4.25 el-date-picker "今天"用 class 匹配

Element UI 日期选择器的"今天"单元格**不显示"今天"文字**，通过 class 属性标识。

```yaml
# ✅ 正确 — class="today" 匹配
select_today: "xpath=//td[contains(@class,'today')]//div"

# ❌ 错误 — 文本匹配（"今天"文字不可见）
select_today: "xpath=//td[contains(.,'今天')]"
```

## R4.26 el-select 条件分支法完整性

case 中 `click_element` 操作 el-select 的 `_select` 字段时，后续必须是完整的条件分支结构：
1. `if_element_visible`（检查 `_editable`）
   - `then_steps`: `fill_value`（搜索，用 `_input`）+ `click_element`（选选项，用 `_option`）
   - `else_steps`: `click_element`（选第一项，用 `_first_option`）

缺少任何分支或步骤都会被校验器报告为 error。旧 pages YAML（无 `_editable`/`_first_option`）降级为旧三步法，校验器两种模式均接受。

> **补充说明**：el-dropdown 触发方式为 click（禁止 hover/JS mouseenter），菜单项用 `contains(text(),'编辑')` 匹配。

## R4.27 同名 label 跨容器冲突检测

pages YAML 中，如果同一个中文 label（如"项目名称"）同时出现在有容器前缀和无容器前缀的定位器中，所有同名定位器**必须统一加容器前缀**。

**典型场景**：搜索区和抽屉内都有"项目名称"下拉框 → 所有"项目名称"定位器都必须加容器前缀，否则 Playwright strict mode violation。

> **补充说明**：抽屉内点击"确定"后弹出二次确认时，两个"确定"按钮通过容器前缀区分：第一次用 `el-drawer` 前缀限定抽屉内，第二次用 `el-dialog` 前缀限定确认弹窗（R4.38）。两次之间需 `wait_for_time(2000)`。

## R4.28 通用操作按钮必须有容器前缀

`confirm_btn`、`cancel_btn`、`save_btn`、`submit_btn`、`close_btn` 等通用操作按钮，在非 `common_elements` 组中**必须有容器前缀**（`el-drawer`/`el-dialog`/`el-message-box`）。

`common_elements` 组中的全局通用按钮免检。模块级 group 中的同名按钮如果无容器前缀，会导致 strict mode violation。

> **补充说明**：等待策略需区分 UI 动画（`wait_for_time` 2000ms）和 API 加载（`check_page_loaded` 自动等待）。弹窗/抽屉打开用 `wait_for_time`，任何按钮操作后由后窥逻辑自动插入 `check_page_loaded`（下一步为等待/断言/L3 时跳过）。

## R4.29 条件性验证（用例含"如果"时）

用例步骤含条件语句（"如果数量大于0，则..."）时，必须用 `if_element_visible` + `then_steps`/`else_steps` 实现条件逻辑。禁止无条件 throw。

## R4.30 iframe 内富文本断言用 execute_script

如果用例中某字段通过 `frame_fill_value` 填写（TinyMCE/UEditor），该字段的断言**必须用 `execute_script`** 读取 iframe 内 `contentDocument.body.textContent`。页面级 XPath 无法穿透 iframe。

## R4.31 case/suite 中变量引用存在性检查

case/suite 中所有 `${group.field}` 引用必须在 pages/data YAML 中存在对应定义。

**检查范围**：
- `params.locator` 中的变量引用
- `params.value` 中的变量引用
- `params.expect_results` 中的变量引用

**跳过**：
- 纯数据变量（如 `${data.xxx}`、`${env.xxx}`、`${config.xxx}`）

**常见错误**：
- case 引用了 `${work_order_new_elements.submit_btn}`，但 pages YAML 中字段名是 `create_submit_btn`
- 运行时错误：`Unsupported token "{" while parsing css selector`（变量未解析）

## R4.32 el-select _select 字段必须指向 input 而非 div 容器

el-select 条件分支法的 click（_select）、fill（_input）、可编辑判断（_editable）都操作 `input[@class='el-input__inner']` 元素。

**禁止**：`_select` 字段指向 `div[contains(@class,'el-select')]` 容器 div（click 会超时，容器无 click handler）

**正确**：`_select` 字段指向 `input[@class='el-input__inner']`（与 `_input` 字段相同）

```yaml
# ✅ 正确：_select 和 _input 都指向 input
project_name_select: "xpath=//*[contains(text(),'项目名称')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' ...]"
project_name_input: "xpath=//*[contains(text(),'项目名称')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' ...]"

# ❌ 错误：_select 指向 div 容器
project_name_select: "xpath=//*[contains(text(),'项目名称')]/following-sibling::div//div[contains(@class,'el-select') ...]"
```

**工具自动处理**：`generate_pages_from_probe.py` 会自动补全 `_select` 伴生字段（当 `xxx_input` 指向 el-select input 时）。

## R4.33 容器上下文引用检查

打开容器（抽屉/对话框）后，case 步骤引用的 group 必须在容器内定义。

**场景**：
1. click `${question_search_elements.add_btn}` → 打开抽屉
2. click `${question_search_elements.project_name_select}` → ❌ 错误！搜索区 group 无抽屉前缀
3. 应改为 `${impl_drawer_elements.project_name_select}` → ✅ 正确

**检查逻辑**：
- 检测 `click_element` 步骤引用了 `add_btn`/`edit_btn` 等打开容器的按钮
- 后续步骤如果引用了 `*_search_elements` group 的字段
- 且该字段在容器 group（`*_drawer_elements`/`*_dialog_elements`）中也有同名定义
- 则报错，建议改用容器 group 版本

## R4.34 禁止 text()='xxx' 精确等号匹配

XPath 中禁止使用 `text()='xxx'`（精确等号），根据场景区分使用方式：

| 场景 | 正确写法 | 示例 |
|------|---------|------|
| **断言**（`except_to_be_visible`） | `contains(.,'xxx')` | `//*[contains(.,'正常项目')]` |
| **操作**（click/fill 精确定位） | `contains(text(),'xxx')` | `//span[contains(text(),'正常项目')]` |
| **禁止** | `text()='xxx'` | ❌ `//span[text()='正常项目']` |

**原因**：`text()='xxx'` 对空白字符敏感 — 子元素、换行、前后空格都会导致不匹配。`contains(.,'xxx')` 匹配元素及其所有后代文本，更健壮。

## R4.35 富文本编辑器（TinyMCE/UEditor）必须使用 frame_fill_value

当 pages YAML 头部注释包含 `[TinyMCE]` 标记，或字段有 `_iframe` + `_body` 伴生定位器时，该字段的输入必须使用 `frame_fill_value`，禁止使用 `fill_value`。

**识别方式**：pages YAML 头部注释：
```yaml
# [TinyMCE] 以下字段为富文本编辑器（iframe），case 中必须使用 frame_fill_value：
#   - impl_drawer_elements.fix_plan
```

**正确用法**：
```yaml
- desc: "在修复方案文本框中输入"
  keyword: "frame_fill_value"
  params:
    frame: "${impl_drawer_elements.fix_plan_iframe}"
    locator: "${impl_drawer_elements.fix_plan_body}"
    value: "${question_data.fix_plan_text}"
```

**禁止**：
```yaml
# ❌ fill_value 无法操作 iframe 内的隐藏 textarea
- keyword: "fill_value"
  params: {locator: "${impl_drawer_elements.fix_plan_textarea}", value: "..."}
```

**配套定位器命名规则**：
- `{field}_iframe`：iframe 元素的 XPath
- `{field}_body`：iframe 内 `//body` 的 XPath
- `{field}_textarea`：原始 textarea（被隐藏，仅作参考）

**断言方式**：iframe 内字段的断言必须使用 `frame_except_to_be_visible`，页面级 `except_to_be_visible` 无法穿透 iframe。

## R4.36 按钮定位器必须使用 button 标签（优先级 2-1-3）

按钮类字段（`_btn`、`_button`、`confirm`、`cancel` 等）的定位器必须遵循以下优先级：

| 优先级 | 模式 | 示例 | 适用场景 |
|--------|------|------|---------|
| 1（最优先） | button + 完整文本 | `//button[contains(.,'里程碑')]` | 默认选择 |
| 2（次选） | 拆字 contains | `//button[contains(.,'里') and contains(.,'程') and contains(.,'碑')]` | 空格变异兼容 |
| 3（禁止） | 通用 text() | `//*[contains(text(),'里程碑')]` | 按钮禁止使用 |

**为什么拆字**：`contains(text(),'里程碑')` 是子串匹配，会同时命中"影响里程碑"等元素，导致 strict mode violation。拆字后每个 `contains(.,'X')` 独立匹配，精确度更高，且能处理按钮文本中的空格（如"确 定"）。

**正确**（容器前缀根据实际 UI 选择 el-drawer 或 el-dialog，参见 R4.38）：
```yaml
# ✅ 抽屉内的确认按钮
confirm_btn: "xpath=//div[contains(@class,'el-drawer')]//button[contains(.,'确') and contains(.,'定') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]"
# ✅ 对话框内的确认按钮
confirm_btn: "xpath=//div[contains(@class,'el-dialog')]//button[contains(.,'确') and contains(.,'定') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]"
```

**禁止**：
```yaml
# ❌ 模式 3 用于按钮（子串误匹配）
confirm_btn: "xpath=//*[contains(text(),'确定')]"
```

**校验器**：`validate_08_scripts.py` 的 R4.36 自动检测：
- 按钮字段使用 `contains(text(),'...')` → **error**（必须转模式 1）
- 按钮字段使用 `//button[contains(.,'完整文本')]` 且文本 > 1 字 → **warning**（建议拆字）
- 生成工具 `generate_pages_from_probe.py` 自动转换按钮定位器为拆字模式

## R4.37 case ID 全局唯一（多模块必须含模块标识）

case YAML 的 `id` 字段在**整个项目中必须全局唯一**。多模块项目中，不同模块的 case 如果共用 `case-01` 这样的 ID，`run.py` 的 `load_cases()` 会用 `id` 做字典 key，导致后加载的覆盖先加载的。

**格式要求**（两种均可，推荐 slug 格式）：

| 格式 | 示例 | 生成方式 |
|------|------|---------|
| **slug 格式**（推荐） | `mail_readReminder` | `--slug-file` 参数，AI 生成英文标识 |
| **序号格式**（fallback） | `mail-case-01` | 无 slug 时自动生成 |

**slug 命名规则**：`{module}_{action}`
- `module`：模块英文名，小驼峰，最多 2 词（如 `mail`、`workOrder`）
- `action`：用例动作英文名，小驼峰，最多 2 词（如 `readReminder`、`createOrder`）
- 完整示例：`mail_readReminder`、`project_addMember`、`workOrder_checkApproval`

```yaml
# ✅ 正确 — slug 格式（推荐）
id: mail_readReminder
id: project_addMember
id: workOrder_checkApproval

# ✅ 正确 — 序号格式（fallback）
id: mail-case-01
id: work-order-case-03
id: project-manage-case-09

# ❌ 错误 — 无模块标识，多模块时冲突
id: case-01
id: case-02
```

**影响范围**：`run.py` 的 `build_master_suite()` 用 `seen_ids` 去重，ID 冲突时只有第一个被加入 master suite，其余静默丢失。

**工具自动处理**：`generate_cases_from_excel.py` 的 `--slug-file` 参数接收 AI 生成的 slug 映射 JSON，自动确保 ID 与文件名一致。无 slug 时自动添加 `--module` 参数值作为前缀。

**手写 case 时**：必须手动添加模块标识（slug 或前缀）。suite 的 `case_refs` 中 `case_id` 必须与 case 的 `id` 完全匹配。

## R4.38 容器类型判定规则（el-drawer vs el-dialog）

容器前缀必须与 Element UI 实际渲染的容器组件一致，**不能凭经验猜测**。同一 group 内所有带容器前缀的元素必须使用相同的容器类型。

**Element UI 容器类型对照**：

| UI 表现 | Element UI 组件 | XPath 容器前缀 |
|---------|----------------|---------------|
| 从右侧/左侧滑出的面板 | el-drawer | `//div[contains(@class,'el-drawer')]` |
| 居中弹出的对话框 | el-dialog | `//div[contains(@class,'el-dialog')]` |

**典型场景**：

| 场景 | 容器类型 | 示例 |
|------|---------|------|
| 新增/编辑表单（点击按钮后从右侧滑出） | `el-drawer` | 项目管理新增、问题管理编辑 |
| 高级筛选面板（从顶部/侧面滑出） | `el-drawer` | 工单高级筛选 |
| 操作确认弹窗（点击提交后居中弹出） | `el-dialog` | 产品清单确认、提交确认 |
| 删除确认弹窗（居中弹出小窗口） | `el-dialog` | 删除确认 |

**判定方法**（优先级从高到低）：

1. **probe 结果**：探测时容器已打开，`container_type` 字段即为正确答案
2. **harvest 结果**：`detected_patterns.container_type` 字段
3. **group 名推断**：`*_drawer_elements` → drawer，`*_dialog_elements` → dialog
4. **Excel 描述推断**："打开抽屉"/"侧边栏" → drawer，"弹窗"/"对话框"/"确认框" → dialog
5. **同 group 已有元素**：参考同组其他元素的容器类型保持一致

**禁止**：不确定时默认使用 `el-dialog`。必须通过上述方法确认。

**校验器**：`validate_08_scripts.py` 的 R4.38 自动检测同 group 内 drawer/dialog 混用 → **warning**（先后弹出不同容器属正常，同一容器元素应统一）。

