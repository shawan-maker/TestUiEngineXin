# UIEngine

基于 Playwright 的关键字驱动 UI 自动化测试引擎。

## 特性

- **关键字驱动**：通过中文/英文关键字编写测试用例，降低使用门槛
- **中英文双注册**：每个关键字同时支持中英文名称，大小写兼容
- **88 个内置关键字**：覆盖页面操作、元素交互、等待策略、断言、iframe、流程控制等场景
- **变量替换**：支持 `${variable}` 语法引用全局变量，支持最多 3 层嵌套解析
- **流程控制**：支持条件分支（`if_element_visible`）、循环（`for_each`）、重试（`retry_until`）
- **执行树追踪**：自动记录关键字嵌套调用关系，失败时附带截图和完整日志
- **HTML 报告**：自动生成自包含静态 HTML 报告，含步骤树、截图、错误分析
- **灵活配置**：支持 dict 和 YAML 两种配置方式
- **可扩展**：支持动态注册自定义关键字和认证扩展

## 安装

```bash
pip install ui_engine_xin
playwright install
```

## 快速开始

```python
from UIEngine import Runner

config = {
    "browser_type": "chromium",
    "is_debug": True,                # True=显示浏览器，False=无头模式
    "host": "http://localhost:8080",
    "cookie": "session=abc123",      # 可选，自动注入到浏览器上下文
    "cookie_domain": "localhost",
    "global_variable": {
        "username": "admin",
        "password": "123456"
    }
}

suite = {
    "id": "suite_001",
    "name": "登录功能测试",
    "setup_step": [
        {"desc": "打开浏览器", "keyword": "open_browser", "params": {"browser_type": "chromium"}},
        {"desc": "打开登录页", "keyword": "open_url", "params": {"url": "/login"}},
    ],
    "cases": [
        {
            "id": "case_001",
            "name": "正确密码登录",
            "steps": [
                {"desc": "输入用户名", "keyword": "fill_value",
                 "params": {"locator": "#username", "value": "${username}"}},
                {"desc": "输入密码", "keyword": "fill_value",
                 "params": {"locator": "#password", "value": "${password}"}},
                {"desc": "点击登录", "keyword": "click_element",
                 "params": {"locator": "#login-btn"}},
                {"desc": "验证登录成功", "keyword": "except_to_be_visible",
                 "params": {"locator": ".welcome"}}
            ]
        }
    ]
}

result = Runner(config).run(suite)
print(f"通过: {result['success']} | 失败: {result['fail']} | 错误: {result['error']}")
```

## 架构概览

### 继承链（MRO）

```
BaseCase
  → PageMixin       (14 个页面操作关键字)
  → LocatorMixin    (25 个元素操作关键字)
  → MouseMixin      (8 个鼠标键盘关键字)
  → WaitMixin       (7 个等待关键字)
  → IFrameMixin     (13 个 iframe 关键字)
  → AssertMixin     (13 个断言关键字)
  → FlowMixin       (8 个流程控制关键字)
  → BaseBrowser     (浏览器生命周期管理)
```

所有 Mixin 继承自 `BaseBrowser`，可直接访问 `self.page`、`self.context`、`self.browser`。

### 关键字调度流程

```
Runner.run(suite)
  → BaseCase.perform(step)
    → VariableResolver.resolve(params)      # ${var} 变量替换
    → KeyWordManager.get_keyword_maps(name)  # 注册表查找
    → method(self, **params)                 # 调用 Mixin 方法
    → ExecutionTreeBuilder.push/pop          # 执行树追踪
```

查找优先级：
1. `KeyWordManager.maps` 精确匹配 → 大小写不敏感匹配
2. `getattr(BaseCase, keyword)` 直接方法调用（回退）
3. 均未找到 → 抛出 `KeywordNotFoundError`

### 目录结构

```
UIEngine/
├── __init__.py              # 包入口，导出 6 个核心类
├── basecase.py              # BaseCase 组合类 + perform() 调度
├── caseLog.py               # 日志处理器
├── browser/
│   └── base_browser.py      # Playwright 浏览器生命周期
├── config/
│   └── default.yaml         # 引擎默认配置
├── core/
│   ├── keyword_manager.py   # 关键字注册表
│   ├── variable_resolver.py # 变量解析器
│   └── exceptions.py        # 自定义异常
├── keywords/                # 7 个 Mixin 文件（88 个关键字）
│   ├── page_keywords.py     # 页面操作
│   ├── locator_keywords.py  # 元素操作
│   ├── mouse_keywords.py    # 鼠标键盘
│   ├── wait_keywords.py     # 等待策略
│   ├── iframe_keywords.py   # iframe 操作
│   ├── assert_keywords.py   # 断言
│   └── flow_keywords.py     # 流程控制
├── reporting/
│   ├── html_report.py       # HTML 报告生成（1072 行）
│   ├── execution_tree.py    # 执行树构建器
│   └── result.py            # 测试结果聚合
├── runner/
│   ├── runner.py            # Runner 执行器
│   └── screenshot_manager.py# 截图管理
└── utils/
    └── path_helper.py       # 项目目录解析
```

