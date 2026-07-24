---
name: generate-ui-test
description: 基于 UIEngine 生成可独立运行的 UI 自动化测试工程。支持自然语言、Excel、CSV 输入，自动参数化，按模块组织。
triggers:
  - 生成UI测试脚本
  - 创建自动化测试
  - 生成测试工程
  - 从Excel生成测试
  - 从CSV生成测试
allowed-tools:
  - Read
  - Write
  - Bash
---

# generate-ui-test

基于 UIEngine 生成可独立运行的 UI 自动化测试工程。

## 🚨 全局强制约束（优先级最高，生成任何文件前必须确认）

> **以下 3 条约束适用于所有阶段、所有文件，违反即阻断。**

**① 全 XPath 定位器 — 禁止一切 CSS**

所有定位器**必须使用 XPath 格式**，包括路径补齐。以下全部禁止：

| 禁止 | 示例 |
|------|------|
| CSS 选择器 | `.el-drawer`、`.el-loading-mask`、`button.btn` |
| CSS >> XPath 混合 | `.el-select >> xpath=.//...` |
| Playwright CSS | `button:has-text('新增')`、`input[placeholder='...']` |
| `css=` 前缀 | `css=.el-table__row` |
| Playwright 操作符 | `nth=0`、`nth=1`（用 XPath `[1]`、`[2]` 替代） |

```yaml
# ✅ 纯 XPath
locator: "xpath=//button[contains(.,'新增')]"
# ✅ 路径补齐用 XPath [1]
locator: "xpath=(//div[contains(@class,'el-table__body-wrapper')]//tr)[1]"
# ❌ 禁止 nth=0
locator: "${var} >> nth=0"
# ❌ 禁止 CSS
locator: ".el-select >> xpath=.//input"
```

**② 断言统一使用 `except_to_be_visible` — 禁止 `except_to_have_text`**

所有断言（成功提示、字段值验证、数据校验）**统一使用 `except_to_be_visible` + 通用文本定位器**：

```yaml
# ✅ 唯一允许的断言方式
- keyword: except_to_be_visible
  params: {locator: "${common_elements.success_text}"}

# ❌ 禁止 — except_to_have_text / except_to_have_value / except_to_have_attribute
- keyword: except_to_have_text
  params: {locator: "...", expect_results: "..."}
```

pages YAML 中定义通用断言定位器：
```yaml
common_elements:
  success_text: "xpath=//*[contains(.,'成功')]"
  error_text: "xpath=//*[contains(.,'失败')]"
```

**③ 全变量引用 — case 禁止硬编码定位器和业务数据**

case 中所有 locator 引用 `pages/`（`${group.field}`），所有 value 引用 `data/`（`${group.field}`）。

**④ 定位器模式参考 — 16 类已验证 XPath**

生成任何定位器前，参考 `knowledge/locator-patterns.md`（16 类操作模式 + 速查表），所有 XPath 表达式已在目标系统中验证，只需替换对应的数据/文本/按钮名称即可使用。

**⑤ 工具链强制 — pages YAML 必须工具生成，禁止手写**

> **此约束优先级等同于 ①②③，违反即阻断。**

| 资源 | 生成方式 | 禁止 |
|------|---------|------|
| pages + cases + data | `generate_from_excel.py`（v2 统一编排，direct import） | 分别手动调用旧工具 |
| pages YAML | `_pages_writer.py`（由编排工具内部调用） | 手动抄写 locator |
| pages 验证 | `verify_locators.py`（Phase 3f 强制运行） | 跳过验证 |
| pages option locator | `_pages_writer.py`（自动生成） | 手写选项 XPath |
| case YAML | `_case_generator.py`（由编排工具内部调用）或严格按模板手写 | 自由编排步骤 |

**例外**：`common_elements`（success_text、loading_mask 等通用断言/等待定位器）和 `detail_page_elements`（详情页字段，probe 通常无法覆盖）允许手动追加到 pages YAML 末尾。

**⑥ 阶段门禁强制 — 验证器自动检查前置阶段**

`validate_05` 运行时自动检查 Phase 3/3f/3.5 的执行证据（`_phase_registry.py`）。
如果前置阶段未执行，输出 `PREREQUISITE` error 并阻断。
不可绕过（无 `--skip-prerequisites` 参数）。

检查项：
- `_probe/discovery_*.json` ≥1 个 或 `_probe/probe_*.json` ≥1 个（Phase 3）
- `_probe/verify_result.json` 存在 或 `_probe/probe_supplement*.json` 存在（Phase 3f）
- `lib/module_keywords.py` 存在（Phase 3.5，仅当 `_knowledge/` 非空时）

---

## ⚠️ 强制规则（生成任何文件前必须阅读）

规则已拆分为 7 个阶段文件，每个阶段开始前必须阅读对应规则：

| 阶段 | 规则文件 | 验证器 |
|------|---------|--------|
| Phase 0 配置确认 | `rules/01_rule_config_confirmation.md` | `validators/validate_01_config.py [--runtime-check]` |
| Phase 0.5 Excel 预检（Excel 时必询问） | — | `tools/validate_excel.py`（L1/L2 自动修复 + L3 解析能力验证） |
| Phase 1 脚手架生成 | `rules/02_rule_scaffold_generation.md` | `validators/validate_02_scaffold.py` |
| Phase 3 全自动探测 | `rules/04_rule_element_probing.md` | `validators/validate_04_probe.py` |
| Phase 3f 运行时定位器验证（🚨强制） | — | `tools/verify_locators.py`（KB+discovery 验证+回写） |
| Phase 3.5 模块关键字编译 | — | `tools/compile_module_keywords.py` + `validators/validate_03_5_keywords.py` |
| Phase 4 脚本生成 | `rules/05_rule_script_generation.md` | `validators/validate_05_scripts.py` |
| Phase 5 报告生成 | `rules/06_rule_report_generation.md` | `validators/validate_06_report.py` |
| Phase 6 运行验证 | `rules/07_rule_execution_validation.md` | `validators/validate_07_execution.py` |

