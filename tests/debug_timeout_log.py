"""调试脚本：追踪 tolerant timeout 的日志级别和异常处理

目的：确认 wait_for_network 超时时，日志级别和异常传播路径
"""
import sys
sys.path.insert(0, r'D:\PyProject\TestUiEngineXin')

from UIEngine.caseLog import CaseLogHandler
from UIEngine.basecase import BaseCase
from unittest.mock import Mock

# 创建日志处理器
log = CaseLogHandler(name='debug_timeout_test', console=True)

# 创建 mock config
config = {
    'target_url': 'http://test.com',
    'browser_type': 'chromium'
}

# 创建 BaseCase（不会真正启动浏览器）
class MockPage:
    def wait_for_load_state(self, state, timeout):
        if state == 'networkidle' and timeout == 3000:
            raise Exception(f'Timeout {timeout}ms exceeded.')
        return None

# 手动设置 mock page
base_case = BaseCase.__new__(BaseCase)
base_case.config = config
base_case.log = log
base_case.page = MockPage()
base_case.variable_resolver = Mock()
base_case.variable_resolver.resolve = lambda x: x
base_case.tree_builder = None

print("=" * 80)
print("测试：调用 tolerant 版本的 wait_for_network")
print("=" * 80)

# 模拟 module_keywords.py 中的 tolerant 调用
try:
    # 这是 module_keywords.py 第 29-37 行的逻辑
    try:
        base_case.perform({
            'desc': '等待网络空闲（SPA兜底，短超时容错）',
            'keyword': 'wait_for_network',
            'params': {'timeout': 3000}
        })
    except Exception as _e:
        base_case.log.debug_log(f'[L3] tolerant skip: 等待网络空闲（SPA兜底，短超时容错） — {_e}')
except Exception as e:
    print(f"外层捕获异常: {e}")

print("\n" + "=" * 80)
print("日志数据分析")
print("=" * 80)

for level, msg in log.log_data:
    print(f"[{level:8s}] {msg}")

print("\n" + "=" * 80)
print("结论")
print("=" * 80)
print(f"总日志条数: {len(log.log_data)}")
error_logs = [m for lvl, m in log.log_data if lvl == 'ERROR']
debug_logs = [m for lvl, m in log.log_data if lvl == 'DEBUG']
print(f"ERROR 级别: {len(error_logs)} 条")
print(f"DEBUG 级别: {len(debug_logs)} 条")

if error_logs:
    print("\nERROR 日志内容:")
    for msg in error_logs:
        print(f"  - {msg}")
