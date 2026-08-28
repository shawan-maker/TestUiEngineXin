"""L3 模块复合关键字编译器（Phase 3）

从 _knowledge/*.yaml 中的 workflow 定义编译为 Python 模块，
输出至 lib/module_keywords.py。

用法:
    python compile_module_keywords.py <project_dir> [--dry-run]

退出码:
    0 = 成功
    1 = 有错误
"""
import sys
import os
import re
import glob
import argparse
from datetime import datetime

# Ensure tools/ is on sys.path for core.* imports
_tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

import yaml


# ============================================================================
# YAML 加载 + list/dict 兼容
# ============================================================================

def load_workflows(project_dir):
    """扫描系统级 + 项目级 workflow 定义，合并返回

    加载顺序（last-writer-wins，项目级覆盖系统级同名关键字）:
      1. 系统级: skills/lib/system_workflows.yaml
      2. 技能级: skills/lib/_knowledge/*.yaml
      3. 项目级: {project}/_knowledge/*.yaml

    兼容 list 和 dict 两种 workflows 格式:
      list: workflows: [{name: xxx, ...}, ...]
      dict: workflows: {name: {...}, ...}

    Returns: (list of (source_file, workflow_dict), list of error_str)
    """
    workflows = []
    errors = []
    seen_names = {}  # name → index in workflows list（用于项目级覆盖系统级）

    # ── 层 1: 系统级 ──
    skill_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys_path = os.path.join(skill_dir, 'lib', 'system_workflows.yaml')
    if os.path.isfile(sys_path):
        _load_yaml_workflows(sys_path, 'lib/system_workflows.yaml',
                             workflows, errors, seen_names)

    # ── 层 2: 技能级 _knowledge/*.yaml ──
    skill_knowledge_dir = os.path.join(skill_dir, 'lib', '_knowledge')  # skill_dir already 3 levels up
    if os.path.isdir(skill_knowledge_dir):
        for f in sorted(glob.glob(os.path.join(skill_knowledge_dir, "*.yaml"))):
            source = f"lib/_knowledge/{os.path.basename(f)}"
            _load_yaml_workflows(f, source, workflows, errors, seen_names)

    # ── 层 3: 项目级（覆盖系统级和技能级同名） ──
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if os.path.isdir(knowledge_dir):
        for f in sorted(glob.glob(os.path.join(knowledge_dir, "*.yaml"))):
            source = f"_knowledge/{os.path.basename(f)}"
            if os.path.basename(f) == 'workflow_aliases.yaml':
                continue  # 已废弃
            _load_yaml_workflows(f, source, workflows, errors, seen_names)

    return workflows, errors


def _load_yaml_workflows(yaml_path, source_name, workflows, errors, seen_names):
    """从单个 YAML 文件加载 workflows，追加到 workflows 列表

    如果 workflow name 已在 seen_names 中出现，覆盖之前的定义。
    """
    try:
        data = yaml.safe_load(open(yaml_path, encoding='utf-8'))
    except Exception as e:
        errors.append(f"{source_name}: YAML 解析失败: {e}")
        return
    if not data or not isinstance(data, dict):
        return

    wfs = data.get('workflows')
    if wfs is None:
        return

    wf_list = []
    if isinstance(wfs, list):
        for wf in wfs:
            if isinstance(wf, dict) and 'name' in wf:
                wf_list.append(wf)
            else:
                errors.append(f"{source_name}: workflow 缺少 name 字段")
    elif isinstance(wfs, dict):
        for name, wf in wfs.items():
            if isinstance(wf, dict):
                wf['name'] = name
                wf_list.append(wf)
    else:
        errors.append(f"{source_name}: workflows 格式错误 (expected list or dict)")
        return

    for wf in wf_list:
        name = wf.get('name', '')
        if name in seen_names:
            # 同名覆盖：替换之前的定义
            idx = seen_names[name]
            workflows[idx] = (source_name, wf)
        else:
            seen_names[name] = len(workflows)
            workflows.append((source_name, wf))


# ============================================================================
# 定位器解析
# ============================================================================

