# 代码生成强制规则（39 条）[已归档]

> **⚠️ 本文件已归档。规则已拆分为 `rules/` 目录下 6 个阶段文件：**
> - `rules/00_rule_config.md` (Phase 0)
> - `rules/02_rule_scaffold.md` (Phase 2)
> - `rules/04_rule_probe.md` (Phase 4)
> - `rules/08_rule_scripts.md` (Phase 8)
> - `rules/09_rule_report.md` (Phase 9)
> - `rules/09_rule_execution.md` (Phase 9)
>
> 本文件保留仅供参考对照，新规则以 `rules/` 为准。

> **本文件是生成 case / pages / data / suites 文件时必须逐条遵守的硬性约束。**
> **每一条都来自真实失败案例，违反任何一条都会导致用例运行失败或维护困难。**
>
> 规则按 7 大类组织，编号全局连续：
> - **A. 工程结构规则（1-9）** — 四层架构、变量化、命名规范（最高优先级）
> - **B. 探测与定位器规则（10-17）** — 探测流程、隐藏过滤、来源保证
> - **C. 关键字规则（18-21）** — 引擎可用关键字和参数格式
> - **D. 定位器编写规则（22-26）** — XPath 编写规范
> - **E. 组件操作规则（27-33）** — Element UI 组件操作方法
> - **F. 等待与断言规则（34-38）** — 时序控制与断言策略
> - **G. 执行安全规则（39）** — execute_script 限制

---

## A. 工程结构规则（最高优先级）

> **以下 9 条规则定义项目的四层文件架构。这是整体结构的根基，其他所有规则都是在此架构之上的细节约束。**

### 规则 1：四层目录结构与职责分离

项目由 4 个平级目录组成，每层职责严格分离：

| 层 | 目录 | 职责 | 存什么 | 不存什么 |
|----|------|------|--------|---------|
| 定位器 | `pages/{module}/` | 元素选择器 | XPath 定位器 | 业务数据、步骤 |
| 数据 | `data/{module}/` | 测试参数值 | URL、输入文本、期望值、搜索关键词 | 定位器、步骤 |
| 用例 | `cases/{module}/` | 测试步骤流程 | keyword + 参数引用（`${...}`） | 硬编码定位器、硬编码业务文本 |
| 套件 | `suites/{module}/` | 执行编排 | setup_step + case_refs | 步骤定义、定位器、数据 |

**case 文件中禁止出现的内容**：
- ❌ 硬编码的 XPath 定位器 → 应定义在 pages/ 中，case 通过 `${group.field}` 引用
- ❌ 硬编码的业务文本（项目名、选项文本、搜索关键词、期望值） → 应定义在 data/ 中
- ❌ 任何具体的数据值（除 timeout 等纯数字参数外）

**case 文件中允许硬编码的内容**：
- ✅ timeout 毫秒数（如 `timeout: 15000`）
- ✅ 浏览器类型（如 `browser_type: "chromium"`）
- ✅ 关键字名称（如 `keyword: "click_element"`）
- ✅ 步骤描述文本（如 `desc: "点击查询按钮"`）

### 规则 2：case 全变量引用

case 中的每个步骤参数，凡是涉及定位器或业务数据的，**必须通过 `${group.field}` 引用**，禁止硬编码。

```yaml
# ✅ 正确：全部引用
steps:
  - keyword: "open_url"
    params:
      url: "${delivery_data.target_url}"
  - keyword: "click_element"
    params:
      locator: "${delivery_search.add_btn}"
  - keyword: "fill_value"
    params:
      locator: "${delivery_form.problem_desc_input}"
      value: "${delivery_data.problem_desc_new}"

# ❌ 错误：硬编码了定位器和数据
steps:
  - keyword: "click_element"
    params:
      locator: "xpath=//button[contains(.,'新增')]"           # ← 应在 pages/ 中
  - keyword: "fill_value"
    params:
      value: "测试数据，商品缺货"                    # ← 应在 data/ 中
```

### 规则 3：el-select 三步法全变量化 + 文本一致性

el-select 下拉框的三步操作中，每一步的参数都必须引用变量，禁止硬编码：

| 步骤 | 关键字 | 参数来源 | 禁止硬编码 |
|------|--------|---------|-----------|
| Step 1: 展开 | `click_element` | locator → `${pages_group.select}` | — |
| Step 2: 搜索 | `fill_value` | value → `${data_group.field_search}` | 中文搜索文本 |
| Step 3: 选择 | `click_element` | locator → `${pages_group.field_option}` | x-placement XPath |

**⚠️ 搜索文本与选项文本必须一致**

Step 2 的搜索文本（`data_group.field_search`）和 Step 3 选项 XPath 中的 `contains(.,'...')` 文本**必须来自同一数据源**——即用户用例步骤中指定的目标值。

**禁止**从 probe 的 `select_options` 列表中随意选取一个值填入选项 XPath。probe 的选项列表仅用于验证用户指定的值是否存在，**不能替代用户的原始输入**。

```
用户用例步骤：在"底座方案"下拉框中选择"私有云底座解决方案_2.1.3"
                                        ↓ 唯一数据源
        data/ → base_solution_search: "私有云底座解决方案_2.1.3"
        pages/ → base_solution_option: "...contains(.,'私有云底座解决方案_2.1.3')..."

        ❌ 禁止: pages/ 中使用 probe select_options 中的其他值（如"全栈专属云解决方案_3.1.4"）
```

**自检方法**：对比每个 el-select 的 `data_group.field_search` 值与 `pages_group.field_option` 中 `contains(.,'...')` 的值，两者必须包含相同的核心文本。

**pages/ 中定义选项 XPath**：

```yaml
delivery_options:
  project_name_option: "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start')]//li[contains(.,'2025年天津市眼科医院')])[1]"
  problem_type_defect: "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start')]//li[contains(.,'产品缺陷')])[1]"
```

**data/ 中定义搜索文本**：

```yaml
delivery_data:
  project_name_search: "2025年天津市眼科医院"
  problem_type_search: "产品缺陷"
```

**case/ 中全部引用**：

```yaml
# Step 1: 展开
- keyword: "click_element"
  params:
    locator: "${delivery_form.project_name_select}"
# Step 2: 搜索
- keyword: "fill_value"
  params:
    locator: "${delivery_form.project_name_select} >> xpath=.//input"
    value: "${delivery_data.project_name_search}"
# Step 3: 选择
- keyword: "click_element"
  params:
    locator: "${delivery_options.project_name_option}"
```

**x-placement 值必须来自 probe 结果**（见规则 14），禁止假设固定为 `bottom-start` 或 `top-start`。

### 规则 4：断言统一使用 except_to_be_visible

所有断言（成功提示、字段值验证、数据校验）**统一使用 `except_to_be_visible` + 通用文本定位器**。