**每个阶段完成后必须运行对应验证器，error > 0 时必须修复后才能进入下一阶段。**

## 前置条件

```bash
pip install ui_engine_xin pyyaml openpyxl
playwright install chromium
```

## 工程结构

```
{project_name}/
├── run.py                    # 运行入口（来自 templates/run.py.tpl，禁止手动创建）
├── config.yaml               # 环境配置（Cookie、localStorage 集中维护）
├── .gitignore                # 排除运行时产物
├── pages/{module}/           # 页面定位器（元素选择器，不含业务数据）
├── data/{module}/            # 测试数据（URL、输入文本、期望值、搜索关键词）
├── cases/{module}/           # 测试用例（步骤流程，全部用 ${group.field} 引用）
├── suites/{module}/          # 测试套件（仅编排用例顺序 + 前置步骤）
├── lib/                      # 运行时关键字（auth + L3 模块关键字）
├── _knowledge/               # 模块级知识库（workflow 定义，编译为 L3 关键字）
├── _probe/                   # harvest/probe 探测结果（自动生成，已 gitignore）
├── files/                    # 运行时截图、日志、下载（自动生成，已 gitignore）
└── report/                   # HTML 测试报告（自动生成，已 gitignore）
    ├── generate_report/      # 脚本生成报告 (Phase 5)
    ├── run_report/           # 运行报告 (Phase 6)
    └── issues_report/        # 问题分析报告 (Phase 5+6 联合)
```

四层目录的模块名必须一致（R4.1），case 文件名必须含序号前缀（R4.5）。

## 执行流程

### Phase 0: 配置确认

**逐项询问用户**，每个问题单独一次 AskUserQuestion，不要合并多个问题：

1. **项目名称** — 如未指定，从目录名推断
2. **目标系统 URL** — 必填
3. **模块名称** — 未指定时默认 `common`
4. **浏览器类型** — 默认 chromium
5. **输入来源** — 自然语言 / Excel / CSV
6. **认证方式**（默认 none）：
   - `none` — 用户名密码登录，通过用例步骤操作登录页面
   - `cookie` — 手动提供 Cookie，自动注入浏览器上下文
   - `header` — Bearer Token 注入 Authorization 请求头
   - `localStorage` — Token 写入浏览器 localStorage

每次只问一个问题，等用户回答后再问下一个。可从上下文推断的值直接跳过询问。

**收集 Cookie 值的正确方式**：

当用户选择 `cookie` 认证时，**直接输出提示消息**，不要用 AskUserQuestion 分步询问：

> 请在下方发送您的 Cookie 字符串：
> 获取方式：浏览器 F12 → Network → 任意请求 → Headers → Cookie → 整串复制粘贴
> （如果暂时无法获取，可以稍后手动编辑 config.yaml 的 cookie 字段）

用户发送后，整串填入 config.yaml 的 `cookie` 字段。

**可选：收集 localStorage 用户信息**（非必填）：

某些系统需要 localStorage 中的用户身份信息。当用户已提供 Cookie 后，询问是否需要，如需要引导用户执行：

> `copy(JSON.stringify(Object.fromEntries(Object.entries(localStorage))))`

收到 JSON 后保留所有字段，写入 config.yaml 的 `local_storage` 段。

**验证**：

```bash
# 静态检查（配置格式）
python .claude/skills/generate-ui-test/validators/validate_01_config.py {config_file}

# 运行时检查（认证有效性 + UI 框架检测，cookie 认证时必执行）
python .claude/skills/generate-ui-test/validators/validate_01_config.py {config_file} --runtime-check
```

| 结果 | 处理方式 |
|------|---------|
| 0 errors | 进入 Phase 0.5 或 Phase 1 |
| R0.6 error（认证无效） | 提示用户重新提供 Cookie，不进入后续阶段 |
| >0 errors | 修复后重新验证 |

运行时检查输出 `_probe/auth_check.json`，包含 `auth_valid`（认证是否有效）和 `ui_framework`（检测到的 UI 框架，为未来多框架支持预留）。

### Phase 0.5: Excel 用例预检（可选）

> **仅当输入来源为 Excel 时执行。** 此阶段对 Excel 用例进行三层验证：L1 格式清洗、L2 语义修复、L3 解析能力验证（确保每个步骤能被 `parse_step()` 分类）。

**用户选择**：

在 Phase 0 确认输入来源为 Excel 后，**必须使用 AskUserQuestion 工具**询问用户是否执行预检：

> Excel 用例预检可以自动检查并修复常见问题（断言关键词不统一、数据污染、步骤编号等），
> 并验证每个步骤是否能被系统解析（L3 解析能力验证）。是否执行预检？
> - **执行预检**（推荐）：自动修复 L1/L2 问题 + L3 解析验证（不通过则阻断）
> - **跳过预检**：直接使用原始 Excel 文件

