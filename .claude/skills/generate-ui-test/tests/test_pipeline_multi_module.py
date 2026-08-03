#!/usr/bin/env python3
"""pipeline.py 多模块执行逻辑单元测试

覆盖 _run_tool 和 _execute_multi_module 的新增分支：
1. returncode==2 → FAILED (auth 阻断)
2. tolerate_tool_failure → 降级为 warning
3. fatal_on_auth_failure → 全局阻断
4. 无模块边界场景
5. _cascade_skip 统一 SKIPPED（移除 gate 升级）
"""
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess

# 确保 tools 目录在路径中
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from pipeline_models import PhaseStatus, PhaseResult
from pipeline_registry import PHASE_DEFINITIONS

# 导入 PipelineRunner（动态加载，避免路径依赖）
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "pipeline",
    Path(__file__).parent.parent / "tools" / "pipeline.py"
)
pipeline_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline_module)
PipelineExecutor = pipeline_module.PipelineExecutor


# ============================================================================
# 测试辅助函数
# ============================================================================

def create_mock_executor(phase_id="phase_6_verify", modules=None):
    """创建带 mock context 的 PipelineExecutor"""
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.project_dir = "/tmp/test_project"
    executor.results = {}
    executor.registry = PHASE_DEFINITIONS

    # Mock context
    executor.context = Mock()
    executor.context.get_modules.return_value = modules if modules is not None else [
        {"slug": "module1", "cn_name": "模块1", "urls": []}
    ]
    executor.context.module_urls_path = None
    executor.context.discovery_path = None
    executor.context.module_map_str = ""

    # Mock 辅助方法
    executor._save_tool_log = Mock()
    executor._tool_log_path = Mock(return_value="/tmp/test.log")

    return executor


def assert_phase_result(result, status, error_keywords=None, warning_keywords=None):
    """断言 PhaseResult 的状态和关键字"""
    assert result.status == status, f"Expected {status}, got {result.status}"

    if error_keywords:
        for kw in error_keywords:
            assert any(kw in err for err in result.errors), \
                f"Expected '{kw}' in errors, got: {result.errors}"

    if warning_keywords:
        for kw in warning_keywords:
            assert any(kw in warn for warn in result.warnings), \
                f"Expected '{kw}' in warnings, got: {result.warnings}"


# ============================================================================
# Test 1: _run_tool — returncode==2 识别为 auth 失败
# ============================================================================

def test_run_tool_exit_code_2():
    """exit(2) 应返回 FAILED + [AUTH_REQUIRED] 错误"""
    executor = create_mock_executor()

    # Mock subprocess.Popen 返回 exit code 2
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = Mock()
        mock_proc.stdout = iter(["[AUTH_REQUIRED] Cookie 已失效\n"])
        mock_proc.returncode = 2
        mock_proc.wait = Mock()
        mock_popen.return_value = mock_proc

        result = executor._run_tool("phase_6_verify", "verification/verify_orchestrator.py", [])

        assert_phase_result(
            result,
            PhaseStatus.FAILED,
            error_keywords=["[AUTH_REQUIRED]", "Cookie"]
        )
        print("✓ Test 1: returncode==2 → FAILED + [AUTH_REQUIRED]")


# ============================================================================
# Test 2: _run_tool — returncode==0 正常通过
# ============================================================================

def test_run_tool_exit_code_0():
    """exit(0) 应返回 PASSED"""
    executor = create_mock_executor()

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = Mock()
        mock_proc.stdout = iter(["验证完成\n"])
        mock_proc.returncode = 0
        mock_proc.wait = Mock()
        mock_popen.return_value = mock_proc

        result = executor._run_tool("phase_6_verify", "verification/verify_orchestrator.py", [])

        assert_phase_result(result, PhaseStatus.PASSED)
        print("✓ Test 2: returncode==0 → PASSED")


# ============================================================================
# Test 3: _run_tool — returncode==1 工具崩溃
# ============================================================================

def test_run_tool_exit_code_1():
    """exit(1) 应返回 FAILED + 错误预览"""
    executor = create_mock_executor()

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = Mock()
        mock_proc.stdout = iter([
            "处理中...\n",
            "Error: playwright not installed\n"
        ])
        mock_proc.returncode = 1
        mock_proc.wait = Mock()
        mock_popen.return_value = mock_proc

        result = executor._run_tool("phase_6_verify", "verification/verify_orchestrator.py", [])

        assert_phase_result(
            result,
            PhaseStatus.FAILED,
            error_keywords=["工具执行失败", "playwright not installed"]
        )
        print("✓ Test 3: returncode==1 → FAILED + error preview")


# ============================================================================
# Test 4: _execute_multi_module — tolerate_tool_failure 降级
# ============================================================================

def test_multi_module_tolerate_tool_failure():
    """Phase 6 (有 tolerate_tool_failure) 工具失败应降级为 warning"""
    executor = create_mock_executor("phase_6_verify")

    # Mock _run_tool 返回 FAILED（非 auth）
    executor._run_tool = Mock(return_value=PhaseResult(
        "phase_6_verify",
        PhaseStatus.FAILED,
        errors=["5 个定位器未解析"]
    ))
    executor._is_auth_failure = Mock(return_value=False)

    result = executor._execute_multi_module(
        "phase_6_verify",
        "verification/verify_orchestrator.py",
        []
    )

    # 应该 PASSED + warning（不阻断）
    assert_phase_result(
        result,
        PhaseStatus.PASSED,
        warning_keywords=["未解析", "不阻断"]
    )
    print("✓ Test 4: tolerate_tool_failure → PASSED + warning")


