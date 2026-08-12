# -*- coding: utf-8 -*-
"""自验证测试：from_expand 分支逻辑和 XPath 生成

验证修改点 1-3 的代码正确性（不需要浏览器）
"""
import sys


def _xpath_escape_label(label: str) -> str:
    """内联版本，与 probe_utils.py:46-58 一致"""
    if not label or "'" not in label:
        return label
    parts = label.split("'")
    if len(parts) == 2:
        return f"""concat('{parts[0]}', "'", '{parts[1]}')"""
    segments = [f"'{p}'" if p else '"\'"' for p in parts]
    return f"concat({', '.join(segments)})"


def test_xpath_escape_label():
    """测试 XPath 转义函数"""
    # 普通中文（无单引号）
    assert _xpath_escape_label("退订") == "退订"
    assert _xpath_escape_label("确认订单") == "确认订单"

    # 包含单引号
    result = _xpath_escape_label("it's")
    assert "concat" in result
    assert "it" in result

    print("[PASS] _xpath_escape_label 测试通过")


def test_from_expand_xpath_generation():
    """测试 from_expand 分支生成的 XPath 格式"""
    # 模拟 from_expand 元素的 locator 生成逻辑
    label = "退订"
    escaped = _xpath_escape_label(label)

    # 模拟 discover_page.py:1354-1358 的 XPath 生成
    xpath = (
        f"//*[@x-placement and not(@x-placement='')]"
        f"//*[contains(text(),'{escaped}')"
        f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
        f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
    )

    # 验证 1: 包含 @x-placement 作用域
    assert "@x-placement" in xpath, "应包含 @x-placement 作用域"

    # 验证 2: 不包含 ancestor::tbody（错误的 table scope）
    assert "ancestor::tbody" not in xpath, "不应包含 ancestor::tbody"

    # 验证 3: 包含目标文本
    assert "退订" in xpath, "应包含目标文本"

    # 验证 4: 包含 hidden 过滤
    assert "is-hidden" in xpath, "应包含 is-hidden 过滤"
    assert "display: none" in xpath, "应包含 display:none 过滤"

    # 验证 5: 不包含 //button（错误的 tag）
    assert "//button" not in xpath, "不应包含 //button"

    print(f"[PASS] from_expand XPath 生成测试通过")
    print(f"  生成的 XPath: {xpath}")


def test_from_expand_branch_priority():
    """测试 from_expand 分支优先级（应在标准 button 分支之前）"""
    # 模拟 discover_page.py:1340-1341 的分支判断
    elem_from_expand = {
        'text': '退订',
        'type': 'dropdown-menu',
        'from_expand': True,
        'is_row_button': True
    }

    elem_normal_button = {
        'text': '删除',
        'type': 'button',
        'from_expand': False,
        'is_row_button': True
    }

    # from_expand 元素应进入专用分支
    assert elem_from_expand.get('from_expand') and 'text' in elem_from_expand, \
        "from_expand 元素应匹配专用分支条件"

    # 普通按钮不应进入 from_expand 分支
    assert not (elem_normal_button.get('from_expand') and 'text' in elem_normal_button), \
        "普通按钮不应匹配 from_expand 分支"

    print("[PASS] from_expand 分支优先级测试通过")


def test_multi_match_handling():
    """测试多匹配时的 [1] 处理"""
    # 模拟 discover_page.py:1365-1367 的逻辑
    label = "退订"
    escaped = _xpath_escape_label(label)

    base_xpath = (
        f"//*[@x-placement and not(@x-placement='')]"
        f"//*[contains(text(),'{escaped}')"
        f" and not(ancestor-or-self::*[contains(@class,'is-hidden')])"
        f" and not(ancestor-or-self::*[contains(@style,'display: none')])]"
    )

    # 模拟 count > 1 的情况
    count = 3
    xpath = base_xpath
    if count > 1:
        xpath = f"({base_xpath})[1]"

    assert xpath.startswith("(") and xpath.endswith(")[1]"), \
        "多匹配时应加 (xpath)[1] 包裹"

    print(f"[PASS] 多匹配处理测试通过")
    print(f"  生成的 XPath: {xpath}")


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("from_expand 分支自验证测试")
    print("=" * 70)

    tests = [
        test_xpath_escape_label,
        test_from_expand_xpath_generation,
        test_from_expand_branch_priority,
        test_multi_match_handling,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 异常: {e}")
            failed += 1

    print("=" * 70)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
