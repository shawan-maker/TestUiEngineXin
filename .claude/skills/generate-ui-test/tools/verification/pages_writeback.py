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
    if not ref:
        return
    orig_xpath = _get_original_xpath(ref, pages_dict)
    # 提取 verified locator 的 xpath 部分（去掉 xpath= 前缀）
    v_xpath = v_loc.replace('xpath=', '') if isinstance(v_loc, str) and v_loc.startswith('xpath=') else v_loc

    # el-select expand 转换：Phase 5 生成 input 目标，Phase 6 验证后转换为 el-select 容器
    field_name = ref.split('.', 1)[-1] if '.' in ref else ref
    if field_name.endswith('_expand') and 'input' in v_xpath and 'el-input__inner' in v_xpath:
        from verification.verify_engine import _convert_input_to_el_select
        converted = _convert_input_to_el_select(v_loc)
        if converted != v_loc:
            v_xpath = converted.replace('xpath=', '')
            v_loc = converted
            print(f"    [CONVERT] '{ref}' → el-select 容器")

    # 只在 locator 有变化时存储（减少不必要的回写）
    if orig_xpath and v_xpath and v_xpath != orig_xpath:
        CONTAINER_MARKERS = ('el-dialog', 'el-drawer', 'el-message-box')
        CONTAINER_GROUP_MARKERS = ('_drawer_', '_dialog_', '_messagebox_',
                                    '_message_box_')
        orig_has_container = any(m in orig_xpath for m in CONTAINER_MARKERS)
        new_has_container = any(m in v_xpath for m in CONTAINER_MARKERS)
        if orig_has_container and not new_has_container:
            # 方案B: 禁止 DOWNGRADED 覆盖 — 原始有容器前缀但验证后没有，保留原始版本
            # 根因：容器检测时序问题导致 Phase 6 验证时 count==1（dialog 未完全渲染），
            # 但 Phase 9 运行时 dialog 已完全打开，count==2 → strict mode violation
            print(f"    [PRESERVED-SCOPED] '{ref}' — 原始 locator 有容器前缀，"
                  f"验证后没有，保留原始版本，不降级")
            return
        # M10: 升级方向 — 原 locator 无前缀，验证通过的有容器前缀
        elif not orig_has_container and new_has_container:
            # 确定容器类型标记
            upgrade_ct = None
            for cm in CONTAINER_MARKERS:
                if cm in v_xpath:
                    upgrade_ct = cm.replace('el-', '')
                    break
            marker = f'[UPGRADED: {upgrade_ct}]' if upgrade_ct else '[UPGRADED]'
            verified_locators[ref] = {
                'locator': v_loc,
                'marker': marker,
                'container_type': v_ct,
            }
            print(f"    {marker} '{ref}': 无前缀→{upgrade_ct or '容器'}前缀")
            return
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
    pages_dir = os.path.join(project_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return

    # BUG-5 + M8: Protect common_elements fields from writeback
    # M8: confirm_btn/cancel_btn 也纳入保护，防止跨模块 deep_merge 冲突
    # 不同模块的 common_elements.confirm_btn 会有不同容器前缀（drawer/dialog），
    # deep_merge 后最后加载的模块覆盖前面的，导致运行时容器定位错误
    PROTECTED_COMMON_FIELDS = {'success_text', 'error_text', 'loading_mask',
                                'confirm_btn', 'cancel_btn'}

    # BUG-5: Build module-scoped search directory
    if module:
        module_dir = module.replace('_', '-')
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
            continue
        group, field = parts
        locator = info.get('locator', '')
        marker = info.get('marker', '')
        is_new_field = info.get('is_new_field', False)

        # BUG-5: Protect common_elements fields from writeback
        if group == 'common_elements' and field in PROTECTED_COMMON_FIELDS:
            print(f"  [SKIP] Protected field common_elements.{field} — writeback not allowed")
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
        if len(matching_files) > 1:
            # H6: 排序确保非 _ 前缀文件优先（elements.yaml > _fallback.yaml）
            matching_files.sort(key=lambda p: (0 if not os.path.basename(p).startswith('_') else 1, p))
            print(f"  [WARN] F8: group '{group}' found in {len(matching_files)} files: "
                  f"{[os.path.basename(p) for p in matching_files]}")
            print(f"         Using: {matching_files[0]} (non-underscore preferred)")
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

    # Write back
    for filepath, groups in updates.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

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
        except Exception as e:
            print(f"  [ERROR] Failed to update {filepath}: {e}")

    # Post-processing: Apply hidden filters and strip not(ancestor::) exclusions
    # These functions were migrated from probe_from_pages.py and need to be called here
    print("\n[Post-processing] Applying hidden filters and cleaning up exclusions...")

    # Build pages_data and source_files for batch processing
    pages_data = load_pages(project_dir, module)
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

    # Apply hidden filters to all locators
    hidden_count = apply_hidden_filters_to_pages(pages_data, source_files, pages_dir)
    if hidden_count > 0:
        print(f"  R4.11: 补齐 {hidden_count} 个定位器的隐藏过滤属性")

    # Strip not(ancestor::) exclusions (R3.14)
    stripped_count = strip_not_ancestor_from_pages(pages_data, source_files, pages_dir)
    if stripped_count > 0:
        print(f"  R3.14: 清除 {stripped_count} 个定位器的 not(ancestor::) 排除")

