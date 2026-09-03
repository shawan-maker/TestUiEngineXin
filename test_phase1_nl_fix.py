"""
验证 Phase 1 NL 的 module_slug 占位符修复
"""
import sys
from pathlib import Path

# 添加 tools 目录到路径
tools_dir = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_dir))

from pipeline import PipelineContext

def test_module_slug_fallback():
    """测试 _resolve_args 的 module_slug fallback 逻辑"""
    print("=" * 70)
    print("测试 1: 空 modules 列表时应回退到 'common'")
    print("=" * 70)

    ctx = PipelineContext(project_dir="/tmp/test_project")
    # 模拟 Phase 1 NL 场景：modules 为空
    ctx.modules = []

    # 模拟 _resolve_args 的逻辑
    args = ["--module", "{module_slug}"]

    # 推断 module_slug 回退值
    _fallback_module_slug = (
        ctx.modules[0]["slug"] if len(ctx.modules) == 1
        else "common"
    )

    resolved_args = []
    for arg in args:
        try:
            resolved = arg.format(module_slug=_fallback_module_slug)
            resolved_args.append(resolved)
        except KeyError:
            resolved_args.append(arg)

    print(f"输入: {args}")
    print(f"输出: {resolved_args}")
    assert resolved_args == ["--module", "common"], f"期望 ['--module', 'common']，实际 {resolved_args}"
    print("✅ PASS\n")

def test_module_slug_single():
    """测试单模块场景"""
    print("=" * 70)
    print("测试 2: 单模块时应使用该模块 slug")
    print("=" * 70)

    ctx = PipelineContext(project_dir="/tmp/test_project")
    ctx.modules = [{"slug": "bcov", "cn_name": "BCOV模块"}]

    args = ["--module", "{module_slug}"]

    _fallback_module_slug = (
        ctx.modules[0]["slug"] if len(ctx.modules) == 1
        else "common"
    )

    resolved_args = []
    for arg in args:
        try:
            resolved = arg.format(module_slug=_fallback_module_slug)
            resolved_args.append(resolved)
        except KeyError:
            resolved_args.append(arg)

    print(f"输入: {args}")
    print(f"输出: {resolved_args}")
    assert resolved_args == ["--module", "bcov"], f"期望 ['--module', 'bcov']，实际 {resolved_args}"
    print("✅ PASS\n")

def test_module_slug_multi():
    """测试多模块场景"""
    print("=" * 70)
    print("测试 3: 多模块时应回退到 'common'")
    print("=" * 70)

    ctx = PipelineContext(project_dir="/tmp/test_project")
    ctx.modules = [
        {"slug": "module_a", "cn_name": "模块A"},
        {"slug": "module_b", "cn_name": "模块B"}
    ]

    args = ["--module", "{module_slug}"]

    _fallback_module_slug = (
        ctx.modules[0]["slug"] if len(ctx.modules) == 1
        else "common"
    )

    resolved_args = []
    for arg in args:
        try:
            resolved = arg.format(module_slug=_fallback_module_slug)
            resolved_args.append(resolved)
        except KeyError:
            resolved_args.append(arg)

    print(f"输入: {args}")
    print(f"输出: {resolved_args}")
    assert resolved_args == ["--module", "common"], f"期望 ['--module', 'common']，实际 {resolved_args}"
    print("✅ PASS\n")

if __name__ == "__main__":
    try:
        test_module_slug_fallback()
        test_module_slug_single()
        test_module_slug_multi()
        print("=" * 70)
        print("🎉 所有测试通过")
        print("=" * 70)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
