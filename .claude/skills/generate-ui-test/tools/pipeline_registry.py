#!/usr/bin/env python3
"""
pipeline_registry.py — 阶段注册表（单一真相源）

定义 11 个 Phase 的依赖关系、工具、验证器、产物。
编排器和 _phase_registry.py 都从这里读取。
"""

import os
from pathlib import Path
from typing import Any


def _has_knowledge_files(ctx) -> bool:
    """检查是否有 workflow YAML（系统级 + 项目级 + 技能级）"""
    skill_dir = Path(__file__).parent.parent

    # 1. 系统级: lib/system_workflows.yaml
    sys_wf = skill_dir / "lib" / "system_workflows.yaml"
    if sys_wf.exists():
        return True

    # 2. 项目级 _knowledge/
    knowledge_dir = Path(ctx.project_dir) / "_knowledge"
    if knowledge_dir.exists() and any(knowledge_dir.glob("*.yaml")):
        return True

    # 3. 技能级 _knowledge/
    skill_knowledge = skill_dir / "lib" / "_knowledge"
    if skill_knowledge.exists() and any(skill_knowledge.glob("*.yaml")):
        return True

    return False


def _has_excel(ctx) -> bool:
    """检查是否有 Excel 输入"""
    return getattr(ctx, 'excel_path', None) is not None


def _has_nl_input(ctx) -> bool:
    """检查是否有自然语言输入（与 Excel 互斥）"""
    return getattr(ctx, 'cases_input_path', None) is not None


# ─── 阶段定义 ───

