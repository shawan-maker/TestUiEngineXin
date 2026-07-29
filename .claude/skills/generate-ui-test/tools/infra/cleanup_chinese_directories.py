#!/usr/bin/env python3
"""
cleanup_chinese_directories.py - 清理中文命名的目录（数据污染）

背景：
旧代码的 fallback 逻辑会产生中文命名的目录（如 pages/问题管理/），
而正确逻辑应该产生英文 slug 目录（如 pages/question-manage/）。

此脚本会删除 pages/, cases/, data/, suites/ 下的中文命名目录，
保留英文 slug 目录和 common 目录。

用法：
    python cleanup_chinese_directories.py <project_dir>
"""
import os
import shutil
import sys


def has_chinese_chars(s):
    """检查字符串是否包含中文（非ASCII）字符"""
    return any(ord(c) > 127 for c in s)


def cleanup_directories(base_dir):
    """清理指定目录下的中文子目录"""
    if not os.path.isdir(base_dir):
        return

    removed = []
    kept = []

    for entry in os.listdir(base_dir):
        entry_path = os.path.join(base_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        # 保留 common 目录
        if entry == 'common':
            kept.append(entry)
            continue

        # 删除中文命名目录
        if has_chinese_chars(entry):
            shutil.rmtree(entry_path)
            removed.append(entry)
        else:
            kept.append(entry)

    return removed, kept


def main():
    if len(sys.argv) != 2:
        print("用法: python cleanup_chinese_directories.py <project_dir>")
        sys.exit(1)

    project_dir = sys.argv[1]

    if not os.path.isdir(project_dir):
        print(f"错误: 项目目录不存在 {project_dir}")
        sys.exit(1)

    print(f"清理项目: {project_dir}\n")

    dirs_to_clean = ['pages', 'cases', 'data', 'suites']
    total_removed = []

    for dir_name in dirs_to_clean:
        dir_path = os.path.join(project_dir, dir_name)
        removed, kept = cleanup_directories(dir_path)

        if removed:
            print(f"{dir_name}/")
            for name in removed:
                print(f"  [DEL] {name}")
            for name in kept:
                print(f"  [KEEP] {name}")
            print()
            total_removed.extend([(dir_name, name) for name in removed])

    if total_removed:
        print(f"\n总计删除 {len(total_removed)} 个中文目录")
    else:
        print("未发现中文命名目录，无需清理")


if __name__ == '__main__':
    main()
