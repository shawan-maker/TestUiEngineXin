#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — 统一管线编排器

用法:
    # 全量执行（从 Excel 到运行）
    python pipeline.py run --project {dir} --excel {file} --cookie "{cookie}"

    # 从指定阶段开始（跳过已完成的阶段）
    python pipeline.py run --project {dir} --from-phase phase_6_verify

    # 仅执行指定阶段
    python pipeline.py run --project {dir} --only-phase phase_4_discovery

    # 查看管线状态（不执行）
    python pipeline.py status --project {dir}

    # 检查阶段间引用一致性
    python pipeline.py validate-refs --project {dir}
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Windows 控制台 UTF-8 输出修复
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# 添加 tools 目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pipeline_models import (
    PhaseStatus,
    PhaseResult,
    Phase0Output,
    Phase1Output,
    Phase2Output,
    Phase3Output,
    Phase4Output,
    Phase5Output,
    Phase6Output,
    Phase7Output,
    Phase8Output,
    Phase9Output,
)
from pipeline_registry import PHASE_DEFINITIONS, EXECUTION_ORDER, get_phase_def
from cross_refs import validate_cross_refs


class PipelineContext:
    """管线执行上下文，存储阶段间共享数据"""

    def __init__(self, project_dir: str, excel_path: Optional[str] = None,
                 cookie: Optional[str] = None, modules: Optional[list] = None):
        self.project_dir = project_dir
        self.excel_path = excel_path
        self.cookie = cookie
        self.config_path = os.path.join(project_dir, "config.yaml")
        self.excel_json_path = None
        self.module_urls_path = None
        self.target_url = None
        self.modules: list[dict] = modules or []  # [{"slug": "xxx", "cn_name": "xxx", "urls": [...]}]
        self.discovery_path = None  # 当前处理的 discovery 文件路径

    def update_from_config(self):
        """从 config.yaml 加载配置"""
        # 自动推导 excel_json_path
        probe_dir = Path(self.project_dir) / "_probe"
        if probe_dir.exists():
            for json_file in probe_dir.glob("excel_parsed.json"):
                self.excel_json_path = str(json_file)
                break

        try:
            import yaml
        except ImportError:
            print("  ⚠️  PyYAML 未安装，跳过 config.yaml 加载")
            return

        config_file = Path(self.config_path)
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config:
                    self.target_url = config.get('target_url')
                    self.cookie = self.cookie or config.get('cookie')

                    # 加载模块列表
                    page_urls = config.get('page_urls', {})
                    if isinstance(page_urls, dict) and not self.modules:
                        for slug, urls in page_urls.items():
                            cn_name = slug  # 默认用 slug
                            self.modules.append({
                                "slug": slug,
                                "cn_name": cn_name,
                                "urls": urls if isinstance(urls, list) else [urls],
                            })

    def get_modules(self) -> list[dict]:
        """获取模块列表"""
        if self.modules:
            return self.modules

        # 从 _probe/ 目录推断模块
        probe_dir = Path(self.project_dir) / "_probe"
        if probe_dir.exists():
            for f in probe_dir.glob("discovery_*.json"):
                slug = f.stem.replace("discovery_", "")
                self.modules.append({"slug": slug, "cn_name": slug, "urls": []})

        return self.modules


