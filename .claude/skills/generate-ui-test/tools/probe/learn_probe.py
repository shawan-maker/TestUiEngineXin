"""探针自学习工具 v2

功能：将用户纠正的正确 XPath 自动学习并合并到探针知识库中。
支持单步/多步/组合模板的学习。

使用方式：
    python learn_probe.py <knowledge.json> <category_type> <category_name> <label> <corrected_xpath> <source_case>

示例：
    # 学习单步按钮
    python learn_probe.py TSManager/_probe/knowledge.json single_step button 查询 "//button[contains(.,'查') and contains(.,'询') and not(ancestor-or-self::*[contains(@class,'is-hidden')]) and not(ancestor-or-self::*[contains(@style,'display: none')])]" case_18

    # 学习多步 el-select 的 select 步骤
    python learn_probe.py TSManager/_probe/knowledge.json multi_step el-select:select 项目名称 "(//div[@x-placement and not(@x-placement='')]//li[contains(.,'{option_text}')])[1]" case_01
"""
import json
import sys
import os


def extract_template(corrected_xpath, label, option_text=None):
    """从纠正的 XPath 中提取模板（将具体文本替换为占位符）

    支持的替换：
    - label 文本 → {label}
    - option_text 文本 → {option_text}
    - 单字 → {char1}, {char2}
    """
    template = corrected_xpath

    # 先替换 option_text（如果有），避免被 label 替换覆盖
    if option_text:
        template = template.replace(option_text, "{option_text}")

    # 替换 label
    if label:
        template = template.replace(label, "{label}")

    return template


def find_category(db, category_type, category_name):
    """在知识库中找到对应的分类"""
    categories = db.get(category_type, {}).get("categories", {})

    # 处理复合键（如 el-select:select）
    if ':' in category_name:
        base_name, step_name = category_name.split(':', 1)
        if base_name in categories:
            cat = categories[base_name]
            # 多步模板
            if 'steps' in cat:
                steps = cat['steps']
                if step_name in steps:
                    return cat, steps[step_name], True  # is_step=True
            # 单步模板
            return cat, cat, False
    else:
        if category_name in categories:
            cat = categories[category_name]
            if 'steps' in cat:
                return cat, cat['steps'], True
            return cat, cat, False

    return None, None, False


def learn_correction(knowledge_path, category_type, category_name, label, corrected_xpath, source_case, option_text=None):
    """学习用户纠正的正确 XPath，自动合并到知识库

    :param knowledge_path: 知识库文件路径
    :param category_type: 分类类型 (single_step / multi_step / composite / assertion)
    :param category_name: 分类名称
    :param label: 元素标签文本
    :param corrected_xpath: 用户纠正的正确 XPath
    :param source_case: 来源用例标识
    :param option_text: 选项文本（用于多步模板中的 option_text 占位符）
    :return: 是否成功学习
    """
    # 加载知识库
    if os.path.exists(knowledge_path):
        with open(knowledge_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
    else:
        db = {"version": "2.0", "single_step": {"categories": {}}, "multi_step": {"categories": {}}, "composite": {"categories": {}}, "assertion": {"categories": {}}}

    # 确保分类存在
    if category_type not in db:
        db[category_type] = {"categories": {}}

    categories = db[category_type].setdefault("categories", {})
    if category_name not in categories:
        categories[category_name] = {"name": category_name, "patterns": [], "fallback": ""}

    category = categories[category_name]

    # 提取模板
    template = extract_template(corrected_xpath, label, option_text)

    # 去重检查：是否已存在相同模板
    learned = False

    # 处理多步模板
    if 'steps' in category:
        if category_name in db.get('multi_step', {}).get('categories', {}):
            # 多步模板需要指定 step
            print(f"  [提示] 多步模板请使用 category_name 格式: {category_name}:step_name")
            return False
    else:
        # 单步模板
        patterns = category.get("patterns", [])
        for p in patterns:
            if isinstance(p, str):
                if p == template:
                    learned = True
                    break
            elif isinstance(p, dict):
                if p.get("xpath") == template:
                    p["success_count"] = p.get("success_count", 0) + 1
                    p["verified"] = True
                    learned = True
                    break

    if not learned:
        # 新学的模板，插入首位（最高优先级）
        if "patterns" not in category:
            category["patterns"] = []

        # 检查是否已经是 dict 格式
        if category["patterns"] and isinstance(category["patterns"][0], dict):
            new_entry = {
                "xpath": template,
                "source": f"user_correction_{source_case}",
                "verified": True,
                "success_count": 1
            }
            category["patterns"].insert(0, new_entry)
        else:
            category["patterns"].insert(0, template)

        print(f"  [NEW] 新增模板到 [{category_type}/{category_name}]")

    # 写回知识库
    os.makedirs(os.path.dirname(os.path.abspath(knowledge_path)), exist_ok=True)
    with open(knowledge_path, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"已学习: [{category_type}/{category_name}] {template[:80]}{'...' if len(template) > 80 else ''}")

    # 自动同步 locator-patterns.md 文档
    try:
        from sync_locator_docs import sync_docs
        # 确定文档输出路径（与知识库同级项目或全局 knowledge/ 目录）
        skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        global_kb = os.path.join(skill_dir, 'tools', 'probe_knowledge.json')
        if os.path.abspath(knowledge_path) == os.path.abspath(global_kb):
            # 全局知识库 → 同步到全局文档
            sync_docs(knowledge_path)
        else:
            # 项目级知识库 → 同步到全局文档（文档只有一份）
            sync_docs(global_kb)
    except Exception as e:
        print(f"  [WARN] 文档同步失败（不影响学习）: {e}")

    return True


def main():
    """CLI 入口"""
    if len(sys.argv) < 7:
        print("用法: python learn_probe.py <knowledge.json> <category_type> <category_name> <label> <corrected_xpath> <source_case> [option_text]")
        print("")
        print("示例:")
        print("  # 学习单步按钮")
        print("  python learn_probe.py TSManager/_probe/knowledge.json single_step button 查询 \"//button[contains(.,'查') and contains(.,'询')]\" case_18")
        print("")
        print("  # 学习带选项文本的多步模板")
        print("  python learn_probe.py TSManager/_probe/knowledge.json multi_step el-select 项目名称 \"(//div[@x-placement and not(@x-placement='')]//li[contains(.,'{option_text}')])[1]\" case_01 \"选项文本\"")
        sys.exit(1)

    knowledge_path = sys.argv[1]
    category_type = sys.argv[2]
    category_name = sys.argv[3]
    label = sys.argv[4]
    corrected_xpath = sys.argv[5]
    source_case = sys.argv[6]
    option_text = sys.argv[7] if len(sys.argv) > 7 else None

    learn_correction(knowledge_path, category_type, category_name, label, corrected_xpath, source_case, option_text)


if __name__ == '__main__':
    main()