## 配置参考

| 字段 | 类型 | 说明 |
|------|------|------|
| `browser_type` | str | 浏览器类型：`chromium`（默认）/ `firefox` / `webkit` |
| `is_debug` | bool | `True` = 有头模式 + `no_viewport`；`False` = 无头 + 1920x1080 |
| `host` | str | 基础 URL，相对路径自动拼接此地址 |
| `cookie` | str | Cookie 字符串 `"name1=value1; name2=value2"`，浏览器创建时自动注入 |
| `cookie_domain` | str | Cookie 域名，为空时自动从 `host` 提取 |
| `project_dir` | str | 显式指定输出目录（日志/截图/报告），不设则自动解析 |
| `max_suite_screenshot_dirs` | int | 截图目录上限（默认 10），超出自动清理最旧目录 |
| `error_pic_path` | str | 覆盖截图基础路径 |
| `global_variable` | dict | 全局变量字典，步骤中用 `${key}` 引用 |
| `local_storage` | dict | localStorage 键值对（需配合认证关键字使用） |
| `auth` | dict | 结构化认证配置（`cookies`/`token`/`storage.navigate_url`） |
| `target_url` | str | 应用根 URL（项目级配置，非引擎核心） |

支持 dict 和 YAML 两种方式：

```python
# dict 方式
config = {"browser_type": "chromium", "is_debug": True, "host": "http://localhost:8080"}

# YAML 文件方式
config = "config.yaml"

result = Runner(config).run(suite)
```

## 关键字完整列表

### 浏览器生命周期（2 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `open_browser` | `打开浏览器` | 启动浏览器（chromium/firefox/webkit） |
| `open_new_page` | *(auto)* | 打开新标签页并标记 |

### 页面操作（14 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `open_url` | `打开页面` | 导航到 URL（相对路径自动拼接 host） |
| `refresh` | `刷新页面` | 刷新当前页面 |
| `go_back` | `返回上一页` | 浏览器后退 |
| `go_forward` | `前进下一页` | 浏览器前进 |
| `scroll_to_height` | `滚动到高度` | 滚动到指定像素高度 |
| `execute_script` | `执行脚本` | 执行 JavaScript |
| `save_page_img` | `保存截图` | 截取页面截图 |
| `download_file` | `下载文件` | 点击触发文件下载 |
| `accept_dialog` | `接受弹窗` | 接受浏览器 alert/confirm/prompt |
| `dismiss_dialog` | `关闭弹窗` | 取消浏览器弹窗 |
| `get_page_title` | `获取页面标题` | 获取当前页面标题 |
| `get_page_url` | `获取页面URL` | 获取当前页面 URL |
| `set_viewport_size` | `设置窗口大小` | 设置浏览器视口尺寸 |
| `set_cookie` | `设置Cookie` | 运行时注入 Cookie |

### 元素操作（25 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `click_element` | `点击元素` | 单击元素（支持 `force` 强制点击） |
| `double_click` | `双击` | 双击元素 |
| `fill_value` | `输入值` | 输入框填值 |
| `type_text` | `输入文本` | 逐字符模拟输入 |
| `clear` | `清空输入框` | 清空输入框内容 |
| `hover` | `悬停` | 鼠标悬停 |
| `focus_element` | `聚焦元素` | 聚焦元素 |
| `check` | `勾选` | 勾选复选框 |
| `uncheck` | `取消勾选` | 取消勾选 |
| `set_checked` | `设置勾选` | 设置勾选状态（True/False） |
| `select_option` | `选择选项` | 原生下拉框按 value 选择 |
| `select_multiple_options` | `多选下拉` | 原生下拉框多选 |
| `click_select_option` | `点击选择选项` | 自定义 UI 下拉框（Element UI / Ant Design） |
| `drag_and_drop` | `拖拽` | 拖拽元素 |
| `upload_file` | `上传文件` | 上传文件 |
| `scroll_to_element` | `滚动到元素` | 滚动至元素可见 |
| `highlight_element` | `高亮元素` | 高亮元素（调试用） |
| `get_text` | `获取文本` | 获取元素文本内容 |
| `get_attribute` | `获取属性` | 获取元素属性（可选存入运行时变量） |
| `get_input_value` | `获取输入值` | 获取输入框当前值 |
| `get_element_count` | `获取元素数量` | 获取匹配元素数量 |
| `is_visible` | `是否可见` | 查询元素可见性 |
| `is_hidden` | `是否隐藏` | 查询元素隐藏状态 |
| `is_enabled` | `是否可用` | 查询元素可用性 |
| `is_disabled` | `是否不可用` | 查询元素禁用状态 |
| `is_checked` | `是否选中` | 查询勾选状态 |

