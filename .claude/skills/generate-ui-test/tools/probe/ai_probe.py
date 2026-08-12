#!/usr/bin/env python3
"""_ai_probe.py — Phase 6 R6 AI 兜底探测模块

独立模块：当 R0-R5 全部失败且 locator 仍为 [待确认] 时，
通过 DOM 快照 + AI 生成 XPath 做最后的兜底尝试。

设计原则：
  - 与 verify_locators.py 完全解耦
  - 只通过 init() / ai_probe_locator() / flush_diagnostics() 三个接口交互
  - 删除本文件 + 去掉 verify_locators.py 中的 import 和一处调用 = 完全回退

依赖：
  - openai（可选，未安装时 Layer 1/2 自动跳过）
  - playwright（由调用方传入 page 对象）

用法：
  from _ai_probe import init, ai_probe_locator, flush_diagnostics

  init(config.get('ai_probe'))          # Phase 6 开始时
  result = ai_probe_locator(...)         # R5 失败时
  count = flush_diagnostics(project_dir) # Phase 6 结束时
"""

import json
import os

# ============================================================================
# 常量
# ============================================================================

# 容器 XPath 前缀（从 xpath_utils.CONTAINER_XPATH 复制，避免 import 耦合）
_CONTAINER_XPATH = {
    'dialog': "//div[contains(@class,'el-dialog') and not(contains(@style,'display: none'))]//",
    'drawer': "//div[contains(@class,'el-drawer') and not(contains(@style,'display: none'))]//",
    'message-box': "//div[contains(@class,'el-message-box') and not(contains(@style,'display: none'))]//",
    # Ant Design
    'ant-modal': "//div[contains(@class,'ant-modal') and not(contains(@style,'display: none'))]//",
    'ant-drawer': "//div[contains(@class,'ant-drawer') and not(contains(@class,'ant-drawer-hidden'))]//",
}

# 元素类型 → 期望 HTML tag 映射（用于语义校验）
_TYPE_TAG_MAP = {
    'input-generic': ('input', 'textarea'),
    'textarea-generic': ('textarea', 'div'),
    'button': ('button', 'a', 'span', 'div'),
    'table-action-button': ('button', 'a', 'span'),
    'el-select': ('input', 'div'),
    'el-cascader': ('input', 'div'),
    'detail-link': ('a', 'span', 'td'),
    'submit-btn': ('button',),
    'search-button': ('button',),
    'download-button': ('button', 'a'),
    'close-button': ('button', 'span', 'i'),
    'tab': ('div', 'li', 'a', 'span'),
    'checkbox': ('input', 'label', 'span'),
}

# hit_source → marker 映射
MARKER_MAP = {
    'ai-probe-l0': '[AI-PROBE-L0]',
    'ai-probe-high': '[AI-PROBE]',
    'ai-probe-medium': '[AI-PROBE-WARN]',
}

# ============================================================================
# 模块级状态
# ============================================================================

_config = None          # ai_probe 配置 dict
_ai_call_count = 0      # 当前模块的 AI 调用计数
_diagnoses = []         # 诊断记录列表


# ============================================================================
# 公开接口
# ============================================================================

def init(config_dict):
    """初始化 AI 探测模块。在 verify_project() 开始时调用一次。

    Args:
        config_dict: config.yaml 中的 ai_probe 配置段，或 None
    """
    global _config, _ai_call_count, _diagnoses
    _config = config_dict
    _ai_call_count = 0
    _diagnoses = []