如果用户选择跳过，直接进入 Phase 1，后续流程使用原始 Excel 文件。

**执行步骤**：

1. **运行 validate_excel.py（L1 + L2 + L3）**：

```bash
python .claude/skills/generate-ui-test/tools/validate_excel.py "{excel_file}"
```

**验证层**：
- **L1 格式清洗**（自动修复）：断言关键词统一、引号标准化、步骤编号修正、注释/分隔符过滤（R21/R22）
- **L2 语义修复**（自动修复）：el-select 等待补充、组件类型修正、级联选择器识别
- **L3 解析能力验证**（阻断式）：
  - 每个步骤调用 `parse_step()` 分类，`unknown` = error + 修改建议
  - `l3_call` 步骤的 workflow 必须在三层定义中存在（系统级 + 技能级 `_knowledge/` + 项目级）
  - `l3_call` 参数数量必须匹配 workflow 定义

**退出码**：
- `0` = L3 通过（无问题直接用原文件，或 L1/L2 已自动修复生成修正版）
- `1` = L3 解析验证失败（阻断，需修改 Excel 后重跑）

**输出文件**（仅当有修复时生成，原文件不会被修改）：
- `{原始文件名}-修正版.xlsx` — L1/L2 自动修复后的文件（L3 通过时）
- `excel_validation_report.html` — 修改前后对照报告（始终生成）

**不生成副本的条件**：如果 L1/L2 零修复且 L3 通过，说明 Excel 已经是干净状态，不会生成 `-修正版.xlsx`，后续直接使用原始文件。

2. **告知用户结果**：

**L3 通过（exit 0）**：
```
Excel 预检通过，L1/L2 自动修复了 N 处问题：
- L1 自动修复: X 处（数据清洗、断言关键词、步骤编号等）
- L2 自动修复: Y 处（el-select 等待、组件类型标注等）
- L2 待确认: Z 处（操作对象缺失等，详见报告）
后续流程将使用修正版文件: {路径}
```

**L3 阻断（exit 1）**：
```
❌ L3 解析验证失败: N 个步骤无法识别
  L1 自动修复: X 处 | L2 自动修复: Y 处 | L3 错误: N 处
修正版（L1/L2 已修复部分）: {路径}
报告: {报告路径}
请修改 Excel 中的问题步骤后重新运行。
```

3. **L3 AI 语义审查**（Claude 自身执行，利用上下文）：

读取通过 L3 验证的 Excel，以已调试通过的 sheet 为参照基准，逐 sheet 检查：

- **复制粘贴错误**：模块名/页面名与用例内容不匹配（如项目管理中出现"新增问题窗口"）
- **业务逻辑矛盾**：操作与断言不匹配（如编辑操作后断言状态为"处理中"）
- **用例完整性**：缺少必要的等待/确认步骤

将 L3 AI 审查问题汇总报告给用户，用户确认后手动修正 Excel 或由 Claude 补充修正。

4. **确定后续使用的 Excel 文件路径**：

| 情况 | 后续使用的文件 |
|------|--------------|
| 用户跳过预检 | 原始 Excel 文件 |
| 预检 L3 通过 + L1/L2 零修复 (exit 0) | 原始 Excel 文件（不生成副本） |
| 预检 L3 通过 + L1/L2 有修复 (exit 0) | 修正版 Excel 文件 |
| 预检 L3 阻断 (exit 1) | 用户修改后重跑 |
| L3 AI 审查有问题 | 用户修正后的文件 |

> **重要**：后续 Phase 4 中 `generate_from_excel.py` 的输入文件必须使用此阶段确定的文件路径。validate_excel.py 的终端输出会明确打印"后续流程使用: {路径}"。

### Phase 1: 脚手架生成

读取 `templates/` 目录下所有 `.tpl` 文件，用 Phase 0 确认的值填充模板变量：

| 模板变量 | 来源 |
|----------|------|
| `{{project_name}}` | Phase 0 项目名称 |
| `{{module}}` | Phase 0 模块名称 |
| `{{target_url}}` | Phase 0 目标系统 URL |
| `{{browser_type}}` | Phase 0 浏览器类型 |

```bash
cp templates/run.py.tpl {project_name}/run.py
cp templates/config.yaml.tpl {project_name}/config.yaml
cp templates/auth_keywords.py.tpl {project_name}/lib/auth_keywords.py
cp templates/auto_learn_keywords.py.tpl {project_name}/lib/auto_learn_keywords.py
touch {project_name}/lib/__init__.py
cp templates/.gitignore.tpl {project_name}/.gitignore
cp templates/README.md.tpl {project_name}/README.md
mkdir -p {project_name}/{pages,data,cases,suites}/{module}
mkdir -p {project_name}/{pages,data,cases,suites}/common
mkdir -p {project_name}/_probe {project_name}/files/{logs,shortcuts,downloads} {project_name}/report/{generate_report,run_report}
# 创建 common_data.yaml（供 suite setup_step 通过 ${common_data.target_url} 引用）
printf "common_data:\n  target_url: \"%s\"\n" "{{target_url}}" > {project_name}/data/common/common_data.yaml
```

**禁止手动创建 run.py**：run.py.tpl 包含所有必要的辅助函数（`deep_merge`、`flatten_dict`、`load_yaml_recursive`、`load_cases`、`resolve_suite`、`run_suite`）。

**检查已有项目**：

```bash
ls {project_name}/run.py 2>/dev/null
```

