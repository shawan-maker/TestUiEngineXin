# generate-ui-test

基于 UIEngine 的 UI 自动化测试工程生成技能。通过管线编排器（pipeline.py）自动执行 11 个阶段（Phase 0-9 + 1b），生成可独立运行的测试工程。

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

## 管线阶段（Phase 0-9）

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
# 完整执行（Phase 0 → Phase 9）
python tools/pipeline.py run --project {项目目录} --excel {Excel文件} --target-url "{URL}" --cookie "{cookie}"

# 从指定阶段恢复（用于修复后重跑）
python tools/pipeline.py run --project {项目目录} --from-phase phase_4_discovery

# 仅执行指定阶段（用于局部调试）
python tools/pipeline.py run --project {项目目录} --only-phase phase_6_verify

# 查看阶段状态
python tools/pipeline.py status --project {项目目录}

# 检查阶段间引用一致性
python tools/pipeline.py validate-refs --project {项目目录}
```

### CLI 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `--project` | ✅ | 项目目录路径 |
| `--excel` | Excel 输入时 | Excel 文件路径（触发 Phase 1/1b） |
| `--target-url` | 必填 | 目标系统 URL（用于自动生成 config.yaml） |
| `--cookie` | 可选 | 认证 Cookie，也可在 config.yaml 中配置 |
| `--from-phase` | 可选 | 从指定阶段开始恢复（前置阶段的 artifact 已存在时自动跳过） |
| `--only-phase` | 可选 | 仅执行指定阶段及其上游依赖 |
| `--browser-type` | 可选 | 浏览器类型：chromium/firefox/webkit（默认 chromium） |
| `--run-smoke` | 可选 | Phase 9 完成后自动执行 smoke 测试 |

### 阶段别名

支持使用短名称，管线自动映射到完整阶段名：

| 别名 | 映射到 |
|------|--------|
| `phase_1b` | `phase_1b_parse` |
| `phase_3` | `phase_3_keywords` |
| `phase_4` | `phase_4_discovery` |
| `phase_6` | `phase_6_verify` |

## 自动化流程

管线编排器（`pipeline.py`）按拓扑依赖顺序自动执行 10 个阶段：

1. **Phase 0** — 验证/生成 `config.yaml`，自动补全 `cookie_domain`
2. **Phase 1** — Excel 预检（仅 Excel 输入时执行）
3. **Phase 1b** — 解析 Excel → `_probe/excel_parsed.json`，提取 `page_urls` 写入 `config.yaml`
4. **Phase 2** — 生成脚手架：`run.py`、`lib/auth_keywords.py`、目录结构
5. **Phase 3** — 编译模块关键字 → `lib/module_keywords.py`
6. **Phase 4** — 自动探测页面元素 → `_probe/discovery_{module}.json`
7. **Phase 5** — 生成 cases/pages/data YAML 文件
8. **Phase 6** — 运行时定位器验证（浏览器验证每个 locator）
9. **Phase 7** — 生成 suites YAML
10. **Phase 8** — 跨文件校验（gate，失败阻断后续阶段）
11. **Phase 9** — 运行验证（检查项目结构完整性）

**恢复机制**：`--from-phase` 恢复时，前置阶段若 artifact 已存在且非空则自动跳过（状态标记为 `skipped`）。

**认证失败阻断**：Phase 4/6 检测到认证失败（401/403/登录/重定向）时全局阻断（`exit(2)`），需人工更新 Cookie 后使用 `--from-phase` 恢复。

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

## 错误恢复

如果管线某阶段失败：
1. 查看管线状态：`_probe/pipeline_state.json`
2. 查看工具完整日志：`_probe/{phase_id}_tool.log`（包含 stdout/stderr 完整输出）
3. 修复问题（如修改 Excel、补充配置）
4. 使用 `--from-phase {失败阶段的Phase ID}` 恢复执行：
   ```bash
   python tools/pipeline.py run --project {目录} --from-phase phase_4_discovery
   ```

**禁止**：直接调用失败阶段的工具（如 `python tools/run_phase4.py`）。必须通过管线恢复。

## 参考文档

知识文档位于 `docs/`，详见各阶段规则文件（`rules/`）。
