#!/usr/bin/env python3
"""
reconcile_probe_labels.py - Probe 标签白名单校验器

读取 probe JSON 和 whitelist JSON，对每个元素的标签进行白名单校验。
不在白名单中的标签尝试模糊匹配修正，修正结果写入新的 probe JSON。

用法:
    python reconcile_probe_labels.py probe.json whitelist.json output.json [--module MODULE]

参数:
    probe.json      探测结果 JSON 文件
    whitelist.json  标签白名单 JSON 文件（read_excel.py --extract-labels 输出）
    output.json     修正后的输出 JSON 文件
    --module MODULE 指定模块名（匹配 whitelist 中的 sheet_name）

输出:
    - 修正后的 probe JSON（包含 label_corrected 和 original_label 字段）
    - corrections.json 修正日志（同目录下）
"""

import argparse
import difflib
import json
import os
import sys


def load_whitelist(path, module=None):
    """加载白名单，返回 label_set 列表"""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    # 如果指定了 module，只返回该模块的标签
    if module:
        for sheet_name, info in data.items():
            if info.get('sheet_name') == module or sheet_name == module:
                return info.get('label_set', [])
        return []

    # 未指定 module，返回所有模块的标签并集
    all_labels = set()
    for info in data.values():
        all_labels.update(info.get('label_set', []))
    return list(all_labels)


def reconcile_label(label, label_set):
    """校验标签是否在白名单中，不在则模糊匹配。
    返回 (final_label, action, confidence)
    action: 'pass' | 'auto_correct' | 'warn' | 'info'
    """
    if label_set is None:
        return label, 'no_whitelist', 1.0

    if label in label_set:
        return label, 'pass', 1.0

    # 模糊匹配
    scores = []
    for wl_label in label_set:
        ratio = difflib.SequenceMatcher(None, label, wl_label).ratio()
        scores.append((wl_label, ratio))

    scores.sort(key=lambda x: x[1], reverse=True)
    best_label, best_score = scores[0] if scores else (None, 0.0)

    if best_score >= 0.7:
        return best_label, 'auto_correct', best_score
    elif best_score >= 0.5:
        return label, 'warn', best_score
    else:
        return label, 'info', best_score


def reconcile_probe(probe_path, whitelist_path, output_path, module=None):
    """对 probe JSON 进行标签白名单校验和修正"""

    # 加载 probe
    with open(probe_path, encoding='utf-8') as f:
        probe = json.load(f)

    # 加载白名单
    label_set = load_whitelist(whitelist_path, module)
    if label_set is None:
        print(f"[WARN] 白名单文件不存在: {whitelist_path}", file=sys.stderr)
        # 直接复制原文件
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(probe, f, ensure_ascii=False, indent=2)
        return

    # 校验每个元素
    corrections = []
    for el in probe.get('elements', []):
        label = el.get('label', '')
        if not label:
            continue

        new_label, action, confidence = reconcile_label(label, label_set)

        if action == 'auto_correct':
            print(f"[FIX] \"{label}\" → \"{new_label}\" (相似度 {confidence:.0%})")
            el['original_label'] = label
            el['label'] = new_label
            el['label_corrected'] = True
            el['correction_confidence'] = round(confidence, 3)
            corrections.append({
                'original': label,
                'corrected': new_label,
                'confidence': round(confidence, 3),
                'key': el.get('key', ''),
            })
        elif action == 'warn':
            print(f"[WARN] \"{label}\" 不在白名单中，最接近: \"{new_label}\" (相似度 {confidence:.0%})")
        elif action == 'info':
            print(f"[INFO] \"{label}\" 不在白名单中，保留原标签")

    # 写入修正后的 probe
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(probe, f, ensure_ascii=False, indent=2)

    print(f"[OK] 修正后的 probe 已写入: {output_path}")

    # 写入修正日志
    if corrections:
        corrections_path = os.path.join(os.path.dirname(output_path), 'corrections.json')
        with open(corrections_path, 'w', encoding='utf-8') as f:
            json.dump(corrections, f, ensure_ascii=False, indent=2)
        print(f"[INFO] 修正日志已写入: {corrections_path}")

    return len(corrections)


def main():
    parser = argparse.ArgumentParser(
        description='Probe 标签白名单校验器'
    )
    parser.add_argument('probe', help='探测结果 JSON 文件')
    parser.add_argument('whitelist', help='标签白名单 JSON 文件')
    parser.add_argument('output', help='修正后的输出 JSON 文件')
    parser.add_argument('--module', help='指定模块名（匹配 whitelist 中的 sheet_name）')

    args = parser.parse_args()

    if not os.path.exists(args.probe):
        print(f"[ERROR] probe 文件不存在: {args.probe}", file=sys.stderr)
        sys.exit(1)

    reconcile_probe(args.probe, args.whitelist, args.output, args.module)


if __name__ == '__main__':
    main()
