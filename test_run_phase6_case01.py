#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行 Phase 6 验证阶段，只针对新增云主机用例
"""

import sys
import os

# 添加 skill 的 tools 目录到 Python 路径
tools_dir = r'D:\PyProject\TestUiEngineXin\.claude\skills\generate-ui-test\tools'
sys.path.insert(0, tools_dir)

from pipeline import run_phase

def main():
    # 项目目录
    project_dir = r'D:\PyProject\TestUiEngineXin\examples\ecsCloud'

    # 只针对新增云主机用例
    case_filter = '01_计算-新增云主机'

    print(f"=== Phase 6 验证 ===")
    print(f"项目目录: {project_dir}")
    print(f"用例过滤: {case_filter}")
    print()

    # 运行 Phase 6
    success = run_phase(
        phase='phase_6_verify',
        project_dir=project_dir,
        case_filter=case_filter,
        skip_filter=False
    )

    if success:
        print("\n✓ Phase 6 完成")
        return 0
    else:
        print("\n✗ Phase 6 失败")
        return 1

if __name__ == '__main__':
    sys.exit(main())
