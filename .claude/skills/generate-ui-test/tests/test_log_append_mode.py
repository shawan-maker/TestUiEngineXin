"""Test: Multi-module log append (fix for phase_6_verify_tool.log overwrite)"""
import sys
import tempfile
import shutil
from pathlib import Path

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from pipeline import PipelineContext, PipelineExecutor


def test_multi_module_log_append():
    """Verify that multiple module logs append to same file, not overwrite"""
    # Create temp project directory
    with tempfile.TemporaryDirectory() as tmpdir:
        probe_dir = Path(tmpdir) / "_probe"
        probe_dir.mkdir()

        # Create executor (minimal setup)
        ctx = PipelineContext(project_dir=tmpdir, target_url="http://test.com")
        executor = PipelineExecutor(ctx)

        # Simulate 3 modules writing logs for phase_6_verify
        modules = ["project", "cloud_question", "ecs_compute"]

        for module_slug in modules:
            # Call _save_tool_log with module_slug
            executor._save_tool_log(
                phase_id="phase_6_verify",
                tool="verification/verify_orchestrator.py",
                module_slug=module_slug,
                stdout=f"[Verify] Module: {module_slug}\n[OK] Steps: 4/5",
                stderr=""
            )

        # Read the log file
        log_path = probe_dir / "phase_6_verify_tool.log"
        assert log_path.exists(), "Log file should exist"

        content = log_path.read_text(encoding='utf-8')

        # Verify all 3 modules appear in log
        for module_slug in modules:
            assert module_slug in content, f"Module '{module_slug}' should appear in log"
            assert f"[Verify] Module: {module_slug}" in content, \
                f"Module '{module_slug}' stdout should appear"

        # Verify separators (should have 3 sections)
        separator_count = content.count("# Module:")
        assert separator_count == 3, f"Should have 3 module separators, found {separator_count}"

        # Verify timestamps (3 separate writes)
        timestamp_count = content.count("# Time:")
        assert timestamp_count == 3, f"Should have 3 timestamps, found {timestamp_count}"

        print("✅ Multi-module log append test PASSED")
        print(f"   - Log file: {log_path}")
        print(f"   - Modules logged: {modules}")
        print(f"   - Total lines: {len(content.splitlines())}")


if __name__ == "__main__":
    test_multi_module_log_append()
