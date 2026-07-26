#!/usr/bin/env python3
"""端到端验证所有管线修复"""
import sys
import os
import ast

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

print('=== 端到端修复验证 ===\n')

errors = []
warnings = []

# 1. 语法检查
print('1. 语法检查')
syntax_files = [
    'pipeline_registry.py',
    'pipeline.py',
    'verify_locators.py',
    'generate_suites.py',
    '../validators/validate_09_execution.py',
    '../validators/validate_00_config.py',
    'compile_module_keywords.py',
]

for f in syntax_files:
    if os.path.isfile(f):
        try:
            with open(f, encoding='utf-8') as fh:
                ast.parse(fh.read())
            print(f'  OK {f}')
        except SyntaxError as e:
            errors.append(f'Syntax {f}: {e}')
            print(f'  FAIL {f}: {e}')
    else:
        print(f'  SKIP {f} not found')

# 2. Path import
print('\n2. pipeline.py Path import')
with open('pipeline.py', encoding='utf-8') as f:
    pl_content = f.read()
if 'from pathlib import Path' in pl_content or 'import pathlib' in pl_content:
    print('  OK')
else:
    errors.append('pipeline.py missing Path import')
    print('  FAIL')

# 3. phase_1b_parse
print('\n3. phase_1b_parse')
from pipeline_registry import PHASE_DEFINITIONS, EXECUTION_ORDER
phase_1b = PHASE_DEFINITIONS.get('phase_1b_parse')
if phase_1b:
    print('  OK defined')
    if phase_1b.get('tool') == 'read_excel.py':
        print('  OK tool')
    else:
        errors.append(f"phase_1b_parse tool={phase_1b.get('tool')}")
    if phase_1b.get('optional') and phase_1b.get('condition'):
        print('  OK optional+condition')
    else:
        errors.append('phase_1b_parse missing optional/condition')
    artifacts = phase_1b.get('artifacts', [])
    if any('excel_parsed.json' in a for a in artifacts):
        print('  OK artifacts')
    else:
        errors.append('phase_1b_parse bad artifacts')
    if 'phase_1b_parse' in EXECUTION_ORDER:
        idx1 = EXECUTION_ORDER.index('phase_1')
        idx1b = EXECUTION_ORDER.index('phase_1b_parse')
        if idx1 < idx1b:
            print(f'  OK order ({idx1} -> {idx1b})')
        else:
            errors.append('phase_1b_parse order wrong')
    else:
        errors.append('phase_1b_parse not in EXECUTION_ORDER')
else:
    errors.append('phase_1b_parse undefined')

# 4. Phase 1 artifacts
print('\n4. Phase 1 artifacts')
phase_1 = PHASE_DEFINITIONS.get('phase_1')
if phase_1 and phase_1.get('artifacts') == []:
    print('  OK artifacts=[]')
else:
    errors.append(f"phase_1 artifacts={phase_1.get('artifacts')}")

# 5. Phase 5 deps
print('\n5. Phase 5 deps')
phase_5 = PHASE_DEFINITIONS.get('phase_5')
if phase_5:
    hd = phase_5.get('hard_deps', [])
    if 'phase_1b_parse' in hd:
        print('  OK has phase_1b_parse')
    else:
        errors.append('phase_5 missing phase_1b_parse dep')
    if 'phase_4_discovery' in hd:
        print('  OK has phase_4_discovery')
    else:
        errors.append('phase_5 missing phase_4_discovery dep')

# 6. Context refresh
print('\n6. Context refresh code')
if 'phase_1b_parse' in pl_content and 'update_from_config' in pl_content:
    print('  OK')
else:
    errors.append('pipeline.py missing phase_1b_parse refresh')

# 7. module_urls_path
print('\n7. module_urls_path code')
if 'module_urls_path' in pl_content and 'phase_4_discovery' in pl_content:
    print('  OK')
else:
    errors.append('pipeline.py missing module_urls_path')

# 8. verify_locators exit
print('\n8. verify_locators exit code')
with open('verify_locators.py', encoding='utf-8') as f:
    vl_content = f.read()
if 'truly_unresolved' in vl_content and 'kb_fallback_stored' in vl_content:
    print('  OK')
else:
    errors.append('verify_locators missing new exit logic')

# 9. Suite keyword
print('\n9. Suite keyword')
with open('generate_suites.py', encoding='utf-8') as f:
    gs_content = f.read()
if 'wait_for_loading_complete' in gs_content:
    print('  OK')
else:
    errors.append('generate_suites missing wait_for_loading_complete')

# 10. validate_09 structured
print('\n10. validate_09 structured output')
with open('../validators/validate_09_execution.py', encoding='utf-8') as f:
    v09_content = f.read()
if 'execution_errors' in v09_content and 'assertion_errors' in v09_content:
    print('  OK')
else:
    errors.append('validate_09 missing structured output')

# 11. localStorage parameterized
print('\n11. localStorage parameterized')
with open('../validators/validate_00_config.py', encoding='utf-8') as f:
    v00_content = f.read()
if '[k, v]' in v00_content:
    print('  OK')
else:
    warnings.append('localStorage may not be parameterized')

# 12. element-ui detection
print('\n12. element-ui detection')
if 'data-v-' in v00_content:
    plus_pos = v00_content.find('element-plus')
    ui_pos = v00_content.find('element-ui')
    if plus_pos > 0 and ui_pos > 0 and plus_pos < ui_pos:
        print('  OK (plus before ui)')
    else:
        warnings.append('element-ui detection order may be suboptimal')
        print(f'  WARN order')
else:
    warnings.append('element-ui detection may not be fixed')

# 13. cookie_domain
print('\n13. cookie_domain')
if 'cookie_domain' in v00_content and "config.get('cookie_domain')" in v00_content:
    print('  OK')
else:
    warnings.append('cookie_domain may not use config.get')
    print('  WARN')

# 14. compile_module_keywords path
print('\n14. compile_module_keywords path')
with open('compile_module_keywords.py', encoding='utf-8') as f:
    cmk_content = f.read()
if 'os.path.join(skill_dir' in cmk_content:
    print('  OK')
else:
    warnings.append('compile_module_keywords may have hardcoded path')

# 15. config.yaml.tpl comment
print('\n15. config.yaml.tpl comment')
tpl_path = '../templates/config.yaml.tpl'
if os.path.isfile(tpl_path):
    with open(tpl_path, encoding='utf-8') as f:
        tpl_content = f.read()
    if '管线不会程序化处理' in tpl_content or 'Mustache' in tpl_content:
        print('  OK')
    else:
        warnings.append('config.yaml.tpl may lack comment')
else:
    warnings.append('config.yaml.tpl not found')

# Summary
print('\n' + '=' * 60)
print(f'Errors: {len(errors)}')
print(f'Warnings: {len(warnings)}')
print(f'Passed: {15 - len(errors) - len(warnings)} / 15')

if errors:
    print('\nErrors:')
    for e in errors:
        print(f'  - {e}')

if warnings:
    print('\nWarnings:')
    for w in warnings:
        print(f'  - {w}')

if not errors:
    print('\nAll critical checks passed!')

sys.exit(1 if errors else 0)