**禁止使用**：`except_to_have_text`、`except_to_have_value`、`except_to_have_attribute`。用户无法给出准确的校验项 XPath，统一用可见性断言。

**正确做法**：

```yaml
# pages/ 中定义通用断言定位器（文本可直接硬编码或引用 data/ 变量）
common_elements:
  success_text: "xpath=//*[contains(.,'成功')]"
  error_text: "xpath=//*[contains(.,'失败')]"
  # 也可以引用 data/ 变量（引擎支持嵌套变量解析，最多 3 层）
  dynamic_assert: "xpath=//*[contains(.,'${common_data.success_keyword}')]"

# data/ 中定义断言关键词（可选）
common_data:
  success_keyword: "成功"
  delete_keyword: "删除成功"

# case/ 中统一使用 except_to_be_visible
- keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_text}"
```

**禁止的做法**：

```yaml
# ❌ 禁止 — except_to_have_text
- keyword: "except_to_have_text"
  params:
    locator: "xpath=//div[contains(@class,'el-message--success')]"
    expect_results: "成功"

# ❌ 禁止 — except_to_have_value
- keyword: "except_to_have_value"
  params:
    locator: "${form.name_input}"
    expect_results: "${data.name}"
```

### 规则 5：四层目录模块名一致

`pages/`、`data/`、`cases/`、`suites/` 四个目录下的一级子目录名（模块名）**必须完全对应**。

```
✅ 正确：四个目录的模块名一致
  cases/deliveryIssues/
  suites/deliveryIssues/
  pages/deliveryIssues/
  data/deliveryIssues/

❌ 错误：模块名不一致
  cases/problemManager/        ← 模块名: problemManager
  data/deliveryIssues/         ← 模块名: deliveryIssues（不一致！）
```

**生成新模块时**，必须同时在四个目录下创建对应的子目录。

### 规则 6：case 文件名含执行序号

case 文件命名格式：`{seq:02d}_{case_slug}.yaml`，seq 与 suite 的 case_refs 列表顺序对应。

```
cases/deliveryIssues/
  01_delivery_add.yaml           ← case_refs 中第 1 个
  02_delivery_edit.yaml          ← case_refs 中第 2 个
  03_delivery_progress.yaml      ← case_refs 中第 3 个
  ...
  08_delivery_delete.yaml        ← 删除操作排最后
```

**编号规则**：
- 两位数字，从 01 开始
- **同一模块内编号必须全局连续**，不按来源（Excel/自然语言）分段
- 与 suite 的 case_refs 列表顺序严格对应
- 新增用例时，seq 从当前模块最大值 +1 开始
- 删除用例后不重新编号（避免影响已有报告引用）

**多来源合并到同一模块时的编号**：

当多个 Excel 文件或多次生成任务的用例归入同一模块时，编号必须在模块级别连续递增，**禁止每个来源从 01 重新开始**：

```
# 第一个 Excel 贡献 8 个用例（01-08）
# 第二个 Excel 贡献 8 个用例（09-16，不是重新从 01 开始）
cases/problemManager/
  01_delivery_add.yaml           ← 第一个 Excel
  ...
  08_delivery_delete.yaml
  09_impl_add_problem.yaml       ← 第二个 Excel，从 09 继续
  ...
  16_impl_delete_problem.yaml
```

### 规则 7：变量引用必须使用 ${group.field} 格式

case 文件中引用变量时，**必须使用完整的 `${group.field}` 格式**，不可省略 group 前缀。

```yaml
# ✅ 正确
url: "${work_order_data.new_url}"
locator: "${order_list_page.title_input}"

# ❌ 错误：省略 group 前缀（引擎无法解析）
url: "${new_url}"
value: "${search_title}"
```

**自检方法**：case 中所有 `${...}` 引用，必须与 data/ 和 pages/ 中的 YAML key 层级完全对应。

### 规则 8：用例间数据依赖与 case_refs 排序

当用例间存在数据依赖时，case_refs 顺序必须保证数据流正确。

典型依赖链：**新增 → 编辑 → 详情 → 导出 → 筛选 → 删除**

```yaml
case_refs:
  - case_id: "add-problem"        # 1. 先新增
  - case_id: "edit-problem"       # 2. 编辑刚新增的数据
  - case_id: "fix-solution"       # 3. 修复方案
  - case_id: "problem-detail"     # 4. 查看详情
  - case_id: "export-problem"     # 5. 导出
  - case_id: "advanced-filter"    # 6. 筛选
  - case_id: "delete-problem"     # 7. 最后删除（破坏性操作）
```

**删除用例必须排在最后**，因为它会销毁前序用例创建的数据。

### 规则 9：认证信息集中管理

Cookie 和 localStorage 认证信息**统一在 `config.yaml` 中维护**，suite 通过 `inject_local_storage` 关键字读取。

禁止在 suite 的 setup_step 中硬编码认证信息。`inject_local_storage` 关键字会自动从 `config.cookie` 提取 token 并合并到 `config.local_storage` 的全部字段，一次调用完成注入。

```yaml
# ✅ 正确
- desc: "注入认证信息到 localStorage（从 config.yaml 读取）"
  keyword: "inject_local_storage"

# ❌ 错误：硬编码 token（Cookie 更新时需逐个 suite 修改）
- keyword: "execute_script"
  params:
    script: "localStorage.setItem('ud_token','eyJhbG...')"
```

---

## B. 探测与定位器规则

> **所有定位器必须经过实际页面探测验证。探测是强制步骤，AI 推断仅作为知识库未覆盖时的最后补充。**

### 规则 10：探测是强制步骤

生成任何 pages/cases 文件之前，必须先对目标页面执行 probe。

```
probe_element.py  →  使用知识库模板逐个验证定位器（verified: true 才能写入 pages/）
       ↓
verify_locators.py (Phase 6)  →  运行时验证 + 隐藏过滤补齐 + 容器前缀修正
       ↓
才能生成 pages/*.yaml 和 cases/*.yaml
```

**禁止的做法**：
- ❌ 跳过 probe，直接生成脚本
- ❌ 从其他项目复制定位器
- ❌ 仅根据用例文字描述猜测定位器
- ❌ 在批量生成脚本中硬编码定位器字符串

**每个新模块/新页面都必须单独执行 harvest + probe**，即使同一项目中其他模块已经探测过。

**AI 推断的定位器**：当知识库（`probe_knowledge.json`）未覆盖某种元素类型时，AI 可以作为**最后手段**推断定位器，但必须满足：
1. 推断的定位器必须经过 probe 验证（`verified: true`）后才能写入 pages/
2. 在生成报告中标记来源为 "AI生成"
3. 标记为待用户确认

**操作匹配优先级**（R3.10）：

