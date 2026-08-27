# generate-ui-test

基于 UIEngine 框架的 UI 自动化测试工程生成技能。通过 11 阶段管线（Phase 0-9 + 1b）将 Excel 测试用例转换为可独立运行的测试工程。

## 核心能力

- **自动化探测**：Phase 4 自动发现页面元素、容器结构、iframe 上下文
- **智能生成**：Phase 5 基于探测结果生成 cases/pages/data YAML
- **运行时验证**：Phase 6 浏览器实际执行验证定位器准确性
- **自愈修复**：自动修复 38 类常见定位器问题（容器前缀丢失、iframe 遗漏等）

## 触发方式

- `/generate-ui-test`
- "生成UI测试脚本" / "创建自动化测试" / "从Excel生成测试"

## ⚠️ 最佳实践（强烈建议遵守）

1. **使用管线编排器**：所有阶段应通过 `python pipeline.py` 执行，避免直接调用 `run_phase4.py`、`generate_from_excel.py`、`verify_locators.py`、`generate_suites.py` 等单个工具。
   - 例外：工具内置自愈机制会自动补全 Phase 2/3，无需手动调用
2. **脚手架文件由管线生成**：`run.py`、`lib/auth_keywords.py`、`lib/module_keywords.py` 应由管线生成，避免手动创建或修改。
   - 例外：如果缺失，工具会自动触发 Phase 2/3 自愈
3. **完整执行所有阶段**：即使 Excel 输入简单，也应执行完整管线（Phase 0 → Phase 9），确保所有产物完整。
4. **模块目录结构由管线生成**：`pages/{module}/`、`cases/{module}/`、`data/{module}/`、`suites/{module}/` 应由管线 Phase 2 生成。

## 🔧 自愈机制

管线工具内置了自愈机制，减少运行时试错：

**自动自愈（Phase 2/3）**：
- 检测到 `config.yaml` 存在但 `run.py` 不存在 → 自动补全 Phase 2（生成脚手架）
- 检测到 `run.py` 存在但 `module_keywords.py` 不存在 → 自动补全 Phase 3（编译关键字）
- 自愈失败不阻断，记录日志，AI 可在运行时自行修复

**阻断（仅 cookie 错误）**：
- 检测到 Phase 4/6 FAILED 且错误包含 `cookie/401/403/unauthorized/登录/认证失败` → exit(2) 阻断
- Cookie 错误需要人工介入，AI 无法自行获取

**日志记录（其余情况）**：
- 其他阶段缺失或失败 → 记录警告日志，不阻断
- AI 可根据日志在运行时自行修复（如补充缺失的定位器、修复数据格式等）

**正确做法**：始终使用 `python pipeline.py run` 执行完整管线，避免依赖自愈机制。

## 工具退出码协议

管线工具通过 exit code 向编排器报告执行结果，编排器根据 code 决定后续行为：

| Exit Code | 含义 | 编排器行为 |
|-----------|------|-----------|
| `0` | 成功 | 标记阶段 PASSED，继续执行后续阶段 |
| `1` | 工具执行失败（非认证） | 标记阶段 FAILED；若阶段配置了 `tolerate_tool_failure: true`，降级为 warning 并继续；否则阻断管线 |
| `2` | 认证失败（Cookie 失效） | 立即阻断管线，提示用户更新 Cookie 后使用 `--from-phase` 恢复 |

**适用阶段**：
- Phase 4（探测）和 Phase 6（验证）支持 `tolerate_tool_failure` 和 `fatal_on_auth_failure`
- 其他阶段仅使用 exit code 0/1，不支持降级

**verify_orchestrator.py 特殊处理**：
- `auth_error=True`（检测到 401/403/Cookie 失效）→ `exit(2)`，触发全局阻断
- `truly_unresolved > 0`（部分定位器未解析）→ `exit(0)` + 警告，不阻断管线
- 工具崩溃或异常 → `exit(1)`，由 `tolerate_tool_failure` 决定是否降级

## 阶段容错配置

`pipeline_registry.py` 中定义每个阶段的容错策略：

```python
"phase_4_discovery": {
    "fatal_on_auth_failure": True,      # Cookie 失败立即阻断
    "tolerate_tool_failure": True,      # 非认证失败降级为 warning
},
"phase_6_verify": {
    "fatal_on_auth_failure": True,      # Cookie 失败立即阻断
    "tolerate_tool_failure": True,      # 非认证失败降级为 warning
},
```

**语义说明**：
- `fatal_on_auth_failure: true` — 检测到认证失败时立即阻断管线，不再处理后续模块
- `tolerate_tool_failure: true` — 非认证的工具失败（如定位器未解析、playwright 未安装）降级为 warning，管线继续

## 管线阶段（Phase 0-9 + 1b）