def resolve_locator(loc_str, workflow):
    """将 ${locators.xxx} 引用替换为实际定位器值

    同时处理:
      - ${locators.xxx} → 从 workflow.locators 查找并内联
      - {param_name}   → 保留为 Python f-string 插值
      - ${other_var}   → 转为 Python f-string 变量引用 {other_var}
    """
    if not isinstance(loc_str, str):
        return loc_str

    locators = workflow.get('locators', {})

    def replace_locator_ref(m):
        var_path = m.group(1)
        if var_path.startswith('locators.'):
            key = var_path[len('locators.'):]
            value = locators.get(key, '')
            if isinstance(value, str):
                return value
        # 非 locator 引用 → 转为运行时变量（f-string 插值）
        return '{' + var_path + '}'

    return re.sub(r'\$\{([^}]+)\}', replace_locator_ref, loc_str)


def to_fstring(value):
    """将值转为 Python f-string 或普通字符串字面量

    始终转义内部的单引号（XPath 中常含单引号）。
    如果值包含 {xxx} 占位符，生成 f'...' 格式。
    """
    s = str(value).replace("'", "\\'")
    if '{' in s:
        return f"f'{s}'"
    return f"'{s}'"


def py_str(value):
    """将值转为 Python 字符串字面量"""
    return f"'{str(value).replace(chr(39), chr(92)+chr(39))}'"


# ============================================================================
# Pre-flight 校验 + 自动修复（编译前运行）
# ============================================================================

# 编译器支持的 keyword 集合（compile_step 的 dispatch 表）
_COMPILER_KEYWORDS = {
    'click_element', 'fill_value', 'wait_for_time',
    'get_element_count', 'get_text', 'if_variable',
    'if_element_visible', 'if_element_hidden',
    'log',
}

# 引擎 L0/L1 关键字（从 validate_03 同步 — 用于 R3.5.3 校验）
_ENGINE_KEYWORDS = {
    'open_url', 'refresh', 'go_back', 'go_forward', 'scroll_to_height',
    'scroll_to_element', 'execute_script', 'save_page_img', 'download_file',
    'accept_dialog', 'dismiss_dialog', 'get_page_title', 'get_page_url',
    'set_viewport_size', 'set_cookie',
    'click_element', 'fill_value', 'type_text', 'hover', 'focus_element',
    'double_click', 'long_click', 'right_click', 'drag_and_drop',
    'check', 'uncheck', 'set_checked', 'clear', 'select_option',
    'select_multiple_options', 'click_select_option', 'upload_file',
    'highlight_element',
    'get_text', 'get_attribute', 'get_input_value', 'get_element_count',
    'is_visible', 'is_hidden', 'is_enabled', 'is_disabled', 'is_checked',
    'frame_fill_value', 'frame_click_element', 'frame_hover',
    'frame_focus_element', 'frame_select_option', 'frame_type_value',
    'frame_long_click_element', 'frame_drag_and_drop',
    'switch_to_frame', 'switch_to_main_frame',
    'frame_except_to_be_visible', 'frame_except_to_be_hidden',
    'frame_except_to_have_text',
    'except_to_be_visible', 'except_to_be_hidden', 'except_to_have_text',
    'except_to_have_value', 'except_to_have_attribute',
    'except_element_count', 'except_to_be_enabled', 'except_to_be_disabled',
    'except_to_be_checked', 'except_to_be_unchecked',
    'except_screenshot', 'except_to_contain_text',
    'if_element_visible', 'if_element_hidden', 'if_element_enabled',
    'if_variable', 'wait_for_time', 'wait_for_element_visible',
    'wait_for_element_hidden', 'wait_for_element_enabled',
    'wait_for_element', 'wait_for_url_contains', 'wait_for_request',
    'wait_for_load', 'wait_for_network',
    'open_browser', 'close_browser', 'inject_local_storage',
    'inject_token_header', 'log',
}


def _fuzzy_match(target, candidates, threshold=0.85):
    """模糊匹配，返回 (best_match, ratio) 或 (None, 0)"""
    from difflib import SequenceMatcher
    best, best_ratio = None, 0
    for c in candidates:
        ratio = SequenceMatcher(None, target, c).ratio()
        if ratio > best_ratio:
            best, best_ratio = c, ratio
    if best_ratio >= threshold:
        return best, best_ratio
    return None, 0


