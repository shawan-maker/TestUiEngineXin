#!/usr/bin/env python3
"""normalize_steps.py — 自然语言输入预检工具 (Phase 1_nl)

对自由文本形式的测试用例进行 L1/L2/L3 规则清洗和交互验证。
供 Phase 1_nl 阶段使用，替代 Excel 路径的 validate_excel.py。

退出码:
  0 = 成功（全部步骤已解析，用户确认）
  1 = 用户退出（输入 q）
  2 = 环境错误（非交互模式）

用法:
  python normalize_steps.py input.txt --output cases_raw.json --module ecm_compute_static
  python normalize_steps.py -  # 从 stdin 读取
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Ensure tools/ is on sys.path for core.* imports
_tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

try:
    from core.step_normalizer import (
        normalize_step_text,
        parse_steps_text,
        rebuild_steps_text,
    )
except ImportError as e:
    print(f"[FATAL] 无法导入 step_normalizer: {e}", file=sys.stderr)
    sys.exit(2)


# ANSI 颜色代码
class Colors:
    RESET = '\033[0m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def colorize(text: str, color: str) -> str:
    """应用 ANSI 颜色（如果终端支持）"""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.RESET}"
    return text


def extract_case_name(text: str) -> Tuple[str, str]:
    """从自由文本中提取用例名称和步骤文本

    规则：
    - 如果第一行是"访问 URL"格式，保留在步骤中，使用默认名称 case_001
    - 如果第一行含编号（以 1. 2. 3. 开头），使用默认名称 case_001
    - 否则第一行是用例名

    Returns:
        (case_name, steps_text)
    """
    lines = text.strip().split('\n')
    if not lines:
        return "case_001", ""

    first_line = lines[0].strip()
    # 检查第一行是否是"访问 URL"格式
    if re.match(r'^访问\s+\S+', first_line):
        # 第一行是 URL 访问步骤，保留在步骤中
        return "case_001", text
    # 检查第一行是否以编号开头
    if re.match(r'^\d+\s*[.、．]\s*', first_line):
        # 第一行是步骤，使用默认名称
        return "case_001", text
    else:
        # 第一行是用例名
        return first_line, '\n'.join(lines[1:])


def extract_url_from_raw_text(text: str, target_url: str = '') -> str:
    """从原始文本的前两行提取 URL

    支持两种情况：
    - 第一行就是 URL：访问 http://...
    - 第一行是用例名，第二行是 URL

    Args:
        text: 原始输入文本
        target_url: 基础 URL（用于拼接相对路径）

    Returns:
        URL 字符串，未找到返回空字符串
    """
    lines = text.strip().split('\n')
    for line in lines[:2]:  # 只检查前两行
        line = line.strip()
        match = re.match(r'^访问\s+(\S+)', line)
        if match:
            url = match.group(1)
            # 相对路径：与 target_url 拼接
            if url.startswith('/') and target_url:
                base = target_url.rstrip('/')
                url = base + url
            return url
    return ""


def extract_url_from_steps(steps: list, target_url: str = '') -> str:
    """从步骤中提取第一个"访问"步骤的 URL

    支持两种格式：
    - 绝对路径：访问 http://... 或 访问 https://...
    - 相对路径：访问 /path/to/page（与 target_url 拼接）

    Args:
        steps: 步骤列表 [(num, content), ...]
        target_url: 基础 URL（用于拼接相对路径）

    Returns:
        URL 字符串，未找到返回空字符串
    """
    for num, content in steps:
        # 匹配"访问 URL" 或 "访问 /相对路径"
        match = re.match(r'^访问\s+(\S+)', content)
        if match:
            url = match.group(1)
            # 相对路径：与 target_url 拼接
            if url.startswith('/') and target_url:
                # 去除 target_url 末尾的斜杠
                base = target_url.rstrip('/')
                url = base + url
            return url
    return ""


def normalize_single_step(step_text: str, case_name: str, module: str) -> Tuple[str, List[dict], List[dict]]:
    """规范化单个步骤，返回 (清洗后文本, 修复记录, unknown 步骤)

    Args:
        step_text: 单个步骤文本（不含编号）
        case_name: 用例名称
        module: 模块名

    Returns:
        (cleaned_text, fix_records, unknown_steps)
    """
    # 包装为带编号的文本
    numbered_text = f"1. {step_text}"
    cleaned_text, fix_records, unknown_steps = normalize_step_text(
        numbered_text, sheet="自然语言输入", case_name=case_name
    )
    # 去除编号
    cleaned_text = re.sub(r'^\d+\s*[.、．]\s*', '', cleaned_text.strip())
    return cleaned_text, fix_records, unknown_steps


def display_results(steps: List[Tuple[int, str]], fix_records: List[dict], unknown_steps: List[dict], case_name: str):
    """展示清洗结果（✅ / ❌ 分类）

    逻辑与 Excel 路径一致：
    - 解析成功：✅ + 步骤内容（不展示 action_type，用户不关心内部类型）
    - 解析失败：❌ + 步骤内容 + suggestion（如果能推断）
    - 汇总：X/Y 已解析，Z 条需修改
    """
    print("\n" + colorize("=" * 70, Colors.CYAN))
    print(colorize(f"  用例: {case_name}", Colors.BOLD))
    print(colorize("=" * 70, Colors.CYAN))

    # 构建 unknown 步骤编号集合
    unknown_nums = {s['step_num'] for s in unknown_steps}

    for step_num, content in steps:
        if step_num in unknown_nums:
            # 无法解析
            print(f"\n  {colorize(f'❌ {step_num}.', Colors.RED)} {content}")
            # 查找对应的 suggestion
            suggestion = next(
                (s['suggestion'] for s in unknown_steps if s['step_num'] == step_num),
                None
            )
            if suggestion:
                print(f"     {colorize('建议:', Colors.YELLOW)} {suggestion}")
        else:
            # 已解析 - 只显示 ✅ + 内容（与 Excel 路径一致）
            print(f"\n  {colorize(f'✅ {step_num}.', Colors.GREEN)} {content}")

    print("\n" + colorize("=" * 70, Colors.CYAN))
    parsed_count = len(steps) - len(unknown_nums)
    total = len(steps)

    if unknown_nums:
        print(colorize(f"{parsed_count}/{total} 已解析，{len(unknown_nums)} 条需要修改", Colors.YELLOW))
    else:
        print(colorize(f"{parsed_count}/{total} 全部解析成功 ✓", Colors.GREEN))

    print(colorize("=" * 70, Colors.CYAN))


def show_fix_history(step_num: int, fix_records: List[dict]):
    """显示指定步骤的 L1 修复历史"""
    step_fixes = [f for f in fix_records if f['step_num'] == step_num]

    if not step_fixes:
        print(f"\n  {colorize('步骤 ' + str(step_num) + ' 无 L1/L2 修复记录', Colors.DIM)}")
        return

    print(f"\n  {colorize(f'步骤 {step_num} 的修复记录:', Colors.BOLD)}")
    print(colorize("  " + "-" * 68, Colors.DIM))

    for f in step_fixes:
        level = f['level']
        rule = f['rule_id']
        before = f['before'][:50] + '...' if len(f['before']) > 50 else f['before']
        after = f['after'][:50] + '...' if len(f['after']) > 50 else f['after']

        # 颜色编码
        level_color = Colors.GREEN if level == 'L1' else Colors.YELLOW
        print(f"  {colorize(level, level_color)} {colorize(rule, Colors.BLUE)}")
        print(f"    {colorize('修改前:', Colors.DIM)} {before}")
        print(f"    {colorize('修改后:', Colors.GREEN)} {after}")
        print()


def interactive_loop(steps: List[Tuple[int, str]], case_name: str, module: str) -> Tuple[List[Tuple[int, str]], bool]:
    """交互式修改循环

    Returns:
        (final_steps, confirmed)
        - final_steps: 修改后的步骤列表
        - confirmed: 用户是否确认（True）或退出（False）
    """
    all_fix_records = []  # 累积所有修复记录

    while True:
        # 规范化并验证
        steps_text = rebuild_steps_text(steps)
        cleaned_text, fix_records, unknown_steps = normalize_step_text(
            steps_text, sheet="自然语言输入", case_name=case_name
        )

        # 累积修复记录
        all_fix_records = fix_records

        # 重新解析步骤
        steps = parse_steps_text(cleaned_text)
        if not steps:
            print("[ERROR] 无有效步骤，请重新输入")
            return steps, False

        # 展示结果
        display_results(steps, fix_records, unknown_steps, case_name)

        # 检查是否全部解析
        unknown_nums = {s['step_num'] for s in unknown_steps}
        if not unknown_nums:
            # 全部解析，询问确认
            print(f"\n{colorize('输入 y 确认，输入 q 退出:', Colors.BOLD)} ", end='')
            try:
                choice = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return steps, False

            if choice == 'y':
                return steps, True
            elif choice == 'q':
                return steps, False
            else:
                print(f"  {colorize('请输入 y 或 q', Colors.YELLOW)}")
                continue

        # 有 unknown 步骤，等待用户输入
        print(f"\n{colorize('命令:', Colors.BOLD)}")
        print(f"  输入步骤编号修改（如 {colorize('4', Colors.CYAN)}）")
        print(f"  查看修复历史（如 {colorize('v 4', Colors.CYAN)}）")
        print(f"  {colorize('y', Colors.GREEN)} 确认，{colorize('q', Colors.RED)} 退出")
        print(f"\n{colorize('>', Colors.BOLD)} ", end='')

        try:
            choice = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return steps, False

        if choice == 'q':
            return steps, False
        elif choice == 'y':
            # 用户强制确认（即使有 unknown）
            print(f"\n{colorize('⚠ 警告: 仍有未解析的步骤，确认继续吗？(y/n):', Colors.YELLOW)} ", end='')
            try:
                confirm = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return steps, False
            if confirm == 'y':
                return steps, True
            continue
        elif choice.startswith('v '):
            # 查看修复历史
            parts = choice.split()
            if len(parts) == 2 and parts[1].isdigit():
                step_num = int(parts[1])
                show_fix_history(step_num, all_fix_records)
            else:
                print(f"  {colorize('用法: v <步骤号>', Colors.YELLOW)}")
        elif choice.isdigit():
            step_num = int(choice)
            # 查找对应步骤
            step_idx = next((i for i, (num, _) in enumerate(steps) if num == step_num), None)
            if step_idx is None:
                print(f"  {colorize(f'步骤 {step_num} 不存在', Colors.RED)}")
                continue

            # 显示当前内容
            _, current_content = steps[step_idx]
            print(f"\n{colorize(f'修改步骤 {step_num}:', Colors.BOLD)}")
            print(f"  {colorize('当前:', Colors.YELLOW)} {current_content}")
            print(f"\n{colorize('标准格式参考:', Colors.DIM)}")
            print(f'  点击"XX"按钮 / 在"XX"下拉框中选择"YY" / 断言：可见"XX"')
            print(f"  访问 https://... / 等待XX加载完成 / 返回")

            print(f"\n{colorize('新步骤:', Colors.BOLD)} ", end='')

            try:
                new_content = input().strip()
            except (EOFError, KeyboardInterrupt):
                continue

            if not new_content:
                print(f"  {colorize('已取消', Colors.DIM)}")
                continue

            # 规范化新步骤
            cleaned_content, _, new_unknown = normalize_single_step(new_content, case_name, module)

            if new_unknown:
                print(f"\n  {colorize(f'❌ 仍无法解析: {cleaned_content}', Colors.RED)}")
                suggestion = new_unknown[0].get('suggestion', '无') if new_unknown else '无'
                print(f"     {colorize('建议:', Colors.YELLOW)} {suggestion}")
                # 询问是否接受
                print(f"\n{colorize('是否接受？(y/n):', Colors.YELLOW)} ", end='')
                try:
                    accept = input().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    continue
                if accept != 'y':
                    continue

            # 更新步骤
            print(f"\n  {colorize(f'✅ 解析成功: {cleaned_content}', Colors.GREEN)}")
            steps[step_idx] = (step_num, cleaned_content)
        else:
            print(f"  {colorize('请输入步骤编号、v <步骤号>、y 或 q', Colors.YELLOW)}")


def _run_non_interactive(
    steps: List[Tuple[int, str]],
    case_name: str,
    module: str,
    output_path: str,
    extracted_url: str,
    input_path: Path
):
    """非交互模式（管线调用）

    - 全部步骤解析成功 → 输出 JSON + exit 0
    - 有 unknown 步骤 → 输出修正版 + exit 1（让用户修改后重跑）
    - 格式/环境错误 → exit 2
    """
    # L1/L2/L3 清洗
    steps_text = rebuild_steps_text(steps)
    cleaned_text, fix_records, unknown_steps = normalize_step_text(
        steps_text, sheet="自然语言输入", case_name=case_name
    )

    # 重新解析清洗后的步骤
    final_steps = parse_steps_text(cleaned_text)
    if not final_steps:
        print("[ERROR] 清洗后无有效步骤", file=sys.stderr)
        sys.exit(2)

    # 检查 unknown
    unknown_nums = {s['step_num'] for s in unknown_steps}

    if unknown_nums:
        # 有无法解析的步骤 → 生成修正版 TXT + exit 1（对齐 Excel 路径行为）
        corrected_path = input_path.parent / f"{input_path.stem}-修正版.txt"

        # 生成修正版 TXT（含 L1/L2 修复 + L3 标注）
        corrected_lines = []
        l1_l2_fix_count = len([f for f in fix_records if f['level'] in ('L1', 'L2')])

        for step_num, content in final_steps:
            if step_num in unknown_nums:
                # L3 unknown 步骤：标注 + 建议
                corrected_lines.append(f"{step_num}. {content}       ← [L3:需修改]")
                suggestion = next((s.get('suggestion') for s in unknown_steps if s['step_num'] == step_num), None)
                if suggestion:
                    corrected_lines.append(f"   # 建议: {suggestion}")
            else:
                # L1/L2 已修复的步骤
                corrected_lines.append(f"{step_num}. {content}")

        corrected_path.write_text('\n'.join(corrected_lines), encoding='utf-8')

        # 保存 module_urls.json（URL 提取不能丢失）
        output_dir = Path(output_path).parent if output_path else Path(input_path.parent / '_probe')
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)

        if extracted_url:
            module_urls_path = output_dir / 'module_urls.json'
            module_urls_data = {module: [extracted_url]}
            with open(module_urls_path, 'w', encoding='utf-8') as f:
                json.dump(module_urls_data, f, ensure_ascii=False, indent=2)

        # 不生成 cases_raw.json（步骤不完整，下游不应使用）

        # 输出摘要（对齐 Excel 格式）
        print(f"\n{'=' * 60}")
        print(f"L3 PARSE VALIDATION FAILED - {len(unknown_nums)} unparseable steps")
        print(f"  L1/L2 auto-fixed: {l1_l2_fix_count}")
        print(f"  L3 errors:        {len(unknown_nums)}")
        print(f"{'=' * 60}")
        print(f"Corrected NL (L1/L2 fixes applied): {corrected_path}")
        print(f"请修改 L3 步骤后重跑管线。")
        sys.exit(1)

    # 全部解析成功 → 输出 JSON
    output_path = output_path or '_probe/cases_raw.json'
    output_data = [
        {
            "sheet": "自然语言输入",
            "cases": [
                {
                    "row": 1,
                    "module": module,
                    "case_name": case_name,
                    "steps": [content for _, content in final_steps],
                    "step_count": len(final_steps),
                }
            ],
        }
    ]

    output_dir = Path(output_path).parent
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 已保存到: {output_path}")
    print(f"   {len(final_steps)} 个步骤全部解析成功")

    # 保存提取的 URL 到 module_urls.json
    if extracted_url:
        module_urls_path = output_dir / 'module_urls.json'
        module_urls_data = {module: [extracted_url]}
        with open(module_urls_path, 'w', encoding='utf-8') as f:
            json.dump(module_urls_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] 已提取 URL 并保存到: {module_urls_path}")

    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description='自然语言输入预检工具 (Phase 1_nl)'
    )
    parser.add_argument('input', help='输入文件路径（.txt）或 - 表示 stdin')
    parser.add_argument('--output', '-o', help='输出 JSON 路径（默认 _probe/cases_raw.json）')
    parser.add_argument('--module', '-m', default='common', help='模块名（默认 common）')
    parser.add_argument('--case-name', help='用例名（可选，默认从第一行提取）')
    parser.add_argument('--target-url', help='目标系统 URL（用于拼接相对路径）')
    parser.add_argument('--force-interactive', action='store_true',
                        help='强制启用交互模式（用于测试，忽略 isatty 检测）')
    parser.add_argument('--non-interactive', action='store_true',
                        help='非交互模式（管线调用）：全部解析成功→exit 0，有 unknown→exit 1')

    args = parser.parse_args()

    # 检查交互环境（--non-interactive 跳过，--force-interactive 忽略检测）
    is_interactive = not args.non_interactive
    if is_interactive and not args.force_interactive and not sys.stdin.isatty():
        print("[ERROR] 非交互环境，无法进行交互式修改", file=sys.stderr)
        print("  请使用 --non-interactive 标志（管线调用）", file=sys.stderr)
        print("  或添加 --force-interactive 标志（测试用）", file=sys.stderr)
        sys.exit(2)

    # 读取输入
    if args.input == '-':
        print("请输入测试用例描述（按 Ctrl+D 结束）:")
        text = sys.stdin.read()
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"[ERROR] 文件不存在: {args.input}", file=sys.stderr)
            sys.exit(2)
        text = input_path.read_text(encoding='utf-8')

    if not text.strip():
        print("[ERROR] 输入为空", file=sys.stderr)
        sys.exit(2)

    # 从原始文本中提取 URL（在解析步骤之前）
    target_url = args.target_url or ''
    extracted_url = extract_url_from_raw_text(text, target_url)

    # 提取用例名
    case_name = args.case_name or extract_case_name(text)[0]
    steps_text = extract_case_name(text)[1] if not args.case_name else text

    print(f"\n用例名称: {case_name}")
    print(f"模块: {args.module}")
    if extracted_url:
        print(f"提取的 URL: {extracted_url}")

    # 解析步骤
    steps = parse_steps_text(steps_text)
    if not steps:
        print("[ERROR] 未检测到有效步骤（应以 1. 2. 3. 编号）", file=sys.stderr)
        sys.exit(2)

    # 如果原始文本第一行是 URL 访问步骤，将其作为步骤 1 插入
    if extracted_url and not any('访问' in content for _, content in steps):
        url_line = text.strip().split('\n')[0]
        steps.insert(0, (1, url_line.strip()))
        # 重新编号后续步骤
        steps = [(i + 1, content) for i, (_, content) in enumerate(steps)]

    print(f"检测到 {len(steps)} 个步骤")

    # ─── 非交互模式（管线调用）───
    if args.non_interactive:
        input_path = Path(args.input) if args.input != '-' else Path('_stdin.txt')
        _run_non_interactive(steps, case_name, args.module, args.output, extracted_url, input_path)
        return  # _run_non_interactive 内部 sys.exit

    # ─── 交互模式 ───
    final_steps, confirmed = interactive_loop(steps, case_name, args.module)

    if not confirmed:
        print("\n用户退出")
        sys.exit(1)

    # 输出 JSON
    output_path = args.output or '_probe/cases_raw.json'
    output_data = [
        {
            "sheet": "自然语言输入",
            "cases": [
                {
                    "row": 1,
                    "module": args.module,
                    "case_name": case_name,
                    "steps": [content for _, content in final_steps],
                    "step_count": len(final_steps),
                }
            ],
        }
    ]

    output_dir = Path(output_path).parent
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已保存到: {output_path}")
    print(f"   {len(final_steps)} 个步骤")

    # 保存提取的 URL 到 module_urls.json
    if extracted_url:
        module_urls_path = output_dir / 'module_urls.json'
        module_urls_data = {args.module: [extracted_url]}
        with open(module_urls_path, 'w', encoding='utf-8') as f:
            json.dump(module_urls_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已提取 URL 并保存到: {module_urls_path}")
        print(f"   模块: {args.module}, URL: {extracted_url}")

    sys.exit(0)


if __name__ == '__main__':
    main()
