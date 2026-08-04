"""
verify_orchestrator.py - 验证编排器主入口

从 verify_locators.py 提取的主编排函数：
- verify_project: 主验证流程
- main: CLI 入口点
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

# Ensure tools/ is on sys.path for core/generation/probe/verification imports
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("[FATAL] pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ─── Shared imports ───
from core.yaml_utils import escape_yaml_scalar as _escape_yaml_scalar
from core.wait_utils import wait_for_dom_stable as _wait_for_dom_stable
from core.xpath_utils import (
    inject_hidden_filter, has_hidden_filter, CONTAINER_XPATH,
    apply_hidden_filters_to_pages, strip_not_ancestor_from_pages,
)
from core.field_suffixes import DIALOG_CONFIRM_LABELS
from core.element_types import (
    TYPE_TO_SECTIONS as _TYPE_COMPATIBLE_SECTIONS,
    ALL_LIST_SECTIONS as _ALL_LIST_SECTIONS,
    infer_discovery_section as _infer_discovery_section,
    infer_elem_type as _infer_elem_type,
    normalize_type as _normalize_type,
)
from probe.probe_element import (
    parse_cookie, detect_visible_containers,
    _xpath_escape_label, _safe_format, safe_count, TOKEN_KEYS,
)
from probe.probe_utils import (
    load_knowledge, get_kb_patterns, get_all_patterns,
    get_multi_step_patterns, kb_fallback, KB_KEY_ALIAS,
)
from generation.pages_writer import (
    _make_editable_locator as _make_editable_locator_from_select,
    _make_editable_locator_postfix,
)

# R6: AI probe functions (optional)
try:
    from probe.ai_probe import (
        ai_probe_locator as _ai_probe_locator,
        MARKER_MAP as _AI_MARKER_MAP,
        flush_diagnostics as _ai_probe_flush,
    )
    _HAS_AI_PROBE = True
except ImportError:
    _HAS_AI_PROBE = False
    _AI_MARKER_MAP = {}
    _ai_probe_flush = lambda *args, **kwargs: None

# ─── Sibling module imports ───
from verification.data_layer import (
    load_yaml_files, load_cases, load_pages, load_data,
    resolve_var, resolve_locator,
    _get_kb_locators, _find_in_discovery, _find_list_page_group,
    CLICK_EXPAND_TYPES,
)
from verification.verify_engine import (
    execute_step, _expand_l3_call, _load_l3_workflows,
    verify_locator_candidates, _verify_count_or_first,
    DESTRUCTIVE_TRIGGERS, CONTAINER_TYPES,
    NO_VERIFY_KEYWORDS, L3_KEYWORDS,
    PROBE_ISOLATION_PREFIX, PROBE_FILL_VALUES,
    _HAS_AI_PROBE,
)
from verification.pages_writeback import (
    update_pages_yaml, _store_verified_locator,
)
from verification.detail_links import (
    _write_verify_result, _consume_pending_detail_links,
)

def verify_project(project_dir, cookie, base_url, discovery_path=None, module=None, local_storage_override=None, headed=False):
    """Main verification flow.

    1. Load all project files
    2. Open browser
    3. Execute each case step-by-step
    4. Verify locators
    5. Write back pages YAML
    """
    print(f"\n{'='*60}")
    print(f"[Verify] Project: {project_dir}")
    print(f"[Verify] URL: {base_url}")
    print(f"{'='*60}\n")

    # Load project files
    # F5: pass module for scoped page loading (prevents cross-module collisions)
    pages_dict = load_pages(project_dir, module=module)
    data_dict = load_data(project_dir)
    cases = load_cases(project_dir, module)

    # Load discovery data
    discovery_data = None
    _v7_flat = None  # G7: V7 展平回退数据（None = 非 V7 或未加载）
    _discovery_pages_by_url = {}  # V7: URL → discovery page mapping

    # C: 自动发现 discovery 文件（如果未提供 --discovery 参数）
    if discovery_path is None:
        probe_dir = os.path.join(project_dir, '_probe')
        if os.path.isdir(probe_dir):
            # 优先级 1: 统一的多模块 discovery.json
            unified_path = os.path.join(probe_dir, 'discovery.json')
            if os.path.isfile(unified_path):
                discovery_path = unified_path
                print(f"[INFO] Auto-discover: {unified_path}")

            # 优先级 2: 模块专属的 discovery 文件
            if discovery_path is None and module:
                module_path = os.path.join(probe_dir, f'discovery_{module}.json')
                module_merged_path = os.path.join(probe_dir, f'discovery_{module}_merged.json')
                if os.path.isfile(module_merged_path):
                    discovery_path = module_merged_path
                    print(f"[INFO] Auto-discover: {module_merged_path}")
                elif os.path.isfile(module_path):
                    discovery_path = module_path
                    print(f"[INFO] Auto-discover: {module_path}")

    if discovery_path and os.path.isfile(discovery_path):
        with open(discovery_path, encoding='utf-8') as f:
            discovery_data = json.load(f)

        # C: 处理统一的多模块 discovery 格式
        if 'modules' in discovery_data and isinstance(discovery_data['modules'], list):
            if module:
                # 提取指定模块的数据
                for mod_data in discovery_data['modules']:
                    if mod_data.get('module') == module:
                        discovery_data = mod_data
                        print(f"[INFO] 从统一 discovery 提取模块: {module}")
                        break
                else:
                    # 未找到指定模块，使用展平的容器数据
                    discovery_data = {
                        'list_page': discovery_data.get('list_page', {}),
                        'containers': discovery_data.get('containers', []),
                    }
                    print(f"[WARN] 模块 {module} 未在统一 discovery 中找到，使用展平数据")
            else:
                # 未指定模块，使用展平的容器数据
                discovery_data = {
                    'list_page': discovery_data.get('list_page', {}),
                    'containers': discovery_data.get('containers', []),
                }
                print(f"[INFO] 使用统一 discovery 的展平数据")

        # V7: detect multi-page discovery format
        if 'pages' in discovery_data and isinstance(discovery_data['pages'], list):
            for dp in discovery_data['pages']:
                dp_url = dp.get('url', '')
                if dp_url:
                    # Store by both full URL and path segment for flexible matching
                    _discovery_pages_by_url[dp_url] = dp
                    # Also store by hash fragment (e.g., #/work-order/new-list)
                    parsed = urlparse(dp_url)
                    if parsed.fragment:
                        _discovery_pages_by_url[parsed.fragment] = dp
                    elif parsed.path:
                        _discovery_pages_by_url[parsed.path] = dp
            print(f"[INFO] V7: 多页面 discovery — {len(discovery_data['pages'])} pages")
            # G7: V7 数据预展平 — 合并所有页面的 list_page/containers，
            # 作为 URL 匹配失败时的回退数据源（_find_in_discovery 不支持 pages[] 格式）
            _v7_flat = {'list_page': {}, 'containers': []}
            _v7_sections = ('buttons', 'row_buttons', 'inputs', 'tabs',
                            'detail_links', 'checkboxes', 'menu_items')
            for dp in discovery_data['pages']:
                lp = dp.get('list_page', {})
                for sec in _v7_sections:
                    if sec in lp:
                        _v7_flat['list_page'].setdefault(sec, []).extend(lp[sec])
                _v7_flat['containers'].extend(dp.get('containers', []))
            _v7_flat_count = (sum(len(v) for v in _v7_flat['list_page'].values())
                              + sum(len(c.get('elements', [])) for c in _v7_flat['containers']))
            print(f"[INFO] V7 展平: {_v7_flat_count} 个元素（{len(_v7_flat['containers'])} 个容器）")
        else:
            _v7_flat = None  # 非 V7 格式，无需展平
        _top_containers = len(discovery_data.get('containers', []))
        if _top_containers:
            print(f"[INFO] Loaded discovery: {_top_containers} containers")
        elif _v7_flat:
            print(f"[INFO] Loaded discovery: V7 多页面格式（已展平）")

    if not cases:
        print("[WARN] No case files found")
        return

    print(f"[INFO] Loaded: {len(pages_dict)} page groups, {len(data_dict)} data entries, {len(cases)} cases")

    # Track verified locators
    verified_locators = {}  # {group.field: {locator, marker}}
    total_steps = 0
    verified_count = 0
    fallback_count = 0
    skipped_count = 0
    error_count = 0

    pw = sync_playwright().start()
    try:
        # headed=True 时有头模式，headed=False 时默认 headless
        browser = pw.chromium.launch(headless=not headed)
        if headed:
            print(f"[INFO] 浏览器以有头模式启动（headed=True）")
        domain = urlparse(base_url).hostname
        cookies = parse_cookie(cookie, domain)

        context = browser.new_context(no_viewport=True)
        context.add_cookies(cookies)

        # Build localStorage map: tokens from cookie (highest priority) + config + CLI
        # Priority order (later overwrites earlier):
        #   1. config.yaml local_storage (base defaults)
        #   2. CLI --local-storage override
        #   3. Cookie token keys (always win — prevents stale config.yaml from overriding fresh cookie)
        local_storage = {}

        # 1. Load from project config.yaml (cookie + local_storage section)
        config_path = os.path.join(project_dir, 'config.yaml')
        if os.path.isfile(config_path):
            try:
                with open(config_path, encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                if isinstance(cfg.get('local_storage'), dict):
                    for k, v in cfg['local_storage'].items():
                        local_storage[str(k)] = str(v)
                # R6: 读取 AI probe 配置并初始化
                if _HAS_AI_PROBE and cfg.get('ai_probe'):
                    _ai_probe_init(cfg['ai_probe'])
                    print(f"  R6: AI probe enabled (model: {cfg['ai_probe'].get('model', 'gpt-4o-mini')})")
            except Exception:
                pass

        # 2. CLI override: --local-storage '{"k":"v",...}'
        if local_storage_override:
            try:
                override = json.loads(local_storage_override)
                if isinstance(override, dict):
                    for k, v in override.items():
                        local_storage[str(k)] = str(v)
            except Exception as e:
                print(f"[WARN] --local-storage JSON parse failed: {e}")

        # 3. Cookie token keys always override (freshest source)
        for c in cookies:
            if c['name'] in TOKEN_KEYS:
                local_storage[c['name']] = c['value']

        page = context.new_page()

        # Perf: 预注入 localStorage 一次（避免每个 case 重复导航）
        _ls_injected = False

        for case_idx, case in enumerate(cases):
            case_name = case.get('name', case.get('_file', f'case_{case_idx}'))
            steps = case.get('steps', [])
            if not steps:
                continue

            print(f"\n[Case {case_idx+1}/{len(cases)}] {case_name}")

            # V7: 为每个 case 选择匹配的 discovery page
            # G7: V7 格式时默认使用展平数据（而非原始 pages[] 格式，_find_in_discovery 无法搜索）
            case_discovery = _v7_flat if _v7_flat else discovery_data
            if _discovery_pages_by_url:
                # Extract open_url from case steps to find target URL
                case_url = ''
                for s in steps:
                    if s.get('keyword') == 'open_url':
                        u = (s.get('params') or {}).get('url', '')
                        if u:
                            case_url = resolve_var(u, data_dict)
                            break
                # Match against discovery pages
                if case_url:
                    matched_dp = _discovery_pages_by_url.get(case_url)
                    if not matched_dp:
                        # Try matching by path/fragment
                        cp = urlparse(case_url)
                        matched_dp = (_discovery_pages_by_url.get(cp.fragment)
                                      or _discovery_pages_by_url.get(cp.path))
                    if matched_dp:
                        # Build a synthetic discovery_data from the matched page
                        case_discovery = {
                            'containers': matched_dp.get('containers', []),
                            'list_page': matched_dp.get('list_page', {}),
                        }
                        print(f"  [V7] discovery 匹配: {matched_dp.get('name', case_url)}")
                    else:
                        # G7: URL 匹配失败时使用展平数据（而非原始 V7 pages[] 格式）
                        if _v7_flat:
                            case_discovery = _v7_flat
                        print(f"  [V7 WARN] 无匹配的 discovery page: {case_url[:80]}"
                              + (" — 使用展平数据回退" if _v7_flat else ""))

            # Navigate to base URL for each case
            try:
                if not _ls_injected:
                    # 首次: goto → inject localStorage → reload (完整认证流程)
                    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    _wait_for_dom_stable(page, timeout_ms=4000)
                    for k, v in local_storage.items():
                        page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
                    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    _wait_for_dom_stable(page, timeout_ms=4000)
                    _ls_injected = True
                    # Check if redirected to login page (invalid cookie)
                    final_url = page.url
                    if '/login' in final_url or final_url.rstrip('/').endswith('login'):
                        print(f"  [ERROR] Redirected to login page — cookie invalid/expired")
                        print(f"  [ERROR] Aborting verification. Please provide a fresh cookie.")
                        return {
                            'total_steps': 0, 'verified': 0, 'skipped': 0,
                            'failed': 0, 'auth_error': True,
                        }
                else:
                    # 后续 case: 导航回首页（localStorage 已注入）
                    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    # SPA hash 路由不变时 goto 可能不触发全页面重载，
                    # reload 强制销毁 Vue app，清除残留 dialog/drawer wrapper
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    _wait_for_dom_stable(page, timeout_ms=4000)
            except Exception as e:
                print(f"  [ERROR] Navigation failed: {str(e)[:100]}")
                continue

            steps_so_far = []
            is_new_page_context = False  # D3: track if we're on a different page than baseline
            case_baseline_url = base_url
            container_context = None  # 容器上下文：跟踪上一个步骤检测到的容器类型

            for step_idx, step in enumerate(steps):
                total_steps += 1
                keyword = step.get('keyword', '')
                desc = step.get('desc', '')

                # P2-2: Handle sub-steps (if_element_visible, then_steps, else_steps)
                if keyword == 'if_element_visible':
                    params = step.get('params', {})
                    then_steps = params.get('then_steps', [])
                    else_steps = params.get('else_steps', [])
                    # Verify the condition locator
                    cond_locator_raw = step.get('params', {}).get('locator', '')
                    if cond_locator_raw:
                        cond_locator = resolve_locator(step.get('params', {}), pages_dict)
                        cond_timeout = step.get('params', {}).get('timeout', 5000)
                        if isinstance(cond_timeout, (int, float)):
                            cond_timeout = int(cond_timeout)
                        else:
                            cond_timeout = 5000
                        cond_timeout = max(cond_timeout, 3000)

                        # ===== DEBUG: Condition locator check =====
                        print(f"    [DEBUG-COND] ===== if_element_visible condition check =====")
                        print(f"    [DEBUG-COND] Step: {desc}")
                        print(f"    [DEBUG-COND] Raw locator: {cond_locator_raw}")
                        print(f"    [DEBUG-COND] Resolved locator: {cond_locator}")

                        # Remove .first, check actual count
                        try:
                            cond_count = page.locator(cond_locator).count()
                            print(f"    [DEBUG-COND] Count: {cond_count}")

                            if cond_count == 0:
                                print(f"    [DEBUG-COND] Result: count=0, will execute else_steps")
                            elif cond_count == 1:
                                # Unique match, check visibility
                                try:
                                    page.locator(cond_locator).first.wait_for(state='visible', timeout=cond_timeout)
                                    print(f"    [DEBUG-COND] Result: count=1, visible=True, will execute then_steps")
                                except Exception as e:
                                    cond_count = 0
                                    print(f"    [DEBUG-COND] Result: count=1 but wait_for failed: {str(e)[:80]}, will execute else_steps")
                            else:
                                # Multiple matches - try prefix traversal
                                print(f"    [DEBUG-COND] Result: count={cond_count} (strict mode violation), attempting prefix traversal")

                                # Extract xpath from locator
                                if cond_locator.startswith('xpath='):
                                    cond_xpath = cond_locator[6:]
                                else:
                                    cond_xpath = cond_locator

                                # Try prefix traversal with verify_locator_candidates
                                print(f"    [DEBUG-COND] Trying prefix traversal with {len(CONTAINER_TYPES)} container types + None")
                                v_loc, v_ct, v_count, v_idx = verify_locator_candidates(
                                    page, [cond_xpath],
                                    container_type=None,
                                    is_el_select_option=False,
                                    return_index=True
                                )

                                if v_loc and v_count == 1:
                                    print(f"    [DEBUG-COND] [OK] Prefix traversal SUCCESS: prefix={v_ct}, count={v_count}")
                                    print(f"    [DEBUG-COND]   Verified locator: {v_loc}")

                                    # Store the verified locator for the condition
                                    _store_verified_locator(
                                        v_loc, v_ct,
                                        {'params': {'locator': cond_locator_raw}},
                                        pages_dict,
                                        verified_locators,
                                        is_best_guess=False
                                    )
                                    print(f"    [DEBUG-COND]   Stored to verified_locators: {cond_locator_raw}")

                                    # Use the verified locator for condition check
                                    cond_locator = v_loc
                                    cond_count = 1
                                    print(f"    [DEBUG-COND] Result: prefix found, will execute then_steps")
                                else:
                                    print(f"    [DEBUG-COND] [FAIL] Prefix traversal FAILED: no valid prefix found")
                                    print(f"    [DEBUG-COND]   Tried: {CONTAINER_TYPES} + [None]")
                                    cond_count = 0
                                    print(f"    [DEBUG-COND] Result: will execute else_steps")

                        except Exception as e:
                            cond_count = 0
                            print(f"    [DEBUG-COND] [FAIL] Exception during count/visibility check: {str(e)[:100]}")
                            print(f"    [DEBUG-COND] Result: will execute else_steps")

                        print(f"    [DEBUG-COND] ===== End condition check (cond_count={cond_count}) =====")

                        sub_steps = then_steps if cond_count > 0 else else_steps
                        print(f"    [DEBUG-COND] Executing: {'then_steps' if cond_count > 0 else 'else_steps'} ({len(sub_steps)} steps)")

                        for sub in sub_steps:
                            total_steps += 1
                            v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                                page, sub, pages_dict, data_dict, steps_so_far,
                                case_discovery, project_dir=project_dir,
                                is_new_page_context=is_new_page_context,
                                container_context=container_context
                            )
                            # 更新容器上下文
                            if v_ct:
                                container_context = v_ct
                            elif (v_ct is None and not v_skip
                                  and sub.get('keyword', '') in ('click_element', 'click')):
                                # 双重确认：检测容器是否真的消失了
                                if container_context:
                                    current_containers = detect_visible_containers(page)
                                    if container_context not in current_containers:
                                        old_ct = container_context
                                        container_context = None
                                        print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                                    else:
                                        print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                            if v_loc:
                                _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                                _store_verified_locator(v_loc, v_ct, sub, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                                if v_bg:
                                    fallback_count += 1
                                else:
                                    verified_count += 1
                            steps_so_far.append(sub)
                    continue

                # P2-3: l3_call expansion
                if keyword in L3_KEYWORDS:
                    sub_steps = _expand_l3_call(step, project_dir, pages_dict, data_dict)
                    print(f"    [L3] {desc} → {len(sub_steps)} sub-steps")
                    for sub in sub_steps:
                        total_steps += 1
                        v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                            page, sub, pages_dict, data_dict, steps_so_far,
                            case_discovery, project_dir=project_dir,
                            is_new_page_context=is_new_page_context,
                            container_context=container_context
                        )
                        # 更新容器上下文
                        if v_ct:
                            container_context = v_ct
                        elif (v_ct is None and not v_skip
                              and sub.get('keyword', '') in ('click_element', 'click')):
                            # 双重确认：检测容器是否真的消失了
                            if container_context:
                                current_containers = detect_visible_containers(page)
                                if container_context not in current_containers:
                                    old_ct = container_context
                                    container_context = None
                                    print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                                else:
                                    print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                        if v_loc:
                            _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                            _store_verified_locator(v_loc, v_ct, sub, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                            if v_bg:
                                fallback_count += 1
                            else:
                                verified_count += 1
                        elif v_loc is None and sub.get('keyword') in NO_VERIFY_KEYWORDS:
                            pass  # skip non-verify steps
                        else:
                            fallback_count += 1
                        steps_so_far.append(sub)
                    continue

                # V5: Custom L3 workflow name expansion
                # Recognizes keywords like 'check_inbox_display' that are L3 workflow names
                _l3_wf = _load_l3_workflows(project_dir or '') if project_dir else {}
                if keyword in _l3_wf:
                    # H3: 检查 module_keywords.py 是否已编译此关键字
                    if project_dir:
                        _mk_path = os.path.join(project_dir, 'lib', 'module_keywords.py')
                        if os.path.isfile(_mk_path):
                            try:
                                with open(_mk_path, encoding='utf-8') as _f:
                                    _mk_content = _f.read()
                                if f"def {keyword}(" not in _mk_content:
                                    print(f"    [WARN] L3 关键字 '{keyword}' 在 workflow YAML 中有定义，"
                                          f"但 module_keywords.py 未编译。运行时将无法解析。")
                            except Exception:
                                pass
                        else:
                            print(f"    [WARN] module_keywords.py 不存在，L3 关键字 '{keyword}' 运行时不可用。"
                                  f"请先运行 compile_module_keywords.py")
                    synthetic_step = {
                        'keyword': 'l3_call',
                        'params': {
                            'workflow': keyword,
                            'args': dict(step.get('params', {}) or {}),
                        },
                    }
                    sub_steps = _expand_l3_call(synthetic_step, project_dir, pages_dict, data_dict)
                    print(f"    [L3] {desc} ({keyword}) → {len(sub_steps)} sub-steps")
                    for sub in sub_steps:
                        total_steps += 1
                        v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                            page, sub, pages_dict, data_dict, steps_so_far,
                            case_discovery, project_dir=project_dir,
                            is_new_page_context=is_new_page_context,
                            container_context=container_context
                        )
                        # 更新容器上下文
                        if v_ct:
                            container_context = v_ct
                        elif (v_ct is None and not v_skip
                              and sub.get('keyword', '') in ('click_element', 'click')):
                            # 双重确认：检测容器是否真的消失了
                            if container_context:
                                current_containers = detect_visible_containers(page)
                                if container_context not in current_containers:
                                    old_ct = container_context
                                    container_context = None
                                    print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                                else:
                                    print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                        if v_loc:
                            _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                            _store_verified_locator(v_loc, v_ct, sub, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                            if v_bg:
                                fallback_count += 1
                            else:
                                verified_count += 1
                        elif v_loc is None and sub.get('keyword') in NO_VERIFY_KEYWORDS:
                            pass  # skip non-verify steps
                        else:
                            fallback_count += 1
                        steps_so_far.append(sub)
                    continue

                # Execute step
                v_loc, v_ct, v_skip, v_bg, v_src = execute_step(
                    page, step, pages_dict, data_dict, steps_so_far,
                    case_discovery, project_dir=project_dir,
                    is_new_page_context=is_new_page_context,
                    container_context=container_context
                )

                # 更新容器上下文
                if v_ct:
                    container_context = v_ct
                elif (v_ct is None and not v_skip
                      and keyword in ('click_element', 'click')):
                    # 双重确认：检测容器是否真的消失了
                    if container_context:
                        current_containers = detect_visible_containers(page)
                        if container_context not in current_containers:
                            old_ct = container_context
                            container_context = None
                            print(f"    [CONTEXT] 容器 {old_ct} 已关闭，清除上下文")
                        else:
                            print(f"    [CONTEXT] 容器 {container_context} 仍然存在，保持上下文")
                # open_url/refresh 后清除容器上下文（页面跳转）
                if keyword in ('open_url', 'refresh'):
                    container_context = None

                if v_skip:
                    skipped_count += 1
                    print(f"    [SKIP] Step {step_idx+1}: {desc}")
                elif v_loc:
                    _marker = (_AI_MARKER_MAP.get(v_src) if _HAS_AI_PROBE and v_src else None)
                    _store_verified_locator(v_loc, v_ct, step, pages_dict, verified_locators, is_best_guess=v_bg, marker_override=_marker)
                    if v_bg:
                        fallback_count += 1
                        print(f"    [UNVERIFIED] Step {step_idx+1}: {desc}")
                    else:
                        verified_count += 1
                        print(f"    [OK] Step {step_idx+1}: {desc}")
                else:
                    if keyword not in NO_VERIFY_KEYWORDS and 'except' not in keyword:
                        fallback_count += 1
                        print(f"    [FAIL] Step {step_idx+1}: {desc}")

                steps_so_far.append(step)

                # D3: Track URL changes for new page context
                try:
                    current_url = page.url
                    if current_url != case_baseline_url:
                        is_new_page_context = True
                    else:
                        is_new_page_context = False
                except Exception:
                    pass

            # Reset for next case: goto + reload 清除残留 dialog/drawer
            try:
                page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                # SPA hash 路由不变时 goto 可能不触发全页面重载，
                # reload 强制销毁 Vue app，清除残留 dialog/drawer wrapper
                page.reload(wait_until="domcontentloaded", timeout=30000)
                _wait_for_dom_stable(page, timeout_ms=2000)  # case 间重置
            except Exception as _e:
                print(f"  [WARN] case 间 page.reload 失败: {_e}")

    finally:
        try:
            browser.close()
            context.close()
        except Exception:
            pass
        pw.stop()

    # Summary
    print(f"\n{'='*60}")
    print(f"[Verify] DONE")
    print(f"  Cases: {len(cases)}")
    print(f"  Steps: {total_steps} total")
    print(f"  Verified: {verified_count} ({100*verified_count//max(total_steps,1)}%)")
    print(f"  Skipped (destructive): {skipped_count}")
    print(f"  Failed: {fallback_count}")
    print(f"  Writeback pending: {len(verified_locators)}")
    print(f"{'='*60}\n")

    # R6: Flush AI probe diagnostics
    if _HAS_AI_PROBE:
        _ai_probe_flush(project_dir)

    return {
        'total_steps': total_steps,
        'verified': verified_count,
        'skipped': skipped_count,
        'failed': fallback_count,
        'verified_locators': verified_locators,
        'writeback_count': len(verified_locators),
    }

def main():
    parser = argparse.ArgumentParser(
        description='Phase 6 运行时验证 — 按 case 流程执行，验证所有 locator'
    )
    parser.add_argument('project_dir', help='项目根目录')
    parser.add_argument('--cookie', required=True, help='Cookie 字符串')
    parser.add_argument('--url', required=True, help='目标系统基础 URL')
    parser.add_argument('--discovery', default=None,
                        help='discovery JSON 文件路径（discover_page.py 输出）')
    parser.add_argument('--module', default=None,
                        help='只验证指定模块（默认全部）')
    parser.add_argument('--local-storage', default=None,
                        help='额外 localStorage 注入（JSON 对象字符串），合并 config.yaml 的 local_storage')
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告需要验证的 locator，不执行浏览器')
    parser.add_argument('--ai-probe', default=None,
                        help='AI 探测配置（JSON 字符串，由 pipeline 传入）')
    parser.add_argument('--headed', action='store_true',
                        help='前台运行浏览器（headless=False），用于调试观察页面状态')

    args = parser.parse_args()

    if not os.path.isdir(args.project_dir):
        print(f"[ERROR] 项目目录不存在: {args.project_dir}")
        sys.exit(1)

    # ── 管线自愈：Phase 2/3 缺失时自动补全，其余记日志不阻断 ──
    from infra.pipeline_guard import check_pipeline_state
    check_pipeline_state(args.project_dir, ["phase_5"], "verify_locators.py",
                          {"cookie": args.cookie})

    if args.dry_run:
        cases = load_cases(args.project_dir, args.module)
        pages = load_pages(args.project_dir, module=args.module)
        total = 0
        for case in cases:
            for step in case.get('steps', []):
                if step.get('keyword') not in NO_VERIFY_KEYWORDS:
                    total += 1
        print(f"[Dry-run] {len(cases)} cases, {total} steps to verify")
        print(f"[Dry-run] {len(pages)} page groups loaded")
        sys.exit(0)

    # M20: 自动消费 pending_detail_links.json（Phase 5 输出）
    _consume_pending_detail_links(args.project_dir, args.cookie, args.url,
                                   args.local_storage)

    result = verify_project(args.project_dir, args.cookie, args.url, args.discovery, args.module, args.local_storage, headed=args.headed)

    # P3f-2: 回写验证结果到 pages YAML + 生成 verify_result.json
    if result and not result.get('auth_error'):
        verified_locators = result.get('verified_locators', {})

        if verified_locators:
            print(f"\n[Writeback] Updating {len(verified_locators)} locators in pages YAML...")
            update_pages_yaml(args.project_dir, verified_locators, module=args.module)

        # 写入 verify_result.json（供阶段门禁检查）
        _write_verify_result(args.project_dir, result)

    # X-2 修复 + Phase 6 不阻断策略（2026-08-03）:
    #   exit code 分流：
    #     0 = 验证完成（含未解析定位器，标记 [待确认]，不阻断管线）
    #     2 = Cookie 失效，管线应阻断并提示用户更新
    #   保留变量名 truly_unresolved / kb_fallback_stored（fixers/verify_all.py 静态检查依赖）
    if result:
        # 【auth_error 优先判断】→ exit(2) 通知管线阻断
        if result.get('auth_error'):
            print("\n[AUTH_REQUIRED] Cookie 已失效，请更新后使用 --from-phase phase_6_verify 重新运行")
            sys.exit(2)

        failed = result.get('failed', 0)
        verified = result.get('verified', 0)
        writeback = result.get('writeback_count', 0)
        kb_fallback_stored = max(0, writeback - verified)  # KB 回退且成功回写的数量
        truly_unresolved = failed - kb_fallback_stored    # 完全无法解析的步骤数
    else:
        truly_unresolved = 0
        kb_fallback_stored = 0

    if truly_unresolved > 0:
        print(f"\n⚠️  {truly_unresolved} 个定位器未解析（标记为 [待确认]，不阻断管线）")
    # 始终 exit(0)：验证失败不阻断管线，只有 auth_error 才 exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
