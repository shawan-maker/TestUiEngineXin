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
DESTRUCTIVE_TRIGGERS = set()  # 已移除破坏性操作跳过机制
CONTAINER_TYPES = ['dialog', 'drawer', 'message-box']
_SYSTEM_WORKFLOWS = None
_PROJECT_WORKFLOWS = {}
PROBE_ISOLATION_PREFIX = '__probe__'
# 可以安全跳过的关键字 — 不影响页面状态，Phase 6 自行管理
SKIP_KEYWORDS = {
    'open_browser', 'close_browser',
    'inject_local_storage', 'inject_cookies', 'inject_token_header',
    'set_viewport_size',
    'log',
    'if_variable', 'set_random_variable',
}

# 必须执行的关键字 — 影响页面状态，不执行会导致后续 locator 验证失败
EXECUTE_KEYWORDS = {
    'open_url', 'refresh', 'go_back',
    'wait_for_loading_complete', 'wait_for_time',
    'wait_for_element', 'wait_for_element_hidden',
    'check_page_loaded',
    'execute_script',  # 滚动表格到目标位置（如规格选择），不执行会导致后续点击失败
}

# 向后兼容别名
NO_VERIFY_KEYWORDS = SKIP_KEYWORDS
L3_KEYWORDS = {'l3_call'}

