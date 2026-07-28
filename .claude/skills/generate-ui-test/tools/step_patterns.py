#!/usr/bin/env python3
"""step_patterns.py — 共享步骤模式定义（单一真相源）

被 _case_generator.py（StepParser）和 validate_excel.py（L2.5 验证）共同导入。
新增/修改步骤匹配模式只需改此一处，保证两个工具的模式定义永不脱节。

用法:
    from step_patterns import parse_step, validate_step, STEP_PATTERNS, Q

    result = parse_step('在"项目名称"下拉框中选择"XX"')
    # {'type': 'el_select', 'args': ('项目名称', 'XX'), 'raw': '...'}

    is_ok, match_type = validate_step('点击"确定"按钮')
    # (True, 'click_btn')
"""
import re

# ============================================================================
# 通用引号字符类
# ============================================================================
# 覆盖 Excel 中可能出现的所有引号类型：
#   “  U+0022  ASCII 双引号（最常见）
#   “  U+201C  中文左双引号
#   “  U+201D  中文右双引号
#   “  U+0022  ASCII 双引号（与首位重复，正则字符类自动去重，保留不影响）
#   '  U+0027  ASCII 单引号
Q = r'["“”“\']'  # U+0022 U+201C U+201D U+0022(dup) U+0027

# ============================================================================
# 步骤模式列表（按优先级排序，越靠前优先级越高）
# ============================================================================
# 每条: (compiled_regex, action_type, group_names)
# group_names: 捕获组的语义名称元组，用于文档和调试

