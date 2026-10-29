"""断言截图功能一键升级脚本

使用方法：
  方式1（本地 whl）: python upgrade_assertion_screenshot.py --whl path/to/ui_engine_xin-0.0.13-py3-none-any.whl
  方式2（pip 在线）: python upgrade_assertion_screenshot.py
  方式3（指定项目）: python upgrade_assertion_screenshot.py D:\\path\\to\\project

功能：
  1. 卸载旧版 ui_engine_xin，安装新版（支持本地 whl 或 pip 在线）
  2. 检查引擎是否包含 ASSERTION_KEYWORDS
  3. config.yaml 追加断言截图配置
  4. run.py 的 DebugRunner 添加上下文传递代码

幂等：重复运行不会重复修改。
"""
import os
import re
import subprocess
import sys


def install_engine(whl_path=None):
    """卸载旧版并安装新版 ui_engine_xin"""
    print(f"  正在卸载旧版 ui_engine_xin...")
    subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'ui_engine_xin'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if whl_path:
        if not os.path.isfile(whl_path):
            print(f"  [FAIL] whl 文件不存在: {whl_path}")
            return False
        print(f"  正在从本地 whl 安装: {os.path.basename(whl_path)}")
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', whl_path, '--force-reinstall'],
                                capture_output=True, text=True)
    else:
        print(f"  正在从 pip 安装最新版 ui_engine_xin...")
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', 'ui_engine_xin', '--upgrade'],
                                capture_output=True, text=True)

    if result.returncode == 0:
        print(f"  [OK] ui_engine_xin 安装成功")
        return True
    else:
        print(f"  [FAIL] 安装失败: {result.stderr}")
        return False


def verify_engine(project_dir):
    """检查引擎是否已升级"""
    # 强制重新导入
    if 'UIEngine.basecase' in sys.modules:
        del sys.modules['UIEngine.basecase']

    try:
        import UIEngine.basecase as bc
        has_keywords = hasattr(bc, 'ASSERTION_KEYWORDS')
        if has_keywords:
            print(f"  [OK] UIEngine 引擎已包含 ASSERTION_KEYWORDS ({len(bc.ASSERTION_KEYWORDS)} 项)")
            return True
        else:
            print(f"  [FAIL] UIEngine 引擎缺少 ASSERTION_KEYWORDS")
            return False
    except ImportError:
        print(f"  [FAIL] 无法导入 UIEngine，请检查安装")
        return False


def upgrade_config(project_dir):
    """config.yaml 追加断言截图配置"""
    config_path = os.path.join(project_dir, 'config.yaml')
    if not os.path.isfile(config_path):
        print(f"  [SKIP] config.yaml 不存在")
        return False

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'assertion_screenshot' in content:
        print(f"  [OK] config.yaml 已包含 assertion_screenshot 配置")
        return True

    project_name = os.path.basename(os.path.abspath(project_dir))

    # 在 max_suite_screenshot_dirs 行之后插入
    pattern = r'(max_suite_screenshot_dirs:\s*\d+\n)'
    replacement = (
        r'\1'
        f'\n'
        f'# 断言截图（每个断言步骤自动截图并嵌入 HTML 报告）\n'
        f'# 设为 false 可关闭断言截图功能，减少报告体积\n'
        f'assertion_screenshot: true\n'
        f'\n'
        f'# 项目名称（用于截图目录结构：report/screenshots/{{project_name}}/{{module}}/）\n'
        f'project_name: "{project_name}"\n'
    )

    new_content, n = re.subn(pattern, replacement, content, count=1)
    if n == 0:
        # 没找到 max_suite_screenshot_dirs，追加到 global_variable 之前
        pattern2 = r'(global_variable:)'
        replacement2 = (
            f'# 断言截图（每个断言步骤自动截图并嵌入 HTML 报告）\n'
            f'assertion_screenshot: true\n'
            f'project_name: "{project_name}"\n'
            f'\n'
            r'\1'
        )
        new_content, n = re.subn(pattern2, replacement2, content, count=1)

    if n == 0:
        print(f"  [WARN] 未找到插入位置，请手动添加以下配置到 config.yaml:")
        print(f'    assertion_screenshot: true')
        print(f'    project_name: "{project_name}"')
        return False

    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"  [OK] config.yaml 已添加断言截图配置 (project_name: {project_name})")
    return True