# ============================================================================
# Test 5: _execute_multi_module — fatal_on_auth_failure 全局阻断
# ============================================================================

def test_multi_module_fatal_auth_failure():
    """Phase 4/6 (有 fatal_on_auth_failure) Cookie 失败应立即阻断"""
    executor = create_mock_executor("phase_6_verify")

    # Mock _run_tool 返回 FAILED（auth 失败）
    executor._run_tool = Mock(return_value=PhaseResult(
        "phase_6_verify",
        PhaseStatus.FAILED,
        errors=["[AUTH_REQUIRED] Cookie 失效"]
    ))
    executor._is_auth_failure = Mock(return_value=True)

    result = executor._execute_multi_module(
        "phase_6_verify",
        "verification/verify_orchestrator.py",
        []
    )

    # 应该 FAILED + 全局阻断提示
    assert_phase_result(
        result,
        PhaseStatus.FAILED,
        error_keywords=["认证失败", "更新 Cookie"]
    )
    print("✓ Test 5: fatal_on_auth_failure → FAILED + 全局阻断")


# ============================================================================
# Test 6: _execute_multi_module — 无模块边界场景
# ============================================================================

def test_multi_module_no_modules_with_tolerate():
    """有 tolerate_tool_failure 的阶段，无模块应返回 PASSED + warning"""
    executor = create_mock_executor("phase_6_verify", modules=[])

    result = executor._execute_multi_module(
        "phase_6_verify",
        "verification/verify_orchestrator.py",
        []
    )

    assert_phase_result(
        result,
        PhaseStatus.PASSED,
        warning_keywords=["无模块可处理"]
    )
    print("✓ Test 6a: no modules + tolerate → PASSED + warning")


def test_multi_module_no_modules_without_tolerate():
    """无 tolerate_tool_failure 的阶段，无模块应返回 FAILED"""
    executor = create_mock_executor("phase_5", modules=[])

    result = executor._execute_multi_module(
        "phase_5",
        "generation/generate_from_excel.py",
        []
    )

    assert_phase_result(
        result,
        PhaseStatus.FAILED,
        error_keywords=["无模块可处理"]
    )
    print("✓ Test 6b: no modules + no tolerate → FAILED")


# ============================================================================
# Test 7: _cascade_skip — 统一 SKIPPED（移除 gate 升级）
# ============================================================================

def test_cascade_skip_uniform_skipped():
    """上游失败时，所有依赖阶段（包括 gate）统一标记为 SKIPPED"""
    executor = create_mock_executor()

    # Phase 6 失败
    executor.results["phase_6_verify"] = PhaseResult(
        "phase_6_verify",
        PhaseStatus.FAILED,
        errors=["验证失败"]
    )

    # 触发级联跳过
    executor._cascade_skip("phase_6_verify")

    # Phase 8（gate 阶段）应该 SKIPPED（不是 FAILED）
    phase_8_result = executor.results.get("phase_8")
    assert phase_8_result is not None, "Phase 8 should be skipped"
    assert_phase_result(
        phase_8_result,
        PhaseStatus.SKIPPED,
        warning_keywords=["phase_6_verify"]
    )

    # Phase 9 也应该 SKIPPED（递归级联）
    phase_9_result = executor.results.get("phase_9")
    assert phase_9_result is not None, "Phase 9 should be skipped"
    assert_phase_result(
        phase_9_result,
        PhaseStatus.SKIPPED,
        warning_keywords=["phase_8"]
    )

    print("✓ Test 7: _cascade_skip → uniform SKIPPED (no gate upgrade)")


# ============================================================================
# Test 8: _is_auth_failure — 关键字检测
# ============================================================================

def test_is_auth_failure_keywords():
    """_is_auth_failure 应识别各类认证关键字"""
    executor = create_mock_executor()

    # 正向测试
    auth_errors = [
        ["401 Unauthorized"],
        ["403 Forbidden"],
        ["Cookie expired"],
        ["认证失败"],
        ["登录过期"],
        ["token invalid"],
    ]
    for errors in auth_errors:
        assert executor._is_auth_failure(errors) is True, \
            f"Should detect auth failure in: {errors}"

    # 负向测试
    non_auth_errors = [
        ["Network timeout"],
        ["File not found"],
        ["Syntax error"],
    ]
    for errors in non_auth_errors:
        assert executor._is_auth_failure(errors) is False, \
            f"Should NOT detect auth failure in: {errors}"

    print("✓ Test 8: _is_auth_failure keyword detection")


# ============================================================================
# 测试执行
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Pipeline.py 多模块执行逻辑单元测试")
    print("=" * 70)

    tests = [
        test_run_tool_exit_code_2,
        test_run_tool_exit_code_0,
        test_run_tool_exit_code_1,
        test_multi_module_tolerate_tool_failure,
        test_multi_module_fatal_auth_failure,
        test_multi_module_no_modules_with_tolerate,
        test_multi_module_no_modules_without_tolerate,
        test_cascade_skip_uniform_skipped,
        test_is_auth_failure_keywords,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test_fn.__name__}: Unexpected error: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