| 优先级 | 层 | 说明 | 示例 |
|--------|-----|------|------|
| 1 | L3 模块关键字 | 项目专属 + 系统级跨项目 | `check_mail_display(tab_name)` |
| 2 | L1 知识库操作 | 单步元素操作 | `click_element` + tab 定位器 |
| 3 | AI 补充生成 | 以上均未匹配时 | 推断关键字和定位器（需 probe 验证） |

### 规则 11：探测覆盖必须完整

case 中出现的**每一个** locator（包括 L3 关键字内部的）都必须经过 probe 验证。

**探测清单来源**：

1. `cases/**/*.yaml` 中所有步骤的 `params.locator`
2. 提取 `${group.field}` 定位器引用 → 加入探测清单
3. 提取硬编码 locator（`xpath=//...`）→ 加入探测清单
4. 数据引用（`${xxx_data.yyy}`）→ 跳过
5. L3 关键字 → 读取 `_knowledge/{module}.yaml` 的 workflow，提取内部 locator
6. `suites/**/*.yaml` 中 `setup_step` 的 locator 引用
7. 去重后生成最终探测清单

**工具保证**：`verify_locators.py`（Phase 6）按 case 步骤顺序预执行，自动验证所有定位器，补齐隐藏过滤，修正容器前缀。

**验证器**：`validate_04_probe.py` 检查每个 locator 在 `_probe/*.json` 中有对应记录，无记录 → error（阻断 Phase 4）。

### 规则 12：隐藏过滤必须自动处理

所有 XPath 定位器的**最终元素标签**中必须包含隐藏过滤属性：

```xpath
and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])
```

**处理时机**（三道防线，确保不遗漏）：

| 防线 | 处理者 | 说明 |
|------|--------|------|
| 1. 知识库模板 | `probe_knowledge.json` | 所有 XPath 模板已内置隐藏过滤 |
| 2. 探测工具 | `probe_element.py` | 探测输出的 locator 已自动包含过滤 |
| 3. 覆盖补全 | `verify_locators.py` | 预执行时自动补齐缺失的隐藏过滤属性 |

**正确示例**：
```yaml
# ✅ 隐藏过滤在最终元素 span 上
option: "xpath=//li[@role='menuitem']//span[contains(text(),'{option_text}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]"

# ❌ 隐藏过滤只在父元素 li 上（子元素 span 可能被隐藏但未被过滤）
option: "xpath=//li[@role='menuitem' and not(ancestor::*[contains(@class,'is-hidden')])]//span[contains(text(),'{option_text}')]"
```

**例外**：以下定位器不需要隐藏过滤：
- `//*[contains(.,'xx')]` — 通用文本匹配断言定位器
- 含 `@x-placement` 的 option 定位器 — 已有可见性逻辑（面板隐藏时整个 dropdown 不可见）

**text() vs . 的使用场景区分**（知识库已正确处理）：
- `contains(text(),'TEXT')` — 叶子节点（label、span），文本直接在节点上
- `contains(.,'TEXT')` — 容器节点（button、div、li），文本可能在子元素中

### 规则 13：表格列索引必须通过探测确定

表格列的实际顺序不能凭猜测，必须通过探测（probe 或 harvest）确定每列的 `nth` 值。不同页面的列顺序不同，凭猜测会导致断言读到错误列的数据。

### 规则 14：el-select 选项兼容双向面板

el-select 的下拉面板可能出现在输入框上方（`top-start`）或下方（`bottom-start`）。选项 XPath 必须使用 `or` 匹配两种位置：

```yaml
# ✅ 正确 — 匹配双向面板
option: "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start') and not(ancestor::*[contains(@style,'display: none')])]//li[contains(.,'选项文本')])[1]"

# ❌ 错误 — 只匹配下方面板
option: "xpath=//div[@x-placement='bottom-start']//li[contains(.,'选项文本')]"
```

知识库 `multi_step/el-select/select` 已同时匹配两个方向，`x-placement` 值必须来自 probe 结果。

### 规则 15：表格行操作按钮必须通过 probe 确认

禁止假设表格存在固定右侧列。不是所有表格都有固定右侧列。

生成表格行操作按钮前，必须用 probe 确认：
- 如果存在固定列 → 使用知识库 `composite/table-action-button` 模板
- 如果不存在 → 使用表格主体区域路径
- 如果按钮在"更多"下拉菜单中 → 使用知识库 `composite/dropdown-menu` 模板

### 规则 16：高级筛选展开后的字段必须单独 probe

高级筛选展开后，页面布局可能变化。禁止复用搜索区的定位器，必须单独 probe 高级筛选区域内的字段。

### 规则 17：探测失败记录原因

探测全部失败时，必须记录失败原因到生成报告的备注列，包括：
- 匹配到的元素数量
- 错误信息
- 建议修改的文件路径

**多步操作失败**：某步失败 → 记录失败原因，后续步骤标记 skip。生成报告时，多步操作的所有步骤必须完整，缺少任一步标记 error。

**唯一值处理**：探测完成无唯一值时，取第一个匹配（XPath `[1]`）。同名按钮通过容器前缀（R4.38）区分，不使用 `[last()]`。

---

## C. 关键字规则

> **只能使用引擎已注册的关键字，参数名必须精确匹配。**

### 规则 18：禁止发明不存在的关键字

UIEngine 引擎完整的可用关键字清单（86 个函数，中英文双注册）：

**页面操作（15个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `open_url` | `打开页面` | 导航到 URL，自动拼接 host |
| `refresh` | `刷新页面` | 刷新当前页面 |
| `go_back` | `返回上一页` | 浏览器后退 |
| `go_forward` | `前进下一页` | 浏览器前进 |
| `scroll_to_height` | `滚动到高度` | 滚动到指定像素高度 |
| `scroll_to_element` | `滚动到元素` | 滚动直到元素可见 |
| `execute_script` | `执行脚本` | 仅用于非DOM操作/读取数据 |
| `save_page_img` | `保存截图` | 页面截图 |
| `download_file` | `下载文件` | 点击下载 |
| `accept_dialog` | `接受弹窗` | 接受 alert/confirm/prompt |
| `dismiss_dialog` | `关闭弹窗` | 关闭弹窗 |
| `get_page_title` | `获取页面标题` | 返回页面标题 |
| `get_page_url` | `获取页面URL` | 返回当前 URL |
| `set_viewport_size` | `设置窗口大小` | 设置视口宽高 |
| `set_cookie` | `设置Cookie` | 运行时注入 Cookie |