class PipelineExecutor:
    """管线执行引擎"""

    def __init__(self, context: PipelineContext):
        self.context = context
        self.project_dir = context.project_dir
        self.registry = PHASE_DEFINITIONS
        self.results: dict[str, PhaseResult] = {}
        self.outputs: dict[str, Any] = {}
        self.start_time = datetime.now()

    def run(self, from_phase: str = None, only_phase: str = None):
        """按拓扑序执行管线"""
        print(f"\n{'='*60}")
        print(f"管线编排器启动")
        print(f"项目目录: {self.project_dir}")
        print(f"开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        # 加载配置
        self.context.update_from_config()

        # --from-phase: 计算需要跳过的阶段
        skip_phases = set()
        if from_phase:
            upstream = self._get_upstream(from_phase)
            for phase_id in EXECUTION_ORDER:
                if phase_id != from_phase and phase_id not in upstream:
                    # 在 from_phase 之前的非上游阶段 → 跳过
                    if EXECUTION_ORDER.index(phase_id) < EXECUTION_ORDER.index(from_phase):
                        skip_phases.add(phase_id)

        # --only-phase: 自动包含上游依赖
        run_phases = set(EXECUTION_ORDER)
        if only_phase:
            upstream = self._get_upstream(only_phase)
            run_phases = upstream | {only_phase}

        # 按顺序执行
        for phase_id in EXECUTION_ORDER:
            # --from-phase: 跳过前面的阶段
            if phase_id in skip_phases:
                continue

            # --only-phase: 只执行指定阶段及其依赖
            if only_phase and phase_id not in run_phases:
                continue

            # 已被级联跳过的阶段不再重复检查
            if phase_id in self.results:
                continue

            defn = self.registry[phase_id]

            # 检查可选条件
            if defn.get("optional") and defn.get("condition"):
                if not defn["condition"](self.context):
                    self.results[phase_id] = PhaseResult(
                        phase_id, PhaseStatus.SKIPPED,
                        warnings=["条件不满足，跳过"]
                    )
                    print(f"[{phase_id}] {defn['name']} ⏭️  SKIPPED (条件不满足)")
                    continue

            # 检查硬依赖
            missing = self._check_hard_deps(phase_id)
            if missing:
                self.results[phase_id] = PhaseResult(
                    phase_id, PhaseStatus.FAILED,
                    errors=[f"硬依赖缺失: {m}" for m in missing]
                )
                print(f"[{phase_id}] {defn['name']} ❌ FAILED (依赖缺失)")
                for m in missing:
                    print(f"  • {m}")

                # 级联跳过
                self._cascade_skip(phase_id)
                continue

            # 检查产物是否已存在（幂等跳过）
            if self._artifacts_exist(phase_id):
                ok, msg = self._validate_artifacts(phase_id)
                if ok:
                    self.results[phase_id] = PhaseResult(
                        phase_id, PhaseStatus.SKIPPED,
                        warnings=[f"产物已存在，跳过: {msg}"]
                    )
                    print(f"[{phase_id}] {defn['name']} ⏭️  SKIPPED (产物已存在)")
                    continue

            # 执行 pre_hook（如果有）
            pre_hook = defn.get("pre_hook")
            if pre_hook == "validate_cross_refs":
                print(f"[{phase_id}] 执行 pre_hook: validate_cross_refs")
                errors = validate_cross_refs(self.project_dir)
                if errors:
                    self.results[phase_id] = PhaseResult(
                        phase_id, PhaseStatus.FAILED,
                        errors=[f"引用验证失败: {len(errors)} 个错误"]
                    )
                    print(f"  ❌ 引用验证失败: {len(errors)} 个错误")
                    for err in errors[:5]:
                        print(f"    • {err}")
                    self._cascade_skip(phase_id)
                    continue

            # 运行阶段
            print(f"[{phase_id}] {defn['name']} 🔄 RUNNING")
            result = self._execute_phase(phase_id)
            self.results[phase_id] = result

            # 运行验证器（仅当阶段通过且有验证器时）
            if result.status == PhaseStatus.PASSED and defn.get("validator"):
                val_result = self._run_validator(phase_id)
                if val_result.returncode != 0:
                    result.status = PhaseStatus.FAILED
                    stderr_preview = (val_result.stderr or "")[:300]
                    result.errors.append(
                        f"验证器 {defn['validator']} 失败 (exit {val_result.returncode})"
                    )
                    if stderr_preview:
                        result.errors.append(f"验证器输出: {stderr_preview}")

            # 输出结果
            if result.status == PhaseStatus.PASSED:
                print(f"  ✅ PASSED ({result.duration_seconds:.1f}s)")
                if result.warnings:
                    for w in result.warnings[:3]:
                        print(f"  ⚠️  {w}")

            elif result.status == PhaseStatus.FAILED:
                print(f"  ❌ FAILED")
                for err in result.errors[:5]:
                    print(f"  • {err}")

                # gate 阶段失败则阻断后续
                if defn.get("gate"):
                    print(f"\n🚫 Gate 阶段 {phase_id} 失败，阻断后续阶段")
                    self._cascade_skip_all_remaining(phase_id)
                    break

                # 非 gate 阶段失败 → 级联跳过有依赖的阶段
                self._cascade_skip(phase_id)

        # 保存状态
        self._save_state()

        # 输出总结
        self._print_summary()

    def _get_upstream(self, target_phase: str) -> set[str]:
        """获取目标阶段的所有上游硬依赖"""
        upstream = set()
        queue = [target_phase]

        while queue:
            phase_id = queue.pop(0)
            if phase_id in upstream:
                continue
            upstream.add(phase_id)

            defn = self.registry.get(phase_id, {})
            for dep in defn.get("hard_deps", []):
                if dep not in upstream:
                    queue.append(dep)

        return upstream

    def _check_hard_deps(self, phase_id: str) -> list[str]:
        """检查硬依赖是否满足"""
        defn = self.registry[phase_id]
        missing = []

        for dep_id in defn["hard_deps"]:
            dep_result = self.results.get(dep_id)

            if dep_result and dep_result.status == PhaseStatus.FAILED:
                missing.append(f"{dep_id} (failed)")

            elif dep_result and dep_result.status == PhaseStatus.SKIPPED:
                # 跳过的阶段：检查其产物是否存在
                if not self._artifacts_exist(dep_id):
                    missing.append(f"{dep_id} (skipped, no artifacts)")

            elif not dep_result:
                # 依赖阶段未执行：检查产物是否存在
                if not self._artifacts_exist(dep_id):
                    missing.append(f"{dep_id} (not run)")

        return missing

    def _artifacts_exist(self, phase_id: str) -> bool:
        """检查阶段产物是否已存在"""
        defn = self.registry[phase_id]
        artifacts = defn.get("artifacts", [])

        if not artifacts:
            return False

        for artifact_pattern in artifacts:
            # 替换模板变量（安全方式，缺失变量跳过检查）
            try:
                pattern = artifact_pattern.format(
                    project_dir=self.project_dir,
                    excel_json_path=self.context.excel_json_path or "",
                )
            except KeyError:
                # 产物模式包含其他变量（如 {module_slug}），跳过此检查
                continue

            # 处理通配符
            if "*" in pattern:
                matches = glob.glob(pattern)
                if not matches:
                    return False
            else:
                if not Path(pattern).exists():
                    return False

        return True

    def _validate_artifacts(self, phase_id: str) -> tuple[bool, str]:
        """验证产物完整性"""
        defn = self.registry[phase_id]
        artifacts = defn.get("artifacts", [])

        for artifact_pattern in artifacts:
            try:
                pattern = artifact_pattern.format(
                    project_dir=self.project_dir,
                    excel_json_path=self.context.excel_json_path or "",
                )
            except KeyError:
                continue

            if "*" in pattern:
                matches = glob.glob(pattern)
                for match in matches:
                    try:
                        if Path(match).stat().st_size == 0:
                            return False, f"{match} 为空文件"
                    except OSError:
                        return False, f"{match} 无法读取"
            else:
                try:
                    if not Path(pattern).exists():
                        return False, f"{pattern} 不存在"
                    if Path(pattern).stat().st_size == 0:
                        return False, f"{pattern} 为空文件"
                except OSError:
                    return False, f"{pattern} 无法读取"

        return True, "所有产物存在且非空"

    def _execute_phase(self, phase_id: str) -> PhaseResult:
        """执行单个阶段"""
        start_time = time.time()
        defn = self.registry[phase_id]
        tool = defn.get("tool")

        try:
            if tool is None:
                # 内置阶段
                result = self._execute_builtin(phase_id)
            else:
                # 构建命令行
                args = self._resolve_args(defn.get("tool_args", []))

                if defn.get("multi_module"):
                    # 多模块：对每个模块执行一次
                    result = self._execute_multi_module(phase_id, tool, args)
                else:
                    result = self._run_tool(phase_id, tool, args)

            result.duration_seconds = time.time() - start_time
            return result

        except Exception as e:
            return PhaseResult(
                phase_id, PhaseStatus.FAILED,
                errors=[f"执行异常: {str(e)}"],
                duration_seconds=time.time() - start_time
            )

    def _execute_builtin(self, phase_id: str) -> PhaseResult:
        """内置阶段（无外部 tool）的执行逻辑"""
        handlers = {
            "phase_0": self._phase0_config,
            "phase_2": self._phase2_scaffold,
            "phase_8": self._phase8_validate_and_report,
            "phase_9": self._phase9_execution,
        }

        handler = handlers.get(phase_id)
        if handler:
            return handler()
        else:
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=[f"未知的内置阶段: {phase_id}"])

    def _phase0_config(self) -> PhaseResult:
        """Phase 0: 配置确认（已由用户提供，只验证）"""
        config_path = Path(self.project_dir) / "config.yaml"
        if not config_path.exists():
            return PhaseResult("phase_0", PhaseStatus.FAILED,
                             errors=["config.yaml 不存在"])

        # 运行验证器
        val_result = self._run_validator("phase_0")
        if val_result.returncode != 0:
            stderr_preview = (val_result.stderr or "")[:300]
            return PhaseResult("phase_0", PhaseStatus.FAILED,
                             errors=["配置验证失败", stderr_preview])

        return PhaseResult("phase_0", PhaseStatus.PASSED)

    def _phase2_scaffold(self) -> PhaseResult:
        """Phase 2: 脚手架生成"""
        project_path = Path(self.project_dir)
        templates_dir = Path(__file__).parent.parent / "templates"

        # 检查脚手架是否已存在
        run_py = project_path / "run.py"
        if run_py.exists():
            # 验证完整性
            val_result = self._run_validator("phase_2")
            if val_result.returncode == 0:
                return PhaseResult("phase_2", PhaseStatus.PASSED,
                                 warnings=["脚手架已存在且有效"])
            # 验证失败但 run.py 存在 → 尝试修复
            return PhaseResult("phase_2", PhaseStatus.FAILED,
                             errors=["脚手架已存在但验证失败，请检查 run.py 和目录结构"])

        # 检查模板目录
        if not templates_dir.exists():
            return PhaseResult("phase_2", PhaseStatus.FAILED,
                             errors=[f"模板目录不存在: {templates_dir}"])

        errors = []

        # 创建目录结构
        dirs_to_create = [
            "pages", "data", "cases", "suites",
            "lib", "_probe",
            "files/logs", "files/shortcuts", "files/downloads",
            "report/generate_report", "report/run_report",
        ]

        # 加载 config.yaml 获取模块信息
        modules = []
        config_path = project_path / "config.yaml"
        if config_path.exists():
            try:
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    page_urls = config.get('page_urls', {})
                    if isinstance(page_urls, dict):
                        modules = list(page_urls.keys())
            except Exception:
                pass

        # 共享资源层始终创建（common_elements / common_data 的写入目标）
        for base in ["pages", "data", "cases", "suites"]:
            dirs_to_create.append(f"{base}/common")

        # 业务模块目录（无模块时 common 已创建，无需额外操作）
        if modules:
            for module in modules:
                if module == "common":
                    continue  # 已创建，不重复
                for base in ["pages", "data", "cases", "suites"]:
                    dirs_to_create.append(f"{base}/{module}")

        for d in dirs_to_create:
            (project_path / d).mkdir(parents=True, exist_ok=True)

        # 复制模板文件
        template_map = {
            "run.py.tpl": "run.py",
            "config.yaml.tpl": None,  # config.yaml 已在 Phase 0 创建
            ".gitignore.tpl": ".gitignore",
            "auth_keywords.py.tpl": "lib/auth_keywords.py",
            "auto_learn_keywords.py.tpl": "lib/auto_learn_keywords.py",
            "README.md.tpl": "README.md",
        }

        for tpl_name, target_name in template_map.items():
            if target_name is None:
                continue
            tpl_path = templates_dir / tpl_name
            target_path = project_path / target_name

            if target_path.exists():
                continue

            if tpl_path.exists():
                try:
                    content = tpl_path.read_text(encoding='utf-8')
                    # 基本变量替换
                    content = content.replace("{{project_name}}", project_path.name)
                    content = content.replace("{{target_url}}", self.context.target_url or "")
                    content = content.replace("{{browser_type}}", "chromium")
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(content, encoding='utf-8')
                except Exception as e:
                    errors.append(f"模板复制失败 {tpl_name} → {target_name}: {e}")
            else:
                # 非关键模板缺失只警告
                if tpl_name in ("run.py.tpl",):
                    errors.append(f"关键模板不存在: {tpl_path}")

        # 创建 __init__.py
        init_py = project_path / "lib" / "__init__.py"
        if not init_py.exists():
            init_py.write_text("", encoding='utf-8')

        if errors:
            return PhaseResult("phase_2", PhaseStatus.FAILED, errors=errors)

        # 运行验证器
        val_result = self._run_validator("phase_2")
        if val_result.returncode != 0:
            stderr_preview = (val_result.stderr or "")[:300]
            return PhaseResult("phase_2", PhaseStatus.FAILED,
                             errors=["脚手架验证失败", stderr_preview])

        return PhaseResult("phase_2", PhaseStatus.PASSED,
                         warnings=[f"模块: {', '.join(modules)}"])

    def _phase8_validate_and_report(self) -> PhaseResult:
        """Phase 8: 跨文件验证 + 报告生成"""
        errors = []

        # 1. 运行 validate_08_scripts.py
        val_result = self._run_validator("phase_8")
        if val_result.returncode != 0:
            stderr_preview = (val_result.stderr or "")[:300]
            errors.append(f"validate_08_scripts.py 失败 (exit {val_result.returncode})")
            if stderr_preview:
                errors.append(f"验证器输出: {stderr_preview}")

        # 2. 运行 validate_09_report.py（如果存在）
        report_validator = Path(__file__).parent.parent / "validators" / "validate_09_report.py"
        if report_validator.exists():
            result = subprocess.run(
                [sys.executable, str(report_validator), self.project_dir],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                errors.append("validate_09_report.py 失败")

        # 3. 生成 issues_report（如果存在）
        report_generator = Path(__file__).parent / "generate_issues_report.py"
        if report_generator.exists():
            try:
                result = subprocess.run(
                    [sys.executable, str(report_generator), self.project_dir],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode != 0:
                    errors.append("generate_issues_report.py 失败")
            except subprocess.TimeoutExpired:
                errors.append("generate_issues_report.py 超时")

        if errors:
            return PhaseResult("phase_8", PhaseStatus.FAILED, errors=errors)

        return PhaseResult("phase_8", PhaseStatus.PASSED)

    def _phase9_execution(self) -> PhaseResult:
        """Phase 9: 运行验证"""
        run_py = Path(self.project_dir) / "run.py"
        if not run_py.exists():
            return PhaseResult("phase_9", PhaseStatus.FAILED,
                             errors=["run.py 不存在"])

        # 运行 validate_09_execution.py
        val_result = self._run_validator("phase_9")
        if val_result.returncode != 0:
            stderr_preview = (val_result.stderr or "")[:300]
            return PhaseResult("phase_9", PhaseStatus.FAILED,
                             errors=["运行验证失败", stderr_preview])

        return PhaseResult("phase_9", PhaseStatus.PASSED)

    def _execute_multi_module(self, phase_id: str, tool: str,
                              args: list[str]) -> PhaseResult:
        """多模块执行（Phase 4/6）— 逐模块运行，Cookie 失败全局阻断"""
        defn = self.registry[phase_id]
        modules = self.context.get_modules()

        if not modules:
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=["无模块可处理，请检查 config.yaml 的 page_urls 或 _probe/ 目录"])

        all_errors = []
        all_warnings = []
        auth_failed = False

        for module_info in modules:
            slug = module_info["slug"]
            print(f"  [{slug}] 🔄 处理模块...")

            # 构建模块特定的参数
            module_args = []
            for arg in args:
                resolved = arg.replace("{module_slug}", slug)
                resolved = resolved.replace("{module_urls_path}",
                                          self.context.module_urls_path or "")
                module_args.append(resolved)

            # 设置 discovery 路径（Phase 6 需要）
            if phase_id == "phase_6_verify":
                discovery_file = Path(self.project_dir) / "_probe" / f"discovery_{slug}.json"
                if discovery_file.exists():
                    self.context.discovery_path = str(discovery_file)
                    module_args = [a.replace("{discovery_path}", str(discovery_file))
                                 for a in module_args]

            result = self._run_tool(phase_id, tool, module_args)

            if result.status == PhaseStatus.FAILED:
                # 检查是否是认证失败
                is_auth_failure = self._is_auth_failure(result.errors)

                if is_auth_failure and defn.get("fatal_on_auth_failure"):
                    print(f"  [{slug}] ❌ Cookie 认证失败，全局阻断")
                    return PhaseResult(
                        phase_id, PhaseStatus.FAILED,
                        errors=[f"模块 {slug} 认证失败: {result.errors[0] if result.errors else '未知'}",
                               "请更新 Cookie 后使用 --from-phase 重新运行"]
                    )

                all_errors.extend([f"[{slug}] {e}" for e in result.errors])
                print(f"  [{slug}] ❌ FAILED")
            else:
                print(f"  [{slug}] ✅ PASSED")
                all_warnings.extend([f"[{slug}] {w}" for w in result.warnings])

        if all_errors:
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=all_errors, warnings=all_warnings)

        return PhaseResult(phase_id, PhaseStatus.PASSED,
                         warnings=all_warnings or [f"已处理 {len(modules)} 个模块"])

    def _is_auth_failure(self, errors: list[str]) -> bool:
        """检测是否是认证失败"""
        auth_keywords = [
            "401", "403", "unauthorized", "认证失败", "cookie",
            "登录", "login", "redirect", "重定向", "auth",
            "token", "expired", "过期"
        ]
        for err in errors:
            err_lower = err.lower()
            for kw in auth_keywords:
                if kw in err_lower:
                    return True
        return False

    def _run_tool(self, phase_id: str, tool: str, args: list[str]) -> PhaseResult:
        """运行外部工具"""
        tool_path = Path(__file__).parent / tool
        if not tool_path.exists():
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=[f"工具不存在: {tool_path}"])

        cmd = [sys.executable, str(tool_path)] + args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600  # 10 分钟超时
            )

            if result.returncode == 0:
                return PhaseResult(phase_id, PhaseStatus.PASSED)
            else:
                stderr_preview = (result.stderr or "")[:500]
                stdout_preview = (result.stdout or "")[:500]
                error_msg = stderr_preview or stdout_preview or f"exit {result.returncode}"
                return PhaseResult(phase_id, PhaseStatus.FAILED,
                                 errors=[f"工具执行失败: {error_msg}"])

        except subprocess.TimeoutExpired:
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=["工具执行超时 (600s)"])
        except Exception as e:
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=[f"工具执行异常: {str(e)}"])

    def _run_validator(self, phase_id: str) -> subprocess.CompletedProcess:
        """运行验证器"""
        defn = self.registry[phase_id]
        validator = defn.get("validator")
        if not validator:
            return subprocess.CompletedProcess([], 0)

        validator_path = Path(__file__).parent.parent / "validators" / validator
        if not validator_path.exists():
            print(f"  ⚠️  验证器不存在: {validator}")
            return subprocess.CompletedProcess([], 1)

        args = self._resolve_args(defn.get("validator_args", []))
        cmd = [sys.executable, str(validator_path)] + args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            return result
        except subprocess.TimeoutExpired:
            print(f"  ⚠️  验证器超时: {validator}")
            return subprocess.CompletedProcess(cmd, 1, "", "timeout")
        except Exception as e:
            print(f"  ⚠️  验证器执行异常: {e}")
            return subprocess.CompletedProcess(cmd, 1, "", str(e))

    def _resolve_args(self, args: list[str]) -> list[str]:
        """解析参数模板"""
        resolved = []
        for arg in args:
            try:
                resolved_arg = arg.format(
                    project_dir=self.project_dir,
                    config_path=self.context.config_path,
                    cookie=self.context.cookie or "",
                    target_url=self.context.target_url or "",
                    excel_path=self.context.excel_path or "",
                    excel_json_path=self.context.excel_json_path or "",
                    module_slug="",  # 多模块时由 _execute_multi_module 处理
                    module_urls_path=self.context.module_urls_path or "",
                    discovery_path=self.context.discovery_path or "",
                )
                resolved.append(resolved_arg)
            except KeyError as e:
                print(f"  ⚠️  参数模板解析失败: {arg}, 缺失变量: {e}")
                resolved.append(arg)
        return resolved

    def _cascade_skip(self, failed_phase: str):
        """阶段失败后，级联跳过所有依赖它的阶段"""
        for phase_id, defn in self.registry.items():
            if failed_phase in defn.get("hard_deps", []):
                if self.results.get(phase_id) is None:
                    self.results[phase_id] = PhaseResult(
                        phase_id, PhaseStatus.SKIPPED,
                        warnings=[f"因 {failed_phase} 失败而跳过"]
                    )
                    print(f"[{phase_id}] {defn['name']} ⏭️  SKIPPED (依赖 {failed_phase})")
                    self._cascade_skip(phase_id)  # 递归

    def _cascade_skip_all_remaining(self, from_phase: str):
        """从指定阶段开始，跳过所有后续阶段"""
        found = False
        for phase_id in EXECUTION_ORDER:
            if phase_id == from_phase:
                found = True
                continue
            if found and self.results.get(phase_id) is None:
                defn = self.registry[phase_id]
                self.results[phase_id] = PhaseResult(
                    phase_id, PhaseStatus.SKIPPED,
                    warnings=[f"因 gate 阶段 {from_phase} 失败而跳过"]
                )
                print(f"[{phase_id}] {defn['name']} ⏭️  SKIPPED (gate 失败)")

    def _save_state(self):
        """保存管线状态到 JSON"""
        state = {
            "run_id": self.start_time.strftime("%Y%m%d_%H%M%S"),
            "started_at": self.start_time.isoformat(),
            "project_dir": self.project_dir,
            "phases": {},
            "final_status": "passed"
        }

        # 记录所有阶段（包括未执行的）
        for phase_id in EXECUTION_ORDER:
            result = self.results.get(phase_id)
            if result:
                state["phases"][phase_id] = {
                    "status": result.status.value,
                    "duration": result.duration_seconds,
                    "errors": result.errors,
                    "warnings": result.warnings,
                }
                if result.status == PhaseStatus.FAILED:
                    state["final_status"] = "failed"
            else:
                state["phases"][phase_id] = {
                    "status": "not_run",
                    "duration": 0,
                    "errors": [],
                    "warnings": [],
                }

        state_path = Path(self.project_dir) / "_probe" / "pipeline_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def _print_summary(self):
        """输出管线总结"""
        passed = sum(1 for r in self.results.values()
                    if r.status == PhaseStatus.PASSED)
        failed = sum(1 for r in self.results.values()
                    if r.status == PhaseStatus.FAILED)
        skipped = sum(1 for r in self.results.values()
                     if r.status == PhaseStatus.SKIPPED)
        total = len(EXECUTION_ORDER)

        duration = (datetime.now() - self.start_time).total_seconds()

        print(f"\n{'='*60}")
        print(f"管线执行完成")
        print(f"{'='*60}")
        print(f"总阶段数: {total}")
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"⏭️  跳过: {skipped}")
        print(f"总耗时: {duration:.1f}s")
        print(f"状态文件: {self.project_dir}/_probe/pipeline_state.json")
        print(f"{'='*60}\n")


