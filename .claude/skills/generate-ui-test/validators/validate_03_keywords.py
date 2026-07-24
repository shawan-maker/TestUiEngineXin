#!/usr/bin/env python3
"""
Phase 3: 模块关键字编译验证器 (validate_03_keywords.py)

检查 _knowledge/*.yaml → lib/module_keywords.py 编译链路的完整性。

规则:
  R3.5.1  _knowledge/*.yaml 是合法 YAML
  R3.5.2  每个 workflow 有必需字段: name, steps
  R3.5.3  每个 workflow step 引用的 keyword 合法（ERROR，pre-flight 应已自动修复）
  R3.5.4  lib/module_keywords.py 存在（当有 workflows 时）
  R3.5.5  lib/module_keywords.py 语法正确
  R3.5.6  register_module_keywords() 函数存在
  R3.5.7  所有 workflow name 在 module_keywords.py 中有对应函数
  R3.5.8  ${locators.xxx} 引用的 key 存在于 workflow 的 locators 块中

向后兼容: _knowledge/ 不存在或为空时退出 0。

用法:
    python validate_03_keywords.py <project_dir>

退出码: 0 = 通过, 1 = 有 error
"""
import argparse
import ast
import glob
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("[FATAL] 需要 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# L0/L1 引擎内置关键字（用于 R3.5.3 校验 workflow 内部步骤）
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
    'open_browser', 'close_browser', 'inject_local_storage',
    'inject_token_header', 'log',
}


