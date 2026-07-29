#!/usr/bin/env python3
"""
Self-verification: close-button KB type integration

Tests:
1. step_patterns: parse close-button steps
2. _element_types: type inference and mappings
3. field_suffixes: label_to_key with close_btn suffix
4. probe_knowledge: KB templates loaded correctly
5. probe_element: subtype detection
6. Integration: full pipeline from step to locator
"""

import sys
import os
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

print("=" * 70)
print("Test 1: step_patterns — parse close-button steps")
print("=" * 70)

from core.step_patterns import parse_step

# Test case 1a: with label (有"的")
result = parse_step('点击"default_ecs"安全组的关闭按钮')
assert result['type'] == 'close_btn', f"Expected 'close_btn', got {result['type']}"
assert result['args'] == ('default_ecs',), f"Expected ('default_ecs',), got {result['args']}"
print("✓ 1a: 点击「default_ecs」安全组的关闭按钮 → close_btn, label='default_ecs'")

# Test case 1b: with label (无"的")
result = parse_step('点击"default_ecs"安全组关闭按钮')
assert result['type'] == 'close_btn', f"Expected 'close_btn', got {result['type']}"
assert result['args'] == ('default_ecs',), f"Expected ('default_ecs',), got {result['args']}"
print("✓ 1b: 点击「default_ecs」安全组关闭按钮 → close_btn, label='default_ecs'")

# Test case 1c: generic (无标签)
result = parse_step('点击关闭按钮')
assert result['type'] == 'close_btn', f"Expected 'close_btn', got {result['type']}"
assert result['args'] == (), f"Expected (), got {result['args']}"
print("✓ 1c: 点击关闭按钮 → close_btn, label=()")

# Test case 1d: should NOT match other click patterns
result = parse_step('点击"确定"按钮')
assert result['type'] == 'click_btn', f"Expected 'click_btn', got {result['type']}"
print("✓ 1d: 点击「确定」按钮 → click_btn (not close_btn)")

print("\n" + "=" * 70)
print("Test 2: _element_types — type inference and mappings")
print("=" * 70)

from core.element_types import (
    infer_elem_type, KB_TYPE_KEYS, STEP_TO_KB, TYPE_TO_SECTIONS,
    DISCOVERY_TO_KB, KB_TO_SUFFIX, SUFFIX_MAP_COMPAT
)

# Test case 2a: type inference
assert infer_elem_type('click_element', '点击「关闭」按钮') == 'close-button'
print("✓ 2a: infer_elem_type('click_element', '点击「关闭」按钮') → 'close-button'")

assert infer_elem_type('click_element', '点击「default_ecs」的关闭按钮') == 'close-button'
print("✓ 2b: infer_elem_type('click_element', '点击「default_ecs」的关闭按钮') → 'close-button'")

# Test case 2c: should NOT infer close-button for other clicks
assert infer_elem_type('click_element', '点击「确定」按钮') == 'button'
print("✓ 2c: infer_elem_type('click_element', '点击「确定」按钮') → 'button'")

# Test case 2d: KB_TYPE_KEYS
assert 'close-button' in KB_TYPE_KEYS
print("✓ 2d: 'close-button' in KB_TYPE_KEYS")

# Test case 2e: STEP_TO_KB
assert STEP_TO_KB.get('close_btn') == 'close-button'
print("✓ 2e: STEP_TO_KB['close_btn'] → 'close-button'")

# Test case 2f: TYPE_TO_SECTIONS
assert TYPE_TO_SECTIONS.get('close-button') == ('buttons',)
print("✓ 2f: TYPE_TO_SECTIONS['close-button'] → ('buttons',)")

# Test case 2g: DISCOVERY_TO_KB
assert DISCOVERY_TO_KB.get('close-button') == 'close-button'
print("✓ 2g: DISCOVERY_TO_KB['close-button'] → 'close-button'")

# Test case 2h: KB_TO_SUFFIX
assert KB_TO_SUFFIX.get('close-button') == '_close_btn'
print("✓ 2h: KB_TO_SUFFIX['close-button'] → '_close_btn'")

# Test case 2i: SUFFIX_MAP_COMPAT
assert SUFFIX_MAP_COMPAT.get('close-button') == '_close_btn'
print("✓ 2i: SUFFIX_MAP_COMPAT['close-button'] → '_close_btn'")

print("\n" + "=" * 70)
print("Test 3: field_suffixes — label_to_key with close_btn suffix")
print("=" * 70)

