"""模块复合关键字模板（L3 层）

由 skill Phase 3.5 编译生成，输出至 {project}/lib/module_keywords.py。

编译输入：{project}/_knowledge/{module}.yaml 中的 workflows 定义
编译输出：本模板渲染为可执行的 Python 模块

变量说明（模板渲染时替换）：
  {{project_name}}  — 项目名称
  {{timestamp}}     — 生成时间
  {{workflows}}     — 从 _knowledge/ 解析的工作流列表
"""

# 以下为模板伪代码，实际由 skill 在 Phase 3.5 渲染：

TEMPLATE = '''
"""{{project_name}} 模块复合关键字（L3）
由 skill 从 _knowledge/ 编译生成 — ⚠️ 请勿手动修改
生成时间：{{timestamp}}

修改请编辑 _knowledge/*.yaml 后重新运行：
  python .claude/skills/generate-ui-test/tools/compile_module_keywords.py {project}
"""
from UIEngine.core.keyword_manager import KeyWordManager
from UIEngine.basecase import BaseCase


{% for workflow in workflows %}
def {{ workflow.name }}(self, {{ workflow.params }}):
    """{{ workflow.description }}

    来源: _knowledge/{{ workflow.source_file }}
    参数:
        {% for p in workflow.param_list %}
        {{ p.name }} — {{ p.description }}
        {% endfor %}
    """
    {% for step in workflow.compiled_steps %}
    # Step {{ step.index }}: {{ step.desc }}
    {{ step.python_code }}
    {% endfor %}

{% endfor %}

def register_module_keywords():
    """注册所有模块复合关键字"""
    keywords = [
        {% for workflow in workflows %}
        ({{ workflow.name }}, '{{ workflow.name }}', '{{ workflow.chinese_name }}'),
        {% endfor %}
    ]
    for func, en, zh in keywords:
        setattr(BaseCase, func.__name__, func)
        KeyWordManager.maps[en] = func
        KeyWordManager.maps[zh] = func
'''

# ========================================================================
# 步骤类型到 Python 代码的编译规则
# ========================================================================

COMPILE_RULES = {
    "click_element": (
        "self.perform({{\n"
        "    'desc': '{desc}',\n"
        "    'keyword': 'click_element',\n"
        "    'params': {{'locator': '{locator}'}}\n"
        "}})"
    ),
    "fill_value": (
        "self.perform({{\n"
        "    'desc': '{desc}',\n"
        "    'keyword': 'fill_value',\n"
        "    'params': {{'locator': '{locator}', 'value': {value}}}\n"
        "}})"
    ),
    "wait_for_time": (
        "self.perform({{\n"
        "    'desc': '{desc}',\n"
        "    'keyword': 'wait_for_time',\n"
        "    'params': {{'timeout': {timeout}}}\n"
        "}})"
    ),
    "get_element_count": (
        "# 获取元素数量并存入变量\n"
        "_count = self.page.locator('{locator}').count()\n"
        "self.config.setdefault('runtime_variables', {{}})['{target_var}'] = str(_count)"
    ),
    "get_text": (
        "# 获取元素文本并存入变量\n"
        "_text = self.page.locator('{locator}').first.text_content(timeout=3000)\n"
        "self.config.setdefault('runtime_variables', {{}})['{target_var}'] = _text"
    ),
    "if_variable": (
        "# 条件判断: {name} {operator} {compare_value}\n"
        "if {condition_expr}:\n"
        "    {then_code}\n"
        "{else_clause}"
    ),
    "except_to_have_text": (
        "self.perform({{\n"
        "    'desc': '{desc}',\n"
        "    'keyword': 'except_to_have_text',\n"
        "    'params': {{'locator': '{locator}', 'expect_results': {expect}}}\n"
        "}})"
    ),
    "log": (
        "# 日志输出\n"
        "self.log.debug_log('[L3] {message}')"
    ),
}
