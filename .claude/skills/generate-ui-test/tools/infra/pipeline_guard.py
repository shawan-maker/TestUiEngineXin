"""_pipeline_guard.py — 管线自愈 + 日志记录

策略：
1. 只自愈 Phase 2/3（参数完整、无外部依赖、风险低）
2. 只阻断 cookie 错误（AI 无法自己获取 cookie）
3. 其余情况记日志，不阻断，让 AI 在运行时自己修复

自愈场景：
- S2: Phase 2 缺失（config.yaml 存在但 run.py 不存在）→ 自愈 Phase 2
- S3: Phase 3 缺失（run.py 存在但 module_keywords.py 不存在）→ 自愈 Phase 3

阻断场景：
- Cookie 错误：Phase 4/6 FAILED 且错误包含 cookie/401/403/unauthorized/登录/认证失败
"""
import json
import sys
import os


PIPELINE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pipeline.py")
COOKIE_KEYWORDS = ["cookie", "401", "403", "unauthorized", "登录", "认证失败"]


def check_pipeline_state(project_dir, required_phases, tool_name, context=None):
    """检查管线状态，自愈 Phase 2/3，其余记日志。

    Args:
        project_dir: 项目根目录路径
        required_phases: 当前工具依赖的前置阶段列表
        tool_name: 当前工具名称（用于日志）
        context: dict, 可选
            - excel_path: Excel 文件路径（用于自愈时传入）
            - cookie: Cookie 字符串（用于自愈时传入）

    Returns:
        无返回值。自愈成功则继续执行，自愈失败则记日志继续执行，
        cookie 错误则 exit(2) 阻断。
    """
    probe_dir = os.path.join(project_dir, "_probe")
    state_file = os.path.join(probe_dir, "pipeline_state.json")
    config_yaml = os.path.join(project_dir, "config.yaml")
    run_py = os.path.join(project_dir, "run.py")

    # ── 场景 1: 无状态文件（全新项目或管线未运行）──
    if not os.path.exists(state_file):
        print(f"[pipeline-guard] {tool_name}: 未找到管线状态文件")
        print(f"   管线可能未运行，尝试自愈 Phase 2/3...")

        # S2: Phase 2 缺失 → 自愈
        if os.path.exists(config_yaml) and not os.path.exists(run_py):
            print(f"   检测到 config.yaml 存在但 run.py 不存在 -> 自愈 Phase 2")
            _try_self_heal(project_dir, "phase_2", context)

        # S3: Phase 3 缺失 → 自愈
        if os.path.exists(run_py):
            keywords_py = os.path.join(project_dir, "lib", "module_keywords.py")
            if not os.path.exists(keywords_py):
                print(f"   检测到 run.py 存在但 module_keywords.py 不存在 -> 自愈 Phase 3")
                _try_self_heal(project_dir, "phase_3_keywords", context)

        # 记录日志，不阻断（让 AI 后续处理）
        print(f"   自愈完成，工具继续执行")
        return

    # ── 场景 2: 有状态文件，检查前置阶段 ──
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[pipeline-guard] {tool_name}: 管线状态文件无法读取: {e}")
        return  # 记日志，不阻断

    phases = state.get("phases", state)  # 兼容两种格式

    for phase in required_phases:
        phase_data = phases.get(phase, {})
        status = phase_data.get("status", "not_run").upper()

        if status == "PASSED":
            continue  # 正常，继续检查下一个

        if status == "FAILED":
            # 检查是否 cookie 相关错误
            if _is_cookie_failure(phase_data):
                print(f"[pipeline-guard] {tool_name}: {phase} FAILED (cookie 错误)")
                print(f"   错误信息: {phase_data.get('errors', [])[:2]}")
                print(f"   Cookie 错误需要人工介入，无法自愈")
                print(f"   请重新登录获取 cookie 后运行: python tools/pipeline.py run --project {project_dir} --cookie \"新cookie\"")
                sys.exit(2)
            else:
                # 非 cookie 错误，记日志不阻断
                print(f"[pipeline-guard] {tool_name}: {phase} FAILED (非 cookie 错误)")
                print(f"   错误信息: {phase_data.get('errors', [])[:2]}")
                print(f"   工具继续执行，AI 可在运行时自行修复")
                continue

        if status in ("NOT_RUN", "SKIPPED"):
            # Phase 2/3 缺失 → 尝试自愈
            if phase in ("phase_2", "phase_3_keywords"):
                print(f"[pipeline-guard] {tool_name}: {phase} {status} -> 尝试自愈")
                _try_self_heal(project_dir, phase, context)
            else:
                # 其他阶段缺失，记日志不阻断
                print(f"[pipeline-guard] {tool_name}: {phase} {status}")
                print(f"   工具继续执行，AI 可在运行时自行修复")
            continue

        # 其他状态（PENDING, RUNNING 等）
        print(f"[pipeline-guard] {tool_name}: {phase} 状态异常: {status}")
        continue


def _is_cookie_failure(phase_data):
    """判断阶段失败是否由 cookie 引起。"""
    errors = phase_data.get("errors", [])
    error_str = str(errors).lower()
    return any(kw in error_str for kw in COOKIE_KEYWORDS)


def _try_self_heal(project_dir, phase, context):
    """尝试自愈指定阶段，失败不阻断。

    Args:
        project_dir: 项目根目录
        phase: 阶段名称（"phase_2" 或 "phase_3_keywords"）
        context: 上下文信息（excel_path, cookie）
    """
    cmd = [sys.executable, PIPELINE_PATH, "run",
           "--project", project_dir,
           "--only-phase", phase]

    # 添加 excel（如果可用）
    excel = (context or {}).get("excel_path")
    if excel and os.path.exists(excel):
        cmd.extend(["--excel", excel])

    # 添加 cookie（如果可用）
    cookie = (context or {}).get("cookie")
    if cookie:
        cmd.extend(["--cookie", cookie])

    try:
        import subprocess
        print(f"   [pipeline-guard] 自愈命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0:
            print(f"   [pipeline-guard] 自愈 {phase} 成功")
        else:
            print(f"   [pipeline-guard] 自愈 {phase} 失败 (exit {result.returncode})")
            if result.stderr:
                print(f"   错误: {result.stderr[:300]}")
    except subprocess.TimeoutExpired:
        print(f"   [pipeline-guard] 自愈 {phase} 超时 (120s)")
    except Exception as e:
        print(f"   [pipeline-guard] 自愈 {phase} 异常: {e}")

    # 失败不阻断，只记日志