def ai_probe_locator(page, step, label, elem_type, current_ct,
                     steps_so_far, container_context, inject_hidden_filter):
    """R6 主入口：当 R5 兜底失败时调用。

    Args:
        page: Playwright Page 对象
        step: 当前步骤 dict
        label: 从 desc 提取的标签文字
        elem_type: 推断的元素类型
        current_ct: 当前容器类型（dialog/drawer/None）
        steps_so_far: 已执行步骤列表
        container_context: 上一步的容器上下文
        inject_hidden_filter: 从 xpath_utils 注入隐藏过滤的函数
            （由调用方传入，避免 _ai_probe.py 直接 import verify_locators 的工具链）

    Returns:
        dict: {locator, is_best_guess, hit_source, marker}
              或 None（所有 Layer 均失败）

        locator: "xpath=..." 格式的验证通过 locator
        is_best_guess: True（AI 生成，非 100% 确认）
        hit_source: 'ai-probe-l0' | 'ai-probe-high' | 'ai-probe-medium'
        marker: '[AI-PROBE-L0]' | '[AI-PROBE]' | '[AI-PROBE-WARN]'
    """
    if not _config or not _config.get('enabled', False):
        return None
    if not label or page is None:
        return None

    desc = step.get('desc', '')

    # 页面 URL
    page_url = ''
    try:
        page_url = page.url
    except Exception:
        pass

    # 容器前缀
    ct = current_ct or container_context
    container_prefix_str = _CONTAINER_XPATH.get(ct, '') if ct else ''

    ai_attempts = []

    # ── Layer 0: Playwright 内置定位器 ──
    if _config.get('layer0_enabled', True):
        l0_result = _layer0_playwright(page, label, elem_type,
                                        container_prefix_str, inject_hidden_filter)
        if l0_result:
            xpath, strategy = l0_result
            print(f"    [AI-PROBE-L0] '{desc}' → Playwright {strategy} (count=1)")
            return _make_result(f"xpath={xpath}", 'ai-probe-l0')

    # ── Layer 1: DOM 快照 + AI 单次生成 ──
    max_calls = _config.get('max_calls', 30)
    global _ai_call_count
    if _ai_call_count >= max_calls:
        print(f"    [AI-PROBE] AI 调用次数已达上限 ({max_calls})，跳过")
        return None

    dom_result = _extract_dom(page, label, container_prefix_str)

    prompt = _build_prompt(desc, label, elem_type, ct, page_url,
                           steps_so_far, dom_result)

    _ai_call_count += 1
    ai_xpath = _ai_call(prompt)

    confidence = None
    details = {}

    if ai_xpath:
        confidence, details = _verify_xpath(page, ai_xpath, elem_type,
                                             inject_hidden_filter)
        ai_attempts.append({
            'round': 0, 'xpath': ai_xpath, 'result': confidence, 'details': details
        })

        if confidence == 'high':
            print(f"    [AI-PROBE] '{desc}' → AI 生成 (count=1, 语义匹配)")
            return _make_result(f"xpath={ai_xpath}", 'ai-probe-high')

        elif confidence == 'multiple':
            narrowed = f"({ai_xpath})[1]"
            try:
                nc = page.locator(inject_hidden_filter(f"xpath={narrowed}")).count()
                if nc == 1:
                    print(f"    [AI-PROBE-WARN] '{desc}' → AI 生成 "
                          f"(count={details['count']}, 已加 [1], 请人工确认)")
                    return _make_result(f"xpath={narrowed}", 'ai-probe-medium')
            except Exception:
                pass

    # ── Layer 2: AI 迭代修正 ──
    if _config.get('layer2_enabled', True) and _ai_call_count < max_calls:
        initial_xpath = ai_xpath or ''
        initial_confidence = confidence or 'zero'

        l2_result = _layer2_iterate(
            page, initial_xpath, initial_confidence, details,
            elem_type, label, dom_result, inject_hidden_filter,
            max_rounds=_config.get('max_rounds', 2)
        )
        if l2_result:
            l2_xpath, l2_confidence, l2_attempts = l2_result
            _ai_call_count += len(l2_attempts)
            ai_attempts.extend(l2_attempts)

            if l2_confidence == 'high':
                print(f"    [AI-PROBE] '{desc}' → AI 迭代修正成功 (count=1)")
                return _make_result(f"xpath={l2_xpath}", 'ai-probe-high')
            elif l2_confidence == 'medium':
                print(f"    [AI-PROBE-WARN] '{desc}' → AI 迭代修正 (count>1, [1] 防御)")
                return _make_result(f"xpath={l2_xpath}", 'ai-probe-medium')

    # ── Layer 3: 诊断报告 ──
    diagnosis = _collect_diagnosis(page, step, label, elem_type,
                                    dom_result, ai_attempts)
    _diagnoses.append(diagnosis)
    print(f"    [AI-FAILED] '{desc}' → {diagnosis['failure_reason']}: "
          f"{diagnosis['hint'][:60]}")

    return None


