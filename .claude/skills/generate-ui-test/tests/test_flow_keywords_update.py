"""验证 flow_keywords 三项改动的集成测试

改动项：
1. for_each 新增 collect_to / collect 参数（数据聚合）
2. 新增 append_variable 关键字（列表追加）
3. 新增 append_variable_from_element 关键字（从元素提取并追加）

测试策略：创建本地 HTML → Playwright 打开 → UIEngine 执行步骤 → 断言变量
"""
import os
import sys
import json
import tempfile

# 确保 UIEngine 可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from UIEngine import Runner

# ======================== 测试用 HTML ========================
TEST_HTML = """<!DOCTYPE html>
<html>
<body>
  <div class="product" data-asin="B001">
    <h2 class="title">Shopping Trolley Foldable</h2>
    <span class="price">29.99</span>
    <p class="desc">Premium quality shopping cart</p>
  </div>
  <div class="product" data-asin="B002">
    <h2 class="title">Garden Wheelbarrow Heavy Duty</h2>
    <span class="price">45.50</span>
    <p class="desc">Steel construction wheelbarrow</p>
  </div>
  <div class="product" data-asin="B003">
    <h2 class="title">Portable Cooler Box 30L</h2>
    <span class="price">19.99</span>
    <p class="desc">Insulated cooler for outdoor use</p>
  </div>
  <input id="search-box" value="test_keyword" />
</body>
</html>"""

PASS = 0
FAIL = 0


def report(name, passed, detail=""):
    global PASS, FAIL
    if passed:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")


def setup_html():
    """创建临时 HTML 文件并返回 file:// URL"""
    tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8')
    tmp.write(TEST_HTML)
    tmp.close()
    return "file:///" + tmp.name.replace("\\", "/")


# ======================== 测试用例 ========================

def test_for_each_backward_compat(page_url):
    """测试1：for_each 不传 collect 参数 → 行为与改动前一致"""
    print("\n[Test 1] for_each 向后兼容（不传 collect_to / collect）")

    config = {
        "browser_type": "chromium",
        "is_debug": False,
        "host": "",
        "project_dir": os.path.dirname(os.path.abspath(__file__)),
    }
    suite = {
        "id": "test_compat",
        "name": "兼容性测试",
        "setup_step": [
            {"desc": "打开浏览器", "keyword": "open_browser", "params": {"browser_type": "chromium"}},
            {"desc": "打开测试页", "keyword": "open_url", "params": {"url": page_url}},
        ],
        "cases": [
            {
                "id": "case_compat",
                "name": "for_each 不传 collect",
                "steps": [
                    {"desc": "遍历产品", "keyword": "for_each",
                     "params": {
                         "locator": ".product",
                         "var_name": "el",
                         "steps": [
                             {"desc": "取标题", "keyword": "set_variable_from_element",
                              "params": {"locator": "${el} >> .title", "target_var": "last_title", "mode": "text"}},
                         ]
                     }},
                ]
            }
        ]
    }
    result = Runner(config).run(suite)

    # 不传 collect 时，runtime_variables 里不应有 collect_to 相关的列表
    # last_title 应该是最后一个产品的标题（被覆盖，不是列表）
    rt = config.get('runtime_variables', {})
    report("for_each 正常执行", result['success'] == 1)
    report("last_title 是字符串（被覆盖，非列表）",
           isinstance(rt.get('last_title'), str),
           f"实际类型: {type(rt.get('last_title'))}, 值: {rt.get('last_title')}")
    report("last_title 值为最后一个产品",
           rt.get('last_title', '').strip() == "Portable Cooler Box 30L",
           f"实际值: '{rt.get('last_title')}'")