**元素操作（18个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `click_element` | `点击元素` | 点击任意可见元素 |
| `fill_value` | `输入值` | 填写输入框 |
| `type_text` | `输入文本` | 模拟逐键输入 |
| `hover` | `悬停` | 鼠标悬停 |
| `focus_element` | `聚焦元素` | 聚焦元素 |
| `double_click` | `双击` | 双击元素 |
| `long_click` | `长按` | 长按元素 |
| `right_click` | `右键点击` | 右键点击 |
| `drag_and_drop` | `拖拽` | 拖拽元素 |
| `check` | `勾选` | 勾选复选框 |
| `uncheck` | `取消勾选` | 取消勾选 |
| `set_checked` | `设置勾选` | 设置勾选状态 |
| `clear` | `清空输入框` | 清空输入内容 |
| `select_option` | `选择选项` | 原生 select 选择 |
| `select_multiple_options` | `多选下拉` | 原生 select 多选 |
| `click_select_option` | `点击选择选项` | 自定义下拉框选择 |
| `upload_file` | `上传文件` | 文件上传 |
| `highlight_element` | `高亮元素` | 高亮元素（调试用） |

**元素查询（9个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `get_text` | `获取文本` | 获取元素文本 |
| `get_attribute` | `获取属性` | 获取属性值 |
| `get_input_value` | `获取输入值` | 获取 input 的 value |
| `get_element_count` | `获取元素数量` | 匹配元素个数 |
| `is_visible` | `是否可见` | 查询可见性 |
| `is_hidden` | `是否隐藏` | 查询隐藏状态 |
| `is_enabled` | `是否可用` | 查询是否启用 |
| `is_disabled` | `是否不可用` | 查询是否禁用 |
| `is_checked` | `是否选中` | 查询勾选状态 |

**iframe 操作（10个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `frame_fill_value` | `框架输入` | iframe 内填写 |
| `frame_click_element` | `框架点击` | iframe 内点击 |
| `frame_hover` | `框架悬停` | iframe 内悬停 |
| `frame_focus_element` | `框架聚焦` | iframe 内聚焦 |
| `frame_select_option` | `框架选择` | iframe 内下拉选择 |
| `frame_type_value` | `框架输入文本` | iframe 内逐键输入 |
| `frame_long_click_element` | `框架长按` | iframe 内长按 |
| `frame_drag_and_drop` | `框架拖拽` | iframe 内拖拽 |
| `switch_to_frame` | `切换iframe` | 切换到 iframe |
| `switch_to_main_frame` | `切回主页面` | 切回主文档 |

**断言（13个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `except_to_have_text` | `断言有文本` | 文本匹配（支持正则） |
| `except_to_have_value` | `断言有值` | value 属性匹配 |
| `except_to_have_attribute` | `断言有属性` | 属性值匹配 |
| `except_to_be_visible` | `断言可见` | 元素可见 |
| `except_to_be_hidden` | `断言隐藏` | 元素隐藏 |
| `except_to_be_enabled` | `断言可用` | 元素可用 |
| `except_to_be_disabled` | `断言不可用` | 元素禁用 |
| `except_to_be_checked` | `断言选中` | 复选框选中 |
| `except_to_be_empty` | `断言为空` | 元素为空 |
| `except_to_be_editable` | `断言可编辑` | 元素可编辑 |
| `except_to_be_focused` | `断言聚焦` | 元素有焦点 |
| `assert_page_title` | `断言标题` | 页面标题匹配 |
| `assert_page_url` | `断言URL` | 页面 URL 匹配 |

**等待（7个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `wait_for_time` | `强制等待` | 固定等待（毫秒） |
| `wait_for_element` | `等待元素` | 等待元素出现 |
| `wait_for_element_hidden` | `等待元素消失` | 等待元素消失 |
| `wait_for_load` | `等待加载` | 等待页面 load |
| `wait_for_network` | `等待网络` | 等待网络空闲 |
| `wait_for_url` | `等待URL` | 等待 URL 匹配 |
| `set_default_timeout` | `设置超时` | 设置全局超时 |

**鼠标/键盘（6个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `mouse_click` | `鼠标点击` | 坐标点击 |
| `move_mouse` | `移动鼠标` | 坐标移动 |
| `mouse_down` | `鼠标按下` | 按下鼠标键 |
| `mouse_up` | `鼠标抬起` | 释放鼠标键 |
| `press_key` | `按键` | 按单个键 |
| `press_type` | `键盘输入` | 键盘输入字符串 |

**浏览器控制**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `open_browser` | `打开浏览器` | 启动浏览器（suite setup 专用） |

**流程控制（7个）**：

| 英文 | 中文 | 说明 |
|------|------|------|
| `set_variable` | `设置变量` | 将值存入运行时变量池 |
| `set_variable_from_element` | `从元素设置变量` | 从页面元素提取文本/属性/值存入变量 |
| `if_element_visible` | `元素可见则执行` | 可见执行 then_steps，否则执行 else_steps |
| `if_variable` | `变量满足条件则执行` | 变量比较后分支执行 |
| `for_each` | `遍历元素集合` | 对每个匹配元素执行 steps |
| `retry_until` | `重试直到成功` | 重试 steps 直到无错误 |
| `goto_step` | `跳转步骤` | 标记步骤标签 |
| `log` | `日志输出` | 输出日志信息 |

**禁止使用的关键字**（不存在，会导致"关键字不存在"错误）：

| ❌ 禁止 | ✅ 替代 |
|---------|---------|
| `assert_text` | `except_to_be_visible` + 通用文本定位器 |
| `assert_visible` | `except_to_be_visible` |
| `assert_not_visible` | `except_to_be_hidden` |
| `assert_contains` | `except_to_be_visible` + 通用文本定位器 |
| `verify_text` | `except_to_be_visible` + 通用文本定位器 |
| `check_element` | `except_to_be_visible` |
| `click_text` | `click_element` + XPath text 定位 |
| `except_to_have_text` | `except_to_be_visible` + 通用文本定位器 |
| `except_to_have_value` | `except_to_be_visible` |
| `except_to_have_attribute` | `except_to_be_visible` |

### 规则 19：参数名必须精确

**参数名错误会导致用例直接崩溃（`unexpected keyword argument`）。**

#### 19a. 参数名对照表

| 关键字 | 正确参数名 | ❌ 常见错误 |
|--------|-----------|------------|
| `except_to_be_visible` | `locator`（可选 `index`） | ~~`selector`~~ ~~`timeout`~~ ~~`expect_results`~~ |
| `except_to_be_hidden` | `locator`（可选 `index`） | ~~`selector`~~ ~~`timeout`~~ |
| `wait_for_element` | `locator` + `timeout` | ~~`wait_time`~~ |
| `wait_for_element_hidden` | `locator` + `timeout` | ~~`wait_time`~~ |
| `wait_for_time` | `timeout` | ~~`time`~~ ~~`ms`~~ ~~`duration`~~ |
| `click_element` | `locator` | ~~`selector`~~ |
| `fill_value` | `locator` + `value` | ~~`text`~~ ~~`input`~~ |
| `frame_fill_value` | `frame` + `locator` + `value` | ~~`iframe`~~ |
| `execute_script` | `script` | ~~`code`~~ ~~`js`~~ |
| `if_element_visible` | `locator` + **`then_steps`** + `else_steps` | ~~`then`~~ ~~`else`~~ |
| `if_variable` | `name` + `operator` + `compare_value` + **`then_steps`** + `else_steps` | ~~`then`~~ ~~`else`~~ |
| `for_each` | `locator` + **`steps`** + `var_name` | ~~`then_steps`~~ |