- **已存在** → 复用现有项目，仅追加新模块目录
- **不存在** → 创建脚手架

> **禁止删除已有项目**。

**认证步骤处理**：
- `none`：不插入认证步骤
- `cookie`：填入 config.yaml 的 `cookie` + `cookie_domain`，引擎自动注入
- `header`：setup_step 中插入 `inject_token_header`
- `localStorage`：setup_step 中插入 `inject_local_storage`（从 config.yaml 读取，零硬编码）

**浏览器视口**：引擎已内置自动最大化，不需要 `set_viewport_size`。

**suite setup_step 标准模板**：
```yaml
setup_step:
  - desc: "打开浏览器"
    keyword: "open_browser"
    params: {browser_type: "chromium"}
  - desc: "导航到目标域"
    keyword: "open_url"
    params: {url: "${common_data.target_url}"}
  - desc: "注入认证信息"
    keyword: "inject_local_storage"
  - desc: "刷新使认证生效"
    keyword: "refresh"
  - desc: "等待页面加载完成"
    keyword: "wait_for_element_hidden"
    params: {locator: "${common_elements.loading_mask}", timeout: 15000}
```

**验证**：

```bash
python .claude/skills/generate-ui-test/validators/validate_02_scaffold.py {project_name}
```

### Phase 3: 全自动广撒网探测

> **此阶段替代旧 probe_element.py 管线。** 使用 `discover_page.py` 自动扫描所有交互元素，无需手动编排 `--element` 参数。

{{ include "knowledge/keyword_spec.md" }}

{{ include "knowledge/locator-patterns.md" }}

#### 3a. URL 收集

从 config.yaml `page_urls` 或 Excel 中 `open_url` 步骤获取每个模块的 URL 列表：

```bash
# 从 Excel 自动提取 URL（可选）
python .claude/skills/generate-ui-test/tools/read_excel.py "{excel_file}" \
  --extract-urls --output {project_name}/_probe/module_urls.json
```

#### 3b. 全自动探测

对每个模块的每个 URL 运行广撒网探测：

```bash
python .claude/skills/generate-ui-test/tools/discover_page.py "{url}" \
  --cookie "name=value;..." \
  --module "{module_slug}" \
  --output {project_name}/_probe/discovery_{module_slug}.json
```

**探测内容**：
- 列表页：按钮、输入框、el-select、行按钮、tabs、详情链接
- 容器内元素：自动点击按钮后检测 drawer/dialog/message-box，扫描容器内所有元素
- 行按钮：hover 触发的操作按钮 + "更多"展开菜单
- 一层探测不递归（容器内元素不继续点击）

**多URL支持**：当模块有多个 URL 时，输出 `pages[]` 数组，每个 URL 的元素独立存储。

#### 3c. 生成 pages YAML

> **注意**：Phase 3c 和 4a 已合并为 `generate_from_excel.py` 统一编排工具。以下步骤由编排工具自动执行，通常不需要手动运行。

```bash
# 由 generate_from_excel.py 自动调用（v2: direct import _pages_writer）。
# 手动调试时使用:
python -c "
import sys; sys.path.insert(0, '.claude/skills/generate-ui-test/tools')
from _pages_writer import generate_pages_yaml_from_discovery
generate_pages_yaml_from_discovery(
    '{project_name}/_probe/discovery_{module_slug}.json',
    '{project_name}/pages/{module_dir}/elements.yaml',
    '{中文模块名}', '{module_slug}')
"
```

**Group 命名规则**（F2/F3/F4 修复后）：
- 单URL模块：`{module_slug}_elements`
- 多URL模块：`{module_slug}_{page_slug}_elements`（每个页面独立 group）
- 容器 group：`{module_slug}_{container_type}_{trigger}_elements`（如 `question_drawer_add_elements`）
- common_elements：通用定位器（确定/取消/加载中...）

**验证**：

```bash
python .claude/skills/generate-ui-test/validators/validate_04_probe.py {project_name}
```

| 结果 | 处理方式 |
|------|---------|
| 0 errors | 进入 Phase 4a |
| >0 errors | 修复定位器后重新探测 |
| warnings only | 人工确认，不阻塞 |

### Phase 3f: 运行时定位器验证（🚨 强制，不可跳过）

> **此阶段在 Phase 4a (cases/data 生成) 之后执行。** 使用 `verify_locators.py` 在真实浏览器中验证所有定位器。

```bash
python .claude/skills/generate-ui-test/tools/verify_locators.py {project_name} \
  --cookie "name=value;..." --url "{base_url}" \
  --discovery {project_name}/_probe/discovery_{module_slug}.json \
  --module "{module_slug}"
```

**验证逻辑（三阶段优先级）**：
1. **KB locator 优先**：知识库模板生成的 XPath，在浏览器中验证 count==1
2. **discovery 已验证 locator**：Phase 3 探测时已验证的 locator
3. **KB fallback**：以上都失败时使用 KB 兜底模板，标记 `[UNVERIFIED]`

**容器兜底规则**：
- 确认/取消按钮无匹配 → 默认 el-dialog 前缀
- 其他元素 + 新页面 → 无前缀
- 其他元素 + 非新页面 → 默认 el-drawer 前缀

**回写**：验证通过的 locator 自动回写到 pages YAML（`update_pages_yaml()`）。

**模块隔离**（F5）：`--module` 参数限制 pages YAML 加载范围，防止跨模块 locator 碰撞。