def _iter_steps_mut(steps):
    """递归遍历 steps（含 then_steps/else_steps），yield (step_dict, parent_list, index)"""
    if not isinstance(steps, list):
        return
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        yield step, steps, i
        params = step.get('params', {})
        if isinstance(params, dict):
            for sub_key in ('then_steps', 'else_steps'):
                yield from _iter_steps_mut(params.get(sub_key, []))


def preflight_check(workflows, project_dir, no_fix=False):
    """Pre-flight 校验：编译前检测并自动修复可修复的问题

    检查项：
      R3.5.3: step keyword 不在已知集合中 → 模糊匹配自动修正
      R3.5.8: ${locators.xxx} 引用的 key 不存在 → 模糊匹配自动修正

    Args:
        workflows: [(source_file, workflow_dict), ...]
        project_dir: 项目根目录（用于回写 YAML）
        no_fix: 如果为 True，仅报告问题不回写文件

    Returns:
        (fix_count: int, block_errors: list[str])
    """
    all_valid_keywords = _ENGINE_KEYWORDS | _COMPILER_KEYWORDS
    # 加上所有已知 L3 名称（互相引用）
    l3_names = {wf.get('name', '') for _, wf in workflows if wf.get('name')}
    all_valid_keywords |= l3_names

    fix_count = 0
    block_errors = []
    # 收集需要回写的文件: {filepath: workflow_list_for_that_file}
    dirty_files = {}

    for source, wf in workflows:
        # 只修复项目级文件（_knowledge/*.yaml）
        is_project_level = source.startswith('_knowledge/')
        if not is_project_level:
            continue

        wf_name = wf.get('name', '?')

        # ── R3.5.2b: name 合法 Python 标识符检查 ──
        if wf_name and wf_name != '?' and not wf_name.isidentifier():
            fixed_name = wf_name.replace('-', '_').replace(' ', '_')
            fixed_name = re.sub(r'[^\w]', '', fixed_name)
            if fixed_name and fixed_name.isidentifier():
                print(f"  [FIX] {source}: workflow name '{wf_name}' → '{fixed_name}'")
                # 更新 keyword 集合: 移除旧名，添加新名
                all_valid_keywords.discard(wf_name)
                all_valid_keywords.add(fixed_name)
                wf['name'] = fixed_name
                wf_name = fixed_name
                fix_count += 1
            else:
                block_errors.append(
                    f"[R3.5.2] {source}: workflow name '{wf_name}' 无法转为合法 Python 标识符"
                )
                continue

        prev_fix_count = fix_count  # 用于精确标记 dirty
        locators = wf.get('locators', {})
        locator_keys = set(locators.keys()) if isinstance(locators, dict) else set()

        for step, _parent, _idx in _iter_steps_mut(wf.get('steps', [])):
            kw = step.get('keyword', '')

            # ── R3.5.3: keyword 合法性 ──
            if kw and kw not in all_valid_keywords:
                fix, ratio = _fuzzy_match(kw, all_valid_keywords)
                if fix:
                    print(f"  [FIX] {source}/{wf_name}: keyword '{kw}' → '{fix}' "
                          f"(相似度 {ratio:.0%})")
                    step['keyword'] = fix
                    fix_count += 1
                else:
                    block_errors.append(
                        f"[R3.5.3] {source}/{wf_name}: keyword '{kw}' 无法匹配任何已知关键字"
                    )

            # ── R3.5.8: locator 引用合法性 ──
            params = step.get('params', {})
            if isinstance(params, dict):
                for pk, pv in params.items():
                    if not isinstance(pv, str):
                        continue
                    # 查找 ${locators.xxx} 引用
                    for m in re.finditer(r'\$\{locators\.([^}]+)\}', pv):
                        ref_key = m.group(1)
                        if ref_key not in locator_keys:
                            if locator_keys:
                                fix, ratio = _fuzzy_match(ref_key, locator_keys)
                                if fix:
                                    old_ref = f'${{locators.{ref_key}}}'
                                    new_ref = f'${{locators.{fix}}}'
                                    params[pk] = pv.replace(old_ref, new_ref)
                                    print(f"  [FIX] {source}/{wf_name}: "
                                          f"locator ref '{ref_key}' → '{fix}' "
                                          f"(相似度 {ratio:.0%})")
                                    fix_count += 1
                                    continue
                            block_errors.append(
                                f"[R3.5.8] {source}/{wf_name}: "
                                f"${{locators.{ref_key}}} 引用不存在"
                                f"（可用: {', '.join(sorted(locator_keys)) or '无'}）"
                            )

        # 精确标记: 仅当本 workflow 有修复时才标记 dirty
        if fix_count > prev_fix_count:
            filepath = os.path.join(project_dir, source)
            if filepath not in dirty_files:
                dirty_files[filepath] = set()
            dirty_files[filepath].add(id(wf))

    # 回写修正后的 YAML（写入该文件的全部 workflow，防止丢失）
    if not no_fix:
        for filepath, wf_ids in dirty_files.items():
            if os.path.isfile(filepath):
                try:
                    source_rel = os.path.relpath(filepath, project_dir).replace('\\', '/')
                    # 收集该文件的全部 workflow
                    file_wfs = [wf for src, wf in workflows
                                if os.path.abspath(os.path.join(project_dir, src))
                                   == os.path.abspath(filepath)]
                    _write_back_all_workflows(filepath, file_wfs)
                    print(f"  [WRITEBACK] {source_rel}: 已回写 {len(file_wfs)} 个 workflow")
                except Exception as e:
                    block_errors.append(f"[WRITEBACK] {filepath}: 回写失败: {e}")
    elif dirty_files:
        print(f"  [INFO] --no-fix 模式，跳过 {len(dirty_files)} 个文件的回写")

    return fix_count, block_errors


