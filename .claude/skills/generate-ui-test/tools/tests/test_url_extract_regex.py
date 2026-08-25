#!/usr/bin/env python3
"""
测试 pipeline.py 的 URL 提取正则表达式
覆盖场景：
1. 有空格相对路径: "访问 /estack/web/vpc"
2. 无空格相对路径: "访问/estack/web/estack/role"
3. 完整 HTTP URL: "打开 http://10.151.37.249/path"
4. 完整 HTTPS URL: "打开 https://example.com/path"
5. 中文文本中的斜杠（不匹配）: "点击"确认"按钮"
6. 中文键值对中的斜杠（不匹配）: "在"产品/服务"中输入"
7. 混合: 一个步骤里同时有完整 URL 和相对路径
8. 查询参数和锚点: "访问 /path?key=value#anchor"
9. 仅中文: "等待页面加载完成" (无匹配)
10. 边界: 斜杠开头但后面是中文 (不匹配)
"""
import re
import sys

# 从 pipeline.py 复制的正则（确保一致）
_URL_RE = re.compile(
    r'(https?://[^\s]+)'
    r'|'
    r'(?<!\w)(/[a-zA-Z][\w/\-#.?&=%]*)',
    re.ASCII
)


def extract_urls(step_text):
    """模拟 pipeline.py 的提取逻辑"""
    results = []
    for m in _URL_RE.finditer(step_text):
        url_str = m.group(1) or m.group(2)
        results.append(url_str)
    return results


def test_case(name, step_text, expected):
    """运行单个测试用例"""
    actual = extract_urls(step_text)
    passed = actual == expected
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}")
    print(f"       输入: {repr(step_text)}")
    print(f"       期望: {expected}")
    print(f"       实际: {actual}")
    if not passed:
        print("       *** 测试失败 ***")
    print()
    return passed


def main():
    all_passed = True

    # 场景 1: 有空格相对路径（旧格式，之前能匹配）
    all_passed &= test_case(
        "场景 1: 有空格相对路径",
        "访问 /estack/web/vpc-console/vpcList",
        ["/estack/web/vpc-console/vpcList"]
    )

    # 场景 2: 无空格相对路径（新格式，之前不能匹配）
    all_passed &= test_case(
        "场景 2: 无空格相对路径",
        "访问/estack/web/estack/user-center/user-manage/role",
        ["/estack/web/estack/user-center/user-manage/role"]
    )

    # 场景 3: 完整 HTTP URL
    all_passed &= test_case(
        "场景 3: 完整 HTTP URL",
        "打开 http://10.151.37.249/estack/path",
        ["http://10.151.37.249/estack/path"]
    )

    # 场景 4: 完整 HTTPS URL
    all_passed &= test_case(
        "场景 4: 完整 HTTPS URL",
        "打开 https://example.com/api/test",
        ["https://example.com/api/test"]
    )

    # 场景 5: 中文文本中的斜杠（不应匹配）
    all_passed &= test_case(
        "场景 5: 中文文本中的斜杠",
        '点击"确认"按钮',
        []
    )

    # 场景 6: 中文键值对中的斜杠（不应匹配）
    all_passed &= test_case(
        "场景 6: 中文键值对中的斜杠",
        '在"产品/服务"中输入',
        []
    )

    # 场景 7: 混合（完整 URL 和相对路径）
    all_passed &= test_case(
        "场景 7: 混合完整 URL 和相对路径",
        "从 http://old.com/path 跳转到 /new/path",
        ["http://old.com/path", "/new/path"]
    )

    # 场景 8: 查询参数和锚点
    all_passed &= test_case(
        "场景 8: 查询参数和锚点",
        "访问 /path?key=value&other=123#section",
        ["/path?key=value&other=123#section"]
    )

    # 场景 9: 仅中文（无匹配）
    all_passed &= test_case(
        "场景 9: 仅中文",
        "等待页面加载完成",
        []
    )

    # 场景 10: 斜杠开头但后面是中文（不应匹配）
    all_passed &= test_case(
        "场景 10: 斜杠开头但后面是中文",
        "访问 /中文路径",
        []
    )

    # 场景 11: 多个空格分隔的相对路径
    all_passed &= test_case(
        "场景 11: 多个空格分隔的相对路径",
        "从 /old/path 到 /new/path",
        ["/old/path", "/new/path"]
    )

    # 场景 12: 实际云管用例步骤（无空格）
    all_passed &= test_case(
        "场景 12: 实际云管用例步骤（无空格）",
        "访问/estack/web/estack/user-center/user-manage/authority-manage",
        ["/estack/web/estack/user-center/user-manage/authority-manage"]
    )

    # 场景 13: 实际其他模块用例步骤（有空格）
    all_passed &= test_case(
        "场景 13: 实际其他模块用例步骤（有空格）",
        "访问 /estack/web/op-compute-web/#/order/vm?orderSource=consoleList",
        ["/estack/web/op-compute-web/#/order/vm?orderSource=consoleList"]
    )

    # 场景 14: 边界 - 斜杠在单词中间（不应匹配）
    all_passed &= test_case(
        "场景 14: 斜杠在单词中间",
        "ratio is 1/2",
        []
    )

    # 场景 15: 边界 - 斜杠后面是数字（不应匹配，要求字母开头）
    all_passed &= test_case(
        "场景 15: 斜杠后面是数字",
        "访问 /123/path",
        []
    )

    print("=" * 60)
    if all_passed:
        print("ALL PASSED: all tests passed")
        return 0
    else:
        print("FAILED: some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
