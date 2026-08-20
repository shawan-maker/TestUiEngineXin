# generate-ui-test

基于 UIEngine 的 UI 自动化测试工程生成技能。

## 快速开始

在 Claude Code 中输入以下任意触发词即可开始：
- `/generate-ui-test`
- "生成UI测试脚本"
- "创建自动化测试"
- "从Excel生成测试"

---

## 用户操作指南

### 第一步：启动技能并确认项目信息

**第一次输入**：/generate-ui-test 在xx目录下创建项目进行ui自动化

**后续输入**：/generate-ui-test   在xxx项目下，针对如下用例进行UI自动化脚本编写及执行，给出结果的汇总和问题分析。

AI 会向您确认以下信息：

> 请确认以下信息：
> 1. 项目名称？
> 2. 模块名称？（不指定默认 common）
> 3. 被测系统 URL？
> 4. 浏览器类型？（默认 chromium）
> 5. 输入来源：自然语言 / Excel / CSV？
> 6. 认证方式？（默认 none）

**你的回答示例：**
```
项目名称：login-test
模块：登录
URL：https://example.com
浏览器：chromium
输入：自然语言
认证方式：cookie
```

### 第二步：安装依赖

在生成工程之前，先确保依赖已安装：

```bash
pip install ui_engine_xin pyyaml openpyxl
playwright install chromium
```

### 第三步：提供测试用例

根据输入方式选择以下其中一种：

#### 方式 A：自然语言描述（推荐新手）

直接用中文描述你的测试步骤，AI 自动理解并生成代码。

**你的输入示例：**

```
帮我生成登录模块的测试用例：

用例1：正确密码登录
1. 访问 /login 页面
2. 在用户名输入框中输入 admin
3. 在密码输入框中输入 123456
4. 点击登录按钮
5. 验证页面显示"欢迎，admin"

用例2：错误密码登录
1. 访问 /login 页面
2. 在用户名输入框中输入 admin
3. 在密码输入框中输入 wrong
4. 点击登录按钮
5. 验证页面提示"密码错误"
```

#### 方式 B：Excel / CSV 文件

准备一个 Excel 或 CSV 文件，只需 3 列：

| 模块 | 用例名称 | 用例步骤 |
|------|---------|---------|
| 登录 | 正确密码登录 | 1. 访问 /login 页面<br>2. 在用户名输入框中输入 admin<br>3. 在密码输入框中输入 123456<br>4. 点击登录按钮<br>5. 验证页面显示"欢迎，admin" |
| 登录 | 错误密码登录 | 1. 访问 /login 页面<br>2. 在用户名输入框中输入 admin<br>3. 在密码输入框中输入 wrong<br>4. 点击登录按钮<br>5. 验证页面提示"密码错误" |

**格式要点：**
- 每行 = 一条完整用例
- 用例步骤列用编号列表（`1.` `2.` `3.`…）书写全部步骤
- Excel 中步骤换行：在单元格内按 **Alt + Enter**
- 列名不同也没关系，AI 会询问映射

### 第四步：AI 自动解析并生成

AI 会自动完成以下工作（无需额外操作）：

1. **全自动探测** — 打开真实页面，自动扫描所有交互元素（按钮、输入框、下拉框、行按钮等）
2. **运行时验证定位器** — 在浏览器中验证每个 XPath 是否可用（count==1）
3. **生成四类文件**：
   - `pages/` — 页面元素定位器（经探测验证）
   - `data/` — 参数化测试数据（结构相似的用例自动提取）
   - `cases/` — 测试用例（完整步骤 + 关键字）
   - `suites/` — 测试套件（编排用例执行顺序）
4. **跨文件验证** — 检查 YAML 语法和引用完整性

### 第五步：运行测试

```bash
cd login-test
python run.py --all                     # 运行全部用例（含子目录，一次执行，一个报告）
python run.py --module login            # 运行指定模块（自动合并子目录用例）
python run.py suites/login/smoke.yaml   # 运行指定套件
python run.py                           # 运行所有套件（按模块自动合并子目录用例）

# 调试模式（失败时暂停，支持手动干预）
python run.py --all --debug             # 启用调试模式，默认最多重试3次
python run.py --all --debug --max-retries 5  # 自定义最大重试次数
python run.py --module login --debug    # 指定模块调试模式
```

