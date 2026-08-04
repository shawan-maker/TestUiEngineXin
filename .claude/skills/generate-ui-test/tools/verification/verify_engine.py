"""
verify_engine.py - 步骤执行引擎

从 verify_locators.py 提取的浏览器交互层函数：
- 定位器候选验证（verify_locator_candidates）
- 步骤执行（execute_step）
- L3 工作流展开
- 容器检测和等待逻辑
- DOM 元素类型检测
"""

import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Script directory for workflow YAML loading
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Adjust to tools/ level (one directory up from verification/)
_TOOLS_DIR = os.path.dirname(SCRIPT_DIR)

# ─── Shared imports ───
from core.xpath_utils import (
    inject_hidden_filter, has_hidden_filter, CONTAINER_XPATH,
    _unwrap_positional, _rewrap_positional,
)
from core.field_suffixes import DIALOG_CONFIRM_LABELS
from core.element_types import infer_elem_type as _infer_elem_type
from core.wait_utils import wait_for_dom_stable as _wait_for_dom_stable
from probe.probe_element import detect_visible_containers, parse_cookie, safe_count
from probe.probe_utils import kb_fallback

# ─── Sibling module imports ───
from verification.data_layer import (
    resolve_var, resolve_locator,
    _get_kb_locators, _find_in_discovery,
    CLICK_EXPAND_TYPES,
)

# R6: AI fallback probe (optional)
try:
    from probe.ai_probe import ai_probe_locator as _ai_probe_locator
    _HAS_AI_PROBE = True
except ImportError:
    _HAS_AI_PROBE = False

# ─── Local copies of constants (originally defined in verify_locators.py lines 92-124) ───
# These are also needed by verify_orchestrator.py, which will import from this module.
DESTRUCTIVE_TRIGGERS = {'删除', '移除', '清空', '重置'}
CONTAINER_TYPES = ['dialog', 'drawer', 'message-box']
_SYSTEM_WORKFLOWS = None
_PROJECT_WORKFLOWS = {}
PROBE_ISOLATION_PREFIX = '__probe__'
NO_VERIFY_KEYWORDS = {
    'open_url', 'open_browser', 'refresh', 'go_back', 'wait_for_time',
    'wait_for_element_hidden', 'log', 'inject_local_storage', 'inject_cookies',
    'inject_token_header', 'close_browser', 'set_viewport_size',
    'check_page_loaded',
    'wait_for_loading_complete',
    'if_variable',
    'wait_for_element',
    'set_random_variable',
}
L3_KEYWORDS = {'l3_call'}
PROBE_FILL_VALUES = {
    'input': PROBE_ISOLATION_PREFIX + '测试',
    'textarea': PROBE_ISOLATION_PREFIX + '测试文本',
    'number': '999',
}

# ─── el-select expand 转换函数（Phase 5 input → Phase 6 el-select 容器）───
def _is_el_select_expand(field_name: str, step_desc: str) -> bool:
    """识别 el-select 的 expand 步骤

    判断依据：
    1. 字段名以 _expand 结尾
    2. 步骤描述包含"点击"和"下拉框"

    Args:
        field_name: pages YAML 中的字段名（如 field_9551c1_expand）
        step_desc: 步骤描述（如"选择「镜像来源」 - 点击下拉框"）

    Returns:
        bool: 是否为 el-select expand 步骤
    """
    if not field_name.endswith('_expand'):
        return False
    if '点击' not in step_desc or '下拉框' not in step_desc:
        return False
    return True


def _convert_input_to_el_select(input_locator: str) -> str:
    """将 input[@class='el-input__inner'] 转换为 el-select 容器

    转换规则：
    //input[@class='el-input__inner' and ...]
    → //div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]

    使用 bracket-depth 扫描替代正则，正确处理嵌套 []（如 hidden filter 中的
    not(ancestor::*[contains(@style,'display: none')])）。

    保留原始的 ()[n] 包裹：如果输入已有 (xpath)[n] 包裹，转换后保持 [n] 不变；
    仅当输入没有 ()[n] 包裹时，自动添加 ()[1]。

    Args:
        input_locator: input 目标的 locator（含 xpath= 前缀）

    Returns:
        str: 转换后的 el-select 容器 locator，转换失败返回原值
    """
    if not input_locator.startswith('xpath='):
        return input_locator

    xpath = input_locator[6:]  # 去掉 xpath= 前缀

    # 定位 //input[@class='el-input__inner'
    marker = "//input[@class='el-input__inner'"
    start = xpath.find(marker)
    if start < 0:
        return input_locator

    # 从 [ 开始 bracket-depth 扫描，找到匹配的 ]
    bracket_start = start + len("//input")  # [ 的位置
    depth = 0
    end = -1
    for i in range(bracket_start, len(xpath)):
        if xpath[i] == '[':
            depth += 1
        elif xpath[i] == ']':
            depth -= 1
            if depth == 0:
                end = i + 1  # ] 后一位
                break

    if end < 0:
        # 未找到匹配的 ]，返回原值
        return input_locator

    # 整段替换为 el-select 容器表达式（使用 //div 精确匹配，而非 //* 通配）
    replacement = "//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]"
    converted = xpath[:start] + replacement + xpath[end:]

    # 保留原始的 ()[n] 包裹：如果已有则保持 [n] 不变，否则添加 ()[1]
    if converted.startswith('('):
        # 已有 ()[n] 包裹 → 保留原始索引，不修改
        pass
    else:
        # 无 () 包裹 → 添加 ()[1]
        converted = f"({converted})[1]"

    return f"xpath={converted}"


# ─── Writeback helpers (used by execute_step Fix-6, also needed by pages_writeback) ───
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


# Locator verification — try candidates × prefixes
# ============================================================================

# 容器前缀剥离正则（匹配 el-dialog/el-drawer/el-message-box 前缀）
CONTAINER_PREFIX_PATTERN = re.compile(
    r"^//div\[contains\(@class,'el-(dialog|drawer|message-box)'\)\]"
)


def _strip_container_prefix(raw_xpath):
    """剥离 XPath 中的容器前缀（el-dialog/el-drawer/el-message-box）

    支持两种格式：
    - 裸 XPath: //div[...]//button → //button
    - 包裹 XPath: (//div[...]//button)[1] → (//button)[1]

    Args:
        raw_xpath: 原始 XPath（不含 xpath= 前缀）

    Returns:
        剥离后的 XPath（保持原有包裹格式）
    """
    inner, wrap = _unwrap_positional(raw_xpath)
    stripped = CONTAINER_PREFIX_PATTERN.sub("", inner)
    return _rewrap_positional(stripped, wrap)


def _verify_count_or_first(page, locator):
    """验证 locator 匹配数，count>1 时自动 [1] 收窄避免 strict mode violation。

    与 verify_locator_candidates() 的 count>1 逻辑保持一致：
    count==1 → 通过；count>1 → 尝试 (xpath)[1] 取首个匹配元素。

    Args:
        page: Playwright Page 对象
        locator: 完整 locator 字符串（含 xpath= 前缀）

    Returns:
        str or None: 验证通过的 locator（可能已 [1] 收窄），count==0 返回 None
    """
    if not locator:
        return None
    try:
        count = page.locator(locator).count()
    except Exception:
        return None
    if count == 1:
        return locator
    if count > 1:
        # 多匹配 → [1] 收窄（与 verify_locator_candidates 的 [1] fallback 一致）
        raw = locator[6:] if locator.startswith('xpath=') else locator

        # 防止双重包裹：如果已有 (xpath)[N] 外层，先解包再用 [1] 重新包裹
        from core.xpath_utils import _unwrap_positional, _rewrap_positional
        inner, _ = _unwrap_positional(raw)
        narrowed_raw = f"({inner})[1]"

        narrowed = inject_hidden_filter(f"xpath={narrowed_raw}")
        try:
            if page.locator(narrowed).count() == 1:
                return narrowed
        except Exception:
            pass
    return None


