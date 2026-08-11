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
from fixers.cross_refs import validate_cross_refs


class PipelineContext:
    """管线执行上下文，存储阶段间共享数据"""

    def __init__(self, project_dir: str, excel_path: Optional[str] = None,
                 cookie: Optional[str] = None, modules: Optional[list] = None,
                 local_storage: Optional[dict] = None,
                 target_url: Optional[str] = None,
                 browser_type: str = "chromium",
                 run_smoke: bool = False,
                 headed: bool = False):
        self.project_dir = project_dir
        self.excel_path = excel_path
        self.cookie = cookie
        self.local_storage = local_storage or {}
        self.config_path = os.path.join(project_dir, "config.yaml")
        self.excel_json_path = None
        self.module_urls_path = None
        self.target_url = target_url
        self.browser_type = browser_type
        self.run_smoke = run_smoke
        self.headed = headed
        self.modules: list[dict] = modules or []  # [{"slug": "xxx", "cn_name": "xxx", "urls": [...]}]
        self.discovery_path = None  # 当前处理的 discovery 文件路径
        self.module_map_str = ""    # 自动构建的 cn_name=slug 映射（传递给 run_phase4.py）
        self._restored_params = set()  # 从 pipeline_state.json 恢复的参数名

    def update_from_config(self, skip_module_rebuild=False):
        """从 config.yaml 加载配置并构建模块映射

        Args:
            skip_module_rebuild: 恢复模式下为 True，跳过基于 excel_parsed.json 的模块重建
        """
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
                    # 方案2: 保护已恢复的 target_url，不被 config.yaml 覆盖
                    if 'target_url' not in self._restored_params:
                        self.target_url = config.get('target_url')
                    # 方案2: 保护已恢复的 cookie，不被 config.yaml 覆盖
                    if 'cookie' not in self._restored_params:
                        self.cookie = self.cookie or config.get('cookie')

                    # H1: 从 config.yaml 加载 local_storage
                    ls = config.get('local_storage')
                    if ls and isinstance(ls, dict) and not self.local_storage:
                        self.local_storage = ls

                    # 加载模块列表（从 page_urls）
                    page_urls = config.get('page_urls', {})
                    if isinstance(page_urls, dict) and not self.modules:
                        for slug, urls in page_urls.items():
                            cn_name = slug  # 默认用 slug
                            # N3: 归一化 slug（确保一致性）
                            if '-' in slug:
                                slug = slug.replace('-', '_')
                            self.modules.append({
                                "slug": slug,
                                "cn_name": cn_name,
                                "urls": urls if isinstance(urls, list) else [urls],
                            })

        # D 方案: 从 Excel 构建 cn_name → slug 映射
        # 仅在 excel_parsed.json 存在时构建（Phase 1b 完成后）
        # Phase 4 调用时会检查，如映射尚未构建则直接读取原始 Excel 作为 fallback
        # 方案1: 恢复模式下跳过，避免基于陈旧的 excel_parsed.json 重建模块映射
        if not skip_module_rebuild and not self.module_map_str and self.excel_json_path:
            self._build_module_aliases()

    def _build_module_aliases(self):
        """从 excel_parsed.json + page_urls 自动构建 cn_name→slug 映射。

        匹配策略：提取每个 sheet 中用例步骤的 URL，与 page_urls 的 URL 列表交叉比对，
        将中文模块名关联到英文 slug。

        结果存入 self.module_map_str，格式 "中文名=slug,中文名=slug"，
        在 Phase 4 时自动注入 --module-map 参数。

        如果 excel_parsed.json 不存在，直接读取原始 Excel 文件。
        """
        # 从 config.yaml page_urls 构建 slug → set(urls)
        slug_urls = {}
        for mod_info in self.modules:
            slug = mod_info.get("slug", "")
            urls = mod_info.get("urls", [])
            if slug and urls:
                slug_urls[slug] = {self._normalize_url(u) for u in urls}

        if not slug_urls:
            return

        # 尝试从 excel_parsed.json 读取（优先）
        excel_data = None
        if self.excel_json_path and Path(self.excel_json_path).is_file():
            try:
                with open(self.excel_json_path, encoding='utf-8') as f:
                    excel_data = json.load(f)
                if not isinstance(excel_data, list):
                    excel_data = None
            except Exception:
                excel_data = None

        # 如果没有 excel_parsed.json，直接读取 Excel 文件
        if excel_data is None and self.excel_path and Path(self.excel_path).is_file():
            try:
                import openpyxl
                import re
                wb = openpyxl.load_workbook(self.excel_path, read_only=True, data_only=True)
                excel_data = []
                for ws in wb.worksheets:
                    rows = list(ws.iter_rows(values_only=True))
                    if not rows:
                        continue

                    headers = [str(h).strip() if h else "" for h in rows[0]]
                    # 查找列索引（兼容各种列名变体，忽略尾部 * 标记）
                    module_idx = None
                    steps_idx = None

                    for idx, h in enumerate(headers):
                        # 去掉尾部 * 和空格后匹配
                        clean_h = re.sub(r'[\s*]+$', '', h)
                        if clean_h in ["模块", "功能模块", "所属模块"]:
                            module_idx = idx
                        elif clean_h in ["用例步骤", "测试步骤", "步骤描述",
                                         "测试用例内容", "用例内容"]:
                            steps_idx = idx

                    if module_idx is None or steps_idx is None:
                        continue

                    sheet_data = {
                        "sheet": ws.title,
                        "cases": []
                    }

                    for row in rows[1:]:
                        if len(row) <= max(module_idx, steps_idx):
                            continue

                        module = str(row[module_idx]).strip() if row[module_idx] else ""
                        steps_text = str(row[steps_idx]).strip() if row[steps_idx] else ""

                        if not module or not steps_text:
                            continue

                        # 解析步骤（按换行符分割）
                        steps = []
                        for step_line in steps_text.split("\n"):
                            step_line = step_line.strip()
                            if step_line:
                                steps.append(step_line)

                        sheet_data["cases"].append({
                            "module": module,
                            "case_name": module,  # 只需要 module 字段
                            "steps": steps
                        })

                    if sheet_data["cases"]:
                        excel_data.append(sheet_data)

                wb.close()
                print(f"  ✅ 直接读取 Excel: {len(excel_data)} 个 sheet")
            except Exception as e:
                print(f"  ⚠️  直接读取 Excel 文件失败：{e}")
                excel_data = None

        if not excel_data:
            return

        # 遍历 Excel 每个 sheet 的用例，收集 cn_name → set(urls)
        cn_name_urls = {}
        for sheet in excel_data:
            if not isinstance(sheet, dict):
                continue
            cases = sheet.get("cases", [])
            for case in cases:
                if not isinstance(case, dict):
                    continue
                cn_name = case.get("module", "").strip()
                if not cn_name:
                    continue
                if cn_name not in cn_name_urls:
                    cn_name_urls[cn_name] = set()
                for step in case.get("steps", []):
                    if isinstance(step, str):
                        # 提取步骤中的 URL（完整URL或/开头的相对路径）
                        base_url = self.target_url or ''
                        for part in step.split():
                            if part.startswith("http://") or part.startswith("https://"):
                                cn_name_urls[cn_name].add(self._normalize_url(part))
                            elif part.startswith("/"):
                                resolved = self._resolve_step_url(part, base_url)
                                cn_name_urls[cn_name].add(self._normalize_url(resolved))

        if not cn_name_urls:
            return

        # 交叉匹配：cn_name 的 URL 集合与 slug 的 URL 集合有交集 → 匹配
        aliases = {}
        for cn_name, cn_urls in cn_name_urls.items():
            if not cn_urls:
                continue
            for slug, s_urls in slug_urls.items():
                if cn_urls & s_urls:
                    aliases[cn_name] = slug
                    break

        if aliases:
            self.module_map_str = ",".join(f"{cn}={slug}" for cn, slug in aliases.items())
            print(f"  ✅ 自动构建 module_map: {self.module_map_str}")

    @staticmethod
    def _normalize_url(url):
        """URL 标准化（保留 hash 路径，忽略 query/fragment）用于匹配。

        对于 hash-based routing 的 SPA（如 http://host/#/path），
        hash 部分是路由路径，必须保留。只忽略 query string 和 fragment。
        """
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url.strip())
            # 返回 scheme + netloc + path + fragment（hash 路由路径）
            # 例如 http://host/#/question-manage/list → http://host/#/question-manage/list
            result = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.fragment:
                result += f"#{parsed.fragment}"
            return result
        except Exception:
            return url.strip()

    @staticmethod
    def _resolve_step_url(raw_url: str, base_url: str) -> str:
        """将步骤中提取到的 URL 规范化为完整 URL。

        - 完整 URL（http/https 开头）→ 原样返回
        - 相对路径（/ 开头）→ 与 base_url 拼接
        - base_url 为空时 → 原样返回（不做无效拼接）
        """
        raw_url = raw_url.strip()
        if raw_url.startswith(('http://', 'https://')):
            return raw_url
        if raw_url.startswith('/') and base_url:
            return f"{base_url.rstrip('/')}{raw_url}"
        return raw_url

    def get_modules(self) -> list[dict]:
        """获取模块列表"""
        if self.modules:
            return self.modules

        # 从 _probe/ 目录推断模块
        probe_dir = Path(self.project_dir) / "_probe"
        if probe_dir.exists():
            for f in probe_dir.glob("discovery_*.json"):
                slug = f.stem.replace("discovery_", "")
                # N1: 过滤 merged 文件，N3: 归一化 slug 为下划线格式
                if slug.endswith("_merged"):
                    continue
                slug = slug.replace('-', '_')
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

        # 清理旧的 pipeline_state.json（避免子进程工具读取过期状态）
        if not from_phase and not only_phase:
            old_state = Path(self.project_dir) / "_probe" / "pipeline_state.json"
            if old_state.exists():
                try:
                    old_state.unlink()
                    print(f"  ✅ 已清理旧的管线状态文件")
                except Exception as e:
                    print(f"  ⚠️  清理旧状态文件失败: {e}")

        # --from-phase 恢复：从上次状态补全缺失的 CLI 参数
        if from_phase or only_phase:
            state_file = Path(self.project_dir) / "_probe" / "pipeline_state.json"
            if state_file.exists():
                try:
                    with open(state_file, 'r', encoding='utf-8') as f:
                        prev_state = json.load(f)
                    prev_params = prev_state.get('cli_params', {})
                    if not self.context.excel_path and prev_params.get('excel_path'):
                        self.context.excel_path = prev_params['excel_path']
                        self.context._restored_params.add('excel_path')
                        print(f"  [恢复] excel_path = {self.context.excel_path}")
                    if not self.context.cookie and prev_params.get('cookie'):
                        self.context.cookie = prev_params['cookie']
                        self.context._restored_params.add('cookie')
                        print(f"  [恢复] cookie = (已加载)")
                    if not self.context.target_url and prev_params.get('target_url'):
                        self.context.target_url = prev_params['target_url']
                        self.context._restored_params.add('target_url')
                        print(f"  [恢复] target_url = {self.context.target_url}")
                except Exception as e:
                    print(f"  ⚠️  恢复 CLI 参数失败: {e}")

        # 加载配置 - 恢复模式下跳过模块映射重建，避免基于陈旧的 excel_parsed.json 污染
        is_resume = bool(from_phase or only_phase)
        self.context.update_from_config(skip_module_rebuild=is_resume)

        # --from-phase / --only-phase: 别名映射（用户可能用短名 phase_6 → phase_6_verify）
        PHASE_ALIASES = {
            "phase_1b": "phase_1b_parse",
            "phase_3": "phase_3_keywords",
            "phase_4": "phase_4_discovery",
            "phase_6": "phase_6_verify",
        }
        if from_phase:
            from_phase = PHASE_ALIASES.get(from_phase, from_phase)
            if from_phase not in EXECUTION_ORDER:
                print(f"  ❌ 错误: 未知的阶段名 '{from_phase}'")
                print(f"     可选: {', '.join(EXECUTION_ORDER)}")
                return
        if only_phase:
            only_phase = PHASE_ALIASES.get(only_phase, only_phase)
            if only_phase not in EXECUTION_ORDER:
                print(f"  ❌ 错误: 未知的阶段名 '{only_phase}'")
                print(f"     可选: {', '.join(EXECUTION_ORDER)}")
                return

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

        # === Resume 模式预处理：上游产物已存在则标记 SKIPPED ===
        target_phase = from_phase or only_phase
        if is_resume and target_phase:
            for phase_id in EXECUTION_ORDER:
                if phase_id == target_phase:
                    break  # 目标 phase 本身不跳过

                # 只处理在 run_phases 中的阶段
                if only_phase and phase_id not in run_phases:
                    continue
                if from_phase and phase_id in skip_phases:
                    continue

                # Phase 0 始终执行（便宜 + 验证 config + 检测 cookie）
                if phase_id == "phase_0":
                    continue

                defn = self.registry[phase_id]

                # 可选阶段且条件不满足 → 直接跳过
                if defn.get("optional") and defn.get("condition"):
                    if not defn["condition"](self.context):
                        self.results[phase_id] = PhaseResult(
                            phase_id, PhaseStatus.SKIPPED,
                            warnings=["条件不满足，跳过"]
                        )
                        print(f"  [跳过] {phase_id} {defn['name']} — 条件不满足")
                        continue

                # 检查产物是否存在
                if self._artifacts_exist(phase_id):
                    # Phase 4 multi_module 额外校验：glob 匹配数 ≥ 模块数
                    if phase_id == "phase_4_discovery" and defn.get("multi_module"):
                        modules = self.context.get_modules()
                        if modules:
                            discovery_pattern = str(Path(self.project_dir) / "_probe" / "discovery_*.json")
                            matches = glob.glob(discovery_pattern)
                            matches = [m for m in matches if not m.endswith("_merged.json")]
                            if len(matches) < len(modules):
                                print(f"  [重跑] {phase_id} {defn['name']} — 产物不完整 ({len(matches)}/{len(modules)} 模块)")
                                continue  # 不跳过，继续执行

                    # 标记为 SKIPPED，_check_hard_deps 会验证产物
                    self.results[phase_id] = PhaseResult(
                        phase_id, PhaseStatus.SKIPPED,
                        warnings=["Resume 模式：产物已存在，跳过"]
                    )
                    print(f"  [跳过] {phase_id} {defn['name']} — 产物已存在")

        # 预计算将执行的阶段列表（用于进度显示）— 移到预处理之后
        _planned_phases = [
            pid for pid in EXECUTION_ORDER
            if pid not in skip_phases
            and (not only_phase or pid in run_phases)
            and pid not in self.results
        ]
        _total_planned = len(_planned_phases)
        _phase_counter = 0

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

            _phase_counter += 1
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

            # 检查软依赖（仅警告，不阻断）
            soft_deps = defn.get("soft_deps", [])
            for soft_dep in soft_deps:
                soft_result = self.results.get(soft_dep)
                if soft_result and soft_result.status == PhaseStatus.FAILED:
                    print(f"  ⚠️  软依赖 {soft_dep} 失败，继续执行但功能可能不完整")

            # 执行 pre_hook（如果有）
            pre_hook = defn.get("pre_hook")
            if pre_hook == "validate_cross_refs":
                print(f"[{phase_id}] 执行 pre_hook: validate_cross_refs")
                result = validate_cross_refs(self.project_dir)
                errors = result.get("errors", []) if isinstance(result, dict) else result
                warnings = result.get("warnings", []) if isinstance(result, dict) else []

                if errors:
                    # cross_refs errors 降级为 warnings，不阻断 Phase 6
                    for err in errors:
                        warnings.append(err)
                    print(f"  ⚠️  引用验证发现 {len(errors)} 个问题（降级为警告，不阻断）")
                    for err in errors[:5]:
                        print(f"    • {err}")
                elif warnings:
                    print(f"  ⚠️  {len(warnings)} 个警告，继续执行")

            # 运行阶段 - 醒目的阶段开始日志
            print(f"\n{'─'*70}")
            print(f"📌 阶段 {_phase_counter}/{_total_planned}  [{phase_id}] {defn['name']}")
            print(f"{'─'*70}")
            print(f"🔄 RUNNING...")
            try:
                result = self._execute_phase(phase_id)
            except Exception as e:
                result = PhaseResult(
                    phase_id, PhaseStatus.FAILED,
                    errors=[f"阶段执行异常: {e}"]
                )
                print(f"  ❌ 未捕获异常: {e}")
            self.results[phase_id] = result

            # X-1 修复: phase_1b_parse 成功后刷新 context，使 excel_json_path 可用
            if phase_id == "phase_1b_parse" and result.status == PhaseStatus.PASSED:
                self.context.update_from_config()
                print(f"  ✅ excel_json_path 已刷新: {self.context.excel_json_path}")
                # D方案: Phase 1b 完成后构建 module_map_str
                if not self.context.module_map_str:
                    self.context._build_module_aliases()
                    if self.context.module_map_str:
                        print(f"  ✅ module_map_str 已构建: {self.context.module_map_str}")

                # 新增: 从 excel_parsed.json 提取 URLs 并填充 page_urls 到 config.yaml
                if self.context.excel_json_path and Path(self.context.excel_json_path).exists():
                    try:
                        with open(self.context.excel_json_path, 'r', encoding='utf-8') as f:
                            excel_data = json.load(f)

                        # 按模块收集 URLs
                        module_urls = {}
                        if isinstance(excel_data, list):
                            for sheet in excel_data:
                                if not isinstance(sheet, dict):
                                    continue
                                cases = sheet.get("cases", [])
                                for case in cases:
                                    if not isinstance(case, dict):
                                        continue
                                    module = case.get("module", "").strip()
                                    if not module:
                                        continue
                                    if module not in module_urls:
                                        module_urls[module] = set()
                                    # 从步骤中提取 URLs（完整URL或/开头的相对路径）
                                    base_url = self.context.target_url or ''
                                    for step in case.get("steps", []):
                                        if isinstance(step, str):
                                            for part in step.split():
                                                if part.startswith("http://") or part.startswith("https://"):
                                                    normalized = self.context._normalize_url(part)
                                                    module_urls[module].add(normalized)
                                                elif part.startswith("/"):
                                                    resolved = self.context._resolve_step_url(part, base_url)
                                                    normalized = self.context._normalize_url(resolved)
                                                    module_urls[module].add(normalized)

                        if module_urls:
                            # 更新 config.yaml
                            config_path = Path(self.project_dir) / "config.yaml"
                            if config_path.exists():
                                import yaml
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = yaml.safe_load(f) or {}

                                # 从 URL 路径提取英文 slug（避免中文目录名）
                                import sys as _sys
                                _tools_dir = Path(__file__).parent
                                if str(_tools_dir) not in _sys.path:
                                    _sys.path.insert(0, str(_tools_dir))
                                from excel.build_module_map import _extract_slug_from_url, _auto_generate_slug

                                cn_to_slug = {}
                                for cn_name, urls in module_urls.items():
                                    # 构建 module_urls.json 格式供 _extract_slug_from_url 使用
                                    module_urls_json = {cn_name: {'urls': list(urls)}}
                                    slug = _extract_slug_from_url(cn_name, module_urls_json)
                                    if not slug:
                                        slug = _auto_generate_slug(cn_name)
                                    cn_to_slug[cn_name] = slug

                                # 合并 page_urls（保留已有配置，使用英文 slug 作为 key）
                                if 'page_urls' not in config:
                                    config['page_urls'] = {}
                                for cn_name, urls in module_urls.items():
                                    slug = cn_to_slug[cn_name]
                                    if slug not in config['page_urls']:
                                        config['page_urls'][slug] = sorted(list(urls))
                                        if cn_name != slug:
                                            print(f"  [SLUG] {cn_name} → {slug}")

                                # 写回 config.yaml
                                with open(config_path, 'w', encoding='utf-8') as f:
                                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

                                # 刷新 context.modules
                                self.context.update_from_config()
                                print(f"  ✅ page_urls 已填充: {len(module_urls)} 个模块")
                    except Exception as e:
                        print(f"  ⚠️  page_urls 自动填充失败: {e}")

            # BUG-8 fix: Phase 1 完成后检测修正版 Excel 并更新路径
            if phase_id == "phase_1" and result.status == PhaseStatus.PASSED:
                if self.context.excel_path:
                    orig = Path(self.context.excel_path)
                    corrected = orig.parent / f"{orig.stem}-修正版.xlsx"
                    if corrected.exists():
                        self.context.excel_path = str(corrected)
                        print(f"  ✅ excel_path 已更新为修正版: {corrected}")

            # Phase 1 FAILED + AI rewrite: 检查 unknown_steps.json，提示 Claude 重写
            if phase_id == "phase_1" and result.status == PhaseStatus.FAILED:
                unknown_path = Path(self.project_dir) / "_probe" / "unknown_steps.json"
                rewrites_path = Path(self.project_dir) / "_probe" / "step_rewrites.json"
                if unknown_path.exists():
                    print(f"\n{'='*70}")
                    print(f"📋 Phase 1 AI 重写流程")
                    print(f"{'='*70}")
                    print(f"1. 读取 {unknown_path} 中的无法匹配步骤")
                    print(f"2. 基于 63 个标准模式重写每个步骤")
                    print(f"3. 创建 {rewrites_path}，格式:")
                    print(f'   {{"key": "重写后的标准步骤描述", ...}}')
                    print(f"4. 重新运行 Phase 1:")
                    print(f"   python pipeline.py run --project {self.project_dir} --only-phase phase_1")
                    print(f"{'='*70}\n")

            # X-3 修复: phase_4 成功后填充 module_urls_path
            if phase_id == "phase_4_discovery" and result.status == PhaseStatus.PASSED:
                mu_path = Path(self.project_dir) / "_probe" / "module_urls.json"
                if mu_path.exists():
                    self.context.module_urls_path = str(mu_path)

            # 运行验证器（仅当阶段通过且有验证器时）
            if result.status == PhaseStatus.PASSED and defn.get("validator"):
                val_result = self._run_validator(phase_id)
                if val_result.returncode != 0:
                    result.status = PhaseStatus.FAILED
                    # 优先读取 stderr，fallback 到 stdout（validator 通常用 print 输出到 stdout）
                    error_output = val_result.stderr or val_result.stdout or ""
                    error_preview = error_output[:500]
                    result.errors.append(
                        f"验证器 {defn['validator']} 失败 (exit {val_result.returncode})"
                    )
                    if error_preview:
                        result.errors.append(f"验证器输出: {error_preview}")

            # 输出结果
            if result.status == PhaseStatus.PASSED:
                print(f"✅ 完成 {_phase_counter}/{_total_planned} - {defn['name']} ({result.duration_seconds:.1f}s)")
                if result.warnings:
                    for w in result.warnings[:3]:
                        print(f"  ⚠️  {w}")
                # 增量保存状态（供子进程工具读取）
                self._save_state(is_intermediate=True)

            elif result.status == PhaseStatus.FAILED:
                print(f"❌ 失败 {_phase_counter}/{_total_planned} - {defn['name']}")
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

        checked = 0
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

            checked += 1
            # 处理通配符
            if "*" in pattern:
                matches = glob.glob(pattern)
                if not matches:
                    return False
            else:
                if not Path(pattern).exists():
                    return False

        # 如果所有模式都因变量缺失被跳过，保守返回 False
        return checked > 0

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
        """Phase 0: 配置确认

        验证已存在的 config.yaml，或等待 Phase 2 生成。
        额外职责：自动补全 cookie_domain（从 target_url 提取），
        确保运行时 base_browser._apply_config_cookies 能正确注入 HTTP Cookie。
        """
        import re as _re
        config_path = Path(self.project_dir) / "config.yaml"

        if not config_path.exists():
            # ── 混合模式：CLI 参数完整时程序化渲染模板 ──
            has_minimal_params = (
                self.context.target_url and
                (self.context.cookie or self.context.local_storage)
            )

            if not has_minimal_params:
                return PhaseResult("phase_0", PhaseStatus.FAILED,
                                 errors=["config.yaml 不存在",
                                        "请通过 CLI 参数提供 --target-url 和 --cookie/--local-storage，",
                                        "或手动创建 config.yaml（参考 templates/config.yaml.tpl）"])

            templates_dir = Path(__file__).parent.parent / "templates"
            tpl_path = templates_dir / "config.yaml.tpl"
            if not tpl_path.exists():
                return PhaseResult("phase_0", PhaseStatus.FAILED,
                                 errors=[f"模板文件不存在: {tpl_path}"])

            content = tpl_path.read_text(encoding='utf-8')

            # 规范化换行符为 \n（修复 CRLF 问题）
            content = content.replace('\r\n', '\n').replace('\r', '\n')

            # 1) 基础变量替换（带 None 防护）
            target_url = self.context.target_url or ""
            content = content.replace("{{browser_type}}", "chromium")
            content = content.replace("{{target_url}}", target_url)
            content = content.replace("{{project_name}}", Path(self.project_dir).name)

            # 2) Cookie 认证条件块
            if self.context.cookie:
                content = content.replace("{{#if cookie_auth}}", "")
                # YAML 转义：反斜杠和双引号
                cookie_escaped = self.context.cookie.replace('\\', '\\\\').replace('"', '\\"')
                content = content.replace("{{cookie_string}}", cookie_escaped)
                from urllib.parse import urlparse as _urlparse
                domain = _urlparse(target_url).hostname or ""
                content = content.replace("{{cookie_domain}}", domain)
            else:
                content = _re.sub(
                    r'\{\{#if cookie_auth\}\}.*?\{\{/if\}\}', '', content, flags=_re.DOTALL
                )

            # 3) localStorage 条件块
            if self.context.local_storage:
                content = content.replace("{{#if local_storage}}", "")
                ls_items = []
                for k, v in self.context.local_storage.items():
                    # YAML 转义键和值
                    k_escaped = str(k).replace('\\', '\\\\').replace('"', '\\"')
                    v_escaped = str(v).replace('\\', '\\\\').replace('"', '\\"')
                    ls_items.append(f'  {k_escaped}: "{v_escaped}"')
                ls_str = "\n".join(ls_items)
                content = content.replace(
                    "{{#each local_storage_items}}\n  {{key}}: \"{{value}}\"\n{{/each}}",
                    ls_str
                )
            else:
                content = _re.sub(
                    r'\{\{#if local_storage\}\}.*?\{\{/if\}\}', '', content, flags=_re.DOTALL
                )

            # 4) 清理残留的 {{/if}} 标记（Cookie 块内的）
            content = content.replace("{{/if}}", "")

            # 5) 注入 page_urls（从 Excel 解析结果或 target_url 推断）
            # 注意：page_urls 在 Phase 1b 完成后由管线自动处理
            # 此处仅注入基础结构，后续阶段会补充完整
            if not _re.search(r'^page_urls:\s*$', content, _re.MULTILINE):
                # 在文件末尾添加 page_urls 占位
                content += "\n# page_urls 将由管线在 Phase 1b 后自动填充\n"
                content += "page_urls: {}\n"

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(content, encoding='utf-8')
            print(f"  [Phase 0] 从模板自动生成 config.yaml（CLI 参数模式）")

        # 增量场景：config.yaml 已存在但 CLI 传入了新 cookie，更新之
        if config_path.exists() and self.context.cookie:
            try:
                import yaml as _yaml_inc
                with open(config_path, 'r', encoding='utf-8') as f:
                    _cfg_inc = _yaml_inc.safe_load(f) or {}
                _old_cookie = _cfg_inc.get('cookie', '')
                if _old_cookie != self.context.cookie:
                    _cfg_inc['cookie'] = self.context.cookie
                    # 同步更新 cookie_domain
                    from urllib.parse import urlparse as _urlparse_inc
                    _target_inc = _cfg_inc.get('target_url', self.context.target_url or '')
                    _domain_inc = _urlparse_inc(_target_inc).hostname or ''
                    if _domain_inc and not _cfg_inc.get('cookie_domain'):
                        _cfg_inc['cookie_domain'] = _domain_inc
                    with open(config_path, 'w', encoding='utf-8') as f:
                        _yaml_inc.dump(_cfg_inc, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                    print(f"  [Phase 0] 增量更新 cookie")
            except Exception as e:
                print(f"  [Phase 0] cookie 增量更新失败（不影响验证）: {e}")

        # 自动补全 cookie_domain（从 target_url 提取）
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            if cfg.get('cookie') and not cfg.get('cookie_domain') and not cfg.get('host'):
                from urllib.parse import urlparse
                target = cfg.get('target_url', '')
                if target:
                    domain = urlparse(target).hostname
                    if domain:
                        # 逐行追加，保留原始注释和格式
                        with open(config_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        lines.append(f'\ncookie_domain: "{domain}"\n')
                        with open(config_path, 'w', encoding='utf-8') as f:
                            f.writelines(lines)
                        print(f"  [Phase 0] 自动补全 cookie_domain: {domain}")
        except Exception as e:
            # 补全失败不阻断（仅警告）
            print(f"  [Phase 0] cookie_domain 自动补全失败（不影响验证）: {e}")

        # 运行验证器
        val_result = self._run_validator("phase_0")
        if val_result.returncode != 0:
            # 优先读取 stderr，fallback 到 stdout（validator 通常用 print 输出到 stdout）
            error_output = val_result.stderr or val_result.stdout or ""
            error_preview = error_output[:500]
            return PhaseResult("phase_0", PhaseStatus.FAILED,
                             errors=["配置验证失败", error_preview])

        return PhaseResult("phase_0", PhaseStatus.PASSED)

    def _phase2_scaffold(self) -> PhaseResult:
        """Phase 2: 脚手架生成（支持全新项目和增量场景）"""
        project_path = Path(self.project_dir)
        templates_dir = Path(__file__).parent.parent / "templates"

        # 检查模板目录
        if not templates_dir.exists():
            return PhaseResult("phase_2", PhaseStatus.FAILED,
                             errors=[f"模板目录不存在: {templates_dir}"])

        errors = []
        is_incremental = (project_path / "run.py").exists()
        new_modules = []

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
            dir_path = project_path / d
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                # 增量场景：记录新增的模块目录
                if is_incremental and any(f"/{module}" in d for module in modules if module != "common"):
                    module_name = d.split("/")[-1]
                    if module_name not in new_modules:
                        new_modules.append(module_name)

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
                continue  # 增量场景：已存在的文件跳过

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

        # 增量场景：记录新增模块
        if is_incremental and new_modules:
            print(f"  [Phase 2] 增量场景：新增模块目录 {', '.join(new_modules)}")

        return PhaseResult("phase_2", PhaseStatus.PASSED,
                         warnings=[f"模块: {', '.join(modules)}"])

    def _phase8_validate_and_report(self) -> PhaseResult:
        """Phase 8: 跨文件验证 + 问题报告生成"""
        errors = []

        # 1. 运行 validate_08_scripts.py
        val_result = self._run_validator("phase_8")
        if val_result.returncode != 0:
            stderr_preview = (val_result.stderr or "")[:300]
            errors.append(f"validate_08_scripts.py 失败 (exit {val_result.returncode})")
            if stderr_preview:
                errors.append(f"验证器输出: {stderr_preview}")

        # 2. 先生成报告（验证前必须有报告）
        report_generator = Path(__file__).parent / "generators/generate_report.py"
        if report_generator.exists():
            output_path = Path(self.project_dir) / "report/generate_report/generation_report.html"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                result = subprocess.run(
                    [sys.executable, str(report_generator), self.project_dir, str(output_path)],
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120
                )
                if result.returncode != 0:
                    errors.append(f"generate_report.py 失败 (exit {result.returncode})")
                else:
                    print(f"  ✅ 报告已生成: {output_path.relative_to(Path(self.project_dir))}")
            except subprocess.TimeoutExpired:
                errors.append("generate_report.py 超时")

        # 3. 运行 validate_09_report.py（验证生成的报告）
        report_validator = Path(__file__).parent.parent / "validators" / "validate_09_report.py"
        if report_validator.exists():
            result = subprocess.run(
                [sys.executable, str(report_validator), self.project_dir],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120
            )
            if result.returncode != 0:
                errors.append("validate_09_report.py 失败")

        # 4. 生成 issues_report（如果存在）
        issues_generator = Path(__file__).parent / "generators/generate_issues_report.py"
        if issues_generator.exists():
            try:
                result = subprocess.run(
                    [sys.executable, str(issues_generator), self.project_dir],
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120
                )
                if result.returncode != 0:
                    errors.append("generate_issues_report.py 失败")
            except subprocess.TimeoutExpired:
                errors.append("generate_issues_report.py 超时")

        if errors:
            return PhaseResult("phase_8", PhaseStatus.FAILED, errors=errors)

        return PhaseResult("phase_8", PhaseStatus.PASSED)

    def _phase9_execution(self) -> PhaseResult:
        """Phase 9: 执行测试脚本"""
        run_py = Path(self.project_dir) / "run.py"
        if not run_py.exists():
            return PhaseResult("phase_9", PhaseStatus.FAILED,
                             errors=["run.py 不存在"])

        print(f"  [Phase 9] 执行测试脚本: {run_py}")
        try:
            result = subprocess.run(
                [sys.executable, str(run_py)],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=3600  # 测试运行可能需要较长时间
            )

            if result.returncode == 0:
                print(f"  ✅ 测试执行成功")
                return PhaseResult("phase_9", PhaseStatus.PASSED)
            else:
                # 测试失败不一定是错误，可能只是部分用例失败
                stdout_preview = (result.stdout or "")[-500:]
                stderr_preview = (result.stderr or "")[-500:]
                print(f"  ⚠️  测试执行完成，退出码: {result.returncode}")
                if stdout_preview:
                    print(f"  输出预览: {stdout_preview[:200]}...")
                # 测试失败不阻断管线，记录为警告
                return PhaseResult("phase_9", PhaseStatus.PASSED,
                                 warnings=[f"测试执行完成，退出码: {result.returncode}"])

        except subprocess.TimeoutExpired:
            print(f"  ⚠️  测试执行超时 (3600s)")
            return PhaseResult("phase_9", PhaseStatus.PASSED,
                             warnings=["测试执行超时"])
        except Exception as e:
            print(f"  ⚠️  测试执行异常: {e}")
            return PhaseResult("phase_9", PhaseStatus.PASSED,
                             warnings=[f"测试执行异常: {e}"])

    def _execute_multi_module(self, phase_id: str, tool: str,
                              args: list[str]) -> PhaseResult:
        """多模块执行（Phase 4/6）— 逐模块运行，Cookie 失败全局阻断"""
        defn = self.registry[phase_id]
        modules = self.context.get_modules()

        if not modules:
            if defn.get("tolerate_tool_failure"):
                # Phase 6: 无模块也降级为 warning，不阻断管线
                print(f"  ⚠️  无模块可处理（不阻断）")
                return PhaseResult(phase_id, PhaseStatus.PASSED,
                                 warnings=["无模块可处理，跳过验证"])
            else:
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

            # BUG-7 fix: Phase 6 需要 --discovery 参数（直接追加，不用字符串替换）
            if phase_id == "phase_6_verify":
                # N2: 优先使用 merged 版本（与 Phase 5 保持一致）
                discovery_file_merged = Path(self.project_dir) / "_probe" / f"discovery_{slug}_merged.json"
                discovery_file = Path(self.project_dir) / "_probe" / f"discovery_{slug}.json"
                if discovery_file_merged.exists():
                    self.context.discovery_path = str(discovery_file_merged)
                    module_args.extend(["--discovery", str(discovery_file_merged)])
                elif discovery_file.exists():
                    self.context.discovery_path = str(discovery_file)
                    module_args.extend(["--discovery", str(discovery_file)])

                # R6: 传递 AI probe 配置到 verify_locators.py
                config_path = Path(self.project_dir) / 'config.yaml'
                if config_path.exists():
                    try:
                        config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
                        ai_probe_cfg = config.get('ai_probe')
                        if ai_probe_cfg and ai_probe_cfg.get('enabled'):
                            module_args.extend(['--ai-probe', json.dumps(ai_probe_cfg)])
                    except Exception:
                        pass  # 配置读取失败不影响主线

                # --headed 透传到 verify_orchestrator.py
                if self.context.headed:
                    module_args.append('--headed')

            # D方案: Phase 4 自动注入 --module-map（解决新项目中文模块名→slug 映射问题）
            if phase_id == "phase_4_discovery" and self.context.module_map_str:
                module_args.extend(["--module-map", self.context.module_map_str])

            result = self._run_tool(phase_id, tool, module_args, module_slug=slug)

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

                elif defn.get("tolerate_tool_failure"):
                    # Phase 6: 工具失败降级为 warning，不阻断管线
                    print(f"  [{slug}] ⚠️  验证有未解析项（不阻断）")
                    all_warnings.extend([f"[{slug}] 验证有未解析定位器（不阻断）"])
                else:
                    # 其他阶段：保持原有行为
                    all_errors.extend([f"[{slug}] {e}" for e in result.errors])
                    print(f"  [{slug}] ❌ FAILED")
            else:
                print(f"  [{slug}] ✅ PASSED")
                all_warnings.extend([f"[{slug}] {w}" for w in result.warnings])

        # ── Phase 4 零元素守卫：防止空探测数据覆盖现有产物 ──
        if phase_id == "phase_4_discovery" and not all_errors:
            total_elements = 0
            _disc_sections = ('buttons', 'row_buttons', 'inputs', 'tabs',
                             'detail_links', 'checkboxes', 'menu_items')
            for module_info in modules:
                slug = module_info["slug"]
                disc_file = Path(self.project_dir) / "_probe" / f"discovery_{slug}.json"
                if not disc_file.exists():
                    merged = Path(self.project_dir) / "_probe" / f"discovery_{slug}_merged.json"
                    disc_file = merged if merged.exists() else None
                if disc_file and disc_file.exists():
                    try:
                        with open(disc_file, encoding='utf-8') as f:
                            disc = json.load(f)
                        if 'pages' in disc:
                            for p in disc['pages']:
                                for c in p.get('containers', []):
                                    total_elements += len(c.get('elements', []))
                                for cat in _disc_sections:
                                    total_elements += len(p.get('list_page', {}).get(cat, []))
                        else:
                            for c in disc.get('containers', []):
                                total_elements += len(c.get('elements', []))
                            for cat in _disc_sections:
                                total_elements += len(disc.get('list_page', {}).get(cat, []))
                    except Exception:
                        pass

            if total_elements == 0:
                return PhaseResult(
                    phase_id, PhaseStatus.FAILED,
                    errors=[f"探测到 0 个元素（共 {len(modules)} 个模块），"
                            f"可能是 Cookie 过期，请更新 config.yaml 中的 cookie 后使用 --from-phase phase_4_discovery 重新运行"],
                    warnings=all_warnings,
                )

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

    def _run_tool(self, phase_id: str, tool: str, args: list[str],
                   module_slug: str | None = None) -> PhaseResult:
        """运行外部工具（实时流式输出到控制台）

        使用 Popen 逐行读取子进程 stdout/stderr，同时：
        1. 打印到控制台（用户可见每个阶段的进度）
        2. 缓存到内存（失败时提取错误尾部）
        3. 写入 _probe/{phase_id}_tool.log（完整日志归档）
        """
        tool_path = Path(__file__).parent / tool
        if not tool_path.exists():
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=[f"工具不存在: {tool_path}"])

        # Phase 4/6 涉及浏览器操作，允许更长超时
        _LONG_TIMEOUT_PHASES = {'phase_4_discovery', 'phase_6_verify'}
        timeout = 3600 if phase_id in _LONG_TIMEOUT_PHASES else 600

        cmd = [sys.executable, str(tool_path)] + args

        # Force UTF-8 for all tool subprocesses (fixes Windows GBK issues)
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout，统一流式输出
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
            )

            # 实时流式读取：逐行打印到控制台 + 缓存
            stdout_lines = []
            start_ts = time.time()
            for line in proc.stdout:
                # 超时检查（每行读取时判断，避免无输出时卡死）
                if time.time() - start_ts > timeout:
                    proc.kill()
                    return PhaseResult(phase_id, PhaseStatus.FAILED,
                                     errors=[f"工具执行超时 ({timeout}s)"])
                # 去掉尾部换行，统一格式
                stripped = line.rstrip('\n').rstrip('\r')
                stdout_lines.append(stripped)
                # 实时输出到控制台（带阶段前缀，便于区分）
                print(f"  │ {stripped}")

            proc.wait(timeout=30)  # 等待进程结束（输出已读完，通常很快）
            returncode = proc.returncode

            # 将完整输出写入日志文件
            full_stdout = '\n'.join(stdout_lines)
            self._save_tool_log(phase_id, tool, module_slug, full_stdout, '')

            if returncode == 0:
                return PhaseResult(phase_id, PhaseStatus.PASSED)
            elif returncode == 2:
                # exit(2) = auth 失效（verify_orchestrator.py 专用），管线应阻断
                return PhaseResult(phase_id, PhaseStatus.FAILED,
                                 errors=["[AUTH_REQUIRED] Cookie 失效，请更新后使用 --from-phase 重新运行"])
            else:
                # 取最后 10 行作为错误预览
                tail_lines = stdout_lines[-10:] if stdout_lines else []
                error_preview = '\n'.join(tail_lines) if tail_lines else f"exit {returncode}"
                log_path = self._tool_log_path(phase_id)
                return PhaseResult(phase_id, PhaseStatus.FAILED,
                                 errors=[f"工具执行失败（完整日志: {log_path}）:\n{error_preview}"])

        except subprocess.TimeoutExpired:
            proc.kill()
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=[f"工具执行超时 ({timeout}s)"])
        except Exception as e:
            return PhaseResult(phase_id, PhaseStatus.FAILED,
                             errors=[f"工具执行异常: {str(e)}"])

    def _tool_log_path(self, phase_id: str) -> str:
        """返回工具执行日志文件路径"""
        probe_dir = Path(self.project_dir) / "_probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        return str(probe_dir / f"{phase_id}_tool.log")

    def _save_tool_log(self, phase_id: str, tool: str, module_slug: str | None,
                       stdout: str | None, stderr: str | None):
        """将工具完整 stdout/stderr 写入 _probe/{phase_id}_tool.log

        多模块阶段使用追加模式，每个模块的日志用分隔符分开。
        """
        log_path = self._tool_log_path(phase_id)
        log_file = Path(log_path)
        try:
            # 文件已存在则追加，否则新建
            mode = 'a' if log_file.exists() else 'w'
            with open(log_path, mode, encoding='utf-8') as f:
                # 分隔符（追加模式下区分不同模块）
                f.write(f"\n{'='*60}\n")
                if module_slug:
                    f.write(f"# Module: {module_slug}\n")
                f.write(f"# Phase: {phase_id}\n")
                f.write(f"# Tool: {tool}\n")
                f.write(f"# Time: {datetime.now().isoformat()}\n")
                f.write(f"# {'=' * 60}\n\n")
                if stdout:
                    f.write("## STDOUT\n")
                    f.write(stdout)
                    if not stdout.endswith('\n'):
                        f.write('\n')
                if stderr:
                    f.write("\n## STDERR\n")
                    f.write(stderr)
                    if not stderr.endswith('\n'):
                        f.write('\n')
        except Exception:
            pass  # 日志写入失败不影响主流程

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
                encoding='utf-8',
                errors='replace',
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
        import json
        ls_str = json.dumps(self.context.local_storage, ensure_ascii=False) if self.context.local_storage else ""
        for arg in args:
            try:
                resolved_arg = arg.format(
                    project_dir=self.project_dir,
                    config_path=self.context.config_path,
                    cookie=self.context.cookie or "",
                    local_storage=ls_str,
                    target_url=self.context.target_url or "",
                    excel_path=self.context.excel_path or "",
                    excel_json_path=self.context.excel_json_path or "",
                    module_urls_path=self.context.module_urls_path or "",
                    # BUG-6 fix: 不传递 module_slug/discovery_path，让 KeyError 保留占位符
                    # 由 _execute_multi_module 在循环中替换为真实值
                )
                resolved.append(resolved_arg)
            except KeyError as e:
                # 缺失变量（module_slug, discovery_path）保留原始占位符
                resolved.append(arg)
        return resolved

    def _cascade_skip(self, failed_phase: str):
        """阶段失败后，级联跳过所有依赖它的阶段

        2026-08-03 简化：所有依赖失败都标记为 SKIPPED，不再升级为 FAILED。
        移除 gate 升级逻辑，避免 Phase 6 失败导致 Phase 8/9 全量阻断。
        """
        for phase_id, defn in self.registry.items():
            if failed_phase in defn.get("hard_deps", []):
                if self.results.get(phase_id) is None:
                    # 统一标记为 SKIPPED（包括 gate 阶段）
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

    def _save_state(self, is_intermediate=False):
        """保存管线状态到 JSON

        Args:
            is_intermediate: True 表示增量保存（阶段间），final_status 设为 "running"
                           False 表示最终保存（管线结束），动态计算 final_status
        """
        state = {
            "run_id": self.start_time.strftime("%Y%m%d_%H%M%S"),
            "started_at": self.start_time.isoformat(),
            "project_dir": self.project_dir,
            "cli_params": {
                "excel_path": self.context.excel_path or "",
                "cookie": self.context.cookie or "",
                "target_url": self.context.target_url or "",
            },
            "phases": {},
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
            else:
                state["phases"][phase_id] = {
                    "status": "not_run",
                    "duration": 0,
                    "errors": [],
                    "warnings": [],
                }

        # 动态计算 final_status
        if is_intermediate:
            # 增量保存：标记为运行中
            state["final_status"] = "running"
        else:
            # 最终保存：根据所有阶段状态计算
            all_statuses = [p["status"] for p in state["phases"].values()]
            if "failed" in all_statuses:
                state["final_status"] = "failed"
            elif "not_run" in all_statuses:
                state["final_status"] = "incomplete"
            else:
                state["final_status"] = "passed"

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

        print(f"\n{'═'*70}")
        print(f"📊 管线执行总结")
        print(f"{'═'*70}")
        print(f"📈 总阶段数: {total}")
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"⏭️  跳过: {skipped}")
        print(f"⏱️  总耗时: {duration:.1f}s")
        print(f"📁 状态文件: {self.project_dir}/_probe/pipeline_state.json")
        print(f"{'═'*70}\n")


def cmd_run(args):
    """执行管线"""
    context = PipelineContext(
        project_dir=args.project,
        excel_path=args.excel,
        cookie=args.cookie,
        target_url=args.target_url,
        browser_type=args.browser_type,
        run_smoke=args.run_smoke,
        headed=args.headed
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
    result = validate_cross_refs(args.project)
    errors = result.get("errors", [])

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
    run_parser.add_argument("--target-url", help="目标系统 URL（用于自动生成 config.yaml）")
    run_parser.add_argument("--browser-type", default="chromium",
                           choices=["chromium", "firefox", "webkit"],
                           help="浏览器类型（默认 chromium）")
    run_parser.add_argument("--run-smoke", action="store_true",
                           help="Phase 9 完成后自动执行 smoke 测试")
    run_parser.add_argument("--headed", action="store_true",
                           help="浏览器以有头模式运行（headless=False），用于调试观察页面状态")
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
