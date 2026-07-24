# {{project_name}}

基于 UIEngine 的 UI 自动化测试工程（由 generate-ui-test 技能自动生成）。

## 第一步：安装依赖

```bash
pip install ui_engine_xin pyyaml openpyxl
playwright install chromium
```

## 第二步：配置环境

编辑 `config.yaml`，确认以下配置：
- `target_url`：被测系统 URL
- `browser_type`：浏览器类型（chromium / firefox / webkit）
- `cookie` + `cookie_domain`：Cookie 认证（引擎自动注入）
- `local_storage`：localStorage 认证（suite 通过 inject_local_storage 读取）

## 第三步：运行测试

```bash
python run.py --all                                # 运行全部用例（一次执行，一个报告）
python run.py                                      # 运行所有套件（每个套件一个报告）
python run.py --module {{module}}                  # 运行指定模块
python run.py suites/{{module}}/xxx.yaml           # 运行指定套件
```

## 工程结构

```
{{project_name}}/
├── run.py              # 运行入口
├── config.yaml         # 环境配置（浏览器、URL、认证）
├── lib/                # 运行时关键字
│   ├── auth_keywords.py         # 认证注入（Cookie/Token/localStorage）
│   └── module_keywords.py     # L3 模块复合关键字（从 _knowledge/ 编译）
├── pages/{{module}}/   # 页面元素定位器
├── data/{{module}}/    # 参数化测试数据
├── cases/{{module}}/   # 测试用例（完整步骤）
├── suites/{{module}}/  # 测试套件（编排用例顺序）
├── _knowledge/         # 模块级知识库
├── _probe/             # 探测结果（自动生成）
├── files/              # 截图/日志/下载（运行时自动创建）
└── report/             # HTML 测试报告（自动生成）
```

## 关键字使用原则

测试用例中**优先使用 UIEngine 封装的关键字**，保证可读性和可维护性：

| 优先级 | 关键字 | 说明 |
|:------:|--------|------|
| 1 | `click_element` | 点击按钮、链接等 |
| 1 | `fill_value` | 输入框填写内容 |
| 1 | `click_select_option` | 下拉框选择（原生 select 或非 Element UI） |
| 1 | `wait_for_element` / `wait_for_element_hidden` | 等待元素出现/消失 |
| 1 | `except_to_have_text` / `except_to_be_visible` | 断言验证 |
| 2 | `execute_script` | **仅当上述方法不可用时**作为后备（如 Element UI el-select、TinyMCE 编辑器） |

> `execute_script` 中的 JS 脚本不支持 `${variable}` 变量替换，且测试人员不易维护，应尽量避免。