**执行顺序（强制）**：
```
Phase 3   discover_page.py → discovery_{module}.json
Phase 4   generate_from_excel.py → pages YAML + cases YAML + data YAML（v2 统一编排）
          （内部 direct import: _element_resolver + _case_generator + _pages_writer）
Phase 3f  verify_locators.py（运行时验证 + 回写）→ 更新 pages YAML
          validate_04（复检）
Phase 3.5 compile_module_keywords.py → validate_03_5
Phase 4b  generate_suites.py → suites
Phase 5   validate_05_scripts.py
Phase 5+6 generate_issues_report.py
```

### Phase 3.5: 模块关键字编译（L3）

将 `_knowledge/{module}.yaml` 中的 workflow 定义编译为 Python 复合关键字，输出至 `lib/module_keywords.py`。

**关键字分层架构**：

| 层 | 来源 | 职责 | 位置 |
|----|------|------|------|
| L0 系统关键字 | 引擎提供 | 原子操作（click/fill/wait/assert） | `UIEngine/keywords/` |
| L1 知识库 | 系统+模块 | 元素定位模式（XPath 模板） | `tools/probe_knowledge.json` + `{project}/_knowledge/` |
| L3 模块关键字 | _knowledge/ 编译 | 项目专属 + 系统级跨项目流程 | `lib/system_workflows.yaml` → `{project}/lib/module_keywords.py` |

**Case 生成时匹配优先级**：L3 模块关键字 > L1 知识库 > AI 补充生成

**编译流程**：
1. 读取 `{project}/_knowledge/{module}.yaml` 中的 workflows
2. 按 `templates/module_keywords.py.tpl` 模板编译为 Python 函数
3. 写入 `{project}/lib/module_keywords.py`
4. `run.py` 启动时自动加载注册

**workflow YAML → Python 编译规则**：

| YAML keyword | Python 编译方式 |
|-------------|---------------|
| `click_element` | `self.perform({'keyword': 'click_element', ...})` |
| `fill_value` | `self.perform({'keyword': 'fill_value', ...})` |
| `wait_for_time` | `self.perform({'keyword': 'wait_for_time', ...})` |
| `get_element_count` + `compile: count_and_store` | `_count = self.page.locator(...).count()` |
| `get_text` + `compile: text_and_store` | `_text = self.page.locator(...).first.text_content()` |
| `if_variable` | `if {condition}:` (Python 原生条件，支持 then_steps / else_steps) |
| `except_to_be_visible` | `self.perform({'keyword': 'except_to_be_visible', ...})` |
| `log` | `self.log.debug_log('[L3] {message}')` |

**run.py 加载顺序**：auth_keywords → module_keywords（均 try/except 静默跳过）

**编译命令**：
```bash
python .claude/skills/generate-ui-test/tools/compile_module_keywords.py {project_name}
```

**验证**（🚨 强制门禁，_knowledge/ 有 workflows 时必须通过）：
```bash
python .claude/skills/generate-ui-test/validators/validate_03_5_keywords.py {project_name}
```

| 结果 | 处理方式 |
|------|---------|
| 0 errors | 进入 Phase 4 |
| R3.5.4 error | module_keywords.py 不存在，先运行编译工具 |
| R3.5.7 error | workflow 未编译，重新运行编译工具 |
| _knowledge/ 为空 | 自动跳过（退出 0） |

### Phase 4: 脚本生成

#### 4.1 pages → `pages/{module}/{page}.yaml`

使用 `templates/pages.yaml.tpl` 格式。

**⚠️ 强制使用 `generate_from_excel.py` 统一编排工具生成 pages + cases + data（🚨 禁止手写 locator）：**

> **所有 pages YAML 通过编排工具从 discovery JSON 生成。手写 locator = R4.11 违规 = validate_05 阻断。**
> **唯一例外：discovery 未覆盖的元素可手动追加到 YAML 末尾，但必须先运行 `verify_locators.py` 验证。**

```bash
# 统一编排（推荐 — 一步生成 pages + cases + data）:
python .claude/skills/generate-ui-test/tools/generate_from_excel.py "{excel_json}" \
    --discovery-dir {project_name}/_probe/ \
    --output-dir {project_name}

# 手动调用（仅调试时使用，v2 direct import）:
python -c "
import sys; sys.path.insert(0, '.claude/skills/generate-ui-test/tools')
from _pages_writer import generate_pages_yaml_from_discovery
generate_pages_yaml_from_discovery(
    '{project_name}/_probe/discovery_{module_slug}.json',
    '{project_name}/pages/{module}/elements.yaml',
    '中文模块名', '{module_slug}')
"
```

> **`--module-name` 必填**（代码强制，缺失即报错退出）：写入 YAML 注释 `# 模块: 名称`，供 `generate_from_excel.py` 通过 discovery JSON `cn_name` 自动建立模块名→英文目录映射，消除手动 `--module-map`。

**工具自动处理**（手写无法可靠做到）：
1. R4.11 隐藏过滤属性注入到每个 XPath 的最终元素标签
2. R4.2 el-select 选项 locator 自动生成（从 probe 的 `select_options` 列表）
3. R4.12 双向面板 `bottom-start or top-start` 兼容
4. 子串冲突检测（`needs_exact_match` → 切换为 `text()='...'`）
5. 容器作用域前缀（`el-drawer` / `el-dialog`）