PHASE_DEFINITIONS: dict[str, dict[str, Any]] = {

    "phase_0": {
        "name": "配置确认",
        "tool": None,              # 交互式 / 模板填充
        "validator": "validate_00_config.py",
        "validator_args": ["{config_path}", "--runtime-check"],
        "hard_deps": [],
        "soft_deps": [],
        "artifacts": ["{project_dir}/config.yaml"],
        "optional": False,
        "multi_module": False,
    },

    "phase_1": {
        "name": "Excel 预检",
        "tool": "excel/validate_excel.py",
        "tool_args": ["{excel_path}"],
        "validator": None,          # validate_excel 自带 exit code
        "hard_deps": ["phase_0"],
        "soft_deps": [],
        "artifacts": [],            # validate_excel 产出修正版 xlsx + HTML 报告（路径不固定，不做幂等检查）
        "optional": True,
        "condition": _has_excel,
        "multi_module": False,
    },

    "phase_1b_parse": {
        "name": "Excel 解析",
        "tool": "excel/read_excel.py",
        "tool_args": [
            "{excel_path}",
            "--output", "{project_dir}/_probe/excel_parsed.json",
        ],
        "validator": None,          # read_excel 自带 exit code
        "hard_deps": ["phase_1"],
        "soft_deps": [],
        "artifacts": ["{project_dir}/_probe/excel_parsed.json"],
        "optional": True,
        "condition": _has_excel,
        "multi_module": False,
    },

    "phase_1_nl": {
        "name": "自然语言预检",
        "tool": "text/normalize_steps.py",
        "tool_args": [
            "{cases_input_path}",
            "--output", "{project_dir}/_probe/cases_raw.json",
            "--module", "{module_slug}",
            "--target-url", "{target_url}",
            "--non-interactive",
        ],
        "validator": None,          # normalize_steps 自带 exit code
        "hard_deps": ["phase_0"],
        "soft_deps": [],
        "artifacts": ["{project_dir}/_probe/cases_raw.json"],
        "optional": True,
        "condition": _has_nl_input,
        "multi_module": False,
    },

    "phase_2": {
        "name": "脚手架生成",
        "tool": None,              # 模板复制（编排器内部实现）
        "validator": "validate_02_scaffold.py",
        "validator_args": ["{project_dir}"],
        "hard_deps": ["phase_0"],
        "soft_deps": [],
        "artifacts": [
            "{project_dir}/run.py",
            "{project_dir}/.gitignore",
            "{project_dir}/lib/auth_keywords.py",
        ],
        "optional": False,
        "multi_module": False,
    },

    "phase_3_keywords": {
        "name": "模块关键字编译",
        "tool": "generators/compile_module_keywords.py",
        "tool_args": ["{project_dir}"],
        "validator": "validate_03_keywords.py",
        "validator_args": ["{project_dir}"],
        "hard_deps": ["phase_2"],
        "soft_deps": [],
        "artifacts": ["{project_dir}/lib/module_keywords.py"],
        "optional": False,
        "multi_module": False,
    },

    "phase_4_discovery": {
        "name": "全自动探测",
        "tool": "probe/run_phase4.py",
        "tool_args": [
            "--excel", "{excel_path}",
            "--config", "{config_path}",
            "--project", "{project_dir}",
            "--cookie", "{cookie}",
            "--local-storage", "{local_storage}",
            "--module", "{module_slug}",
        ],
        "validator": "validate_04_probe.py",
        "validator_args": ["{project_dir}"],
        "hard_deps": ["phase_0", "phase_2"],
        "soft_deps": ["phase_1"],
        "artifacts": [
            "{project_dir}/_probe/module_map.json",
            "{project_dir}/_probe/discovery_*.json",
        ],
        "optional": False,
        "multi_module": True,
        "fatal_on_auth_failure": True,
        "tolerate_tool_failure": True,  # 非 Cookie 的探测失败降级为 warning，不阻断管线
    },

    "phase_5": {
        "name": "cases+pages+data 生成",
        "tool": "generation/generate_from_excel.py",
        "tool_args": [
            "{excel_json_path}",
            "--discovery-dir", "{project_dir}/_probe/",
            "--output-dir", "{project_dir}",
        ],
        "validator": None,          # 由 CrossRef + Phase 8 统一验证
        "hard_deps": ["phase_4_discovery"],  # 硬依赖探测结果
        "soft_deps": ["phase_1b_parse", "phase_1_nl", "phase_3_keywords"],  # 软依赖：Excel 或 NL 二选一产出
        "artifacts": [
            "{project_dir}/pages/*/elements.yaml",
            "{project_dir}/cases/*/*.yaml",
            "{project_dir}/data/*/*.yaml",
        ],
        "optional": False,
        "multi_module": False,
    },

    "phase_6_verify": {
        "name": "运行时定位器验证",
        "tool": "verification/verify_orchestrator.py",
        "tool_args": [
            "{project_dir}",
            "--cookie", "{cookie}",
            "--local-storage", "{local_storage}",
            "--url", "{target_url}",
            "--module", "{module_slug}",
        ],
        "hard_deps": ["phase_0", "phase_5", "phase_4_discovery"],
        "soft_deps": [],
        "pre_hook": "validate_cross_refs",  # Phase 6 运行前执行端到端引用验证
        "artifacts": [
            "{project_dir}/_probe/verify_result.json",
        ],
        "optional": False,
        "multi_module": True,
        "fatal_on_auth_failure": True,
        "tolerate_tool_failure": True,  # 非 auth 的工具失败降级为 warning，不阻断管线
    },

    "phase_7": {
        "name": "suites 生成",
        "tool": "generators/generate_suites.py",
        "tool_args": ["{project_dir}", "--all-modules"],
        "validator": None,
        "hard_deps": ["phase_0", "phase_5"],
        "soft_deps": [],
        "artifacts": ["{project_dir}/suites/*/smoke.yaml"],
        "optional": False,
        "multi_module": False,
    },

    "phase_8": {
        "name": "跨文件验证 + 报告",
        "tool": None,              # 编排器内部组合多个验证器
        "validator": "validate_08_scripts.py",
        "validator_args": ["{project_dir}"],
        "hard_deps": ["phase_5", "phase_7"],
        "soft_deps": ["phase_3_keywords", "phase_6_verify"],   # phase_6 软依赖：定位器验证失败不阻断报告生成
        "artifacts": [
            "{project_dir}/_probe/phase8_violations.json",
        ],
        "optional": False,
        "gate": True,               # errors > 0 阻断 Phase 9
        "multi_module": False,
    },

    "phase_9": {
        "name": "运行验证",
        "tool": None,              # 调用 run.py
        "validator": "validate_09_execution.py",
        "validator_args": ["{project_dir}"],
        "hard_deps": ["phase_8"],
        "soft_deps": [],
        "artifacts": [],
        "optional": False,
        "multi_module": False,
    },
}


# ─── 执行顺序（拓扑排序结果） ───

EXECUTION_ORDER = [
    "phase_0",
    "phase_1",
    "phase_1b_parse",
    "phase_1_nl",
    "phase_2",
    "phase_3_keywords",
    "phase_4_discovery",
    "phase_5",
    "phase_6_verify",
    "phase_7",
    "phase_8",
    "phase_9",
]


def get_phase_def(phase_id: str) -> dict[str, Any]:
    """获取阶段定义"""
    return PHASE_DEFINITIONS.get(phase_id, {})


def get_all_phase_ids() -> list[str]:
    """获取所有阶段 ID"""
    return list(PHASE_DEFINITIONS.keys())