管线编排器自动按依赖顺序执行，AI 只需在 Phase 0 收集用户输入：

| Phase ID | 名称 | 工具 | AI 职责 |
|----------|------|------|---------|
| phase_0 | 配置确认 | — | 逐项询问用户 |
| phase_1 | Excel 预检 | validate_excel.py | 自动（仅 Excel） |
| phase_1b_parse | Excel 解析 | read_excel.py | 自动 |
| phase_2 | 脚手架生成 | — | 自动（生成 run.py、auth_keywords） |
| phase_3_keywords | 模块关键字编译 | compile_module_keywords.py | 自动（生成 module_keywords） |
| phase_4_discovery | 全自动探测 | run_phase4.py | 自动 |
| phase_5 | cases+pages+data 生成 | generate_from_excel.py | 自动 |
| phase_6_verify | 运行时定位器验证 | verify_locators.py | 自动 |
| phase_7 | suites 生成 | generate_suites.py | 自动 |
| phase_8 | 跨文件验证 + 报告 | — | 自动（gate，失败阻断） |
| phase_9 | 运行验证 | — | 自动 |

**⚠️ 上表"工具"列仅供理解内部实现。AI 禁止直接调用这些工具，必须通过 `python pipeline.py run` 执行。**

**阶段门禁**：验证器 error > 0 时阻断，必须修复后才能继续。

## 管线执行命令

```bash
# 完整执行（Phase 0 → Phase 9）— 必须后台 + tee 日志
python -u tools/pipeline.py run --project {项目目录} --excel {Excel文件} --target-url "{URL}" --cookie "{cookie}" 2>&1 | tee {项目目录}/_probe/pipeline.log

# 从指定阶段恢复（用于修复后重跑）
python -u tools/pipeline.py run --project {项目目录} --from-phase phase_4_discovery 2>&1 | tee {项目目录}/_probe/pipeline.log

# 仅执行指定阶段（用于局部调试）
python -u tools/pipeline.py run --project {项目目录} --only-phase phase_6_verify 2>&1 | tee {项目目录}/_probe/pipeline.log

# 查看阶段状态
python tools/pipeline.py status --project {项目目录}

# 检查阶段间引用一致性
python tools/pipeline.py validate-refs --project {项目目录}
```

**参数说明**：
- `--project`：项目目录（必填）
- `--excel`：Excel 文件路径（Excel 输入时必填）
- `--target-url`：目标系统 URL（必填，用于生成 config.yaml 和 cookie_domain）
- `--cookie`：认证 Cookie（可选，也可在 Phase 0 由用户提供）
- `--from-phase`：从指定阶段开始恢复（前置阶段的 artifact 已存在时自动跳过）
- `--only-phase`：仅执行指定阶段及其依赖（用于局部调试）

## 管线执行约束

**必须后台执行 + tee 日志文件**，禁止前台执行全管线。

原因：管线执行时间随模块和用例数量线性增长（1 模块 4 用例约 14 分钟，6 模块 57 用例约 60 分钟），任何固定 timeout 都可能不够。后台模式下 Bash timeout 到期不会 kill 进程，管线可完整执行。

**执行方式**：
```bash
# Bash 工具调用参数
{
    "command": "python -u tools/pipeline.py run ... 2>&1 | tee {项目目录}/_probe/pipeline.log",
    "run_in_background": true,
    "timeout": 120000
}
```

**关键规则**：
- `python -u`：禁用 Python 输出缓冲，确保 `print()` 立即写入 tee
- `2>&1 | tee`：stdout + stderr 同时写入日志文件和保留进程 stdout
- `run_in_background: true`：后台执行，不阻塞 AI 对话
- `timeout` 值无实际意义（后台模式不 kill 进程），设为默认 120000 即可
- 定期 `Read` 日志文件 `{项目目录}/_probe/pipeline.log` 查看进度
- 日志末尾出现 `管线执行总结` 表示管线已完成
- 需要停止时：用 `TaskStop` 终止后台任务

**禁止**：
- 禁止 `run_in_background: false` 前台执行全管线
- 禁止省略 `python -u`（会导致输出缓冲延迟写入日志）
- 禁止省略 `tee`（无日志文件则无法查看进度）

## Phase 0 用户输入收集

**逐项询问**，每个问题单独一次 AskUserQuestion：

1. **项目名称** — 可从目录名推断
2. **目标系统 URL** — 必填
3. **输入来源** — 自然语言 / Excel / CSV
4. **模块名称** — 仅在输入来源为自然语言或 CSV 时询问，默认 `common`。**Excel 输入时不问**，自动从"模块"列提取
5. **浏览器类型** — 默认 chromium
6. **认证方式**（默认 none）：none / cookie（推荐）/ header / localStorage

