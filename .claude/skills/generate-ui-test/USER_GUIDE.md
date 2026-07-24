# generate-ui-test 用户操作手册

> 本手册面向使用该技能生成 UI 自动化测试工程的用户，包含从 0 到 1 新建项目、新增用例、排查修复问题的完整操作流程。

---

## 目录

- [一、前置准备](#一前置准备)
- [二、准备 Excel 用例](#二准备-excel-用例)
- [三、场景一：新建完整项目](#三场景一新建完整项目)
- [四、场景二：已有项目——新增用例](#四场景二已有项目新增用例)
- [五、场景三：排查与修复](#五场景三排查与修复)
- [附录 A：生成的项目目录结构](#附录-a生成的项目目录结构)
- [附录 B：常用命令速查表](#附录-b常用命令速查表)

---

## 一、前置准备

### 1.1 安装依赖

```bash
pip install ui_engine_xin pyyaml openpyxl playwright
playwright install chromium
```

### 1.2 获取 Cookie（如需认证）

如果被测系统需要登录且无法自动化登录（如有验证码）：

1. 用浏览器手动登录被测系统
2. 按 **F12** → **Network** → 点击任意请求 → **Headers** → 找到 **Cookie** → 整串复制
3. 在技能交互阶段粘贴给 AI

> Cookie 有过期时间，过期后需重新获取（见 [5.4 Cookie 过期替换](#54-cookie-过期替换)）。

---

## 二、准备 Excel 用例

### 2.1 基本格式

Excel 文件需要 **3 列**（顺序不限），第一行为列标题：

| 列名 | 必填 | 说明 |
|------|:----:|------|
| 模块 | 建议 | 模块中文名，如"问题管理"、"站内信" |
| 用例名称 | **是** | 用例的名称 |
| 用例步骤 | **是** | 用编号列表写出全部操作步骤（单元格内按 **Alt+Enter** 换行） |

> **列名变体自动识别**：`用例名称` / `测试用例名称` / `Case Name` 都可以；`用例步骤` / `测试用例内容` 都可以。

> **推荐每个模块一个 Sheet**（Sheet 名 = 模块名），便于管理。

### 2.2 可用关键字

Excel 步骤中可以使用以下关键字，AI 会自动识别并生成对应的自动化脚本。

这些是多步骤组合的高级关键字（L3），一个调用 = 多个操作步骤。

**来源**：系统内置关键字定义在 `lib/system_workflows.yaml`，项目专属关键字放在 `_knowledge/*.yaml` 中，由编译器自动合并（项目级覆盖系统级同名）。

| 关键字 | Excel 写法示例 | 功能说明 | 来源 |
|--------|---------------|---------|------|
| 等待加载完成 | `等待加载完成` | 等待 3 种 loading 元素全部消失 + 1s 稳定等待 | 系统内置 |
| 列表查询 | `列表查询(项目名称, 测试项目A)` | 在搜索框输入关键词 → 点击查询 → 等待加载完成 | 系统内置 |
| 导出验证 | `导出验证` | 点击导出 → 等待下载 → 验证文件存在 | 系统内置 |
| 检查站内信显示 | `检查站内信显示(任务提醒)` | 点击 tab → 获取消息数 → 数量>0 则查看详情并断言标题一致 | 项目 |
| 首页列表校验 | `首页列表校验(待办事项)` | 获取指定区域列表行数 → 数量>0 则点击第一条链接 | 项目 |

> **L3 关键字调用格式**：`关键字名(参数1, 参数2)` — 无参数时直接写关键字名。

#### 特殊值表达式

以下表达式可嵌入输入框操作中，自动生成动态值：

| 表达式 | Excel 写法示例 | 功能说明 |
|--------|---------------|---------|
| 随机名称 | `在"项目名称"输入框中输入随机名称(测试项目)` | 自动生成"前缀+时间戳"（如 `测试项目20260717155123`），每次运行不同 |

> **注意**：`随机名称(前缀)` 必须写在输入框操作内，不能单独作为一行使用。支持输入框、文本框、下拉框等所有填写场景。

### 2.3 标准用例示例

参照以下示例编写你的用例即可：

#### 示例 1：新增记录

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 问题管理 | 新增实施问题 | 1. 访问实施问题列表页<br>2. 点击"新增"按钮<br>3. 选择"项目名称"为"测试项目A"<br>4. 选择"底座方案"为"方案一"<br>5. 在"问题描述"中输入"测试描述内容"<br>6. 点击"确定"按钮<br>7. 验证提示"操作成功" |

#### 示例 2：编辑记录

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 问题管理 | 编辑实施问题 | 1. 访问实施问题列表页<br>2. 点击第一条记录的"编辑"按钮<br>3. 在"问题描述"中输入"修改后的描述"<br>4. 点击"确定"按钮<br>5. 验证提示"操作成功" |

#### 示例 3：查询 + 验证

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 工单管理 | 按标题查询工单 | 1. 访问工单列表页<br>2. 在"工单标题"中输入"测试工单"<br>3. 点击"查询"按钮<br>4. 检查第一条记录状态为"待审批" |

#### 示例 4：条件操作

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 审批管理 | 处理待审批记录 | 1. 访问审批列表页<br>2. 如果"待审批"中数量大于0则点击第一条记录的"审批"按钮<br>3. 点击"同意"按钮<br>4. 验证提示"操作成功" |

#### 示例 5：L3 关键字调用

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 首页 | 首页列表校验 | 1. 访问首页<br>2. 等待加载完成<br>3. 首页列表校验(待办事项) |

#### 示例 6：随机名称（每次运行生成不同值）

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 问题管理 | 新增问题-随机数据 | 1. 访问实施问题列表页<br>2. 点击"新增"按钮<br>3. 在"问题标题"输入框中输入随机名称(测试问题)<br>4. 在"问题描述"输入框中输入随机名称(自动描述)<br>5. 点击"确定"按钮<br>6. 验证提示"操作成功" |

> 每次运行时 `随机名称(测试问题)` 会生成类似 `测试问题20260717155123` 的值，确保测试数据不重复。

### 2.4 书写要点

1. **一行 = 一条用例** — 所有步骤写在同一个单元格内，用编号 `1.` `2.` `3.` 分隔
2. **用页面实际文字** — 按钮叫什么就写什么（如"确定"不写"确认"）
3. **下拉框一句话** — `选择"XX"为"YY"` 即可，AI 自动拆三步
4. **断言统一用"验证..."** — 不要用"检查"、"确认"、"断言"
5. **条件用"如果...则..."** — AI 会生成条件分支
6. **步骤编号连续** — 1. 2. 3. ...，不要跳号
7. **不要逗号拼接多步** — 每步只做一件事。逗号会被忽略，只匹配后半句
8. **随机数据用"随机名称(前缀)"** — 在输入框操作中直接写 `随机名称(XX)`，系统自动生成"前缀+时间戳"，每次运行不同，避免数据冲突

   ```
   ❌ 选择第一条查询记录，点击"进展更新"              → 只识别"点击进展更新"，丢失"第一条"
   ✅ 点击第一条记录的"进展更新"按钮                   → 识别为表格行操作，限定第一行

   ❌ 选择第一条查询记录，点击"更多"，选择编辑          → 只识别"点击更多"，丢失首尾两步
   ✅ 拆成两步：
      1. 点击第一条记录的"更多"按钮                    → 表格行操作，点第一行的"更多"
      2. 点击"编辑"                                   → 点击下拉菜单中的"编辑"
   ```

---

## 三、场景一：新建完整项目

### Step 1：触发技能

```
/generate-ui-test 在 D:/projects 目录下创建 my-system 项目进行 UI 自动化
```

### Step 2：逐项确认项目信息

AI 会逐个询问，按提示回答即可：

| 问题 | 你的回答示例 | 说明 |
|------|-------------|------|
| 项目名称？ | `my-system` | 英文，用于目录名 |
| 被测系统 URL？ | `http://100.71.19.25:30101` | 被测系统的完整地址 |
| 模块名称？ | `问题管理` | 中文名，后续会转为英文目录 |
| 浏览器类型？ | `chromium` | 默认即可 |
| 输入来源？ | `Excel` | 选择 Excel |
| 认证方式？ | `cookie` | 无登录选 `none`，有验证码选 `cookie` |
| Cookie 值？ | `ud_token=eyJhbG...` | 认证方式为 cookie 时需要 |
| 是否需要同步 localStorage？ | `是` / `否` | 某些系统 token 同时存在 Cookie 和 localStorage 中，如需要会引导你提供 |

### Step 3：提供 Excel 文件路径

```
Excel 文件路径：D:/testcases/问题管理用例.xlsx
```

### Step 4：等待 AI 自动处理

AI 通过管线编排器自动执行 Phase 2-9（脚手架 → 探测 → 脚本生成 → 定位器验证 → 跨文件校验），你只需等待完成。

如需重新运行某个阶段，可以手动调用：
```bash
# 例：重新探测某个模块
python .claude/skills/generate-ui-test/tools/run_phase4.py {project} --cookie "..."
# 例：重新验证定位器
python .claude/skills/generate-ui-test/tools/verify_locators.py {project} --cookie "..." --url "..." --module "{module}"
```

### Step 5：运行测试

```bash
cd my-system
python run.py
```

---

## 四、场景二：已有项目——新增用例

### 适用场景

项目已存在，需要为新模块或新场景添加用例。

### 操作流程

**1. 准备新的 Excel 文件**（格式见[第二章](#二准备-excel-用例)）

**2. 触发技能**：

```
/generate-ui-test 在 D:/projects/my-system 项目下新增用例
Excel 文件：D:/testcases/新增模块用例.xlsx
```

**3. AI 自动处理**：

- 复用已有项目的配置（URL、Cookie 等）
- 已有页面定位器会复用，新页面会重新探测
- 生成新的 cases/data 文件，更新 suites

---

## 五、场景三：排查与修复

### 5.1 定位问题

运行测试后，打开运行报告查看错误：

```bash
start report/run_report/
```

常见错误及修复方式：

| 错误信息 | 原因 | 修复文件 |
|---------|------|---------|
| `Timeout 3000ms exceeded` | 定位器找不到元素 | pages YAML |
| `strict mode violation: resolved to N elements` | 定位器匹配到多个元素 | pages YAML |
| 数据不存在 | 测试数据在系统中不存在 | data YAML |
| 步骤顺序错误 | 用例步骤逻辑有误 | cases YAML |

### 5.2 修改页面定位器（pages YAML）

**文件位置**：`pages/{module}/elements.yaml`

**场景 1：匹配到多个元素（strict mode violation）**

添加容器前缀限定作用域：

```yaml
# 修改前（匹配到页面上和抽屉里的两个"项目名称"）
project_name_select: "xpath=//*[contains(text(),'项目名称')]/following-sibling::div//div[contains(@class,'el-select')]"

# 修改后（限定在抽屉内）
project_name_select: "xpath=//div[contains(@class,'el-drawer')]//*[contains(text(),'项目名称')]/following-sibling::div//div[contains(@class,'el-select')]"
```

**场景 2：元素找不到（Timeout）**

常见原因和修复：
- 元素在弹窗/抽屉内 → 添加 `//div[contains(@class,'el-drawer')]` 或 `//div[contains(@class,'el-dialog')]` 前缀
- 文本不匹配 → 对照页面实际文字修改 XPath 中的文本
- 页面未加载完 → 在 cases YAML 中添加等待步骤

### 5.3 修改测试数据（data YAML）

**文件位置**：`data/{module}/data.yaml`

如果测试数据有误，直接修改对应字段值：

```yaml
# data/question-manage/data.yaml
question_data:
  project_name_search: "测试项目A"   # ← 改为系统中实际存在的值
  project_name_option: "测试项目A"
```

### 5.4 修改用例步骤（cases YAML）

**文件位置**：`cases/{module}/NN_case-name.yaml`

修改时注意：
- **不要硬编码 locator** — 必须使用 `${group.field}` 引用 pages YAML
- **不要硬编码数据** — 必须使用 `${data_group.field}` 引用 data YAML

```yaml
# ✅ 正确写法
- desc: "选择项目名称"
  keyword: "click_element"
  params:
    locator: "${question_elements.project_name_select}"

# ❌ 错误写法（硬编码 locator）
- desc: "选择项目名称"
  keyword: "click_element"
  params:
    locator: "xpath=//div[contains(@class,'el-select')]"
```

### 5.5 Cookie 过期替换

当运行测试报认证失败（页面跳转到登录页）时，说明 Cookie 已过期：

**步骤 1：重新获取 Cookie**

1. 用浏览器重新登录被测系统
2. **F12** → **Network** → 任意请求 → **Headers** → **Cookie** → 整串复制

**步骤 2：更新 config.yaml**

打开项目根目录下的 `config.yaml`，替换 cookie 字段：

```yaml
# config.yaml
cookie: "ud_token=新的token值; session_id=新的session值"   # ← 替换为新的
cookie_domain: "100.71.19.25"                               # ← 域名不变
```

**步骤 3：如果需要同步 localStorage**

某些系统的 token 同时存在 Cookie 和 localStorage 中，需同步更新：

```yaml
# config.yaml
local_storage:
  ud_token: "新的token值"   # ← 与 cookie 中的值一致
```

**步骤 4：重新运行**

```bash
python run.py
```

> **提示**：也可以直接告诉 AI "Cookie 过期了，新的 Cookie 是 xxx"，AI 会自动更新 config.yaml。

### 5.6 让 AI 修复（推荐）

如果对定位器逻辑不熟悉，可以直接描述问题让 AI 修复：

```
/generate-ui-test 项目 D:/projects/my-system 运行出错：
- 01_create.yaml 第6步 Timeout：定位器找不到元素
- 03_edit.yaml 第12步 strict mode violation：匹配到2个元素
请修复。
```

AI 会分析错误、重新探测、修改定位器、重新验证。提供越详细的错误信息，修复越准确。

---

## 附录 A：生成的项目目录结构

```
my-system/
├── run.py                          # 运行入口
├── config.yaml                     # 环境配置（URL、Cookie、浏览器）
│
├── pages/                          # 页面元素定位器
│   ├── common/common.yaml          # 通用定位器（loading、toast）
│   └── {module}/elements.yaml      # 模块页面定位器
│
├── data/                           # 参数化测试数据
│   ├── common/common_data.yaml     # 公共数据（target_url 等）
│   └── {module}/data.yaml          # 模块测试数据
│
├── cases/                          # 测试用例
│   └── {module}/
│       ├── 01_create.yaml
│       └── 02_edit.yaml
│
├── suites/                         # 测试套件
│   └── {module}/smoke.yaml
│
├── lib/                            # 运行时关键字
│   ├── auth_keywords.py            # 认证注入
│   └── module_keywords.py          # 模块级 L3 关键字
│
├── _knowledge/                     # 模块知识库（workflow 定义）
├── _probe/                         # 探测结果（discovery JSON，自动生成）
├── files/                          # 运行时文件（截图、下载）
└── report/                         # HTML 报告
    ├── generate_report/            # 脚本生成报告 (Phase 8)
    └── run_report/                 # 运行结果报告 (Phase 9)
```

---

## 附录 B：常用命令速查表

### 运行测试

```bash
# 运行所有套件（一个报告）
python run.py --all

# 运行所有套件（每个套件一个报告）
python run.py

# 运行指定模块
python run.py --module question-manage

# 运行指定套件文件
python run.py suites/question-manage/smoke.yaml
```

### 查看已注册的关键字

```bash
# 查看引擎内置关键字 + 项目自定义关键字列表
python -c "from UIEngine.keywords.keyword_manager import KeyWordManager; [print(k) for k in sorted(KeyWordManager.maps.keys())]"
```

> 在项目目录下运行，会自动加载 `lib/` 中的自定义关键字（auth_keywords + module_keywords）。