def verify_locator_candidates(page, candidates, container_type=None, discovery_ct=None, is_el_select_option=False, return_index=False):
    """Try multiple locator candidates with multiple container prefixes.

    Priority: discovery container_type > default priority > no prefix

    P1-2: el-select options (is_el_select_option=True) — NO container prefix,
    dropdown panel floats globally outside drawer/dialog.

    P2-4: When count>1 in preferred container, fall back to (xpath)[last()]
    for dialog/drawer (last opened = topmost).

    Args:
        return_index: If True, return 4-tuple with matched candidate index.
                     If False (default), return 3-tuple for backward compatibility.

    Returns:
        If return_index=False: (matched_locator, matched_prefix, count) or (None, None, 0)
        If return_index=True: (matched_locator, matched_prefix, count, candidate_index) or (None, None, 0, None)
    """
    # Build prefix order
    if is_el_select_option:
        # P1-2: options are globally in dropdown panel, no container prefix
        prefix_order = [None]
    elif discovery_ct:
        prefix_order = [discovery_ct] + [p for p in CONTAINER_TYPES if p != discovery_ct] + [None]
    elif container_type:
        prefix_order = [container_type] + [p for p in CONTAINER_TYPES if p != container_type] + [None]
    else:
        prefix_order = CONTAINER_TYPES + [None]

    # Helper: return result with or without candidate index
    def _ret(xpath, pfx, cnt, cidx=None):
        if return_index:
            return xpath, pfx, cnt, cidx
        return xpath, pfx, cnt

    # [TRACE-P6] 遍历入口：候选数量 + prefix 顺序
    print(f"    [TRACE-P6] verify_locator_candidates: {len(candidates)} candidates, "
          f"prefix_order={[p or 'None' for p in prefix_order]}")

    # 两轮验证：
    # 第一轮：遍历所有候选，仅返回 count==1 的唯一匹配（跳过 [1]/[last()] 收窄）
    # 第二轮：保留原有 count>1 逻辑（[1] 防御、[last()]、容器前缀修复）
    for _pass in (1, 2):
        for prefix in prefix_order:
            # [TRACE-P6] 当前 prefix
            print(f"    [TRACE-P6]   pass={_pass} prefix={prefix or 'None'}")
            for candidate_index, candidate in enumerate(candidates):
                xpath = candidate
                if not xpath.startswith('xpath='):
                    xpath = f"xpath={xpath}"

                # 剥离已有容器前缀 → 得到裸 XPath
                raw_xpath = xpath[6:] if xpath.startswith('xpath=') else xpath
                bare_xpath = _strip_container_prefix(raw_xpath)

                # 按 prefix 决定的顺序测试 4 种变体
                if prefix is None:
                    # prefix=None: 容器前缀优先，最后不带前缀
                    # 优先级: dialog > drawer > message-box > 无前缀
                    test_order = CONTAINER_TYPES + [None]
                else:
                    # prefix='dialog': dialog 优先，然后其他容器，最后 none
                    test_order = [prefix] + [p for p in CONTAINER_TYPES if p != prefix] + [None]

                for test_prefix in test_order:
                    # 构建测试 XPath
                    if test_prefix is None:
                        test_xpath = bare_xpath
                    elif test_prefix in CONTAINER_XPATH:
                        # BUG-13 修复：前缀注入到括号内部，避免 prefix + (xpath)[N] 无效拼接
                        inner, wrap = _unwrap_positional(bare_xpath)
                        test_xpath = _rewrap_positional(CONTAINER_XPATH[test_prefix] + inner, wrap)
                    else:
                        test_xpath = bare_xpath

                    # C-3 / L-5: el-select options — do NOT inject hidden filter
                    # (dropdown panel uses display:none internally when not expanded)
                    if is_el_select_option:
                        full_xpath = f"xpath={test_xpath}" if not test_xpath.startswith('xpath=') else test_xpath
                    else:
                        full_xpath = inject_hidden_filter(f"xpath={test_xpath}")

                    try:
                        count = page.locator(full_xpath).count()
                        # [TRACE-P6] 每个 candidate 的 count 值
                        print(f"    [TRACE-P6]     cand[{candidate_index}] count={count} test_prefix={test_prefix or 'None'}: "
                              f"{full_xpath[:120]}{'...' if len(full_xpath) > 120 else ''}")
                        if count == 1:
                            return _ret(full_xpath, test_prefix, count, candidate_index)
                        if count > 1:
                            # 第一轮：跳过所有收窄，继续尝试其他候选
                            if _pass == 1:
                                continue
                            # 第二轮：保留原有 count>1 逻辑
                            # 3b: strict mode auto-fix — 无前缀时自动尝试容器前缀
                            if test_prefix is None and not is_el_select_option:
                                for try_ct in ['dialog', 'drawer', 'message-box']:
                                    if try_ct not in CONTAINER_XPATH:
                                        continue
                                    try_prefix = CONTAINER_XPATH[try_ct]
                                    # BUG-13 修复：前缀注入到括号内部
                                    inner, wrap = _unwrap_positional(bare_xpath)
                                    scoped_raw = _rewrap_positional(try_prefix + inner, wrap)
                                    scoped_full = inject_hidden_filter(f"xpath={scoped_raw}")
                                    try:
                                        scoped_count = page.locator(scoped_full).count()
                                        if scoped_count == 1:
                                            print(f"    [INFO] 3b strict mode 修复: 自动添加 {try_ct} 前缀")
                                            return _ret(scoped_full, try_ct, 1, candidate_index)
                                    except Exception as _e:
                                        # H4: 记录异常（XPath语法错误/超时/其他）便于调试
                                        print(f"    [WARN] H4: 3b strict 前缀探测异常({try_ct}): {_e}")
                            # P2-4: [last()] strategy for dialog/drawer (topmost = last opened)
                            if test_prefix in ('dialog', 'drawer') and not is_el_select_option:
                                wrapped_last = f"({test_xpath})[last()]"
                                full_last = inject_hidden_filter(f"xpath={wrapped_last}")
                                try:
                                    cnt_last = page.locator(full_last).count()
                                    if cnt_last == 1:
                                        return _ret(full_last, test_prefix, 1, candidate_index)
                                except Exception as _e:
                                    print(f"    [WARN] H4: [last()] 探测异常: {_e}")
                            # Fallback: [1]
                            wrapped = f"({test_xpath})[1]"
                            if is_el_select_option:
                                full_wrapped = f"xpath={wrapped}"
                            else:
                                full_wrapped = inject_hidden_filter(f"xpath={wrapped}")
                            count2 = page.locator(full_wrapped).count()
                            if count2 == 1:
                                return _ret(full_wrapped, test_prefix, 1, candidate_index)
                    except Exception as _e:
                        print(f"    [WARN] H4: 候选 XPath 探测异常: {_e}")

    # BUG-3 层2: 容器前缀替换安全网 — M3: 已移除跨容器猜测
    # 旧逻辑: 尝试 el-drawer ↔ el-dialog 替换（属于"下游猜测"，违反原则二）
    # 新逻辑: 容器类型不一致会作为验证失败暴露，必须在上游修复
    # （跨容器替换已移除，不再执行任何替换操作）

    # BUG-4 D3: H9 修复 — 全部 count==0 时返回 None（而非未验证的 fallback）
    # 让 KB fallback 链（D5 + M11）可达，避免静默传播 count=0 的错误 locator
    # 拆字模式在 KB fallback 中有独立的模板，不需要此处保留错误候选
    if candidates:
        return _ret(None, None, 0, None)

    return _ret(None, None, 0, None)


# ============================================================================
# Step execution
# ============================================================================

# L3 system workflows cache (P2-3)
_L3_WORKFLOWS_CACHE = {}