def _write_back_all_workflows(filepath, wf_list):
    """将修正后的全部 workflow 回写到 YAML 文件

    保留文件中的其他顶层字段，仅替换 workflows 部分。
    wf_list: 该文件中所有 workflow 的列表（含修正和未修正的）。
    """
    with open(filepath, encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        data = {}

    data['workflows'] = [dict(wf) for wf in wf_list]

    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)




def compile_step(step, workflow, indent):
    """将单个 workflow step 编译为 Python 代码行列表

    Args:
        step: workflow step dict
        workflow: 父 workflow dict (用于 locator 查找)
        indent: 缩进空格数
    Returns:
        list of str (Python 代码行，不含缩进前缀)
    """
    keyword = step.get('keyword', '')
    params = step.get('params', {})
    desc = step.get('desc', '')
    tolerant = step.get('tolerant', False)

    # ── 自动 tolerant 规则 ──
    # 防御性等待步骤默认 tolerant，避免因元素不存在或超时而阻断流程
    # 这些步骤的语义是"如果元素存在就等待它消失/完成"，不存在或超时不应阻断
    # 仅在用户未显式设置 tolerant 字段时生效（'tolerant' not in step）
    # 显式 tolerant: false 仍可覆盖（向后兼容）
    AUTO_TOLERANT_KEYWORDS = {
        'wait_for_element_hidden',  # 等待元素消失（可能不存在或持续可见，如 loading 元素）
        'wait_for_load',            # 页面加载等待（可能已完成）
        'wait_for_network',         # 网络空闲等待（可能无请求或 SPA 长连接永不 idle）
    }

    if 'tolerant' not in step and keyword in AUTO_TOLERANT_KEYWORDS:
        tolerant = True

    if keyword == 'click_element':
        lines = _compile_click(desc, params, workflow, indent)
    elif keyword == 'fill_value':
        lines = _compile_fill(desc, params, workflow, indent)
    elif keyword == 'wait_for_time':
        lines = _compile_wait(desc, params, indent)
    elif keyword == 'get_element_count':
        lines = _compile_count(desc, params, workflow, indent)
    elif keyword == 'get_text':
        lines = _compile_get_text(desc, params, workflow, indent)
    elif keyword == 'if_variable':
        # Merge step-level fields (condition, then_steps, else_steps) into params
        merged_params = dict(params) if params else {}
        for field in ('condition', 'name', 'operator', 'compare_value',
                       'then_steps', 'else_steps'):
            if field in step and field not in merged_params:
                merged_params[field] = step[field]
        lines = _compile_if_var(desc, merged_params, workflow, indent)
    elif keyword in ('if_element_visible', 'if_element_hidden'):
        lines = _compile_if_element(keyword, desc, params, workflow, indent)
    elif keyword == 'log':
        lines = _compile_log(params, indent)
    else:
        # 默认: self.perform({...}) 通用处理
        lines = _compile_perform(desc, keyword, params, workflow, indent)

    # tolerant: true → 包裹 try/except，超时或异常不阻断
    if tolerant:
        wrapped = [
            f"{_sp(indent)}try:",
        ]
        # 内部行增加 4 空格缩进
        for line in lines:
            if line.strip():
                wrapped.append('    ' + line)
            else:
                wrapped.append(line)
        wrapped.append(f"{_sp(indent)}except Exception as _e:")
        wrapped.append(f"{_sp(indent+4)}self.log.debug_log(f'[L3] tolerant skip: {desc} — {{_e}}')")
        wrapped.append(f"{_sp(indent+4)}if hasattr(self, 'tree_builder') and self.tree_builder:")
        wrapped.append(f"{_sp(indent+8)}self.tree_builder.tolerate_last_error()")
        return wrapped

    return lines