**Excel 模块自动提取规则**：
- 优先从"模块"列逐行读取中文模块名
- 无"模块"列时回退到 Sheet 名称
- 提取后展示给用户确认（不询问）

**Cookie 收集**：选择 `cookie` 时直接输出提示：
> 请在下方发送 Cookie 字符串：F12 → Network → 任意请求 → Headers → Cookie → 整串复制

## 全局强制约束

### ① 全 XPath 定位器
禁止 CSS 选择器、Playwright CSS、`nth=0`。用 `[1]` 替代 `nth=0`。

### ② 断言统一 except_to_be_visible
禁止 `except_to_have_text` / `except_to_have_value`。

### ③ 全变量引用
case 中 locator 引用 `${group.field}`（pages/），value 引用 `${group.field}`（data/），禁止硬编码。

### ④ pages YAML 工具生成
必须通过 `generate_from_excel.py` 生成（由管线自动调用）。例外：`common_elements` 和 `detail_page_elements` 可手动追加。

### ⑤ config.yaml 纯 YAML 格式
config.yaml 是 YAML 文件，注释**只能用 `#`**，禁止 Python docstring `"""` 和 shebang `#!/usr/bin/env python3`。文件头格式参考 `templates/config.yaml.tpl`。

### ⑥ 禁止修改用户提供的配置值
用户提供的 cookie、target_url、cookie_domain 等配置值，AI **禁止自行修改**。
如果管线报错 cookie 相关错误：
1. **先分析日志**：确认是 cookie 真的过期，还是重定向时序问题
2. **报告给用户**：展示诊断信息，由用户决定是否更新 cookie
3. **绝不自行替换**：即使看起来像是 cookie 过期

## 错误恢复

管线某阶段失败时，按以下决策树处理：

### Step 1: 分析失败原因
- 读取 `_probe/pipeline_state.json` 查看失败阶段和错误信息
- 读取 `_probe/{phase_id}_tool.log` 查看工具完整输出
- **不要急于重试**，先判断失败类型

### Step 2: 判断失败类型

| 失败类型 | 典型错误 | 处理方式 |
|---------|---------|---------|
| **认证失败** | `auth_error`, `Redirected to login` | 展示诊断信息给用户，等用户提供新 cookie |
| **验证器错误** | `validate_04`, `validate_08` 报错 | 分析具体规则，修复 Excel 或定位器后 `--from-phase` 恢复 |
| **工具执行失败** | Playwright 未安装、文件缺失等 | 修复环境问题后 `--from-phase` 恢复 |
| **数据问题** | discovery 覆盖率低、步骤未匹配 | 可能需要补充 Excel 或调整配置 |

### Step 3: 恢复执行
```bash
# 仅用于修复后重跑，不用于正常流程
python -u tools/pipeline.py run --project {目录} --from-phase {失败阶段} 2>&1 | tee {目录}/_probe/pipeline.log
```

**禁止**：
- 禁止在正常生成流程中使用 `--from-phase` 或 `--only-phase`
- 禁止自行修改用户提供的 cookie 值
- 禁止因单次失败就反复重试（最多重试 1 次，仍失败则报告用户）

## 参考文档

### 系统架构文档

- **[SYSTEM_TECHNICAL_OVERVIEW.md](docs/design/SYSTEM_TECHNICAL_OVERVIEW.md)** — 系统技术总览（v10.0）
  - 代码结构、分层架构、数据流、匹配逻辑、工具链依赖
  - Phase 0-9 全链路业务逻辑（每阶段详细说明）
  - 跨阶段架构决策（容器作用域、隐藏过滤、iframe、框架注册表）
  - 38 类常见陷阱与解决方案

- **[SKILL_ARCHITECTURE.md](docs/design/SKILL_ARCHITECTURE.md)** — Skill 架构设计
  - 8 个工具子包职责划分
  - 管线状态机、自愈机制、容错策略
  - 验证器总览（6 个 validate_XX 脚本）

- **[kb-locator-reference.md](docs/design/kb-locator-reference.md)** — 知识库全量类型与 Locator 参考
  - probe_knowledge.json 完整解析（24 canonical types）
  - 单步/多步/组合/断言定位器模板
  - 类型系统映射表（STEP_TO_KB、DISCOVERY_TO_KB、KB_TO_SUFFIX）
  - 占位符变量说明、通用隐藏过滤规则

### Phase 专项设计文档

