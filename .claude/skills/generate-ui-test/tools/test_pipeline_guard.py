#!/usr/bin/env python3
"""pipeline_guard 验证脚本 (V1-V5)

测试 _pipeline_guard.py 的自愈+日志+cookie阻断 逻辑。

V1: 无 pipeline_state.json + config.yaml 存在 + run.py 不存在 → 自愈 Phase 2
V2: phase_5 FAILED + cookie 错误 → exit(2) 阻断
V3: phase_5 FAILED + 非 cookie 错误 → 记日志不阻断
V4: 缺少 config.yaml → generate_suites.py 自身报错
V5: TSManager2 正常流程 → 无警告
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent.parent
TOOLS_DIR = PROJECT_ROOT / ".claude" / "skills" / "generate-ui-test" / "tools"
TEST_PROJECT = PROJECT_ROOT / "examples" / "test-selfheal"


def setup_test_project():
    if TEST_PROJECT.exists():
        shutil.rmtree(TEST_PROJECT)
    TEST_PROJECT.mkdir(parents=True)
    return TEST_PROJECT


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_test(name, cmd, expect_exit=None, expect_in_output=None, expect_not_in_output=None):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"CMD:  {' '.join(cmd)}")
    print(f"{'='*60}")

    result = subprocess.run(
        cmd,
        cwd=str(TOOLS_DIR),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}
    )

    stdout = result.stdout
    stderr = result.stderr
    combined = stdout + "\n" + stderr

    print(f"EXIT: {result.returncode}")
    # Print first 30 lines of combined output
    lines = combined.strip().split("\n")
    for line in lines[:30]:
        print(f"  | {line}")
    if len(lines) > 30:
        print(f"  ... ({len(lines) - 30} more lines)")

    ok = True

    if expect_exit is not None and result.returncode != expect_exit:
        print(f"  [FAIL] exit code: expected {expect_exit}, got {result.returncode}")
        ok = False

    if expect_in_output:
        for text in expect_in_output:
            if text not in combined:
                print(f"  [FAIL] output should contain: '{text}'")
                ok = False

    if expect_not_in_output:
        for text in expect_not_in_output:
            if text in combined:
                print(f"  [FAIL] output should NOT contain: '{text}'")
                ok = False

    if ok:
        print(f"  [PASS]")
    return ok


def test_v1_self_heal_phase2():
    """V1: 无 pipeline_state.json + config.yaml 存在 + run.py 不存在
    generate_suites.py 检查 [phase_5]，但 guard 会先检测到无状态文件，
    然后尝试自愈 Phase 2（因为 config.yaml 存在但 run.py 不存在）"""
    setup_test_project()

    # 只创建 config.yaml，不创建 run.py 和 pipeline_state.json
    (TEST_PROJECT / "config.yaml").write_text(
        "target_url: http://test.com\nbrowser_type: chromium\n"
    )

    return run_test(
        "V1: self-heal Phase 2 (no state file)",
        ["python", "generate_suites.py", str(TEST_PROJECT), "--all-modules"],
        expect_in_output=[
            "[pipeline-guard]",
            "phase_2",
        ]
    )


def test_v2_cookie_block():
    """V2: phase_5 FAILED + cookie 错误 → exit(2) 阻断
    verify_locators.py 检查 [phase_5]，phase_5 状态是 FAILED 且包含 cookie 关键词"""
    setup_test_project()

    (TEST_PROJECT / "config.yaml").write_text(
        "target_url: http://test.com\nbrowser_type: chromium\n"
    )
    (TEST_PROJECT / "_probe").mkdir(exist_ok=True)

    # phase_5 FAILED with cookie error
    write_json(TEST_PROJECT / "_probe" / "pipeline_state.json", {
        "phases": {
            "phase_0": {"status": "passed"},
            "phase_2": {"status": "passed"},
            "phase_5": {
                "status": "failed",
                "errors": ["401 Unauthorized: cookie expired"]
            }
        }
    })

    return run_test(
        "V2: cookie error blocks (exit 2)",
        ["python", "verify_locators.py", str(TEST_PROJECT),
         "--cookie", "test_cookie", "--url", "http://test.com", "--dry-run"],
        expect_exit=2,
        expect_in_output=[
            "[pipeline-guard]",
            "cookie",
        ]
    )


def test_v3_non_cookie_no_block():
    """V3: phase_5 FAILED + 非 cookie 错误 → 记日志不阻断
    verify_locators.py 检查 [phase_5]，phase_5 状态是 FAILED 但无 cookie 关键词"""
    setup_test_project()

    (TEST_PROJECT / "config.yaml").write_text(
        "target_url: http://test.com\nbrowser_type: chromium\n"
    )
    (TEST_PROJECT / "_probe").mkdir(exist_ok=True)

    # phase_5 FAILED with non-cookie error
    write_json(TEST_PROJECT / "_probe" / "pipeline_state.json", {
        "phases": {
            "phase_0": {"status": "passed"},
            "phase_2": {"status": "passed"},
            "phase_5": {
                "status": "failed",
                "errors": ["Network timeout"]
            }
        }
    })

    return run_test(
        "V3: non-cookie error, no block",
        ["python", "verify_locators.py", str(TEST_PROJECT),
         "--cookie", "test_cookie", "--url", "http://test.com", "--dry-run"],
        # Should NOT exit(2) from guard; may exit with other code from tool logic
        expect_in_output=[
            "[pipeline-guard]",
            "FAILED",
        ],
        expect_not_in_output=[
            "Cookie",
        ]
    )


def test_v4_missing_config():
    """V4: 缺少 config.yaml → generate_suites.py 自身报错"""
    setup_test_project()
    # No config.yaml, no _probe

    return run_test(
        "V4: missing config.yaml",
        ["python", "generate_suites.py", str(TEST_PROJECT), "--all-modules"],
        expect_exit=2,
        expect_in_output=["config.yaml"]
    )


def test_v5_normal_flow():
    """V5: TSManager2 正常流程 → 无 guard 警告"""
    tsmanager = PROJECT_ROOT / "examples" / "TSManager2"

    if not tsmanager.exists():
        print(f"\nSKIP V5: {tsmanager} not found")
        return True

    return run_test(
        "V5: normal flow (TSManager2)",
        ["python", "generate_suites.py", str(tsmanager), "--all-modules"],
        expect_exit=0,
        expect_not_in_output=["[pipeline-guard]"]
    )


if __name__ == "__main__":
    print("=" * 60)
    print("Pipeline Guard Validation Tests (V1-V5)")
    print("=" * 60)

    tests = [
        ("V1: self-heal Phase 2", test_v1_self_heal_phase2),
        ("V2: cookie block", test_v2_cookie_block),
        ("V3: non-cookie no block", test_v3_non_cookie_no_block),
        ("V4: missing config", test_v4_missing_config),
        ("V5: normal flow", test_v5_normal_flow),
    ]

    results = []
    for name, fn in tests:
        results.append((name, fn()))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    for name, result in results:
        print(f"  {'PASS' if result else 'FAIL'}: {name}")
    print(f"\nTotal: {passed}/{len(results)} passed")

    sys.exit(0 if passed == len(results) else 1)