**禁止手写的具体规则**：
- ❌ 禁止从 discovery JSON 手动抄写 locator 到 YAML（会丢失隐藏过滤属性）
- ❌ 禁止凭经验手写 XPath（无法保证 R4.11 合规）
- ❌ 禁止在 pages YAML 中手写 el-select 选项 XPath（工具会自动生成）
- ✅ 允许：probe 未覆盖的通用定位器（如 `success_text`、`loading_mask`）可手动追加到 `common_elements` 组
- ✅ 允许：detail_page_elements 等详情页字段可手动追加（probe 通常无法覆盖详情页）

**关键要求**：
- 搜索区域和容器内元素必须用不同 group 区分
- 每个 el-select 的选项 XPath 必须定义在 pages 中
- 通用 XPath（success_text、loading_mask 等）定义于 `common_elements` 组

**生成后自检**：每个定位器是否来自 probe？容器内元素是否加了作用域前缀？运行 `validate_05_scripts.py` 确认 R4.11 无 error。

#### 4.2 data → `data/{module}/{data}.yaml`

{{ include "knowledge/param_extract_rule.md" }}

使用 `templates/data.yaml.tpl` 格式。

**必须包含**：所有 fill_value 的 value、所有 expect_results、所有 el-select 搜索关键词、所有 URL。

#### 4.3 cases → `cases/{module}/{seq:02d}_{case_slug}.yaml`

使用 `templates/case.yaml.tpl` 格式。文件名含序号前缀（R4.5）。**同一模块内编号必须全局连续**，多个来源（Excel/自然语言）合并到同一模块时，编号从已有最大值 +1 继续，禁止每个来源从 01 重新开始。

**case ID 全局唯一（R4.37）**：`id` 字段必须包含模块标识，推荐 slug 格式 `{module}_{action}`（如 `mail_readReminder`、`project_addMember`），fallback 序号格式 `{module}-case-{NN}`（如 `mail-case-01`）。`run.py` 的 `load_cases()` 用 `id` 做字典 key，多模块共用 `case-01` 会导致后加载的覆盖先加载的。使用 `--slug-file` 时 ID 与文件名自动一致。手写 case 时必须手动添加模块标识。

**🚨 优先使用 `generate_from_excel.py` 统一编排工具自动生成（消除 AI 手写错误 + 组名不一致）：**

```bash
# 1. 先将 Excel 解析为 JSON
python .claude/skills/generate-ui-test/tools/read_excel.py testcases.xlsx --output cases.json

# 2. 统一编排（推荐 — 一步生成 pages + cases + data + 自动过滤）
python .claude/skills/generate-ui-test/tools/generate_from_excel.py cases.json \
    --discovery-dir {project}/_probe/ \
    --output-dir {project}

# 手动调用 case 生成（仅调试时使用，v2 direct import）:
# 3. 自动生成 case YAML + data YAML
python -c "
import sys, json; sys.path.insert(0, '.claude/skills/generate-ui-test/tools')
from _element_resolver import ElementResolver
from _case_generator import CaseGenerator, generate_case_file
# ... 详见 generate_from_excel.py main() 内部逻辑
"
```

**工具自动处理**（手写无法可靠做到）：
1. el-select 条件分支法自动生成（click + if_element_visible 判断可编辑 → fill + click option / click 第一项），不可能遗漏 fill 步骤
2. locator 自动引用 pages YAML（`${group.field}`），不可能硬编码 XPath
3. 数据值自动提取到 data YAML（`${group.field}`），不可能硬编码业务数据
4. 开头三步自动插入（open_url + refresh + wait_for_element_hidden）
5. 查询/提交后自动插入 loading 等待

**工具无法覆盖时的回退**：
- 步骤解析失败 → 标记 `[待确认]`，AI 手动修正
- 复杂交互（如 if_element_visible、多步骤弹窗）→ AI 在生成后的 YAML 中手动补充
- 断言逻辑 → 工具统一用 `except_to_be_visible` + `common_elements.success_text`

**关键要求**：
- 所有 locator 引用 pages/（`${group.field}`）
- 所有 value 引用 data/（`${group.field}`）
- 开头 3 步：open_url → refresh → wait_for_element_hidden（R4.9）
- el-select 条件分支法全变量化（R4.3）

**el-select 条件分支法严格模板**（🚨 必须逐字使用此模板，禁止 AI 自行编排步骤）：

```yaml
# === el-select 条件分支法开始 ===
# Step 1: 点击展开下拉框
- desc: "选择{字段名} - 点击下拉框"
  keyword: "click_element"
  params:
    locator: "${pages_group}.{field}_select"
# Step 2: 运行时判断输入框是否可编辑（timeout:500 避免 readonly 分支 3 秒空等）
- desc: "判断{字段名}输入框是否可编辑"
  keyword: "if_element_visible"
  params:
    locator: "${pages_group}.{field}_editable"
    timeout: 500
    then_steps:
      # 可编辑 → fill + 精确选择
      - desc: "选择{字段名} - 输入搜索"
        keyword: "fill_value"
        params:
          locator: "${pages_group}.{field}_input"
          value: "${data_group}.{field}_search"
      - desc: "选择{字段名} - 选择选项"
        keyword: "click_element"
        params:
          locator: "${pages_group}.{field}_option"
    else_steps:
      # 只读（readonly）→ 直接选择第一项
      - desc: "选择{字段名} - 选择第一项"
        keyword: "click_element"
        params:
          locator: "${pages_group}.{field}_first_option"
# Step 3: 等待下拉关闭
- desc: "等待"
  keyword: "wait_for_time"
  params:
    timeout: 1000
# === el-select 条件分支法结束 ===
```