def test_for_each_collect_to(page_url):
    """测试2：for_each 传 collect_to → 自动聚合数据为列表"""
    print("\n[Test 2] for_each + collect_to（数据聚合）")

    config = {
        "browser_type": "chromium",
        "is_debug": False,
        "host": "",
        "project_dir": os.path.dirname(os.path.abspath(__file__)),
    }
    suite = {
        "id": "test_collect",
        "name": "数据聚合测试",
        "setup_step": [
            {"desc": "打开浏览器", "keyword": "open_browser", "params": {"browser_type": "chromium"}},
            {"desc": "打开测试页", "keyword": "open_url", "params": {"url": page_url}},
        ],
        "cases": [
            {
                "id": "case_collect",
                "name": "for_each 收集产品数据",
                "steps": [
                    {"desc": "遍历产品并收集", "keyword": "for_each",
                     "params": {
                         "locator": ".product",
                         "var_name": "el",
                         "collect_to": "products",
                         "collect": ["asin", "title", "price"],
                         "steps": [
                             {"desc": "取ASIN", "keyword": "set_variable_from_element",
                              "params": {"locator": "${el}", "target_var": "asin",
                                         "mode": "attribute"}},
                             {"desc": "取标题", "keyword": "set_variable_from_element",
                              "params": {"locator": "${el} >> .title", "target_var": "title", "mode": "text"}},
                             {"desc": "取价格", "keyword": "set_variable_from_element",
                              "params": {"locator": "${el} >> .price", "target_var": "price", "mode": "text"}},
                         ]
                     }},
                ]
            }
        ]
    }

    # 注意：set_variable_from_element mode=attribute 取的是 value 属性
    # 我们的 HTML 用 data-asin，需要调整测试 HTML 或用 get_attribute
    # 先跳过 asin 的 attribute 测试，聚焦 collect_to 核心逻辑
    # 改用 set_variable 手动设置来验证 collect 聚合机制
    suite["cases"][0]["steps"] = [
        {"desc": "遍历产品并收集", "keyword": "for_each",
         "params": {
             "locator": ".product",
             "var_name": "el",
             "collect_to": "products",
             "collect": ["title", "price"],
             "steps": [
                 {"desc": "取标题", "keyword": "set_variable_from_element",
                  "params": {"locator": "${el} >> .title", "target_var": "title", "mode": "text"}},
                 {"desc": "取价格", "keyword": "set_variable_from_element",
                  "params": {"locator": "${el} >> .price", "target_var": "price", "mode": "text"}},
             ]
         }},
    ]

    result = Runner(config).run(suite)
    rt = config.get('runtime_variables', {})
    products = rt.get('products', [])

    report("for_each 执行成功", result['success'] == 1)
    report("products 是列表", isinstance(products, list), f"实际类型: {type(products)}")
    report("products 有 3 条记录", len(products) == 3, f"实际数量: {len(products)}")

    if len(products) == 3:
        report("第1条标题正确",
               products[0]['title'].strip() == "Shopping Trolley Foldable",
               f"实际: '{products[0]['title']}'")
        report("第2条价格正确",
               products[1]['price'].strip() == "45.50",
               f"实际: '{products[1]['price']}'")
        report("第3条完整",
               products[2]['title'].strip() == "Portable Cooler Box 30L"
               and products[2]['price'].strip() == "19.99",
               f"实际: title='{products[2]['title']}', price='{products[2]['price']}'")
    print(f"  [DATA] collected: {json.dumps(products, ensure_ascii=False, indent=2)}")


def test_append_variable(page_url):
    """测试3：append_variable 关键字"""
    print("\n[Test 3] append_variable（列表追加）")

    config = {
        "browser_type": "chromium",
        "is_debug": False,
        "host": "",
        "project_dir": os.path.dirname(os.path.abspath(__file__)),
    }
    suite = {
        "id": "test_append",
        "name": "追加变量测试",
        "setup_step": [
            {"desc": "打开浏览器", "keyword": "open_browser", "params": {"browser_type": "chromium"}},
            {"desc": "打开测试页", "keyword": "open_url", "params": {"url": page_url}},
        ],
        "cases": [
            {
                "id": "case_append",
                "name": "多次追加",
                "steps": [
                    {"desc": "追加第1个", "keyword": "append_variable",
                     "params": {"name": "tags", "value": "outdoor"}},
                    {"desc": "追加第2个", "keyword": "append_variable",
                     "params": {"name": "tags", "value": "shopping"}},
                    {"desc": "追加第3个", "keyword": "append_variable",
                     "params": {"name": "tags", "value": "portable"}},
                ]
            }
        ]
    }
    result = Runner(config).run(suite)
    rt = config.get('runtime_variables', {})
    tags = rt.get('tags', [])

    report("执行成功", result['success'] == 1)
    report("tags 是列表", isinstance(tags, list), f"实际类型: {type(tags)}")
    report("tags 有 3 个元素", len(tags) == 3, f"实际数量: {len(tags)}")
    report("tags 内容正确",
           tags == ["outdoor", "shopping", "portable"],
           f"实际值: {tags}")


