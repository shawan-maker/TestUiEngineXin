"""共享关键字常量（v1.1 P1-3）

统一 ENGINE_KEYWORDS 定义，供多个工具共享使用：
- validators/validate_08_scripts.py
- tools/_case_generator.py
- tools/auto_fix_checkpoint_a.py（已删除 R4.50，但保留供未来使用）

使用方法：
    from tools._shared_keywords import ENGINE_KEYWORDS, KEYWORD_MISTAKES
"""

# 引擎内置关键字（UIEngine 提供）
# 包含英文关键字和中文别名
ENGINE_KEYWORDS = {
    # 页面操作 (15)
    'open_url', '打开页面', 'refresh', '刷新页面',
    'go_back', '返回上一页', 'go_forward', '前进下一页',
    'scroll_to_height', '滚动到高度', 'scroll_to_element', '滚动到元素',
    'execute_script', '执行脚本', 'save_page_img', '保存截图',
    'download_file', '下载文件', 'accept_dialog', '接受弹窗',
    'dismiss_dialog', '关闭弹窗', 'get_page_title', '获取页面标题',
    'get_page_url', '获取页面URL', 'set_viewport_size', '设置窗口大小',
    'set_cookie', '设置Cookie',
    # 元素操作 (18×2)
    'click_element', '点击元素', 'fill_value', '输入值',
    'type_text', '输入文本', 'hover', '悬停',
    'focus_element', '聚焦元素', 'double_click', '双击',
    'long_click', '长按', 'right_click', '右键点击',
    'drag_and_drop', '拖拽', 'check', '勾选',
    'uncheck', '取消勾选', 'set_checked', '设置勾选',
    'clear', '清空输入框', 'select_option', '选择选项',
    'select_multiple_options', '多选下拉',
    'click_select_option', '点击选择选项',
    'upload_file', '上传文件', 'highlight_element', '高亮元素',
    # 元素查询 (9×2)
    'get_text', '获取文本', 'get_attribute', '获取属性',
    'get_input_value', '获取输入值', 'get_element_count', '获取元素数量',
    'is_visible', '是否可见', 'is_hidden', '是否隐藏',
    'is_enabled', '是否可用', 'is_disabled', '是否不可用',
    'is_checked', '是否选中',
    # iframe (10×2)
    'frame_fill_value', '框架输入', 'frame_click_element', '框架点击',
    'frame_hover', '框架悬停', 'frame_focus_element', '框架聚焦',
    'frame_select_option', '框架选择', 'frame_type_value', '框架输入文本',
    'frame_long_click_element', '框架长按', 'frame_drag_and_drop', '框架拖拽',
    'switch_to_frame', '切换iframe', 'switch_to_main_frame', '切回主页面',
    # iframe 断言 (3×2)
    'frame_except_to_be_visible', '框架断言可见',
    'frame_except_to_be_hidden', '框架断言隐藏',
    'frame_except_to_have_text', '框架断言文本',
    # 断言 (13×2)
    'except_to_have_text', '断言有文本',
    'except_to_have_value', '断言有值',
    'except_to_have_attribute', '断言有属性',
    'except_to_be_visible', '断言可见',
    'except_to_be_hidden', '断言隐藏',
    'except_to_be_enabled', '断言可用',
    'except_to_be_disabled', '断言不可用',
    'except_to_be_checked', '断言选中',
    'except_to_be_empty', '断言为空',
    'except_to_be_editable', '断言可编辑',
    'except_to_be_focused', '断言聚焦',
    'assert_page_title', '断言标题',
    'assert_page_url', '断言URL',
    # 等待 (7×2)
    'wait_for_time', '强制等待', 'wait_for_element', '等待元素',
    'wait_for_element_hidden', '等待元素消失',
    'wait_for_load', '等待加载', 'wait_for_network', '等待网络',
    'wait_for_url', '等待URL', 'set_default_timeout', '设置超时',
    # 鼠标/键盘 (6×2)
    'mouse_click', '鼠标点击', 'move_mouse', '移动鼠标',
    'mouse_down', '鼠标按下', 'mouse_up', '鼠标抬起',
    'press_key', '按键', 'press_type', '键盘输入',
    # 浏览器控制
    'open_browser', '打开浏览器',
    # 认证注入 (3, 来自 auth_keywords.py)
    'inject_cookies', 'inject_token_header', 'inject_local_storage',
    # 流程控制 (8×2, 来自 flow_keywords.py)
    'set_variable', '设置变量',
    'set_variable_from_element', '从元素设置变量',
    'if_element_visible', '元素可见则执行',
    'if_variable', '变量满足条件则执行',
    'for_each', '遍历元素集合',
    'retry_until', '重试直到成功',
    'goto_step', '跳转步骤',
    'log', '日志输出',
    # 额外关键字（_case_generator.py 使用）
    'set_random_variable', 'except_element_count',
}

# 常见关键字错误映射（用于自动修复建议）
KEYWORD_MISTAKES = {
    'assert_text': 'except_to_have_text',
    'assert_visible': 'except_to_be_visible',
    'assert_not_visible': 'except_to_be_hidden',
    'assert_contains': 'except_to_have_text',
    'verify_text': 'except_to_have_text',
    'check_element': 'except_to_be_visible',
    'click_text': 'click_element',
}

# 仅英文关键字（不含中文别名，用于某些场景的快速查找）
ENGINE_KEYWORDS_EN = {kw for kw in ENGINE_KEYWORDS if not any('一' <= c <= '鿿' for c in kw)}