#### 19b. ⚠️ 禁止参数清单（写了直接报错）

**所有 `except_to_*` 断言关键字均不接受 `timeout` 参数。** 如需等待元素出现后再断言，用 `wait_for_element` + 断言组合。

| 关键字 | ❌ 禁止参数 | 报错信息 |
|--------|-----------|---------|
| 所有 `except_to_be_*`（8个） | `timeout` | `got an unexpected keyword argument 'timeout'` |
| ~~`except_to_have_*`（3个）~~ | — | **已被规则 4 完全禁止使用** |
| `except_to_be_visible` | `expect_results` | 此关键字只检查可见性，不接受文本匹配参数 |
| `if_element_visible` / `if_variable` | `then` | 参数名是 `then_steps`，非 `then` |
| `get_element_count` / `is_visible` / `is_hidden` | `timeout` | 查询关键字无 timeout 参数 |

**正确写法**：

```yaml
# ✅ 断言不加 timeout
- keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_text}"

# ✅ 需要等待时，先 wait_for_element 再断言
- keyword: "wait_for_element"
  params: {locator: "${common_elements.success_text}", timeout: 10000}
- keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_text}"

# ✅ 条件步骤用 then_steps
- keyword: "if_element_visible"
  params:
    locator: "${list.first_message}"
    then_steps:
      - keyword: "click_element"
        params: {locator: "${list.first_message}"}
```

### 规则 20：每条 case 开头必须环境隔离

```yaml
steps:
  - desc: "访问页面"
    keyword: "open_url"
    params: {url: "${data.url}"}
  - desc: "刷新页面确保环境干净"
    keyword: "refresh"
  - desc: "等待页面加载完成"
    keyword: "wait_for_element_hidden"
    params:
      locator: "${common_elements.loading_mask}"
      timeout: 15000
```

每个用例的前 3 步必须是：访问 URL → 刷新 → 等待加载完成。保证用例执行时页面状态干净。

### 规则 21：富文本编辑器根据 probe 选择关键字

当 probe 返回 `is_rich_text_editor: true` 时，根据 `has_iframe` 和 `has_contenteditable` 字段选择正确的关键字：

| probe 结果 | 关键字 | 说明 |
|-----------|--------|------|
| `has_iframe: true` | `frame_fill_value` | 有 iframe（TinyMCE/UEditor） |
| `has_contenteditable: true`（无 iframe） | `fill_value` | 无 iframe 的富文本编辑器 |
| 仅 `aria-hidden` | `execute_script` | 降级方案 |

---

## D. 定位器编写规则

> **定位器统一使用 XPath 格式，必须精确匹配目标元素。**

### 规则 22：定位器全部来自知识库

所有元素定位器**必须从探针知识库（probe_knowledge.json）中获取**，禁止 AI 自行编写 XPath（规则 10 中的 AI 补充例外）。

**参考文档**：`knowledge/locator-patterns.md` — 16 类已验证的 XPath 定位模式，可直接遍历使用。

知识库覆盖的元素类型：
- **单步**：button、search-button、download-button、menu-item、tab、input、textarea、detail-link
- **多步**：el-select（三步）、el-cascader（多级）、date-picker（日期/时间）
- **组合**：table-action-button、dropdown-menu（更多）、tab-scoped（多tab）

探测时按知识库 patterns 顺序逐个尝试，count==1 即使用。
知识库未覆盖的元素类型，标记 `[待确认]` 由用户补充。

### 规则 23：Playwright >> 链式选择器必须全 XPath

在已有定位器基础上进一步缩小范围时，**必须**用 `>>` 连接，**禁止**用空格。且 `>>` 两侧**都必须是 XPath 格式**：

```yaml
# ✅ 正确 — XPath >> XPath
locator: "${form.project_name_select} >> xpath=.//input"

# ✅ 正确 — 纯 XPath 位置限定（取第一个匹配）
locator: "xpath=(//div[contains(@class,'el-table__body-wrapper')]//tr)[1]"

# ❌ 错误 — 空格被解析为后代选择器
locator: "${form.project_name_select} input"

# ❌ 错误 — >> 右侧使用 CSS 标签选择器
locator: "${form.project_name_select} >> input"

# ❌ 错误 — CSS >> XPath 混合
locator: ".el-select >> xpath=.//input"

# ❌ 错误 — Playwright nth=0（用 XPath [1] 替代）
locator: "${delivery_elements.add_btn} >> nth=0"
```

### 规则 24：用户文本必须用于定位器

当用例步骤中明确提到了要操作的文本内容时，**选项文本必须使用用户原文的完整文本**，禁止截断。

**el-select 选项匹配器**：搜索关键字（Step 2 fill_value）可以用短文本，但选项匹配器（Step 3 contains）必须用完整文本。原因：下拉选项往往存在子串关系，短文本会选中错误选项。

**示例**：
```yaml
# 用户用例：在"底座方案"下拉框中选择"私有云底座解决方案_2.1.3"
# data/ → base_solution_search: "私有云底座解决方案"  (短文本，用于搜索)
# pages/ → base_solution_option: "...contains(.,'私有云底座解决方案_2.1.3')..."  (完整文本，用于匹配)
```

自检方法：对比每个 el-select 的 `data_group.field_search` 值与 `pages_group.field_option` 中 `contains(.,'...')` 的值，后者必须包含用户原文的完整选项文本。

### 规则 25：禁止盲目取第一个

除非用例明确要求"第一条记录"，否则**禁止使用 `[1]` 取第一个匹配元素**。

必须通过以下方式精确定位（按优先级）：
1. **区域作用域限定** — 先定位所属区域，再在区域内找目标
   ```yaml
   # ✅ 在抽屉内找"确定"按钮
   locator: "xpath=//div[contains(@class,'el-drawer')]//button[contains(.,'确定')]"
   ```
2. **文本内容限定** — 用 `contains(text(),'具体文本')` 精确匹配
   ```yaml
   # ✅ 用文本精确匹配
   locator: "xpath=//button[contains(.,'提交审核')]"
   ```
3. **probe 探测确认** — 通过知识库模板获取定位器