def _load_l3_workflows(project_dir):
    """Load L3 system + skill + project workflows (P2-3).

    Returns: {workflow_name: {params: [...], steps: [...]}}
    """
    if project_dir in _L3_WORKFLOWS_CACHE:
        return _L3_WORKFLOWS_CACHE[project_dir]
    workflows = {}
    # System workflows (always available)
    sys_wf_path = os.path.join(SCRIPT_DIR, 'system_workflows.yaml')
    if not os.path.isfile(sys_wf_path):
        sys_wf_path = os.path.join(SCRIPT_DIR, '..', 'templates', 'system_workflows.yaml')
    if os.path.isfile(sys_wf_path):
        try:
            with open(sys_wf_path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                for name, wf in data.items():
                    if isinstance(wf, dict) and 'steps' in wf:
                        workflows[name] = wf
        except Exception as e:
            print(f"    [WARN] Failed to load system workflows: {e}")
    # Skill-level workflows (lib/_knowledge/)
    skill_knowledge_dir = os.path.join(SCRIPT_DIR, '..', 'lib', '_knowledge')
    if os.path.isdir(skill_knowledge_dir):
        for f in os.listdir(skill_knowledge_dir):
            if f.endswith(('.yaml', '.yml')):
                try:
                    with open(os.path.join(skill_knowledge_dir, f), encoding='utf-8') as fh:
                        data = yaml.safe_load(fh) or {}
                    for wf in data.get('workflows', []):
                        if isinstance(wf, dict) and 'name' in wf:
                            workflows[wf['name']] = wf
                except Exception as e:
                    print(f"    [WARN] Failed to load skill workflow {f}: {e}")
    # Project workflows (from _knowledge/)
    knowledge_dir = os.path.join(project_dir, '_knowledge')
    if os.path.isdir(knowledge_dir):
        for f in os.listdir(knowledge_dir):
            if f.endswith(('.yaml', '.yml')):
                try:
                    with open(os.path.join(knowledge_dir, f), encoding='utf-8') as fh:
                        data = yaml.safe_load(fh) or {}
                    for wf in data.get('workflows', []):
                        if isinstance(wf, dict) and 'name' in wf:
                            workflows[wf['name']] = wf
                except Exception as e:
                    print(f"    [WARN] Failed to load project workflow {f}: {e}")
    _L3_WORKFLOWS_CACHE[project_dir] = workflows
    return workflows


def _expand_l3_call(step, project_dir, pages_dict, data_dict):
    """Expand l3_call step into sub-steps (P2-3).

    Replaces ${param} placeholders in workflow steps with actual args.
    Returns list of sub-steps (empty if workflow not found).
    """
    params = step.get('params', {}) or {}
    workflow_name = params.get('workflow', '') or step.get('workflow', '')
    if not workflow_name:
        return []
    workflows = _load_l3_workflows(project_dir or '')
    wf = workflows.get(workflow_name)
    if not wf:
        print(f"    [WARN] l3_call workflow not found: {workflow_name}")
        return []
    wf_steps = wf.get('steps', []) or []
    if not wf_steps:
        return []
    # Build substitution map
    wf_param_names = wf.get('params', []) or []
    actual_args = params.get('args', []) or []
    if isinstance(actual_args, str):
        actual_args = [actual_args]
    sub_map = {}
    if isinstance(actual_args, list):
        for i, pname in enumerate(wf_param_names):
            if i < len(actual_args):
                sub_map[f'${{{pname}}}'] = str(actual_args[i])
    if isinstance(params.get('args'), dict):
        for k, v in params['args'].items():
            sub_map[f'${{{k}}}'] = str(v)
    # BUG-1: Build locators substitution map from workflow's locators dict
    wf_locators = wf.get('locators', {}) or {}
    resolved_locators = {}
    # Whitelist: only substitute {param} for params explicitly declared in workflow
    _param_whitelist = set(wf_param_names)
    for loc_name, loc_xpath in wf_locators.items():
        resolved = loc_xpath
        # Replace {param} placeholders (single brace) with actual values
        for placeholder, value in sub_map.items():
            bare_key = placeholder[2:-1]  # ${tab_name} → tab_name
            if bare_key in _param_whitelist:
                resolved = resolved.replace(f'{{{bare_key}}}', value)
        resolved_locators[loc_name] = resolved
    # Add ${locators.xxx} → resolved XPath to sub_map
    for loc_name, loc_xpath in resolved_locators.items():
        # Warn if locator template still has unresolved {param} placeholders
        _unresolved = re.findall(r'\{([a-zA-Z_]\w*)\}', loc_xpath)
        if _unresolved:
            print(f"    [WARN] Locator '{loc_name}' has unresolved placeholders: {_unresolved}")
        sub_map[f'${{locators.{loc_name}}}'] = loc_xpath
    # Deep copy + substitute
    expanded = []
    for ws in wf_steps:
        if not isinstance(ws, dict):
            continue
        ws_copy = json.loads(json.dumps(ws))
        # BUG-1: Also substitute {param} in desc field (for log readability)
        if 'desc' in ws_copy and isinstance(ws_copy['desc'], str):
            for placeholder, value in sub_map.items():
                bare_key = placeholder[2:-1]
                if bare_key in _param_whitelist:
                    ws_copy['desc'] = ws_copy['desc'].replace(f'{{{bare_key}}}', value)
        if 'params' in ws_copy and isinstance(ws_copy['params'], dict):
            for pk, pv in list(ws_copy['params'].items()):
                if isinstance(pv, str):
                    for placeholder, value in sub_map.items():
                        pv = pv.replace(placeholder, value)
                    ws_copy['params'][pk] = pv
        expanded.append(ws_copy)
    return expanded


def _smart_wait_after_action(page, wait_dom_stable=True):
    """P3-2: Smart wait after user-visible action.

    Combines networkidle (max 2s) + loading-mask hidden (max 3s) + DOM stable (max 3s).
    Non-fatal — never raises.

    Args:
        wait_dom_stable: 默认 True，等待 DOM 渲染稳定。
            仅在确认无渲染场景（如纯等待步骤）时可设为 False 跳过。
    """
    try:
        page.wait_for_load_state('networkidle', timeout=2000)
    except Exception:
        pass
    try:
        mask = page.locator("xpath=//div[contains(@class,'el-loading-mask') and not(contains(@style,'display: none'))]")
        if mask.count() > 0:
            mask.first.wait_for(state='hidden', timeout=3000)
    except Exception:
        pass

    # DOM 稳定性等待：等表单元素数量不再变化（默认启用）
    if wait_dom_stable:
        _wait_for_dom_stable(page, timeout_ms=3000)


# Plan D: 容器等待增强 — 参考 Phase 4 的 wait_for_stable() 逻辑
_SKIP_CONTAINER_WAIT_LABELS = {
    '确定', '确认', '取消', '删除', '移除', '关闭', '返回', '保存', '提交',
    '搜索', '查询', '刷新', '导出', '下载', '批量', '更多', '重置', '清空',
}




def _should_wait_for_container(desc, locator, keyword):
    """Plan D: 判断 click 后是否需要等待容器渲染完成。

    避免对所有 click 都增加 8s 等待开销。

    Returns:
        bool: True 表示应启用增强容器等待
    """
    if keyword == 'click_select_option':
        return False
    # 表格行内按钮通常不打开容器
    if 'tbody' in locator:
        return False
    # 从 desc 提取按钮标签（优先引号内，回退到直接匹配）
    btn_match = re.search(r'[「"""](.+?)[」"""]', desc)
    btn_label = btn_match.group(1) if btn_match else ''
    if not btn_label:
        # 回退：直接在 desc 中检查跳过标签
        btn_label = desc
    if any(skip in btn_label for skip in _SKIP_CONTAINER_WAIT_LABELS):
        return False
    return True


def _wait_for_container_after_click(page, timeout_ms=2000):
    """点击后容器探测（Playwright 事件驱动，非 Python 轮询）。

    在 _smart_wait_after_action（最多 ~8s）之后调用。
    _smart_wait 已覆盖网络+loading+DOM 稳定，容器如果存在通常已可见。
    本函数用 Playwright 原生 wait_for 做二次确认：
      - 容器已可见 → 立即返回（~0ms）
      - 容器在 API 回调后异步出现 → 事件驱动立即捕捉（比 Python 轮询更快更可靠）
      - 容器不存在 → timeout_ms 后返回 None

    Args:
        timeout_ms: 最大等待时长（默认 2s，_smart_wait 已给了 8s 基础等待）

    Returns:
        str or None: 检测到的容器类型，或 None
    """
    container_selector = (
        "xpath=//div[contains(@class,'el-drawer')"
        " and not(contains(@style,'display: none'))] | "
        "//div[contains(@class,'el-dialog__wrapper')"
        " and not(contains(@style,'display: none'))] | "
        "//div[contains(@class,'el-message-box')]"
    )
    try:
        page.locator(container_selector).first.wait_for(
            state='visible', timeout=timeout_ms)
    except Exception:
        return None  # 超时 → 没有容器出现

    # wait_for 返回 → 容器元素已可见，用 detect_visible_containers 确认类型
    visible = detect_visible_containers(page)
    if visible:
        for ct in CONTAINER_TYPES:
            if ct in visible:
                return ct
        return visible[0] if visible else None

    # wait_for 检测到了但 detect_visible_containers 返回空（极罕见：动画中间态）
    # 短重试
    for _retry in range(3):
        page.wait_for_timeout(300)
        visible = detect_visible_containers(page)
        if visible:
            for ct in CONTAINER_TYPES:
                if ct in visible:
                    return ct
    return None


def should_skip_confirm(steps_so_far):
    """Check if the last few steps contain a destructive trigger."""
    for step in steps_so_far[-3:]:
        desc = step.get('desc', '')
        for trigger in DESTRUCTIVE_TRIGGERS:
            if trigger in desc:
                return True
    return False


# R3: Runtime DOM element type detection
_TAG_TO_KB_TYPE = {
    'textarea': 'textarea-generic',
    'input': 'input-generic',
    'select': 'el-select',
    'date': 'date-picker',
    'button': 'button',
}

# BUG-11: R3 DOM 检测类型守卫 — 防止 button→textarea 等跨类型越界注入
# R3 (_detect_actual_element_type) 在 R4 elif 链之前执行，其结果必须通过
# 类型兼容性检查才能插入 _alt_types，否则同名表单字段会污染按钮类型。
_R3_TYPE_COMPAT = {
    # 按钮类：只允许按钮子类型之间互转
    'button':                {'button', 'search-button', 'download-button', 'close-button', 'table-action-button'},
    'table-action-button':   {'table-action-button', 'button'},
    'search-button':         {'search-button', 'button'},
    'download-button':       {'download-button', 'button'},
    'close-button':          {'close-button', 'button'},
    # 输入类：input ↔ textarea 互转
    'input-generic':         {'input-generic', 'textarea-generic'},
    'textarea-generic':      {'textarea-generic', 'input-generic'},
    # 选择类
    'el-select':             {'el-select'},
    'el-cascader':           {'el-cascader', 'el-select'},
    # 日期类
    'date-picker':           {'date-picker', 'input-generic'},
    # 其他
    'tab':                   {'tab'},
    'checkbox':              {'checkbox', 'checkbox-all'},
    'checkbox-all':          {'checkbox-all', 'checkbox'},
    'detail-link':           {'detail-link'},
    'menu-item':             {'menu-item'},
    'field-assertion':       {'field-assertion'},
}


def _detect_actual_element_type(page, label, container_prefix=''):
    """R3: 运行时 DOM 检查 — 确定 label 对应的实际表单元素类型。

    在 KB/discovery 全部 count=0 时调用。通过 JS 查找 label 附近的表单元素，
    返回实际 tagName 映射的 KB 类型。

    Returns: KB canonical type string or None
    """
    if not label:
        return None
    try:
        # Escape for JS string literal safety
        # Order matters: escape backslash FIRST, then single quote
        safe_label = label.replace('\\', '\\\\').replace("'", "\\'")
        safe_prefix = container_prefix.replace('\\', '\\\\').replace("'", "\\'")
        result = page.evaluate(f"""() => {{
            const prefix = "{safe_prefix}";
            const labelText = "{safe_label}";

            // Build XPath to find label text nodes
            const xpath = prefix
                ? prefix + "//*[contains(text(),'" + labelText + "')]"
                : "//*[contains(text(),'" + labelText + "')]";

            const nodes = document.evaluate(
                xpath, document, null,
                XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
            );

            for (let i = 0; i < nodes.snapshotLength; i++) {{
                const node = nodes.snapshotItem(i);
                // Skip hidden elements
                if (node.offsetParent === null && node.getClientRects().length === 0) continue;

                // Strategy 1: following-sibling (up to 3 siblings)
                let sibling = node.nextElementSibling;
                for (let j = 0; j < 3 && sibling; j++) {{
                    if (sibling.querySelector('textarea') || sibling.tagName === 'TEXTAREA')
                        return 'textarea';
                    const sel = sibling.querySelector('.el-select') ||
                                (sibling.classList && sibling.classList.contains('el-select') ? sibling : null);
                    if (sel) return 'select';
                    const dateEl = sibling.querySelector('.el-date-editor');
                    if (dateEl) return 'date';
                    const inp = sibling.querySelector('input:not([type=hidden])') ||
                                (sibling.tagName === 'INPUT' ? sibling : null);
                    if (inp) return 'input';
                    sibling = sibling.nextElementSibling;
                }}

                // Strategy 2: el-form-item parent structure
                const formItem = node.closest('.el-form-item');
                if (formItem) {{
                    const content = formItem.querySelector('.el-form-item__content');
                    if (content) {{
                        if (content.querySelector('textarea')) return 'textarea';
                        if (content.querySelector('.el-select')) return 'select';
                        if (content.querySelector('.el-date-editor')) return 'date';
                        if (content.querySelector('input:not([type=hidden])')) return 'input';
                    }}
                }}
            }}
            return null;
        }}""")
        if result:
            return _TAG_TO_KB_TYPE.get(result)
    except Exception:
        pass
    return None


def execute_step(page, step, pages_dict, data_dict, steps_so_far, discovery_data=None, project_dir=None,
                 is_new_page_context=False, container_context=None):
    """Execute a single case step in the browser.

    Args:
        is_new_page_context: True if we're on a different page than baseline (7.10 fix)
        container_context: 上一个步骤检测到的容器类型（dialog/drawer），当本次检测失败时作为 fallback

    Returns: (verified_locator, container_type, skipped, is_best_guess, hit_source)
             hit_source: 'discovery' | 'kb' | 'original' | 'fallback' | None
    """
    is_best_guess = False  # R5: set True when KB best-guess locator is used
    hit_source = None  # Track which candidate source succeeded
    keyword = step.get('keyword', '')
    params = step.get('params', {})
    desc = step.get('desc', '')

    # [TRACE-P6] 函数入口上下文
    _raw_locator_param = params.get('locator', '') if isinstance(params, dict) else ''
    print(f"    [TRACE-P6] entry: keyword={keyword}, desc='{desc[:60]}'")
    print(f"    [TRACE-P6]   raw_locator={_raw_locator_param}, "
          f"is_new_page={is_new_page_context}, container_ctx={container_context}")
    # [TRACE-P6] 当前页面 URL（用于追踪页面导航）
    try:
        _entry_url = page.url
        print(f"    [TRACE-P6]   current_url={_entry_url[:80]}")
    except Exception:
        pass

    if keyword in NO_VERIFY_KEYWORDS:
        # open_url / refresh must still be executed so we navigate to the right page
        if keyword == 'open_url':
            url = params.get('url', '') if isinstance(params, dict) else ''
            if url:
                url = resolve_var(url, data_dict)
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    _smart_wait_after_action(page)
                except Exception as e:
                    print(f"    [ERROR] open_url failed: {str(e)[:80]}")
        elif keyword == 'refresh':
            try:
                page.reload(wait_until='domcontentloaded', timeout=30000)
                _smart_wait_after_action(page)
            except Exception as _e:
                print(f"    [WARN] page.reload 失败: {_e}")
        return None, None, False, False, None

    # Skip assertions (Phase 9 responsibility)
    # BUG-4b: added except_element_count (assertion keyword with locator, not for Phase 6)
    if keyword in ('except_to_be_visible', 'except_to_have_text',
                   'except_to_have_value', 'except_element_count'):
        return None, None, False, False, None

    # P2-3: l3_call is expanded in the caller — skip here
    if keyword in L3_KEYWORDS:
        return None, None, False, False, None

    # V5: Custom L3 workflow names are also expanded in the caller
    if project_dir:
        _wf_cache = _load_l3_workflows(project_dir)
        if keyword in _wf_cache:
            return None, None, False, False, None

    # Extract locator
    locator = ''
    if isinstance(params, dict):
        locator = params.get('locator', '')
    if not locator:
        return None, None, False, False, None

    # BUG-7 fix: save raw locator reference before resolution for suffix detection
    raw_locator_ref = locator

    # Resolve variable references
    locator = resolve_locator(params, pages_dict)

    # Extract label from desc for KB lookup
    # BUG-4 D1 fix: 增加「」匹配（中文角括号在测试用例中极为常见）
    # 匹配: ASCII “, 左弯引号 U+201C, 右弯引号 U+201D, 左角括号 U+300C
    # F3: 提取所有引号对，取最后一个（实际操作对象）
    # 单引号对: re.findall[-1] 与 re.search 结果相同，零影响
    # 多引号对: “点击「第」一条记录的「更多」按钮” → ['第', '更多'] → '更多'
    _all_labels = re.findall(r'["\'“”「]([^"\'“”「」]+)["\'“”」]', desc)
    label = _all_labels[-1] if _all_labels else ''

    # D4: Enhanced element type inference (unified in _element_types)
    # BUG-3 fix: can now produce 'table-action-button'
    # BUG-5 fix: can now produce 'detail-link'
    # BUG-7 fix: pass locator_ref for _select/_editable suffix detection
    elem_type = _infer_elem_type(keyword, desc, locator_ref=raw_locator_ref)
    # [TRACE-P6] 类型推断结果
    print(f"    [TRACE-P6] infer: label='{label}', elem_type={elem_type}")

    # Fix-2b-A: 类型推断 + discovery 交叉验证
    # _infer_elem_type 是纯函数（不依赖 discovery），对"编辑/删除/查看/详情"
    # 无条件返回 table-action-button。但同一文本在不同模块可能是工具栏按钮或行按钮。
    # 用 discovery 数据交叉验证：如果 label 在 buttons 区但不在 row_buttons 区，修正为 button。
    if elem_type == 'table-action-button' and discovery_data and label:
        _lp = discovery_data.get('list_page', {})
        _disc_containers = discovery_data.get('containers', [])
        _get_lbl = lambda e: (e.get('text', '') or e.get('label', '')
                              or e.get('name', ''))
        # 检查 row_buttons（list_page + containers 内的行按钮）
        _in_row_btns = any(
            _get_lbl(e) == label
            for e in _lp.get('row_buttons', [])
        )
        if not _in_row_btns:
            # 也搜索 containers 中的元素（行按钮可能在容器内）
            _in_row_btns = any(
                _get_lbl(e) == label
                for c in _disc_containers
                for e in c.get('elements', [])
                if (e.get('type', '') == 'table-action-button'
                    or e.get('is_row_button', False))
            )
        _in_btns = any(
            _get_lbl(e) == label
            for e in _lp.get('buttons', [])
        )
        if not _in_row_btns and _in_btns:
            print(f"    [TYPE-CORRECTION] '{desc}' label='{label}': "
                  f"table-action-button → button "
                  f"(discovery: in buttons, not in row_buttons)")
            elem_type = 'button'

    # Detect current visible containers (7.10: skip if on new page — no container context)
    # BUG-1b 修复：容器检测提前到 discovery 查找之前，传入 preferred_container
    visible_containers = detect_visible_containers(page) if not is_new_page_context else []
    current_ct = None
    if visible_containers:
        for ct in CONTAINER_TYPES:
            if ct in visible_containers:
                current_ct = ct
                break

    # 容器上下文 fallback：当 detect_visible_containers 返回空但有上一步传递的容器上下文时使用
    if current_ct is None and container_context and not is_new_page_context:
        current_ct = container_context
        print(f"    [CONTEXT] detect_visible_containers 返回空，使用上次容器上下文: {container_context}")

    # ── 统一兜底前缀计算（M11/R5 共用）──
    # 规则：确认类按钮 → el-dialog | 新页面 → 无前缀 | 其他 → current_ct 优先，默认 drawer
    if is_new_page_context:
        _fallback_prefix = 'none'
        _fallback_prefix_str = ''
    elif label in DIALOG_CONFIRM_LABELS:
        _fallback_prefix = 'dialog'
        _fallback_prefix_str = CONTAINER_XPATH.get('dialog', '')
    else:
        _fallback_prefix = current_ct if current_ct else 'drawer'
        _fallback_prefix_str = CONTAINER_XPATH.get(_fallback_prefix, '')

    # Build candidate locators
    # Priority: KB → Discovery → Original (stable order, reverted from Discovery-first)
    candidates = []

    # M9: 占位符检测 — xpath=[待确认] 不是真实 locator，跳过作为候选
    is_placeholder = locator in ('xpath=[待确认]', '[待确认]')

    # 优先级 0: KB templates (highest priority — stable, universal XPath patterns)
    if label:
        kb_locators = _get_kb_locators(elem_type, label)
        for kb_xpath in kb_locators:
            candidates.append((kb_xpath, 'kb'))

    # 优先级 1: Discovery locator (Phase 4 verified)
    discovery_ct = None
    _discovery_verified = False  # Fix-6 条件：跟踪 discovery 是否已验证
    if discovery_data and label:
        disc_locator, discovery_ct = _find_in_discovery(
            discovery_data, label, preferred_container=current_ct,
            elem_type=elem_type)
        # [TRACE-P6] discovery 查找结果
        print(f"    [TRACE-P6] discovery: found={disc_locator is not None}, "
              f"discovery_ct={discovery_ct}")
        if disc_locator:
            print(f"    [TRACE-P6]   disc_locator={disc_locator[:100]}{'...' if len(disc_locator) > 100 else ''}")
            _discovery_verified = True  # _find_in_discovery 只返回 verified=true 的元素
            disc_raw = (disc_locator.replace('xpath=', '')
                        if disc_locator.startswith('xpath=')
                        else disc_locator)
            # 去重（KB 可能和 discovery 一样）
            if not any(c[0] == disc_raw for c in candidates):
                candidates.append((disc_raw, 'discovery'))

    # F2: candidates 为空时，将有效 locator 加入候选
    #
    # 触发条件（全部满足）:
    #   1. locator 非未解析变量（不以 ${ 开头）
    #   2. 非 [待确认] 占位符
    #   3. 非空且长度合理
    #
    # Fix-6: 始终将原始 locator 加入候选池尾部作为安全网（去掉 candidates==0 条件）
    # 原因：即使 KB 产生了候选（可能用错误 label 生成），原始 locator 来自 Phase 5
    #       的 _track_field，基于 Excel 单元格值构建，比 KB 候选更可靠。
    # 不影响 KB 优先级：原始 locator 在候选尾部，KB/discovery 候选优先验证。
    if (not locator.startswith('${')       # guard 1: 非未解析变量
        and not is_placeholder             # guard 2: 非占位符
        and locator                        # guard 3a: 非空
        and len(locator) > 5):             # guard 3b: 非退化值
        _resolved_bare = (locator.replace('xpath=', '', 1)
                          if locator.startswith('xpath=') else locator)
        if not any(c[0] == _resolved_bare for c in candidates):    # Fix-6: 去重
            candidates.append((_resolved_bare, 'original'))   # Fix-6: 始终加入尾部作为安全网

    # Priority 3: Click-type wildcard fallback — last resort for click steps only
    # Only applies to button/table-action-button/detail-link types.
    # Excluded: input-generic, el-select, textarea, tab, checkbox, etc.
    # Guarded by [1] to avoid count>1 strict mode violation.
    if elem_type in CLICK_EXPAND_TYPES and label:
        _click_fb = f"(//*[contains(text(),'{label}')])[1]"
        if not any(c[0] == _click_fb for c in candidates):
            candidates.append((_click_fb, 'kb-fallback'))

    # Verify candidates × prefixes (P1-2: el-select input gets container prefix normally)
    # Split candidates into xpaths and sources for return_index lookup
    xpaths = [c[0] for c in candidates]
    sources = {i: c[1] for i, c in enumerate(candidates)}

    # [TRACE-P6] 候选列表（进入 verify_locator_candidates 前）
    print(f"    [TRACE-P6] execute_step: desc='{desc[:50]}', elem_type={elem_type}, label='{label}'")
    print(f"    [TRACE-P6]   current_ct={current_ct}, fallback_prefix={_fallback_prefix}")
    print(f"    [TRACE-P6]   candidates ({len(candidates)}):")
    for ci, (cx, cs) in enumerate(candidates):
        print(f"    [TRACE-P6]     [{ci}] src={cs}: {cx[:100]}{'...' if len(cx) > 100 else ''}")

    verified_locator, matched_prefix, count, matched_index = verify_locator_candidates(
        page, xpaths, container_type=current_ct, discovery_ct=discovery_ct,
        is_el_select_option=False, return_index=True
    )

    # Determine hit source
    hit_source = sources.get(matched_index) if matched_index is not None else None

    # [TRACE-P6] VLC 返回结果
    print(f"    [TRACE-P6]   VLC result: verified={'Yes' if verified_locator else 'No'}, "
          f"prefix={matched_prefix}, count={count}, "
          f"hit_source={hit_source}, matched_index={matched_index}")
    if verified_locator:
        print(f"    [TRACE-P6]   verified_locator: {verified_locator[:120]}")

    # R4: Multi-type retry — collect alternative types when initial type fails
    # Sources: keyword/desc inference, DOM check (R3), locator_ref suffix
    # Weight only affects try order, no type is excluded.
    if not verified_locator and label:
        _alt_types = [elem_type]  # primary type first (already tried)

        # Source: keyword/desc re-inference (already captured in elem_type, skip dup)
        # Source: DOM check (R3 — highest priority, only when fast path failed)
        # BUG-11: 类型守卫 — R3 结果必须通过兼容性检查才能插入 _alt_types
        _dom_type = _detect_actual_element_type(page, label, CONTAINER_XPATH.get(current_ct, '') if current_ct else '')
        if _dom_type and _dom_type not in _alt_types:
            _compat_set = _R3_TYPE_COMPAT.get(elem_type, {elem_type})
            if _dom_type in _compat_set:
                _alt_types.insert(1, _dom_type)  # insert after primary (DOM = high priority)
                print(f"    [DOM-CHECK] inferred={elem_type}, DOM detected={_dom_type}")
            else:
                print(f"    [DOM-CHECK] REJECTED: inferred={elem_type}, "
                      f"DOM detected={_dom_type} (incompatible with {_compat_set})")

        # Source: common cross-type confusions (input↔textarea)
        if elem_type == 'input-generic' and 'textarea-generic' not in _alt_types:
            _alt_types.append('textarea-generic')
        elif elem_type == 'textarea-generic' and 'input-generic' not in _alt_types:
            _alt_types.append('input-generic')
        # Source: button → table-action-button fallback
        # 仅遍历结构泛化的按钮 KB（所有 pattern 含 {label}，不会假阳性）。
        # download-button / search-button 属于特殊场景，由 Phase 5 类型推断
        # 根据 Excel 描述关键词（导出/下载/搜索/查询）直接匹配，不参与 R4 遍历。
        elif elem_type == 'button':
            if 'table-action-button' not in _alt_types:
                _alt_types.append('table-action-button')
        # Fix-2b-B: 反向回退 — 子类型 → button
        # 当 _infer_elem_type 返回子类型（如 table-action-button）但 KB 和 discovery
        # 均未验证通过时，尝试基类 button 作为安全网。
        # 与 Fix-2b-A 互补：A 在入口处修正类型，B 在 R4 重试时兜底。
        elif elem_type in ('table-action-button', 'search-button', 'download-button', 'close-button'):
            if 'button' not in _alt_types:
                _alt_types.append('button')

        # [TRACE-P6] R4 alt_types 列表
        print(f"    [TRACE-P6]   R4 alt_types: {_alt_types}")

        # Try each alternative type (skip first = already tried in fast path)
        for _alt_type in _alt_types[1:]:
            _alt_candidates = []

            # KB locators for this type - Priority 0 (highest)
            _alt_kb = _get_kb_locators(_alt_type, label)
            for _alt_kb_xpath in _alt_kb:
                _alt_candidates.append((_alt_kb_xpath, 'kb'))

            # Discovery locator (with relaxed type guard) - Priority 1
            if discovery_data:
                _alt_disc, _alt_disc_ct = _find_in_discovery(
                    discovery_data, label, preferred_container=current_ct,
                    elem_type=_alt_type)
                if _alt_disc:
                    _alt_disc_raw = (_alt_disc.replace('xpath=', '')
                                    if _alt_disc.startswith('xpath=') else _alt_disc)
                    # 去重
                    if not any(c[0] == _alt_disc_raw for c in _alt_candidates):
                        _alt_candidates.append((_alt_disc_raw, 'discovery'))

            # Priority 3: Click-type wildcard fallback — last resort for click steps only
            if _alt_type in CLICK_EXPAND_TYPES and label:
                _click_fb = f"(//*[contains(text(),'{label}')])[1]"
                if not any(c[0] == _click_fb for c in _alt_candidates):
                    _alt_candidates.append((_click_fb, 'kb-fallback'))

            if not _alt_candidates:
                continue

            # [TRACE-P6] R4 每个 alt_type 的候选列表
            print(f"    [TRACE-P6]   R4 trying alt_type={_alt_type}, {len(_alt_candidates)} candidates")
            for aci, (acx, acs) in enumerate(_alt_candidates):
                print(f"    [TRACE-P6]     [{aci}] src={acs}: {acx[:100]}{'...' if len(acx) > 100 else ''}")

            # Split into xpaths and sources
            _alt_xpaths = [c[0] for c in _alt_candidates]
            _alt_sources = {i: c[1] for i, c in enumerate(_alt_candidates)}

            _alt_vl, _alt_mp, _alt_cnt, _alt_idx = verify_locator_candidates(
                page, _alt_xpaths, container_type=current_ct,
                discovery_ct=discovery_ct, is_el_select_option=False,
                return_index=True
            )
            if _alt_vl:
                verified_locator = _alt_vl
                matched_prefix = _alt_mp
                elem_type = _alt_type  # update type for subsequent operations
                hit_source = _alt_sources.get(_alt_idx)
                print(f"    [TYPE-CORRECT] '{desc}' → {_alt_type} "
                      f"(corrected from initial type)")
                break

    if not verified_locator:
        # D5: Try KB fallback before giving up
        if label:
            fb = kb_fallback(elem_type, label, label)
            # [TRACE-P6] kb_fallback 调用结果
            print(f"    [TRACE-P6] kb_fallback: result={'found' if fb and fb.get('locator') else 'None'}")
            if fb and fb.get('locator'):
                print(f"    [TRACE-P6]   strategy={fb.get('strategy', 'unknown')}")
                print(f"    [TRACE-P6]   fb_locator={fb['locator'][:100]}{'...' if len(fb['locator']) > 100 else ''}")
                fb_locator = inject_hidden_filter(fb['locator'])
                _fb_result = _verify_count_or_first(page, fb_locator)
                print(f"    [TRACE-P6]   _verify_count_or_first: result={'passed' if _fb_result else 'failed'}")
                if _fb_result:
                    verified_locator = _fb_result
                    print(f"    [KB-FALLBACK] '{desc}' → {fb.get('strategy', 'unknown')}")

        # Scheme 4: 跨类型 fallback — input-generic 失败时尝试 textarea-generic
        # 解决 Phase 5 将 textarea 字段误标为 _input 后缀的场景 D
        if not verified_locator and label and elem_type == 'input-generic':
            _CROSS_TYPE_ALIASES = ['textarea-generic']
            for _cross_type in _CROSS_TYPE_ALIASES:
                fb_cross = kb_fallback(_cross_type, label, label)
                if fb_cross and fb_cross.get('locator'):
                    fb_locator = inject_hidden_filter(fb_cross['locator'])
                    _fb_result = _verify_count_or_first(page, fb_locator)
                    if _fb_result:
                        verified_locator = _fb_result
                        print(f"    [KB-FALLBACK] '{desc}' → {_cross_type} "
                              f"(cross-type fallback from {elem_type})")
                        break

        # D1: Structured fallback rules if KB fallback also failed
        if not verified_locator:
            # [TRACE-P6] D1/M11 兜底决策入口
            print(f"    [TRACE-P6] D1/M11 fallback: label='{label}', in_dialog_confirm={label in DIALOG_CONFIRM_LABELS}, has_candidates={len(candidates) > 0}")
            if label in DIALOG_CONFIRM_LABELS:
                # 确认/取消按钮 → default el-dialog prefix
                fallback_xpath = f"//div[contains(@class,'el-dialog')]//button[contains(.,'{label}')]"
                fallback_xpath = inject_hidden_filter(f"xpath={fallback_xpath}")
                print(f"    [TRACE-P6]   D1 dialog-confirm: {fallback_xpath[:100]}")
                _fb_result = _verify_count_or_first(page, fallback_xpath)
                print(f"    [TRACE-P6]   D1 result: {'passed' if _fb_result else 'failed'}")
                if _fb_result:
                    verified_locator = _fb_result
                    print(f"    [FALLBACK] '{desc}' → dialog-confirm")
            elif candidates:
                # M11: KB locator优先兜底，candidates[0] 最后回退
                # 使用函数开头计算的统一前缀变量 _fallback_prefix / _fallback_prefix_str

                # M11 修复: 优先用 KB locator 兜底，不用 candidates[0]
                _m11_resolved = False
                if label:
                    kb_locators = _get_kb_locators(elem_type, label)
                    print(f"    [TRACE-P6]   M11 KB fallback: {len(kb_locators)} locators, prefix={_fallback_prefix_str[:50]}")
                    for i, kb_loc in enumerate(kb_locators):
                        fallback_xpath = inject_hidden_filter(
                            f"xpath={_fallback_prefix_str}{kb_loc}")
                        print(f"    [TRACE-P6]     M11[{i}]: {fallback_xpath[:100]}")
                        _fb_result = _verify_count_or_first(page, fallback_xpath)
                        print(f"    [TRACE-P6]     M11[{i}] result: {'passed' if _fb_result else 'failed'}")
                        if _fb_result:
                            verified_locator = _fb_result
                            print(f"    [FALLBACK] '{desc}' → KB-{elem_type} with {_fallback_prefix} prefix (M11)")
                            _m11_resolved = True
                            break

                    # Scheme 4 (M11): 跨类型 fallback — input-generic 失败时尝试 textarea-generic
                    if not _m11_resolved and elem_type == 'input-generic':
                        for _cross_type in ('textarea-generic',):
                            cross_kb_locators = _get_kb_locators(_cross_type, label)
                            for kb_loc in cross_kb_locators:
                                fallback_xpath = inject_hidden_filter(
                                    f"xpath={_fallback_prefix_str}{kb_loc}")
                                _fb_result = _verify_count_or_first(page, fallback_xpath)
                                if _fb_result:
                                    verified_locator = _fb_result
                                    print(f"    [FALLBACK] '{desc}' → KB-{_cross_type} "
                                          f"with {_fallback_prefix} prefix (M11 cross-type)")
                                    _m11_resolved = True
                                    break
                            if _m11_resolved:
                                break

                # KB locator 全部失败时，回退到第一个 KB candidate（原 M11 逻辑）
                if not _m11_resolved:
                    # BUG-14 fix: candidates 是 list[tuple]，需解包取 c[0] xpath 和 c[1] source
                    first_kb_candidate = next((c[0] for c in candidates if c[1] == 'kb'), None)
                    if first_kb_candidate is None:
                        first_kb_candidate = candidates[0][0] if candidates else None
                    if first_kb_candidate:
                        fallback_xpath = inject_hidden_filter(
                            f"xpath={_fallback_prefix_str}{first_kb_candidate}")
                        print(f"    [TRACE-P6]   M11 first-kb-candidate: {fallback_xpath[:100]}")
                        _fb_result = _verify_count_or_first(page, fallback_xpath)
                        print(f"    [TRACE-P6]   M11 first-kb-candidate result: {'passed' if _fb_result else 'failed'}")
                        if _fb_result:
                            verified_locator = _fb_result
                            print(f"    [FALLBACK] '{desc}' → first-kb-candidate with {_fallback_prefix} prefix (M11)")

        # Fix-6: 仅当 discovery 已验证时保留 Phase 5 原始 locator
        # 设计意图（三层优先级）：
        #   1. KB 验证成功 → 使用 KB locator（主验证路径）
        #   2. KB 失败 + discovery 已验证 → 保留原始值（discovery 已验证的同值候选已尝试）
        #   3. KB 失败 + discovery 未验证 → R5 KB 兜底回写（比可能错误的原始值更可靠）
        if not verified_locator and _discovery_verified:
            # [TRACE-P6] Fix-6 路径
            print(f"    [TRACE-P6] Fix-6: attempting to preserve original locator (discovery was verified)")
            _orig_ref = _extract_locator_ref(step)
            _orig_xpath = _get_original_xpath(_orig_ref, pages_dict) if _orig_ref else ''
            print(f"    [TRACE-P6]   _orig_ref={_orig_ref}, _orig_xpath={_orig_xpath[:80] if _orig_xpath else 'None'}")
            if (_orig_xpath
                and _orig_xpath not in ('[待确认]', '')
                and len(_orig_xpath) > 10
                and not _orig_xpath.startswith('${')):
                _preserved_locator = (f"xpath={_orig_xpath}"
                                   if not _orig_xpath.startswith('xpath=')
                                   else _orig_xpath)
                # 防御性：count>1 时自动 [1] 收窄（与 M11/R5 兜底路径一致）
                # 场景：discovery 已验证 count=1，但 Phase 6 验证时因表格异步
                # 加载等原因 count>1，运行时可能仍多匹配
                _preserved_narrowed = _verify_count_or_first(page, _preserved_locator)
                if _preserved_narrowed:
                    verified_locator = _preserved_narrowed
                    is_best_guess = True
                    _p_note = ('已 [1] 收窄' if _preserved_narrowed != _preserved_locator
                               else 'count=1')
                    print(f"    [PRESERVED] '{desc}' → 保留 Phase 5 原始 locator "
                          f"(discovery verified, {_p_note})")
                else:
                    # count==0：加 [1] 防御 Phase 9 strict mode
                    # 场景：验证时元素不可见（count=0），Phase 9 运行时前序步骤执行后元素出现
                    # 但可能出现多个匹配（如表格行按钮），[1] 防止 strict mode violation
                    _raw = (_preserved_locator.replace('xpath=', '', 1)
                            if _preserved_locator.startswith('xpath=')
                            else _preserved_locator)
                    verified_locator = f"xpath=({_raw})[1]"
                    is_best_guess = True
                    print(f"    [PRESERVED] '{desc}' → 保留 Phase 5 原始 locator "
                          f"(discovery verified, count=0, [1] 防御)")

        if not verified_locator:
            # ── R5: KB locator 兜底回写（规则 6 修复）──
            # 即使 count=0，也用 KB locator 回写（比 [待确认] 更有价值）
            # 理由：KB locator 结构正确，count=0 通常因为容器未打开，
            #       Phase 9 运行时前序步骤正确执行后大概率能命中。
            # [TRACE-P6] R5 入口
            print(f"    [TRACE-P6]   R5 fallback: entering (no verified_locator)")
            _bg_locator = None
            _bg_source = None

            # 使用函数开头计算的统一前缀变量 _fallback_prefix_str

            # 优先级 1: KB 模板 locator（推断类型 + 容器前缀）
            if label:
                kb_locs = _get_kb_locators(elem_type, label)
                if kb_locs:
                    _bg_locator = inject_hidden_filter(
                        f"xpath={_fallback_prefix_str}{kb_locs[0]}")
                    _bg_source = f'KB-{elem_type}'

            # 优先级 2: KB fallback 函数
            if not _bg_locator and label:
                fb = kb_fallback(elem_type, label, label)
                if fb and fb.get('locator'):
                    _bg_raw = fb['locator'].replace('xpath=', '') if fb['locator'].startswith('xpath=') else fb['locator']
                    _bg_locator = inject_hidden_filter(
                        f"xpath={_fallback_prefix_str}{_bg_raw}")
                    _bg_source = f'KB-fallback-{elem_type}'

            # 优先级 3: 第一个 KB candidate 的 xpath（优先），否则第一个 candidate
            if not _bg_locator and candidates:
                _first_kb_c = next((c[0] for c in candidates if c[1] == 'kb'), None)
                _fallback_xpath = _first_kb_c if _first_kb_c else candidates[0][0]
                _bg_locator = inject_hidden_filter(
                    f"xpath={_fallback_prefix_str}{_fallback_xpath}")
                _bg_source = 'first-kb-candidate' if _first_kb_c else 'first-candidate'

            # [TRACE-P6] R5 _bg_locator 计算结果
            print(f"    [TRACE-P6]   R5 _bg_source={_bg_source}")
            print(f"    [TRACE-P6]   R5 _bg_locator={_bg_locator[:120] if _bg_locator else 'None'}")

            if _bg_locator:
                # 防御性：count>1 时自动 [1] 收窄（与 M11 兜底路径一致）
                # 场景：表格异步加载未完成时 count=0，加载完 count>1（行按钮等）
                # 若不做 [1] 收窄，Phase 9 运行时 strict mode violation
                _bg_narrowed = _verify_count_or_first(page, _bg_locator)
                if _bg_narrowed:
                    # count==1 或 count>1 已收窄 → 使用收窄后的 locator
                    verified_locator = _bg_narrowed
                    _bg_note = ('已 [1] 收窄' if _bg_narrowed != _bg_locator
                                else 'count=1')
                else:
                    # count==0：加 [1] 防御 Phase 9 strict mode（与 Fix-6 对齐）
                    # 场景：验证时元素不可见，Phase 9 运行时可能出现多个匹配
                    _raw = (_bg_locator.replace('xpath=', '', 1)
                            if _bg_locator.startswith('xpath=')
                            else _bg_locator)
                    verified_locator = f"xpath=({_raw})[1]"
                    _bg_note = 'count=0, [1] 防御'
                is_best_guess = True
                print(f"    [UNVERIFIED] '{desc}' → {_bg_source} "
                      f"({_bg_note}, 兜底回写)")
            else:
                # ── R6: KB 已穷尽，打印警告 ──
                # R5 失败意味着 KB 模板 + KB fallback + 第一个 candidate 全部 count=0
                # probe_element() 深度探测与 R5 的 KB 遍历重复，不再调用
                if is_placeholder:
                    print(f"    [WARN] '{desc}' → KB 已穷尽，locator 仍为 [待确认]，"
                          f"请检查前序步骤是否正确打开了容器")

                # ── R6: AI 兜底探测（新增）──
                if (_HAS_AI_PROBE and is_placeholder and label
                        and page is not None):
                    _r6 = _ai_probe_locator(
                        page, step, label, elem_type, current_ct,
                        steps_so_far, container_context, inject_hidden_filter)
                    if _r6:
                        verified_locator = _r6['locator']
                        is_best_guess = _r6['is_best_guess']
                        hit_source = _r6['hit_source']

                # 走原有逻辑
                if not verified_locator:
                    is_best_guess = False
                    hit_source = None
                    if is_placeholder:
                        print(f"    [WARN] 占位符步骤 '{desc}' 验证失败 — "
                              f"KB 和 discovery 均未匹配，请检查前序步骤是否正确打开了容器")
                    else:
                        print(f"    [FALLBACK] '{desc}' — no candidate matched, KB 无覆盖")
                    return None, current_ct, False, False, hit_source

    # Execute the step
    try:
        # click_select_option: 引擎内部处理 el-select 全流程，
        # Phase 6 只需验证触发器 locator 存在 + 点击展开
        if keyword == 'click_select_option':
            page.locator(verified_locator).click(timeout=5000)  # 方案 B: 严格模式
            # 验证下拉面板出现（证明触发器有效）
            panel_xpath = ("xpath=//div[contains(@class,'el-select-dropdown') "
                           "and not(contains(@style,'display: none'))]")
            try:
                page.locator(panel_xpath).first.wait_for(
                    state='visible', timeout=3000)
            except Exception:
                pass  # 面板未出现不阻断验证
            # 关闭下拉（点空白区域）
            try:
                page.locator("xpath=//body").click(position={'x': 10, 'y': 10})
            except Exception:
                pass
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        if 'click' in keyword:
            # Check destructive operation protection
            if keyword in ('confirm_dialog', 'confirm_delete') or ('确' in desc and '定' in desc):
                if should_skip_confirm(steps_so_far):
                    print(f"    [SKIP] '{desc}' — destructive operation protection")
                    return verified_locator, matched_prefix or current_ct, True, is_best_guess, hit_source

            # BUG-9: For row buttons (ancestor::tbody), hover the row first to reveal hidden buttons
            if 'tbody' in verified_locator:
                try:
                    row = page.locator("xpath=(//tr[contains(@class,'el-table__row')])[1]")
                    if row.count() > 0:
                        row.first.hover()
                        page.wait_for_timeout(500)
                except Exception:
                    pass  # hover failure is non-fatal, click may still succeed

            # M10: detail-link 类型验证时检查 tagName（防止匹配到 <th> 表头）
            if elem_type == 'detail-link' and verified_locator:
                try:
                    _tag = page.locator(verified_locator).first.evaluate(
                        "e => e.tagName.toLowerCase()")
                    if _tag == 'th':
                        print(f"    [WARN] M10: '{desc}' locator匹配到<th>表头，"
                              f"预期<td>或链接元素")
                except Exception:
                    pass  # tag check 失败不影响主流程

            page.locator(verified_locator).click(timeout=5000)  # 方案 B: 严格模式
            # [TRACE-P6] click 成功后：记录页面 URL
            try:
                _post_click_url = page.url
                _post_click_title = page.title()
                print(f"    [TRACE-P6]   click success: url={_post_click_url[:80]}, title={_post_click_title[:40]}")
            except Exception:
                pass
            # P3-2: smart wait replaces fixed 500ms (含 DOM 稳定检测)
            _smart_wait_after_action(page)

            # ── 容器探测：每次 click 后都执行（排除下拉框 click_select_option）──
            # 原因：任何 click 都可能打开容器（确定→二次确认弹窗，删除→确认弹窗等）
            #
            # 时序：
            #   1. detect_visible_containers() — 快速检查（~5ms），如果容器已渲染完就直接返回
            #   2. _wait_for_container_after_click() — Playwright wait_for（事件驱动，容器一出现立即返回）
            #      场景：API 回调触发的容器（先 networkidle → 再渲染），_smart_wait 可能早于容器出现
            #
            # 对于不打开容器的 click（搜索/查询等），wait_for 在 2s 后超时返回 None，
            # 加上 _smart_wait 8s，单个 click 最多 ~10s。
            new_containers = detect_visible_containers(page)
            # [TRACE-P6] 容器探测结果
            print(f"    [TRACE-P6]   containers after click: {list(new_containers.keys()) if new_containers else 'none'}")
            if not new_containers:
                # 快速检查未检测到 → 增强等待（容器可能在 API 回调后异步出现）
                container_ct = _wait_for_container_after_click(page)
                if container_ct:
                    _wait_for_dom_stable(page, timeout_ms=3000)
                    # [TRACE-P6] 异步容器出现
                    print(f"    [TRACE-P6]   async container detected: {container_ct}")
                    return verified_locator, container_ct, False, is_best_guess, hit_source
            else:
                # 快速检查已检测到容器 → 等待内部表单渲染
                _wait_for_dom_stable(page, timeout_ms=3000)
                for ct in CONTAINER_TYPES:
                    if ct in new_containers:
                        return verified_locator, ct, False, is_best_guess, hit_source
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif 'fill' in keyword:
            value = params.get('value', '') if isinstance(params, dict) else ''
            value = resolve_var(value, data_dict)
            if not value:
                value = PROBE_FILL_VALUES.get('input', PROBE_ISOLATION_PREFIX + 'P3f')
            # P2-6: prepend isolation prefix if not already present
            if not value.startswith(PROBE_ISOLATION_PREFIX):
                value = PROBE_ISOLATION_PREFIX + value
            # 1c: iframe 填充支持 — 检测 locator 是否指向 iframe 元素
            _vl_clean = verified_locator.replace('xpath=', '') if verified_locator.startswith('xpath=') else verified_locator
            if 'iframe' in _vl_clean.lower():
                try:
                    iframe_el = page.locator(verified_locator)
                    if iframe_el.count() > 0:
                        frame = iframe_el.first.content_frame()
                        if frame:
                            editor = frame.locator(
                                'body[contenteditable="true"], body.mce-content-body, '
                                'body.ql-editor, textarea, [role="textbox"]'
                            )
                            if editor.count() > 0:
                                editor.first.fill(value, timeout=5000)
                                print(f"    [OK] 1c iframe fill: '{desc}'")
                                return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source
                            else:
                                print(f"    [WARN] iframe 内未找到可编辑元素，尝试标准 fill")
                        else:
                            print(f"    [WARN] 无法进入 iframe context，尝试标准 fill")
                except Exception as e:
                    print(f"    [WARN] iframe fill 异常: {str(e)[:80]}，尝试标准 fill")
            # Perf: 对 el-select 触发器（readonly input 或 div），快速检测并跳过 fill
            # 避免 5 秒超时浪费（Phase 6 目标是验证 locator，不是测试 fill 功能）
            try:
                el = page.locator(verified_locator).first
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                if tag != 'textarea':
                    is_readonly = el.evaluate(
                        "e => e.hasAttribute('readonly') || e.getAttribute('role') === 'combobox'"
                        " || e.closest('.el-select') !== null"
                    )
                    if is_readonly:
                        # readonly el-select 触发器 — 验证 locator 存在即可，跳过 fill
                        return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source
            except Exception:
                pass  # 检测失败则走正常 fill 流程

            page.locator(verified_locator).fill(value, timeout=5000)
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword.startswith('frame_'):
            # iframe operations — skip for now (Phase 6 实现时启用)
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'wait_for_element_visible':
            page.locator(verified_locator).first.wait_for(state='visible', timeout=5000)
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'wait_for_element_hidden':
            try:
                page.locator(verified_locator).first.wait_for(state='hidden', timeout=5000)
            except Exception:
                pass
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'get_text':
            try:
                text = page.locator(verified_locator).first.text_content(timeout=3000)
            except Exception:
                text = ''
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword == 'get_element_count':
            try:
                cnt = page.locator(verified_locator).count()
            except Exception:
                cnt = 0
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        else:
            # Unknown keyword — just verify locator exists
            count = page.locator(verified_locator).count()
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

    except Exception as e:
        print(f"    [ERROR] '{desc}': {str(e)[:100]}")
        return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