**使用规则**：
1. 每个 el-select 操作**必须**包含 Step 1 + Step 2（条件分支）+ Step 3（等待）
2. `{pages_group}` = pages YAML 中的 group 名（如 `impl_drawer_elements`）
3. `{field}` = 字段英文标识（如 `project_name`、`issue_status`）
4. `{data_group}` = data YAML 中的 group 名（如 `question_data`）
5. `_select` / `_input` / `_option` / `_editable` / `_first_option` 后缀由 `_pages_writer.py` 自动生成
6. `if_element_visible` 必须使用 `then_steps` / `else_steps`（禁止 `then` / `else`）
7. `_editable` XPath 含 `not(@readonly)` 条件：可编辑时匹配→走 then_steps，readonly 时不匹配→走 else_steps
8. **禁止** AI 判断"某个下拉框不需要搜索"而省略条件分支或去掉 else_steps
9. 旧 pages YAML（无 `_editable` / `_first_option` 字段）降级为旧三步法，工具自动处理

**智能等待策略**（根据 harvest/probe 结果自动插入）：

| 触发条件 | 插入步骤 |
|---------|---------|
| open_url 后（有 loading mask） | `wait_for_element_hidden(${common_elements.loading_mask})` |
| 任何按钮操作后（后窥逻辑：下一步不是等待/断言/L3） | `check_page_loaded`（3 种 loading 消失 + 1s 稳定等待） |
| 选择操作触发 API 联动 | `wait_for_element(目标元素, timeout: 10000)` |
| 点击删除后 | `wait_for_time(1000)` + `click_element(${confirm_dialog.confirm_btn})` |

**生成后逐条自检**（与 validate_05_scripts.py 自动检查对应）：
- [ ] 所有 keyword 在注册清单中（R4.13）
- [ ] 无 execute_script 做元素点击/输入（R4.10）
- [ ] 链式选择器用 `>>` 不用空格（R4.15）
- [ ] el-select 条件分支法完整: click + if_element_visible(then: fill+option / else: first_option)（R4.2, R4.3）
- [ ] 搜索文本与选项 XPath contains 文本一致（R4.3）
- [ ] 断言参数名精确（R4.14）
- [ ] 开头有环境隔离（R4.9）
- [ ] 所有 `${}` 引用含 `group.` 前缀（R4.6）
- [ ] 点击定位器精确匹配（R4.16）
- [ ] 选项定位器兼容双向面板 bottom-start or top-start（R4.12）
- [ ] 断言统一使用 except_to_be_visible，禁止 except_to_have_text/value/attribute（R4.4, R4.22）
- [ ] 四层目录模块名一致（R4.1）
- [ ] case 文件名含序号（R4.5）
- [ ] 定位器技术细节正确（R4.17）
- [ ] pages YAML 无嵌套变量引用（R4.0）
- [ ] XPath 定位器包含隐藏过滤属性（R4.11）
- [ ] pages YAML 定位器无 `>> nth=N` 后缀（R4.19）
- [ ] data YAML 中 URL 必须是完整 URL（http/https 开头，从 harvest/probe 提取）（R4.18）
- [ ] 步骤顺序与源文件（Excel/自然语言）严格一致，未自行归类调整（R4.20）
- [ ] 所有定位器统一使用纯 XPath，容器限定用 `//div[contains(@class,'el-drawer')]`（R4.21）
- [ ] 断言用 `except_to_be_visible` + 通用文本定位器，禁止 `except_to_have_text` + 特定 class（R4.22）
- [ ] 禁止 `text()='xxx'` 精确等号匹配，断言用 `contains(.,'xx')`，操作用 `contains(text(),'xx')`（R4.34）
- [ ] 富文本编辑器字段使用 `frame_fill_value`，禁止 `fill_value`（R4.35）
- [ ] 按钮定位器使用拆字 contains 模式（优先级 2-1-3），禁止 `//*[contains(text(),'按钮名')]`（R4.36）
- [ ] case ID 含模块标识（slug 格式 `{module}_{action}` 或序号格式 `{module}-case-{NN}`），全局唯一（R4.37）
- [ ] 容器前缀（el-drawer/el-dialog）与实际 UI 一致，同 group 不混用（R4.38）
- [ ] 确认按钮容器前缀不是凭经验默认 el-dialog，需确认是侧滑抽屉还是居中弹窗

**额外人工检查**（校验器暂不自动检测）：
- [ ] 无盲目取第一个（[1]），除非用例明确要求
- [ ] el-cascader 操作方式正确

#### 4.4 suites → `suites/{module}/{suite}.yaml`

**使用 `generate_suites.py` 自动生成（禁止手写 suite）：**

```bash
# 单模块
python .claude/skills/generate-ui-test/tools/generate_suites.py {project_name} --module {module}

# 所有模块（推荐）
python .claude/skills/generate-ui-test/tools/generate_suites.py {project_name} --all-modules
```

工具自动完成：
- 扫描 `cases/{module}/` 下所有 case ID
- 按依赖顺序排序（新增→编辑→详情→导出→查询→批量→删除）（R4.7）
- 生成 setup_step（浏览器+导航+认证+等待，认证方式从 config.yaml 自动推断）
- 写入 `suites/{module}/smoke.yaml`

**禁止手写**：AI 手写 suite 容易出现排序错误或漏引 case_id（D1 修复前成功率仅 ~50%）。