| 阶段 | 文档 | 核心内容 |
|------|------|---------|
| Phase 0 | [phase0-config-confirmation-design.md](docs/design/phase0-config-confirmation-design.md) | 配置确认流程、runtime-check 认证验证 |
| Phase 1 | [phase1-parse-validation-design.md](docs/design/phase1-parse-validation-design.md) | Excel 预检（3 层验证：格式/语义/解析） |
| Phase 2 | [phase2-scaffold-generation-design.md](docs/design/phase2-scaffold-generation-design.md) | 脚手架生成、目录结构优化 |
| Phase 3 | [phase3-module-keywords-compiler-design.md](docs/design/phase3-module-keywords-compiler-design.md) | L3 关键字编译、三层加载机制 |
| Phase 4 | [phase4-discovery-design.md](docs/design/phase4-discovery-design.md) | 元素探测（JS 扫描、容器检测、iframe 双通道） |
| Phase 5 | [phase5-case-generation-design.md](docs/design/phase5-case-generation-design.md) | 步骤匹配（49+ 正则）、discovery 四步查找链、el-select 5 步序列 |
| Phase 6 | [phase6-locator-verification-design.md](docs/design/phase6-locator-verification-design.md) | 运行时验证（VLC 两轮、6 层兜底链、Plan B [1] 统一） |
| Phase 7 | [phase7-suite-generation-design.md](docs/design/phase7-suite-generation-design.md) | suites YAML 生成 |
| Phase 8 | [phase8-cross-file-validation-design.md](docs/design/phase8-cross-file-validation-design.md) | 跨文件验证（13 项规则） |
| Phase 9 | [phase9-execution-validation-design.md](docs/design/phase9-execution-validation-design.md) | 运行验证、测试报告生成 |

### 全链路业务逻辑

- **[phase4-5-6-full-business-logic.md](docs/design/phase4-5-6-full-business-logic.md)** — Phase 4/5/6 端到端数据流
  - 探测 → 生成 → 验证的完整数据传递链路
  - 容器上下文、iframe 上下文、Tab 上下文传递
  - 回写机制（pages YAML、case YAML、_iframe 伴侣字段）

### 规则文档

- **[rules/02_rule_scaffold.md](rules/02_rule_scaffold.md)** — Phase 2 脚手架验证规则
- **[rules/09_rule_execution.md](rules/09_rule_execution.md)** — Phase 9 执行验证规则
- **[rules/09_rule_report.md](rules/09_rule_report.md)** — Phase 9 报告生成规则

### 知识库文档

- **[knowledge/keyword_spec.md](knowledge/keyword_spec.md)** — L3 关键字规范
- **[knowledge/engine_arch.md](knowledge/engine_arch.md)** — UIEngine 引擎架构
- **[knowledge/param_extract_rule.md](knowledge/param_extract_rule.md)** — 参数提取规则

### 用户文档

- **[USER_GUIDE.md](USER_GUIDE.md)** — 用户操作手册（完整版）
  - 前置准备、Excel 用例编写规范
  - 三种场景操作流程（新建项目/新增用例/排查修复）
  - 附录 C：Excel 步骤描述格式规范（49+ 匹配模式详解）

### 历史调试文档

`docs/debug/old/` 目录包含 100+ 份历史 bug 修复记录（已归档），记录 38 类定位器问题的根因分析与修复方案。

---

## 快速索引

### 常见问题速查

| 问题 | 解决方案 | 参考文档 |
|------|---------|---------|
| Cookie 失效 | 用户提供新 cookie，`--from-phase phase_4_discovery` 恢复 | SYSTEM_TECHNICAL_OVERVIEW §十一 |
| 定位器 `[待确认]` | 检查 discovery 覆盖率，补充 Excel 步骤 | phase4-discovery-design.md |
| 容器前缀丢失 | Phase 6 自动回写，或手动添加 `//div[el-dialog]//` 前缀 | SYSTEM_TECHNICAL_OVERVIEW §九.1 |
| iframe 内元素找不到 | Phase 6 自动探测 + `_iframe` 伴侣字段回写 | SYSTEM_TECHNICAL_OVERVIEW §九.4 |
| el-select 匹配失败 | 检查是否使用"下拉框"关键词，确认 5 步序列生成 | kb-locator-reference.md §2.1 |

### 关键文件索引

| 文件 | 行数 | 职责 |
|------|------|------|
| `tools/pipeline.py` | ~1,200 | 统一管线编排器 |
| `tools/core/element_types.py` | 631 | 类型系统单一真相源 |
| `tools/core/step_patterns.py` | 373 | 49+ 步骤匹配正则 |
| `tools/core/xpath_utils.py` | 433 | XPath 构建、隐藏过滤注入 |
| `tools/probe/discover_page.py` | ~2,600 | Phase 4 探测核心 |
| `tools/generation/case_generator.py` | ~2,500 | Phase 5 生成核心 |
| `tools/verification/verify_engine.py` | ~2,400 | Phase 6 验证核心 |
| `tools/probe_knowledge.json` | 554 | 知识库（24 types + Ant Design） |