def flush_diagnostics(project_dir):
    """输出诊断报告 + 重置状态。在 verify_project() 结束前调用。

    Returns:
        int: 诊断记录数量（0 = 无失败）
    """
    global _ai_call_count, _diagnoses

    count = len(_diagnoses)

    if _diagnoses:
        probe_dir = os.path.join(project_dir, '_probe')
        os.makedirs(probe_dir, exist_ok=True)
        diag_path = os.path.join(probe_dir, 'r6_ai_diagnostics.json')
        with open(diag_path, 'w', encoding='utf-8') as f:
            json.dump(_diagnoses, f, ensure_ascii=False, indent=2)
        print(f"\n[AI-Probe] {count} 个步骤 AI 探测失败，诊断报告: {diag_path}")

    _ai_call_count = 0
    _diagnoses = []

    return count


# ============================================================================
# 内部：Layer 0 — Playwright 内置定位器
# ============================================================================

_XPATH_FROM_ELEMENT_JS = """el => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
        if (node.id) {
            parts.unshift(`//*[@id='${node.id}']`);
            break;
        }
        let idx = 1;
        let sib = node.previousElementSibling;
        while (sib) {
            if (sib.tagName === node.tagName) idx++;
            sib = sib.previousElementSibling;
        }
        const tag = node.tagName.toLowerCase();
        const cls = node.className && typeof node.className === 'string'
                    ? node.className.trim().split(/\\s+/)[0] : '';
        if (cls && !cls.match(/^[\\d]/)) {
            parts.unshift(`${tag}[contains(@class,'${cls}')]`);
            if (cls.startsWith('el-dialog') || cls.startsWith('el-drawer')
                || cls.startsWith('el-form-item')) {
                break;
            }
        } else {
            parts.unshift(`${tag}[${idx}]`);
        }
        node = node.parentElement;
        if (parts.length > 6) break;
    }
    return '//' + parts.join('/');
}"""


def _layer0_playwright(page, label, elem_type, container_prefix_str,
                        inject_hidden_filter):
    """Layer 0: Playwright 内置定位器 + XPath 反推。

    Returns: (xpath, strategy_name) or None
    """
    strategies = []

    if elem_type in ('button', 'table-action-button', 'submit-btn',
                      'search-button', 'download-button', 'close-button'):
        strategies.append(('role-button', page.get_by_role('button', name=label)))
        strategies.append(('role-link', page.get_by_role('link', name=label)))

    if elem_type in ('input-generic', 'textarea-generic'):
        strategies.append(('role-textbox', page.get_by_role('textbox', name=label)))
        strategies.append(('get-by-label', page.get_by_label(label)))
        strategies.append(('placeholder', page.get_by_placeholder(label)))

    if elem_type in ('el-select', 'el-cascader'):
        strategies.append(('role-combobox', page.get_by_role('combobox', name=label)))

    if elem_type == 'tab':
        strategies.append(('role-tab', page.get_by_role('tab', name=label)))

    strategies.append(('title', page.get_by_title(label)))

    for name, loc in strategies:
        try:
            count = loc.count()
            if count == 0 or count > 3:
                continue

            el = loc.first
            xpath = el.evaluate(_XPATH_FROM_ELEMENT_JS)

            verify_count = page.locator(f"xpath={xpath}").count()
            if verify_count == 1:
                return xpath, name

            if verify_count > 1 and container_prefix_str:
                scoped = f"{container_prefix_str}{xpath.lstrip('/')}"
                scoped_count = page.locator(
                    inject_hidden_filter(f"xpath={scoped}")
                ).count()
                if scoped_count == 1:
                    return scoped, f"{name}+container"

        except Exception:
            continue

    return None


# ============================================================================
# 内部：DOM 提取
# ============================================================================