# ── iframe 探测结果通道 ──
# execute_step() 通过此变量向 verify_orchestrator 传递 iframe 发现
# 每次 execute_step 调用前清空，调用后读取
_last_iframe_discovery = None
PROBE_FILL_VALUES = {
    'input': '测试',
    'textarea': '测试文本',
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


def _try_find_in_iframes(page, locator: str, max_iframes=10):
    """在 iframe 中查找元素（当主页面 count=0 时）

    策略：
    1. 等待 iframe 出现（初始5s，每次重试2s，最多3次）
    2. 轮询 page.frames() 检测动态创建的 iframe
    3. 遍历页面中所有 iframe
    4. 在每个 iframe 内尝试定位元素
    5. 返回第一个找到的 iframe context

    Args:
        page: Playwright page 对象
        locator: XPath 定位器（已剥离容器前缀）
        max_iframes: 最多检查的 iframe 数量

    Returns:
        dict: {frame_selector, frame_locator, count} 或 None
    """
    import time
    if not locator or 'xpath=' not in locator:
        print(f"    [DEBUG-IFRAME] Early exit: locator is None or not xpath")
        return None

    print(f"    [DEBUG-IFRAME] ========== _try_find_in_iframes START ==========")
    print(f"    [DEBUG-IFRAME] Timestamp: {time.strftime('%H:%M:%S')}")

    # 提取纯 XPath
    xpath = locator.replace('xpath=', '', 1)

    # [DEBUG-IFRAME] 原始 XPath
    print(f"    [DEBUG-IFRAME] 原始 XPath: {xpath[:120]}")

    # 剥离 hidden filter（iframe 内不需要）
    # 兼容旧版 ancestor:: 和新版 ancestor-or-self:: 两种写法
    # 同时兼容单引号 'is-hidden' 和 YAML 双引号 ''is-hidden''
    xpath = re.sub(r"\s*and\s+not\(ancestor(?:-or-self)?::\*\[contains\(@class,''?is-hidden''?\)\]\)", '', xpath)
    xpath = re.sub(r"\s*and\s+not\(ancestor(?:-or-self)?::\*\[contains\(@style,''?display:\s*none''?\)\]\)", '', xpath)

    # [DEBUG-IFRAME] 剥离 hidden filter 后
    print(f"    [DEBUG-IFRAME] 剥离 hidden filter: {xpath[:120]}")

    # 剥离容器前缀（iframe 是独立页面，没有主页面的抽屉/弹窗容器）
    # 常见容器：el-dialog, el-drawer, el-message-box, ant-modal, ant-drawer
    container_prefixes = [
        r'^\(\s*//div\[contains\(@class,\'el-dialog\'\)\]//',
        r'^\(\s*//div\[contains\(@class,\'el-drawer\'\)\]//',
        r'^\(\s*//div\[contains\(@class,\'el-message-box\'\)\]//',
        r'^\(\s*//div\[contains\(@class,\'ant-modal\'\)\]//',
        r'^\(\s*//div\[contains\(@class,\'ant-drawer\'\)\]//',
        r'^//div\[contains\(@class,\'el-dialog\'\)\]//',
        r'^//div\[contains\(@class,\'el-drawer\'\)\]//',
        r'^//div\[contains\(@class,\'el-message-box\'\)\]//',
        r'^//div\[contains\(@class,\'ant-modal\'\)\]//',
        r'^//div\[contains\(@class,\'ant-drawer\'\)\]//',
    ]
    for prefix_pattern in container_prefixes:
        if re.match(prefix_pattern, xpath):
            old_xpath = xpath
            xpath = re.sub(prefix_pattern, '//', xpath)
            # 剥离容器前缀后，末尾可能残留配对括号 ')' 和尾部索引 '[1]'
            # 例: (//div...//button[...]))[1] → 剥离后 //button[...])][1] → 去掉 )[1]
            xpath = re.sub(r'\)\[(\d+)\]\s*$', '', xpath)
            xpath = re.sub(r'\)\s*$', '', xpath)
            print(f"    [DEBUG-IFRAME] strip container prefix:")
            print(f"    [DEBUG-IFRAME]   before: {old_xpath[:120]}")
            print(f"    [DEBUG-IFRAME]   after:  {xpath[:120]}")
            break

    # 剥离尾部索引 [1]
    xpath = re.sub(r'\)\[(\d+)\]\s*$', ')', xpath)

    # [DEBUG-IFRAME] 最终 XPath
    print(f"    [DEBUG-IFRAME] 最终 XPath: {xpath[:120]}")

    # 保存清理后的 xpath，用于后续点击
    clean_xpath = xpath

    # 方案1+2：增强等待逻辑
    # 初始等待5秒，最多重试3次，每次间隔2秒
    max_attempts = 3
    initial_wait = 5000  # 初始等待时间（ms）
    retry_interval = 2000  # 重试间隔（ms）

    iframes = None

    for attempt in range(max_attempts):
        wait_time = initial_wait if attempt == 0 else retry_interval
        print(f"    [DEBUG-IFRAME] 尝试 {attempt + 1}/{max_attempts}，等待 {wait_time}ms...")

        # 方式1：等待 DOM 中的 <iframe> 标签
        try:
            page.wait_for_selector('iframe', state='attached', timeout=wait_time)
            print(f"    [DEBUG-IFRAME] iframe 元素已出现")
        except Exception as wait_err:
            print(f"    [DEBUG-IFRAME] 等待 iframe 超时: {str(wait_err)[:60]}")

        # 方式2：轮询 page.frames() 检测动态创建的 iframe
        iframes = page.frames
        print(f"    [DEBUG-IFRAME] page.frames 数量: {len(iframes)}")

        # [DEBUG-IFRAME] 列出所有 iframe 信息
        for i, frame in enumerate(iframes):
            frame_name = frame.name or 'main_frame'
            frame_url = frame.url[:80] if frame.url else 'N/A'
            print(f"    [DEBUG-IFRAME] Frame[{i}]: name='{frame_name}', url='{frame_url}'")

            # 特别检查 confirmIframe
            if 'confirmIframe' in (frame.name or '') or 'confirm' in frame.url:
                print(f"    [DEBUG-IFRAME] *** 找到 confirmIframe! name='{frame.name}'")

        if len(iframes) > 1:  # 找到 iframe，开始扫描
            print(f"    [TRACE-P6-IFRAME] 检测到 {len(iframes)-1} 个 iframe，开始扫描")
            break

        # 只有主 frame，如果还有重试机会则继续等待
        if attempt < max_attempts - 1:
            print(f"    [DEBUG-IFRAME] 只有主 frame，{retry_interval}ms 后重试...")
            page.wait_for_timeout(retry_interval)
        else:
            print(f"    [DEBUG-IFRAME] 只有主 frame，无 iframe，已重试 {max_attempts} 次")
            return None

    # 确认有 iframe 后才继续
    if not iframes or len(iframes) <= 1:
        print(f"    [DEBUG-IFRAME] 最终未找到 iframe")
        return None

    scanned = 0
    for frame in iframes:
        if frame == page.main_frame:
            print(f"    [DEBUG-IFRAME] 跳过 main_frame")
            continue
        if scanned >= max_iframes:
            print(f"    [TRACE-P6-IFRAME] 达到上限 {max_iframes}，停止扫描")
            break

        scanned += 1
        frame_name = frame.name or frame.url.split('/')[-1] or f'frame_{scanned}'

        # [DEBUG-IFRAME] 每个 iframe 扫描前日志
        print(f"    [DEBUG-IFRAME] 扫描 iframe[{scanned}]: name='{frame_name}'")

        frame_selector = None  # 初始化，防止 count=0 时 UnboundLocalError
        try:
            # 尝试在 iframe 内定位
            full_xpath_query = f'xpath={xpath}'
            # [DEBUG-IFRAME] 完整 XPath（不截断，便于诊断括号问题）
            print(f"    [DEBUG-IFRAME] FULL XPath for iframe[{scanned}]:")
            print(f"    [DEBUG-IFRAME]   {full_xpath_query}")
            # 括号平衡检查
            _open_sq = full_xpath_query.count('[')
            _close_sq = full_xpath_query.count(']')
            _open_paren = full_xpath_query.count('(')
            _close_paren = full_xpath_query.count(')')
            _bracket_balanced = (_open_sq == _close_sq) and (_open_paren == _close_paren)
            print(f"    [DEBUG-IFRAME]   brackets: [={_open_sq} ]={_close_sq} (={_open_paren} )={_close_paren} balanced={_bracket_balanced}")

            frame_locator = frame.locator(full_xpath_query)
            count = frame_locator.count()

            # [DEBUG-IFRAME] 每个 iframe 的 count 结果
            print(f"    [DEBUG-IFRAME] iframe '{frame_name}' count={count}")

            # 调试：count=0 时输出 iframe 内容预览
            if count == 0:
                print(f"    [DEBUG-IFRAME] [FAIL] iframe '{frame_name}' count=0!")
                print(f"    [DEBUG-IFRAME]   iframe URL: {frame.url[:120]}")
                try:
                    body_text = frame.locator('body').text_content(timeout=2000)
                    preview = body_text[:300].replace('\n', ' ') if body_text else 'empty'
                    print(f"    [DEBUG-IFRAME]   iframe body: {preview}")
                except Exception as txt_err:
                    print(f"    [DEBUG-IFRAME]   cannot read body: {txt_err}")

            if count > 0:
                print(f"    [TRACE-P6-IFRAME] [OK] iframe '{frame_name}' found {count} matches")

                # 生成 frame selector（全 XPath 格式，2026-08-07）
                # 优先读取 DOM 属性，而非 Playwright frame.name
                frame_selector = None
                try:
                    iframe_el = frame.frame_element()
                    # 优先级 1: id
                    iframe_id = iframe_el.get_attribute('id')
                    if iframe_id:
                        candidate = f'xpath=//iframe[@id="{iframe_id}"]'
                        if page.locator(candidate).count() == 1:
                            frame_selector = candidate
                            print(f"    [DEBUG-IFRAME] 使用 id 生成 selector: {frame_selector}")

                    # 优先级 2: class
                    if not frame_selector:
                        iframe_class = iframe_el.get_attribute('class')
                        if iframe_class:
                            candidate = f'xpath=//iframe[@class="{iframe_class}"]'
                            cnt = page.locator(candidate).count()
                            if cnt == 1:
                                frame_selector = candidate
                                print(f"    [DEBUG-IFRAME] 使用 class 生成 selector: {frame_selector}")
                            elif cnt > 1:
                                frame_selector = f'({candidate})[1]'
                                print(f"    [DEBUG-IFRAME] class 不唯一(count={cnt})，加索引: {frame_selector}")

                    # 优先级 3: DOM name 属性
                    if not frame_selector:
                        iframe_name = iframe_el.get_attribute('name')
                        if iframe_name:
                            candidate = f'xpath=//iframe[@name="{iframe_name}"]'
                            if page.locator(candidate).count() >= 1:
                                frame_selector = candidate
                                print(f"    [DEBUG-IFRAME] 使用 DOM name 生成 selector: {frame_selector}")

                    # 优先级 4: src 特征路径
                    if not frame_selector and frame.url and frame.url != 'about:blank':
                        src_fragment = frame.url.split('/')[-2] if '/' in frame.url else frame.url[:30]
                        if src_fragment and len(src_fragment) > 3:
                            candidate = f'xpath=//iframe[contains(@src,"{src_fragment}")]'
                            if page.locator(candidate).count() >= 1:
                                frame_selector = candidate
                                print(f"    [DEBUG-IFRAME] 使用 src 生成 selector: {frame_selector}")

                    # 优先级 5: DOM 位置索引
                    if not frame_selector:
                        try:
                            all_iframes = page.locator('iframe')
                            total = all_iframes.count()
                            for idx in range(total):
                                if all_iframes.nth(idx) == iframe_el:
                                    frame_selector = f'xpath=(//iframe)[{idx + 1}]'
                                    print(f"    [DEBUG-IFRAME] 使用位置索引生成 selector: {frame_selector}")
                                    break
                        except Exception:
                            pass
                except Exception as dom_err:
                    print(f"    [DEBUG-IFRAME] DOM 属性读取失败: {dom_err}")

            # 检查是否成功生成 frame_selector
            if not frame_selector:
                print(f"    [DEBUG-IFRAME] [ERROR] 无法生成 frame selector")
                print(f"    [DEBUG-IFRAME]   iframe 无 id/class/name 属性")
                print(f"    [DEBUG-IFRAME]   src: {frame.url or 'None'}")
                print(f"    [DEBUG-IFRAME]   DOM 位置索引也失败")
                print(f"    [DEBUG-IFRAME]   跳过此 iframe，继续扫描下一个")
                continue  # 跳过此 iframe，尝试下一个

            return {
                'frame_selector': frame_selector,
                'frame_locator': frame_locator,
                'clean_xpath': clean_xpath,
                'count': count,
                'frame_name': frame_name,
            }
        except Exception as e:
                # 跨域 iframe 或其他错误，静默跳过
                print(f"    [DEBUG-IFRAME] iframe '{frame_name}' 定位异常: {str(e)[:80]}")
                continue

        print(f"    [TRACE-P6-IFRAME] 扫描 {scanned} 个 iframe，未找到匹配元素")

    return None


def _convert_input_to_el_select(input_locator: str) -> str:
    """将 input[@class='el-input__inner'] 或 input[contains(@class,'ant-input')] 转换为 select 容器

    转换规则：
    Element UI: //input[@class='el-input__inner' and ...]
    → //div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]

    Ant Design: //input[contains(@class,'ant-input') and ...]
    → //div[contains(@class,'ant-select') and not(contains(@class,'ant-select-dropdown'))]

    使用 bracket-depth 扫描替代正则，正确处理嵌套 []（如 hidden filter 中的
    not(ancestor::*[contains(@style,'display: none')])）。

    保留原始的 ()[n] 包裹：如果输入已有 (xpath)[n] 包裹，转换后保持 [n] 不变；
    仅当输入没有 ()[n] 包裹时，自动添加 ()[1]。

    Args:
        input_locator: input 目标的 locator（含 xpath= 前缀）

    Returns:
        str: 转换后的 select 容器 locator，转换失败返回原值
    """
    if not input_locator.startswith('xpath='):
        return input_locator

    xpath = input_locator[6:]  # 去掉 xpath= 前缀

    # Element UI marker
    marker_eu = "//input[@class='el-input__inner'"
    start_eu = xpath.find(marker_eu)

    # Ant Design marker
    marker_antd = "//input[contains(@class,'ant-input')"
    start_antd = xpath.find(marker_antd)

    # 选择第一个匹配的 marker
    if start_eu >= 0 and (start_antd < 0 or start_eu <= start_antd):
        marker = marker_eu
        start = start_eu
        is_antd = False
    elif start_antd >= 0:
        marker = marker_antd
        start = start_antd
        is_antd = True
    else:
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

    # 整段替换为 select 容器表达式（使用 //div 精确匹配，而非 //* 通配）
    if is_antd:
        replacement = "//div[contains(@class,'ant-select') and not(contains(@class,'ant-select-dropdown'))]"
    else:
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


def _generate_el_select_candidates(input_locator):
    """Generate dual candidates for el-select/ant-select expand step.

    When the input locator contains `following-sibling::*[self::div or self::span]`,
    generate two candidates:
      - Candidate 1 (descendant mode): following-sibling::*[self::div or self::span]//div[contains(@class,'el-select')]
        Use when el-select is a descendant of the following-sibling.
      - Candidate 2 (direct sibling mode): following-sibling::*[self::div or self::span][contains(@class,'el-select')]
        Use when el-select IS the following-sibling itself.

    Both candidates are validated by VLC; whichever matches count==1 is selected.

    Args:
        input_locator: input 定位器（不含 xpath= 前缀）

    Returns:
        list: [candidate1, candidate2] or [candidate1] if pattern doesn't match
    """
    # Candidate 1: descendant mode (standard conversion)
    cand1 = _convert_input_to_el_select(f"xpath={input_locator}")[6:]  # strip xpath=

    # Candidate 2: 直接兄弟模式
    # 匹配: /following-sibling::*[self::div or self::span]//input[@class='el-input__inner'...]
    # 或: /following-sibling::*[self::div or self::span]//input[contains(@class,'ant-input')...]
    # 替换: /following-sibling::*[self::div or self::span][contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]
    # 或: /following-sibling::*[self::div or self::span][contains(@class,'ant-select') and not(contains(@class,'ant-select-dropdown'))]
    sibling_marker = "following-sibling::*[self::div or self::span]"

    # 检测 Element UI 或 Ant Design 的 input marker
    input_marker_eu = "//input[@class='el-input__inner'"
    input_marker_antd = "//input[contains(@class,'ant-input')"

    sib_pos = input_locator.find(sibling_marker)
    inp_pos_eu = input_locator.find(input_marker_eu)
    inp_pos_antd = input_locator.find(input_marker_antd)

    # 选择第一个匹配的 marker
    if inp_pos_eu >= 0 and (inp_pos_antd < 0 or inp_pos_eu <= inp_pos_antd):
        input_marker = input_marker_eu
        inp_pos = inp_pos_eu
        is_antd = False
    elif inp_pos_antd >= 0:
        input_marker = input_marker_antd
        inp_pos = inp_pos_antd
        is_antd = True
    else:
        # No input marker found, return single candidate
        return [cand1]

    if sib_pos >= 0 and inp_pos > sib_pos:
        # 先剥离原始 ()[N] 包裹，避免替换后 )[N] 残留导致双重包裹
        from core.xpath_utils import _unwrap_positional, _rewrap_positional
        loc_inner, orig_wrap = _unwrap_positional(input_locator)
        # 在剥离后的 inner 上重新定位（偏移可能变化）
        sib_pos2 = loc_inner.find(sibling_marker)
        inp_pos2 = loc_inner.find(input_marker)
        if sib_pos2 >= 0 and inp_pos2 > sib_pos2:
            bracket_start = inp_pos2 + len("//input")
            depth = 0
            end = -1
            for i in range(bracket_start, len(loc_inner)):
                if loc_inner[i] == '[':
                    depth += 1
                elif loc_inner[i] == ']':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > 0:
                if is_antd:
                    replacement = "[contains(@class,'ant-select') and not(contains(@class,'ant-select-dropdown'))]"
                else:
                    replacement = "[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))]"
                cand2_body = loc_inner[:inp_pos2] + replacement + loc_inner[end:]
                # 重新包裹：保留原始 ()[N] 索引，无则添加 ()[1]
                cand2 = _rewrap_positional(cand2_body, orig_wrap if orig_wrap else '[1]')
                return [cand1, cand2]
    # Pattern didn't match or bracket scan failed, return single candidate
    return [cand1]


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

# 容器前缀剥离正则（匹配 el-dialog/el-drawer/el-message-box/ant-modal/ant-drawer 前缀）
CONTAINER_PREFIX_PATTERN = re.compile(
    r"^//div\[contains\(@class,'(el-(dialog|drawer|message-box)|ant-(modal|drawer))'\)\]"
)


def _strip_container_prefix(raw_xpath):
    """剥离 XPath 中的容器前缀（el-dialog/el-drawer/el-message-box）

    支持两种格式：
    - 裸 XPath: //div[...]//button → //button
    - 包裹 XPath: (//div[...]//button)[1] → (//button)[1]

    双重 ()[1] 包裹修复：
    - 输入: ((xpath)[1])[1]
    - 输出: (xpath)[1]（剥离多余的外层包裹）

    Args:
        raw_xpath: 原始 XPath（不含 xpath= 前缀）

    Returns:
        剥离后的 XPath（保持单层 ()[N] 包裹格式）
    """
    from core.xpath_utils import _unwrap_positional, _rewrap_positional

    # 修复双重 ()[1] 包裹：循环剥离多余的外层
    while True:
        inner, wrap = _unwrap_positional(raw_xpath)
        if not wrap:
            # 没有 ()[N] 包裹，退出循环
            break
        # 检查 inner 是否也是 ()[N] 包裹（双重包裹）
        inner2, wrap2 = _unwrap_positional(inner)
        if wrap2:
            # 双重包裹，剥离外层，保留内层
            raw_xpath = inner
            continue
        # 单层包裹，退出循环
        break

    # 剥离容器前缀
    inner, wrap = _unwrap_positional(raw_xpath)
    stripped = CONTAINER_PREFIX_PATTERN.sub("", inner)
    return _rewrap_positional(stripped, wrap)


def _verify_count_or_first(page, locator, elem_type=None):
    """验证 locator 匹配数，count>1 时自动 [1] 收窄避免 strict mode violation。

    与 verify_locator_candidates() 的 count>1 逻辑保持一致：
    count==1 → 通过（点击类元素始终 [1] 包裹）；count>1 → 尝试 (xpath)[1] 取首个匹配元素。

    Args:
        page: Playwright Page 对象
        locator: 完整 locator 字符串（含 xpath= 前缀）
        elem_type: 元素类型（用于判断是否需要 [1] 包裹）

    Returns:
        str or None: 验证通过的 locator（可能已 [1] 收窄），count==0 返回 None
    """
    from core.xpath_utils import _unwrap_positional, _rewrap_positional
    if not locator:
        return None
    try:
        count = page.locator(locator).count()
    except Exception:
        return None
    if count == 1:
        # 点击类元素：始终 [1] 包裹，防止运行时多匹配导致 strict mode violation
        if elem_type in CLICK_EXPAND_TYPES:
            raw = locator[6:] if locator.startswith('xpath=') else locator
            inner, wrap = _unwrap_positional(raw)
            if not wrap:  # 没有已有 positional 包裹
                wrapped = f"({raw})[1]"
                locator = inject_hidden_filter(f"xpath={wrapped}", elem_type=elem_type)
        return locator
    if count > 1:
        # 多匹配 → [1] 收窄（与 verify_locator_candidates 的 [1] fallback 一致）
        raw = locator[6:] if locator.startswith('xpath=') else locator

        # 防止双重包裹：如果已有 (xpath)[N] 外层，先解包再用 [1] 重新包裹
        inner, _ = _unwrap_positional(raw)
        narrowed_raw = f"({inner})[1]"

        narrowed = inject_hidden_filter(f"xpath={narrowed_raw}")
        try:
            if page.locator(narrowed).count() == 1:
                return narrowed
        except Exception:
            pass
    return None


def verify_locator_candidates(page, candidates, container_type=None, discovery_ct=None, return_index=False, elem_type=None):
    """Try multiple locator candidates with multiple container prefixes.

    Priority: discovery container_type > default priority > no prefix

    P2-4: When count>1 in preferred container, fall back to (xpath)[last()]
    for dialog/drawer (last opened = topmost).

    Args:
        return_index: If True, return 4-tuple with matched candidate index.
                     If False (default), return 3-tuple for backward compatibility.
        elem_type: Element type (e.g., 'button', 'input-generic'). Used to inject
                  disabled filter for button types.

    Returns:
        If return_index=False: (matched_locator, matched_prefix, count) or (None, None, 0)
        If return_index=True: (matched_locator, matched_prefix, count, candidate_index) or (None, None, 0, None)
    """
    # Build prefix order
    if discovery_ct:
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
                _stripped = bare_xpath != raw_xpath
                # [TRACE-P6] 前缀剥离详情（仅当实际发生剥离时打印）
                if _stripped:
                    print(f"    [TRACE-P6]     cand[{candidate_index}] STRIP: had container prefix")
                    print(f"    [TRACE-P6]       raw:    {raw_xpath[:100]}")
                    print(f"    [TRACE-P6]       bare:   {bare_xpath[:100]}")

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

                    full_xpath = inject_hidden_filter(f"xpath={test_xpath}", elem_type=elem_type)

                    try:
                        count = page.locator(full_xpath).count()
                        # [TRACE-P6] 每个 candidate 的 count 值
                        # 标记：原始候选是否自带容器前缀 + 当前测试的前缀
                        _orig_had_prefix = 'YES' if _stripped else 'NO'
                        print(f"    [TRACE-P6]     cand[{candidate_index}] "
                              f"count={count} test_prefix={test_prefix or 'None'} "
                              f"(orig_had_prefix={_orig_had_prefix}): "
                              f"{full_xpath[:120]}{'...' if len(full_xpath) > 120 else ''}")
                        if count == 1:
                            # 点击类元素：始终 [1] 包裹，防止运行时多匹配导致 strict mode violation
                            if elem_type in CLICK_EXPAND_TYPES:
                                inner, wrap = _unwrap_positional(test_xpath)
                                if not wrap:  # 没有已有 positional 包裹
                                    wrapped_test_xpath = f"({test_xpath})[1]"
                                    full_xpath = inject_hidden_filter(f"xpath={wrapped_test_xpath}", elem_type=elem_type)
                                    print(f"    [TRACE-P6]     [1] wrapped for click type: {full_xpath[:120]}")
                            return _ret(full_xpath, test_prefix, count, candidate_index)
                        if count > 1:
                            # 第一轮：跳过所有收窄，继续尝试其他候选
                            if _pass == 1:
                                continue
                            # 第二轮：保留原有 count>1 逻辑
                            # 3b: strict mode auto-fix — 无前缀时自动尝试容器前缀
                            if test_prefix is None:
                                for try_ct in ['dialog', 'drawer', 'message-box']:
                                    if try_ct not in CONTAINER_XPATH:
                                        continue
                                    try_prefix = CONTAINER_XPATH[try_ct]
                                    # BUG-13 修复：前缀注入到括号内部
                                    inner, wrap = _unwrap_positional(bare_xpath)
                                    scoped_raw = _rewrap_positional(try_prefix + inner, wrap)
                                    scoped_full = inject_hidden_filter(f"xpath={scoped_raw}", elem_type=elem_type)
                                    try:
                                        scoped_count = page.locator(scoped_full).count()
                                        if scoped_count == 1:
                                            print(f"    [INFO] 3b strict mode 修复: 自动添加 {try_ct} 前缀")
                                            return _ret(scoped_full, try_ct, 1, candidate_index)
                                    except Exception as _e:
                                        # H4: 记录异常（XPath语法错误/超时/其他）便于调试
                                        print(f"    [WARN] H4: 3b strict 前缀探测异常({try_ct}): {_e}")
                            # P2-4: [last()] strategy for dialog/drawer (topmost = last opened)
                            if test_prefix in ('dialog', 'drawer'):
                                wrapped_last = f"({test_xpath})[last()]"
                                full_last = inject_hidden_filter(f"xpath={wrapped_last}", elem_type=elem_type)
                                try:
                                    cnt_last = page.locator(full_last).count()
                                    if cnt_last == 1:
                                        return _ret(full_last, test_prefix, 1, candidate_index)
                                except Exception as _e:
                                    print(f"    [WARN] H4: [last()] 探测异常: {_e}")
                            # Fallback: [1]
                            wrapped = f"({test_xpath})[1]"
                            full_wrapped = inject_hidden_filter(f"xpath={wrapped}", elem_type=elem_type)
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
        # Element UI: el-loading-mask, Ant Design: ant-spin-spinning
        mask = page.locator("xpath=//div[(contains(@class,'el-loading-mask') or contains(@class,'ant-spin-spinning')) and not(contains(@style,'display: none'))]")
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
        "//div[contains(@class,'el-dialog')] | "
        "//div[contains(@class,'el-message-box')] | "
        "//div[contains(@class,'ant-drawer')"
        " and not(contains(@class,'ant-drawer-hidden'))] | "
        "//div[contains(@class,'ant-modal')"
        " and not(contains(@class,'ant-modal-hidden'))]"
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
                    // Element UI: .el-select
                    const sel_eu = sibling.querySelector('.el-select') ||
                                (sibling.classList && sibling.classList.contains('el-select') ? sibling : null);
                    if (sel_eu) return 'select';
                    // Ant Design: .ant-select
                    const sel_antd = sibling.querySelector('.ant-select') ||
                                (sibling.classList && sibling.classList.contains('ant-select') ? sibling : null);
                    if (sel_antd) return 'select';
                    // Element UI: .el-date-editor
                    const dateEl = sibling.querySelector('.el-date-editor');
                    if (dateEl) return 'date';
                    // Ant Design: .ant-picker
                    const pickerEl = sibling.querySelector('.ant-picker');
                    if (pickerEl) return 'date';
                    const inp = sibling.querySelector('input:not([type=hidden])') ||
                                (sibling.tagName === 'INPUT' ? sibling : null);
                    if (inp) return 'input';
                    sibling = sibling.nextElementSibling;
                }}

                // Strategy 2: el-form-item parent structure (Element UI)
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
                // Strategy 2b: ant-form-item parent structure (Ant Design)
                const formItemAntd = node.closest('.ant-form-item');
                if (formItemAntd) {{
                    const content = formItemAntd.querySelector('.ant-form-item-control-input-content');
                    if (content) {{
                        if (content.querySelector('textarea')) return 'textarea';
                        if (content.querySelector('.ant-select')) return 'select';
                        if (content.querySelector('.ant-picker')) return 'date';
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


def _iframe_execute_action(keyword, element_loc, verified_locator, page, params, data_dict, desc):
    """iframe 内执行具体操作（点击/填充/悬停等），统一返回格式。

    Args:
        keyword: frame_* 关键字
        element_loc: Playwright Locator（已在 iframe 内定位到目标元素）
        verified_locator: 验证通过的定位器字符串
        page: Playwright page 对象
        params: 步骤参数 dict
        data_dict: 数据变量字典
        desc: 步骤描述（仅用于日志）

    Returns:
        tuple: (verified_locator, container_ct, is_skip, is_best_guess, hit_source)
    """
    try:
        if keyword == 'frame_click_element':
            element_loc.first.click(timeout=5000)
            _smart_wait_after_action(page)
            print(f"    [OK] frame_click_element: '{desc}'")
            return verified_locator, None, False, False, 'iframe'

        elif keyword == 'frame_fill_value':
            value = params.get('value', '') if isinstance(params, dict) else ''
            value = resolve_var(value, data_dict)
            if not value:
                value = PROBE_FILL_VALUES.get('input', '测试')
            element_loc.first.fill(value, timeout=5000)
            print(f"    [OK] frame_fill_value: '{desc}'")
            return verified_locator, None, False, False, 'iframe'

        elif keyword == 'frame_hover':
            element_loc.first.hover(timeout=5000)
            print(f"    [OK] frame_hover: '{desc}'")
            return verified_locator, None, False, False, 'iframe'

        elif keyword == 'frame_focus_element':
            element_loc.first.focus(timeout=5000)
            print(f"    [OK] frame_focus_element: '{desc}'")
            return verified_locator, None, False, False, 'iframe'

        elif keyword == 'frame_select_option':
            opt_value = params.get('value', '') if isinstance(params, dict) else ''
            opt_value = resolve_var(opt_value, data_dict)
            element_loc.first.select_option(opt_value, timeout=5000)
            print(f"    [OK] frame_select_option: '{desc}'")
            return verified_locator, None, False, False, 'iframe'

        elif keyword in ('frame_except_to_be_visible', 'frame_except_to_be_hidden', 'frame_except_to_have_text'):
            from playwright.sync_api import expect
            if keyword == 'frame_except_to_be_visible':
                expect(element_loc.first).to_be_visible(timeout=5000)
            elif keyword == 'frame_except_to_be_hidden':
                expect(element_loc.first).to_be_hidden(timeout=5000)
            elif keyword == 'frame_except_to_have_text':
                expected_text = params.get('expect_results', '') if isinstance(params, dict) else ''
                expected_text = resolve_var(expected_text, data_dict)
                expect(element_loc.first).to_contain_text(expected_text, timeout=5000)
            print(f"    [OK] {keyword}: '{desc}'")
            return verified_locator, None, False, False, 'iframe'

        else:
            print(f"    [WARN] 未实现的 frame 关键字: {keyword}，仅验证 locator 存在")
            return verified_locator, None, False, False, 'iframe'

    except Exception as e:
        err_str = str(e)
        if 'Timeout' in err_str:
            print(f"    [ERROR] iframe 元素操作超时: {verified_locator[:80]}")
        else:
            print(f"    [ERROR] {keyword} 执行失败: {err_str[:100]}")
        return None, None, False, False, None


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

    # L4a: 从 discovery_data 提取框架信息
    _framework = discovery_data.get('framework') if discovery_data else None

    # 清空上一次执行的 iframe 发现（防止跨步骤状态泄漏）
    # 只有调用 verify_locator() 的步骤才会重新设置此变量
    global _last_iframe_discovery
    _last_iframe_discovery = None

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

    # 特殊处理 set_random_variable：模拟变量生成并注入 data_dict
    # 这样后续步骤的 ${random_field_xxx} 可以正确解析
    if keyword == 'set_random_variable':
        var_name = params.get('name', '') if isinstance(params, dict) else ''
        prefix = params.get('prefix', '') if isinstance(params, dict) else ''
        if var_name:
            # 解析 prefix 中可能包含的变量引用
            prefix = resolve_var(prefix, data_dict)
            # 生成确定性值（非随机，保证 Phase 6 每次一致）
            simulated_value = f"{prefix}_phase6_test"
            data_dict[var_name] = simulated_value
            print(f"    [SIMULATE] set_random_variable: {var_name} = '{simulated_value}'")
        return None, None, True, False, 'skip'

    if keyword in SKIP_KEYWORDS:
        # 浏览器生命周期 / 认证注入 / 日志 — 不影响页面状态，直接跳过
        return None, None, False, False, None

    # --- EXECUTE_KEYWORDS: 影响页面状态，必须实际执行 ---
    if keyword == 'open_url':
        url = params.get('url', '') if isinstance(params, dict) else ''
        if url:
            url = resolve_var(url, data_dict)
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                _smart_wait_after_action(page)
            except Exception as e:
                print(f"    [ERROR] open_url failed: {str(e)[:80]}")
        return None, None, False, False, None

    if keyword == 'refresh':
        try:
            page.reload(wait_until='domcontentloaded', timeout=30000)
            _smart_wait_after_action(page)
        except Exception as _e:
            print(f"    [WARN] page.reload failed: {_e}")
        return None, None, False, False, None

    if keyword == 'go_back':
        try:
            page.go_back()
            _smart_wait_after_action(page)
        except Exception as e:
            print(f"    [WARN] go_back failed: {str(e)[:80]}")
        return None, None, False, False, None

    if keyword == 'wait_for_loading_complete':
        _wait_for_dom_stable(page, timeout_ms=5000)
        return None, None, False, False, None

    if keyword == 'wait_for_time':
        _seconds = 1
        if isinstance(params, dict):
            _seconds = params.get('seconds', params.get('duration', 1))
        elif desc:
            _m = re.search(r'(\d+)', desc)
            if _m:
                _seconds = int(_m.group(1))
        try:
            page.wait_for_timeout(int(_seconds) * 1000)
        except Exception:
            pass
        return None, None, False, False, None

    if keyword == 'execute_script':
        script = params.get('script', '') if isinstance(params, dict) else ''
        if script:
            try:
                page.evaluate(script)
            except Exception as e:
                print(f"    [WARN] execute_script failed: {str(e)[:80]}")
        return None, None, False, False, None

    if keyword == 'wait_for_element':
        _wloc = params.get('locator', '') if isinstance(params, dict) else ''
        if _wloc:
            _wloc = resolve_var(_wloc, data_dict)
            try:
                page.locator(_wloc).first.wait_for(state='attached', timeout=10000)
            except Exception:
                pass
        return None, None, False, False, None

    if keyword == 'wait_for_element_hidden':
        _wloc = params.get('locator', '') if isinstance(params, dict) else ''
        if _wloc:
            _wloc = resolve_var(_wloc, data_dict)
            try:
                page.locator(_wloc).first.wait_for(state='hidden', timeout=10000)
            except Exception:
                pass
        return None, None, False, False, None

    if keyword == 'check_page_loaded':
        _wait_for_dom_stable(page, timeout_ms=5000)
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
    locator = resolve_var(locator, data_dict)  # Resolve inline ${data.field}

    # 方案 2：基于 locator 前缀的容器等待
    # 如果原始 locator 包含容器前缀（el-dialog/el-drawer），等待该容器出现
    # 这样可以确保后续 detect_visible_containers 能正确检测到容器
    _container_wait_result = None
    if not is_new_page_context and locator and locator.startswith('xpath='):
        _raw_xpath = locator[6:]  # 去掉 xpath= 前缀
        _container_match = re.match(
            r"^\(?//div\[contains\(@class,\s*'el-(dialog|drawer)'\)\]",
            _raw_xpath
        )
        if _container_match:
            _container_type = _container_match.group(1)
            _container_xpath = f"//div[contains(@class, 'el-{_container_type}')]"
            print(f"    [TRACE-P6] Container-wait: waiting for el-{_container_type}")
            try:
                page.wait_for_selector(
                    f"xpath={_container_xpath}",
                    state='attached',
                    timeout=5000
                )
                _container_wait_result = _container_type
                print(f"    [TRACE-P6] Container-wait: el-{_container_type} detected")
            except Exception as e:
                print(f"    [TRACE-P6] Container-wait: timeout waiting for el-{_container_type}")

    # Extract label: 优先使用 Phase 5 写入的结构化 label 字段（P0 修复）
    # Phase 5 的 label 是生成 XPath 时使用的原始标签，比 desc regex 提取更准确
    # 回退到 regex 提取保持向后兼容（旧 case YAML 无 label 字段时）
    label = step.get('label', '')
    if not label:
        # BUG-4 D1 fix: 增加「」匹配（中文角括号在测试用例中极为常见）
        # 匹配: ASCII “, 左弯引号 U+201C, 右弯引号 U+201D, 左角括号 U+300C
        # F3: 提取所有引号对，取最后一个（实际操作对象）
        # 单引号对: re.findall[-1] 与 re.search 结果相同，零影响
        # 多引号对: “点击「第」一条记录的「更多」按钮” → ['第', '更多'] → '更多'
        _all_labels = re.findall(r'[“\'””「]([^”\'””「」]+)[“\'””」]', desc)
        label = _all_labels[-1] if _all_labels else ''

    # D4: Enhanced element type inference (unified in _element_types)
    # BUG-3 fix: can now produce 'table-action-button'
    # BUG-5 fix: can now produce 'detail-link'
    # BUG-7 fix: pass locator_ref for _select/_editable suffix detection
    elem_type = _infer_elem_type(keyword, desc, locator_ref=raw_locator_ref)
    # [TRACE-P6] 类型推断结果
    print(f"    [TRACE-P6] infer: label='{label}', elem_type={elem_type}")

    # ── iframe 快速通道：frame_* 关键字跳过主页面 VLC，直接用 frame_locator 验证 ──
    if keyword.startswith('frame_'):
        frame_ref = params.get('frame', '') if isinstance(params, dict) else ''
        if not frame_ref:
            print(f"    [ERROR] {keyword} 缺少 frame 参数: '{desc}'")
            return None, None, False, False, None

        # 解析 frame 参数（兼容 xpath= 和 css= 前缀）
        frame_selector = resolve_var(frame_ref, data_dict)
        if '${' in frame_selector:
            frame_selector = resolve_locator({'locator': frame_selector}, pages_dict)
        # 剥离前缀供 Playwright API 使用
        if frame_selector.startswith('xpath='):
            frame_selector = frame_selector[6:]
        elif frame_selector.startswith('css='):
            frame_selector = frame_selector[4:]

        # 降级检查：如果 frame_selector 或 locator 解析为空，说明变量未定义，跳过快速通道
        # 让后续的正常流程（包括 iframe 探测）处理
        # locator 为空时：快速通道无法操作（Playwright 不接受空 locator），
        # 必须降级到正常流程，让基于 label 的 iframe 探测（行2139+）触发回写
        if not frame_selector:
            print(f"    [TRACE-P6] iframe 快速通道: frame_selector 为空（变量未定义），降级到正常流程")
            # 不 return，让代码继续执行后续的正常逻辑（包括 iframe 探测）
        elif not locator:
            print(f"    [TRACE-P6] iframe 快速通道: locator 为空（原始字段未写入），降级到正常流程")
            print(f"    [TRACE-P6]   frame_selector='{frame_selector}' 有效，但 locator 为空")
            print(f"    [TRACE-P6]   将由基于 label 的 iframe 探测回写原始字段")
            # 不 return，让代码继续执行后续的正常逻辑（包括 iframe 探测）
        else:
            print(f"    [TRACE-P6] iframe 快速通道: frame='{frame_selector}', locator='{locator[:80]}'")

            # 提取纯 XPath（用于回退扫描）
            _iframe_xpath = locator.replace('xpath=', '', 1) if locator.startswith('xpath=') else locator

            # ── 策略 1: 用指定选择器尝试 ──
            _frame_found = False
            try:
                page.wait_for_selector(frame_selector, state='attached', timeout=10000)
                page.wait_for_timeout(1000)
                _frame_found = True
            except Exception:
                print(f"    [TRACE-P6] iframe 选择器 '{frame_selector}' 未找到，回退扫描所有 iframe")

            if _frame_found:
                try:
                    frame_loc = page.frame_locator(frame_selector)
                    element_loc = frame_loc.locator(locator)

                    count = 0
                    for retry in range(5):
                        count = element_loc.count()
                        if count > 0:
                            break
                        print(f"    [TRACE-P6] iframe element count=0, retry {retry+1}/5...")
                        page.wait_for_timeout(1000)

                    print(f"    [TRACE-P6] iframe element count={count}")
                    if count > 0:
                        # 修改 9: 验证 frame_selector 在 DOM 中真实存在
                        # 如果 DOM 中找不到，说明当前 selector 有误，需要触发回写
                        try:
                            dom_count = page.locator(frame_selector).count()
                            if dom_count == 0:
                                print(f"    [TRACE-P6] ⚠️ frame_selector '{frame_selector}' 在 DOM 中不存在，触发回写")
                                # 调用 _try_find_in_iframes() 获取正确的 selector
                                iframe_result = _try_find_in_iframes(page, locator)
                                if iframe_result and iframe_result.get('count', 0) > 0:
                                    # 设置 _iframe_discovery 触发回写
                                    _last_iframe_discovery = {
                                        'frame_selector': iframe_result['frame_selector'],
                                        'frame_name': iframe_result['frame_name'],
                                        'clean_xpath': iframe_result['clean_xpath'],
                                        'count': iframe_result['count'],
                                        'locator_ref': locator,
                                        'keyword': keyword,
                                    }
                                    # 用新的 selector 重试
                                    new_frame_selector = iframe_result['frame_selector']
                                    if new_frame_selector.startswith('xpath='):
                                        new_frame_selector = new_frame_selector[6:]
                                    elif new_frame_selector.startswith('css='):
                                        new_frame_selector = new_frame_selector[4:]
                                    frame_selector = new_frame_selector
                                    frame_loc = page.frame_locator(frame_selector)
                                    element_loc = frame_loc.locator(locator)
                                    count = element_loc.count()
                                    print(f"    [TRACE-P6] 使用新 selector: {frame_selector}, count={count}")
                        except Exception as dom_err:
                            print(f"    [TRACE-P6] DOM 验证异常: {dom_err}")

                        verified_locator = locator
                        return _iframe_execute_action(keyword, element_loc, verified_locator,
                                                      page, params, data_dict, desc)
                except Exception as e:
                    print(f"    [TRACE-P6] 指定 iframe 操作失败: {str(e)[:80]}，回退扫描")

            # ── 策略 2: 回退 — 扫描所有 iframe 查找目标元素 ──
            _iframe_result = _try_find_in_iframes(page, locator)
            if _iframe_result and _iframe_result.get('count', 0) > 0:
                _fb_selector = _iframe_result['frame_selector']
                _frame_name = _iframe_result.get('frame_name', '')
                _clean_xpath = _iframe_result.get('clean_xpath', '')
                print(f"    [TRACE-P6] iframe 回退成功: selector='{_fb_selector}', name='{_frame_name}', clean_xpath='{_clean_xpath[:60]}'")
                verified_locator = locator

                # 关键修复：用 page.frame(name=...) 直接获取 Frame 对象，而不是 frame_locator(css)
                # 因为 confirmIframe 在 DOM 中不可达（CSS 选择器找不到），但 page.frames 能按 name 找到
                frame_obj = None
                if _frame_name:
                    frame_obj = page.frame(name=_frame_name)
                    print(f"    [TRACE-P6] 使用 page.frame(name='{_frame_name}') 获取 Frame 对象")

                if not frame_obj:
                    # 回退：尝试用 frame_locator
                    frame_obj = page.frame_locator(_fb_selector)
                    print(f"    [TRACE-P6] 回退使用 frame_locator('{_fb_selector}')")

                # 使用清理后的 XPath（去掉 hidden filter 和 [1] 索引），避免 iframe 内定位失败
                _fb_locator = f'xpath={_clean_xpath}' if _clean_xpath else locator
                element_loc = frame_obj.locator(_fb_locator)
                return _iframe_execute_action(keyword, element_loc, verified_locator,
                                              page, params, data_dict, desc)

            print(f"    [ERROR] iframe 内未找到元素: '{desc}'")
            print(f"    [ERROR]   frame='{frame_selector}', locator='{locator[:100]}'")
            return None, None, False, False, None

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

    # [TRACE-P6] 容器检测详情
    print(f"    [TRACE-P6] detect_visible_containers: {visible_containers if visible_containers else 'empty'}")
    print(f"    [TRACE-P6] current_ct: {current_ct}, container_context(传入): {container_context}, is_new_page: {is_new_page_context}")

    # 容器上下文 fallback：当 detect_visible_containers 返回空但有上一步传递的容器上下文时使用
    if current_ct is None and container_context and not is_new_page_context:
        current_ct = container_context
        print(f"    [TRACE-P6] [CONTEXT-FALLBACK] detect_visible_containers 返回空，使用上次容器上下文: {container_context}")

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

    # [TRACE-P6] 候选构建开始
    print(f"    [TRACE-P6] Building candidates: label='{label}', elem_type={elem_type}, "
          f"is_placeholder={is_placeholder}")

    # 优先级 0: KB templates (highest priority — stable, universal XPath patterns)
    kb_locators = []
    if label:
        kb_locators = _get_kb_locators(elem_type, label, _framework)
        print(f"    [TRACE-P6] KB templates: {len(kb_locators)} locators")
        for i, kb_xpath in enumerate(kb_locators):
            has_prefix = ('el-dialog' in kb_xpath or 'el-drawer' in kb_xpath or 'el-message-box' in kb_xpath
                         or 'ant-modal' in kb_xpath or 'ant-drawer' in kb_xpath)
            print(f"    [TRACE-P6]   KB[{i}]: has_prefix={has_prefix}, {kb_xpath[:100]}")

        # ─── el-select 展开步骤定位器转换 ───
    # ─── el-select 展开步骤定位器转换 ───
    # 同时保留 input 候选和转换后的 div 候选，让 VLC 验证哪个 count=1
    # - input 候选：run8 验证有效（点击 input 展开下拉框）
    # - div 候选：DOM 中 el-select 容器是 input 的祖先，部分场景必须用 div
    if elem_type == 'el-select':
        _field_name = ''
        if raw_locator_ref and raw_locator_ref.startswith('${'):
            _field_name = raw_locator_ref.split('.')[-1].rstrip('}')

        _is_expand = _is_el_select_expand(_field_name, desc)
        # [TRACE-P6-ELSELECT] el-select 类型推断详情
        print(f"    [TRACE-P6-ELSELECT] field_name='{_field_name}', is_expand={_is_expand}, "
              f"desc='{desc}'")
        if _is_expand:
            # 打印原始 locator 的索引信息，用于诊断 _2_expand 索引丢失问题
            _resolved_for_dbg = locator  # 已 resolve 的 locator
            _idx_match = re.search(r'\)\[(\d+)\]\s*$', _resolved_for_dbg)
            _idx_val = _idx_match.group(1) if _idx_match else 'N/A(no trailing [n])'
            print(f"    [TRACE-P6-ELSELECT] resolved_locator index=[{_idx_val}], "
                  f"locator={_resolved_for_dbg[:120]}")
            # 检查 _2_ 变体是否索引正确
            if '_2_' in _field_name and _idx_val == '1':
                print(f"    [WARN-ELSELECT] _2_ variant has index [1]! "
                      f"Expected [2]. field='{_field_name}'")

        if _is_expand:
            # ─── 方案B：辅助函数 + kb-label 候选生成 ───
            def _replace_trailing_index(xpath: str, new_idx: str) -> str:
                """只替换 xpath 最末尾的 )[N]，避免误改中间索引"""
                m = re.search(r'\)\[(\d+)\]\s*$', xpath)
                if m and m.group(1) == '1':
                    return xpath[:m.start()] + f')[{new_idx}]'
                return xpath

            # 提取原始 locator 的索引（用于 _2_expand 等变体）
            _orig_idx = '1'
            if locator:
                _idx_m = re.search(r'\)\[(\d+)\]\s*$', locator)
                if _idx_m:
                    _orig_idx = _idx_m.group(1)
            print(f"    [TRACE-P6] el-select expand: 保留 input + 生成 div 双候选, orig_idx=[{_orig_idx}]")

            # ─── 方案B：新增 kb-label 候选（基于 //label 的 div 容器）───
            if label:
                _kb_label_cands = [
                    # Pattern L1: label 的兄弟元素后代中的 el-select（标准 Element UI 布局）
                    f"(//label[contains(.,'{label}')]//following-sibling::*[self::div or self::span]"
                    f"//div[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))])[{_orig_idx}]",
                    # Pattern L2: label 的兄弟元素本身就是 el-select（紧凑布局）
                    f"(//label[contains(.,'{label}')]//following-sibling::*[self::div or self::span]"
                    f"[contains(@class,'el-select') and not(contains(@class,'el-select-dropdown'))])[{_orig_idx}]",
                ]
                print(f"    [TRACE-P6-ELSELECT] kb-label candidates generated: {len(_kb_label_cands)} patterns")

            div_locators = []
            for kb_xpath in kb_locators:
                # ★★★ 修改点 2：过滤 placeholder 模式 ★★★
                # 原因：placeholder 模式经 _convert_input_to_el_select 转换后会丢失所有 label 约束
                # 变成裸 div，在抽屉未打开时可能 count=1 被误选
                if 'contains(@placeholder' in kb_xpath:
                    print(f"    [TRACE-P6-ELSELECT] Skip placeholder KB pattern: {kb_xpath[:80]}")
                    continue

                if 'input[@class' in kb_xpath or 'el-input__inner' in kb_xpath:
                    dual_cands = _generate_el_select_candidates(kb_xpath)
                    if _orig_idx != '1':
                        dual_cands = [_replace_trailing_index(c, _orig_idx) for c in dual_cands]
                        print(f"    [TRACE-P6-ELSELECT] KB div candidates index adjusted: [1] → [{_orig_idx}]")
                    div_locators.extend(dual_cands)

            # ─── 候选排序策略 ───
            # 1. kb-label 候选（idx=[N]）优先（更可靠的 label 定位器）
            # 2. 原始 locator（idx=[N]）作为 fallback
            # 3. kb input 候选（idx 调整后）
            # 4. kb-div 候选（idx 调整后）

            # Step 1: kb-label 候选（方案B 核心改进）— 优先于 original
            if label and _kb_label_cands:
                for _kb_loc in _kb_label_cands:
                    if not any(c[0] == _kb_loc for c in candidates):
                        candidates.append((_kb_loc, 'kb-label'))
                print(f"    [TRACE-P6-ELSELECT] kb-label candidates added: {len(_kb_label_cands)}")

            # Step 2: 原始 locator 作为 fallback
            if _orig_idx != '1' and locator and not locator.startswith('${'):
                _orig_bare = (locator.replace('xpath=', '', 1)
                              if locator.startswith('xpath=') else locator)
                if not any(c[0] == _orig_bare for c in candidates):
                    candidates.append((_orig_bare, 'original'))
                print(f"    [TRACE-P6-ELSELECT] Original locator (idx=[{_orig_idx}]) as fallback")

            # Step 3: kb input 候选
            for kb_xpath in kb_locators:
                if _orig_idx != '1':
                    _kb_adj = _replace_trailing_index(kb_xpath, _orig_idx)
                    candidates.append((_kb_adj, 'kb'))
                else:
                    candidates.append((kb_xpath, 'kb'))

            # Step 4: kb-div 候选
            for div_xpath in div_locators:
                if not any(c[0] == div_xpath for c in candidates):
                    candidates.append((div_xpath, 'kb-div'))
        else:
            for kb_xpath in kb_locators:
                candidates.append((kb_xpath, 'kb'))
    else:
        for kb_xpath in kb_locators:
            candidates.append((kb_xpath, 'kb'))
    # ─── el-select 展开步骤定位器转换结束 ───

    # 优先级 1: Discovery locator (Phase 4 verified)
    discovery_ct = None
    _discovery_verified = False  # Fix-6 条件：跟踪 discovery 是否已验证
    if discovery_data and label:
        print(f"    [TRACE-P6] Discovery lookup: preferred_container={current_ct}, elem_type={elem_type}")
        disc_locator, discovery_ct = _find_in_discovery(
            discovery_data, label, preferred_container=current_ct,
            elem_type=elem_type)
        # [TRACE-P6] discovery 查找结果
        print(f"    [TRACE-P6] discovery: found={disc_locator is not None}, "
              f"discovery_ct={discovery_ct}")
        if disc_locator:
            has_prefix = ('el-dialog' in disc_locator or 'el-drawer' in disc_locator or 'el-message-box' in disc_locator
                         or 'ant-modal' in disc_locator or 'ant-drawer' in disc_locator)
            print(f"    [TRACE-P6]   disc_locator: has_prefix={has_prefix}, {disc_locator[:100]}{'...' if len(disc_locator) > 100 else ''}")
            _discovery_verified = True  # _find_in_discovery 只返回 verified=true 的元素
            disc_raw = (disc_locator.replace('xpath=', '')
                        if disc_locator.startswith('xpath=')
                        else disc_locator)
            # 去重（KB 可能和 discovery 一样）
            if not any(c[0] == disc_raw for c in candidates):
                candidates.append((disc_raw, 'discovery'))
                print(f"    [TRACE-P6]   Added to candidates as 'discovery'")
            else:
                print(f"    [TRACE-P6]   Skipped (duplicate of existing candidate)")

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
        has_prefix = ('el-dialog' in _resolved_bare or 'el-drawer' in _resolved_bare or 'el-message-box' in _resolved_bare
                     or 'ant-modal' in _resolved_bare or 'ant-drawer' in _resolved_bare)
        print(f"    [TRACE-P6] Original locator: has_prefix={has_prefix}, {_resolved_bare[:100]}")
        if not any(c[0] == _resolved_bare for c in candidates):    # Fix-6: 去重
            candidates.append((_resolved_bare, 'original'))   # Fix-6: 始终加入尾部作为安全网
            print(f"    [TRACE-P6]   Added to candidates as 'original'")
        else:
            print(f"    [TRACE-P6]   Skipped (duplicate of existing candidate)")
    else:
        print(f"    [TRACE-P6] Original locator skipped: is_var={locator.startswith('${')}, "
              f"is_placeholder={is_placeholder}, len={len(locator) if locator else 0}")

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
        return_index=True, elem_type=elem_type
    )

    # Determine hit source
    hit_source = sources.get(matched_index) if matched_index is not None else None

    # [TRACE-P6] VLC 返回结果
    print(f"    [TRACE-P6]   VLC result: verified={'Yes' if verified_locator else 'No'}, "
          f"prefix={matched_prefix}, count={count}, "
          f"hit_source={hit_source}, matched_index={matched_index}")
    if verified_locator:
        print(f"    [TRACE-P6]   verified_locator: {verified_locator[:120]}")

    # 初始化 iframe discovery 变量（函数级别，确保所有路径都能访问）
    _iframe_discovery = None

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
            _alt_kb = _get_kb_locators(_alt_type, label, _framework)
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
                discovery_ct=discovery_ct,
                return_index=True, elem_type=_alt_type
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
            fb = kb_fallback(elem_type, label, label, framework=_framework)
            # [TRACE-P6] kb_fallback 调用结果
            print(f"    [TRACE-P6] kb_fallback: result={'found' if fb and fb.get('locator') else 'None'}")
            if fb and fb.get('locator'):
                print(f"    [TRACE-P6]   strategy={fb.get('strategy', 'unknown')}")
                print(f"    [TRACE-P6]   fb_locator={fb['locator'][:100]}{'...' if len(fb['locator']) > 100 else ''}")
                fb_locator = inject_hidden_filter(fb['locator'], elem_type=elem_type)
                _fb_result = _verify_count_or_first(page, fb_locator, elem_type=elem_type)
                print(f"    [TRACE-P6]   _verify_count_or_first: result={'passed' if _fb_result else 'failed'}")
                if _fb_result:
                    verified_locator = _fb_result
                    print(f"    [KB-FALLBACK] '{desc}' → {fb.get('strategy', 'unknown')}")

        # Scheme 4: 跨类型 fallback — input-generic 失败时尝试 textarea-generic
        # 解决 Phase 5 将 textarea 字段误标为 _input 后缀的场景 D
        if not verified_locator and label and elem_type == 'input-generic':
            _CROSS_TYPE_ALIASES = ['textarea-generic']
            for _cross_type in _CROSS_TYPE_ALIASES:
                fb_cross = kb_fallback(_cross_type, label, label, framework=_framework)
                if fb_cross and fb_cross.get('locator'):
                    fb_locator = inject_hidden_filter(fb_cross['locator'], elem_type=_cross_type)
                    _fb_result = _verify_count_or_first(page, fb_locator, elem_type=_cross_type)
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
                # 确认/取消按钮 → framework-aware dialog prefix
                if _framework == 'ant-design':
                    fallback_xpath = f"//div[contains(@class,'ant-modal')]//button[contains(.,'{label}')]"
                else:
                    fallback_xpath = f"//div[contains(@class,'el-dialog')]//button[contains(.,'{label}')]"
                fallback_xpath = inject_hidden_filter(f"xpath={fallback_xpath}", elem_type='button')
                print(f"    [TRACE-P6]   D1 dialog-confirm: {fallback_xpath[:100]}")
                _fb_result = _verify_count_or_first(page, fallback_xpath, elem_type='button')
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
                    kb_locators = _get_kb_locators(elem_type, label, _framework)
                    print(f"    [TRACE-P6]   M11 KB fallback: {len(kb_locators)} locators, prefix={_fallback_prefix_str[:50]}")
                    for i, kb_loc in enumerate(kb_locators):
                        fallback_xpath = inject_hidden_filter(
                            f"xpath={_fallback_prefix_str}{kb_loc}", elem_type=elem_type)
                        print(f"    [TRACE-P6]     M11[{i}]: {fallback_xpath[:100]}")
                        _fb_result = _verify_count_or_first(page, fallback_xpath, elem_type=elem_type)
                        print(f"    [TRACE-P6]     M11[{i}] result: {'passed' if _fb_result else 'failed'}")
                        if _fb_result:
                            verified_locator = _fb_result
                            print(f"    [FALLBACK] '{desc}' → KB-{elem_type} with {_fallback_prefix} prefix (M11)")
                            _m11_resolved = True
                            break

                    # Scheme 4 (M11): 跨类型 fallback — input-generic 失败时尝试 textarea-generic
                    if not _m11_resolved and elem_type == 'input-generic':
                        for _cross_type in ('textarea-generic',):
                            cross_kb_locators = _get_kb_locators(_cross_type, label, _framework)
                            for kb_loc in cross_kb_locators:
                                fallback_xpath = inject_hidden_filter(
                                    f"xpath={_fallback_prefix_str}{kb_loc}", elem_type=_cross_type)
                                _fb_result = _verify_count_or_first(page, fallback_xpath, elem_type=_cross_type)
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
                            f"xpath={_fallback_prefix_str}{first_kb_candidate}", elem_type=elem_type)
                        print(f"    [TRACE-P6]   M11 first-kb-candidate: {fallback_xpath[:100]}")
                        _fb_result = _verify_count_or_first(page, fallback_xpath, elem_type=elem_type)
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
                _preserved_narrowed = _verify_count_or_first(page, _preserved_locator, elem_type=elem_type)
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
                    # 防止重复包裹：检查是否已有 (xpath)[N] 形式
                    inner, wrap = _unwrap_positional(_raw)
                    if not wrap:  # 没有已有 positional 包裹
                        verified_locator = f"xpath=({_raw})[1]"
                    else:
                        verified_locator = _preserved_locator  # 已有包裹，不重复添加
                    is_best_guess = True
                    print(f"    [PRESERVED] '{desc}' → 保留 Phase 5 原始 locator "
                          f"(discovery verified, count=0, [1] 防御{', 已有包裹跳过' if wrap else ''})")

        # ── iframe 探测：当主页面所有候选都 count=0 时，尝试在 iframe 中查找 ──
        # 构建 iframe 搜索用的 locator：
        #   1. locator 有值且含 xpath= 且非占位符 → 直接用
        #   2. locator 为 None 或 [待确认] → 用 KB candidates 构建搜索 XPath
        _iframe_search_locator = None
        if not verified_locator:
            if locator and 'xpath=' in locator and '[待确认]' not in locator:
                _iframe_search_locator = locator
            elif candidates:
                # locator 为 None 或 [待确认]，用第一个 KB 候选作为搜索 XPath
                kb_xpath = next((c[0] for c in candidates if c[1] == 'kb'), None)
                if kb_xpath is None and candidates:
                    kb_xpath = candidates[0][0]
                if kb_xpath:
                    _iframe_search_locator = f"xpath={kb_xpath}"
                    print(f"    [DEBUG-IFRAME] locator={'None' if locator is None else 'placeholder'}, "
                          f"using KB candidate for iframe search: {kb_xpath[:80]}")
            elif label:
                # 无 candidates 也无 locator，用 KB 生成一个搜索 XPath
                kb_locs = _get_kb_locators(elem_type, label, _framework)
                if kb_locs:
                    _iframe_search_locator = f"xpath={kb_locs[0]}"
                    print(f"    [DEBUG-IFRAME] no candidates, using KB-generated xpath: {kb_locs[0][:80]}")

        if not verified_locator and _iframe_search_locator:
            print(f"    [TRACE-P6]   iframe 探测: 主页面所有候选 count=0，尝试 iframe")
            print(f"    [DEBUG-IFRAME] 触发条件: desc='{desc}', locator='{_iframe_search_locator[:80]}...'")
            iframe_result = _try_find_in_iframes(page, _iframe_search_locator)
            print(f"    [DEBUG-IFRAME] _try_find_in_iframes 返回: {iframe_result is not None}")
            if iframe_result:
                print(f"    [DEBUG-IFRAME] 返回内容: count={iframe_result.get('count')}, "
                      f"frame_name={iframe_result.get('frame_name')}, "
                      f"frame_selector={iframe_result.get('frame_selector', '')[:80]}")
                # 提取 locator_ref（用于 writeback）
                _raw_locator_ref = _extract_locator_ref(step)
                _iframe_discovery = {
                    'frame_selector': iframe_result['frame_selector'],
                    'frame_name': iframe_result['frame_name'],
                    'clean_xpath': iframe_result['clean_xpath'],
                    'count': iframe_result['count'],
                    'locator': _iframe_search_locator,
                    'locator_ref': _raw_locator_ref,  # ${group.field} 格式
                    'keyword': keyword,
                    'desc': desc,
                }
                print(f"    [IFRAME-DISCOVERY] [OK] Found element in iframe '{iframe_result['frame_name']}'")
                print(f"    [IFRAME-DISCOVERY]   locator_ref={_raw_locator_ref}")
                # 使用 iframe 内的 locator（不添加容器前缀）
                verified_locator = _iframe_search_locator
                # 点击类元素：始终 [1] 包裹，防止运行时多匹配导致 strict mode violation
                if elem_type in CLICK_EXPAND_TYPES:
                    raw = verified_locator[6:] if verified_locator.startswith('xpath=') else verified_locator
                    inner, wrap = _unwrap_positional(raw)
                    if not wrap:  # 没有已有 positional 包裹
                        wrapped = f"({raw})[1]"
                        verified_locator = inject_hidden_filter(f"xpath={wrapped}", elem_type=elem_type)
                hit_source = 'iframe'
                is_best_guess = True
                _wrap_note = '[1] wrapped' if elem_type in CLICK_EXPAND_TYPES else 'raw'
                print(f"    [TRACE-P6]   iframe discovery success, return {_wrap_note} locator (no container prefix needed in iframe)")
        elif not verified_locator:
            print(f"    [TRACE-P6]   iframe 探测: 跳过（无可用搜索 locator）")

        # 存储 iframe discovery 到模块级变量（供 verify_orchestrator 读取）
        # global 声明已在函数开头（行1082）
        _last_iframe_discovery = _iframe_discovery

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
                kb_locs = _get_kb_locators(elem_type, label, _framework)
                if kb_locs:
                    _bg_locator = inject_hidden_filter(
                        f"xpath={_fallback_prefix_str}{kb_locs[0]}", elem_type=elem_type)
                    _bg_source = f'KB-{elem_type}'

            # 优先级 2: KB fallback 函数
            if not _bg_locator and label:
                fb = kb_fallback(elem_type, label, label)
                if fb and fb.get('locator'):
                    _bg_raw = fb['locator'].replace('xpath=', '') if fb['locator'].startswith('xpath=') else fb['locator']
                    _bg_locator = inject_hidden_filter(
                        f"xpath={_fallback_prefix_str}{_bg_raw}", elem_type=elem_type)
                    _bg_source = f'KB-fallback-{elem_type}'

            # 优先级 3: 第一个 KB candidate 的 xpath（优先），否则第一个 candidate
            if not _bg_locator and candidates:
                _first_kb_c = next((c[0] for c in candidates if c[1] == 'kb'), None)
                _fallback_xpath = _first_kb_c if _first_kb_c else candidates[0][0]
                _bg_locator = inject_hidden_filter(
                    f"xpath={_fallback_prefix_str}{_fallback_xpath}", elem_type=elem_type)
                _bg_source = 'first-kb-candidate' if _first_kb_c else 'first-candidate'

            # [TRACE-P6] R5 _bg_locator 计算结果
            print(f"    [TRACE-P6]   R5 _bg_source={_bg_source}")
            print(f"    [TRACE-P6]   R5 _bg_locator={_bg_locator[:120] if _bg_locator else 'None'}")

            if _bg_locator:
                # 防御性：count>1 时自动 [1] 收窄（与 M11 兜底路径一致）
                # 场景：表格异步加载未完成时 count=0，加载完 count>1（行按钮等）
                # 若不做 [1] 收窄，Phase 9 运行时 strict mode violation
                _bg_narrowed = _verify_count_or_first(page, _bg_locator, elem_type=elem_type)
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
                    # 防止重复包裹：检查是否已有 (xpath)[N] 形式
                    inner, wrap = _unwrap_positional(_raw)
                    if not wrap:  # 没有已有 positional 包裹
                        verified_locator = f"xpath=({_raw})[1]"
                        _bg_note = 'count=0, [1] 防御'
                    else:
                        verified_locator = _bg_locator  # 已有包裹，不重复添加
                        _bg_note = 'count=0, 已有包裹跳过'
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
    # _iframe_discovery 已在上方 iframe 探测阶段设置，此处不再初始化
    try:
        # click_select_option: 引擎内部处理 el-select 全流程，
        # Phase 6 只需验证触发器 locator 存在 + 点击展开
        if keyword == 'click_select_option':
            page.locator(verified_locator).click(timeout=5000)  # 方案 B: 严格模式
            # 验证下拉面板出现（证明触发器有效）— 支持 Element UI 和 Ant Design
            panel_xpath = ("xpath=//div[(contains(@class,'el-select-dropdown') "
                           "and not(contains(@style,'display: none'))) "
                           "or (contains(@class,'ant-select-dropdown') "
                           "and not(contains(@class,'ant-select-dropdown-hidden')))]")
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
            # iframe 感知点击：直接访问 frame 对象（与探测阶段一致）
            if _iframe_discovery:
                frame_selector = _iframe_discovery['frame_selector']
                clean_xpath = _iframe_discovery['clean_xpath']

                # 通过 frame_selector 找到对应的 frame 对象
                target_frame = None
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    # 匹配 frame selector
                    if frame.name and f'iframe[name="{frame.name}"]' == frame_selector:
                        target_frame = frame
                        break
                    elif frame_selector.startswith('iframe:nth-of-type('):
                        # 提取索引并匹配
                        match = re.search(r'nth-of-type\((\d+)\)', frame_selector)
                        if match:
                            target_idx = int(match.group(1))
                            frame_idx = 0
                            for f in page.frames:
                                if f != page.main_frame:
                                    frame_idx += 1
                                    if frame_idx == target_idx:
                                        target_frame = f
                                        break
                        if target_frame:
                            break
                    elif frame_selector.startswith('iframe[src*="'):
                        # 通过 src 匹配
                        src_pattern = frame_selector.replace('iframe[src*="', '').replace('"]', '')
                        if src_pattern in frame.url:
                            target_frame = frame
                            break
                    # XPath 格式匹配（2026-08-07 后 _try_find_in_iframes 返回 XPath）
                    elif frame_selector.startswith('xpath=//iframe[@id='):
                        # xpath=//iframe[@id="confirmIframe"]
                        id_match = re.search(r'@id="([^"]+)"', frame_selector)
                        if id_match:
                            target_id = id_match.group(1)
                            try:
                                iframe_el = frame.frame_element()
                                if iframe_el.get_attribute('id') == target_id:
                                    target_frame = frame
                                    break
                            except Exception:
                                pass
                    elif frame_selector.startswith('xpath=//iframe[@name='):
                        # xpath=//iframe[@name="xxx"]
                        name_match = re.search(r'@name="([^"]+)"', frame_selector)
                        if name_match:
                            target_name = name_match.group(1)
                            if frame.name == target_name:
                                target_frame = frame
                                break
                    elif frame_selector.startswith('xpath=//iframe[@class='):
                        # xpath=//iframe[@class="xxx"]
                        class_match = re.search(r'@class="([^"]+)"', frame_selector)
                        if class_match:
                            target_class = class_match.group(1)
                            try:
                                iframe_el = frame.frame_element()
                                if iframe_el.get_attribute('class') == target_class:
                                    target_frame = frame
                                    break
                            except Exception:
                                pass
                    elif frame_selector.startswith('xpath=//iframe[contains(@src,'):
                        # xpath=//iframe[contains(@src,"xxx")]
                        src_match = re.search(r'contains\(@src,"([^"]+)"\)', frame_selector)
                        if src_match:
                            src_pattern = src_match.group(1)
                            if src_pattern in frame.url:
                                target_frame = frame
                                break
                    elif frame_selector.startswith('xpath=(//iframe)'):
                        # xpath=(//iframe)[n] - 按位置索引匹配
                        idx_match = re.search(r'\[(\d+)\]$', frame_selector)
                        if idx_match:
                            target_idx = int(idx_match.group(1))
                            frame_idx = 0
                            for f in page.frames:
                                if f != page.main_frame:
                                    frame_idx += 1
                                    if frame_idx == target_idx:
                                        target_frame = f
                                        break
                            if target_frame:
                                break

                if target_frame:
                    element = target_frame.locator(f'xpath={clean_xpath}')
                    if element.count() > 0:
                        element.first.click(timeout=5000)
                        verified_locator = f"xpath={clean_xpath}"  # 设置验证后的定位器
                        is_best_guess = False  # 实际点击成功，不是猜测
                        print(f"    [TRACE-P6]   iframe click success: frame={frame_selector}, xpath={clean_xpath[:60]}")
                    else:
                        print(f"    [WARN] iframe 内元素未找到 (count=0)，回退主页面")
                        page.locator(verified_locator).click(timeout=5000)
                else:
                    print(f"    [WARN] 未找到匹配的 frame，回退主页面")
                    page.locator(verified_locator).click(timeout=5000)
            else:
                # BUG-9: For row buttons (ancestor::tbody), hover the row first to reveal hidden buttons
                if 'tbody' in verified_locator:
                    try:
                        row = page.locator("xpath=(//tr[contains(@class,'el-table__row') or contains(@class,'ant-table-row')])[1]")
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

                # ── Layered click: count_check → scroll → normal → retry → dispatch_event ──
                # 解决 drawer/dialog 内按钮因动画/遮挡/视口外导致的 click 超时
                # 正常路径（click 一次成功）零额外开销

                # 层 0: count check（快速判断元素是否存在，避免 count=0 时的无效重试）
                _el_count = page.locator(verified_locator).count()
                if _el_count == 0:
                    print(f"    [ERROR] '{desc}': element not found (count=0), skip click")
                    print(f"    [DEBUG-COUNT=0] locator: {verified_locator[:150]}")
                    print(f"    [DEBUG-COUNT=0] current_url: {page.url[:100]}")
                    # 诊断 el-table 和更多按钮状态
                    try:
                        _diag = page.evaluate("""(() => {
                            const result = {};
                            result.title = document.title;
                            result.url = window.location.href;

                            // el-table 状态
                            const tables = document.querySelectorAll('.el-table');
                            result.table_count = tables.length;
                            result.tables = [];
                            tables.forEach((t, i) => {
                                const rect = t.getBoundingClientRect();
                                result.tables.push({
                                    index: i,
                                    rect: {w: Math.round(rect.width), h: Math.round(rect.height)},
                                    hasFixedRight: !!t.querySelector('.el-table__fixed-right')
                                });
                            });

                            // el-table__fixed-right 状态
                            const fixedRights = document.querySelectorAll('.el-table__fixed-right');
                            result.fixed_right_count = fixedRights.length;
                            result.fixed_rights = [];
                            fixedRights.forEach((fr, i) => {
                                const rows = fr.querySelectorAll('tbody tr');
                                const rect = fr.getBoundingClientRect();
                                result.fixed_rights.push({
                                    index: i,
                                    row_count: rows.length,
                                    rect: {w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top)}
                                });
                            });

                            // 搜索「更多」按钮
                            const moreEls = [];
                            document.querySelectorAll('span, button, a, div').forEach(el => {
                                const t = (el.textContent || '').trim();
                                if (t === '更多') {
                                    const rect = el.getBoundingClientRect();
                                    moreEls.push({
                                        tag: el.tagName,
                                        class: (typeof el.className === 'string' ? el.className : '').slice(0, 60),
                                        rect: {w: Math.round(rect.width), h: Math.round(rect.height)},
                                        inFixedRight: !!el.closest('.el-table__fixed-right'),
                                        inBodyWrapper: !!el.closest('.el-table__body-wrapper')
                                    });
                                }
                            });
                            result.more_elements_count = moreEls.length;
                            result.more_elements_sample = moreEls.slice(0, 5);

                            return result;
                        })()""")
                        print(f"    [DEBUG-COUNT=0] title: {_diag.get('title', 'N/A')}")
                        print(f"    [DEBUG-COUNT=0] url: {_diag.get('url', 'N/A')[:100]}")
                        print(f"    [DEBUG-COUNT=0] el-table count: {_diag.get('table_count', 0)}")
                        for t in _diag.get('tables', []):
                            print(f"      table[{t['index']}]: rect={t['rect']}, hasFixedRight={t['hasFixedRight']}")
                        print(f"    [DEBUG-COUNT=0] el-table__fixed-right count: {_diag.get('fixed_right_count', 0)}")
                        for fr in _diag.get('fixed_rights', []):
                            print(f"      fixed-right[{fr['index']}]: rows={fr['row_count']}, rect={fr['rect']}")
                        print(f"    [DEBUG-COUNT=0] 「更多」元素 count: {_diag.get('more_elements_count', 0)}")
                        for me in _diag.get('more_elements_sample', []):
                            pos = "FIXED-RIGHT" if me['inFixedRight'] else ("BODY" if me['inBodyWrapper'] else "OTHER")
                            print(f"      <{me['tag']}> class=\"{me['class']}\" rect={me['rect']} [{pos}]")
                    except Exception as _diag_err:
                        print(f"    [DEBUG-COUNT=0] 诊断失败: {str(_diag_err)[:100]}")
                    # 容器探测
                    _fail_ct = detect_visible_containers(page)
                    if _fail_ct:
                        for _fct in CONTAINER_TYPES:
                            if _fct in _fail_ct:
                                print(f"    [TRACE-P6]   container detected despite count=0: {_fct}")
                                return verified_locator, _fct, False, is_best_guess, hit_source
                    return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

                # 层 1: scroll into view（元素存在时）
                try:
                    page.locator(verified_locator).first.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass  # scroll failure is non-fatal

                try:
                    page.locator(verified_locator).click(timeout=5000)
                except Exception as _click_err:
                    # 层 2: 等 2s + 重试正常 click（给动画/loading 更多时间）
                    try:
                        page.wait_for_timeout(2000)
                        page.locator(verified_locator).click(timeout=5000)
                        print(f"    [WARN] click retry succeeded: '{desc}'")
                    except Exception:
                        # 层 3: dispatch_event 绕过可操作性检查
                        try:
                            page.locator(verified_locator).first.dispatch_event('click')
                            print(f"    [WARN] dispatch_event fallback: '{desc}'")
                        except Exception as _final_err:
                            print(f"    [ERROR] '{desc}': all click attempts failed. "
                                  f"Last error: {str(_final_err)[:80]}")
                            # 即使全部失败，也做最终容器探测
                            _fail_ct = detect_visible_containers(page)
                            if _fail_ct:
                                for _fct in CONTAINER_TYPES:
                                    if _fct in _fail_ct:
                                        print(f"    [TRACE-P6]   container detected despite click failure: {_fct}")
                                        return verified_locator, _fct, False, is_best_guess, hit_source
                            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source
            # [TRACE-P6] click 成功后：记录页面 URL
            try:
                _post_click_url = page.url
                _post_click_title = page.title()
                print(f"    [TRACE-P6]   click success: url={_post_click_url[:80]}, title={_post_click_title[:40]}")
                # [DEBUG-IFRAME] 记录 click 后的 iframe 状态
                _frames_count = len(page.frames)
                print(f"    [DEBUG-IFRAME] page.frames after click: {_frames_count}")
                if _frames_count > 1:
                    for _fi, _fr in enumerate(page.frames):
                        if _fr != page.main_frame:
                            _fr_name = _fr.name or 'unnamed'
                            _fr_url = _fr.url[:60] if _fr.url else 'N/A'
                            print(f"    [DEBUG-IFRAME]   Frame[{_fi}]: name='{_fr_name}', url='{_fr_url}'")
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
            print(f"    [TRACE-P6]   containers after click: {new_containers if new_containers else 'none'}")
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
                value = PROBE_FILL_VALUES.get('input', '测试')

            # iframe 感知填充：使用 frame_locator
            if _iframe_discovery:
                frame_selector = _iframe_discovery['frame_selector']
                frame_loc = page.frame_locator(frame_selector)
                element = frame_loc.locator(verified_locator)
                if element.count() == 0:
                    print(f"    [WARN] iframe 内元素未找到，回退主页面")
                    page.locator(verified_locator).fill(value, timeout=5000)
                else:
                    element.first.fill(value, timeout=5000)
                    print(f"    [TRACE-P6]   iframe fill: frame={frame_selector}")
                return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

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
                        " || e.closest('.ant-select') !== null"
                    )
                    if is_readonly:
                        # readonly el-select 触发器 — 验证 locator 存在即可，跳过 fill
                        return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source
            except Exception:
                pass  # 检测失败则走正常 fill 流程

            page.locator(verified_locator).fill(value, timeout=5000)
            return verified_locator, matched_prefix or current_ct, False, is_best_guess, hit_source

        elif keyword.startswith('frame_'):
            # iframe 操作：使用 frame_locator API（MVP 实现）
            frame_ref = params.get('frame', '') if isinstance(params, dict) else ''
            if not frame_ref:
                print(f"    [ERROR] {keyword} 缺少 frame 参数: '{desc}'")
                return None, matched_prefix or current_ct, False, False, hit_source

            # 解析 frame 参数
            frame_selector = resolve_var(frame_ref, data_dict)
            if '${' in frame_selector:
                frame_selector = resolve_locator({'locator': frame_selector}, pages_dict)
            # 剥离前缀供 Playwright API 使用（兼容 xpath= 和 css=）
            if frame_selector.startswith('xpath='):
                frame_selector = frame_selector[6:]
            elif frame_selector.startswith('css='):
                frame_selector = frame_selector[4:]

            print(f"    [TRACE-P6] iframe 快速通道: frame='{frame_selector}', locator='{verified_locator[:80]}'")

            # ── 策略 1: 用指定选择器尝试 ──
            _frame_found = False
            try:
                page.wait_for_selector(frame_selector, state='attached', timeout=10000)
                page.wait_for_timeout(1000)
                _frame_found = True
            except Exception:
                print(f"    [TRACE-P6] iframe 选择器 '{frame_selector}' 未找到，回退扫描所有 iframe")

            if _frame_found:
                try:
                    frame_loc = page.frame_locator(frame_selector)
                    element_loc = frame_loc.locator(verified_locator)

                    count = 0
                    for retry in range(5):
                        count = element_loc.count()
                        if count > 0:
                            break
                        print(f"    [TRACE-P6] iframe element count=0, retry {retry+1}/5...")
                        page.wait_for_timeout(1000)

                    print(f"    [TRACE-P6] iframe element count={count}")
                    if count > 0:
                        return _iframe_execute_action(keyword, element_loc, verified_locator,
                                                      page, params, data_dict, desc)
                except Exception as e:
                    print(f"    [TRACE-P6] 指定 iframe 操作失败: {str(e)[:80]}，回退扫描")

            # ── 策略 2: 回退 — 扫描所有 iframe 查找目标元素 ──
            _iframe_result = _try_find_in_iframes(page, verified_locator)
            if _iframe_result and _iframe_result.get('count', 0) > 0:
                _fb_selector = _iframe_result['frame_selector']
                print(f"    [TRACE-P6] iframe 回退成功: selector='{_fb_selector}'")
                frame_loc = page.frame_locator(_fb_selector)
                element_loc = frame_loc.locator(verified_locator)
                return _iframe_execute_action(keyword, element_loc, verified_locator,
                                              page, params, data_dict, desc)

            print(f"    [ERROR] iframe 内未找到元素: '{desc}'")
            print(f"    [ERROR]   frame='{frame_selector}', locator='{verified_locator[:100]}'")
            return None, matched_prefix or current_ct, False, False, hit_source

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

