"""
pages_writeback.py - Pages YAML 回写

从 verify_locators.py 提取的 YAML 回写函数：
- _store_verified_locator: 存储验证通过的 locator
- update_pages_yaml: 将验证结果回写到 pages YAML 文件
"""

import os
import re
import sys

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ─── Shared imports ───
from core.yaml_utils import escape_yaml_scalar as _escape_yaml_scalar
from core.xpath_utils import apply_hidden_filters_to_pages, strip_not_ancestor_from_pages
from generation.pages_writer import _make_editable_locator_postfix
from verification.data_layer import load_pages

# ─── Local copies of writeback helpers (also in verify_engine.py for execute_step Fix-6) ───
def _extract_locator_ref(step):
    """从 step params 中提取 ${group.field} 引用（P3f-1 修复）"""
    params = step.get('params', {})
    locator = params.get('locator', '') if isinstance(params, dict) else ''
    m = re.match(r'^\$\{([^}]+)\}$', locator)
    if m:
        return m.group(1)
    return None


def _get_original_xpath(ref, pages_dict):
    """获取 pages_dict 中的原始 xpath（P3f-1 修复）"""
    if not ref:
        return ''
    parts = ref.split('.', 1)
    if len(parts) != 2:
        return ''
    group, field = parts
    group_data = pages_dict.get(group, {})
    if not isinstance(group_data, dict):
        return ''
    val = group_data.get(field, '')
    if isinstance(val, str):
        return val.replace('xpath=', '')
    return ''


# Regex for stripping old verification markers from YAML trailing comments (#7)
_OLD_MARKER_RE = re.compile(
    r'\s*#\s*\[(?:UPGRADED|DOWNGRADED|CROSS-GROUP-NEW|UNVERIFIED|FALLBACK|PENDING-NO-GROUP)'
    r'(?::\s*[\w-]+)?\]'
)


def _extract_locator_ref(step):
    """从 step params 中提取 ${group.field} 引用（P3f-1 修复）"""
    params = step.get('params', {})
    locator = params.get('locator', '') if isinstance(params, dict) else ''
    m = re.match(r'^\$\{([^}]+)\}$', locator)
    if m:
        return m.group(1)
    return None


def _get_original_xpath(ref, pages_dict):
    """获取 pages_dict 中的原始 xpath（P3f-1 修复）"""
    if not ref:
        return ''
    parts = ref.split('.', 1)
    if len(parts) != 2:
        return ''
    group, field = parts
    group_data = pages_dict.get(group, {})
    if not isinstance(group_data, dict):
        return ''
    val = group_data.get(field, '')
    if isinstance(val, str):
        return val.replace('xpath=', '')
    return ''


