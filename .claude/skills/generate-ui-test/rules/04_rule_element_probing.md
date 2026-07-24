# Phase 3: 元素探测规则

## R3.1 定位器全部来自知识库

所有元素定位器**必须从探针知识库（probe_knowledge.json）中获取**，禁止 AI 自行编写 XPath。

**参考文档**：`knowledge/locator-patterns.md` — 16 类已验证的 XPath 定位模式，可直接遍历使用，只需修改对应的数据/文本/按钮名称。

知识库路径：`tools/probe_knowledge.json`

| 元素类型 | 知识库路径 | 参考文档章节 |
|---------|-----------|-------------|
| 按钮 | `single_step/button` | 七、普通按钮 |
| 搜索按钮 | `single_step/search-button` | 六、搜索按钮 |
| 下载导出按钮 | `single_step/download-button` | 五、下载导出按钮 |
| 输入框 | `single_step/input-generic` | 一、各种输入框 |
| 文本框 | `single_step/textarea-generic` | 一、各种输入框 |
| Tab 标签 | `single_step/tab` | 十五、多 tab |
| 侧边目录 | `single_step/menu-item` | 十一、侧边目录 |
| 批量全选 | `single_step/checkbox-all` | 十三、批量全选 |
| 详情页链接 | `single_step/detail-link` | 十二、进入详情页 |
| el-select | `multi_step/el-select` | 二、el-select 条件分支法 |
| el-cascader | `multi_step/el-cascader` | 三、级联选择器 |
| date-picker | `multi_step/date-picker` | 四、时间选择框 |
| 表格行按钮 | `composite/table-action-button` | 九、列表右侧按钮 |
| 更多菜单 | `composite/dropdown-menu` | 十、更多展开按钮 |
| 多 tab 作用域（按钮） | `composite/tab-scoped` → `scoped-button` | 十五、多 tab |
| 多 tab 作用域（输入框） | `composite/tab-scoped` → `scoped-input` | 十五、多 tab |
| 多 tab 作用域（详情链接） | `composite/tab-scoped` → `scoped-detail-link` | 十五、多 tab |
| 多 tab 作用域（目录） | `composite/tab-scoped` → `scoped-menu-item` | 十五、多 tab |
| 成功/失败提示 | `assertion/success-toast` + `assertion/error-toast` | 十四、断言 |
| 第一行内容 | `assertion/first-row-content` | 十四、断言 |
| 字段值断言 | `assertion/field-value` + `single_step/field-assertion` | 十四、断言 |

## R3.2 探测流程

1. 加载知识库
2. 按 patterns 顺序逐个尝试
3. count==1 → verified=true，记录 success_count
4. 全部失败 → 使用 fallback 策略（标记为不可信）

## R3.3 隐藏过滤自动处理

知识库所有 XPath 已内置隐藏过滤，探测时无需手动添加：
`not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])`

## R3.4 多步操作完整性

多步操作（el-select 三步、级联多级、日期选择）必须按 steps 顺序探测：
- 某步失败 → 记录失败原因，后续步骤标记 skip
- 生成报告时，多步操作的所有步骤必须完整

## R3.5 唯一值优先

探测完成无唯一值时：
- 普通元素取第一个匹配（XPath `[1]`）

## R3.6 探测失败记录原因

探测全部失败时，必须记录：
- 匹配到的元素数量
- 错误信息
- 建议修改的文件路径

## R3.7 自学习机制

用户纠正的正确 XPath 自动学习并合并到知识库：
- 相同模板去重累加 success_count
- 新模板插入首位（最高优先级）
- 只学习 verified=true 的路径

## R3.8 知识库路径

- 全局默认：`tools/probe_knowledge.json`
- 项目级：`{project}/_probe/knowledge.json`
- 学习更新：`python learn_probe.py {knowledge_path} {type} {name} {label} {xpath} {source}`

## R3.9 多 Tab 页面必须使用作用域定位

当页面存在 2 个及以上 `@role="tab"` 元素时，判定为多 Tab 页面，**必须**遵循三步流程：

### 三步流程

| 步骤 | 关键字 | 说明 |
|------|--------|------|
| 1. 切换 Tab | `click_element` | 定位器：`//*[contains(text(),'{label}') and @role='tab']` |
| 2. 获取作用域 ID | `get_attribute` | 读取 tab 元素的 `aria-controls` 属性值，存入变量 |
| 3. 作用域内操作 | `click_element` / `fill_value` | 定位器前缀 `//div[@id='{变量名}']` |

