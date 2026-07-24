#!/usr/bin/env python3
"""
统一阶段门禁注册表 — 声明式阶段产物检查

设计原则:
  1. 声明式 — 每个阶段的产物和检查条件在注册表中声明
  2. 条件化 — 前置阶段是否需要检查取决于条件（如 _knowledge/ 为空则 Phase 3 无需检查）
  3. 可复用 — 同一个 check_prerequisite_phases() 函数被多个验证器调用
  4. 可扩展 — 新增阶段只需在注册表中加一条

用法:
    from tools._phase_registry import check_prerequisite_phases
    violations = check_prerequisite_phases(project_dir, 'validate_08')
"""
import json
import os
import glob
from dataclasses import dataclass


@dataclass
class Violation:
    """与 validate_08_scripts.py Violation 格式一致"""
    file: str
    line: int
    rule: str
    severity: str
    message: str
    suggestion: str


# ============================================================================
# 内容完整性校验器（Reg-A: 防止手动伪造空文件通过门禁）
# ============================================================================

def _validate_verify_result(filepath):
    """Reg-A: 验证 verify_result.json 是 verify_locators.py 实际运行的产物

    Returns: (ok: bool, message: str)
    """
    # 仅校验 verify_result.json（probe_supplement*.json 跳过）
    if not os.path.basename(filepath).startswith('verify_result'):
        return True, "OK (non-verify_result artifact)"

    try:
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, f"JSON 解析失败: {e}"

    if not isinstance(data, dict):
        return False, "根元素不是对象"

    # 1. 必须字段检查（修复后的 verify_locators.py 才写入这些字段）
    required = ['total_steps', 'verified', 'writeback_count']
    for field in required:
        if field not in data:
            return False, (
                f"缺少必须字段: {field}"
                f"（verify_locators.py 版本过旧或未实际运行，请重新执行）"
            )

    # 2. 完整性检查: total_steps > 0 排除手动创建的空文件
    total = data.get('total_steps', 0)
    if not isinstance(total, int) or total <= 0:
        return False, f"total_steps={total}，verify_locators.py 未实际执行任何步骤"

    return True, "OK"


# ============================================================================
# 阶段产物注册表
# ============================================================================

PHASE_ARTIFACTS = {
    'phase_4_discovery': {
        'artifact_globs': ['_probe/probe_*.json', '_probe/discovery_*.json'],
        'min_count': 1,
        'condition_check': lambda d: bool(
            glob.glob(os.path.join(d, 'pages', '**', '*.yaml'), recursive=True)
        ),
        'condition_reason': 'pages YAML 已生成，但无任何 probe 结果',
        'remediation': 'python discover_page.py "{url}" --cookie "..." --module ... --output {project}/_probe/discovery_{module}.json',
    },
    'phase_6_verify': {
        'artifact_globs': ['_probe/probe_supplement*.json', '_probe/verify_result.json'],
        'min_count': 1,
        'content_validator': _validate_verify_result,
        'condition_check': lambda d: bool(
            glob.glob(os.path.join(d, 'pages', '**', '*.yaml'), recursive=True)
        ),
        'condition_reason': 'pages YAML 已生成，但 Phase 6 (verify_locators.py) 未执行',
        'remediation': 'python verify_locators.py {project} --cookie "..." --url "..." --discovery ... --module ...',
    },
    'phase_3_keywords': {
        'artifact_globs': ['lib/module_keywords.py'],
        'min_count': 1,
        'condition_check': lambda d: bool(
            glob.glob(os.path.join(d, '_knowledge', '*.yaml'))
            or glob.glob(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'lib', '_knowledge', '*.yaml'))
        ),
        'condition_reason': '_knowledge/ 有 workflows 但 module_keywords.py 不存在',
        'remediation': 'python compile_module_keywords.py {project}',
    },
}

# ============================================================================
# 验证器 → 前置阶段映射
# ============================================================================

VALIDATOR_PREREQUISITES = {
    'validate_04': [],  # 旧 phase_2_harvest 已废弃（Phase 4 探测，文件不改名）
    'validate_03': [],  # Phase 3 在 Phase 6 之前执行，无前置（D1 决策）
    'validate_08': [    # Phase 8 跨文件验证
        'phase_4_discovery',
        'phase_6_verify',
        'phase_3_keywords',
    ],
}


# ============================================================================
# 通用前置检查函数
# ============================================================================

def check_prerequisite_phases(project_dir, validator_name):
    """检查当前验证器所需的所有前置阶段是否已执行。

    Args:
        project_dir: 项目根目录
        validator_name: 当前验证器名（如 'validate_08'）

    Returns:
        list[Violation]: 未满足的前置阶段违规列表
    """
    prerequisites = VALIDATOR_PREREQUISITES.get(validator_name, [])
    if not prerequisites:
        return []

    violations = []
    for phase_key in prerequisites:
        spec = PHASE_ARTIFACTS[phase_key]

        # 1. 检查前置条件 — 条件不满足说明前置阶段本身不需要执行
        cond = spec.get('condition_check')
        if cond and not cond(project_dir):
            continue  # 前置阶段不需要（如无 pages YAML → 无需 probe）

        # 2. 检查主产物（支持多个 glob）
        globs = spec.get('artifact_globs', [spec.get('artifact_glob', '')])
        matched_files = []
        for g in globs:
            matched_files.extend(glob.glob(os.path.join(project_dir, g)))
        min_count = spec.get('min_count', 1)

        if len(matched_files) >= min_count:
            # Reg-A: 内容完整性校验（防止手动创建空文件通过门禁）
            validator = spec.get('content_validator')
            if validator:
                for fp in matched_files:
                    ok, msg = validator(fp)
                    if not ok:
                        violations.append(Violation(
                            file=fp,
                            line=0,
                            rule='PREREQUISITE_INTEGRITY',
                            severity='error',
                            message=f"产物完整性校验失败: {msg}",
                            suggestion=spec['remediation'].replace('{project}', project_dir),
                        ))
            continue  # 主产物存在（完整性问题已单独报告）

        # 3. 不满足 → 记录违规
        violations.append(Violation(
            file=project_dir,
            line=0,
            rule='PREREQUISITE',
            severity='error',
            message=spec['condition_reason'] + f'（{phase_key}）',
            suggestion=spec['remediation'].replace('{project}', project_dir),
        ))

    return violations
