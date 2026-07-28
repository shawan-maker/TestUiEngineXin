# generate-ui-test

基于 UIEngine 的 UI 自动化测试工程生成技能。通过管线编排器（pipeline.py）自动执行 10 个阶段，生成可独立运行的测试工程。

## 触发方式

- `/generate-ui-test`
- "生成UI测试脚本" / "创建自动化测试" / "从Excel生成测试"

## 管线阶段（Phase 0-9）

管线编排器自动按依赖顺序执行，AI 只需在 Phase 0 收集用户输入：

| Phase | 名称 | 工具 | 验证器 | AI 职责 |
|-------|------|------|--------|---------|
| 0 | 配置确认 | — | validate_00_config.py | 逐项询问用户 |
| 1 | Excel 预检 | validate_excel.py | — | 询问是否执行（仅 Excel） |
| 2 | 脚手架生成 | — | validate_02_scaffold.py | 自动 |
| 3 | 模块关键字编译 | compile_module_keywords.py | validate_03_keywords.py | 自动 |
| 4 | 全自动探测 | run_phase4.py | validate_04_probe.py | 自动 |
| 5 | cases+pages+data 生成 | generate_from_excel.py | — | 自动 |
| 6 | 运行时定位器验证 | verify_locators.py | validate_04_probe.py | 自动 |
| 7 | suites 生成 | generate_suites.py | — | 自动 |
| 8 | 跨文件验证 | — | validate_08_scripts.py | 自动（gate） |
| 9 | 运行验证 | — | validate_09_execution.py | 自动 |

**阶段门禁**：验证器 error > 0 时阻断，必须修复后才能继续。

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
必须通过 `generate_from_excel.py` 生成。例外：`common_elements` 和 `detail_page_elements` 可手动追加。

### ⑤ config.yaml 纯 YAML 格式
config.yaml 是 YAML 文件，注释**只能用 `#`**，禁止 Python docstring `"""` 和 shebang `#!/usr/bin/env python3`。文件头格式参考 `templates/config.yaml.tpl`。

## 工程结构

```
{project}/
├── run.py / config.yaml
├── pages/{module}/    # 定位器（工具生成）
├── data/{module}/     # 测试数据
├── cases/{module}/    # 测试用例
├── suites/{module}/   # 测试套件
├── lib/               # auth_keywords + module_keywords（L3）
├── _knowledge/        # workflow YAML → 编译为 L3
├── _probe/            # 探测结果（自动生成）
└── report/            # HTML 报告
```

## 关键字分层

L0 引擎原子操作 > L1 知识库 XPath 模板 > L3 _knowledge/ 编译复合流程

## el-select 条件分支法

```yaml
- desc: "选择{字段名} - 点击下拉框"
  keyword: click_element
  params: {locator: "${pages_group}.{field}_select"}
- desc: "判断{字段名}输入框是否可编辑"
  keyword: if_element_visible
  params:
    locator: "${pages_group}.{field}_editable"
    timeout: 500
    then_steps:
      - keyword: fill_value
        params: {locator: "${pages_group}.{field}_select", value: "${data_group}.{field}_search"}
      - keyword: wait_for_time
        params: {timeout: 1500}
      - keyword: click_element
        params: {locator: "xpath=(//div[(@x-placement='bottom-start' or @x-placement='top-start') and not(ancestor::*[contains(@style,'display: none')])]//li[not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])][contains(.,'${data_group}.{field}_option')])[1]"}
    else_steps:
      - keyword: wait_for_time
        params: {timeout: 1000}
      - keyword: click_element
        params: {locator: "${pages_group}.{field}_first_option"}
      - keyword: wait_for_time
        params: {timeout: 1000}
```

## 参考文档

- `knowledge/keyword_spec.md` — 关键字规范
- `knowledge/locator-patterns.md` — 16 类 XPath 定位模式
- `knowledge/param_extract_rule.md` — 数据提取规则
- `USER_GUIDE.md` — 用户操作手册