### 页面 YAML 命名规范

```yaml
# Tab 标签统一用 tab_ 前缀
tab_xxx: "xpath=//*[contains(text(),'xxx') and @role='tab']"
```

### Case Steps 标准模板

```yaml
# 步骤 1：点击 tab
- desc: "点击 xxx 标签"
  keyword: click_element
  params: {locator: "${page.tab_xxx}"}

# 步骤 2：获取 tab 作用域 ID
- desc: "获取 xxx tab 作用域"
  keyword: get_attribute
  params:
    locator: "${page.tab_xxx}"
    name: "aria-controls"
    target_var: "tab_panel_xxx"

# 步骤 3：在作用域内操作元素
- desc: "操作 tab 内元素"
  keyword: click_element
  params: {locator: "xpath=//div[@id='${tab_panel_xxx}']//目标元素xpath"}
```

### 禁止事项

- ❌ 禁止直接用文本匹配点击 tab（如 `xpath=//span[contains(text(),'tab名')]`），必须使用 `@role='tab'` 模式
- ❌ 禁止在 tab 切换后不获取作用域 ID 就直接操作 tab 内元素
- ❌ 禁止硬编码 tab panel 的 ID，必须通过 `get_attribute` 动态获取

### 知识库对应路径

- Tab 点击：`single_step/tab` → `//*[contains(text(),'{label}') and @role='tab']`
- 作用域获取：`composite/tab-scoped` → `get-tab-id` 步骤
- 作用域内按钮：`composite/tab-scoped` → `scoped-button` 步骤
- 作用域内输入框：`composite/tab-scoped` → `scoped-input` 步骤
- 作用域内详情链接：`composite/tab-scoped` → `scoped-detail-link` 步骤
- 作用域内目录：`composite/tab-scoped` → `scoped-menu-item` 步骤

**通用规则**：多 tab 页面中，**所有元素**（不仅按钮）的定位器都必须加上 `//div[@id='{作用域ID}']` 前缀。

## R3.10 全量探测规则

**原则**：case 中出现的每一个 locator（包括 L3 关键字内部的）都必须经过 probe 验证。

### 探测清单提取

Phase 3 开始前，从以下来源提取完整探测清单：

1. 扫描 `cases/**/*.yaml` 中所有步骤的 `params.locator`
2. 提取定位器引用，区分：
   - 变量引用（`${xxx_elements.yyy}`）→ 加入探测清单
   - 硬编码 locator（`xpath=//...`、`.css-selector`、`//...`）→ 加入探测清单
   - 数据引用（`${xxx_data.yyy}`）→ 跳过
3. 遇到 L3 关键字 → 读取 `_knowledge/{module}.yaml` 的 workflow，提取内部所有 locator
4. 扫描 `suites/**/*.yaml` 中 `setup_step` 的 locator 引用
5. 去重后生成最终探测清单

### 操作匹配顺序

Case 生成时，按以下优先级匹配用例步骤的实现方式：

| 优先级 | 层 | 说明 | 示例 |
|--------|-----|------|------|
| 1 | L3 模块关键字 | 项目专属 + 系统级跨项目 | `check_mail_display(tab_name)` |
| 2 | L1 知识库操作模式 | 单步元素操作 | `click_element` + tab 定位器 |
| 3 | AI 补充生成 | 以上均未匹配时推断 | 推断关键字和定位器 |

**定位器统一来源**：不论操作来自哪层，所有 locator 都来自知识库（系统级 `probe_knowledge.json` + 模块级 `_knowledge/*.yaml`），且必须经过 probe 验证。

### 探测结果

| 结果 | 标记 | 备注 |
|------|------|------|
| 成功 | ✅ | 备注来源（知识库/L3/AI生成） |
| 失败 | ❌ | 备注需修改的文件路径 |
| 不需要探测 | — | 无 locator 的步骤（open_url/refresh/wait 等） |

### 验证器校验

`validate_04_probe.py` 必须检查：
- cases 中每个 `${xxx_elements.yyy}` 引用在 `_probe/*.json` 中有对应记录
- 无对应记录 → **error**（阻断 Phase 4）
- L3 关键字内部的 locator 也必须出现在 probe 结果中

## R3.11 iframe 内元素操作规则

当探测发现某个元素位于 iframe 内（`has_iframe: true` 或 DOM 结构中检测到 iframe），**必须**遵循以下流程：

### 操作流程