def _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators,
                            is_best_guess=False, marker_override=None):
    """P3f-1: 存储验证通过的 locator 到 verified_locators 字典

    修复: Issue 2b — 当原 locator 有容器前缀但验证版本无前缀时，
    不再跳过写回，而是将验证通过的裸 XPath 写回到列表页 group 的对应字段。

    Args:
        is_best_guess: R5 — True when locator is KB best-guess (count=0), sets [UNVERIFIED] marker
    """
    ref = _extract_locator_ref(step)
    # [DEBUG] 早期退出点 1: ref 提取
    _debug_locator_param = step.get('params', {}).get('locator', '') if isinstance(step.get('params', {}), dict) else ''
    if not ref:
        print(f"    [DEBUG-STORE] ref=None, raw_locator='{_debug_locator_param[:80]}', step_desc='{step.get('desc','')[:40]}'")
        return
    orig_xpath = _get_original_xpath(ref, pages_dict)
    # [DEBUG] orig_xpath 提取
    print(f"    [DEBUG-STORE] ref='{ref}', orig_xpath='{orig_xpath[:80] if orig_xpath else '(empty)'}'")
    # 提取 verified locator 的 xpath 部分（去掉 xpath= 前缀）
    v_xpath = v_loc.replace('xpath=', '') if isinstance(v_loc, str) and v_loc.startswith('xpath=') else v_loc

    # el-select expand 转换：Phase 5 生成 input 目标，Phase 6 验证后转换为 el-select 容器
    field_name = ref.split('.', 1)[-1] if '.' in ref else ref
    if (field_name.endswith('_expand')
        and 'input' in v_xpath
        and 'el-input__inner' in v_xpath
        and 'contains(@placeholder' not in v_xpath):
        from verification.verify_engine import _convert_input_to_el_select
        converted = _convert_input_to_el_select(v_loc)
        if converted != v_loc:
            v_xpath = converted.replace('xpath=', '')
            v_loc = converted
            print(f"    [CONVERT] '{ref}' → el-select 容器")

    # 只在 locator 有变化时存储（减少不必要的回写）
    if orig_xpath and v_xpath and v_xpath != orig_xpath:
        CONTAINER_MARKERS = ('el-dialog', 'el-drawer', 'el-message-box',
                            'ant-modal', 'ant-drawer')
        CONTAINER_GROUP_MARKERS = ('_drawer_', '_dialog_', '_messagebox_',
                                    '_message_box_', '_ant-modal_', '_ant-drawer_')
        orig_has_container = any(m in orig_xpath for m in CONTAINER_MARKERS)
        new_has_container = any(m in v_xpath for m in CONTAINER_MARKERS)

        # [TRACE-P6] 写回决策日志
        print(f"    [TRACE-P6] _store_verified_locator: ref='{ref}'")
        print(f"    [TRACE-P6]   orig_has_container={orig_has_container}, new_has_container={new_has_container}")
        print(f"    [TRACE-P6]   orig: {orig_xpath[:80]}{'...' if len(orig_xpath) > 80 else ''}")
        print(f"    [TRACE-P6]   new:  {v_xpath[:80]}{'...' if len(v_xpath) > 80 else ''}")

        # 容器前缀移除：区分「降级」和「跨框架纠错」
        # 降级（阻止）：同框架内去掉容器前缀，可能是容器临时关闭导致
        # 跨框架纠错（允许）：原始前缀属于不同框架（如 el-drawer 用在 ant-modal 页面上）
        if orig_has_container and not new_has_container:
            ELEMENT_UI_MARKERS = ('el-dialog', 'el-drawer', 'el-message-box')
            ANT_DESIGN_MARKERS = ('ant-modal', 'ant-drawer')

            orig_is_el = any(m in orig_xpath for m in ELEMENT_UI_MARKERS)
            orig_is_ant = any(m in orig_xpath for m in ANT_DESIGN_MARKERS)
            group_is_ant = any(m in ref for m in ANT_DESIGN_MARKERS)
            group_is_el = any(m in ref for m in ('_dialog_', '_drawer_', '_messagebox_', '_message_box_'))

            # 跨框架纠错：原始前缀和页面框架不匹配
            is_cross_framework = (orig_is_el and group_is_ant) or (orig_is_ant and group_is_el)

            if is_cross_framework:
                orig_ct_name = next((m for m in ELEMENT_UI_MARKERS + ANT_DESIGN_MARKERS if m in orig_xpath), 'unknown')
                group_fw = 'ant' if group_is_ant else 'element-ui'
                marker = f'[CROSS-FRAMEWORK-CORRECT: {orig_ct_name}→{group_fw}]'
                verified_locators[ref] = {
                    'locator': v_loc,
                    'marker': marker_override or marker,
                    'container_type': v_ct,
                }
                print(f"    {marker} '{ref}' — 跨框架纠错，允许回写: "
                      f"{orig_xpath[:60]} → {v_xpath[:60]}")
                return

            print(f"    [BLOCKED: CONTAINER-DOWNGRADE] '{ref}' — 容器前缀降级，跳过写入: "
                  f"{orig_xpath[:60]} → {v_xpath[:60]}")
            return

        # M10: 升级方向 — 原 Locator 无前缀，验证通过的有容器前缀
        if not orig_has_container and new_has_container:
            # 确定容器类型标记
            upgrade_ct = None
            for cm in CONTAINER_MARKERS:
                if cm in v_xpath:
                    # 提取容器类型名称（去掉框架前缀）
                    upgrade_ct = cm.replace('el-', '').replace('ant-', '')
                    # 如果是 ant-modal 或 ant-drawer，保留 ant 前缀以便区分
                    if 'ant-' in cm:
                        upgrade_ct = cm  # ant-modal, ant-drawer
                    break
            marker = f'[UPGRADED: {upgrade_ct}]' if upgrade_ct else '[UPGRADED]'
            verified_locators[ref] = {
                'locator': v_loc,
                'marker': marker,
                'container_type': v_ct,
            }
            print(f"    {marker} '{ref}': 无前缀→{upgrade_ct or '容器'}前缀")
            return

        # [TRACE-P6] 情况③④：两边都有容器 或 两边都无容器
        if orig_has_container and new_has_container:
            # 情况③：容器类型变化
            orig_ct = None
            new_ct = None
            for cm in CONTAINER_MARKERS:
                if cm in orig_xpath:
                    orig_ct = cm
                if cm in v_xpath:
                    new_ct = cm
            if orig_ct != new_ct:
                print(f"    [TRACE-P6] 情况③: 容器类型变化 {orig_ct}→{new_ct}")
                marker = f'[CONTAINER-CHANGE: {orig_ct}→{new_ct}]'
                verified_locators[ref] = {
                    'locator': v_loc,
                    'marker': marker_override or marker,
                    'container_type': v_ct,
                }
                return
            else:
                print(f"    [TRACE-P6] 情况③: 容器类型相同 {orig_ct}")

        verified_locators[ref] = {
            'locator': v_loc,
            'marker': marker_override or ('[UNVERIFIED]' if is_best_guess else None),
            'container_type': v_ct,
        }


