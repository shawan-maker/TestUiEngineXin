---
name: generate-ui-test
description: >-
  UI 自动化测试工程生成技能，通过 11 阶段管线（Phase 0-9 + 1b）将 Excel
  测试用例转换为可运行工程。支持 Element UI / Ant Design / 原生 HTML 框架。
user-invocable: true
invocation-trigger: /generate-ui-test
---

# generate-ui-test

UI 自动化测试工程生成技能，通过 11 阶段管线（Phase 0-9 + 1b）将 Excel 测试用例转换为可运行工程。

**触发**：`/generate-ui-test` 或 "生成UI测试" / "创建自动化测试"

**核心原则**：
- 始终使用 `python pipeline.py` 执行，禁止直接调用单阶段工具
- 脚手架（run.py、lib/）由管线生成，禁止手动创建
- 完整执行 Phase 0→9，确保产物完整

**自愈**：缺少 run.py 或 module_keywords.py 时自动补全 Phase 2/3。Cookie 失败（exit 2）阻断需人工介入，其他失败记录日志不阻断。

## 退出码

| Code | 含义 | 行为 |
|------|------|------|
| 0 | 成功 | 继续 |
| 1 | 工具失败 | 配置 `tolerate_tool_failure` 则降级继续，否则阻断 |
| 2 | 认证失败 | 立即阻断，需更新 Cookie |

## 管线阶段

| Phase | 名称 | 状态 |
|-------|------|------|
| phase_0 | 配置确认 | 询问用户 |
| phase_1 | Excel 预检 | 自动 |
| phase_1b_parse | Excel 解析 | 自动 |
| phase_2 | 脚手架生成 | 自动 |
| phase_3_keywords | 关键字编译 | 自动 |
| phase_4_discovery | 页面探测 | 自动 |
| phase_5 | cases+pages+data 生成 | 自动 |
| phase_6_verify | 定位器验证 | 自动 |
| phase_7 | suites 生成 | 自动 |
| phase_8 | 跨文件验证 | 自动（gate） |
| phase_9 | 运行验证 | 自动 |

**⚠️ 禁止直接调用工具，必须通过 `python pipeline.py` 执行**

## 执行命令

```bash
# Excel 输入执行（必须后台 + tee）
python -u tools/pipeline.py run --project {目录} --excel {文件} --target-url "{URL}" --cookie "{cookie}" 2>&1 | tee {目录}/_probe/pipeline.log

# 自然语言输入执行（必须后台 + tee）
# --module 参数：指定模块名称（slug 格式，如 "user_manage"），不传则默认为 "common"
python -u tools/pipeline.py run --project {目录} --nl-input {文件} --module {模块名} --target-url "{URL}" --cookie "{cookie}" 2>&1 | tee {目录}/_probe/pipeline.log

# 从指定阶段恢复
python -u tools/pipeline.py run --project {目录} --from-phase phase_4_discovery 2>&1 | tee {目录}/_probe/pipeline.log

# 仅执行指定阶段
python -u tools/pipeline.py run --project {目录} --only-phase phase_6_verify 2>&1 | tee {目录}/_probe/pipeline.log

# 查看状态
python tools/pipeline.py status --project {目录}

# 验证引用
python tools/pipeline.py validate-refs --project {目录}
```

**执行约束**：
- 必须 `run_in_background: true` + `tee` 日志
- 必须 `python -u`（禁用缓冲）+ `2>&1`（合并 stderr）
- 定期 Read `{目录}/_probe/pipeline.log` 查看进度
- 禁止前台执行全管线

## Phase 0 用户输入

逐项询问（每个问题单独 AskUserQuestion）：

1. **项目名称**（从目录推断）
2. **目标 URL**（必填）
3. **输入来源**（自然语言 / Excel / CSV）
4. **模块名称**（仅非 Excel 时询问，默认 common）
5. **浏览器**（默认 chromium）
6. **认证方式**（none / cookie / header / localStorage）

**自然语言输入**：必须询问模块名称，并通过 `--module` 参数传递给管线。模块名用于：
- 生成目录结构：`cases/{module}/`, `pages/{module}/`, `data/{module}/`, `suites/{module}/`
- 生成 `module_map.json`：`{module_cn_name: module_slug}`
- Phase 1 NL 的 `{module_slug}` 占位符替换

**Excel 输入**：自动从"模块"列或 Sheet 名提取模块名，展示确认。不需要 `--module` 参数。

**Cookie 收集**：提示用户从 F12 → Network → Cookie 复制。

**禁止询问项**（违反"不需要人工交互"原则）：

- ❌ "是否采集DOM" - Phase 4 自动执行
- ❌ "是否运行Phase X" - 管线阶段全部自动执行
- ❌ "是否跳过某阶段" - 使用 CLI 参数（`--only-phase`, `--from-phase`, `--skip-phase`），不询问
- ❌ 任何关于"是否执行某功能"的询问 - 管线默认执行所有阶段

**原则**：Phase 0 只收集 6 项配置信息，不询问执行策略。所有阶段默认执行，通过 CLI 参数控制。

## 全局约束

**① 全 XPath**：禁止 CSS 选择器、`nth=0`，用 `[1]` 替代。

**② 断言统一**：只用 `except_to_be_visible`，禁止 `except_to_have_text`/`except_to_have_value`。

**③ 全变量引用**：case 中 locator 引用 `${group.field}`（pages/），value 引用 `${data_group.field}`（data/），禁止硬编码。

**④ pages 生成**：必须通过管线工具生成，例外：`common_elements` 和 `detail_page_elements` 可手动追加。

**⑤ config.yaml 格式**：纯 YAML，注释只用 `#`，禁止 Python docstring `"""` 和 shebang。

**⑥ 禁止修改用户配置**：cookie、target_url、cookie_domain 等用户提供的值禁止自行修改。Cookie 错误时：先分析日志 → 报告用户 → 等用户提供新值。

**⑦ L3 tolerant 规则**：防御性等待（`wait_for_element_hidden`/`wait_for_load`/`wait_for_network`）自动添加 `tolerant: true`，非防御性关键字需手动标注。

## 错误恢复

**Step 1：分析**
- Read `_probe/pipeline_state.json` 查看失败阶段
- Read `_probe/{phase_id}_tool.log` 查看工具输出
- 不要急于重试

**Step 2：判断类型**

| 类型 | 典型错误 | 处理 |
|------|---------|------|
| 认证失败 | `Redirected to login` | 展示给用户，等新 cookie |
| 验证器错误 | `validate_04` 报错 | 修复 Excel/定位器后 `--from-phase` 恢复 |
| 工具失败 | Playwright 未安装 | 修复环境后恢复 |
| 数据问题 | discovery 覆盖率低 | 补充 Excel 或调整配置 |

**Step 3：恢复**
```bash
python -u tools/pipeline.py run --project {目录} --from-phase {失败阶段} 2>&1 | tee {目录}/_probe/pipeline.log
```

**禁止**：
- 正常流程中使用 `--from-phase`
- 自行修改用户 cookie
- 反复重试（最多 1 次，仍失败则报告用户）

## 参考文档

- **[SYSTEM_TECHNICAL_OVERVIEW.md](docs/design/SYSTEM_TECHNICAL_OVERVIEW.md)** — 系统架构、全链路业务逻辑、38 类陷阱
- **[USER_GUIDE.md](USER_GUIDE.md)** — 用户操作手册、Excel 规范、步骤格式（49+ 模式）
- **[kb-locator-reference.md](docs/design/kb-locator-reference.md)** — 知识库类型与定位器模板