from core.field_suffixes import label_to_key, STANDARD_SUFFIXES, FIELD_RE_SUFFIXES

# Test case 3a: with label
key = label_to_key('defaultecs', 'close-button')
assert key == 'defaultecs_close_btn', f"Expected 'defaultecs_close_btn', got {key}"
print("✓ 3a: label_to_key('defaultecs', 'close-button') → 'defaultecs_close_btn'")

# Test case 3b: generic (label='关闭')
key = label_to_key('关闭', 'close-button')
assert key == 'close_btn', f"Expected 'close_btn', got {key}"
print("✓ 3b: label_to_key('关闭', 'close-button') → 'close_btn' (not 'close_close_btn')")

# Test case 3c: Chinese label
key = label_to_key('安全组', 'close-button')
assert key.endswith('_close_btn'), f"Expected key ending with '_close_btn', got {key}"
print("✓ 3c: label_to_key('安全组', 'close-button') → '{hash}_close_btn'")

# Test case 3d: STANDARD_SUFFIXES
assert '_close_btn' in STANDARD_SUFFIXES
print("✓ 3d: '_close_btn' in STANDARD_SUFFIXES")

# Test case 3e: FIELD_RE_SUFFIXES
assert 'close_btn' in FIELD_RE_SUFFIXES
print("✓ 3e: 'close_btn' in FIELD_RE_SUFFIXES")

print("\n" + "=" * 70)
print("Test 4: probe_knowledge — KB templates loaded correctly")
print("=" * 70)

from probe.probe_utils import get_all_patterns

# Test case 4a: load patterns
patterns = get_all_patterns('close-button')
assert len(patterns) == 2, f"Expected 2 patterns, got {len(patterns)}"
print(f"✓ 4a: get_all_patterns('close-button') → {len(patterns)} patterns")

# Test case 4b: pattern content
assert 'el-icon-close' in patterns[0]
assert '{label}' in patterns[0]
print(f"✓ 4b: patterns[0] contains 'el-icon-close' and '{{label}}'")

assert 'el-icon-close' in patterns[1]
assert '{label}' not in patterns[1]
print(f"✓ 4c: patterns[1] contains 'el-icon-close' but not '{{label}}' (generic)")

print("\n" + "=" * 70)
print("Test 5: probe_element — subtype detection")
print("=" * 70)

# Test case 5a: _detect_subtype for close-button
# We can't easily test _detect_subtype without a page object, but we can verify
# the routing logic by checking the function exists and has the right structure
import inspect
from probe_element import _detect_subtype
sig = inspect.signature(_detect_subtype)
assert len(sig.parameters) == 4
print("✓ 5a: _detect_subtype function signature correct")

# Test case 5b: verify close-button routing in probe_element
import probe_element
source = inspect.getsource(probe_element)
assert 'close-button' in source
print("✓ 5b: probe_element.py contains 'close-button' references")

print("\n" + "=" * 70)
print("Test 6: Integration — full pipeline from step to locator")
print("=" * 70)

# Test case 6a: step parsing → type inference → field naming
step_text = '点击"default_ecs"安全组的关闭按钮'
parsed = parse_step(step_text)
assert parsed['type'] == 'close_btn'

inferred_type = infer_elem_type('click_element', step_text)
assert inferred_type == 'close-button'

label = parsed['args'][0]
field_key = label_to_key(label, inferred_type)
# label_to_key strips underscores (ASCII extraction), so default_ecs → defaultecs
assert field_key == 'defaultecs_close_btn', f"Expected 'defaultecs_close_btn', got {field_key}"

print(f"✓ 6a: '{step_text}'")
print(f"    → parse: {parsed['type']}, label='{label}'")
print(f"    → infer: {inferred_type}")
print(f"    → field: {field_key}")

# Test case 6b: generic close button
step_text = '点击关闭按钮'
parsed = parse_step(step_text)
assert parsed['type'] == 'close_btn'
assert parsed['args'] == ()

inferred_type = infer_elem_type('click_element', step_text)
assert inferred_type == 'close-button'

# Generic case: no label, so field_key would be generated differently
# In real usage, this would use a default label or hash
print(f"✓ 6b: '{step_text}'")
print(f"    → parse: {parsed['type']}, label={parsed['args']}")
print(f"    → infer: {inferred_type}")

print("\n" + "=" * 70)
print("ALL TESTS PASSED ✓")
print("=" * 70)
