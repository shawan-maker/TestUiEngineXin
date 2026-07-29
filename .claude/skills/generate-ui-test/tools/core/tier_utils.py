#!/usr/bin/env python3
"""共享工具函数：Case 排序层级

提供 case ID 的排序层级计算功能，用于 validate_08 和 auto_fix 工具。
"""

import re


# R4.7 排序层级（与 generate_suites.py DEPENDENCY_ORDER 对齐）
ORDER_TIERS = [
    {'add', 'create', '新增', '新建', '创建'},              # Tier 0: 新增
    {'edit', 'modify', 'update', '编辑', '修改'},            # Tier 1: 编辑
    {'detail', 'view', '详情', '查看'},                      # Tier 2: 详情
    {'export', 'import', '导出', '导入'},                    # Tier 3: 导出/导入
    {'query', 'search', 'filter', '查询', '搜索', '筛选'},   # Tier 4: 查询
    {'batch', '批量'},                                        # Tier 5: 批量
    {'delete', 'remove', '删除', '清除', '批量删除'},         # Tier 6: 删除
]

TIER_CN = {
    0: '新增', 1: '编辑', 2: '详情', 3: '导出',
    4: '查询', 5: '批量', 6: '删除',
}


def get_case_tier(case_id: str) -> int:
    """返回 case_id 所属的排序层级（0-6），未匹配返回 -1

    取所有词段和中文子串中的最高层级（最具破坏性操作）。

    Args:
        case_id: Case ID 字符串（如 "cloud-question_add", "work-order_delete_batch"）

    Returns:
        int: 排序层级（0-6），未匹配返回 -1

    Examples:
        >>> get_case_tier("cloud-question_add")
        0
        >>> get_case_tier("work-order_edit")
        1
        >>> get_case_tier("project_delete_batch")
        6
        >>> get_case_tier("unknown_case")
        -1
    """
    cid = case_id

    # 拆分词段（保留原始大小写 → camelCase 拆分 → 转小写）
    parts = re.split(r'[-_]', cid)
    tokens = []
    for p in parts:
        sub = re.sub(r'([a-z])([A-Z])', r'\1 \2', p).split()
        tokens.extend([s.lower() for s in sub] if sub else [p.lower()])

    max_tier = -1

    # 英文词段精确匹配
    for token in tokens:
        if not token or not token[0].isascii():
            continue
        for i, tier in enumerate(ORDER_TIERS):
            for kw in tier:
                if kw.isascii() and kw == token:
                    max_tier = max(max_tier, i)

    # 中文子串匹配
    cid_lower = cid.lower()
    for i, tier in enumerate(ORDER_TIERS):
        for kw in tier:
            if not kw.isascii() and len(kw) >= 2 and kw in cid_lower:
                max_tier = max(max_tier, i)

    return max_tier