def _sp(indent):
    """生成缩进空格"""
    return ' ' * indent


def _compile_click(desc, params, wf, indent):
    loc = resolve_locator(params.get('locator', ''), wf)
    return [
        f"{_sp(indent)}# {desc}",
        f"{_sp(indent)}self.perform({{",
        f"{_sp(indent+4)}'desc': {py_str(desc)},",
        f"{_sp(indent+4)}'keyword': 'click_element',",
        f"{_sp(indent+4)}'params': {{'locator': {to_fstring(loc)}}}",
        f"{_sp(indent)}}})",
    ]


def _compile_fill(desc, params, wf, indent):
    loc = resolve_locator(params.get('locator', ''), wf)
    val = params.get('value', '')
    val_expr = to_fstring(val) if isinstance(val, str) else str(val)
    return [
        f"{_sp(indent)}# {desc}",
        f"{_sp(indent)}self.perform({{",
        f"{_sp(indent+4)}'desc': {py_str(desc)},",
        f"{_sp(indent+4)}'keyword': 'fill_value',",
        f"{_sp(indent+4)}'params': {{'locator': {to_fstring(loc)}, 'value': {val_expr}}}",
        f"{_sp(indent)}}})",
    ]


def _compile_wait(desc, params, indent):
    timeout = params.get('timeout', 1000)
    return [
        f"{_sp(indent)}# {desc}",
        f"{_sp(indent)}self.perform({{",
        f"{_sp(indent+4)}'desc': {py_str(desc)},",
        f"{_sp(indent+4)}'keyword': 'wait_for_time',",
        f"{_sp(indent+4)}'params': {{'timeout': {timeout}}}",
        f"{_sp(indent)}}})",
    ]


def _compile_count(desc, params, wf, indent):
    loc = resolve_locator(params.get('locator', ''), wf)
    store_as = params.get('variable') or params.get('store_as', '_count')
    return [
        f"{_sp(indent)}# {desc}",
        f"{_sp(indent)}{store_as} = self.page.locator({to_fstring(loc)}).count()",
        f"{_sp(indent)}self.log.debug_log(f'[L3] {store_as}={{{store_as}}}')",
    ]


def _compile_get_text(desc, params, wf, indent):
    loc = resolve_locator(params.get('locator', ''), wf)
    store_as = params.get('variable') or params.get('store_as', '_text')
    return [
        f"{_sp(indent)}# {desc}",
        f"{_sp(indent)}{store_as} = self.page.locator({to_fstring(loc)}).first.text_content() or ''",
        f"{_sp(indent)}{store_as} = {store_as}.strip()",
        f"{_sp(indent)}self.log.debug_log(f'[L3] {store_as}={{{store_as}}}')",
    ]


def _compile_log(params, indent):
    msg = params.get('message', '')
    return [
        f"{_sp(indent)}# 日志",
        f"{_sp(indent)}self.log.debug_log({py_str('[L3] ' + msg)})",
    ]


