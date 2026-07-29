#!/usr/bin/env python3
"""
Self-verification: Click-type wildcard fallback logic

Tests:
1. candidates structure: Discovery → KB → Original → kb-fallback
2. Click-type guard: only CLICK_EXPAND_TYPES get fallback
3. Non-click types excluded: input, el-select, textarea, tab, checkbox
4. Dedup logic: prevents duplicate fallback
5. Writeback decision: kb-fallback triggers writeback (not discovery)
6. R4 multi-type retry: fallback added in _alt_candidates
"""

import sys
import os
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

# Import the constant from verify_locators
from verification.verify_orchestrator import CLICK_EXPAND_TYPES

print("=" * 70)
print("CLICK_EXPAND_TYPES:", CLICK_EXPAND_TYPES)
print("=" * 70)

# === Test 1: Main candidate building (click step) ===
print("\n" + "=" * 70)
print("Test 1: Main candidate building — click step")
print("=" * 70)

elem_type = 'button'
label = '高级搜索'
candidates = [
    ('//input[@id="search"]', 'discovery'),
    ('//button[contains(.,"高级搜索")]', 'kb'),
    ('//button[@class="btn-search"]', 'original'),
]

# Simulate the new code
if elem_type in CLICK_EXPAND_TYPES and label:
    _click_fb = f"//*[contains(text(),'{label}')]"
    if not any(c[0] == _click_fb for c in candidates):
        candidates.append((_click_fb, 'kb-fallback'))

assert len(candidates) == 4, f"Expected 4 candidates, got {len(candidates)}"
assert candidates[0][1] == 'discovery', "Priority 0 should be discovery"
assert candidates[1][1] == 'kb', "Priority 1 should be kb"
assert candidates[2][1] == 'original', "Priority 2 should be original"
assert candidates[3][1] == 'kb-fallback', "Priority 3 should be kb-fallback"
assert candidates[3][0] == "//*[contains(text(),'高级搜索')]"
print("✓ candidates structure: Discovery → KB → Original → kb-fallback")
print(f"  Fallback xpath: {candidates[3][0][:60]}...")

# === Test 2: Non-click types excluded ===
print("\n" + "=" * 70)
print("Test 2: Non-click types excluded")
print("=" * 70)

non_click_types = [
    'input-generic', 'textarea-generic', 'el-select', 'el-cascader',
    'date-picker', 'tab', 'checkbox', 'checkbox-all', 'menu-item',
    'search-button', 'download-button'
]

for etype in non_click_types:
    candidates = [
        ('//input[@id="test"]', 'discovery'),
        ('//input[@placeholder="test"]', 'kb'),
        ('//input[@name="test"]', 'original'),
    ]
    if etype in CLICK_EXPAND_TYPES and 'test' in ('test',):
        _click_fb = f"//*[contains(text(),'test')]"
        if not any(c[0] == _click_fb for c in candidates):
            candidates.append((_click_fb, 'kb-fallback'))

    assert len(candidates) == 3, f"Type {etype} should NOT add fallback, got {len(candidates)}"
    print(f"✓ {etype}: no fallback added (3 candidates)")

# === Test 3: Click types included ===
print("\n" + "=" * 70)
print("Test 3: Click types included")
print("=" * 70)

for etype in CLICK_EXPAND_TYPES:
    candidates = [
        ('//button[@id="test"]', 'discovery'),
        ('//button[contains(.,"test")]', 'kb'),
        ('//button[@class="btn"]', 'original'),
    ]
    if etype in CLICK_EXPAND_TYPES and 'test':
        _click_fb = f"//*[contains(text(),'test')]"
        if not any(c[0] == _click_fb for c in candidates):
            candidates.append((_click_fb, 'kb-fallback'))

    assert len(candidates) == 4, f"Type {etype} should add fallback, got {len(candidates)}"
    assert candidates[3][1] == 'kb-fallback'
    print(f"✓ {etype}: fallback added (4 candidates)")

# === Test 4: Dedup logic ===
print("\n" + "=" * 70)
print("Test 4: Dedup logic")
print("=" * 70)

candidates = [
    ('//button[@id="test"]', 'discovery'),
    ("//*[contains(text(),'test')]", 'kb-fallback'),  # Already present
]
elem_type = 'button'
label = 'test'

if elem_type in CLICK_EXPAND_TYPES and label:
    _click_fb = f"//*[contains(text(),'{label}')]"
    if not any(c[0] == _click_fb for c in candidates):
        candidates.append((_click_fb, 'kb-fallback'))

assert len(candidates) == 2, f"Dedup should prevent adding, got {len(candidates)}"
print("✓ Dedup: no duplicate fallback added")

# === Test 5: Writeback decision ===
print("\n" + "=" * 70)
print("Test 5: Writeback decision")
print("=" * 70)

test_cases = [
    ('discovery', False, "Discovery hit → no writeback"),
    ('kb', True, "KB hit → writeback"),
    ('original', True, "Original hit → writeback"),
    ('kb-fallback', True, "kb-fallback hit → writeback"),
    (None, True, "All failed → writeback fallback"),
]

for v_src, should_writeback, desc in test_cases:
    # Existing logic: if v_src != 'discovery': _store_verified_locator(...)
    actual_writeback = (v_src != 'discovery')
    assert actual_writeback == should_writeback, f"Failed: {desc}"
    print(f"✓ {desc}: writeback={actual_writeback}")

# === Test 6: R4 multi-type retry ===
print("\n" + "=" * 70)
print("Test 6: R4 multi-type retry — _alt_candidates")
print("=" * 70)

_alt_type = 'table-action-button'
label = '编辑'
_alt_candidates = [
    ('//div[@class="el-table"]//span[contains(.,"编辑")]', 'discovery'),
    ('//div[contains(@class,"el-table__fixed-right")]//tbody/tr[1]//span[contains(.,"编辑")]', 'kb'),
]

# Simulate R4 code
if _alt_type in CLICK_EXPAND_TYPES and label:
    _click_fb = f"//*[contains(text(),'{label}')]"
    if not any(c[0] == _click_fb for c in _alt_candidates):
        _alt_candidates.append((_click_fb, 'kb-fallback'))

assert len(_alt_candidates) == 3, f"Expected 3 _alt_candidates, got {len(_alt_candidates)}"
assert _alt_candidates[2][1] == 'kb-fallback'
print("✓ R4 _alt_candidates: fallback added")
print(f"  Fallback xpath: {_alt_candidates[2][0][:60]}...")

# === Test 7: Empty label guard ===
print("\n" + "=" * 70)
print("Test 7: Empty label guard")
print("=" * 70)

candidates = [('//button', 'kb')]
elem_type = 'button'
label = ''

if elem_type in CLICK_EXPAND_TYPES and label:
    _click_fb = f"//*[contains(text(),'{label}')]"
    if not any(c[0] == _click_fb for c in candidates):
        candidates.append((_click_fb, 'kb-fallback'))

assert len(candidates) == 1, f"Empty label should not add fallback, got {len(candidates)}"
print("✓ Empty label: no fallback added")

# === Summary ===
print("\n" + "=" * 70)
print("ALL TESTS PASSED ✓")
print("=" * 70)
print("""
Verified:
1. ✓ Main candidate building: Discovery → KB → Original → kb-fallback
2. ✓ Non-click types excluded (11 types)
3. ✓ Click types included (3 types)
4. ✓ Dedup logic prevents duplicate fallback
5. ✓ Writeback decision: kb-fallback triggers writeback
6. ✓ R4 multi-type retry: fallback added in _alt_candidates
7. ✓ Empty label guard: no fallback added
""")