**调试模式交互**：
- 测试失败时，浏览器保持打开状态
- 输入 `r`：重试当前用例（从头执行，包含环境隔离步骤）
- 输入 `s`：跳过当前用例，继续执行后续用例
- 输入 `q`：终止全部执行，生成报告
- 非交互式环境（CI/CD）自动降级为跳过模式

---

## 关键字使用原则

测试用例中**优先使用 UIEngine 封装的关键字**，保证可读性和可维护性：

| 优先级 | 关键字 | 说明 |
|:------:|--------|------|
| 1 | `click_element` | 点击按钮、链接等 |
| 1 | `fill_value` | 输入框填写内容 |
| 1 | `click_select_option` | 下拉框选择（原生 select 或非 Element UI） |
| 1 | `wait_for_element` / `wait_for_element_hidden` | 等待元素出现/消失 |
| 1 | `except_to_be_visible` | 断言验证（统一使用可见性断言） |
| 2 | `execute_script` | **仅当上述方法不可用时**作为后备 |

> `execute_script` 中的 JS 脚本不支持 `${variable}` 变量替换，且测试人员不易维护，应尽量避免。

**Element UI 已知引擎方法失效场景**（需使用 `execute_script` 后备）：

| 场景 | 失效原因 | 后备方案 |
|------|---------|---------|
| el-select 选项选择 | `:visible` 伪类对 Element UI 全局失效 | 使用纯 XPath 定位 + `click_element` 展开选择 |
| 等待 drawer/dialog 出现 | visibility 检查失效 | `wait_for_time` |
| TinyMCE 编辑器填写 | textarea 有 `aria-hidden` | `execute_script` + TinyMCE API |
| 断言 toast 成功消息 | toast 可能太快消失 | `except_to_be_visible` 验证页面正常 |

---

## 认证配置指南

### 方式一：用户名密码登录（无需配置）

适用于：系统使用用户名+密码登录，**验证码已关闭或使用固定值**。

在测试用例中正常编写登录步骤即可，无需额外配置。

> **关于验证码**：建议联系开发在测试环境关闭验证码，或设置万能验证码（如 `0000`）。

### 方式二：Cookie 认证（推荐）

适用于：登录有动态验证码，无法通过浏览器自动登录。

**操作步骤：**

1. 用浏览器手动登录被测系统
2. 按 F12 → Network → 任意请求 → Headers → Cookie → 整串复制
3. 填入 `config.yaml`：

```yaml
# config.yaml
cookie: "ud_token=eyJhbGci...; lang=zh-CN"    # 整串粘贴即可
cookie_domain: "100.71.19.25"                  # Cookie 所属域名
```

引擎在 `open_browser` 时**自动注入** Cookie，无需在 suite 中添加额外步骤。

> **注意**：Cookie 有过期时间，过期后需重新手动登录并更新 `config.yaml` 中的值。

### 方式三：Token 请求头认证

适用于：前后端分离系统，通过 Authorization 请求头携带 Bearer Token。

```yaml
# config.yaml
# 在 suite 的 setup_step 中使用 inject_token_header 关键字
token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### 方式四：localStorage 认证

适用于：前端框架将 Token 存储在 localStorage 中。

```yaml
# config.yaml
# 在 suite 的 setup_step 中使用 inject_local_storage 关键字
storage_key: "access_token"
storage_value: "eyJhbGciOiJIUzI1NiIs..."
storage_navigate_url: "/login"
```

### 认证方式对比

| 方式 | 适用场景 | 凭据来源 | 注入方式 |
|------|---------|---------|---------|
| 用户名密码 | 无验证码或验证码固定 | 写在用例步骤中 | 无需注入 |
| Cookie | 有验证码，无法自动登录 | DevTools 复制 | 引擎自动注入 |
| Header Token | 前后端分离 | DevTools 或 API | setup_step 手动注入 |
| localStorage | 前端 Token 存储 | 同上 | setup_step 手动注入 |

---

## 生成的工程结构

```
{project_name}/
├── run.py                    # 运行入口
├── config.yaml               # 环境配置（浏览器、URL、Cookie、localStorage）
├── pages/{module}/           # 页面元素定位器（经 probe 验证）
├── data/{module}/            # 参数化测试数据
├── cases/{module}/           # 测试用例（完整步骤 + 引擎关键字，支持子目录自动发现）
├── suites/{module}/          # 测试套件（编排用例顺序）
├── lib/                      # 运行时关键字（auth + L3 模块关键字）
├── _knowledge/               # 模块级知识库（workflow 定义 → 编译为 L3 关键字）
├── _probe/                   # 探测结果（discovery JSON，自动生成）
├── files/                    # 截图/日志/下载（运行时自动创建）
└── report/                   # HTML 测试报告
    ├── generate_report/      # 脚本生成报告 (Phase 8)
    └── run_report/           # 运行报告 (Phase 9)