def _compile_perform(desc, keyword, params, wf, indent):
    """通用 self.perform() 编译 — 适用于 except_to_be_visible 等标准关键字"""
    # 构建 params dict 字面量
    param_parts = []
    for k, v in params.items():
        if k in ('then_steps', 'else_steps'):
            continue
        if isinstance(v, str):
            resolved = resolve_locator(v, wf)
            param_parts.append(f"'{k}': {to_fstring(resolved)}")
        else:
            param_parts.append(f"'{k}': {repr(v)}")

    params_str = '{' + ', '.join(param_parts) + '}'

    return [
        f"{_sp(indent)}# {desc}",
        f"{_sp(indent)}self.perform({{",
        f"{_sp(indent+4)}'desc': {py_str(desc)},",
        f"{_sp(indent+4)}'keyword': {py_str(keyword)},",
        f"{_sp(indent+4)}'params': {params_str}",
        f"{_sp(indent)}}})",
    ]


# ============================================================================
# if_variable 条件编译
# ============================================================================

_OP_MAP = {
    'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=',
    'eq': '==', 'neq': '!=',
}


def _compile_if_var(desc, params, wf, indent):
    then_steps = params.get('then_steps', [])
    else_steps = params.get('else_steps', [])

    # Support two formats:
    #   1. condition string: "variable_name > 0"  (YAML format)
    #   2. structured fields: name + operator + compare_value  (programmatic format)
    condition_str = params.get('condition', '')
    if condition_str:
        # Parse "variable_name >=|<=|!=|==|>|< value"
        import re as _re
        m = _re.match(r'(\w+)\s*(>=|<=|!=|==|>|<)\s*(.+)', condition_str.strip())
        if m:
            name, op, compare_value = m.group(1), m.group(2), m.group(3).strip()
        else:
            # Fallback: treat entire condition as-is
            name, op, compare_value = condition_str, '', ''
    else:
        name = params.get('name', '')
        operator = params.get('operator', 'gt')
        compare_value = params.get('compare_value', '0')
        op = _OP_MAP.get(operator, '>')

    lines = [f"{_sp(indent)}# {desc}"]

    # Generate condition expression
    if op:
        try:
            int(compare_value)
            cond = f"{name} {op} {compare_value}"
        except (ValueError, TypeError):
            cond = f"{name} {op} {py_str(compare_value)}"
    else:
        cond = name  # raw condition string

    lines.append(f"{_sp(indent)}if {cond}:")

    if then_steps:
        for sub in then_steps:
            lines.extend(compile_step(sub, wf, indent + 4))
    else:
        lines.append(f"{_sp(indent+4)}pass")

    if else_steps:
        lines.append(f"{_sp(indent)}else:")
        for sub in else_steps:
            lines.extend(compile_step(sub, wf, indent + 4))

    return lines


def _compile_if_element(keyword, desc, params, wf, indent):
    """编译 if_element_visible / if_element_hidden 为内联 Python 条件语句

    与 _compile_if_var 对称：直接生成 Python if/else，递归编译 then/else 步骤。
    不走 self.perform() 分派，避免 then_steps/else_steps 被丢弃。
    """
    loc = resolve_locator(params.get('locator', ''), wf)
    timeout = params.get('timeout', 3000)
    then_steps = params.get('then_steps', [])
    else_steps = params.get('else_steps', [])

    # visible 检查 vs hidden 检查：条件取反
    condition = 'visible' if keyword == 'if_element_visible' else 'not visible'

    lines = [f"{_sp(indent)}# {desc}"]
    lines.append(f"{_sp(indent)}try:")
    lines.append(f"{_sp(indent+4)}visible = self.page.locator({to_fstring(loc)}).first.is_visible(timeout={timeout})")
    lines.append(f"{_sp(indent)}except Exception:")
    lines.append(f"{_sp(indent+4)}visible = False")
    lines.append(f"{_sp(indent)}if {condition}:")

    if then_steps:
        for sub in then_steps:
            lines.extend(compile_step(sub, wf, indent + 4))
    else:
        lines.append(f"{_sp(indent+4)}pass")

    if else_steps:
        lines.append(f"{_sp(indent)}else:")
        for sub in else_steps:
            lines.extend(compile_step(sub, wf, indent + 4))

    return lines