_RAW_PATTERNS = [
    # ── 数量断言（必须在 l3_call 之前，防止 "至少有3个任务" 等被 l3_call 拦截）──
    # Pattern A: "断言：" 前缀 + 至少有N条/个XX
    (r'断言[：:]?\s*至少.{0,2}有?\s*(\S+?)\s*(?:条|个|笔)\s*(.*)',
     'assert_count', ('min_count_raw', 'section')),
    # Pattern B: 无前缀 + 至少有N条/个XX（R34 拆分后的独立步骤）
    (r'^至少.{0,2}有?\s*(\S+?)\s*(?:条|个|笔)\s*(.*)',
     'assert_count', ('min_count_raw', 'section')),
    # Pattern C: XX数量/条数 + 比较运算符 + N
    (r'(?:断言[：:]?\s*)?(.+?)\s*(?:数量|条数|记录数)\s*(?:大于等于|≥|>=|不少于)\s*(\S+)',
     'assert_count', ('section', 'min_count_raw')),
    # Pattern D: 有N条以上XX
    (r'(?:断言[：:]?\s*)?有\s*(\S+?)\s*(?:条|个|笔)\s*以上\s*(.*)',
     'assert_count', ('min_count_raw', 'section')),

    # ── 表格勾选操作（必须在 l3_call 之前，防止被拦截）──
    # 勾选第N个/条XX（通用表格行复选框）
    (r'勾选第([一二三四五六七八九十\d]+)[个条]?(.*)',
     'check_first', ('row_num', 'item_desc')),

    # ── 关闭按钮（通用，必须在 l3_call 之前，"点击关闭按钮" 6 字符会被 l3_call 拦截）──
    (r'点击关闭按钮',
     'close_btn', ()),

    # ── L3 中文关键字直调（最高优先级，必须在所有其他模式之前）──
    # Excel 中直接使用关键字名称 + 括号说明，如 "Tab页签搜索(点击任务提醒tab)"
    # 关键字名限制 2-8 字符（\w 含 Unicode word chars + digits，实际仅中英文+数字+下划线）
    # 无排除词：如果匹配到但 workflow 未找到，generate_step() 回退让后续 pattern 重新匹配
    # 匹配后需在 generate_step 中校验关键字是否在两层 workflow 定义中
    (r'^([一-鿿A-Za-z_]\w{1,7})\s*(?:\((.+?)\))?\s*$',
     'l3_call', ('keyword_name', 'raw_params')),

    # ── conditional_click 系列（必须在 click 系列之前，防止 search() 子串匹配）──
    # 条件 + "XX"按钮（最具体）
    (rf'如果{Q}(.+?){Q}.*?中.*?(?:数量|条数).*?(?:大于|>)\s*0.*?则点击{Q}(.+?){Q}\s*按钮',
     'conditional_click_btn', ('tab_or_section', 'label')),
    # 条件 + "XX"tab
    (rf'如果{Q}(.+?){Q}.*?中.*?(?:数量|条数).*?(?:大于|>)\s*0.*?则点击{Q}(.+?){Q}\s*tab',
     'conditional_click_tab', ('tab_or_section', 'tab_label')),
    # 条件 + 第N条记录
    (rf'如果{Q}(.+?){Q}.*?中.*?(?:数量|条数).*?(?:大于|>)\s*0.*?则点击第.+?条',
     'conditional_click_row', ('tab_or_section',)),
    # 条件 + 通用点击（兜底，最低优先级）
    (rf'如果{Q}(.+?){Q}.*?中.*?(?:数量|条数).*?(?:大于|>)\s*0.*?则点击',
     'conditional_click', ('tab_or_section',)),

    # ── 随机名称系列（在 fill/el-select 之前，匹配无引号的随机名称表达式）──
    # 在"字段"输入框/文本框中输入随机名称(前缀)  — 支持中英文括号
    (rf'在{Q}(.+?){Q}\s*(?:输入框|文本框|框)中?\s*(?:输入|填入)(随机名称[(（].+?[)）])',
     'fill', ('field', 'value')),
    # 在"字段"第N个下拉框中选择随机名称(前缀)
    (rf'在{Q}(.+?){Q}\s*第([一二三四五六七八九十\d]+)个?下拉框中?选择(随机名称[(（].+?[)）]).*等待',
     'el_select', ('field', 'nth', 'value')),
    (rf'在{Q}(.+?){Q}\s*第([一二三四五六七八九十\d]+)个?下拉框中?选择(随机名称[(（].+?[)）])',
     'el_select', ('field', 'nth', 'value')),
    # 在"字段"下拉框中选择随机名称(前缀)
    (rf'在{Q}(.+?){Q}\s*下拉框中?选择(随机名称[(（].+?[)）]).*等待',
     'el_select', ('field', 'value')),
    (rf'在{Q}(.+?){Q}\s*下拉框中?选择(随机名称[(（].+?[)）])',
     'el_select', ('field', 'value')),

    # ── el-select 带序号系列（4 个，优先级高于无序号版本）──
    # 在"field"第N个下拉框中选择"value"
    (rf'在{Q}(.+?){Q}\s*第([一二三四五六七八九十\d]+)个?下拉框中选择{Q}(.+?){Q}.*等待',
     'el_select', ('field', 'nth', 'value')),
    (rf'在{Q}(.+?){Q}\s*第([一二三四五六七八九十\d]+)个?下拉框中选择{Q}(.+?){Q}',
     'el_select', ('field', 'nth', 'value')),
    (rf'在{Q}(.+?){Q}\s*第([一二三四五六七八九十\d]+)个?下拉框选择{Q}(.+?){Q}.*等待',
     'el_select', ('field', 'nth', 'value')),
    (rf'在{Q}(.+?){Q}\s*第([一二三四五六七八九十\d]+)个?下拉框选择{Q}(.+?){Q}',
     'el_select', ('field', 'nth', 'value')),

    # ── el-select 系列（3 个，无序号时 nth 默认为 1）──
    (rf'在{Q}(.+?){Q}\s*下拉框中选择{Q}(.+?){Q}.*等待',
     'el_select', ('field', 'value')),
    (rf'在{Q}(.+?){Q}\s*下拉框中选择{Q}(.+?){Q}',
     'el_select', ('field', 'value')),
    (rf'在{Q}(.+?){Q}\s*下拉框选择{Q}(.+?){Q}',
     'el_select', ('field', 'value')),

    # ── el-cascader 系列（2 个）──
    # Pattern 1: 在"字段"级联选择框中依次选择"值1"、"值2"（标签在前，值在后）
    # 修复: 加 级联选择框 变体 + 加 依次 可选前缀 + 捕获所有值原始字符串
    (rf'在{Q}(.+?){Q}\s*(?:级联选择器|级联选择框|级联框|级联)中(?:依次)?(?:选择|勾选)(.*)',
     'el_cascader', ('field', 'values_raw')),
    # Pattern 2: 级联选择器..."字段"..."值"（备用，标签在级联关键词之后）
    # 修复: 加 ^在 负向前瞻，防止与 Pattern 1 冲突（当文本以 在"..."级联... 开头时不匹配）
    (rf'^(?!在{Q})(?:级联选择器?|级联选择框|级联框|级联).+?{Q}(.+?){Q}.+?{Q}(.+?){Q}',
     'el_cascader', ('field', 'value')),

    # ── option-card 系列（1 个）──
    # 在"字段"选项卡中选择/点击/勾选"值"
    (rf'在{Q}(.+?){Q}\s*选项卡中?(?:选择|点击|勾选){Q}(.+?){Q}',
     'option_card', ('field', 'value')),

    # ── fill 系列（6 个，优先级：textarea > 有类型关键词 > 无类型关键词 > 变体）──
    # Issue 1b: "文本框" 明确为 textarea（优先级高于通用 fill）
    (rf'在{Q}(.+?){Q}\s*文本框中?[，,]?\s*输入{Q}(.+?){Q}',
     'textarea', ('field', 'value')),
    # "输入框中输入" 或 "输入框，输入"
    (rf'在{Q}(.+?){Q}\s*输入框中?[，,]?\s*输入{Q}(.+?){Q}',
     'fill', ('field', 'value')),
    # "框中输入"
    (rf'在{Q}(.+?){Q}框中输入{Q}(.+?){Q}',
     'fill', ('field', 'value')),
    # "框输入"（无"中"）
    (rf'在{Q}(.+?){Q}框输入{Q}(.+?){Q}',
     'fill', ('field', 'value')),
    # "里输入" 变体
    (rf'在{Q}(.+?){Q}里输入{Q}(.+?){Q}',
     'fill', ('field', 'value')),
    # "中输入"（无类型关键词）
    (rf'在{Q}(.+?){Q}中输入{Q}(.+?){Q}',
     'fill', ('field', 'value')),

    # ── click 系列（优先级：特异性从高到低）──
    # F-R3: 复合步骤必须在通用 click_btn 之前
    # 点击第N条(查询)记录的"更多"按钮，点击"XX"（复合步骤：展开+操作）
    (rf'点击第[一二三四五六七八九十\d]+条(?:查询)?记录的{Q}更多{Q}按钮[，,]\s*点击{Q}(.+?){Q}',
     'click_more_then_click', ('action',)),
    # 点击"更多"...选择/点击XX（无行号前缀的简化版复合步骤）
    (rf'点击{Q}更多{Q}.*?(?:选择|点击)\s*{Q}(.+?){Q}',
     'click_more_then', ('action',)),
    # 点击第N条(查询)记录的"XX"按钮（更具体，优先于 click_detail_link）
    (rf'点击第[一二三四五六七八九十\d]+条(?:查询)?记录的{Q}(.+?){Q}按钮',
     'click_table_row_btn', ('label',)),
    # 点击第N条(查询)记录的XX标题"TEXT"
    (rf'点击第[一二三四五六七八九十\d]+条(?:查询)?记录的\S+?{Q}(.+?){Q}',
     'click_detail_link', ('text',)),
    # 点击第N条(查询)记录的XX（无引号文本）
    (rf'点击第[一二三四五六七八九十\d]+条(?:查询)?记录的(\S+)',
     'click_detail_link', ('field',)),
    # 点击XX中的第一个"YY"按钮
    (rf'点击.+?第一个{Q}(.+?){Q}按钮',
     'click_first_in_list', ('label',)),
    # 点击"XX"可以跳转
    (rf'(?:点击|单击|点){Q}(.+?){Q}可以跳转',
     'click_navigate', ('label',)),
    # 点击"XX" tab（必须在通用 click 之前）
    (rf'(?:点击|单击|点){Q}(.+?){Q}\s*tab',
     'click_tab', ('label',)),
    # 点击XX部分/区域
    (r'点击(.+?)(?:部分|区域)',
     'click_section', ('section',)),
    # 如果有数据则点击"XX"区域（P-D2: 合并到 click_section）
    (rf'如果有数据则点击{Q}(.+?){Q}\s*区域',
     'click_section', ('section',)),
    # 点击"XX"安全组关闭按钮（close_btn 专用，必须在 click_btn 之前）
    (rf'点击{Q}(.+?){Q}\S*?关闭按钮',
     'close_btn', ('label',)),
    # 点击/单击/点"XX"按钮（通用）
    (rf'(?:点击|单击|点){Q}(.+?){Q}\s*按钮',
     'click_btn', ('label',)),
    # 点击/单击/点"XX"（行尾）
    (rf'(?:点击|单击|点){Q}(.+?){Q}$',
     'click_btn', ('label',)),
    # 点击"XX"（通用，最低优先级）
    (rf'点击{Q}(.+?){Q}',
     'click', ('label',)),

    # ── 条件/确认 ──
    # 弹窗确认"XX" 或 确认"XX"
    (rf'(?:弹窗)?确认{Q}(.+?){Q}',
     'confirm_dialog', ('label',)),
    # 确认删除...点击"XX"
    (rf'确认删除.*?点击{Q}(.+?){Q}',
     'confirm_delete', ('label',)),

    # ── 日期选择 ──
    # 在"XX"时间选择框中选择"YY"
    (rf'在{Q}(.+?){Q}\s*时间选择框中选择{Q}(.+?){Q}',
     'date_select', ('field', 'value')),
    # 在"XX"时间选择框选择"YY"（无"中"）
    (rf'在{Q}(.+?){Q}\s*时间选择框选择{Q}(.+?){Q}',
     'date_select', ('field', 'value')),
    # 在XX弹窗中，开始时间选择"今天"
    (rf'在(.+?)弹窗中.*?时间选择{Q}(.+?){Q}',
     'dialog_date_select', ('context', 'value')),

    # ── 断言（assert_row 必须在 assert 之前，防止被贪婪捕获拦截）──
    # 第一条记录/第一行...的XX"YY" 或 XX为"YY"（行级断言，"为"可选）
    (rf'(?:断言[：:]?|查看|检查|确认).*?(?:第一条|第一行).*?{Q}(.+?){Q}',
     'assert_row', ('value',)),
    # 断言：XX / 文本断言：XX（通用兜底，必须在 assert_row 之后）
    (r'断言[：:](.+)',
     'assert', ('desc',)),
    (r'文本断言[：:](.+)',
     'assert', ('desc',)),
    # 检查XX与YY一致
    (r'检查(.+?)与(.+?)一致',
     'check_assert', ('actual', 'expected')),

    # ── 导航/等待 ──
    # 访问 URL
    (r'访问\s*(https?://\S+)',
     'open_url', ('url',)),
    # 等待XX加载完成/出现/展示
    (r'等待(.+?)(?:加载完成|出现|展示)',
     'wait', ('desc',)),
    # 等待进入/弹出/出现XX
    (r'等待(?:进入|弹出|出现)(.+)',
     'wait_element', ('desc',)),
    # 等待Ns
    (r'等待(\d+)s',
     'wait_time', ('seconds',)),

    # ── 表格操作 ──
    # 选择第一条...，点击"XX"
    (rf'选择第一条.*?[，,]\s*点击{Q}(.+?){Q}',
     'click_table_action', ('label',)),

    # ── 其他 ──
    (r'返回', 'go_back', ()),
    (r'刷新', 'refresh', ()),
    (r'请完成测试结论', 'skip', ()),
]

