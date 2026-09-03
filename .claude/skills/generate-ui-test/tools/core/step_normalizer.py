#!/usr/bin/env python3
"""step_normalizer.py — 步骤文本规范化共享层

从 validate_excel.py 抽取 L1/L2/L3 规则逻辑，封装为 normalize_step_text() 函数。
供 Excel 路径和自然语言路径共用。

主要功能：
- L1 自动修复（引号统一、空格去除、格式标准化）
- L2 自动修复（el-select 补等待、级联识别）
- L3 解析验证（unknown 步骤检测）

依赖：validate_excel.py 的 ExcelValidator 类（方案 A：实例化复用）
"""

import os
import sys
from typing import List, Tuple

# Ensure tools/ is on sys.path for core.* imports
_tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

try:
    from excel.validate_excel import ExcelValidator, FixRecord
except ImportError as e:
    print(f"[FATAL] 无法导入 validate_excel: {e}", file=sys.stderr)
    sys.exit(2)


class _VirtualValidator(ExcelValidator):
    """虚拟验证器：继承 ExcelValidator 的规则逻辑，不加载 Excel 文件

    重写 __init__ 跳过 openpyxl.load_workbook()，仅使用 L1/L2/L3 规则方法。
    """

    def __init__(self):
        from pathlib import Path
        # 设置占位符路径（不实际使用）
        self.input_path = Path("virtual")
        self.output_path = "virtual"
        self.report_path = "virtual"
        self.wb = None  # 不加载 workbook
        self.fixes = []
        self.stats = {'L1_auto': 0, 'L2_auto': 0, 'L2_warn': 0, 'L3_error': 0}

    def _infer_project_dir(self):
        """重写：返回当前工作目录（虚拟验证器无需推断项目目录）"""
        return os.getcwd()


def normalize_step_text(
    text: str,
    sheet: str = "自然语言输入",
    case_name: str = "case_001"
) -> Tuple[str, List[dict], List[dict]]:
    """规范化步骤文本，返回 (清洗后文本, 修复记录, unknown 步骤)

    Args:
        text: 原始步骤文本（多行，含编号 1. 2. 3.）
        sheet: 来源标识（Excel sheet 名或 "自然语言输入"）
        case_name: 用例名称

    Returns:
        (cleaned_text, fix_records, unknown_steps)
        - cleaned_text: 清洗后的文本
        - fix_records: 修复记录列表（dict 格式）
        - unknown_steps: L3 无法解析的步骤列表（dict 格式）
    """
    # 创建虚拟的 ExcelValidator 实例（不加载实际文件）
    # 仅使用其规则逻辑，不操作 Excel 文件
    validator = _create_virtual_validator()

    # 应用 L1 规则
    cleaned_text = validator._apply_l1_rules(text, sheet, case_name, row_idx=1)

    # 应用 L2 规则
    cleaned_text = validator._apply_l2_rules(cleaned_text, sheet, case_name, row_idx=1)

    # R20: 复合步骤拆分
    cleaned_text = validator._r20_split_compound_steps(cleaned_text, sheet, case_name)

    # R20b: 去重连续相同的等待步骤
    cleaned_text = validator._dedup_consecutive_waits(cleaned_text, sheet, case_name)

    # L2.5: AI 步骤重写（跳过，需要 rewrites JSON）
    # cleaned_text = validator._apply_ai_rewrite(cleaned_text, sheet, case_name)

    # L3a: 解析验证
    validator._apply_l3_parse_validation(cleaned_text, sheet, case_name)

    # L3b/c: 关键字白名单 + 参数校验
    validator._apply_l3_whitelist_validation(cleaned_text, sheet, case_name)

    # 提取修复记录
    fix_records = [f.to_dict() for f in validator.fixes]

    # 提取 L3 unknown 步骤
    unknown_steps = [
        f.to_dict() for f in validator.fixes
        if f.level == 'L3' and f.severity == 'error'
    ]

    return cleaned_text, fix_records, unknown_steps


def _create_virtual_validator() -> _VirtualValidator:
    """创建虚拟验证器实例（不加载 Excel 文件）

    使用 _VirtualValidator 继承 ExcelValidator，跳过 __init__ 中的文件加载。
    仅使用其 L1/L2/L3 规则逻辑。
    """
    return _VirtualValidator()


def parse_steps_text(text: str) -> List[Tuple[int, str]]:
    """解析步骤文本为 [(step_num, content), ...]

    与 validate_excel.py 的 _parse_steps() 逻辑一致。
    """
    import re

    steps = []
    current_num = None
    current_parts = []

    for line in text.split('\n'):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # 只在行首匹配步骤编号
        m = re.match(r'^(\d+)\s*[.、．]\s*(.*)', line_stripped)
        if m:
            # 保存前一个步骤
            if current_num is not None:
                steps.append((current_num, '\n'.join(current_parts).strip()))
            current_num = int(m.group(1))
            current_parts = [m.group(2)]
        elif current_num is not None:
            # 续行（属于当前步骤的内容）
            current_parts.append(line_stripped)

    # 保存最后一个步骤
    if current_num is not None:
        steps.append((current_num, '\n'.join(current_parts).strip()))

    return steps


def rebuild_steps_text(steps: List[Tuple[int, str]]) -> str:
    """将步骤列表重建为文本"""
    lines = []
    for i, (_, content) in enumerate(steps, 1):
        lines.append(f"{i}. {content}")
    return '\n'.join(lines)