# ============================================================================
# 模块生成
# ============================================================================

def generate_module(workflows_with_sources, project_dir):
    """从编译后的 workflows 生成完整的 Python 模块代码

    Args:
        workflows_with_sources: [(source_file, workflow_dict), ...]
        project_dir: 项目名称（写入 docstring）
    Returns:
        (module_code: str, errors: list[str])
    """
    errors = []
    functions = []
    project_name = os.path.basename(os.path.abspath(project_dir))
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    skill_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # generate-ui-test/

    needs_datetime = False

    for source, wf in workflows_with_sources:
        name = wf.get('name', '')
        if not name:
            errors.append(f"{source}: workflow 缺少 name")
            continue

        # ── 特殊编译: set_random_variable（含 datetime.now() 运行时调用）──
        if name == 'set_random_variable':
            needs_datetime = True
            functions.append({
                'name': 'set_random_variable',
                'chinese_name': wf.get('chinese_name', '生成随机变量'),
                'params_str': 'name, prefix',
                'description': wf.get('description', ''),
                'source': source,
                'code': (
                    "    self.log.debug_log(f'[L3] set_random_variable: "
                    "name={name}, prefix={prefix}')\n"
                    "    _gen_value = f'{prefix}' + "
                    "datetime.now().strftime('%Y%m%d%H%M%S')\n"
                    "    self.config.setdefault('runtime_variables', "
                    "{})[name] = _gen_value\n"
                    "    self.log.debug_log(f'[L3] 随机变量: "
                    "{name}={_gen_value}')"
                ),
            })
            continue

        params_list = wf.get('params', [])
        if isinstance(params_list, str):
            params_list = [params_list]
        params_str = ', '.join(params_list) if params_list else ''

        description = wf.get('description', '')
        steps = wf.get('steps', [])

        # 编译所有步骤
        code_lines = []
        code_lines.append(f"    self.log.debug_log(f'[L3] {name}: "
                          f"{', '.join(p + '=' + '{' + p + '}' for p in params_list)}')")

        for step in steps:
            code_lines.extend(compile_step(step, wf, 4))

        func_code = '\n'.join(code_lines)

        functions.append({
            'name': name,
            'chinese_name': wf.get('chinese_name', name),
            'params_str': params_str,
            'description': description,
            'source': source,
            'code': func_code,
        })

    # 组装模块
    module_lines = []
    module_lines.append(f'"""{project_name} 模块复合关键字（L3）')
    module_lines.append('')
    module_lines.append(f'由 lib/system_workflows.yaml + _knowledge/*.yaml 编译 — 请勿手动修改')
    module_lines.append(f'生成时间: {timestamp}')
    module_lines.append('')
    module_lines.append('修改请编辑对应 YAML 后重新运行:')
    module_lines.append(f'  python {os.path.join(skill_dir, "tools", "compile_module_keywords.py")} {project_name}')
    module_lines.append('"""')
    module_lines.append('from UIEngine.core.keyword_manager import KeyWordManager')
    module_lines.append('from UIEngine.basecase import BaseCase')
    if needs_datetime:
        module_lines.append('from datetime import datetime')
    module_lines.append('')

    for func in functions:
        module_lines.append('')
        module_lines.append(f"def {func['name']}(self, {func['params_str']}):")
        module_lines.append(f'    """{func["description"]}')
        module_lines.append('')
        module_lines.append(f"    来源: {func['source']}")
        module_lines.append('    """')
        module_lines.append(func['code'])
        module_lines.append('')

    # register_module_keywords()
    module_lines.append('')
    module_lines.append('def register_module_keywords():')
    module_lines.append('    """注册所有 L3 模块复合关键字"""')
    module_lines.append('    keywords = [')
    for func in functions:
        module_lines.append(
            f"        ({func['name']}, ['{func['name']}', '{func['chinese_name']}']),"
        )
    module_lines.append('    ]')
    module_lines.append('    for func, names in keywords:')
    module_lines.append('        setattr(BaseCase, func.__name__, func)')
    module_lines.append('        for name in names:')
    module_lines.append('            KeyWordManager.maps[name] = func')
    module_lines.append('')

    return '\n'.join(module_lines), errors


