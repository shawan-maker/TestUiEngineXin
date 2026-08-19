#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：运行 Phase 6 验证阶段（只针对新增云主机用例）
"""

import sys
import os
import subprocess

# 项目目录
project_dir = r'D:\PyProject\TestUiEngineXin\examples\ecsCloud'
pipeline_script = r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools\pipeline.py'

def main():
    print("=== Phase 6 验证测试 ===")
    print(f"项目目录: {project_dir}")
    print()

    # 构建命令
    cmd = [
        sys.executable,
        pipeline_script,
        'run',
        '--project', project_dir,
        '--only-phase', 'phase_6_verify'
    ]

    print(f"执行命令: {' '.join(cmd)}")
    print()

    # 执行命令
    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=False,  # 实时输出
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        print()
        print(f"=== 执行完成 ===")
        print(f"返回码: {result.returncode}")

        return result.returncode

    except Exception as e:
        print(f"执行失败: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