def upgrade_run_py(project_dir):
    """run.py 的 DebugRunner 添加断言截图上下文传递"""
    run_path = os.path.join(project_dir, 'run.py')
    if not os.path.isfile(run_path):
        print(f"  [SKIP] run.py 不存在")
        return False

    with open(run_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查是否已升级
    if '_assertion_screenshot_dir' in content:
        print(f"  [OK] run.py 已包含断言截图代码")
        return True

    # 检查是否有 DebugRunner
    if 'class DebugRunner' not in content:
        print(f"  [SKIP] run.py 无 DebugRunner 类（仅 Runner 模式，引擎已自动处理）")
        return True

    modified = False

    # ── 位置 A: for 循环内，case_name 赋值后、skip 检查前 ──
    context_block = (
        "\n"
        "            # ── 设置断言截图上下文（与 Runner 一致）──\n"
        "            self.base_case._assertion_screenshot_dir = self._assertion_screenshot_dir\n"
        "            self.base_case._current_module = case.get('_module', 'default')\n"
        "            self.base_case._current_case_name = case_name\n"
        "            self.base_case._current_seq = case.get('_seq', idx + 1)\n"
        "            self.base_case._assertion_counter = 0\n"
        "\n"
    )

    # 匹配: case_name = ... \n\n if case.get("skip"):
    pattern_a = r"(case_name = case\.get\('name'\) or case\.get\('id'\) or f\"case_\{idx \+ 1\}\")\n(\n\s+if case\.get\(\"skip\"\):)"
    replacement_a = r"\1\n" + context_block + r"\2"
    new_content, n = re.subn(pattern_a, replacement_a, content, count=1)
    if n > 0:
        content = new_content
        modified = True
        print(f"  [OK] run.py 位置A: for 循环上下文设置已插入")
    else:
        print(f"  [WARN] run.py 位置A: 未找到精确匹配，尝试宽松匹配...")
        # 宽松匹配
        pattern_a2 = r"(case_name = case\.get\(.name.\)[^\n]+)\n(\n\s+if case\.get\(.skip.\):)"
        replacement_a2 = r"\1\n" + context_block + r"\2"
        new_content, n = re.subn(pattern_a2, replacement_a2, content, count=1)
        if n > 0:
            content = new_content
            modified = True
            print(f"  [OK] run.py 位置A: 宽松匹配成功")
        else:
            print(f"  [FAIL] run.py 位置A: 无法自动插入，请手动添加")

    # ── 位置 B: while 重试循环内，tree_builder.reset() 之后 ──
    pattern_b = r"(self\.tree_builder\.reset\(\))\n(\n\s+try:)"
    replacement_b = r"\1\n                self.base_case._assertion_counter = 0  # ★ 重试时重置断言计数器\n\2"

    # 只在 DebugRunner 的 run_suite_case 中替换（第二次出现）
    # 先检查是否已有（Runner 的 run_suite_case 可能已有）
    parts = content.split('self.tree_builder.reset()')
    if len(parts) >= 3:
        # 有多个 tree_builder.reset()，只改 DebugRunner 中的（最后一个）
        # 通过检查后面是否紧跟 try: 来确认
        last_idx = content.rfind('self.tree_builder.reset()')
        after = content[last_idx:last_idx + 100]
        if '_assertion_counter' not in after:
            content = (content[:last_idx]
                       + 'self.tree_builder.reset()\n                self.base_case._assertion_counter = 0  # ★ 重试时重置断言计数器'
                       + content[last_idx + len('self.tree_builder.reset()'):])
            modified = True
            print(f"  [OK] run.py 位置B: 重试计数器重置已插入")
        else:
            print(f"  [OK] run.py 位置B: 已存在")
    else:
        # 只有一个 tree_builder.reset()，直接用正则
        new_content, n = re.subn(pattern_b, replacement_b, content, count=1)
        if n > 0 and '_assertion_counter = 0  # ★ 重试时' not in content[:content.find(new_content[:20])]:
            content = new_content
            modified = True
            print(f"  [OK] run.py 位置B: 重试计数器重置已插入")
        else:
            print(f"  [WARN] run.py 位置B: 未找到匹配或已存在")

    if modified:
        with open(run_path, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        print(f"  [INFO] run.py 无需修改")

    return True


def print_help():
    """打印帮助信息"""
    print("""
断言截图功能升级工具
==================

用法:
  python upgrade_assertion_screenshot.py [选项] [项目目录]

选项:
  --whl <path>     使用本地 whl 文件安装引擎（默认从 pip 在线安装）
  --skip-engine    跳过引擎安装步骤（仅升级项目配置）
  --help, -h       显示此帮助信息

示例:
  # 在项目目录下运行（自动从 pip 安装最新版引擎）
  python upgrade_assertion_screenshot.py

  # 使用本地 whl 文件
  python upgrade_assertion_screenshot.py --whl ui_engine_xin-0.0.13-py3-none-any.whl

  # 指定项目目录
  python upgrade_assertion_screenshot.py D:\\path\\to\\project

  # 仅升级配置，不安装引擎
  python upgrade_assertion_screenshot.py --skip-engine
""")


def main():
    # 解析参数
    whl_path = None
    project_dir = os.getcwd()
    skip_engine = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('--help', '-h'):
            print_help()
            return
        elif arg == '--whl' and i + 1 < len(sys.argv):
            whl_path = os.path.abspath(sys.argv[i + 1])
            i += 2
        elif arg == '--skip-engine':
            skip_engine = True
            i += 1
        elif not arg.startswith('--'):
            project_dir = os.path.abspath(arg)
            i += 1
        else:
            print(f"[ERROR] 未知参数: {arg}")
            print("使用 --help 查看帮助信息")
            sys.exit(1)

    print(f"{'=' * 50}")
    print(f"断言截图功能升级工具")
    print(f"项目目录: {project_dir}")
    if whl_path:
        print(f"本地 whl: {whl_path}")
    if skip_engine:
        print(f"跳过引擎安装: 是")
    print(f"{'=' * 50}")

    # Step 1: 安装/升级引擎
    if not skip_engine:
        print(f"\n[1/4] 安装 UIEngine...")
        install_ok = install_engine(whl_path)
        if not install_ok:
            print(f"  [FAIL] 引擎安装失败，终止升级")
            sys.exit(1)
    else:
        print(f"\n[1/4] 跳过引擎安装（--skip-engine）")

    # Step 2: 验证引擎
    print(f"\n[2/4] 验证引擎版本...")
    engine_ok = verify_engine(project_dir)
    if not engine_ok:
        print(f"  [FAIL] 引擎验证失败")
        if not skip_engine:
            print(f"  请检查安装日志")
            sys.exit(1)
        else:
            print(f"  当前使用 --skip-engine，请确保引擎已包含断言截图功能")
            sys.exit(1)

    # Step 3: 升级 config.yaml
    print(f"\n[3/4] 升级 config.yaml...")
    upgrade_config(project_dir)

    # Step 4: 升级 run.py
    print(f"\n[4/4] 升级 run.py (DebugRunner)...")
    upgrade_run_py(project_dir)

    # 完成
    print(f"\n{'=' * 50}")
    print(f"[OK] 升级完成！运行以下命令验证：")
    print(f"   python run.py --module <模块名>")
    print(f"")
    print(f"验证项：")
    print(f"  - report/screenshots/ 目录下生成截图文件")
    print(f"  - HTML 报告中显示内嵌截图（可点击放大）")
    print(f"{'=' * 50}")


if __name__ == '__main__':
    main()