| 步骤 | 关键字 | 说明 |
|------|--------|------|
| 1. 切换到 iframe | `switch_to_frame` | 参数 `frame_locator_str` 为 iframe 的定位表达式 |
| 2. 在 iframe 内操作 | `frame_click_element` / `frame_fill_value` / `frame_hover` 等 | 参数 `frame` 为 iframe 定位器，`locator` 为 iframe 内目标元素 |
| 3. 切回主页面 | `switch_to_main_frame` | 操作完成后切回，避免影响后续步骤 |

### 判断规则

- 探测结果 `recommended_keyword: "frame_fill_value"` → 该元素在 iframe 内，必须用 frame 系列关键字
- 富文本编辑器（TinyMCE/UEditor）通常使用 iframe 模式
- 如果用例中某个字段通过 `frame_fill_value` 填写，则该字段的断言也必须用 `execute_script` 读取 iframe 内容（页面级 XPath 无法穿透 iframe）

### Case Steps 标准模板

```yaml
# 步骤 1：切换到 iframe
- desc: "切换到富文本编辑器 iframe"
  keyword: switch_to_frame
  params: {frame_locator_str: "${pages_group.editor_iframe}"}

# 步骤 2：在 iframe 内操作
- desc: "在 iframe 内输入内容"
  keyword: frame_fill_value
  params:
    frame: "${pages_group.editor_iframe}"
    locator: "${pages_group.editor_body}"
    value: "${data_group.content}"

# 步骤 3：切回主页面
- desc: "切回主页面"
  keyword: switch_to_main_frame
```

### 禁止事项

- ❌ 禁止在 iframe 内元素上使用普通 `click_element` / `fill_value`（会找不到元素）
- ❌ 禁止在 iframe 操作完成后忘记 `switch_to_main_frame`
- ❌ 禁止用页面级 XPath 断言 iframe 内的富文本内容（必须用 `execute_script` 读取 `contentDocument.body.textContent`）

### 知识库对应路径

- iframe 检测：`probe_element.py` 探测富文本时自动检测 `has_iframe`
- iframe 关键字：`keyword_spec.md` → iframe 章节（10 个 frame 系列关键字）

## R3.12 二级弹窗容器前缀规则

当页面存在嵌套弹窗（如 drawer 内弹出 dialog、dialog 内弹出 message-box），**优先尝试正常探测**。如果二级弹窗的按钮因隐藏/不可交互而无法探测，**默认使用 `el-dialog` 容器前缀**。

### 适用场景

| 一级容器 | 二级容器 | 默认前缀 | 说明 |
|---------|---------|---------|------|
| `el-drawer` | `el-dialog` | `//div[contains(@class,'el-dialog')]` | 最常见：侧滑面板内弹出确认框 |
| `el-dialog` | `el-dialog` | `//div[contains(@class,'el-dialog')]` | 弹窗内再弹确认框 |
| `el-drawer` | `el-message-box` | `//div[contains(@class,'el-message-box')]` | 侧滑面板内弹出 $confirm |

### 探测流程

1. **优先正常探测**：尝试用 `--action` 打开二级弹窗并探测按钮
2. **探测失败判断**：
   - 按钮存在但 `parent_visible: false`（祖先链有隐藏元素）
   - 按钮尺寸为 0（`rect_w: 0, rect_h: 0`）
   - Playwright 报 "element is not visible"
3. **失败时回退**：手动添加定位器，使用 `el-dialog` 前缀（或根据实际 UI 框架选择）

### 手动添加定位器示例

```yaml
# 二级弹窗的确定按钮（探测失败，使用默认 el-dialog 前缀）
secondary_confirm_btn: "xpath=//div[contains(@class,'el-dialog')]//button[contains(.,'确定')]"

# 二级弹窗的取消按钮
secondary_cancel_btn: "xpath=//div[contains(@class,'el-dialog')]//button[contains(.,'取消')]"
```

### 多容器探测优先级

`probe_element.py` 已实现 `reversed(container_types)` 策略：当多个容器同时可见时，**后检测的容器优先**（通常是 z-index 更高的顶层弹窗）。

- 单容器场景：正常探测，容器前缀自动添加
- 双容器场景（drawer + dialog）：优先尝试 dialog 前缀
- 探测失败：回退到手动添加 + `el-dialog` 默认前缀

### 禁止事项

- ❌ 禁止假设二级弹窗一定是 `el-dialog` 而不尝试探测
- ❌ 禁止在探测成功的情况下手动修改容器前缀
- ✅ 允许在探测失败时使用默认前缀并标注 `[手动添加，探测失败]`

## R3.13 手动添加定位器必须使用知识库第一模式