**唯一例外**：用例步骤明确写了"第一条记录"、"第一行"等表述时，可使用 `[1]`，但仍需 probe 确认第一行确实是目标元素。

### 规则 26：用户数据保持原样

用例中用户提供的数据（项目名称、选项文本等）**必须保持原样**，不得修改。

---

## E. 组件操作规则

> **Element UI 组件的正确操作方式。每个组件都有特定的 DOM 结构，必须用对应的方法操作。**

### 规则 27：el-select 三步法（固定，无 fallback）

所有 el-select 下拉框统一使用三步法，三步都**必须用 Playwright 关键字，禁止用 execute_script**。

定位器从知识库 `multi_step/el-select` 中获取：
- **expand**：点击展开下拉框
- **fill**：输入搜索关键词
- **select**：选择匹配选项

**el-select 必须始终包含 fill_value 搜索步骤**：fill_value 触发 el-select 的内部过滤机制，确保选项面板正确更新。

**无匹配时的处理**：如果 probe 的选项列表中不包含用户指定的选项文本，仍然按三步法生成，运行时匹配不到会自然报错。禁止用 execute_script 实现"先尝试匹配、失败则选第一个"的条件逻辑。

**抽屉内的 el-select**：也必须用 `click_element` 展开，不得用 execute_script。

### 规则 28：el-cascader 与 el-select 必须区分

"项目类型"等字段可能是 el-cascader（级联选择器），不是 el-select。el-cascader 的 DOM 结构不含 `el-select` 类名，用 el-select 三步法会 Timeout。

**识别方法**：
- harvest 检测到的 `component_type` 为 `cascader`
- 页面 DOM 中有 `el-cascader` 类名而非 `el-select`
- probe 时用 el-select 选择器返回 `verified: false`

**生成前检查**：用例步骤中提到的每个筛选字段，都必须通过 probe 确认实际组件类型。

### 规则 29：el-cascader 级联选择器操作方式

定位器从知识库 `multi_step/el-cascader` 中获取：
- **expand**：点击展开级联面板
- **select-level**：勾选/展开某一级（可重复多次）

逐级点击文字区域展开子级面板，最后点击勾选框完成选择。

### 规则 30：el-date-picker 日期选择器操作方式

定位器从知识库 `multi_step/date-picker` 中获取：
- **expand**：点击展开日期面板
- **select-today**：选择今天（用 `class="today"` 匹配，不是文本）
- **select-now**：选择此刻
- **select-month**：选择当月
- **range-start/range-end**：选择起始/结束时间

**⚠️ "今天"用 `class="today"` 匹配，不是文本**：Element UI 日期选择器的"今天"单元格**不显示"今天"文字**，而是通过 class 属性标识。XPath 写法：`//td[contains(@class,'today')]//div`。

**禁止 AI 推断日期面板定位器**（规则 10）：必须通过知识库或 probe 获取。

### 规则 31：el-dropdown 操作方式

**触发方式**：el-dropdown 的触发是 **click**（不是 hover，也不是 JS mouseenter）。

**触发按钮**：用 `click_element` 直接点击触发文本，禁止用 JS 事件模拟。定位器从知识库 `composite/dropdown-menu` 获取。

**菜单项**：el-dropdown 菜单项（`<li>`）的文本匹配必须用 `contains(text(),'编辑')` 而非 `contains(.,'编辑')`。知识库 `composite/dropdown-menu/click-action` 已正确处理。

### 规则 32：高级筛选连续 el-select 面板冲突处理

高级筛选中连续操作多个 el-select 时，之前展开的 dropdown panel 可能未完全关闭。

**解决方案**：
1. 每次 el-select 操作后额外等待 500ms 确保前面板关闭
2. 选项 XPath 添加隐藏祖先过滤（规则 12 已要求）

**适用场景**：高级筛选中包含 5 个以上 el-select 字段时使用此策略。

### 规则 33：抽屉确认按钮 + 二次确认弹窗

当抽屉内点击"确定"后系统弹出二次确认弹窗时，存在两个"确定"按钮需要依次点击。

两个按钮通过**容器前缀**（R4.38）区分，不使用 `[last()]`：
- 第一次点击：抽屉内的确认按钮（`el-drawer` 前缀）
  ```yaml
  locator: "xpath=//div[contains(@class,'el-drawer')]//button[contains(.,'确') and contains(.,'定')]"
  ```
- 等待 2000ms
- 第二次点击：确认弹窗的确定按钮（`el-dialog` 前缀）
  ```yaml
  locator: "xpath=//div[contains(@class,'el-dialog')]//button[contains(.,'确') and contains(.,'定')]"
  ```

---

## F. 等待与断言规则

> **时序控制的正确方式：区分 UI 动画等待和 API 数据加载等待。**

### 规则 34：弹窗/抽屉用 wait_for_time

```yaml
# ✅ 正确：wait_for_time 给足够时间
- keyword: "wait_for_time"
  params: {timeout: 2000}

# ❌ 错误：wait_for_element 可能匹配隐藏的同名元素
- keyword: "wait_for_element"
  params:
    locator: "xpath=//div[@role='dialog']"
    timeout: 5000
```

### 规则 35：API 驱动的内容加载必须用条件等待

当操作触发后台 API 请求并渲染新内容（表格、列表、checkbox 等），**必须用 `wait_for_element` 等待下一步要操作的目标元素出现**，而不是用 `wait_for_time` 盲等。

**识别特征**：
- 选择项目/方案后，联动加载产品列表、设备列表、人员列表
- 切换 Tab 后，加载对应 Tab 的表格数据
- 选择级联条件后，动态渲染的表单字段或选项
- 任何「选择 A → 后台请求 → 渲染 B」的联动模式

```yaml
# ✅ 正确：等待下一步要操作的目标元素
- keyword: "wait_for_element"
  params:
    locator: "${new_order_page.first_product_checkbox}"
    timeout: 10000

# ❌ 错误：盲等固定时间
- keyword: "wait_for_time"
  params: {timeout: 15000}
```

**超时设置**：API 联动的条件等待统一使用 `timeout: 10000`（10 秒）。

**与规则 34 的关系**：规则 34 要求弹窗/抽屉用 `wait_for_time`（因为 `wait_for_element` 可能匹配隐藏的同名元素）。规则 35 针对的是 API 联动加载的内容元素，不存在"隐藏同名"问题。两条规则互不冲突，按场景分别适用。

### 规则 36：条件性验证（用例含"如果"时）

当用例步骤含条件语句（"如果数量大于0，则..."），生成的验证脚本必须用条件逻辑：有数据才验证，无数据正常通过。禁止无条件 throw（无数据时直接失败）。

### 规则 37：断言定位器定义规范

