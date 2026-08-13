"""Transform discover_page.py: replace hardcoded Element UI selectors in _DISCOVER_JS with fwSelectors."""
import re

fp = '../discover_page.py'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# === ORDER MATTERS: longer/more specific patterns FIRST ===

# Group A: Compound selectors (longer patterns, must come before standalone)
A_replacements = [
    # (old_pattern, new_pattern, description)
    (r"'input,select,textarea,\.el-select,\.el-cascader,\.el-date-editor'",
     r"'input,select,textarea,' + fwSelectors.selectExclude",
     'form field counter sort (x2)'),
    (r"'\.el-select \.el-input__inner'",
     r"fwSelectors.selectInput",
     'el-select input (x3)'),
    (r"'\.el-form-item__content'",
     r"fwSelectors.formItemContent",
     'form item content'),
    (r"'\.el-form-item__label'",
     r"fwSelectors.formItemLabel",
     'form item label (x3)'),
    (r"'\.el-form-item'",
     r"fwSelectors.formItem",
     'form item (x4)'),
    (r"'textarea\.el-textarea__inner'",
     r"fwSelectors.textareaInner",
     'textarea inner'),
    (r"'\.el-textarea'",
     r"fwSelectors.textarea",
     'textarea wrapper'),
    (r"'input\.el-input__inner'",
     r"fwSelectors.inputInner",
     'input inner (x2)'),
    (r"'\.el-input__inner'",
     r"fwSelectors.inputInner",
     'input inner bare'),
    (r"'\.el-date-editor input'",
     r"fwSelectors.dateEditor",
     'date editor'),
    (r"'\.el-cascader \.el-input__inner'",
     r"fwSelectors.cascaderInput",
     'cascader input'),
]

for old, new, desc in A_replacements:
    count = len(re.findall(old, content))
    if count > 0:
        content = re.sub(old, new, content)
        changes += count
        print(f'  [{count}x] {desc}')

# Group B: Multi-selector querySelectorAll (use regex with flexible whitespace)
B_patterns = [
    # selectExclude in closest()
    (r"el\.closest\('\.el-select'\)\s*\|\|\s*el\.closest\('\.el-date-editor'\)\s*\|\|\s*el\.closest\('\.el-cascader'\)",
     r"el.closest(fwSelectors.selectExclude)",
     'select exclude closest (x2)'),
    # Row button querySelectorAll (line 601)
    (r"'tbody \.el-button, tbody \.ec-button, tbody button, tbody \.el-dropdown span\.el-dropdown-link, tbody \.ec-dropdown span\.el-dropdown-link, tbody span\.el-dropdown-link, tbody \.el-dropdown span\[style\*=\"cursor\"\], tbody \.ec-dropdown span\[style\*=\"cursor\"\]'",
     r"fwSelectors.rowButton + ', tbody button'",
     'row button querySelectorAll'),
]

for old, new, desc in B_patterns:
    count = len(re.findall(old, content))
    if count > 0:
        content = re.sub(old, new, content)
        changes += count
        print(f'  [{count}x] {desc}')

# Group C: Toolbar button selector (line 398)
old_btn = "'button.el-button, button.ec-button, button, [role=\"button\"], .ec-button, div.search-wrap'"
new_btn = "fwSelectors.button + ', button, [role=\"button\"], div.search-wrap'"
count = content.count(old_btn)
if count > 0:
    content = content.replace(old_btn, new_btn)
    changes += count
    print(f'  [{count}x] toolbar button selector')

# Group D: Standalone short selectors (after compound patterns are replaced)
D_replacements = [
    (r"'\.el-input'", r"fwSelectors.inputWrapper", 'input wrapper'),
    (r"'\.el-select'", r"fwSelectors.selectExclude", 'select exclude standalone (x3)'),
    (r"'\.el-date-editor'", r"fwSelectors.selectExclude", 'date editor standalone'),
    (r"'\.el-cascader'", r"fwSelectors.selectExclude", 'cascader standalone'),
    (r"'\.el-icon-search'", r"fwSelectors.iconSearch", 'icon search'),
    (r"'\.el-icon-download'", r"fwSelectors.iconDownload", 'icon download'),
    (r"'\.el-menu-item'", r"fwSelectors.menuItem", 'menu item (x2)'),
]

for old, new, desc in D_replacements:
    count = len(re.findall(old, content))
    if count > 0:
        content = re.sub(old, new, content)
        changes += count
        print(f'  [{count}x] {desc}')

# Group E: Noise filter functions (add antd alternatives, keep existing)
# isBreadcrumb: .el-breadcrumb → fwSelectors.breadcrumb + keep fallbacks
old_bc = "'.el-breadcrumb, .breadcrumb, [class*=\"breadcrumb\"]'"
new_bc = "fwSelectors.breadcrumb + ', .breadcrumb, [class*=\"breadcrumb\"]'"
count = content.count(old_bc)
if count > 0:
    content = content.replace(old_bc, new_bc)
    changes += count
    print(f'  [{count}x] isBreadcrumb')

# isUserDropdown: .el-dropdown → fwSelectors.dropdown + keep fallbacks
old_ud = "'.el-dropdown, .user-info, .header-right, [class*=\"user\"]'"
new_ud = "fwSelectors.dropdown + ', .user-info, .header-right, [class*=\"user\"]'"
count = content.count(old_ud)
if count > 0:
    content = content.replace(old_ud, new_ud)
    changes += count
    print(f'  [{count}x] isUserDropdown')

# Group F: iframe button selector
old_ib = "'button, [role=\"button\"], .el-button, .ec-button'"
new_ib = "'button, [role=\"button\"], ' + fwSelectors.iframeButton"
count = content.count(old_ib)
if count > 0:
    content = content.replace(old_ib, new_ib)
    changes += count
    print(f'  [{count}x] iframe button')

# Group G: iframe input exclude
old_ie = "el.closest('.el-select') || el.closest('.el-date-editor')"
new_ie = "el.closest(fwSelectors.iframeInputExclude)"
count = content.count(old_ie)
if count > 0:
    content = content.replace(old_ie, new_ie)
    changes += count
    print(f'  [{count}x] iframe input exclude')

# Group H: iframe select input
old_is = "'.el-select .el-input__inner'"
new_is = "fwSelectors.iframeSelectInput"
count = content.count(old_is)
if count > 0:
    content = content.replace(old_is, new_is)
    changes += count
    print(f'  [{count}x] iframe select input')

print(f'\nTotal replacements: {changes}')

with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
print('discover_page.py updated')
