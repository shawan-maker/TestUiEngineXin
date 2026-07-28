#!/usr/bin/env python3
"""
知识库文档同步工具

从 probe_knowledge.json 自动生成/更新 locator-patterns.md。
当 learn_probe.py 学习了新的 XPath 模板后，调用此工具同步文档。

使用方式：
    python sync_locator_docs.py [knowledge.json路径] [--output locator-patterns.md路径]

默认路径：
    knowledge: tools/probe_knowledge.json
    output:    knowledge/locator-patterns.md
"""
import json
import os
import sys

# ============================================================================
# 章节定义（固定结构 + 说明文本）
# ============================================================================

SECTION_DEFS = [
    {
        "num": "一", "title": "各种输入框（普通输入框、文本框、选择框、级联框、时间选择框）",
        "category_type": "single_step",
        "categories": ["input-generic", "textarea-generic"],
        "intro": '替换规则：`选项文本` → 字段 label 文本（如“项目名称”、“问题描述”）',
    },
    {
        "num": "二", "title": "el-select 下拉框操作（三步法）",
        "category_type": "multi_step",
        "categories": ["el-select"],
        "steps_order": ["expand", "fill", "select"],
        "step_labels": {
            "expand": "第一步：点击展开下拉框",
            "fill": "第二步：输入搜索文本",
            "select": "第三步：选择第一个匹配的元素",
        },
        "step_keywords": {
            "expand": "click_element",
            "fill": "fill_value",
            "select": "click_element",
        },
        "notes": "⚠️ Step 2 搜索文本与 Step 3 选项文本必须一致（均来自用户用例），禁止从 probe 的 select_options 中随意选取。",
    },
    {
        "num": "三", "title": "级联选择器（el-cascader）操作",
        "category_type": "multi_step",
        "categories": ["el-cascader"],
        "steps_order": ["expand", "select-level"],
        "step_labels": {
            "expand": "第一步：点击展开选择器",
            "select-level": "第二步及后续：勾选/展开某一级（可重复多次）",
        },
        "step_keywords": {
            "expand": "click_element",
            "select-level": "click_element",
        },
    },
    {
        "num": "四", "title": "时间选择框（el-date-picker）操作",
        "category_type": "multi_step",
        "categories": ["date-picker"],
        "steps_order": ["expand", "select-today", "select-now", "select-month", "range-start", "range-end"],
        "step_labels": {
            "expand": "第一步：点击展开时间选择框",
            "select-today": "选择今天（用 class=\"today\" 匹配，不是文本）",
            "select-now": "选择此刻",
            "select-month": "选择当月",
            "range-start": "选择起始时间（日期范围）",
            "range-end": "选择结束时间",
        },
        "step_keywords": {
            "expand": "click_element",
            "select-today": "click_element",
            "select-now": "click_element",
            "select-month": "click_element",
            "range-start": "click_element",
            "range-end": "click_element",
        },
        "notes": "⚠️ \"今天\"用 `class=\"today\"` 匹配，Element UI 日期选择器的\"今天\"单元格**不显示\"今天\"文字**。",
    },
    {
        "num": "五", "title": "下载导出按钮",
        "category_type": "single_step",
        "categories": ["download-button"],
    },
    {
        "num": "六", "title": "关闭按钮（tag 标签关闭）",
        "category_type": "single_step",
        "categories": ["close-button"],
    },
    {
        "num": "七", "title": "搜索按钮",
        "category_type": "single_step",
        "categories": ["search-button"],
    },
    {
        "num": "八", "title": "页面中的普通按钮",
        "category_type": "single_step",
        "categories": ["button"],
        "notes": "替换规则：按钮名称拆分为单字 contains 组合，如\"新增\" → `contains(.,\"新\") and contains(.,\"增\")`",
    },
    {
        "num": "九", "title": "列表右侧按钮（表格行操作按钮）",
        "category_type": "composite",
        "categories": ["table-action-button"],
        "notes": "不是所有表格都有固定右侧列，必须通过 probe 确认使用哪种路径。",
    },
    {
        "num": "十", "title": "列表右侧的\"更多\"展开按钮",
        "category_type": "composite",
        "categories": ["dropdown-menu"],
        "steps_order": ["click-more", "click-action"],
        "step_labels": {
            "click-more": "第一步：点击\"更多\"",
            "click-action": "第二步：点击对应的操作按钮",
        },
        "step_keywords": {
            "click-more": "click_element",
            "click-action": "click_element",
        },
    },
    {
        "num": "十一", "title": "点击侧边的目录",
        "category_type": "single_step",
        "categories": ["menu-item"],
    },
    {
        "num": "十二", "title": "进入详情页",
        "category_type": "single_step",
        "categories": ["detail-link"],
    },
    {
        "num": "十三", "title": "点击批量全选",
        "category_type": "single_step",
        "categories": ["checkbox-all"],
    },
    {
        "num": "十四", "title": "断言（存在即可，不用精确匹配到一个元素）",
        "category_type": "assertion",
        "categories": ["success-toast", "error-toast", "first-row-content", "field-value"],
        "no_hidden_filter": True,
        "intro": "断言定位器是隐藏过滤的例外 — `//*[contains(.,'xx')]` 通用文本匹配不需要加隐藏过滤属性。\n\n所有断言统一使用 `except_to_be_visible`，禁止使用 `except_to_have_text`/`except_to_have_value`/`except_to_have_attribute`。",
    },
    {
        "num": "十五", "title": "多 tab 时右侧操作按钮",
        "category_type": "composite",
        "categories": ["tab-scoped"],
        "steps_order": ["get-tab-id", "scoped-button", "scoped-input", "scoped-detail-link", "scoped-menu-item"],
        "step_labels": {
            "get-tab-id": "第一步：点击 tab + 获取 aria-controls 属性值",
            "scoped-button": "第三步：tab 作用域内的按钮",
            "scoped-input": "第三步：tab 作用域内的输入框",
            "scoped-detail-link": "第三步：tab 作用域内的详情链接",
            "scoped-menu-item": "第三步：tab 作用域内的侧边目录",
        },
        "notes": "⚠️ 多 tab 时，**所有元素**（不光是按钮）都要先切换 tab → 获取 aria-controls → 在 xpath 前加 `//div[@id='{变量}']` 前缀。",
    },
    {
        "num": "十六", "title": "有 iframe 的情况",
        "category_type": None,  # 特殊：不对应 JSON 分类
        "categories": [],
        "intro": "同多 tab 的处理思路：如果探测发现某个元素在 iframe 下，先切换到 iframe，再进行相关操作。进入 iframe 后的元素定位或断言方法跟前面一样。",
        "static_content": """### 操作流程

| 步骤 | 关键字 | 说明 |
|------|--------|------|
| 1. 切换到 iframe | `switch_to_frame` | 参数 `frame_locator_str` 为 iframe 的定位表达式 |
| 2. 在 iframe 内操作 | `frame_fill_value` / `frame_click_element` 等 | 参数 `frame` 为 iframe 定位器，`locator` 为 iframe 内目标元素 |
| 3. 切回主页面 | `switch_to_main_frame` | 操作完成后必须切回 |

> ⚠️ 如果某个字段通过 `frame_fill_value` 填写（TinyMCE/UEditor 富文本），该字段的断言也必须用 `execute_script` 读取 iframe 内容（页面级 XPath 无法穿透 iframe）。""",
    },
]