**验证（强制门禁）**：

```bash
python .claude/skills/generate-ui-test/validators/validate_05_scripts.py {project_name}
```

| 结果 | 处理方式 |
|------|---------|
| 0 errors | 进入 Phase 5 |
| >0 errors | **必须修复所有 error 后才能进入下一阶段** |
| warnings only | 人工确认，不阻塞 |

**此步骤不可跳过。** 覆盖 14 条跨文件规则：R4.1, R4.3, R4.7, R4.20, R4.31, R4.31s, R4.33, R4.37, R4.41, R4.42, R4.43, PREREQUISITE, SUITE_REF, EXCEL_COMPLETE。单文件检查已前置到生成工具自检层。

**⚠️ 任何 case/pages/data/suites 文件变更后，必须重新运行 Phase 5 报告生成。**

### Phase 5: 报告生成

```bash
python .claude/skills/generate-ui-test/tools/generate_report.py {project_name}
```

报告自动输出至 `{project_name}/report/generate_report/generation_report.html`（HTML 格式，自包含）。

**验证**：

```bash
python .claude/skills/generate-ui-test/validators/validate_06_report.py {project_name}
```

检查项：
- R5.1 报告路径正确（HTML 格式）
- R5.2 报告格式（HTML 自包含、模块/用例可收起、步骤表格 9 列含实际数据/实际定位器）
- R5.3 探测结果标记（✅/❌/—，仅三种状态）
- R5.4 探测来源标注（知识库/L3/AI生成）
- R5.5 失败步骤备注含文件路径
- R5.6 实际数据/实际定位器列变量解析完整

### Phase 6: 运行验证

> ⚠️ **Phase 6 不再自动阻断。** 运行失败记录在 HTML 联合报告中。
> 如果报告中存在"运行时失败"项，必须人工排查后才能视为通过。

```bash
cd {project_name} && python run.py 2>&1 | tee ui_log.txt
```

**分类记录**（纯分析，不再触发 AI 修复循环）：

| 失败类型 | 判断标准 | 处理 |
|---------|---------|------|
| 执行问题 | Timeout、element not found、locator 错误 | **记录到 HTML 报告**，人工处理 |
| 断言问题 | 断言失败但前置步骤全成功 | **记录到 HTML 报告**，可能是系统 bug |

**自学习**（运行后自动触发）：

```bash
# auto_learn 由 run.py 自动调用，无需手动运行
# 学习数据写入 {project}/_probe/learn_log.json
```

**验证**（纯分析，始终 exit 0）：

```bash
python .claude/skills/generate-ui-test/validators/validate_07_execution.py {project_name}
```

**HTML 联合问题报告**：

```bash
python .claude/skills/generate-ui-test/tools/generate_issues_report.py {project_name}
```

报告整合三类问题源：
- Phase 4a 自检层修复日志（`_probe/repair_log.json`）
- Phase 5 跨文件检查问题（`_probe/phase5_violations.json`）
- Phase 6 运行时失败 + 累积学习记录（`_probe/learn_log.json`）

输出至 `{project}/report/issues_report/issues_YYYYMMDD_HHMMSS.html`（单文件，内嵌 CSS）。

## 引擎架构参考

{{ include "knowledge/engine_arch.md" }}

## 输出要求

1. 每个文件包含中文注释
2. case 的每个 step 必须有 `desc`
3. suite 不含 step，只用 `case_refs`
4. 结构相似的用例必须参数化（提取到 data/）
5. 四层目录均创建模块子目录，模块名一致
6. case 文件名含序号前缀
7. 生成后列出文件清单和安装命令
8. 无法匹配的步骤标记 `[待确认]`

## 验证器总览

| 阶段 | 验证器命令 | 覆盖规则 | 门禁 |
|------|-----------|---------|------|
| Phase 0 | `validate_01_config.py {config} [--runtime-check]` | R0.1-R0.6 | error=阻断 |
| Phase 1 | `validate_02_scaffold.py {project}` | R1.1-R1.3, R1.5 | error=阻断 |
| Phase 3 | `validate_04_probe.py {project}` | R3.1,R3.3,R3.4,R3.6,R3.10 | error=阻断 |
| Phase 3f | `verify_locators.py {project} --cookie "..." --url "..." --discovery ...` | KB+discovery验证+回写pages YAML | **🚨 强制**，cases生成后运行一次 |
| Phase 3.5 | `validate_03_5_keywords.py {project}` | R3.5.1-R3.5.7 | error=阻断（_knowledge/ 为空时自动跳过） |
| Phase 4 | `validate_05_scripts.py {project}` | R4.1,R4.3,R4.7,R4.20,R4.31,R4.31s,R4.33,R4.37,R4.41-R4.43,PREREQUISITE,SUITE_REF,EXCEL_COMPLETE | error=阻断（仅 14 项跨文件检查） |
| Phase 4（自检层）| _case_generator.py 内置自检（SelfCheckLayer） | R4.2,R4.4,R4.6,R4.9,R4.13,R4.14,R4.21,R4.22 等 | 代码自修复 + remaining 记录 |
| Phase 5 | `validate_06_report.py {project}` | R5.1-R5.6 | warn=提示 |
| Phase 5+6 | `generate_issues_report.py {project}` | HTML 联合报告 | 纯分析产出 |
| Phase 6 | `validate_07_execution.py {project}` | R6.1-R6.4 | 纯分析，始终 exit 0 |
