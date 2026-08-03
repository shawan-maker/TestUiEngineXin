#!/usr/bin/env python3
"""调试 get_kb_patterns 函数"""
import sys
import os
sys.path.insert(0, '.claude/skills/generate-ui-test/tools/probe')
sys.path.insert(0, '.claude/skills/generate-ui-test/tools')

# 先检查文件路径
knowledge_path = '.claude/skills/generate-ui-test/tools/probe_knowledge.json'
print(f"知识库文件路径: {knowledge_path}")
print(f"文件存在: {os.path.exists(knowledge_path)}")

if os.path.exists(knowledge_path):
    import json
    with open(knowledge_path, 'r', encoding='utf-8') as f:
        db = json.load(f)

    print("\n=== 知识库顶层结构 ===")
    print(f"版本: {db.get('version')}")
    print(f"顶层 keys: {list(db.keys())}")

    print("\n=== composite.categories ===")
    composite_cats = db.get('composite', {}).get('categories', {})
    print(f"composite 中的类型: {list(composite_cats.keys())}")

    if 'table-action-button' in composite_cats:
        print(f"\ntable-action-button 定义:")
        print(json.dumps(composite_cats['table-action-button'], indent=2, ensure_ascii=False))

print("\n=== 导入并测试 get_kb_patterns ===")
try:
    from probe_utils import get_kb_patterns, load_knowledge

    # 测试 load_knowledge
    loaded_db = load_knowledge()
    print(f"load_knowledge 返回的 keys: {list(loaded_db.keys())}")

    # 测试 get_kb_patterns
    patterns = get_kb_patterns('table-action-button')
    print(f"\nget_kb_patterns('table-action-button') 返回:")
    print(f"  类型: {type(patterns)}")
    print(f"  长度: {len(patterns)}")
    if patterns:
        for i, p in enumerate(patterns, 1):
            print(f"  {i}. {p}")
    else:
        print("  (空列表)")

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
