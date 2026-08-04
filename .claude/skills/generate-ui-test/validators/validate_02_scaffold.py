"""Phase 2 脚手架生成验证器

验证内容：
1. 目录结构正确（R1.1）
2. 模板变量替换完整（R1.2）
3. .gitignore 正确（R1.3）
4. run.py 存在（R1.5）
5. 四层目录含 common/ 子目录（R1.6）

用法：
    python validate_02_scaffold.py <project_dir>
"""
import sys
import os
import yaml


REQUIRED_DIRS = ['pages', 'data', 'cases', 'suites', 'lib', '_probe', 'files', 'report']
REQUIRED_FILES = ['run.py', 'config.yaml', '.gitignore']


def validate_directory_structure(project_dir):
    """验证目录结构"""
    errors = []
    for d in REQUIRED_DIRS:
        if not os.path.isdir(os.path.join(project_dir, d)):
            errors.append(f"[R1.1] 缺少目录: {d}/")
    return errors


def validate_template_variables(project_dir):
    """验证模板变量替换"""
    errors = []

    # 检查 config.yaml（跳过注释行）
    config_file = os.path.join(project_dir, 'config.yaml')
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                # 跳过注释行（YAML 注释以 # 开头）
                if stripped.startswith('#'):
                    continue
                if '{{' in line:
                    errors.append("[R1.2] config.yaml 中存在未替换的模板变量")
                    break

    # 检查 run.py（跳过注释行）
    run_file = os.path.join(project_dir, 'run.py')
    if os.path.exists(run_file):
        with open(run_file, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                # 跳过 Python 注释行
                if stripped.startswith('#'):
                    continue
                if '{{' in line:
                    errors.append("[R1.2] run.py 中存在未替换的模板变量")
                    break

    return errors


def validate_gitignore(project_dir):
    """验证 .gitignore"""
    errors = []
    gitignore_file = os.path.join(project_dir, '.gitignore')
    if os.path.exists(gitignore_file):
        with open(gitignore_file, 'r', encoding='utf-8') as f:
            content = f.read()
        required_patterns = ['files/', 'report/', '_probe/', '__pycache__/', '*.pyc']
        for pattern in required_patterns:
            if pattern not in content:
                errors.append(f"[R1.3] .gitignore 缺少排除项: {pattern}")
    else:
        errors.append("[R1.3] .gitignore 文件不存在")
    return errors


def validate_run_py(project_dir):
    """验证 run.py 存在"""
    errors = []
    run_file = os.path.join(project_dir, 'run.py')
    if not os.path.exists(run_file):
        errors.append("[R1.5] run.py 文件不存在")
    return errors


def validate_common_subdirs(project_dir):
    """验证四层目录中 common/ 子目录存在（R1.6）"""
    errors = []
    for layer in ['pages', 'data', 'cases', 'suites']:
        common_dir = os.path.join(project_dir, layer, 'common')
        if not os.path.isdir(common_dir):
            errors.append(f"[R1.6] 缺少子目录: {layer}/common/")
    return errors


def validate_scaffold(project_dir):
    """主验证入口"""
    errors = []
    warnings = []
    info = []

    errors.extend(validate_directory_structure(project_dir))
    errors.extend(validate_template_variables(project_dir))
    errors.extend(validate_gitignore(project_dir))
    errors.extend(validate_run_py(project_dir))
    errors.extend(validate_common_subdirs(project_dir))

    # 统计模块数
    cases_dir = os.path.join(project_dir, 'cases')
    if os.path.exists(cases_dir):
        modules = [d for d in os.listdir(cases_dir) if os.path.isdir(os.path.join(cases_dir, d))]
        info.append(f"检测到 {len(modules)} 个模块: {', '.join(modules)}")

    return errors, warnings, info


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python validate_02_scaffold.py <project_dir>")
        sys.exit(1)

    project_dir = sys.argv[1]
    errors, warnings, info = validate_scaffold(project_dir)

    print("=" * 60)
    print(f"Phase 2 Scaffold Validation - {project_dir}")
    print("=" * 60)

    for msg in info:
        print(f"  [INFO] {msg}")
    for msg in warnings:
        print(f"  [WARN] {msg}")
    for msg in errors:
        print(f"  [ERR]  {msg}")

    print("-" * 60)
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s)")

    sys.exit(1 if errors else 0)