当探测失败需要手动添加定位器时，**必须使用知识库中该元素类型的第一个模式**（最高优先级）。

### 原则

知识库 `probe_knowledge.json` 中每种元素类型的 patterns 列表按优先级排序：
- 第一个模式：最常见、最可靠的场景
- 后续模式：边缘场景、备选方案

手动添加时，**从第一个模式开始尝试**，只有确认第一个模式不适用时才降级到后续模式。

### 示例：表格行按钮（table-action-button）

知识库中的 4 个模式（按优先级）：

| 优先级 | 模式 | 适用场景 |
|--------|------|----------|
| 1 | `el-table__fixed-right` | 固定右列按钮（最常见） |
| 2 | `el-table__body-wrapper` | 普通表格体按钮 |
| 3 | `el-table__fixed-body-wrapper` | 固定体包裹按钮 |
| 4 | tabpanel + `el-table__fixed-right` | 多 tab 场景 |

**正确做法**：
```yaml
# ✅ 使用 pattern #1: el-table__fixed-right
first_remove_btn: "xpath=//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//span[contains(.,'移除')...]"
```

**错误做法**：
```yaml
# ❌ 跳过 pattern #1，直接用 pattern #2
first_remove_btn: "xpath=//div[contains(@class,'el-table__body-wrapper')]//tbody/tr[1]//span[contains(.,'移除')...]"
```

### 适用所有元素类型

此规则适用于知识库中所有元素类型：
- 按钮（button）：优先 `//button[contains(.,'{label}')]`
- 输入框（input-generic）：优先 `//*[contains(text(),'{label}')]/following-sibling::...`
- el-select：优先 `//*[contains(text(),'{label}')]/following-sibling::...//input[@class='el-input__inner']`
- 表格行按钮（table-action-button）：优先 `el-table__fixed-right`
- 其他类型：同理，使用知识库中第一个模式

### 禁止事项

- ❌ 禁止凭经验编写 XPath，必须参考知识库
- ❌ 禁止跳过第一个模式直接使用后续模式（除非已验证第一个模式不适用）
- ✅ 允许在第一个模式不适用时降级，但必须在注释中说明原因

## R3.14 禁止负向排除，改用正向容器前缀 + 降级策略

**禁止**使用 `not(ancestor::*[contains(@class,'el-drawer')])` 等负向排除条件来区分同名元素。改用**正向容器前缀 + 探测降级**策略。

### 问题背景

旧方案在跨 group 出现同名 label 时（如"确定"按钮同时出现在搜索区和 drawer 中），会给无前缀的 locator 注入 `not(ancestor::...)` 排除条件。当实际目标元素**位于容器内部**时，排除条件反而阻止了正确匹配，导致超时。

### 正确策略：正向容器前缀 + 探测降级

```
探测顺序（对任何可能存在容器冲突的元素）：
1. 正向：//div[contains(@class,'el-drawer')]//button[contains(.,'确定')] → count==1? ✅ 用这个
2. 降级：//button[contains(.,'确定')] → count==1? ✅ 用这个（无前缀，不加任何排除）
3. 都失败 → fallback（标记为不可信）
```

### 核心原则

- **正向优先**：如果元素在容器内，使用 `//div[contains(@class,'el-drawer')]//...` 正向容器前缀
- **降级兜底**：如果正向容器前缀匹配不到，降级到无前缀版本
- **禁止负向**：绝对不要在 XPath 中使用 `not(ancestor::*[contains(@class,...)])`

### 禁止事项

- ❌ 禁止生成 `not(ancestor::*[contains(@class,'el-drawer')])` 排除条件
- ❌ 禁止生成 `not(ancestor::*[contains(@class,'el-dialog')])` 排除条件
- ❌ 禁止生成 `not(ancestor::*[contains(@class,'el-message-box')])` 排除条件
- ✅ 允许使用 `//div[contains(@class,'el-drawer')]//...` 正向容器前缀
- ✅ 允许无前缀版本作为降级兜底

### 知识库模板

`probe_knowledge.json` 中的所有模板均不含负向排除条件，只包含隐藏过滤（`is-hidden`、`display: none`）。容器前缀由探测阶段动态添加。

### 验证器行为

- **R4.27**：同名 label 跨容器冲突 → warning（提示确认，不阻断）
- **R4.28**：通用按钮缺少容器前缀 → warning（建议添加，不阻断）
- `probe_from_pages.py` 的 `strip_not_ancestor_exclusions()` 自动清除已有的负向排除
