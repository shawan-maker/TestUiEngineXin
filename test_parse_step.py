"""验证 parse_step 对"点击「新增」按钮"的解析结果"""
import sys
sys.path.insert(0, r"D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools")

from core.step_patterns import parse_step

test_cases = [
    "点击「新增」按钮",
    "点击新增按钮",
    "点击「新增」",
    "点击新增",
]

for text in test_cases:
    result = parse_step(text)
    print(f"\n输入: '{text}'")
    print(f"  type: {result.get('type')}")
    print(f"  args: {result.get('args')}")