_DOM_EXTRACT_JS = """(label, containerXpath) => {
    const results = [];
    const walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT, null
    );
    while (walker.nextNode()) {
        const textNode = walker.currentNode;
        if (!textNode.textContent.includes(label)) continue;
        const parent = textNode.parentElement;
        if (!parent) continue;
        let fieldRoot = parent;
        for (let i = 0; i < 4 && fieldRoot.parentElement; i++) {
            const p = fieldRoot.parentElement;
            if (p.classList.contains('el-form-item')
                || p.classList.contains('el-dialog')
                || p.classList.contains('el-drawer')
                || p.classList.contains('el-table')
                || p.tagName === 'FORM') {
                fieldRoot = p;
                break;
            }
            fieldRoot = p;
        }
        const snippet = fieldRoot.outerHTML
            .replace(/style="[^"]*"/g, '')
            .replace(/>([^<]{30,})</g, '>[...]</')
            .substring(0, 1500);
        results.push({
            html: snippet,
            tag: fieldRoot.tagName.toLowerCase(),
            classes: (typeof fieldRoot.className === 'string') ? fieldRoot.className : '',
            parentTag: fieldRoot.parentElement?.tagName?.toLowerCase() || '',
            parentClasses: (typeof fieldRoot.parentElement?.className === 'string')
                          ? fieldRoot.parentElement.className : '',
        });
        if (results.length >= 5) break;
    }
    let container = null;
    if (containerXpath) {
        try {
            const cel = document.evaluate(
                containerXpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (cel) {
                container = {
                    tag: cel.tagName.toLowerCase(),
                    classes: cel.className || '',
                    children: Array.from(cel.children).slice(0, 10).map(c => ({
                        tag: c.tagName.toLowerCase(),
                        classes: (typeof c.className === 'string') ? c.className.substring(0, 80) : '',
                        text: (c.textContent || '').substring(0, 50).trim()
                    }))
                };
            }
        } catch(e) {}
    }
    return { matches: results, container: container };
}"""


_PAGE_SUMMARY_JS = """() => {
    const fields = [];
    document.querySelectorAll('.el-form-item').forEach(item => {
        const label = item.querySelector('.el-form-item__label');
        const input = item.querySelector('input, textarea, .el-select, .ql-editor');
        if (label) {
            fields.push({
                label: label.textContent.trim().substring(0, 30),
                inputTag: input?.tagName?.toLowerCase() || 'none',
                inputClass: (typeof input?.className === 'string')
                           ? input.className.substring(0, 60) : ''
            });
        }
    });
    return fields.slice(0, 20);
}"""


def _extract_dom(page, label, container_prefix_str):
    """提取目标区域的 DOM 快照。"""
    try:
        return page.evaluate(_DOM_EXTRACT_JS, [label, container_prefix_str or ''])
    except Exception as e:
        print(f"    [AI-PROBE] DOM 提取失败: {str(e)[:80]}")
        return None


# ============================================================================
# 内部：Prompt 构建
# ============================================================================

def _build_prompt(desc, label, elem_type, container_type, page_url,
                  steps_so_far, dom_result):
    """构建 AI Prompt。"""

    prev_lines = []
    for s in (steps_so_far or [])[-3:]:
        prev_lines.append(f"  - {s.get('desc', '')} ({s.get('keyword', '')})")
    prev_text = '\n'.join(prev_lines) if prev_lines else '  (无前序步骤)'

    if dom_result and dom_result.get('matches'):
        dom_parts = []
        for i, m in enumerate(dom_result['matches'][:3]):
            dom_parts.append(
                f"--- 匹配 {i+1} (tag={m['tag']}, class=\"{m['classes'][:80]}\") ---")
            dom_parts.append(m['html'][:1200])
        dom_text = '\n'.join(dom_parts)
    else:
        dom_text = "(DOM 中未找到包含该标签文字的元素)"

    if dom_result and dom_result.get('container'):
        c = dom_result['container']
        container_text = (
            f"容器: <{c['tag']} class=\"{c['classes'][:80]}\">\n"
            f"子元素: " + ', '.join(
                f"<{ch['tag']} class=\"{ch['classes'][:40]}\">"
                for ch in c.get('children', [])[:6]
            )
        )
    else:
        container_text = "(无容器或容器未检测到)"

    prefix_hints = {
        'dialog': "//div[contains(@class,'el-dialog')]",
        'drawer': "//div[contains(@class,'el-drawer')]",
        'message-box': "//div[contains(@class,'el-message-box')]",
    }
    prefix_hint = prefix_hints.get(container_type, '(无容器前缀)')

    return f"""你是一个 Web UI 自动化测试的 XPath 专家。

**任务**: 为目标元素生成一个 XPath 定位器。

## 目标信息
- 步骤描述: {desc}
- 元素标签: {label}
- 推断类型: {elem_type}
- 当前容器: {container_type or 'none'}
- 页面 URL: {page_url}

## 页面 DOM 上下文（真实 DOM，非猜测）
{dom_text}

## 容器结构
{container_text}

## 前序步骤
{prev_text}

## 生成规则
1. 使用相对路径，禁止绝对路径（/html/body/...）
2. 容器前缀: {prefix_hint}
3. 对于输入框: 定位 input[@class='el-input__inner'] 或 textarea 或 .ql-editor
4. 对于按钮: 定位 button 元素
5. 对于 el-select: 定位 .el-select 的 input（触发器）
6. 加隐藏过滤: not(ancestor-or-self::*[contains(@style,'display: none')])
7. 避免硬编码 index（div[3]），优先用 class 或文本
8. 只返回一个 XPath，不要解释，不要 ``` 代码块"""