### 鼠标键盘（8 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `mouse_click` | `鼠标点击` | 坐标点击 |
| `move_mouse` | `移动鼠标` | 坐标移动 |
| `mouse_down` | `鼠标按下` | 按下鼠标键 |
| `mouse_up` | `鼠标抬起` | 释放鼠标键 |
| `long_click` | `长按` | 长按元素（delay 毫秒） |
| `right_click` | `右键点击` | 右键点击元素 |
| `press_key` | `按键` | 键盘按键（如 "Enter"、"Tab"） |
| `press_type` | `键盘输入` | 键盘输入文本 |

### 等待（7 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `set_default_timeout` | `设置超时` | 设置全局默认超时 |
| `wait_for_time` | `强制等待` | 固定等待（毫秒） |
| `wait_for_load` | `等待加载` | 等待页面加载完成 |
| `wait_for_network` | `等待网络` | 等待网络空闲 |
| `wait_for_element` | `等待元素` | 等待元素可见 |
| `wait_for_element_hidden` | `等待元素消失` | 等待元素不可见 |
| `wait_for_url` | `等待URL` | 等待 URL 匹配 |

### 断言（13 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `assert_page_title` | `断言标题` | 断言页面标题（正则，`is_equal=0` 取反） |
| `assert_page_url` | `断言URL` | 断言页面 URL（正则） |
| `except_to_have_text` | `断言有文本` | 断言元素包含文本（正则） |
| `except_to_have_value` | `断言有值` | 断言元素值匹配（正则） |
| `except_to_have_attribute` | `断言有属性` | 断言元素属性值 |
| `except_to_be_visible` | `断言可见` | 断言元素可见 |
| `except_to_be_hidden` | `断言隐藏` | 断言元素隐藏 |
| `except_to_be_enabled` | `断言可用` | 断言元素可用 |
| `except_to_be_disabled` | `断言不可用` | 断言元素禁用 |
| `except_to_be_checked` | `断言选中` | 断言元素已勾选 |
| `except_to_be_empty` | `断言为空` | 断言元素为空 |
| `except_to_be_editable` | `断言可编辑` | 断言元素可编辑 |
| `except_to_be_focused` | `断言聚焦` | 断言元素有焦点 |

### iframe（13 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `frame_click_element` | `框架点击` | iframe 内点击元素 |
| `frame_fill_value` | `框架输入` | iframe 内输入 |
| `frame_hover` | `框架悬停` | iframe 内悬停 |
| `frame_focus_element` | `框架聚焦` | iframe 内聚焦 |
| `frame_select_option` | `框架选择` | iframe 内下拉选择 |
| `frame_type_value` | `框架输入文本` | iframe 内逐字符输入 |
| `frame_long_click_element` | `框架长按` | iframe 内长按 |
| `frame_drag_and_drop` | `框架拖拽` | iframe 内拖拽 |
| `switch_to_frame` | `切换iframe` | 切换到 iframe 上下文 |
| `switch_to_main_frame` | `切回主页面` | 切回主页面上下文 |
| `frame_except_to_be_visible` | `框架断言可见` | iframe 内断言可见 |
| `frame_except_to_be_hidden` | `框架断言隐藏` | iframe 内断言隐藏 |
| `frame_except_to_have_text` | `框架断言文本` | iframe 内断言文本 |

### 流程控制（8 个）

| 英文 | 中文 | 说明 |
|------|------|------|
| `set_variable` | `设置变量` | 存入运行时变量（`${name}` 引用） |
| `set_variable_from_element` | `从元素设置变量` | 从元素提取值到变量（text/attribute/value） |
| `if_element_visible` | `元素可见则执行` | 条件分支：元素可见执行 `then_steps`，否则 `else_steps` |
| `if_variable` | `变量满足条件则执行` | 变量比较分支（eq/ne/contains/gt/lt/ge/le） |
| `for_each` | `遍历元素集合` | 循环遍历匹配元素，每个执行 `steps` |
| `retry_until` | `重试直到成功` | 重试步骤列表直到成功或达到 `max_retry` |
| `goto_step` | `跳转步骤` | 步骤标签标记/跳转 |
| `log` | `日志输出` | 输出日志消息 |

## 流程控制示例

