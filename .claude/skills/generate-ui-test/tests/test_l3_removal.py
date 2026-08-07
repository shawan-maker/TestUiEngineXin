"""验证 _lookup_discovery_element L3 全局回退已删除。

测试场景：
1. L1 多URL精确匹配仍有效
2. L2 向后兼容匹配仍有效
3. L3 全局回退已删除（跨页面不再误匹配）
4. 子串搜索的页面隔离仍有效
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from generation.case_generator import CaseGenerator


def _make_generator():
    """构造最小化 CaseGenerator，仅填充 discovery maps。"""
    gen = CaseGenerator.__new__(CaseGenerator)
    gen._discovery_element_map = {}
    gen._discovery_page_element_map = {}
    gen._discovery_trigger_map = {}
    gen._current_context = 'list_page'
    gen._current_page_url = None
    gen._page_slug_map = {}
    return gen


def _set_page_slug(gen, slug):
    gen._current_page_url = f"http://example.com/{slug}" if slug else None
    gen._page_slug_map = {gen._current_page_url: slug} if slug else {}


def _get_current_page_slug_patch(gen):
    url = gen._current_page_url
    return gen._page_slug_map.get(url)


# monkey-patch
CaseGenerator._get_current_page_slug = lambda self: _get_current_page_slug_patch(self)


passed = 0
failed = 0


def check(name, condition, detail=''):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


# ─── Test 1: L1 多URL精确匹配 ───
print("\n[Test 1] L1: 多URL精确匹配")
gen = _make_generator()
_set_page_slug(gen, 'vm')
elem_vm = {'locator': 'xpath=//vm-input', 'group_name': 'vm_grp', 'field_key': 'field_a'}
gen._discovery_page_element_map[('vm', 'list_page', '确认密码')] = elem_vm

result = gen._lookup_discovery_element('确认密码')
check("vm 页面精确匹配", result is elem_vm, f"got {result}")

# ─── Test 2: L1 容器回退 ───
print("\n[Test 2] L1: 页面级容器回退")
gen = _make_generator()
_set_page_slug(gen, 'vm')
gen._current_context = 'el-dialog'
elem_dialog = {'locator': 'xpath=//dialog-input', 'group_name': 'dialog_grp', 'field_key': 'field_b'}
gen._discovery_page_element_map[('vm', 'list_page', '确认密码')] = elem_dialog

result = gen._lookup_discovery_element('确认密码')
check("容器 ctx 回退到 list_page", result is elem_dialog, f"got {result}")

# ─── Test 3: L2 向后兼容（无 page_slug） ───
print("\n[Test 3] L2: 向后兼容（无 page_slug）")
gen = _make_generator()
_set_page_slug(gen, None)  # 单URL模块
elem_flat = {'locator': 'xpath=//flat-input', 'group_name': 'flat_grp', 'field_key': 'field_c'}
gen._discovery_element_map[('list_page', '用户名')] = elem_flat

result = gen._lookup_discovery_element('用户名')
check("扁平 map 匹配", result is elem_flat, f"got {result}")

# ─── Test 4: L2 容器回退（无 page_slug） ───
print("\n[Test 4] L2: 向后兼容容器回退")
gen = _make_generator()
_set_page_slug(gen, None)
gen._current_context = 'el-dialog'
elem_lp = {'locator': 'xpath=//lp-input', 'group_name': 'lp_grp', 'field_key': 'field_d'}
gen._discovery_element_map[('list_page', '确认密码')] = elem_lp

result = gen._lookup_discovery_element('确认密码')
check("无 page_slug 时容器回退到 list_page", result is elem_lp, f"got {result}")

# ─── Test 5: L3 全局回退已删除（核心测试） ───
print("\n[Test 5] L3 全局回退已删除")
gen = _make_generator()
_set_page_slug(gen, 'vm')
# vm 页面没有"确认密码"，但 list 页面的 _discovery_element_map 有
elem_list = {'locator': 'xpath=//list-dialog-input', 'group_name': 'list_grp', 'field_key': 'field_e'}
gen._discovery_element_map[('el-dialog', '确认密码')] = elem_list  # 来自 list 页面的 dialog

result = gen._lookup_discovery_element('确认密码')
check("跨页面不误匹配 → 返回 None", result is None,
      f"expected None but got {result}")

# ─── Test 6: L3 全局回退已删除（即使 context 不同） ───
print("\n[Test 6] L3: 不同 context 也不全局回退")
gen = _make_generator()
_set_page_slug(gen, 'vm')
gen._current_context = 'list_page'
elem_other = {'locator': 'xpath=//other', 'group_name': 'other_grp', 'field_key': 'field_f'}
gen._discovery_element_map[('some_other_context', '确认密码')] = elem_other

result = gen._lookup_discovery_element('确认密码')
check("不同 context 不误匹配 → 返回 None", result is None,
      f"expected None but got {result}")

# ─── Test 7: 容器 context 的保护仍有效 ───
print("\n[Test 7] 容器 context 跳过 list_page 回退")
gen = _make_generator()
_set_page_slug(gen, None)
gen._current_context = 'el-dialog'
gen._discovery_trigger_map = {'el-dialog': True}
elem_lp2 = {'locator': 'xpath=//lp2', 'group_name': 'lp2_grp', 'field_key': 'field_g'}
gen._discovery_element_map[('list_page', '测试字段')] = elem_lp2

result = gen._lookup_discovery_element('测试字段')
check("容器 context 跳过 list_page 回退 → None", result is None,
      f"expected None but got {result}")

# ─── Test 8: _discovery_lookup 子串搜索页面隔离 ───
print("\n[Test 8] _discovery_lookup 子串搜索页面隔离")
gen = _make_generator()
_set_page_slug(gen, 'vm')
gen._current_context = 'list_page'
# list 页面有"确认密码"，vm 页面没有
elem_list2 = {'locator': 'xpath=//list2', 'group_name': 'list2_grp', 'field_key': 'field_h', 'type': 'input'}
gen._discovery_page_element_map[('list', 'list_page', '确认密码')] = elem_list2

result = gen._discovery_lookup('确认密码')
check("子串搜索不跨页面 → None", result is None,
      f"expected None but got {result}")

# ─── Test 9: _discovery_lookup 子串搜索同页面命中 ───
print("\n[Test 9] _discovery_lookup 子串搜索同页面命中")
gen = _make_generator()
_set_page_slug(gen, 'vm')
gen._current_context = 'list_page'
elem_vm2 = {'locator': 'xpath=//vm2', 'group_name': 'vm2_grp', 'field_key': 'field_i', 'type': 'input'}
gen._discovery_page_element_map[('vm', 'list_page', '确认密码输入框')] = elem_vm2

result = gen._discovery_lookup('确认密码')
check("子串搜索同页面命中", result is elem_vm2,
      f"expected elem_vm2 but got {result}")

# ─── Test 10: 回归 — 单URL模块 L2 完整链路 ───
print("\n[Test 10] 回归：单URL模块完整链路")
gen = _make_generator()
_set_page_slug(gen, None)
gen._current_context = 'list_page'
elem_single = {'locator': 'xpath=//single', 'group_name': 'single_grp', 'field_key': 'field_j'}
gen._discovery_element_map[('list_page', '项目类型')] = elem_single

result = gen._lookup_discovery_element('项目类型')
check("单URL模块 L2 匹配正常", result is elem_single, f"got {result}")


# ─── 总结 ───
print(f"\n{'='*50}")
total = passed + failed
print(f"结果: {passed}/{total} PASS, {failed}/{total} FAIL")
if failed > 0:
    print("[FAIL] has failures")
    sys.exit(1)
else:
    print("[OK] all passed")
    sys.exit(0)