# ============================================================================
# 文档生成
# ============================================================================

def format_xpath_block(xpath_str):
    """格式化单个 XPath 为 markdown 代码块"""
    return f"```xpath\n{xpath_str}\n```"


def format_patterns_list(patterns, is_dict_format=False):
    """格式化 patterns 列表为 markdown"""
    lines = []
    for p in patterns:
        if isinstance(p, dict):
            xpath = p.get("xpath", "")
            source = p.get("source", "")
            count = p.get("success_count", 0)
            prefix = f"# [学习] source={source}, count={count}\n" if source else ""
            lines.append(f"```xpath\n{prefix}{xpath}\n```")
        else:
            lines.append(f"```xpath\n{p}\n```")
    return "\n\n".join(lines)


def generate_section(section_def, db):
    """生成一个章节的 markdown 内容"""
    lines = []
    num = section_def["num"]
    title = section_def["title"]
    lines.append(f"## {num}、{title}\n")

    # 介绍文本
    if section_def.get("intro"):
        lines.append(f"{section_def['intro']}\n")

    # 静态内容（iframe 特殊章节）
    if section_def.get("static_content"):
        lines.append(section_def["static_content"])
        return "\n".join(lines)

    category_type = section_def.get("category_type")
    categories = section_def.get("categories", [])

    if not category_type or not categories:
        return "\n".join(lines)

    type_data = db.get(category_type, {})
    type_categories = type_data.get("categories", {})

    # 多步模板
    if section_def.get("steps_order"):
        steps_order = section_def["steps_order"]
        step_labels = section_def.get("step_labels", {})
        step_keywords = section_def.get("step_keywords", {})

        for cat_name in categories:
            cat_data = type_categories.get(cat_name, {})
            steps_data = cat_data.get("steps", {})

            for step_name in steps_order:
                if step_name not in steps_data:
                    continue
                step = steps_data[step_name]
                label = step_labels.get(step_name, step_name)
                keyword = step_keywords.get(step_name, "click_element")

                lines.append(f"### {label}\n")
                if step.get("desc"):
                    lines.append(f"_{step['desc']}_\n")
                lines.append(f"- **关键字**：`{keyword}`\n")
                patterns = step.get("patterns", [])
                if patterns:
                    lines.append(format_patterns_list(patterns))
                    lines.append("")

    # 单步模板
    else:
        for cat_name in categories:
            cat_data = type_categories.get(cat_name, {})
            patterns = cat_data.get("patterns", [])
            if len(categories) > 1:
                cat_display_name = cat_data.get("name", cat_name)
                lines.append(f"### {cat_display_name}\n")
            if patterns:
                lines.append(format_patterns_list(patterns))
                lines.append("")

    # 备注
    if section_def.get("notes"):
        lines.append(f"> {section_def['notes']}\n")

    return "\n".join(lines)


