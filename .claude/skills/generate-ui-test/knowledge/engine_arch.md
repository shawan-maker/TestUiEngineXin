# UIEngine 引擎架构

## 四层分离

| 层 | 目录 | 职责 |
|----|------|------|
| 页面定位器 | `pages/{module}/` | 元素选择器定义，不含业务逻辑 |
| 测试数据 | `data/{module}/` | 输入值、期望值，支持参数化数据集 |
| 测试用例 | `cases/{module}/` | 完整测试步骤（keyword + params） |
| 测试套件 | `suites/{module}/` | 编排用例执行顺序，不含步骤 |

## 变量替换规则

所有 YAML 中通过 `${变量名}` 引用，`run.py` 启动时自动加载注入：

| 引用格式 | 来源 | 加载方式 |
|----------|------|----------|
| `${login_page.username_input}` | `pages/**/*.yaml` | run.py 递归加载 + flatten_dict 展平 |
| `${dataset_1.username}` | `data/**/*.yaml` | run.py 递归加载 + flatten_dict 展平 |
| `${username}` | `config.yaml` global_variable | 直接读取 |

**重要**：UIEngine 的 VariableResolver 使用**扁平字典**查找，`${group.key}` 整体作为 key。
`run.py` 中的 `flatten_dict()` 函数将 pages/data 的嵌套字典展平为点分键：
`{"login_page": {"btn_submit": ".cls"}}` → `{"login_page.btn_submit": ".cls"}`

变量解析器递归遍历 dict/list/str，仅对字符串值做替换，保持原始类型不变。

## 用例引用机制（case_refs）

suite 通过 `case_refs` 引用 cases/ 中的用例：

```yaml
case_refs:
  - case_id: "case_login_valid"        # 必填，对应 case 文件的 id 字段
  - case_id: "case_login_invalid"
    skip: true                          # 可选，覆盖用例的 skip 状态
  - case_id: "case_login_template"
    data_binding:                       # 可选，动态绑定数据集
      username: "dataset_2.username"
      password: "dataset_2.password"
```

`run.py` 中的 `resolve_suite()` 将 `case_id` 替换为实际用例定义后交给引擎执行。

## 两种执行模式

perform() 支持两种调度方式：
1. **关键字模式**：通过 KeyWordManager.maps 查表（优先）
2. **直接调用模式**：未注册时回退到 getattr(self, method)

suite/case 中使用 `keyword` 或 `method` 字段均可。

## 截图与日志

- 截图保存：`工程根目录/files/shortcuts/{suite_name}/`（通过 `error_pic_path` 配置）
- 日志默认保存：`工程根目录/files/logs/`
- `run.py` 自动将 `error_pic_path` 设为工程本地 `files/shortcuts`，避免写入引擎安装目录
- 每次 run() 创建独立 logger（以 suite_id 命名），互不干扰
- `files/` 目录已加入 `.gitignore`，运行时自动创建

## pip 安装

```bash
pip install ui_engine_xin pyyaml openpyxl
playwright install chromium
```

生成的工程通过 `from UIEngine.runner.runner import Runner` 导入引擎。
