#!/usr/bin/env python3
"""调试 load_knowledge 文件加载路径"""
import sys
import os
sys.path.insert(0, '.claude/skills/generate-ui-test/tools/probe')
sys.path.insert(0, '.claude/skills/generate-ui-test/tools')

from probe_utils import DEFAULT_KNOWLEDGE_PATH, load_knowledge

print(f"DEFAULT_KNOWLEDGE_PATH: {DEFAULT_KNOWLEDGE_PATH}")
print(f"绝对路径: {os.path.abspath(DEFAULT_KNOWLEDGE_PATH)}")
print(f"文件存在: {os.path.exists(DEFAULT_KNOWLEDGE_PATH)}")

# 手动加载正确的文件
correct_path = '.claude/skills/generate-ui-test/tools/probe_knowledge.json'
print(f"\n正确路径: {correct_path}")
print(f"绝对路径: {os.path.abspath(correct_path)}")
print(f"文件存在: {os.path.exists(correct_path)}")

import json
with open(correct_path, 'r', encoding='utf-8') as f:
    correct_db = json.load(f)
print(f"正确文件的 keys: {list(correct_db.keys())}")

# 调用 load_knowledge
db = load_knowledge()
print(f"\nload_knowledge() 返回的 keys: {list(db.keys())}")

# 检查是否有缓存
from probe_utils import _knowledge_db
print(f"_knowledge_db 缓存: {_knowledge_db is not None}")
