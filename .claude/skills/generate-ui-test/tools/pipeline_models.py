#!/usr/bin/env python3
"""
pipeline_models.py — 管线数据模型

阶段间数据接口定义（dataclass），替代文件名约定的隐式传递。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from enum import Enum


class PhaseStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PhaseResult:
    """每个阶段的统一返回结构"""
    phase: str                    # 阶段标识（如 "phase_4"）
    status: PhaseStatus
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ─── Phase 0: 配置确认 ───

@dataclass
class Phase0Output:
    """Phase 0 的输出：确认后的项目配置"""
    project_dir: Path
    config_path: Path             # {project}/config.yaml
    target_url: str
    browser_type: str             # chromium / firefox / webkit
    auth_type: str                # none / cookie / header / localStorage
    cookie: Optional[str] = None
    cookie_domain: Optional[str] = None
    local_storage: Optional[dict] = None
    excel_path: Optional[Path] = None   # Excel 输入时的原始文件路径


# ─── Phase 1: Excel 预检 ───

@dataclass
class Phase1Output:
    """Phase 1 的输出：预检后的 Excel 文件"""
    validated_excel_path: Path    # 修正版 Excel 路径（或原始路径）
    excel_json_path: Path         # read_excel.py 输出的 JSON
    module_urls_path: Optional[Path] = None  # --extract-urls 输出
    l1_fixes: int = 0
    l2_fixes: int = 0
    l3_errors: int = 0


# ─── Phase 2: 脚手架 ───

@dataclass
class Phase2Output:
    """Phase 2 的输出：项目脚手架"""
    project_dir: Path
    modules: list[str]            # 已创建的模块列表
    run_py_path: Path
    config_path: Path


# ─── Phase 3: 模块关键字编译 ───

@dataclass
class Phase3Output:
    """Phase 3 的输出：编译后的 L3 关键字"""
    module_keywords_path: Optional[Path] = None  # lib/module_keywords.py
    workflow_count: int = 0
    skipped: bool = False         # _knowledge/ 为空时跳过
    skip_reason: Optional[str] = None


# ─── Phase 4: 元素探测 ───

@dataclass
class DiscoveryEntry:
    """单个模块的探测结果"""
    module_slug: str
    cn_name: str
    discovery_path: Path          # discovery_{module}.json
    url_count: int = 1
    element_count: int = 0
    verified_count: int = 0


@dataclass
class Phase4Output:
    """Phase 4 的输出：全量探测结果"""
    discoveries: list[DiscoveryEntry]
    probe_dir: Path               # {project}/_probe/
    module_urls_path: Optional[Path] = None


# ─── Phase 5: cases + pages + data 生成 ───

@dataclass
class ModuleArtifacts:
    """单个模块的生成产物"""
    module_slug: str
    pages_path: Path              # pages/{module}/elements.yaml
    cases_dir: Path               # cases/{module}/
    data_dir: Path                # data/{module}/
    case_count: int = 0
    field_count: int = 0
    match_report_path: Optional[Path] = None


@dataclass
class Phase5Output:
    """Phase 5 的输出：cases + pages + data"""
    modules: list[ModuleArtifacts]
    pending_detail_links_path: Optional[Path] = None


# ─── Phase 6: 运行时定位器验证 ───

@dataclass
class Phase6Output:
    """Phase 6 的输出：验证 + 回写结果"""
    verify_result_path: Path      # _probe/verify_result.json
    total_steps: int = 0
    verified_count: int = 0
    writeback_count: int = 0
    unverified_count: int = 0


# ─── Phase 7: suites 生成 ───

@dataclass
class Phase7Output:
    """Phase 7 的输出：测试套件"""
    suite_paths: list[Path]       # suites/{module}/smoke.yaml


# ─── Phase 8: 跨文件验证 + 报告 ───

@dataclass
class Phase8Output:
    """Phase 8 的输出：验证结果 + 生成报告"""
    validate_08_errors: int = 0
    validate_08_warnings: int = 0
    violations_json_path: Optional[Path] = None
    report_html_path: Optional[Path] = None
    ref_validation_errors: list[str] = field(default_factory=list)


# ─── Phase 9: 运行验证 ───

@dataclass
class Phase9Output:
    """Phase 9 的输出：运行结果"""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    analysis_json_path: Optional[Path] = None