def update_pages_yaml(project_dir, verified_locators, module=None):
    """Update pages YAML with verified locators.

    verified_locators: {group.field: {locator, marker, container_type, is_new_field}}
    marker: None = verified, '[UPGRADED: ct]' = 升级, '[DOWNGRADED]' = 降级,
            '[UNVERIFIED]' = KB fallback, '[FALLBACK]' = fallback
    #7: marker 写入引号外作为 YAML 注释（如 ``# [UPGRADED: drawer]``），
        不嵌入 locator 值内（避免破坏 XPath 解析）
    is_new_field: True = append new field to group (cross-group writeback create)
    module: BUG-5 — when specified, restrict writeback to this module's pages directory
    """
    print(f"  [TRACE] update_pages_yaml: verified_locators={len(verified_locators)}, module={module}")
    pages_dir = os.path.join(project_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return

    # BUG-5: Protect common_elements fields from writeback
    # confirm_btn/cancel_btn 不纳入保护，因为它们高度依赖容器上下文（dialog/drawer）
    # Phase 6 验证后的带前缀 locator 比模板的无前缀 locator 更准确
    # 每个模块的 pages YAML 是独立的，不会发生 deep_merge 冲突
    PROTECTED_COMMON_FIELDS = {'success_text', 'error_text', 'loading_mask'}

    # BUG-5: Build module-scoped search directory
    if module:
        module_dir = module
        search_root = os.path.join(pages_dir, module_dir)
        if not os.path.isdir(search_root):
            search_root = pages_dir  # fallback if module dir doesn't exist
    else:
        search_root = pages_dir

    # Build {filepath: {group: {field: new_locator}}}
    updates = {}
    # #7: marker 独立存储，不嵌入 locator 值（避免破坏 XPath 解析）
    field_markers = {}  # {filepath: {group: {field: marker_string}}}

    for ref, info in verified_locators.items():
        parts = ref.split('.', 1)
        if len(parts) != 2:
            print(f"  [DEBUG-WB-BUILD] SKIP ref='{ref}': not group.field format")
            continue
        group, field = parts
        locator = info.get('locator', '')
        marker = info.get('marker', '')
        is_new_field = info.get('is_new_field', False)

        # BUG-5: Protect common_elements fields from writeback
        if group == 'common_elements' and field in PROTECTED_COMMON_FIELDS:
            print(f"  [DEBUG-WB-BUILD] SKIP {ref}: protected field")
            continue

        # Find which YAML file contains this group
        # F8: track all matching files to detect cross-module group name collisions
        # BUG-5: restrict search to module-scoped directory when module is specified
        matching_files = []
        for root, dirs, files in os.walk(search_root):
            for f in files:
                if f.endswith(('.yaml', '.yml')):
                    path = os.path.join(root, f)
                    try:
                        with open(path, encoding='utf-8') as fh:
                            data = yaml.safe_load(fh)
                        if isinstance(data, dict) and group in data:
                            matching_files.append(path)
                    except Exception:
                        pass

        if not matching_files:
            print(f"  [DEBUG-WB-BUILD] SKIP {ref}: group '{group}' not found in any YAML file")
            print(f"                   search_root={search_root}")
            continue

        if len(matching_files) > 1:
            # H6: 排序确保非 _ 前缀文件优先（elements.yaml > _fallback.yaml）
            matching_files.sort(key=lambda p: (0 if not os.path.basename(p).startswith('_') else 1, p))
            print(f"  [WARN] F8: group '{group}' found in {len(matching_files)} files: "
                  f"{[os.path.basename(p) for p in matching_files]}")
            print(f"         Using: {matching_files[0]} (non-underscore preferred)")

        print(f"  [DEBUG-WB-BUILD] ADD {ref}: file={os.path.basename(matching_files[0])}, is_new={is_new_field}")
        for path in matching_files[:1]:  # use first match only
            if path not in updates:
                updates[path] = {}
            if group not in updates[path]:
                updates[path][group] = {}
            # #7: 存储干净的 locator，不嵌入 marker
            updates[path][group][field] = locator
            # M5: _select 写回时同步更新 _editable companion
            if field.endswith('_select'):
                editable_field = field[:-len('_select')] + '_editable'
                # 从 _select locator 生成 _editable locator（后置模式）
                raw_locator = locator
                if raw_locator.startswith('xpath='):
                    raw_locator = raw_locator[6:]
                editable_raw = _make_editable_locator_postfix(raw_locator)
                if editable_raw != raw_locator:  # 仅当实际修改了才同步
                    updates[path][group][editable_field] = f'xpath={editable_raw}'
            if marker:
                if path not in field_markers:
                    field_markers[path] = {}
                if group not in field_markers[path]:
                    field_markers[path][group] = {}
                field_markers[path][group][field] = marker

    # [DEBUG-WB] 进入 writeback 时，打印所有 verified_locators
    print(f"\n  [DEBUG-WB] === update_pages_yaml START ===")
    print(f"  [DEBUG-WB] 总 verified_locators: {len(verified_locators)}")
    for r, info in verified_locators.items():
        loc_val = info.get('locator', '')
        loc_short = loc_val.replace('xpath=', '')[:80] if loc_val else ''
        marker = info.get('marker', '')
        is_new = info.get('is_new_field', False)
        print(f"  [DEBUG-WB]   {r}: marker={marker}, is_new={is_new}, locator='{loc_short}'")

    # [DEBUG-WB] 打印 updates 字典构建结果
    print(f"\n  [DEBUG-WB] === updates dict ===")
    for filepath, groups in updates.items():
        print(f"  [DEBUG-WB] File: {os.path.basename(filepath)}")
        for group, fields in groups.items():
            print(f"  [DEBUG-WB]   Group '{group}': {len(fields)} fields")
            for field in fields:
                print(f"  [DEBUG-WB]     - {field}")

    # Write back
    for filepath, groups in updates.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # [DEBUG-WB] 写回前：打印文件中所有 common_elements 行的当前值
            print(f"\n  [DEBUG-WB] --- 文件写回前: {os.path.basename(filepath)} ---")
            for _i, _line in enumerate(lines):
                _s = _line.strip()
                if _s.startswith('common_elements:'):
                    # 打印整个 common_elements 组
                    print(f"  [DEBUG-WB]   [PRE] Line {_i+1}: {_s}")
                    for _j in range(_i + 1, min(_i + 20, len(lines))):
                        _s2 = lines[_j].strip()
                        if _s2 and not _s2.startswith(' ') and not _s2.startswith('#'):
                            break
                        if 'confirm_btn' in _s2 or 'cancel_btn' in _s2:
                            print(f"  [DEBUG-WB]   [PRE] Line {_j+1}: {_s2}")

            for group, fields in groups.items():
                # 分离新字段和已有字段
                new_fields = {}
                existing_fields = {}
                for field, new_locator in fields.items():
                    ref_key = f"{group}.{field}"
                    info = verified_locators.get(ref_key, {})
                    if info.get('is_new_field', False):
                        new_fields[field] = new_locator
                    else:
                        existing_fields[field] = new_locator
                # [DEBUG-WB] 记录分组处理详情
                print(f"  [DEBUG-WB] Processing group '{group}': {len(existing_fields)} existing, {len(new_fields)} new")
                if existing_fields:
                    print(f"  [DEBUG-WB]   existing_fields: {list(existing_fields.keys())}")
                if new_fields:
                    print(f"  [DEBUG-WB]   new_fields: {list(new_fields.keys())}")

                # 替换已有字段
                in_group = False
                group_end = -1
                for i, line in enumerate(lines):
                    stripped = line.rstrip()
                    if stripped.startswith(f'{group}:'):
                        in_group = True
                        continue
                    if in_group:
                        # Check if we've left the group (new top-level key)
                        if stripped and not stripped.startswith(' ') and not stripped.startswith('#'):
                            group_end = i
                            in_group = False
                            continue
                        for field, new_locator in existing_fields.items():
                            if stripped.lstrip().startswith(f'{field}:'):
                                # [DEBUG-WB] 行匹配日志 - 扩展为所有字段
                                _old_line = line.strip()
                                _is_common = group == 'common_elements'
                                # 记录所有字段的匹配，不仅仅是 common_elements
                                print(f"  [DEBUG-WB]   MATCH Line {i+1}: field='{field}', group='{group}'")
                                print(f"  [DEBUG-WB]     OLD: {_old_line[:120]}")
                                # 防御: 拒绝回写 contains(text(),'') 废模板
                                if isinstance(new_locator, str) and "contains(text(),'')" in new_locator:
                                    print(f"  [WARN] 跳过废模板回写: {field} 包含 contains(text(),'')")
                                    continue
                                # Replace the line, preserving trailing comment
                                indent = len(line) - len(line.lstrip())
                                # Extract trailing comment after closing quote
                                # F1: 兼容单引号和双引号（_pages_writer 用单引号）
                                _comment = ''
                                _last_quote = max(line.rfind('"'), line.rfind("'"))
                                if _last_quote > 0:
                                    _after = line[_last_quote + 1:]
                                    _hash_idx = _after.find('#')
                                    if _hash_idx >= 0:
                                        _comment = _after[_hash_idx:].rstrip()
                                # #7: 清除旧版 marker，防止重复标注
                                if _comment:
                                    _comment = _OLD_MARKER_RE.sub('', _comment).strip()
                                # #7: marker 写入引号外作为 YAML 注释
                                _fmarker = field_markers.get(filepath, {}).get(group, {}).get(field, '')
                                _parts = []
                                if _comment:
                                    _parts.append(f"  {_comment}")
                                if _fmarker:
                                    _parts.append(f"  # {_fmarker}")
                                _final_comment = "".join(_parts)
                                scalar = _escape_yaml_scalar(new_locator)
                                lines[i] = f"{' ' * indent}{field}: {scalar}{_final_comment}\n"
                                # 记录所有字段的新值
                                print(f"  [DEBUG-WB]     NEW: {lines[i].strip()[:120]}")
                                break

                # 追加新字段到 group 末尾
                if new_fields:
                    insert_pos = group_end if group_end > 0 else len(lines)
                    for field, new_locator in new_fields.items():
                        # 防御: 拒绝回写 contains(text(),'') 废模板
                        if isinstance(new_locator, str) and "contains(text(),'')" in new_locator:
                            print(f"  [WARN] 跳过废模板回写: {field} 包含 contains(text(),'')")
                            continue
                        # #7: 新字段也添加 marker 作为 YAML 注释
                        _fmarker = field_markers.get(filepath, {}).get(group, {}).get(field, '')
                        _marker_part = f"  # {_fmarker}" if _fmarker else ""
                        scalar = _escape_yaml_scalar(new_locator)
                        new_line = f'  {field}: {scalar}{_marker_part}\n'
                        lines.insert(insert_pos, new_line)
                        insert_pos += 1

            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            print(f"  [OK] Updated: {filepath}")

            # [DEBUG-WB] 写回后：打印文件中所有 confirm_btn/cancel_btn 行的最终值
            if filepath:
                print(f"\n  [DEBUG-WB] --- 文件写回后: {os.path.basename(filepath)} ---")
                for _i, _line in enumerate(lines):
                    _s = _line.strip()
                    if 'confirm_btn' in _s or 'cancel_btn' in _s:
                        print(f"  [DEBUG-WB]   [POST] Line {_i+1}: {_s[:120]}")
        except Exception as e:
            print(f"  [ERROR] Failed to update {filepath}: {e}")

    # Post-processing: Apply hidden filters and strip not(ancestor::) exclusions
    # These functions were migrated from probe_from_pages.py and need to be called here
    print("\n[Post-processing] Applying hidden filters and cleaning up exclusions...")

    # [DEBUG-WB] 后处理前：打印 common_elements 当前状态
    print("\n  [DEBUG-WB] --- 后处理前: 读取 YAML 文件中的 common_elements ---")

    # Build pages_data and source_files for batch processing
    pages_data = load_pages(project_dir, module)

    # [意见4b] 校验 pages_data 与刚写入的文件是否一致
    if 'common_elements' in pages_data and isinstance(pages_data['common_elements'], dict):
        ce = pages_data['common_elements']
        for ref, info in verified_locators.items():
            if not ref.startswith('common_elements.'):
                continue
            field = ref.split('.', 1)[1]
            expected = info.get('locator', '')
            actual = ce.get(field, '')
            exp_clean = expected.replace('xpath=', '') if expected else ''
            act_clean = actual.replace('xpath=', '') if isinstance(actual, str) else ''
            if exp_clean and act_clean and exp_clean != act_clean:
                print(f"  [WARN-P6] pages_data 与文件不一致: {ref}")
                print(f"            expected: {exp_clean[:80]}")
                print(f"            actual:   {act_clean[:80]}")
                # 修正内存对象，防止后处理覆盖正确值
                ce[field] = expected

    source_files = {}
    for root, dirs, files in os.walk(pages_dir):
        for f in files:
            if f.endswith(('.yaml', '.yml')):
                path = os.path.join(root, f)
                try:
                    with open(path, encoding='utf-8') as fh:
                        data = yaml.safe_load(fh)
                    if isinstance(data, dict):
                        for group in data.keys():
                            if group != 'page_urls' and isinstance(data[group], dict):
                                source_files[group] = path
                except Exception:
                    pass

    # [DEBUG-WB] 后处理前：打印 common_elements 当前状态
    if 'common_elements' in pages_data:
        common_data = pages_data['common_elements']
        if isinstance(common_data, dict):
            for field in ['confirm_btn', 'confirm_btn_2', 'confirm_btn_3', 'confirm_btn_4', 'confirm_btn_5',
                          'cancel_btn', 'cancel_btn_2', 'cancel_btn_3', 'cancel_btn_4', 'cancel_btn_5']:
                if field in common_data:
                    val = common_data[field]
                    val_short = val[:80] if isinstance(val, str) else str(val)[:80]
                    print(f"  [DEBUG-WB]   [PRE-POST] common_elements.{field} = {val_short}")

    # Apply hidden filters to all locators
    hidden_count = apply_hidden_filters_to_pages(pages_data, source_files, pages_dir)
    if hidden_count > 0:
        print(f"  R4.11: 补齐 {hidden_count} 个定位器的隐藏过滤属性")

    # [DEBUG-WB] hidden filters 后：打印 common_elements 状态
    if 'common_elements' in pages_data:
        common_data = pages_data['common_elements']
        if isinstance(common_data, dict):
            print(f"\n  [DEBUG-WB] --- hidden filters 后 ---")
            for field in ['confirm_btn', 'confirm_btn_2', 'confirm_btn_3', 'confirm_btn_4', 'confirm_btn_5',
                          'cancel_btn', 'cancel_btn_2', 'cancel_btn_3', 'cancel_btn_4', 'cancel_btn_5']:
                if field in common_data:
                    val = common_data[field]
                    val_short = val[:80] if isinstance(val, str) else str(val)[:80]
                    print(f"  [DEBUG-WB]   [POST-HIDDEN] common_elements.{field} = {val_short}")

    # Strip not(ancestor::) exclusions (R3.14)
    stripped_count = strip_not_ancestor_from_pages(pages_data, source_files, pages_dir)
    if stripped_count > 0:
        print(f"  R3.14: 清除 {stripped_count} 个定位器的 not(ancestor::) 排除")

    # [DEBUG-WB] 后处理完成后：重新读取文件，打印最终状态
    print(f"\n  [DEBUG-WB] --- 后处理完成后: 重新读取 YAML 文件 ---")
    if module:
        module_dir = module
        final_path = os.path.join(pages_dir, module_dir, 'elements.yaml')
        if os.path.exists(final_path):
            try:
                with open(final_path, 'r', encoding='utf-8') as f:
                    final_lines = f.readlines()
                for _i, _line in enumerate(final_lines):
                    _s = _line.strip()
                    if 'confirm_btn' in _s or 'cancel_btn' in _s:
                        print(f"  [DEBUG-WB]   [FINAL] Line {_i+1}: {_s[:120]}")
            except Exception:
                pass


def _write_iframe_companion_fields(project_dir, iframe_discoveries, module=None):
    """在 pages YAML 中追加 iframe 伴侣字段（方案 B：保留原有格式）

    对于每个 iframe 发现，在对应的 pages YAML 中追加 `{field}_iframe` 字段，
    值为 iframe 的 CSS 选择器。

    Args:
        project_dir: 项目根目录
        iframe_discoveries: [{group, field, frame_selector}, ...]
        module: 模块名（可选，用于定位 pages 目录）
    """
    if not iframe_discoveries:
        return

    print(f"\n[IFRAME] 写入 {len(iframe_discoveries)} 个 iframe 伴侣字段...")

    # BUG-5: Build module-scoped search directory
    pages_dir = os.path.join(project_dir, 'pages')
    if module:
        module_dir = module
        search_root = os.path.join(pages_dir, module_dir)
        if not os.path.isdir(search_root):
            search_root = pages_dir
    else:
        search_root = pages_dir

    # 按文件分组
    updates_by_file = {}  # {filepath: [{group, field, frame_selector}, ...]}

    for disc in iframe_discoveries:
        group = disc.get('group')
        field = disc.get('field')
        frame_selector = disc.get('frame_selector')

        if not (group and field and frame_selector):
            continue

        # 查找包含该 group 的 YAML 文件
        target_file = None
        for root, dirs, files in os.walk(search_root):
            for f in files:
                if f.endswith(('.yaml', '.yml')):
                    path = os.path.join(root, f)
                    try:
                        with open(path, encoding='utf-8') as fh:
                            data = yaml.safe_load(fh)
                        if isinstance(data, dict) and group in data:
                            target_file = path
                            break
                    except Exception:
                        pass
            if target_file:
                break

        if not target_file:
            print(f"  [WARN] 未找到包含 group '{group}' 的 YAML 文件")
            continue

        if target_file not in updates_by_file:
            updates_by_file[target_file] = []
        updates_by_file[target_file].append({
            'group': group,
            'field': field,
            'frame_selector': frame_selector,
            'clean_xpath': disc.get('clean_xpath', ''),
        })

    # 逐个文件处理
    for filepath, updates in updates_by_file.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 对每个更新，找到 field 所在位置，在其后插入 _iframe 伴侣字段
            for update in updates:
                group = update['group']
                field = update['field']
                frame_selector = update['frame_selector']
                iframe_field = f'{field}_iframe'

                # 检查是否已存在 _iframe 字段
                iframe_exists = False
                for line in lines:
                    if line.strip().startswith(f'{iframe_field}:'):
                        iframe_exists = True
                        break

                # 回写 iframe 内 locator 到原始字段（2026-08-19）
                # 必须在 iframe_exists 检查之前，因为即使 _iframe 字段已存在，原始字段可能仍缺失
                clean_xpath = update.get('clean_xpath')
                if clean_xpath:
                    # 查找原始字段是否已存在
                    original_exists = False
                    for line in lines:
                        if line.strip().startswith(f'{field}:'):
                            original_exists = True
                            break

                    if not original_exists:
                        # 原始字段不存在，在 _iframe 字段后插入（或在 group 末尾）
                        original_value = f'xpath={clean_xpath}'
                        original_scalar = _escape_yaml_scalar(original_value)

                        # 找到 _iframe 字段位置或 group 末尾
                        original_insert_pos = None
                        original_indent = None
                        in_target_group = False
                        for i, line in enumerate(lines):
                            stripped = line.strip()

                            # 进入目标 group
                            if stripped.startswith(f'{group}:'):
                                in_target_group = True
                                continue

                            # 离开 group（遇到新的顶层 key）
                            if in_target_group and stripped and not line.startswith(' ') and ':' in stripped:
                                original_insert_pos = i
                                original_indent = 2  # 默认缩进
                                break

                            # 找到 _iframe 字段，在它后面插入
                            if in_target_group and stripped.startswith(f'{iframe_field}:'):
                                original_insert_pos = i + 1
                                original_indent = len(line) - len(line.lstrip())
                                break

                        # 如果没找到 _iframe 字段，在 group 末尾插入
                        if original_insert_pos is None and in_target_group:
                            # 找到 group 的最后一个字段
                            for j in range(len(lines) - 1, -1, -1):
                                if lines[j].strip().startswith(f'{group}:'):
                                    original_insert_pos = j + 1
                                    original_indent = 2
                                    break
                                elif lines[j].strip() and lines[j].startswith(' '):
                                    # 找到 group 内的最后一个字段
                                    original_insert_pos = j + 1
                                    original_indent = len(lines[j]) - len(lines[j].lstrip())
                                    break

                        if original_insert_pos is not None:
                            indent_str = ' ' * original_indent
                            original_line = f'{indent_str}{field}: {original_scalar}  # iframe 内元素（自动发现）\n'
                            lines.insert(original_insert_pos, original_line)
                            print(f"  [OK] {group}.{field} = {original_value[:80]}")
                        else:
                            print(f"  [WARN] 无法找到插入位置: {group}.{field}")
                    else:
                        print(f"  [SKIP] {group}.{field} 已存在")

                if iframe_exists:
                    print(f"  [SKIP] {group}.{iframe_field} 已存在")
                    continue

                # 找到 field 所在位置
                insert_pos = None
                field_indent = None
                in_target_group = False
                for i, line in enumerate(lines):
                    stripped = line.strip()

                    # 进入目标 group
                    if stripped.startswith(f'{group}:'):
                        in_target_group = True
                        continue

                    # 离开 group（遇到新的顶层 key）
                    if in_target_group and stripped and not line.startswith(' ') and ':' in stripped:
                        in_target_group = False

                    # 在 group 内找到目标 field
                    if in_target_group and stripped.startswith(f'{field}:'):
                        insert_pos = i + 1
                        # 检测实际缩进
                        field_indent = len(line) - len(line.lstrip())
                        break

                if insert_pos is None:
                    # field 未找到，尝试在空 group 中追加
                    group_pos = None
                    group_indent = None
                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        if stripped.startswith(f'{group}:'):
                            group_pos = i
                            group_indent = len(line) - len(line.lstrip())
                            # 检查 group 是否为空（下一行是顶层 key 或文件结尾）
                            if i + 1 >= len(lines) or (lines[i+1].strip() and not lines[i+1].startswith(' ')):
                                # 空 group，在 group 声明后插入
                                insert_pos = i + 1
                                field_indent = group_indent + 2  # 子字段缩进
                                break
                            else:
                                # 非空 group，找到最后一个子字段后插入
                                for j in range(i + 1, len(lines)):
                                    if lines[j].strip() and not lines[j].startswith(' '):
                                        # 遇到顶层 key，在它之前插入
                                        insert_pos = j
                                        field_indent = group_indent + 2
                                        break
                                    elif lines[j].strip().startswith(f'{field}:'):
                                        # 已存在该 field，跳过
                                        insert_pos = None
                                        break
                                break

                    if insert_pos is None:
                        print(f"  [WARN] 未在 {filepath} 中找到 {group}.{field}")
                        continue

                # 插入 _iframe 伴侣字段（全 XPath 格式，2026-08-07）
                indent = ' ' * (field_indent if field_indent else 2)
                # 使用统一的 YAML 转义函数处理 frame_selector
                scalar = _escape_yaml_scalar(frame_selector)
                # 检查 frame_selector 是否已经是 xpath= 开头
                if frame_selector.startswith('xpath='):
                    new_line = f'{indent}{iframe_field}: {scalar}  # iframe 定位器（自动发现）\n'
                else:
                    # 兼容旧的 CSS 格式，转换为 XPath
                    new_line = f'{indent}{iframe_field}: {scalar}  # iframe 定位器（待转换）\n'
                lines.insert(insert_pos, new_line)
                print(f"  [OK] {group}.{iframe_field} = {frame_selector}")

            # 写回文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)

        except Exception as e:
            print(f"  [ERROR] 处理 {filepath} 失败: {e}")


def _update_case_iframe_keywords(project_dir, iframe_discoveries, module=None):
    """在 case YAML 中将 iframe 内步骤的 keyword 更新为 frame_* 形式

    对于每个 iframe 发现，将对应步骤的 keyword 从 click_element/fill_value
    更新为 frame_click_element/frame_fill_value，并添加 frame 参数。

    Args:
        project_dir: 项目根目录
        iframe_discoveries: [{case_name, step_index, group, field, keyword}, ...]
        module: 模块名（可选，用于定位 cases 目录）
    """
    if not iframe_discoveries:
        return

    print(f"\n[IFRAME] 更新 {len(iframe_discoveries)} 个 case 步骤的 keyword...")

    # 按 case 文件分组
    updates_by_case = {}  # {case_filepath: [{step_index, group, field, keyword}, ...]}

    cases_dir = os.path.join(project_dir, 'cases')
    if module:
        module_dir = module
        search_root = os.path.join(cases_dir, module_dir)
        if not os.path.isdir(search_root):
            search_root = cases_dir
    else:
        search_root = cases_dir

    for disc in iframe_discoveries:
        case_name = disc.get('case_name')
        step_index = disc.get('step_index')
        group = disc.get('group')
        field = disc.get('field')
        keyword = disc.get('keyword', '')

        if case_name is None or step_index is None or not (group and field):
            continue

        # 查找 case 文件
        target_file = None
        for root, dirs, files in os.walk(search_root):
            for f in files:
                if f.endswith(('.yaml', '.yml')) and case_name in f:
                    target_file = os.path.join(root, f)
                    break
            if target_file:
                break

        if not target_file:
            print(f"  [WARN] 未找到 case 文件: {case_name}")
            continue

        if target_file not in updates_by_case:
            updates_by_case[target_file] = []
        updates_by_case[target_file].append({
            'step_index': step_index,
            'group': group,
            'field': field,
            'keyword': keyword,
        })

    # 逐个文件处理
    for filepath, updates in updates_by_case.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            data = yaml.safe_load(content)
            if not data or not isinstance(data, dict) or 'steps' not in data:
                print(f"  [WARN] {filepath} 格式异常，跳过")
                continue

            steps = data['steps']
            updated_count = 0

            # 关键修复：倒序处理 updates，避免插入步骤导致后续索引偏移
            updates_sorted = sorted(updates, key=lambda u: u['step_index'], reverse=True)

            for update in updates_sorted:
                step_index = update['step_index']
                group = update['group']
                field = update['field']
                old_keyword = update['keyword']

                if step_index >= len(steps):
                    continue

                step = steps[step_index]
                if not isinstance(step, dict):
                    continue

                # 防御性校验：确认步骤的 keyword 与 discovery 记录的 keyword 一致
                # 防止索引偏移导致把 frame_* 写入错误的步骤
                current_keyword = step.get('keyword')
                if current_keyword != old_keyword:
                    print(f"  [WARN] Step {step_index+1}: keyword 不匹配 "
                          f"({current_keyword} ≠ {old_keyword})，跳过")
                    continue

                # 映射 keyword → frame_keyword
                frame_keyword_map = {
                    'click_element': 'frame_click_element',
                    'fill_value': 'frame_fill_value',
                    'click': 'frame_click_element',
                }
                new_keyword = frame_keyword_map.get(old_keyword)
                if not new_keyword:
                    continue

                # 更新 keyword
                step['keyword'] = new_keyword

                # 添加 frame 参数
                iframe_ref = f'${{{group}.{field}_iframe}}'
                if 'params' not in step:
                    step['params'] = {}
                step['params']['frame'] = iframe_ref

                # 关键修复：在 frame_* 步骤前插入 wait_for_element 等待 iframe 加载
                # 与 case_generator.py line 1620-1626 逻辑对称
                # 检查前一步是否已经是 wait_for_element（避免重复插入）
                _need_wait = True
                if step_index > 0:
                    _prev_step = steps[step_index - 1]
                    if (isinstance(_prev_step, dict)
                            and _prev_step.get('keyword') == 'wait_for_element'
                            and 'iframe' in _prev_step.get('desc', '')):
                        _need_wait = False

                if _need_wait:
                    # 从 step desc 中提取标签用于 wait 步骤描述
                    _label = ''
                    _desc = step.get('desc', '')
                    import re as _re
                    _m = _re.search(r'[「『](.+?)[」』]', _desc)
                    if _m:
                        _label = _m.group(1)

                    _wait_desc = f"等待「{_label}」的 iframe 加载完成" if _label else "等待 iframe 加载完成"
                    _wait_step = {
                        'desc': _wait_desc,
                        'keyword': 'wait_for_element',
                        'params': {
                            'locator': iframe_ref,
                            'timeout': 10000,
                        },
                    }
                    steps.insert(step_index, _wait_step)
                    print(f"  [OK] Step {step_index+1}: 插入 wait_for_element (iframe 等待)")

                updated_count += 1
                print(f"  [OK] Step {step_index+1}: {old_keyword} → {new_keyword} (frame={iframe_ref})")

            if updated_count > 0:
                # 写回 YAML（保留格式）
                with open(filepath, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                print(f"  [OK] Updated: {filepath} ({updated_count} steps)")

        except Exception as e:
            print(f"  [ERROR] 处理 {filepath} 失败: {e}")


def _update_case_collapse_prefix(collapse_updates, project_dir, module=None):
    """在 case YAML 中更新 collapse 步骤的容器前缀

    对于每个 expand 验证成功且容器前缀与 collapse 不一致的情况，
    将 collapse 步骤的容器前缀替换为 expand 的容器前缀。

    Args:
        collapse_updates: [{case_name, step_index, old_prefix, new_prefix}, ...]
        project_dir: 项目根目录
        module: 模块名（可选，用于定位 cases 目录）
    """
    if not collapse_updates:
        return

    print(f"\n[COLLAPSE] 更新 {len(collapse_updates)} 个 case 步骤的容器前缀...")

    # 按 case 文件分组
    updates_by_case = {}  # {case_filepath: [{step_index, old_prefix, new_prefix}, ...]}

    cases_dir = os.path.join(project_dir, 'cases')
    if module:
        module_dir = module
        search_root = os.path.join(cases_dir, module_dir)
        if not os.path.isdir(search_root):
            search_root = cases_dir
    else:
        search_root = cases_dir

    for update in collapse_updates:
        case_name = update.get('case_name')
        step_index = update.get('step_index')
        old_prefix = update.get('old_prefix')
        new_prefix = update.get('new_prefix')

        if case_name is None or step_index is None:
            continue

        # 查找 case 文件
        target_file = None
        for root, dirs, files in os.walk(search_root):
            for f in files:
                if f.endswith(('.yaml', '.yml')) and case_name in f:
                    target_file = os.path.join(root, f)
                    break
            if target_file:
                break

        if not target_file:
            print(f"  [WARN] 未找到 case 文件: {case_name}")
            continue

        if target_file not in updates_by_case:
            updates_by_case[target_file] = []
        updates_by_case[target_file].append({
            'step_index': step_index,
            'old_prefix': old_prefix,
            'new_prefix': new_prefix,
        })

    # 逐个文件处理
    for filepath, updates in updates_by_case.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            data = yaml.safe_load(content)
            if not data or not isinstance(data, dict) or 'steps' not in data:
                print(f"  [WARN] {filepath} 格式异常，跳过")
                continue

            steps = data['steps']
            updated_count = 0

            for update in updates:
                step_index = update['step_index']
                old_prefix = update['old_prefix']
                new_prefix = update['new_prefix']

                if step_index >= len(steps):
                    continue

                step = steps[step_index]
                if not isinstance(step, dict):
                    continue

                # 防御性校验：确认是 if_element_visible 且 desc 包含"收起"
                if step.get('keyword') != 'if_element_visible':
                    print(f"  [WARN] Step {step_index+1}: 不是 if_element_visible，跳过")
                    continue

                desc = step.get('desc', '')
                if '收起' not in desc or ('下拉面板' not in desc and '级联面板' not in desc):
                    print(f"  [WARN] Step {step_index+1}: 不是 collapse 步骤，跳过")
                    continue

                # 更新外层 locator 和 then_steps 内层 locator
                updated = False
                for loc_path in [
                    ('params', 'locator'),
                    ('params', 'then_steps', 0, 'params', 'locator'),
                ]:
                    obj = step
                    for key in loc_path[:-1]:
                        if isinstance(key, int):
                            obj = obj[key] if isinstance(obj, list) and key < len(obj) else None
                        else:
                            obj = obj.get(key) if isinstance(obj, dict) else None
                        if obj is None:
                            break

                    loc_key = loc_path[-1]
                    if not isinstance(obj, dict) or loc_key not in obj:
                        continue

                    locator = obj[loc_key]
                    if not locator or not isinstance(locator, str):
                        continue

                    if old_prefix:
                        # 有旧前缀：替换为新前缀
                        if new_prefix:
                            locator = locator.replace(old_prefix, new_prefix, 1)
                        else:
                            # 删除旧前缀
                            locator = locator.replace(old_prefix, '', 1)
                    elif new_prefix:
                        # 无前缀 → 有前缀：在 xpath= 后或 ( 后插入前缀
                        if locator.startswith('xpath=('):
                            locator = locator.replace('xpath=(', f'xpath=({new_prefix}', 1)
                        elif locator.startswith('xpath=//'):
                            locator = locator.replace('xpath=', f'xpath={new_prefix}', 1)

                    obj[loc_key] = locator
                    updated = True

                if updated:
                    updated_count += 1
                    print(f"  [OK] Step {step_index+1}: {old_prefix or '(无前缀)'} → {new_prefix or '(无前缀)'}")

            if updated_count > 0:
                # 写回 YAML
                with open(filepath, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                print(f"  [OK] Updated: {filepath} ({updated_count} steps)")

        except Exception as e:
            print(f"  [ERROR] 处理 {filepath} 失败: {e}")