def cmd_run(args):
    """执行管线"""
    context = PipelineContext(
        project_dir=args.project,
        excel_path=args.excel,
        cookie=args.cookie
    )

    executor = PipelineExecutor(context)
    executor.run(from_phase=args.from_phase, only_phase=args.only_phase)


def cmd_status(args):
    """查看管线状态"""
    state_path = Path(args.project) / "_probe" / "pipeline_state.json"
    if not state_path.exists():
        print(f"❌ 未找到管线状态文件: {state_path}")
        print("提示: 请先运行 'python pipeline.py run'")
        return

    with open(state_path, 'r', encoding='utf-8') as f:
        state = json.load(f)

    print(f"\n{'='*60}")
    print(f"管线状态")
    print(f"{'='*60}")
    print(f"运行 ID: {state['run_id']}")
    print(f"开始时间: {state['started_at']}")
    print(f"项目目录: {state['project_dir']}")
    print(f"最终状态: {state['final_status']}")
    print(f"\n阶段状态:")

    for phase_id in EXECUTION_ORDER:
        phase_state = state['phases'].get(phase_id, {})
        status = phase_state.get('status', 'not_run')
        duration = phase_state.get('duration', 0)
        icon = {
            "passed": "✅", "failed": "❌", "skipped": "⏭️", "not_run": "⬜"
        }.get(status, "❓")
        defn = get_phase_def(phase_id)
        name = defn.get("name", phase_id)
        print(f"  {icon} {phase_id} ({name}): {status} ({duration:.1f}s)")

        if phase_state.get('errors'):
            for err in phase_state['errors'][:2]:
                print(f"      • {err}")

    print(f"{'='*60}\n")


