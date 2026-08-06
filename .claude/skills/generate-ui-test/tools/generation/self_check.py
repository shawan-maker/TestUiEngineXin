#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
self_check.py - 自检查层

从 _case_generator.py 提取的 SelfCheckLayer 类，负责验证生成的 case 是否符合规范。
包含所有 _SC_ 常量定义。
"""

import copy
import re


# ═══════════════════════════════════════════════════════════════
# SelfCheckLayer 常量定义
# ═══════════════════════════════════════════════════════════════

_SC_ENGINE_KEYWORDS = {
    'open_url', 'refresh', 'go_back', 'go_forward', 'execute_script',
    'scroll_to_height', 'scroll_to_element', 'open_browser',
    'download_file', 'save_page_img', 'set_viewport_size', 'set_cookie',
    'click_element', 'fill_value', 'type_text', 'hover', 'clear',
    'double_click', 'long_click', 'right_click', 'drag_and_drop',
    'check', 'uncheck', 'set_checked', 'select_option', 'upload_file',
    'click_select_option', 'select_multiple_options',
    'focus_element', 'highlight_element',
    'get_text', 'get_attribute', 'get_input_value', 'get_element_count',
    'is_visible', 'is_hidden', 'is_enabled', 'is_disabled', 'is_checked',
    'frame_fill_value', 'frame_click_element', 'frame_hover',
    'frame_except_to_be_visible', 'frame_except_to_be_hidden',
    'switch_to_frame', 'switch_to_main_frame',
    'except_to_be_visible', 'except_to_be_hidden', 'except_to_be_enabled',
    'except_to_be_disabled', 'except_to_be_checked', 'except_to_be_empty',
    'except_to_be_editable', 'except_to_be_focused',
    'except_to_have_text', 'except_to_have_value', 'except_to_have_attribute',
    'assert_page_title', 'assert_page_url',
    'wait_for_time', 'wait_for_element', 'wait_for_element_hidden',
    'wait_for_load', 'wait_for_network', 'wait_for_url', 'set_default_timeout',
    'set_variable', 'set_variable_from_element', 'if_element_visible',
    'if_variable', 'for_each', 'retry_until', 'goto_step', 'log',
    'inject_cookies', 'inject_token_header', 'inject_local_storage',
    'accept_dialog', 'dismiss_dialog', 'get_page_title', 'get_page_url',
    'frame_focus_element', 'frame_select_option', 'frame_type_value',
    'frame_long_click_element', 'frame_drag_and_drop',
    'mouse_click', 'move_mouse', 'mouse_down', 'mouse_up',
    'press_key', 'press_type',
    'set_random_variable', 'except_element_count',
}

_SC_KEYWORD_MISTAKES = {
    'assert_text': 'except_to_have_text',
    'assert_visible': 'except_to_be_visible',
    'assert_not_visible': 'except_to_be_hidden',
    'assert_contains': 'except_to_have_text',
    'verify_text': 'except_to_have_text',
    'check_element': 'except_to_be_visible',
    'click_text': 'click_element',
}

_SC_FORBIDDEN_PARAMS = {
    'except_to_be_visible': {'timeout', 'expect_results'},
    'except_to_be_hidden': {'timeout', 'expect_results'},
    'except_to_be_enabled': {'timeout', 'expect_results'},
    'except_to_be_disabled': {'timeout', 'expect_results'},
    'except_to_be_checked': {'timeout', 'expect_results'},
    'except_to_be_empty': {'timeout', 'expect_results'},
    'except_to_be_editable': {'timeout', 'expect_results'},
    'except_to_be_focused': {'timeout', 'expect_results'},
    'except_to_have_text': {'timeout'},
    'except_to_have_value': {'timeout'},
    'except_to_have_attribute': {'timeout'},
    'assert_page_title': {'timeout'},
    'assert_page_url': {'timeout'},
    'if_element_visible': {'then', 'else'},
    'if_variable': {'then', 'else'},
    'for_each': {'then_steps', 'then', 'else_steps', 'else'},
    'get_element_count': {'timeout'},
    'is_visible': {'timeout'},
    'is_hidden': {'timeout'},
}

_SC_WRONG_PARAM_MAP = {
    'expected': 'expect_results',
    'text': 'expect_results',
    'selector': 'locator',
    'wait_time': 'timeout',
    'time': 'timeout',
    'ms': 'timeout',
    'duration': 'timeout',
    'input': 'value',
    'code': 'script',
    'js': 'script',
    'iframe': 'frame',
    'variable': 'name',
    'condition': 'operator',
    'attribute': 'name',
    'then': 'then_steps',
    'else': 'else_steps',
}

_SC_FORBIDDEN_ASSERT_KW = {'except_to_have_text', 'except_to_have_value', 'except_to_have_attribute'}
_SC_VAR_REF_RE = re.compile(r'\$\{([^}]+)\}')
_SC_EXEMPT_VALUES = {'成功', '失败', '确定', '取消', '是', '否', ''}


# ═══════════════════════════════════════════════════════════════
# SelfCheckLayer 类
# ═══════════════════════════════════════════════════════════════

class SelfCheckLayer:
    """生成后自检层 — 在 case YAML 写入磁盘前执行"""

    def __init__(self, resolver, data_entries, data_group_name,
                 l3_keywords=None, module_name=''):
        self.resolver = resolver
        self.data_entries = data_entries
        self.data_group_name = data_group_name
        self.l3_keywords = l3_keywords or set()
        self.module_name = module_name
        self.repair_log = []
        self.remaining = []

    def run_all_checks(self, steps, case_id=''):
        steps = self._safe_repair(steps, self._repair_keywords, 'R4.13')
        steps = self._safe_repair(steps, self._repair_params, 'R4.14')
        steps = self._safe_repair(steps, self._repair_locator_format, 'R4.21')
        steps = self._safe_repair(steps, self._repair_forbidden_kw, 'R4.22')
        steps = self._safe_repair(steps, self._repair_env_isolation, 'R4.9')
        steps = self._safe_repair(steps, self._repair_var_format, 'R4.6')
        steps = self._safe_repair(steps, self._repair_hardcoded_values, 'R4.2')
        self.remaining = self._verify_all(steps, case_id)
        return steps, self.repair_log, self.remaining

    def _safe_repair(self, steps, repair_fn, rule_id):
        original = copy.deepcopy(steps)
        try:
            repaired = repair_fn(copy.deepcopy(steps))
            new_issues = self._verify_rule(repaired, rule_id)
            if len(new_issues) > len(self._verify_rule(original, rule_id)):
                self.repair_log.append({
                    'rule': rule_id, 'action': 'rollback',
                    'reason': f'修复后新增 {len(new_issues)} 个同规则问题',
                })
                return original
            return repaired
        except Exception as e:
            self.repair_log.append({
                'rule': rule_id, 'action': 'rollback',
                'reason': f'修复异常: {e}',
            })
            return original

    def _repair_keywords(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            if kw in _SC_KEYWORD_MISTAKES:
                old_kw = kw
                step['keyword'] = _SC_KEYWORD_MISTAKES[kw]
                self.repair_log.append({
                    'rule': 'R4.13',
                    'action': f'rename {old_kw} → {step["keyword"]}',
                    'guarantee': 'COMMON_KEYWORD_MISTAKES 静态映射',
                })
        return steps

    def _repair_params(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue

            for forbidden in _SC_FORBIDDEN_PARAMS.get(kw, set()):
                if forbidden in params:
                    del params[forbidden]
                    self.repair_log.append({
                        'rule': 'R4.14', 'action': f'delete forbidden: {forbidden}',
                        'guarantee': 'FORBIDDEN_PARAMS 静态表',
                    })

            for wrong, correct in _SC_WRONG_PARAM_MAP.items():
                if wrong in params:
                    params[correct] = params.pop(wrong)
                    self.repair_log.append({
                        'rule': 'R4.14', 'action': f'rename param {wrong} → {correct}',
                        'guarantee': 'WRONG_PARAM_MAP 静态映射',
                    })
        return steps

    def _repair_locator_format(self, steps):
        _CSS_PATTERNS = [
            (re.compile(r'^css=\.([a-zA-Z_-]+)'),
             lambda m: f"xpath=//*[contains(@class,'{m.group(1)}')]"),
            (re.compile(r'^css=#([a-zA-Z_-]+)'),
             lambda m: f"xpath=//*[@id='{m.group(1)}']"),
            (re.compile(r'^css=button:has-text\((.+?)\)'),
             lambda m: f"xpath=//button[contains(.,'{m.group(1)}')]"),
            (re.compile(r'^css=input\[placeholder=[\"\'](.+?)[\"\']\]'),
             lambda m: f"xpath=//input[@placeholder='{m.group(1)}']"),
        ]

        for step in steps:
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            locator = params.get('locator', '')
            if not isinstance(locator, str):
                continue

            if locator.startswith('css='):
                for pattern, replacer in _CSS_PATTERNS:
                    m = pattern.match(locator)
                    if m:
                        new_loc = replacer(m)
                        params['locator'] = new_loc
                        self.repair_log.append({
                            'rule': 'R4.21',
                            'action': f'CSS→XPath: {locator} → {new_loc}',
                            'guarantee': '常见 CSS 模式有确定 XPath 映射',
                        })
                        break
        return steps

    def _repair_forbidden_kw(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            if kw in _SC_FORBIDDEN_ASSERT_KW:
                params = step.get('params', {})
                if not isinstance(params, dict):
                    continue
                text = params.get('expect_results', '')
                if text and isinstance(text, str) and not text.startswith('${'):
                    new_locator = (
                        f"xpath=//*[contains(.,'{text}') and "
                        f"not(ancestor-or-self::*[contains(@style,'display:none') or "
                        f"contains(@style,'display: none')])]"
                    )
                    step['keyword'] = 'except_to_be_visible'
                    step['params'] = {'locator': new_locator}
                    self.repair_log.append({
                        'rule': 'R4.22',
                        'action': f'{kw} → except_to_be_visible + text locator',
                        'guarantee': '语义等价替换',
                    })
        return steps

    def _repair_env_isolation(self, steps):
        ISOLATION_KW = {'open_url', 'refresh', 'wait_for_element_hidden'}
        first_keywords = set()
        for s in steps[:5]:
            if isinstance(s, dict):
                first_keywords.add(s.get('keyword', ''))

        if ISOLATION_KW.issubset(first_keywords):
            return steps

        preamble = [
            {'desc': '导航到目标页', 'keyword': 'open_url',
             'params': {'url': '${common_data.target_url}'}},
            {'desc': '刷新页面', 'keyword': 'refresh'},
            {'desc': '等待加载完成', 'keyword': 'wait_for_loading_complete', 'params': {}},
        ]
        for p_step in reversed(preamble):
            if p_step['keyword'] not in first_keywords:
                steps.insert(0, p_step)
                first_keywords.add(p_step['keyword'])
                self.repair_log.append({
                    'rule': 'R4.9',
                    'action': f'insert {p_step["keyword"]}',
                    'guarantee': '标准环境隔离模板',
                })
        return steps

    def _repair_var_format(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            for key in ('locator', 'value', 'expect_results'):
                val = params.get(key, '')
                if not isinstance(val, str):
                    continue
                for m in _SC_VAR_REF_RE.finditer(val):
                    ref = m.group(1)
                    if '.' not in ref:
                        group = self._find_group_for_field(ref)
                        if group:
                            new_ref = f"{group}.{ref}"
                            val = val.replace(f"${{{ref}}}", f"${{{new_ref}}}")
                            params[key] = val
                            self.repair_log.append({
                                'rule': 'R4.6',
                                'action': f'add group: ${{{ref}}} → ${{{new_ref}}}',
                                'guarantee': 'ElementResolver 精确查找',
                            })
        return steps

    def _repair_hardcoded_values(self, steps):
        for step in steps:
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue

            if kw in ('fill_value', 'frame_fill_value'):
                value = str(params.get('value', ''))
                if (value and not value.startswith('${')
                        and value not in _SC_EXEMPT_VALUES
                        and any('一' <= c <= '鿿' for c in value)
                        and len(value) > 1):
                    field_name = self._generate_data_field_name(value)
                    var_ref = f"${{{self.data_group_name}.{field_name}}}"
                    grp = self.data_entries.setdefault(self.data_group_name, {})
                    grp[field_name] = value
                    params['value'] = var_ref
                    self.repair_log.append({
                        'rule': 'R4.2',
                        'action': f'extract "{value}" → {var_ref}',
                        'guarantee': '值已存入 data_entries',
                    })
        return steps

    def _find_group_for_field(self, field_name):
        """在 resolver groups 中查找字段所属的 group"""
        if not self.resolver:
            return None
        matches = []
        for gname, field_map in self.resolver.get_groups().items():
            if field_name in field_map:
                matches.append(gname)
        if len(matches) == 1:
            return matches[0]
        if self.module_name:
            prefix = self.module_name.replace('-', '_')
            for g in matches:
                if g.replace('-', '_').startswith(prefix):
                    return g
        return matches[0] if matches else None

    def _generate_data_field_name(self, value):
        slug = re.sub(r'[^a-z0-9]', '_', value.lower()).strip('_')
        if slug and len(slug) < 30:
            return slug
        existing = self.data_entries.get(self.data_group_name, {})
        idx = len(existing) + 1
        return f'field_{idx}'

    def _verify_all(self, steps, case_id=''):
        issues = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue

            if (kw and kw not in _SC_ENGINE_KEYWORDS
                    and kw not in self.l3_keywords):
                issues.append({'rule': 'R4.13', 'step': i, 'kw': kw,
                               'reason': '关键字不在注册表'})

            for p in _SC_FORBIDDEN_PARAMS.get(kw, set()):
                if p in params:
                    issues.append({'rule': 'R4.14', 'step': i, 'param': p,
                                   'reason': '仍存在禁止参数'})

            locator = str(params.get('locator', ''))
            if locator.startswith('css='):
                issues.append({'rule': 'R4.21', 'step': i, 'locator': locator,
                               'reason': 'CSS 选择器无法转换为 XPath'})

            if kw in _SC_FORBIDDEN_ASSERT_KW:
                issues.append({'rule': 'R4.22', 'step': i, 'kw': kw,
                               'reason': '仍使用禁止断言'})

            for param_key in ('locator', 'value', 'expect_results'):
                val = params.get(param_key, '')
                if not isinstance(val, str):
                    continue
                for m_ref in _SC_VAR_REF_RE.finditer(val):
                    ref = m_ref.group(1)
                    if '.' not in ref:
                        issues.append({'rule': 'R4.6', 'step': i, 'ref': ref,
                                       'reason': '变量缺少 group 前缀'})

        # M9: 4 项盲区检查（只检测不修复，作为 warning 报告）

        # M9-1: R4.41 变量引用有效性 — ${group.field} 是否在 resolver/required_fields 中存在
        all_groups = self.resolver.get_groups() if self.resolver else {}
        required_keys = set()
        if hasattr(self, '_required_fields_ref'):
            required_keys = self._required_fields_ref
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            for param_key in ('locator', 'value'):
                val = str(params.get(param_key, ''))
                for m_ref in _SC_VAR_REF_RE.finditer(val):
                    ref = m_ref.group(1)
                    if '.' in ref:
                        gname, fkey = ref.split('.', 1)
                        if gname in all_groups and fkey not in all_groups[gname]:
                            if ref not in required_keys:
                                issues.append({'rule': 'R4.41', 'step': i,
                                               'ref': ref,
                                               'reason': f'变量引用 {ref} 在 resolver 中不存在'})

        # M9-2: R4.42 XPath 基础语法检查 — 括号平衡 + ]*[ 残留
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            locator = str(params.get('locator', ''))
            if not locator:
                continue
            # 检查 ]*[ 残留（Fix-1 修复后不应出现）
            if ']*[' in locator:
                issues.append({'rule': 'R4.42', 'step': i, 'locator': locator[:80],
                               'reason': 'XPath 含 ]*[ 残留（容器前缀拼接错误）'})
            # 检查 [待确认] 占位符
            if '[待确认]' in locator:
                issues.append({'rule': 'R4.42', 'step': i, 'locator': locator[:80],
                               'reason': 'XPath 含 [待确认] 占位符'})
            # 括号平衡检查
            raw = locator.replace('xpath=', '')
            depth = 0
            for ch in raw:
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
            if depth != 0:
                issues.append({'rule': 'R4.42', 'step': i, 'locator': locator[:80],
                               'reason': f'XPath 方括号不平衡 (depth={depth})'})

        # M9-3: R4.43 companion 字段完整性 — el-select 步骤的 _select 引用
        #       是否有对应 _editable companion
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            kw = step.get('keyword', '')
            params = step.get('params', {})
            if not isinstance(params, dict):
                continue
            locator = str(params.get('locator', ''))
            # 检查 if_element_visible 步骤引用的 _editable 是否存在
            if kw == 'if_element_visible' and '_editable' in locator:
                m = _SC_VAR_REF_RE.search(locator)
                if m:
                    ref = m.group(1)
                    if '.' in ref:
                        gname, fkey = ref.split('.', 1)
                        if gname in all_groups:
                            # 检查对应的 _select 是否也存在
                            select_key = fkey.replace('_editable', '_select')
                            if select_key not in all_groups.get(gname, {}):
                                issues.append({'rule': 'R4.43', 'step': i,
                                               'ref': ref,
                                               'reason': f'_editable 引用但对应 _select({select_key}) 不存在'})

        for issue in issues:
            issue['case_id'] = case_id
            issue['file'] = f'cases/{self.module_name}/{case_id}' if case_id else ''
            issue['suggestion'] = self._get_suggestion(issue)
        return issues

    def _verify_rule(self, steps, rule_id):
        return [i for i in self._verify_all(steps) if i['rule'] == rule_id]

    def _get_suggestion(self, issue):
        rule = issue.get('rule', '')
        suggestions = {
            'R4.13': '确认关键字是否在 ENGINE_KEYWORDS 或 L3 关键字中',
            'R4.14': '检查参数名是否符合关键字规范',
            'R4.21': '复杂 CSS 选择器需手动转为 XPath',
            'R4.22': 'except_to_have_text 已被全局约束禁止',
            'R4.6': '多 group 同名时无法自动确定所属 group',
            'R4.2': '硬编码值已提取但字段名可能需要人工调整',
            'R4.41': 'M9: 变量引用的 group.field 在 resolver 中不存在，检查 pages YAML 是否生成',
            'R4.42': 'M9: XPath 语法错误（括号不平衡/]*[残留/[待确认]占位符）',
            'R4.43': 'M9: _editable companion 引用但对应 _select 不存在',
        }