```

> **子目录用例自动发现**：`cases/<module>/<subdir>/` 下的用例无需注册到 suite 的 `case_refs`，`--all`、`--module`、无参数三种模式均会自动扫描子目录并合并执行。同级根目录下未引用的用例视为有意排除，不会被自动发现。

## 单独运行各阶段（高级用法）

当需要调试或重新生成特定模块时，可以单独运行各个阶段，而不必重跑整个 pipeline。

### Phase 4：页面探测（discover_page.py）

探测指定模块的页面元素，生成 `discovery_{module}.json`。

**命令格式：**
```bash
python .claude/skills/generate-ui-test/tools/probe/run_phase4.py \
  --excel "path/to/test_cases.xlsx" \
  --config "path/to/project/config.yaml" \
  --project "path/to/project" \
  --cookie "cookie_string_here" \
  --module "模块名称" \
  --local-storage '{"key1":"value1","key2":"value2"}'
```

**参数说明：**
- `--excel`：Excel 测试用例文件路径（**必填**）
- `--config`：项目 config.yaml 路径（**必填**）
- `--project`：项目根目录路径（**必填**）
- `--cookie`：Cookie 字符串（可选，默认从 config.yaml 读取）
- `--module`：限定单个模块名称（可选，不指定则处理所有模块）
- `--local-storage`：localStorage 注入，JSON 对象格式（可选）
- `--skip-discover`：跳过探测步骤，使用已有的 discovery JSON（可选）
- `--skip-generate`：跳过 pages 生成步骤（可选）

**示例：**
```bash
# 仅探测 ecsCloud2 项目的 order 模块
python .claude/skills/generate-ui-test/tools/probe/run_phase4.py \
  --excel "examples/ecsCloud2/测试用例.xlsx" \
  --config "examples/ecsCloud2/config.yaml" \
  --project "examples/ecsCloud2" \
  --cookie "session=abc123; user=admin" \
  --module "order"
```

**输出：**
- `_probe/discovery_{module}.json`：探测结果 JSON 文件

---

### Phase 5：代码生成（generate_from_excel.py）

根据 Excel 测试用例和探测结果，生成 case/data/pages 文件。

**命令格式：**
```bash
python .claude/skills/generate-ui-test/tools/generation/generate_from_excel.py \
  "path/to/excel_parsed.json" \
  --discovery-dir "path/to/project/_probe" \
  --output-dir "path/to/project" \
  --module-map "中文名1=slug1,中文名2=slug2" \
  --module-slug "target_module_slug"
```

**参数说明：**
- `excel_parsed.json`：Excel 解析后的 JSON 文件（**必填**，位置参数）
- `--discovery-dir`：discovery JSON 目录，通常是 `{project}/_probe/`（**必填**）
- `--output-dir`：项目根目录（**必填**）
- `--module-map`：中英文模块映射，逗号分隔，格式 `"中文名=slug"`（可选）
- `--module-slug`：限定单个模块 slug，仅生成该模块的代码（可选）
- `--skip-pages`：跳过 pages YAML 生成（如果已存在）
- `--skip-filter`：跳过 v2 有效性过滤（慎用，可能生成无效元素和数据）

**示例：**
```bash
# 仅生成 order 模块的代码
python .claude/skills/generate-ui-test/tools/generation/generate_from_excel.py \
  "examples/ecsCloud2/_probe/excel_parsed.json" \
  --discovery-dir "examples/ecsCloud2/_probe" \
  --output-dir "examples/ecsCloud2" \
  --module-map "订单管理=order,用户管理=user" \
  --module-slug "order"