# 编译所有模式
STEP_PATTERNS = [
    (re.compile(raw), action_type, group_names)
    for raw, action_type, group_names in _RAW_PATTERNS
]


# ============================================================================
# 公共 API
# ============================================================================

def parse_step(step_text):
    """解析单个步骤文本，返回结构化字典

    Args:
        step_text: 步骤描述文本（如 '点击"确定"按钮'）

    Returns:
        dict: {'type': str, 'args': tuple, 'raw': str}
        - type: 匹配到的动作类型（如 'click_btn'），未匹配时为 'unknown'
        - args: 正则捕获组元组
        - raw: 原始步骤文本
    """
    step_text = step_text.strip()
    for pattern, action_type, _group_names in STEP_PATTERNS:
        m = pattern.search(step_text)
        if m:
            return {
                'type': action_type,
                'args': m.groups(),
                'raw': step_text,
            }
    return {
        'type': 'unknown',
        'args': (step_text,),
        'raw': step_text,
    }


def validate_step(step_text):
    """验证步骤是否可被 StepParser 解析

    Args:
        step_text: 步骤描述文本

    Returns:
        tuple: (is_parseable: bool, match_type: str)
    """
    result = parse_step(step_text)
    return result['type'] != 'unknown', result['type']


def list_pattern_types():
    """列出所有已定义的模式类型及其匹配正则（用于调试和文档生成）

    Returns:
        list of dict: [{'type': str, 'pattern': str, 'groups': tuple}, ...]
    """
    return [
        {
            'type': action_type,
            'pattern': pattern.pattern,
            'groups': group_names,
        }
        for pattern, action_type, group_names in STEP_PATTERNS
    ]


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    # 快速自测
    test_cases = [
        ('在"项目名称"下拉框中选择"XX"，等待1s', 'el_select'),
        ('在"项目名称"下拉框选择"XX"', 'el_select'),
        ('在"工单标题"输入框输入"肖洋"', 'fill'),
        ('在"处理意见"输入框，输入"同意"', 'fill'),
        ('在"项目名称"中输入"测试"', 'fill'),
        ('在"项目名称"里输入"测试"', 'fill'),
        ('在"姓名"框中输入"张三"', 'fill'),
        ('在"文件夹名称"框输入"测试1"', 'fill'),
        ('点击"确定"按钮', 'click_btn'),
        ('点击"确定"', 'click_btn'),
        ('单击"确定"按钮', 'click_btn'),
        ('点"确定"按钮', 'click_btn'),
        ('点击第一条记录的工单标题"肖洋发起的制品出库"', 'click_detail_link'),
        ('点击第一条查询记录的"团队成员"按钮', 'click_table_row_btn'),
        ('如果"任务提醒"tab中消息数量大于0，则点击"查看"按钮', 'conditional_click_btn'),
        ('如果"问题列表"中记录数量大于0，则点击第一条', 'conditional_click_row'),
        ('如果"消息"中条数大于0，则点击"任务提醒"tab', 'conditional_click_tab'),
        ('如果"任务提醒"tab中消息的数量大于0，则点击下方的具体消息', 'conditional_click'),
        ('检查消息详情页面显示的标题，与消息列表中的标题一致', 'check_assert'),
        ('等待进入工单详情页面', 'wait_element'),
        ('等待弹出"产品清单确认"页面', 'wait_element'),
        ('点击"任务提醒"tab', 'click_tab'),
        ('弹窗确认"请确认是否创建新的流程？"', 'confirm_dialog'),
        ('请完成测试结论的总结并结束任务', 'skip'),
        ('Tab页签搜索(点击任务提醒tab查看消息)', 'l3_call'),
        ('列表查询', 'l3_call'),
        ('等待加载完成', 'l3_call'),          # l3_call 无排除词：匹配后回退重解析处理
        ('返回', 'l3_call'),                  # l3_call 无排除词：匹配后回退重解析处理
        ('刷新', 'l3_call'),                  # l3_call 无排除词：匹配后回退重解析处理
        ('检查站内信显示(任务提醒)', 'l3_call'),  # l3_call + 参数
        ('列表查询(项目名称, 测试项目)', 'l3_call'),  # l3_call + 多参数
        # el-cascader 级联选择器
        ('在"项目类型"级联选择框中依次选择"小站"、"EIS"', 'el_cascader'),
        ('在"项目类型"级联选择器中选择"小站"', 'el_cascader'),
        ('在"区域"级联框中勾选"北京"', 'el_cascader'),
    ]

    passed = 0
    failed = 0
    for text, expected in test_cases:
        result = parse_step(text)
        status = '✓' if result['type'] == expected else '✗'
        if result['type'] == expected:
            passed += 1
        else:
            failed += 1
            print(f'  {status} "{text}" → {result["type"]} (expected {expected})')

    print(f'\nSelf-test: {passed}/{len(test_cases)} passed, {failed} failed')