所有断言定位器在 pages YAML 的 `common_elements` 组中定义，使用通用文本匹配（见规则 4）。

**pages/ 中定义**：

```yaml
common_elements:
  success_text: "xpath=//*[contains(.,'成功')]"
  error_text: "xpath=//*[contains(.,'失败')]"
  # 按操作类型细化（可选）
  export_success: "xpath=//*[contains(.,'导出成功')]"
  delete_success: "xpath=//*[contains(.,'删除成功')]"
```

**case/ 中引用**（统一 except_to_be_visible）：

```yaml
- keyword: "except_to_be_visible"
  params:
    locator: "${common_elements.success_text}"
```

**禁止的做法**：

```yaml
# ❌ 禁止 — except_to_have_text + 特定 class
- keyword: "except_to_have_text"
  params:
    locator: "xpath=//div[contains(@class,'el-message--success')]"
    expect_results: "成功"

# ❌ 禁止 — CSS 定位器
- keyword: "except_to_be_visible"
  params:
    locator: ".el-message--success"
```

### 规则 38：iframe 内富文本内容断言必须用 execute_script

TinyMCE/UEditor 渲染的字段（如"问题描述"、"修复方案"）在 iframe 中，页面级 XPath 无法访问。

当详情视图中某个字段由 TinyMCE 渲染在 iframe 内时：
- `except_to_have_text` + `body` 无法穿透 iframe → 断言失败
- `except_to_have_text` + `//*[contains(.,'文本')]` 同样无法穿透 iframe

**正确做法**：用 `execute_script` 遍历所有 TinyMCE iframe，读取 `contentDocument.body.textContent` 验证。具体实现见 lib/ 中封装的 iframe 断言关键字。

**判断规则**：如果用例中断言的字段在前序用例中通过 `frame_fill_value` 填写，则该字段的断言也必须用 `execute_script` 读取 iframe。

---

## G. 执行安全规则

> **防止静默失败和误操作。**

### 规则 39：原则上不使用 execute_script

**核心原则**：`execute_script` 是**最后手段**，仅在以下关键字都**无法实现**时才允许使用：

| 场景 | 优先使用关键字 | 说明 |
|------|--------------|------|
| 元素点击 | `click_element` | 按钮、链接、tab、卡片、表格行等 |
| 元素输入 | `fill_value` | 输入框、textarea |
| 条件性操作 | `if_element_visible` | 元素存在才执行 |
| 条件性断言 | `if_element_visible` + `then_steps`/`else_steps` | 有数据才验证 |
| 遍历操作 | `for_each` | 对每个匹配元素执行 |
| 重试逻辑 | `retry_until` | 重试直到成功 |
| 数据读取 | `get_text` / `get_attribute` / `get_element_count` | 提取页面数据 |
| 变量传递 | `set_variable` / `set_variable_from_element` | 跨步骤/跨用例传参 |

**只在以下场景允许 execute_script**：
- **iframe 内富文本内容断言**（规则 38）：TinyMCE/UEditor 渲染的字段在 iframe 中，页面级 XPath 无法访问
- **读取 localStorage / 页面全局变量**：无对应关键字时
- **复杂计算逻辑**：非 DOM 操作，如数据转换、条件判断

**绝对禁止用 execute_script 的场景**：
- ❌ 展开 el-select 下拉面板 — 必须用 `click_element`
- ❌ 选择 el-select 选项 — 必须用 `click_element` + xpath
- ❌ 点击任何按钮、链接、卡片、tab — 必须用 `click_element`
- ❌ 填写任何输入框 — 必须用 `fill_value`
- ❌ 勾选复选框 — 必须用 `click_element`
- ❌ 条件性操作 — 必须用 `if_element_visible`
- ❌ 遍历操作 — 必须用 `for_each`

**为什么禁止 JS 点击**：`execute_script` 点击不验证元素是否存在，找不到元素时**不报错、静默失败**，后续步骤全部级联超时，且错误信息指向后续步骤而非真正失败的步骤，极难排查。

**对比示例**：

```yaml
# ❌ 旧写法（execute_script）
- keyword: "execute_script"
  params:
    script: "(function(){ var rows=document.querySelectorAll('xpath=//div[contains(@class,''el-table__body-wrapper'')]//tr[contains(@class,''el-table__row'')]'); if(rows.length===0){return 'skip';} rows[0].click(); ... })()"

# ✅ 新写法（if_element_visible）
- keyword: "if_element_visible"
  params:
    locator: "${list.first_row}"
    then_steps:
      - keyword: "click_element"
        params: {locator: "${list.first_row}"}
```

**⚠️ execute_script JS 语法强制要求：必须使用 IIFE 包裹**

Playwright 的 `Page.evaluate()` 将脚本作为**表达式**求值，**不允许顶层 `return` 语句**。所有 `execute_script` 的 `script` 参数**必须**包裹在立即执行函数表达式（IIFE）中：

```yaml
# ✅ 正确：IIFE 包裹，内部可使用 return
- keyword: "execute_script"
  params:
    script: "(function(){ var el=document.querySelector('[data-testid=\"xxx\"]'); if(!el){return 'skip';} return 'ok'; })()"

# ❌ 错误：裸 return 导致 SyntaxError: Illegal return statement
- keyword: "execute_script"
  params:
    script: "var el=document.querySelector('[data-testid=\"xxx\"]'); if(!el){return 'skip';} return 'ok';"
```

**自检方法**：每个 `execute_script` 的 `script` 值，必须以 `(function(){` 开头、`})()` 结尾。

---

## 自检清单

生成每个文件后，按分类逐条检查：

**A. 工程结构（最高优先级）**：
- [ ] pages/、data/、cases/、suites/ 四层目录结构正确，模块名一致（规则 1、5）
- [ ] case 中所有 locator 引用 pages/，所有 value 引用 data/（规则 2）
- [ ] 断言统一使用 except_to_be_visible + 通用文本定位器（规则 4）
- [ ] el-select 三步法的 Step 2 value 和 Step 3 locator 全部变量化（规则 3）
- [ ] 搜索文本与选项 XPath contains 文本一致，均来自用户用例而非 probe 选项列表（规则 3）
- [ ] 变量引用使用完整的 ${group.field} 格式（规则 7）
- [ ] case_refs 排序符合数据依赖链（规则 8）
- [ ] case 文件名含两位数字序号前缀（规则 6）
- [ ] suite 使用 inject_local_storage，无硬编码认证信息（规则 9）

**B. 探测与定位器**：
- [ ] 所有定位器来自 probe 输出，AI 推断的已标记（规则 10）
- [ ] 每个 locator 都经过 probe 验证，validate_04 无 error（规则 11）
- [ ] 所有 XPath 包含隐藏过滤属性（规则 12）
- [ ] 表格列索引来自 probe/harvest（规则 13）
- [ ] 选项定位器兼容双向面板（bottom-start or top-start）（规则 14）
- [ ] 表格行操作按钮通过 probe 确认（规则 15）
- [ ] 高级筛选展开后字段单独 probe（规则 16）