def generate_empty_module(project_dir):
    """生成空的 module_keywords.py（_knowledge/ 为空时）"""
    project_name = os.path.basename(os.path.abspath(project_dir))
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    return '\n'.join([
        f'"""{project_name} 模块复合关键字（L3）— 空模块',
        '',
        f'生成时间: {timestamp}',
        '_knowledge/ 为空，无 L3 复合关键字。',
        '"""',
        '',
        '',
        'def register_module_keywords():',
        '    """无 L3 模块关键字需要注册"""',
        '    pass',
        '',
    ])


# ============================================================================
# CLI
# ============================================================================

def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description="L3 模块复合关键字编译器 — 从 _knowledge/*.yaml 编译为 lib/module_keywords.py"
    )
    parser.add_argument('project_dir', help="项目根目录路径")
    parser.add_argument('--dry-run', action='store_true',
                        help="只打印编译结果，不写入文件")
    parser.add_argument('--no-fix', action='store_true',
                        help="禁用 pre-flight 自动修复（仅报告问题）")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    # 加载 workflows
    workflows, load_errors = load_workflows(project_dir)

    if load_errors:
        for e in load_errors:
            print(f"[ERROR] {e}", file=sys.stderr)

    if not workflows:
        # 系统级 + 项目级均为空 → 检查 system_workflows.yaml 是否可达
        skill_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys_path = os.path.join(skill_dir, 'lib', 'system_workflows.yaml')
        if os.path.isfile(sys_path):
            print(f"[WARN] system_workflows.yaml 存在 ({sys_path}) 但未加载，请检查文件格式")
        else:
            print(f"[INFO] system_workflows.yaml 不存在: {sys_path}")
        print("[INFO] 系统级和项目级 workflow 均为空，生成空 module_keywords.py")
        module_code = generate_empty_module(project_dir)
        if args.dry_run:
            print(module_code)
        else:
            lib_dir = os.path.join(project_dir, 'lib')
            os.makedirs(lib_dir, exist_ok=True)
            with open(os.path.join(lib_dir, 'module_keywords.py'), 'w', encoding='utf-8') as f:
                f.write(module_code)
            print(f"[OK] 已生成: lib/module_keywords.py (空模块)")
        sys.exit(0)

    # 编译
    print(f"[INFO] 发现 {len(workflows)} 个 workflow:")
    for source, wf in workflows:
        name = wf.get('name', '?')
        cn = wf.get('chinese_name', '')
        print(f"  - {name} ({cn}) ← {source}")

    # Pre-flight 校验 + 自动修复（编译前）
    print(f"\n[PRE-FLIGHT] 校验 workflow 定义...")
    fix_count, block_errors = preflight_check(workflows, project_dir,
                                               no_fix=args.no_fix)
    if fix_count > 0:
        print(f"[PRE-FLIGHT] 自动修复 {fix_count} 处问题")
    if block_errors:
        for e in block_errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        print(f"[PRE-FLIGHT] {len(block_errors)} 个无法自动修复的错误，编译中止")
        sys.exit(1)
    if fix_count == 0:
        print(f"[PRE-FLIGHT] 全部通过")

    # 如果 preflight 做了回写，需要重新加载 workflows
    if fix_count > 0 and not args.dry_run:
        workflows, load_errors = load_workflows(project_dir)
        if load_errors:
            for e in load_errors:
                print(f"[ERROR] {e}", file=sys.stderr)

    module_code, compile_errors = generate_module(workflows, project_dir)

    if compile_errors:
        for e in compile_errors:
            print(f"[ERROR] {e}", file=sys.stderr)

    if args.dry_run:
        print("\n--- 编译产物 ---")
        print(module_code)
    else:
        lib_dir = os.path.join(project_dir, 'lib')
        os.makedirs(lib_dir, exist_ok=True)
        output = os.path.join(lib_dir, 'module_keywords.py')
        with open(output, 'w', encoding='utf-8') as f:
            f.write(module_code)
        print(f"\n[OK] 已生成: lib/module_keywords.py ({len(workflows)} 个关键字)")

    sys.exit(1 if (load_errors or compile_errors) else 0)


if __name__ == '__main__':
    main()
