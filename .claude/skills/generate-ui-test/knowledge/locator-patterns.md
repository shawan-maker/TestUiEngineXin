# 元素定位器模式参考（16 类 · 已验证可直接使用）

> **本文档由 `tools/sync_locator_docs.py` 从 `probe_knowledge.json` 自动生成。**
> **所有 XPath 表达式均已在目标系统中验证，可直接遍历使用，只需修改对应的数据/文本/按钮名称。**
>
> 对应 `tools/probe_knowledge.json` 的模板定义，本文件提供人类可读的操作说明。
>
> 最后同步时间：由 `learn_probe.py` 学习新模板后自动触发。

---

## 🚨 通用原则：隐藏过滤（所有模式必须遵守）

**所有元素表达式的最后一个标签中必须加上隐藏过滤属性**（查找非隐藏的元素）：

```xpath
and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])
```

如果标签已有属性条件，前面加 `and` 连接。

**例外**（以下定位器不需要隐藏过滤）：
- `//*[contains(.,'xx')]` — 通用文本匹配断言定位器
- 含 `@x-placement` 的 option 定位器 — 已有可见性逻辑（面板隐藏时整个 dropdown 不可见）
- 含 `not(contains(@style,'display: none'))` 的容器定位器 — 已有可见性过滤

---
## 一、各种输入框（普通输入框、文本框、选择框、级联框、时间选择框）

替换规则：`选项文本` → 字段 label 文本（如“项目名称”、“问题描述”）

### 通用输入框

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 通用文本框

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//textarea[not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

---

## 二、el-select 下拉框操作（条件分支法）

### Step 1：点击展开下拉框（`_select`）

_点击展开下拉框_

- **关键字**：`click_element`

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### Step 2：运行时判断是否可编辑（`_editable`）

_条件分支：可编辑走 fill+选项，readonly 走第一项_

- **关键字**：`if_element_visible`
- **timeout**：`500`（避免 readonly 分支 3 秒空等）

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(@readonly) and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

> 与 `_select` 相同的 XPath，额外加了 `and not(@readonly)` 条件。
> 可编辑时 XPath 匹配 → `is_visible=True` → 走 `then_steps`。
> readonly 时 XPath 不匹配 → `is_visible=False` → 走 `else_steps`。

#### then_steps（可编辑分支）

**输入搜索文本**（`_input`）：

- **关键字**：`fill_value`

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**选择匹配选项**（`_option`）：

- **关键字**：`click_element`

```xpath
(//div[(@x-placement='bottom-start' or @x-placement='top-start') and not(ancestor::*[contains(@style,'display: none')])]//li[not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])][contains(.,'{option_text}')])[1]
```

#### else_steps（readonly 分支）

**选择第一项**（`_first_option`）：

- **关键字**：`click_element`

```xpath
(//div[(@x-placement='bottom-start' or @x-placement='top-start') and not(ancestor::*[contains(@style,'display: none')])]//li[contains(@class,'el-select-dropdown__item') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])])[1]
```

> ⚠️ then_steps 搜索文本与选项文本必须一致（均来自用户用例），禁止从 probe 的 select_options 中随意选取。
> ⚠️ else_steps 选择的是下拉面板第一项，适用于 readonly 下拉框不需要指定具体值的场景。

---

## 三、级联选择器（el-cascader）操作

### 第一步：点击展开选择器

_点击展开级联面板_

- **关键字**：`click_element`

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 第二步及后续：勾选/展开某一级（可重复多次）

_勾选/展开某一级_

- **关键字**：`click_element`

```xpath
//li[@role='menuitem' and contains(.,'{option_text}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//span[@class='el-checkbox__inner']
```

```xpath
//li[@role='menuitem' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//span[contains(text(),'{option_text}')]
```

---

## 四、时间选择框（el-date-picker）操作

### 第一步：点击展开时间选择框

_点击展开日期面板_

- **关键字**：`click_element`