**C. 关键字**：
- [ ] 所有 keyword 都在可用清单中（规则 18）
- [ ] 断言参数名精确（expect_results 不是 expected）（规则 19）
- [ ] case 开头有 open_url → refresh → wait_for_element_hidden（规则 20）
- [ ] 富文本编辑器根据 probe 选择正确关键字（规则 21）

**D. 定位器编写**：
- [ ] 所有定位器来自知识库（规则 22）
- [ ] 链式操作用 >> 且两侧均为 XPath（规则 23）
- [ ] 用户提供的完整选项文本用于 el-select 匹配（规则 24）
- [ ] 点击定位器精确匹配，无盲目取第一个（规则 25）
- [ ] 用户数据未被修改（规则 26）

**E. 组件操作**：
- [ ] el-select 三步法完整、无 fallback（规则 27）
- [ ] el-cascader 与 el-select 正确区分（规则 28）
- [ ] el-cascader 操作用知识库模板（规则 29）
- [ ] el-date-picker 用 class="today" 匹配（规则 30）
- [ ] el-dropdown 用 click_element，禁止 JS mouseenter（规则 31）
- [ ] 高级筛选连续 el-select 添加面板冲突处理（规则 32）
- [ ] 抽屉确认 + 二次弹窗通过容器前缀（el-drawer/el-dialog）区分（规则 33，R4.38）

**F. 等待与断言**：
- [ ] 弹窗/抽屉用 wait_for_time（规则 34）
- [ ] API 联动加载用 wait_for_element（规则 35）
- [ ] 条件性验证用条件逻辑（规则 36）
- [ ] 提示消息断言用 except_to_be_visible + 通用文本定位器（规则 37）
- [ ] **所有 except_to_* 断言无 timeout 参数**（规则 19b）
- [ ] if_element_visible/if_variable 用 then_steps（非 then）（规则 19a）
- [ ] for_each 用 steps（非 then_steps）（规则 19a）
- [ ] iframe 内富文本断言用 execute_script（规则 38）

**G. 执行安全**：
- [ ] 原则上不使用 execute_script，优先使用流程控制关键字（规则 39）
- [ ] execute_script 必须用 IIFE 包裹（规则 39）

---

## 规则编号映射表（旧 → 新）

供参考：以下为旧编号到新编号的映射，便于对照历史版本。

| 旧编号 | 新编号 | 规则名称 | 变更说明 |
|--------|--------|---------|---------|
| 规则 1 | 规则 1 | 四层目录结构与职责分离 | 不变 |
| 规则 2 | 规则 2 | case 全变量引用 | 不变 |
| 规则 3 | 规则 3 | el-select 三步法全变量化 | 合并旧规则 21（用户文本一致性） |
| 规则 4 | 规则 4 | 断言统一 except_to_be_visible | 重写：禁止 except_to_have_text/value/attribute |
| 规则 5 | 规则 5 | 四层目录模块名一致 | 不变 |
| 规则 6 | 规则 6 | case 文件名含执行序号 | 不变 |
| 规则 7 | 规则 7 | 变量引用 ${group.field} 格式 | 不变 |
| 规则 8 | 规则 8 | 用例间数据依赖排序 | 不变 |
| 规则 9 | 规则 9 | 认证信息集中管理 | 不变 |
| 规则 10 | 规则 10 | 探测是强制步骤 | 重写：AI 推断作为最后补充而非完全禁止；新增 probe_from_pages.py 流程 |
| 规则 10b.1 | 规则 12 | 隐藏过滤 | 合并旧规则 23，增加三道防线说明 |
| 规则 10b.2 | — | 知识库优先探测 | 融入规则 10（探测流程）和规则 22（知识库来源） |
| 规则 10b.3 | 规则 17 | 多步操作完整性 | 合并到探测失败记录 |
| 规则 10b.4 | 规则 17 | 唯一值优先 | 合并到探测失败记录 |
| 规则 10b.5 | 规则 17 | 探测失败记录 | 合并到探测失败记录 |
| 规则 10c | — | 生成报告 | 移至 `rules/09_rule_report.md` |
| 规则 11 | 规则 13 | 表格列索引 | 不变 |
| 规则 12 | 规则 14 | el-select 双向面板 | 不变 |
| 规则 12b | 规则 14 | el-select 双向面板 | 合并入规则 14 |
| 规则 13 | 规则 15 | 表格行操作按钮 | 不变 |
| 规则 14 | 规则 16 | 高级筛选单独 probe | 不变 |
| 规则 15 | 规则 18 | 禁止发明关键字 | 不变 |
| 规则 16 | 规则 19 | 参数名精确 | 不变 |
| 规则 17 | 规则 20 | 环境隔离 | 不变 |
| 规则 18 | 规则 21 | 富文本编辑器 | 不变 |
| 规则 19 | 规则 22 | 定位器来自知识库 | 合并旧规则 12（重复） |
| 规则 20 | 规则 23 | >> 链式选择器 | 全 XPath 示例，禁止 CSS |
| 规则 21 | 规则 24 | 用户文本定位器 | 从规则 3 拆出独立 |
| 规则 22 | 规则 25 | 禁止盲目取第一个 | XPath 示例 |
| 规则 23 | 规则 12 | 隐藏过滤 | 合并入规则 12（与 Section B 统一） |
| 规则 24 | 规则 26 | 用户数据保持原样 | 不变 |
| 规则 26 | 规则 27 | el-select 三步法 | 不变（旧规则 25 已删除） |
| 规则 27 | 规则 28 | el-cascader 区分 | 不变 |
| 规则 28 | 规则 29 | el-cascader 操作 | 不变 |
| 规则 28b | 规则 30 | el-date-picker | 独立编号 |
| 规则 29+30 | 规则 31 | el-dropdown | 合并触发+菜单项 |
| 规则 31 | 规则 32 | 高级筛选面板冲突 | 不变 |
| 规则 32 | 规则 33 | 抽屉确认+二次弹窗 | 改用容器前缀（R4.38），移除 [last()] |
| 规则 33 | 规则 34 | 弹窗/抽屉 wait_for_time | 不变 |
| 规则 34 | 规则 35 | API 条件等待 | 不变 |
| 规则 34b | 规则 37 | 提示消息断言 | 独立编号，增加与规则 4 关系说明 |
| 规则 35 | 规则 36 | 条件性验证 | 不变 |
| 规则 36 | 规则 38 | iframe 富文本断言 | 不变 |
| 规则 37 | 规则 39 | 不使用 execute_script | 不变 |