# ============================================================================
# 内部：AI 调用
# ============================================================================

def _ai_call(prompt, timeout=None):
    """调用 OpenAI API 生成 XPath。Returns: xpath or None"""
    model = _config.get('model', 'gpt-4o-mini')
    timeout = timeout or _config.get('timeout', 15)
    temperature = _config.get('temperature', 0)

    try:
        import openai
        client = openai.OpenAI()

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system",
                 "content": "You are a UI test XPath expert. Respond with XPath only."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=300,
            timeout=timeout,
        )

        xpath = response.choices[0].message.content.strip()

        # 清理 markdown 代码块
        if xpath.startswith('```'):
            lines = xpath.split('\n')
            xpath = lines[1] if len(lines) > 1 else xpath[3:]
        if xpath.endswith('```'):
            xpath = xpath[:-3]
        xpath = xpath.strip()

        # 格式校验
        if not (xpath.startswith('//') or xpath.startswith('(')):
            print(f"    [AI-PROBE] AI 返回非 XPath: {xpath[:60]}")
            return None

        if xpath.startswith('/html') or xpath.startswith('/body'):
            print(f"    [AI-PROBE] AI 返回绝对路径: {xpath[:60]}")
            return None

        return xpath

    except ImportError:
        print(f"    [AI-PROBE] openai 包未安装，跳过 (pip install openai)")
        return None
    except Exception as e:
        print(f"    [AI-PROBE] AI 调用失败: {str(e)[:80]}")
        return None


# ============================================================================
# 内部：XPath 验证 + 语义校验
# ============================================================================

def _verify_xpath(page, xpath, elem_type, inject_hidden_filter):
    """验证 AI 生成的 XPath。

    Returns: (confidence, details_dict)
        confidence: 'high' | 'multiple' | 'semantic-mismatch' | 'zero' | 'error'
    """
    full_xpath = inject_hidden_filter(f"xpath={xpath}")

    try:
        count = page.locator(full_xpath).count()
    except Exception as e:
        return 'error', {'error': str(e)[:100]}

    if count == 0:
        return 'zero', {'count': 0}

    el = page.locator(full_xpath).first
    try:
        tag = el.evaluate("e => e.tagName.toLowerCase()")
        classes = el.evaluate(
            "e => (typeof e.className === 'string') ? e.className : ''")
        is_visible = el.is_visible()
    except Exception:
        return 'error', {'error': 'evaluate failed'}

    semantic_ok = True
    notes = []

    expected_tags = _TYPE_TAG_MAP.get(elem_type, ())
    if expected_tags and tag not in expected_tags:
        semantic_ok = False
        notes.append(f"tag={tag}, expected {expected_tags}")

    if not is_visible:
        semantic_ok = False
        notes.append("element is not visible")

    if count == 1 and semantic_ok:
        return 'high', {'count': 1, 'tag': tag, 'classes': classes[:80]}
    elif count == 1 and not semantic_ok:
        return 'semantic-mismatch', {
            'count': 1, 'tag': tag, 'classes': classes[:80],
            'notes': '; '.join(notes)
        }
    else:
        return 'multiple', {'count': count, 'tag': tag, 'classes': classes[:80]}


# ============================================================================
# 内部：Layer 2 — 迭代修正
# ============================================================================