### 条件分支（el-select 下拉框处理）

```python
{
    "desc": "选择省份",
    "keyword": "if_element_visible",
    "params": {
        "locator": "xpath=//input[@class='el-input__inner' and not(@readonly)]",
        "timeout": 500,
        "then_steps": [
            {"desc": "输入搜索", "keyword": "fill_value",
             "params": {"locator": "...", "value": "江苏"}},
            {"desc": "选择选项", "keyword": "click_element",
             "params": {"locator": "xpath=//li[contains(.,'江苏')]"}},
        ],
        "else_steps": [
            {"desc": "选择第一项", "keyword": "click_element",
             "params": {"locator": "xpath=(//li[contains(@class,'el-select-dropdown__item')])[1]"}},
        ]
    }
}
```

### 变量操作

```python
# 设置变量
{"desc": "记录数量", "keyword": "set_variable", "params": {"name": "count", "value": "5"}}

# 从元素提取变量
{"desc": "获取标题", "keyword": "set_variable_from_element",
 "params": {"locator": "h1", "target_var": "page_title", "mode": "text"}}

# 变量条件判断
{"desc": "判断数量", "keyword": "if_variable",
 "params": {"name": "count", "operator": "gt", "compare_value": "3",
            "then_steps": [...], "else_steps": [...]}}
```

## HTML 测试报告

引擎在每次 `Runner.run()` 执行完成后自动生成 HTML 报告：

**报告路径解析**：
1. `config["project_dir"]` → 显式指定
2. 环境变量 `UIENGINE_PROJECT_DIR`
3. 调用栈中 `run.py` 所在目录
4. 当前工作目录（兜底）

**输出位置**：`{project_dir}/report/run_report/{suite_id}_{YYYYMMDD_HHMMSS}.html`

**报告特性**：
- 自包含静态 HTML（CSS + JS 内联，无外部依赖）
- 概览卡片（通过/失败/错误/跳过计数 + 通过率）
- 按模块分组摘要表（失败用例自动展开）
- 逐用例执行树（每个步骤的耗时、参数、日志、截图链接）
- 失败步骤附带源文件提示（分析 `${var}` 引用，提示检查 pages/data/cases 文件）
- 自动清理 3 天前的旧报告

**截图管理**：
- 路径：`{project_dir}/files/shortcuts/{suite_name}/`
- 最多保留 `max_suite_screenshot_dirs`（默认 10）个套件目录
- 日志：`{project_dir}/files/logs/{suite_id}_{timestamp}.log`

## 扩展机制

### 动态注册关键字

```python
from UIEngine import KeyWordManager

# 注册中英文关键字（字符串代码方式）
KeyWordManager.register_keyword(
    ["custom_login", "自定义登录"],
    '''
def custom_login(self, username, password):
    self.page.locator("#user").fill(username)
    self.page.locator("#pass").fill(password)
    self.page.locator("#submit").click()
    '''
)
```

### 认证扩展（项目级）

认证方式因系统而异，引擎提供注册接口，具体实现由项目方编写：

```python
# 项目的 lib/auth_keywords.py
from UIEngine.core.keyword_manager import KeyWordManager
from UIEngine.basecase import BaseCase

def inject_local_storage(self, key=None, value=None):
    """从 config.local_storage + config.cookie 提取 token 注入 localStorage"""
    storage_items = dict(self.config.get('local_storage', {}))
    # ... 实现逻辑 ...
    self.page.evaluate(js_script)

def register_auth_keywords():
    """注册认证关键字到引擎"""
    keywords = [
        (inject_local_storage, ["inject_local_storage", "注入LocalStorage"]),
    ]
    for func, names in keywords:
        setattr(BaseCase, func.__name__, func)
        for name in names:
            KeyWordManager.maps[name] = func
```

然后在运行入口调用 `register_auth_keywords()` 即可在 suite 的 `setup_step` 中使用 `"inject_local_storage"` 关键字。

## YAML 项目结构

对于大型项目，推荐使用 YAML 驱动的四层结构：

```
project/
├── config.yaml          # 环境配置
├── run.py               # 运行入口
├── lib/                 # 自定义关键字（认证、业务逻辑）
├── pages/               # 页面定位器（YAML，按模块组织）
│   └── common/common.yaml
├── data/                # 测试数据（YAML，按模块组织）
│   └── login/data.yaml
├── cases/               # 测试用例（YAML，引用 pages + data 变量）
│   └── login/01_login_success.yaml
└── suites/              # 测试套件（引用 cases）
    └── login/smoke.yaml
```

`run.py` 负责加载 YAML → 合并到 `config["global_variable"]` → 调用 `Runner(config).run(suite)`。

## License

MIT
