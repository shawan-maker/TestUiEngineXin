#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 wait_for_loading_complete 自动插入逻辑

验证场景：
1. 点击按钮 → 无后续步骤 → 插入 wait_for_loading_complete
2. 点击按钮 → 等待1s → 先插入 wait_for_loading_complete，再等待1s
3. 点击按钮 → 等待加载完成 → 不重复插入
4. 点击按钮 → 断言 → 不插入（断言前无需等待）
"""
import sys
import io
from pathlib import Path
from unittest.mock import Mock

# 设置标准输出为 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加 tools 目录到 sys.path
tools_dir = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_dir))

from core.step_patterns import parse_step


def mock_find_workflow(cn_name):
    """Mock _find_workflow 方法"""
    workflow_map = {
        '等待加载完成': {'name': 'wait_for_loading_complete', 'chinese_name': '等待加载完成'},
        '等待页面加载完成': {'name': 'wait_for_loading_complete', 'chinese_name': '等待页面加载完成'},
        '等待1s': {'name': 'wait_for_time', 'chinese_name': '等待1s'},
        '检查页面加载完成': {'name': 'check_page_loaded', 'chinese_name': '检查页面加载完成'},
    }
    return workflow_map.get(cn_name)


def test_scenario_1():
    """场景1：点击按钮 → 无后续步骤 → 插入 wait_for_loading_complete"""
    print("\n" + "=" * 80)
    print("场景1：点击按钮 → 无后续步骤")
    print("=" * 80)

    raw_steps = ['点击"确认订单"按钮']

    # 模拟 _next_needs_no_wait 逻辑（需要 mock _find_workflow）
    idx = 0
    if idx + 1 >= len(raw_steps):
        no_wait = False
    else:
        next_step = raw_steps[idx + 1]
        next_parsed = parse_step(next_step)
        next_type = next_parsed.get('type')

        if next_type != 'l3_call':
            no_wait = next_type in {'wait_element', 'assert', 'assert_row', 'assert_count', 'check_assert'}
        else:
            cn_name = next_parsed.get('args', (None,))[0]
            wf_def = mock_find_workflow(cn_name) if cn_name else None
            blocking_keywords = {'wait_for_loading_complete', 'check_page_loaded'}
            no_wait = wf_def and wf_def.get('name') in blocking_keywords if wf_def else False

    # 当前步骤是 click_btn
    current_parsed = parse_step(raw_steps[0])
    is_button = current_parsed.get('type') == 'click_btn'

    # 判断是否插入
    should_insert = is_button and not no_wait

    print(f"当前步骤: {raw_steps[0]}")
    print(f"下一步: (无)")
    print(f"no_wait: {no_wait}")
    print(f"should_insert wait_for_loading_complete: {should_insert}")

    assert no_wait == False, "无后续步骤时 no_wait 应为 False"
    assert should_insert == True, "应插入 wait_for_loading_complete"
    print("✅ 验证通过")


def test_scenario_2():
    """场景2：点击按钮 → 等待1s → 先插入 wait_for_loading_complete，再等待1s"""
    print("\n" + "=" * 80)
    print("场景2：点击按钮 → 等待1s")
    print("=" * 80)

    raw_steps = [
        '点击"下一步：确认配置"按钮',
        '等待1s'
    ]

    # 模拟 _next_needs_no_wait 逻辑（需要 mock _find_workflow）
    idx = 0
    next_step = raw_steps[idx + 1]
    next_parsed = parse_step(next_step)
    next_type = next_parsed.get('type')

    print(f"下一步解析结果: {next_parsed}")

    if next_type != 'l3_call':
        no_wait = next_type in {'wait_element', 'assert', 'assert_row', 'assert_count', 'check_assert'}
    else:
        cn_name = next_parsed.get('args', (None,))[0]
        wf_def = mock_find_workflow(cn_name) if cn_name else None
        blocking_keywords = {'wait_for_loading_complete', 'check_page_loaded'}
        no_wait = wf_def and wf_def.get('name') in blocking_keywords if wf_def else False

    # 当前步骤是 click_btn
    current_parsed = parse_step(raw_steps[0])
    is_button = current_parsed.get('type') == 'click_btn'

    # 判断是否插入
    should_insert = is_button and not no_wait

    print(f"当前步骤: {raw_steps[0]}")
    print(f"下一步: {raw_steps[1]}")
    print(f"下一步 type: {next_type}, cn_name: {next_parsed.get('args', (None,))[0]}")
    print(f"no_wait: {no_wait}")
    print(f"should_insert wait_for_loading_complete: {should_insert}")

    assert no_wait == False, "等待1s（wait_for_time）不应阻止插入"
    assert should_insert == True, "应插入 wait_for_loading_complete"
    print("✅ 验证通过")


def test_scenario_3():
    """场景3：点击按钮 → 等待加载完成 → 不重复插入"""
    print("\n" + "=" * 80)
    print("场景3：点击按钮 → 等待加载完成")
    print("=" * 80)

    raw_steps = [
        '点击"下一步：确认配置"按钮',
        '等待加载完成'
    ]

    # 模拟 _next_needs_no_wait 逻辑（需要 mock _find_workflow）
    idx = 0
    next_step = raw_steps[idx + 1]
    next_parsed = parse_step(next_step)
    next_type = next_parsed.get('type')

    print(f"下一步解析结果: {next_parsed}")

    if next_type != 'l3_call':
        no_wait = next_type in {'wait_element', 'assert', 'assert_row', 'assert_count', 'check_assert'}
    else:
        cn_name = next_parsed.get('args', (None,))[0]
        wf_def = mock_find_workflow(cn_name) if cn_name else None
        blocking_keywords = {'wait_for_loading_complete', 'check_page_loaded'}
        no_wait = wf_def and wf_def.get('name') in blocking_keywords if wf_def else False

    # 当前步骤是 click_btn
    current_parsed = parse_step(raw_steps[0])
    is_button = current_parsed.get('type') == 'click_btn'

    # 判断是否插入
    should_insert = is_button and not no_wait

    print(f"当前步骤: {raw_steps[0]}")
    print(f"下一步: {raw_steps[1]}")
    print(f"下一步 type: {next_type}, cn_name: {next_parsed.get('args', (None,))[0]}")
    print(f"no_wait: {no_wait}")
    print(f"should_insert wait_for_loading_complete: {should_insert}")

    assert no_wait == True, "等待加载完成（wait_for_loading_complete）应阻止重复插入"
    assert should_insert == False, "不应重复插入 wait_for_loading_complete"
    print("✅ 验证通过")


def test_scenario_4():
    """场景4：点击按钮 → 断言 → 不插入（断言前无需等待）"""
    print("\n" + "=" * 80)
    print("场景4：点击按钮 → 断言")
    print("=" * 80)

    raw_steps = [
        '点击"确定"按钮',
        '断言：页面提示"新增成功"'
    ]

    # 模拟 _next_needs_no_wait 逻辑（需要 mock _find_workflow）
    idx = 0
    next_step = raw_steps[idx + 1]
    next_parsed = parse_step(next_step)
    next_type = next_parsed.get('type')

    print(f"下一步解析结果: {next_parsed}")

    if next_type != 'l3_call':
        no_wait = next_type in {'wait_element', 'assert', 'assert_row', 'assert_count', 'check_assert'}
    else:
        cn_name = next_parsed.get('args', (None,))[0]
        wf_def = mock_find_workflow(cn_name) if cn_name else None
        blocking_keywords = {'wait_for_loading_complete', 'check_page_loaded'}
        no_wait = wf_def and wf_def.get('name') in blocking_keywords if wf_def else False

    # 当前步骤是 click_btn
    current_parsed = parse_step(raw_steps[0])
    is_button = current_parsed.get('type') == 'click_btn'

    # 判断是否插入
    should_insert = is_button and not no_wait

    print(f"当前步骤: {raw_steps[0]}")
    print(f"下一步: {raw_steps[1]}")
    print(f"下一步 type: {next_type}")
    print(f"no_wait: {no_wait}")
    print(f"should_insert wait_for_loading_complete: {should_insert}")

    assert no_wait == True, "断言（assert）应阻止插入"
    assert should_insert == False, "断言前不应插入 wait_for_loading_complete"
    print("✅ 验证通过")


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("测试 wait_for_loading_complete 自动插入逻辑")
    print("=" * 80)

    try:
        test_scenario_1()
        test_scenario_2()
        test_scenario_3()
        test_scenario_4()

        print("\n" + "=" * 80)
        print("✅ 所有场景验证通过")
        print("=" * 80)
        sys.exit(0)

    except AssertionError as e:
        print(f"\n❌ 验证失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