def main():
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description="Phase 3 模块关键字编译验证器"
    )
    parser.add_argument('project_dir', help="项目根目录路径")
    args = parser.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    if not os.path.isdir(project_dir):
        print(f"[FATAL] 目录不存在: {project_dir}", file=sys.stderr)
        sys.exit(2)

    knowledge_dir = os.path.join(project_dir, '_knowledge')
    errors = []
    warnings = []

    # ── 检查系统级 + 项目级 workflow 源文件 ──
    _sys_wf_path = os.path.join(project_dir, 'lib', 'system_workflows.yaml')
    has_system_wf = os.path.isfile(_sys_wf_path)

    if not os.path.isdir(knowledge_dir) and not has_system_wf:
        print("[INFO] _knowledge/ 和 system_workflows.yaml 均不存在，跳过 L3 验证")
        sys.exit(0)

    # ── 统一阶段门禁：检查 Phase 6 前置（十一） ──
    _sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _sys_path not in sys.path:
        sys.path.insert(0, _sys_path)
    try:
        from tools._phase_registry import check_prerequisite_phases
        prereq_violations = check_prerequisite_phases(project_dir, 'validate_03')
        for pv in prereq_violations:
            errors.append(f"[PREREQUISITE] {pv.message} → {pv.suggestion}")
    except ImportError:
        pass  # _phase_registry.py 不存在时静默跳过

    yaml_files = sorted(glob.glob(os.path.join(knowledge_dir, "*.yaml")))
    # 追加系统级 workflow 校验（R3.5.1-R3.5.3 + R3.5.8）
    if has_system_wf:
        yaml_files = [_sys_wf_path] + yaml_files
    if not yaml_files:
        print("[INFO] 无 workflow 源文件，跳过 L3 验证")
        sys.exit(0)

    all_workflows = []  # [(source_file, wf_dict), ...]

    for f in yaml_files:
        # 系统级用相对路径，项目级用文件名
        if f == _sys_wf_path:
            source = 'lib/system_workflows.yaml'
        else:
            source = os.path.basename(f)

        # R3.5.1: 合法 YAML
        try:
            data = yaml.safe_load(open(f, encoding='utf-8'))
        except yaml.YAMLError as e:
            errors.append(f"[R3.5.1] {source}: YAML 解析失败: {e}")
            continue

        if not data or not isinstance(data, dict):
            continue

        raw_wfs = data.get('workflows')
        if raw_wfs is None:
            continue

        # 规范化为 list
        wf_list = []
        if isinstance(raw_wfs, list):
            wf_list = raw_wfs
        elif isinstance(raw_wfs, dict):
            for name, wf in raw_wfs.items():
                if isinstance(wf, dict):
                    wf['name'] = name
                    wf_list.append(wf)

        for wf in wf_list:
            if not isinstance(wf, dict):
                errors.append(f"[R3.5.2] {source}: workflow 不是 dict")
                continue
            all_workflows.append((source, wf))

    # R3.5.2: 必需字段 + R3.5.2b 标识符合法性
    for source, wf in all_workflows:
        name = wf.get('name', '')
        if not name:
            errors.append(f"[R3.5.2] {source}: workflow 缺少 name 字段")
            continue
        if not name.isidentifier():
            errors.append(
                f"[R3.5.2] {source}: workflow name '{name}' 不是合法 Python 标识符"
                f"（不能包含连字符、空格等）。请修正后重新编译。"
            )
        steps = wf.get('steps')
        if not steps or not isinstance(steps, list):
            errors.append(f"[R3.5.2] {source}/{name}: 缺少 steps 字段或 steps 为空")

    # R3.5.3: step keyword 合法性（升级为 ERROR — pre-flight 应已自动修复）
    known_l3_names = {wf.get('name', '') for _, wf in all_workflows}
    all_valid = _ENGINE_KEYWORDS | known_l3_names

    for source, wf in all_workflows:
        name = wf.get('name', '')
        for step in _iter_steps(wf.get('steps', [])):
            kw = step.get('keyword', '')
            if kw and kw not in all_valid:
                errors.append(
                    f"[R3.5.3] {source}/{name}: step keyword '{kw}' 未在 "
                    f"ENGINE_KEYWORDS 或已知 L3 关键字中注册。"
                    f"请重新编译: python tools/compile_module_keywords.py {os.path.basename(project_dir)}"
                )

    # R3.5.8: ${locators.xxx} 引用合法性
    import re as _re
    for source, wf in all_workflows:
        name = wf.get('name', '')
        locators = wf.get('locators', {})
        locator_keys = set(locators.keys()) if isinstance(locators, dict) else set()

        for step in _iter_steps(wf.get('steps', [])):
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            for pk, pv in params.items():
                if not isinstance(pv, str):
                    continue
                for m in _re.finditer(r'\$\{locators\.([^}]+)\}', pv):
                    ref_key = m.group(1)
                    if locator_keys and ref_key not in locator_keys:
                        errors.append(
                            f"[R3.5.8] {source}/{name}: "
                            f"${{locators.{ref_key}}} 引用不存在"
                            f"（可用: {', '.join(sorted(locator_keys))}）"
                        )

    # R3.5.4: module_keywords.py 存在
    mk_path = os.path.join(project_dir, 'lib', 'module_keywords.py')
    if all_workflows:
        if not os.path.isfile(mk_path):
            errors.append(
                f"[R3.5.4] lib/module_keywords.py 不存在。"
                f"_knowledge/ 中有 {len(all_workflows)} 个 workflow 但未编译。"
                f"请运行: python tools/compile_module_keywords.py {os.path.basename(project_dir)}"
            )

    if not os.path.isfile(mk_path):
        # 无编译产物，后续检查跳过
        _report(errors, warnings, project_dir)
        sys.exit(1 if errors else 0)

    # R3.5.5: 语法正确
    try:
        source_code = open(mk_path, encoding='utf-8').read()
        tree = ast.parse(source_code)
    except SyntaxError as e:
        errors.append(f"[R3.5.5] lib/module_keywords.py 语法错误: 行 {e.lineno}: {e.msg}")
        _report(errors, warnings, project_dir)
        sys.exit(1)

    # R3.5.6: register_module_keywords() 函数存在
    func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    if 'register_module_keywords' not in func_names:
        errors.append(
            "[R3.5.6] lib/module_keywords.py 中缺少 register_module_keywords() 函数"
        )

    # R3.5.7: 所有 workflow name 有对应函数
    compiled_funcs = set(func_names)
    for source, wf in all_workflows:
        name = wf.get('name', '')
        if name and name not in compiled_funcs:
            errors.append(
                f"[R3.5.7] workflow '{name}' (来自 {source}) "
                f"在 lib/module_keywords.py 中没有对应的函数定义。请重新编译。"
            )

    _report(errors, warnings, project_dir)
    sys.exit(1 if errors else 0)


def _iter_steps(steps):
    """递归遍历 steps（含 then_steps/else_steps）"""
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        yield step
        params = step.get('params', {})
        if isinstance(params, dict):
            for sub_key in ('then_steps', 'else_steps'):
                yield from _iter_steps(params.get(sub_key, []))


def _report(errors, warnings, project_dir):
    """输出检查报告"""
    project_name = os.path.basename(project_dir)
    print(f"\n{'='*60}")
    print(f"Phase 3 模块关键字编译验证: {project_name}")
    print(f"{'='*60}")

    for w in warnings:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [ERROR] {e}")

    if not errors and not warnings:
        print("  [OK] 全部通过")
    else:
        print(f"\n  结果: {len(errors)} error(s), {len(warnings)} warning(s)")


if __name__ == '__main__':
    main()
