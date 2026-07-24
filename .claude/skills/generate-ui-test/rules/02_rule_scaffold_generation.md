# Phase 1: 脚手架生成规则

## R1.1 目录结构正确

项目必须包含以下四层目录结构：

```
{project_name}/
├── pages/{module}/     # 页面定位器
├── data/{module}/      # 测试数据
├── cases/{module}/     # 测试用例
├── suites/{module}/    # 测试套件
├── lib/                # 运行时关键字（auth + L3 模块关键字）
├── _knowledge/         # 模块级知识库（workflow 定义 → 编译为 L3 关键字）
├── _probe/             # 探测结果
├── files/              # 运行时产物
└── report/             # 测试报告
```

## R1.2 模板变量替换完整

从 templates/ 复制的文件必须完成以下变量替换：

| 模板变量 | 替换为 |
|---------|--------|
| `{{project_name}}` | 用户输入的项目名称 |
| `{{module}}` | 默认模块名（common 或从输入推断） |
| `{{target_url}}` | 用户输入的目标 URL |
| `{{browser_type}}` | 用户输入的浏览器类型 |

## R1.3 .gitignore 正确

必须包含以下排除项：
- `files/` — 运行时截图、日志、下载
- `report/` — HTML 测试报告
- `_probe/` — 探测结果
- `__pycache__/` — Python 缓存
- `*.pyc` — 编译文件

## R1.4 不删除已有项目

如果项目目录已存在 `run.py`，视为已有项目，**禁止删除**，只追加新模块。

## R1.5 run.py 禁止手动创建

run.py 必须从 `templates/run.py.tpl` 复制，包含 deep_merge、flatten_dict、load_yaml_recursive 等辅助函数。

## R1.6 common/ 子目录必须存在

四层目录（pages/data/cases/suites）中必须包含 `common/` 子目录，用于存放跨模块共享资源（通用定位器、公共数据、共享用例等）。

验证：`validate_02_scaffold.py` 检查 `{layer}/common/` 目录存在性。