```

**输出：**
- `cases/{module}/`：测试用例文件
- `data/{module}/`：测试数据文件
- `pages/{module}/`：页面元素定位器文件

---

### Phase 6：定位器验证（verify_locators.py）

在浏览器中验证生成的定位器是否正确，更新 pages 文件中的 `[VERIFIED]` 标记。

**命令格式：**
```bash
python .claude/skills/generate-ui-test/tools/verification/verify_locators.py \
  "path/to/project" \
  --cookie "cookie_string_here" \
  --url "http://target-url" \
  --module "module_slug" \
  --headed
```

**参数说明：**
- `project_dir`：项目根目录（**必填**，位置参数）
- `--cookie`：Cookie 字符串（**必填**，用于登录态）
- `--url`：目标系统 URL（**必填**）
- `--module`：模块名称（可选，不指定则验证所有模块）
- `--headed`：有头模式运行浏览器，可以看到操作过程（可选）

**示例：**
```bash
# 验证 order 模块的定位器（有头模式）
python .claude/skills/generate-ui-test/tools/verification/verify_locators.py \
  "examples/ecsCloud2" \
  --cookie "session=abc123; user=admin" \
  --url "http://10.151.37.249" \
  --module "order" \
  --headed
```

**输出：**
- 更新 `pages/{module}/elements.yaml` 中的 `[VERIFIED]` 标记
- 生成 `_probe/verification_report_{module}.json` 验证报告

---

### 完整的单模块调试流程

当你需要重新生成某个模块时，按以下顺序执行：

```bash
# 1. 清理旧产物（可选，谨慎操作）
rm -f examples/ecsCloud2/_probe/discovery_order.json
rm -rf examples/ecsCloud2/cases/order
rm -rf examples/ecsCloud2/data/order
rm -rf examples/ecsCloud2/pages/order

# 2. Phase 4：重新探测
python .claude/skills/generate-ui-test/tools/probe/run_phase4.py \
  --excel "examples/ecsCloud2/测试用例.xlsx" \
  --config "examples/ecsCloud2/config.yaml" \
  --project "examples/ecsCloud2" \
  --module "order"

# 3. Phase 5：重新生成代码
python .claude/skills/generate-ui-test/tools/generation/generate_from_excel.py \
  "examples/ecsCloud2/_probe/excel_parsed.json" \
  --discovery-dir "examples/ecsCloud2/_probe" \
  --output-dir "examples/ecsCloud2" \
  --module-slug "order"

# 4. Phase 6：验证定位器
python .claude/skills/generate-ui-test/tools/verification/verify_locators.py \
  "examples/ecsCloud2" \
  --cookie "session=abc123; user=admin" \
  --url "http://10.151.37.249" \
  --module "order"

# 5. 检查验证报告
cat examples/ecsCloud2/_probe/verification_report_order.json
```

**注意事项：**
- Phase 4 依赖 Excel 和 config.yaml，确保文件存在且格式正确
- Phase 5 依赖 Phase 4 的 discovery JSON 和 excel_parsed.json
- Phase 6 依赖 Phase 5 生成的 pages/cases/data 文件
- 清理旧产物时，建议先备份再删除
- `--module` 参数使用模块中文名（如 "订单管理"），`--module-slug` 使用 slug（如 "order"）

## 常见问题

**Q：用例 ID 怎么来的？**
A：AI 根据模块名和用例名称自动生成（如"正确密码登录"→ `login-correct-password`）。

**Q：元素定位不准确怎么办？**
A：直接编辑 `pages/` 目录下对应文件中的选择器即可。修改后建议重新运行 Phase 6 验证：
```bash
python .claude/skills/generate-ui-test/tools/verify_locators.py {project} \
  --cookie "..." --url "..." --module "{module}"
```

**Q：Cookie/Token 过期了怎么办？**
A：重新手动登录获取新值，更新 `config.yaml` 即可。无需重新生成工程。

**Q：系统有验证码怎么处理？**
A：推荐让开发在测试环境关闭验证码。如果无法关闭，使用 Cookie 认证方式跳过登录。