def test_append_variable_from_element(page_url):
    """测试4：append_variable_from_element 关键字"""
    print("\n[Test 4] append_variable_from_element（从元素提取并追加）")

    config = {
        "browser_type": "chromium",
        "is_debug": False,
        "host": "",
        "project_dir": os.path.dirname(os.path.abspath(__file__)),
    }
    suite = {
        "id": "test_append_el",
        "name": "从元素追加测试",
        "setup_step": [
            {"desc": "打开浏览器", "keyword": "open_browser", "params": {"browser_type": "chromium"}},
            {"desc": "打开测试页", "keyword": "open_url", "params": {"url": page_url}},
        ],
        "cases": [
            {
                "id": "case_append_el",
                "name": "逐个追加产品标题",
                "steps": [
                    {"desc": "追加第1个标题", "keyword": "append_variable_from_element",
                     "params": {"locator": ".product >> nth=0 >> .title", "target_var": "all_titles", "mode": "text"}},
                    {"desc": "追加第2个标题", "keyword": "append_variable_from_element",
                     "params": {"locator": ".product >> nth=1 >> .title", "target_var": "all_titles", "mode": "text"}},
                    {"desc": "追加第3个标题", "keyword": "append_variable_from_element",
                     "params": {"locator": ".product >> nth=2 >> .title", "target_var": "all_titles", "mode": "text"}},
                    {"desc": "追加输入框值", "keyword": "append_variable_from_element",
                     "params": {"locator": "#search-box", "target_var": "all_titles", "mode": "value"}},
                ]
            }
        ]
    }
    result = Runner(config).run(suite)
    rt = config.get('runtime_variables', {})
    all_titles = rt.get('all_titles', [])

    report("执行成功", result['success'] == 1)
    report("all_titles 是列表", isinstance(all_titles, list))
    report("all_titles 有 4 个元素", len(all_titles) == 4, f"实际: {len(all_titles)}")
    if len(all_titles) >= 4:
        report("第1个标题正确",
               all_titles[0] == "Shopping Trolley Foldable",
               f"实际: '{all_titles[0]}'")
        report("第3个标题正确",
               all_titles[2] == "Portable Cooler Box 30L",
               f"实际: '{all_titles[2]}'")
        report("第4个是输入框值",
               all_titles[3] == "test_keyword",
               f"实际: '{all_titles[3]}'")
    print(f"  [DATA] appended: {all_titles}")


def test_keyword_registered():
    """测试0：验证新关键字已注册（不需要浏览器）"""
    print("\n[Test 0] 关键字注册检查")
    from UIEngine.core.keyword_manager import KeyWordManager

    report("append_variable 已注册（英文）",
           "append_variable" in KeyWordManager.maps,
           f"maps keys: {[k for k in KeyWordManager.maps if 'append' in k]}")
    report("追加变量 已注册（中文）",
           "追加变量" in KeyWordManager.maps)
    report("append_variable_from_element 已注册（英文）",
           "append_variable_from_element" in KeyWordManager.maps)
    report("从元素追加变量 已注册（中文）",
           "从元素追加变量" in KeyWordManager.maps)


# ======================== 主入口 ========================

if __name__ == "__main__":
    print("=" * 60)
    print("UIEngine flow_keywords 改动验证")
    print("=" * 60)

    # 先检查关键字注册（无需浏览器）
    test_keyword_registered()

    # 创建测试页面
    page_url = setup_html()
    print(f"\n测试页面: {page_url}")

    try:
        test_for_each_backward_compat(page_url)
        test_for_each_collect_to(page_url)
        test_append_variable(page_url)
        test_append_variable_from_element(page_url)
    finally:
        # 清理临时文件
        path = page_url.replace("file:///", "")
        if os.path.exists(path):
            os.unlink(path)

    print("\n" + "=" * 60)
    print(f"结果: {PASS} 通过 | {FAIL} 失败")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