def _build_feedback_prompt(prev_xpath, confidence, details, dom_result,
                            elem_type, label):
    """构建迭代修正 Prompt。"""
    if confidence == 'zero':
        result_desc = "count=0（XPath 未命中任何 DOM 节点）"
        extra_dom = ""
        if dom_result and dom_result.get('matches'):
            extra_dom = f"\n实际 DOM:\n{dom_result['matches'][0]['html'][:1500]}"
    elif confidence == 'semantic-mismatch':
        result_desc = (
            f"count=1 但类型不匹配: tag={details.get('tag')}, "
            f"class=\"{details.get('classes', '')[:60]}\", "
            f"问题: {details.get('notes', '')}"
        )
        extra_dom = ""
    elif confidence == 'multiple':
        result_desc = f"count={details.get('count')}（多个匹配，需更精确）"
        extra_dom = ""
    else:
        result_desc = f"{confidence}: {details}"
        extra_dom = ""

    return f"""上一次你生成的 XPath:
{prev_xpath}

验证结果: {result_desc}
目标: label="{label}", 类型={elem_type}
{extra_dom}

请修正 XPath。只返回修正后的 XPath，不要解释。"""


def _layer2_iterate(page, prev_xpath, confidence, details, elem_type, label,
                     dom_result, inject_hidden_filter, max_rounds=2):
    """Layer 2: 迭代修正。

    Returns: (xpath, confidence, attempts_list) or None
    """
    current_xpath = prev_xpath
    current_confidence = confidence
    current_details = details
    attempts = []

    for round_num in range(1, max_rounds + 1):
        feedback = _build_feedback_prompt(
            current_xpath, current_confidence, current_details,
            dom_result, elem_type, label
        )

        new_xpath = _ai_call(feedback)
        if not new_xpath:
            attempts.append({'round': round_num, 'xpath': None, 'result': 'ai-error'})
            break

        conf, det = _verify_xpath(page, new_xpath, elem_type, inject_hidden_filter)
        attempts.append({
            'round': round_num, 'xpath': new_xpath,
            'result': conf, 'details': det,
        })

        if conf == 'high':
            return new_xpath, 'high', attempts
        elif conf == 'multiple':
            narrowed = f"({new_xpath})[1]"
            try:
                nc = page.locator(
                    inject_hidden_filter(f"xpath={narrowed}")
                ).count()
                if nc == 1:
                    return narrowed, 'medium', attempts
            except Exception:
                pass

        current_xpath = new_xpath
        current_confidence = conf
        current_details = det

    return None


# ============================================================================
# 内部：Layer 3 — 诊断
# ============================================================================

def _collect_diagnosis(page, step, label, elem_type, dom_result, ai_attempts):
    """Layer 3: 收集失败诊断信息。"""
    diagnosis = {
        'step_desc': step.get('desc', ''),
        'label': label,
        'elem_type': elem_type,
        'keyword': step.get('keyword', ''),
        'dom_label_found': bool(dom_result and dom_result.get('matches')),
        'dom_match_count': len(dom_result.get('matches', [])) if dom_result else 0,
        'ai_attempts': ai_attempts,
        'failure_reason': None,
        'hint': '',
    }

    if not dom_result or not dom_result.get('matches'):
        diagnosis['failure_reason'] = 'LABEL_NOT_IN_DOM'
        diagnosis['hint'] = (
            f'页面上找不到包含「{label}」的文字。'
            f'可能原因：前序步骤未正确打开容器，或表单尚未渲染完成。'
        )
        try:
            diagnosis['visible_fields'] = page.evaluate(_PAGE_SUMMARY_JS)[:10]
        except Exception:
            pass
    else:
        diagnosis['failure_reason'] = 'AI_XPATH_FAILED'
        diagnosis['hint'] = (
            f'DOM 中找到了「{label}」，但 AI 经过 {len(ai_attempts)} 轮尝试'
            f'仍无法生成有效的 XPath。建议手动检查 DOM 结构。'
        )
        diagnosis['dom_snippets'] = [
            m['html'][:300] for m in dom_result.get('matches', [])[:3]
        ]

    return diagnosis


# ============================================================================
# 内部：工具函数
# ============================================================================

def _make_result(locator, hit_source):
    """构造统一的返回 dict。"""
    return {
        'locator': locator,
        'is_best_guess': True,
        'hit_source': hit_source,
        'marker': MARKER_MAP.get(hit_source, '[AI-PROBE]'),
    }