def cmd_validate_refs(args):
    """验证引用一致性"""
    errors = validate_cross_refs(args.project)

    if errors:
        print(f"\n❌ 引用验证失败: {len(errors)} 个错误")
        sys.exit(1)
    else:
        print(f"\n✅ 引用验证通过")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="统一管线编排器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run 命令
    run_parser = subparsers.add_parser("run", help="执行管线")
    run_parser.add_argument("--project", required=True, help="项目目录")
    run_parser.add_argument("--excel", help="Excel 文件路径")
    run_parser.add_argument("--cookie", help="Cookie 字符串")
    run_parser.add_argument("--from-phase", help="从指定阶段开始 (如 phase_6_verify)")
    run_parser.add_argument("--only-phase", help="仅执行指定阶段及其依赖 (如 phase_4_discovery)")
    run_parser.set_defaults(func=cmd_run)

    # status 命令
    status_parser = subparsers.add_parser("status", help="查看管线状态")
    status_parser.add_argument("--project", required=True, help="项目目录")
    status_parser.set_defaults(func=cmd_status)

    # validate-refs 命令
    refs_parser = subparsers.add_parser("validate-refs", help="验证引用一致性")
    refs_parser.add_argument("--project", required=True, help="项目目录")
    refs_parser.set_defaults(func=cmd_validate_refs)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