```xpath
//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 选择今天（用 class="today" 匹配，不是文本）

_选择今天_

- **关键字**：`click_element`

```xpath
//div[@x-placement='bottom-start' or @x-placement='top-start']//table[not(contains(@style,'display: none')) and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//td[contains(@class,'today')]
```

### 选择此刻

_选择此刻_

- **关键字**：`click_element`

```xpath
//div[@x-placement='bottom-start' or @x-placement='top-start']//table[not(contains(@style,'display: none')) and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//button[contains(.,'此刻')]
```

### 选择当月

_选择当月_

- **关键字**：`click_element`

```xpath
//table[@class='el-month-table' and not(contains(@style,'display: none')) and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//td[@class='today' or @class='current']
```

### 选择起始时间（日期范围）

_选择起始时间_

- **关键字**：`click_element`

```xpath
(//div[contains(@class,'is-left') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//*[contains(@class,'available')])[1]
```

### 选择结束时间

_选择结束时间_

- **关键字**：`click_element`

```xpath
(//div[contains(@class,'is-right') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]//*[@class='available'])[1]
```

> ⚠️ "今天"用 `class="today"` 匹配，Element UI 日期选择器的"今天"单元格**不显示"今天"文字**。

---

## 五、下载导出按钮

```xpath
//span[(contains(.,'导出') or contains(.,'下载')) and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//i[@class='el-icon-download' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@role='tabpanel' and not(contains(@style,'display: none'))]//i[@class='el-icon-download' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

---

## 六、搜索按钮

```xpath
(//i[@class='el-icon-search' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])])[last()]
```

```xpath
//i[@class='el-icon-search' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//button[contains(@class,'search') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//button[contains(.,'搜') and contains(.,'索') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

---

## 七、页面中的普通按钮

> **优先级 2 > 1 > 3**：优先使用 button + 完整文本（最简洁直接），
> 降级为拆字 contains（兼容空格变异），最后才用通用 text() 匹配。
> probe 按此顺序尝试，命中即用。校验器 R4.36 禁止按钮使用模式 3。

**模式 2（最优先）— button + 完整文本**：

```xpath
//button[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 1（次选）— 拆字 contains**：

```xpath
//button[contains(.,'{char1}') and contains(.,'{char2}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 3（最后，按钮禁止使用）**：

```xpath
//*[contains(text(),'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

> 替换规则：`{label}` 填入完整按钮名称（如"查询"、"新增"），`{char1}/{char2}` 为首尾字符

---

## 八、列表右侧按钮（表格行操作按钮）

> **手动添加定位器时，必须从模式 1 开始尝试（R3.13）**，只有确认不适用时才降级。

**模式 1（优先，固定右列）**：

```xpath
//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 2（普通表格体）**：

```xpath
//div[contains(@class,'el-table__body-wrapper')]//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 3（固定体包裹）**：

```xpath
//div[contains(@class,'el-table__fixed-body-wrapper')]//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 4（多 tab 场景）**：

```xpath
//div[@role='tabpanel' and not(contains(@style,'display: none'))]//div[@class='el-table__fixed-right']//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

> 不是所有表格都有固定右侧列，必须通过 probe 确认使用哪种路径。手动添加时默认使用模式 1。

---

## 九、列表右侧的"更多"展开按钮

> 同第八节，手动添加时默认使用模式 1（el-table__fixed-right）。

### 第一步：点击"更多"

_点击更多按钮_

- **关键字**：`click_element`

**模式 1（优先，固定右列）**：

```xpath
//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//span[contains(.,'更多') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 2（普通表格体）**：

```xpath
//div[contains(@class,'el-table__body-wrapper')]//tbody/tr[1]//span[contains(.,'更多') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 3（固定体包裹）**：

```xpath
//div[contains(@class,'el-table__fixed-body-wrapper')]//tbody/tr[1]//span[contains(.,'更多') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

**模式 4（多 tab 场景）**：

```xpath
//div[@role='tabpanel' and not(contains(@style,'display: none'))]//div[@class='el-table__fixed-right']//tbody/tr[1]//span[contains(.,'更多') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 第二步：点击对应的操作按钮

_点击菜单项_

- **关键字**：`click_element`

```xpath
//*[(@x-placement='top-end' or @x-placement='bottom-end') and not(ancestor::*[contains(@style,'display: none')])]//*[not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])][contains(text(),'{label}')]
```

---

## 十、点击侧边的目录

```xpath
//*[@class='el-menu-item' and contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

---

## 十一、进入详情页

```xpath
//td[not(contains(@class,'is-hidden'))]//*[contains(text(),'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//td[not(contains(@class,'is-hidden'))]//*[contains(@class,'link-style') or contains(@class,'click-list') or contains(@class,'resource-id') or contains(@class,'name')][contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//td[not(contains(@class,'is-hidden'))]//*[contains(@class,'link-style') or contains(@class,'click-list') or contains(@class,'resource-id') or contains(@class,'name')][contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]/div[@class='resource-id' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//td[not(contains(@class,'is-hidden'))]//*[@class='edit-name' and contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]/preceding-sibling::div[contains(@class,'link-style')]
```

---

## 十二、点击批量全选

```xpath
//div[@class='el-table__header-wrapper']//span[@class='el-checkbox__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

---

## 十三、断言（存在即可，不用精确匹配到一个元素）

断言定位器是隐藏过滤的例外 — `//*[contains(.,'xx')]` 通用文本匹配不需要加隐藏过滤属性。

所有断言统一使用 `except_to_be_visible`，禁止使用 `except_to_have_text`/`except_to_have_value`/`except_to_have_attribute`。

### 成功提示

```xpath
//*[contains(.,'{keyword}成功')]
```

### 失败提示

```xpath
//*[contains(.,'{keyword}失败')]
```

### 第一行内容

```xpath
//tbody/tr[1]//*[contains(.,'{keyword}')]
```

### 字段值

```xpath
//*[contains(text(),'{field_label}')]/following-sibling::*[self::div or self::span]//*[contains(.,'{keyword}')]
```

---

## 十四、多 tab 时右侧操作按钮

### 第一步：点击 tab + 获取 aria-controls 属性值

_获取tab的aria-controls属性_

- **关键字**：`click_element`

```xpath
//*[contains(text(),'{tab_name}') and @role='tab' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 第三步：tab 作用域内的按钮

_tab作用域内的元素（按钮、输入框、链接等均需加作用域前缀）_

- **关键字**：`click_element`

```xpath
//div[@id='{element_id}']//button[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//span[contains(.,'{label}') and @role='button' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//div[contains(@class,'el-table__fixed-right')]//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//div[contains(@class,'el-table__body-wrapper')]//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//div[contains(@class,'el-table__fixed-body-wrapper')]//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//div[@role='tabpanel' and not(contains(@style,'display: none'))]//div[@class='el-table__fixed-right']//tbody/tr[1]//span[contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 第三步：tab 作用域内的输入框

_tab作用域内的输入框_

- **关键字**：`click_element`

```xpath
//div[@id='{element_id}']//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner' and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//textarea[not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 第三步：tab 作用域内的详情链接

_tab作用域内的详情页链接_

- **关键字**：`click_element`

```xpath
//div[@id='{element_id}']//td[not(contains(@class,'is-hidden'))]//*[contains(text(),'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

```xpath
//div[@id='{element_id}']//td[not(contains(@class,'is-hidden'))]//*[contains(@class,'link-style') or contains(@class,'click-list') or contains(@class,'resource-id') or contains(@class,'name')][contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

### 第三步：tab 作用域内的侧边目录

_tab作用域内的侧边目录_

- **关键字**：`click_element`

```xpath
//div[@id='{element_id}']//*[@class='el-menu-item' and contains(.,'{label}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])]
```

> ⚠️ 多 tab 时，**所有元素**（不光是按钮）都要先切换 tab → 获取 aria-controls → 在 xpath 前加 `//div[@id='{变量}']` 前缀。

---

## 十五、有 iframe 的情况

同多 tab 的处理思路：如果探测发现某个元素在 iframe 下，先切换到 iframe，再进行相关操作。进入 iframe 后的元素定位或断言方法跟前面一样。

### 操作流程

| 步骤 | 关键字 | 说明 |
|------|--------|------|
| 1. 切换到 iframe | `switch_to_frame` | 参数 `frame_locator_str` 为 iframe 的定位表达式 |
| 2. 在 iframe 内操作 | `frame_fill_value` / `frame_click_element` 等 | 参数 `frame` 为 iframe 定位器，`locator` 为 iframe 内目标元素 |
| 3. 切回主页面 | `switch_to_main_frame` | 操作完成后必须切回 |

> ⚠️ 如果某个字段通过 `frame_fill_value` 填写（TinyMCE/UEditor 富文本），该字段的断言也必须用 `execute_script` 读取 iframe 内容（页面级 XPath 无法穿透 iframe）。

---

## 十六、容器定位器（el-drawer / el-dialog）

容器内的元素必须在 XPath 前添加容器前缀，确保定位器只匹配当前容器内的元素，避免 strict mode violation。

### 容器类型判定（R4.38）

| UI 表现 | Element UI 组件 | XPath 容器前缀 |
|---------|----------------|---------------|
| 从右侧/左侧滑出的面板 | el-drawer | `//div[contains(@class,'el-drawer')]` |
| 居中弹出的对话框 | el-dialog | `//div[contains(@class,'el-dialog')]` |

### 抽屉（el-drawer）内元素

```xpath
# 抽屉内输入框
//div[contains(@class,'el-drawer')]//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']

# 抽屉内 el-select
//div[contains(@class,'el-drawer')]//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]

# 抽屉内确认按钮
//div[contains(@class,'el-drawer')]//button[contains(.,'确') and contains(.,'定')]

# 抽屉内 textarea
//div[contains(@class,'el-drawer')]//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//textarea
```

### 对话框（el-dialog）内元素

```xpath
# 对话框内确认按钮
//div[contains(@class,'el-dialog')]//button[contains(.,'确') and contains(.,'定')]

# 对话框内取消按钮
//div[contains(@class,'el-dialog')]//button[contains(.,'取') and contains(.,'消')]

# 对话框内输入框
//div[contains(@class,'el-dialog')]//*[contains(text(),'{label}')]/following-sibling::*[self::div or self::span]//input[@class='el-input__inner']
```

> ⚠️ **同一 group 内所有带容器前缀的元素必须使用相同的容器类型**（R4.38 校验器自动检查）。
> 新增/编辑表单通常使用 Drawer，操作确认/删除确认通常使用 Dialog。不确定时必须通过 probe 或页面观察确认。

---

## 十七、选项卡（option-card）数据分离模式

选项卡（如"计费方式"选择"按量计费"、"架构"选择"ARM计算型"）采用数据分离模式：pages 存容器 XPath，data 存选项值，case 用内联 XPath + `${data}` 引用。

### 架构对比

| 维度 | el-select | option-card |
|------|-----------|-------------|
| **pages 字段** | `_select`（触发器） | `_card`（容器） |
| **data 字段** | `_option` + `_search` | `_card_value` |
| **case 引用** | 内联 XPath + `${data.option}` | 内联 XPath + `${data.card_value}` |

### pages YAML

pages 中只存容器 XPath（不含选项值）：

```yaml
compute_vm_newpage_listpage_elements:
  field_0eaa6a_card: 'xpath=//label[contains(.,"架构")]//following-sibling::*[self::div or self::span]'
  # 注释: option-card 容器定位（不含选项值）
```

容器 XPath 定位到"架构"标签后的 div/span 容器，不包含具体的选项文本。

### data YAML

data 中存储选项值（会随场景变化的测试数据）：

```yaml
compute_data:
  case01_field_0eaa6a_card_value: "ARM 计算"
  case01_field_0eaa6a_card_value_2: "ARM计算型"  # 同 case 内第二个同 label 步骤
```

### case YAML

case 中用内联 XPath + `${data}` 引用：

```yaml
- desc: 在「架构」选项卡中选择「ARM 计算」
  keyword: click_element
  params:
    locator: 'xpath=(//label[contains(.,"架构")]//following-sibling::*[self::div or self::span]//*[contains(.,"${compute_data.case01_field_0eaa6a_card_value}") and not(ancestor::*[contains(@class,"is-hidden")]) and not(ancestor::*[contains(@style,"display: none")])])[1]'

- desc: 在「架构」选项卡中选择「ARM计算型」
  keyword: click_element
  params:
    locator: 'xpath=(//label[contains(.,"架构")]//following-sibling::*[self::div or self::span]//*[contains(.,"${compute_data.case01_field_0eaa6a_card_value_2}") and not(ancestor::*[contains(@class,"is-hidden")]) and not(ancestor::*[contains(@style,"display: none")])])[1]'
```

### 同 label 多值处理

当同一个 case 内对同一个选项卡选择多个不同的值时（如"架构"先选"ARM 计算"再选"ARM计算型"），data 字段自动添加后缀 `_2`、`_3`：

- `case01_field_0eaa6a_card_value` = "ARM 计算"
- `case01_field_0eaa6a_card_value_2` = "ARM计算型"

每个步骤引用自己的 data key，运行时点击不同元素。这解决了旧实现中"同 label 多值覆盖"的问题。

### 容器定位器 XPath

```xpath
//label[contains(.,'{label}')]//following-sibling::*[self::div or self::span]
```

定位到 `{label}`（如"架构"）标签后的 div/span 容器。选项值通过 data 引用注入到内联 XPath 中。

### 完整内联 XPath

```xpath
(//label[contains(.,'{label}')]//following-sibling::*[self::div or self::span]//*[contains(.,'{card_value_ref}') and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])])[1]
```

其中 `{card_value_ref}` 是 `${compute_data.case01_field_xxx_card_value}` 形式的 data 引用。

> ⚠️ pages 中的 `_card` 字段是容器定位器（文档存档 + probe 验证），实际点击通过 case 中的内联 XPath 完成。
> 这与 el-select 的 `_select`（触发器）不同：el-select 的 `_select` 用于点击展开，而 option-card 的 `_card` 仅用于文档和验证。

---

## 速查表

| # | 元素类型 | 关键字 | 操作步数 | 对应 probe_knowledge.json 路径 |
|---|---------|--------|---------|-------------------------------|
| 1 | 输入框/文本框 | `fill_value` | 1 | `single_step/input-generic`, `textarea-generic` |
| 2 | el-select | `click_element` + `if_element_visible`(then: fill+option / else: first_option) | 1+if(2/1) | `multi_step/el-select` |
| 3 | el-cascader | `click_element` × N | 2+ | `multi_step/el-cascader` |
| 4 | el-date-picker | `click_element` × 2 | 2 | `multi_step/date-picker` |
| 5 | 下载/导出 | `click_element` / `download_file` | 1 | `single_step/download-button` |
| 6 | 搜索 | `click_element` | 1 | `single_step/search-button` |
| 7 | 普通按钮 | `click_element` | 1 | `single_step/button` |
| 8 | 列表行按钮 | `click_element` | 1 | `composite/table-action-button` |
| 9 | 更多菜单 | `click_element` × 2 | 2 | `composite/dropdown-menu` |
| 10 | 侧边目录 | `click_element` | 1 | `single_step/menu-item` |
| 11 | 详情页链接 | `click_element` | 1 | `single_step/detail-link` |
| 12 | 批量全选 | `click_element` | 1 | `single_step/checkbox-all` |
| 13 | 断言 | `except_to_be_visible` | 1 | `assertion/*` |
| 14 | 多 tab 操作 | `click_element` + `get_attribute` + 操作 | 3 | `composite/tab-scoped` |
| 15 | iframe 内操作 | `switch_to_frame` + frame 系列 + `switch_to_main_frame` | 3 | — (规则 R3.11) |
| 16 | 容器内元素 | `click_element` / `fill_value`（带容器前缀） | 1 | `el-drawer` / `el-dialog` (R4.38) |