def generate_speed_table(db):
    """生成速查表"""
    rows = [
        ("1", "输入框/文本框", "`fill_value`", "1", "`single_step/input-generic`, `textarea-generic`"),
        ("2", "el-select", "`click_element` + `fill_value` + `click_element`", "3", "`multi_step/el-select`"),
        ("3", "el-cascader", "`click_element` × N", "2+", "`multi_step/el-cascader`"),
        ("4", "el-date-picker", "`click_element` × 2", "2", "`multi_step/date-picker`"),
        ("5", "下载/导出", "`click_element` / `download_file`", "1", "`single_step/download-button`"),
        ("6", "搜索", "`click_element`", "1", "`single_step/search-button`"),
        ("7", "普通按钮", "`click_element`", "1", "`single_step/button`"),
        ("8", "列表行按钮", "`click_element`", "1", "`composite/table-action-button`"),
        ("9", "更多菜单", "`click_element` × 2", "2", "`composite/dropdown-menu`"),
        ("10", "侧边目录", "`click_element`", "1", "`single_step/menu-item`"),
        ("11", "详情页链接", "`click_element`", "1", "`single_step/detail-link`"),
        ("12", "批量全选", "`click_element`", "1", "`single_step/checkbox-all`"),
        ("13", "断言", "`except_to_be_visible`", "1", "`assertion/*`"),
        ("14", "多 tab 操作", "`click_element` + `get_attribute` + 操作", "3", "`composite/tab-scoped`"),
        ("15", "iframe 内操作", "`switch_to_frame` + frame 系列 + `switch_to_main_frame`", "3", "— (规则 R3.11)"),
    ]

    lines = [
        "## 速查表\n",
        "| # | 元素类型 | 关键字 | 操作步数 | 对应 probe_knowledge.json 路径 |",
        "|---|---------|--------|---------|-------------------------------|",
    ]
    for row in rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |")

    return "\n".join(lines)


def generate_full_document(db):
    """生成完整的 locator-patterns.md"""
    header = """# 元素定位器模式参考（16 类 · 已验证可直接使用）

> **本文档由 `tools/sync_locator_docs.py` 从 `probe_knowledge.json` 自动生成。**
> **所有 XPath 表达式均已在目标系统中验证，可直接遍历使用，只需修改对应的数据/文本/按钮名称。**
>
> 对应 `tools/probe_knowledge.json` 的模板定义，本文件提供人类可读的操作说明。
>
> 最后同步时间：由 `learn_probe.py` 学习新模板后自动触发。

---

## 🚨 通用原则：隐藏过滤（所有模式必须遵守）

**所有元素表达式的最后一个标签中必须加上隐藏过滤属性**（查找非隐藏的元素）：

```xpath
and not(ancestor::*[contains(@class,'is-hidden')]) and not(ancestor::*[contains(@style,'display: none')])
```

如果标签已有属性条件，前面加 `and` 连接。

**例外**（以下定位器不需要隐藏过滤）：
- `//*[contains(.,'xx')]` — 通用文本匹配断言定位器
- 含 `@x-placement` 的 option 定位器 — 已有可见性逻辑（面板隐藏时整个 dropdown 不可见）
- 含 `not(contains(@style,'display: none'))` 的容器定位器 — 已有可见性过滤

---
"""

    sections = []
    for section_def in SECTION_DEFS:
        sections.append(generate_section(section_def, db))

    speed_table = generate_speed_table(db)

    return header + "\n---\n\n".join(sections) + "\n\n---\n\n" + speed_table + "\n"


# ============================================================================
# 入口
# ============================================================================

def sync_docs(knowledge_path=None, output_path=None):
    """同步知识库到 locator-patterns.md"""
    if knowledge_path is None:
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        knowledge_path = os.path.join(skill_dir, 'tools', 'probe_knowledge.json')

    if output_path is None:
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = os.path.join(skill_dir, 'knowledge', 'locator-patterns.md')

    if not os.path.isfile(knowledge_path):
        print(f"[ERR] 知识库文件不存在: {knowledge_path}")
        return False

    with open(knowledge_path, 'r', encoding='utf-8') as f:
        db = json.load(f)

    content = generate_full_document(db)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"文档已同步: {output_path}")
    print(f"  来源: {knowledge_path}")
    print(f"  版本: {db.get('version', '?')}")
    return True


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ('-h', '--help'):
        print("用法: python sync_locator_docs.py [knowledge.json路径] [--output 输出路径]")
        print("")
        print("默认路径:")
        print("  knowledge: tools/probe_knowledge.json")
        print("  output:    knowledge/locator-patterns.md")
        sys.exit(0)

    knowledge_path = sys.argv[1] if len(sys.argv) >= 2 and not sys.argv[1].startswith('--') else None
    output_path = None

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == '--output' and i < len(sys.argv) - 1:
            output_path = sys.argv[i + 1]

    sync_docs(knowledge_path, output_path)


if __name__ == '__main__':
    main()
