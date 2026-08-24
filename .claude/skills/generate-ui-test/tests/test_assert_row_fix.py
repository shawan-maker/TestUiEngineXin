#!/usr/bin/env python3
"""测试 commit 4973040（断言增加"或"选项）的回归修复

验证场景：
  1. 单值+可见  — 尾部断言关键字不应被纳入值
  2. 或关系     — 多值"或"拆分应正确
  3. 普通单值   — 无尾部关键字的常规断言
  4. 单值+显示  — 其他断言关键字变体
  5. 或+可见    — 或关系 + 尾部关键字组合
  6. 单值无尾部 — 最简形式
  7. 检查+显示  — "检查"前缀变体
"""
import re
import sys
import os

# 确保能导入项目模块
skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(skill_dir, 'tools', 'core'))

from step_patterns import parse_step, Q

# ============================================================================
# 测试数据
# ============================================================================
# (名称, 输入步骤文本, 期望type, 期望捕获值, 期望清理后的OR值列表)
TESTS = [
    # ── 场景 1: 单值 + 尾部断言关键字 ──
    (
        '单值+可见',
        '断言：第一条记录的问题状态为“PENDING”可见',
        'assert_row',
        'PENDING',
        ['PENDING'],
    ),
    # ── 场景 2: 或关系（多值） ──
    (
        '或关系',
        '断言第一条记录的协议类型包含“IPv6+IPv4”或“IPv4+IPv6”',
        'assert_row',
        'IPv6+IPv4”或“IPv4+IPv6',
        ['IPv6+IPv4', 'IPv4+IPv6'],
    ),
    # ── 场景 3: 普通单值（无尾部关键字） ──
    (
        '普通单值',
        '断言第一条记录包含“已完成”',
        'assert_row',
        '已完成',
        ['已完成'],
    ),
    # ── 场景 4: 单值 + "显示" ──
    (
        '单值+显示',
        '检查第一条记录的状态为“OPEN”显示',
        'assert_row',
        'OPEN',
        ['OPEN'],
    ),
    # ── 场景 5: 或关系 + 尾部"可见" ──
    (
        '或+可见',
        '断言：第一条记录的状态为“待审核”或“已审核”可见',
        'assert_row',
        '待审核”或“已审核',
        ['待审核', '已审核'],
    ),
    # ── 场景 6: 最简形式（无"为"、无尾部关键字） ──
    (
        '单值无尾部',
        '断言：第一条记录的问题状态为“PENDING”',
        'assert_row',
        'PENDING',
        ['PENDING'],
    ),
    # ── 场景 7: "确认"前缀 + "可见" ──
    (
        '确认+可见',
        '确认第一条记录的名称为“测试项目”可见',
        'assert_row',
        '测试项目',
        ['测试项目'],
    ),
]

# case_generator 中用于拆分"或"的逻辑（与修改后的代码一致）
def clean_or_values(value):
    """模拟 case_generator.py assert_row 中的值清理逻辑"""
    _or_parts = re.split(rf'{Q}(?:或|或者){Q}', value)
    return [v.strip() for v in _or_parts if v.strip()]

# ============================================================================
# 执行测试
# ============================================================================
def run():
    fail = 0
    for name, desc, exp_type, exp_raw, exp_or_list in TESTS:
        result = parse_step(desc)

        # 1) parse_step 是否匹配
        if result is None:
            print('FAIL [%s]: parse_step returned None' % name)
            fail += 1
            continue

        ptype = result.get('type', '')
        raw_value = result.get('args', ())[0] if result.get('args') else ''

        # 2) 正则捕获值是否正确
        type_ok = (ptype == exp_type)
        raw_ok = (raw_value == exp_raw)

        # 3) case_generator 清理后的 OR 值是否正确
        or_values = clean_or_values(raw_value)
        or_ok = (or_values == exp_or_list)

        all_ok = type_ok and raw_ok and or_ok
        mark = 'PASS' if all_ok else 'FAIL'
        if not all_ok:
            fail += 1

        print('%s [%s]' % (mark, name))
        print('  input : %s' % desc)
        print('  type  : %s  (expect: %s) %s' % (ptype, exp_type, 'v' if type_ok else 'X'))
        print('  raw   : "%s"  (expect: "%s") %s' % (raw_value, exp_raw, 'v' if raw_ok else 'X'))
        print('  or_val: %s  (expect: %s) %s' % (or_values, exp_or_list, 'v' if or_ok else 'X'))
        print()

    total = len(TESTS)
    passed = total - fail
    print('=' * 50)
    print('Result: %d/%d passed' % (passed, total))
    if fail:
        print('FAILED: %d test(s)' % fail)
        sys.exit(1)
    else:
        print('ALL PASSED')

if __name__ == '__main__':
    run()
