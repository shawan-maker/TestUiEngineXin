#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 _resolve_step_url 函数"""

import sys
import os

# 添加 skill 根目录到路径，使 tools 成为可导入的包
_skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _skill_root)

from tools.excel.read_excel import _resolve_step_url, _URL_EXTRACT_RE


def test_resolve_step_url():
    """测试各种 URL 解析场景"""

    base_url = "http://console.example.com"

    # 测试1: 完整 URL 应保持不变
    assert _resolve_step_url("https://other.com/vm/list", base_url) == "https://other.com/vm/list"
    assert _resolve_step_url("http://console.example.com/vm", base_url) == "http://console.example.com/vm"

    # 测试2: 相对路径应拼接
    assert _resolve_step_url("/estack/web/vm/list", base_url) == "http://console.example.com/estack/web/vm/list"
    assert _resolve_step_url("/#/order/vm", base_url) == "http://console.example.com/#/order/vm"

    # 测试3: base_url 末尾有 / 应正确处理
    base_url_with_slash = "http://console.example.com/"
    assert _resolve_step_url("/vm/list", base_url_with_slash) == "http://console.example.com/vm/list"

    # 测试4: base_url 为空时应返回原值
    assert _resolve_step_url("/vm/list", "") == "/vm/list"
    assert _resolve_step_url("/vm/list", None) == "/vm/list"

    # 测试5: hash 路由
    assert _resolve_step_url("/#/payment", base_url) == "http://console.example.com/#/payment"
    assert _resolve_step_url("/#/order/vm?orderSource=list", base_url) == "http://console.example.com/#/order/vm?orderSource=list"

    # 测试6: 带 query 参数的相对路径
    assert _resolve_step_url("/vm/list?page=1", base_url) == "http://console.example.com/vm/list?page=1"

    # 测试7: 非 / 开头的内容应返回原值
    assert _resolve_step_url("vm/list", base_url) == "vm/list"
    assert _resolve_step_url("首页", base_url) == "首页"

    print("[OK] All _resolve_step_url tests passed")


def test_url_regex():
    """测试 URL 提取正则"""
    # 测试1: 完整 URL
    m = _URL_EXTRACT_RE.search("访问 https://example.com/vm/list")
    assert m and m.group(1) == "https://example.com/vm/list"

    # 测试2: 相对路径
    m = _URL_EXTRACT_RE.search("访问 /estack/web/vm/list")
    assert m and m.group(1) == "/estack/web/vm/list"

    # 测试3: hash 路由
    m = _URL_EXTRACT_RE.search("访问 /#/order/vm")
    assert m and m.group(1) == "/#/order/vm"

    # 测试4: 带 query 参数
    m = _URL_EXTRACT_RE.search("访问 /vm/list?page=1&size=10")
    assert m and m.group(1) == "/vm/list?page=1&size=10"

    # 测试5: 非 URL 步骤不应匹配
    m = _URL_EXTRACT_RE.search("点击确认按钮")
    assert m is None

    # 测试6: 以 / 开头但后面有中文（边界情况）
    m = _URL_EXTRACT_RE.search("访问 /vm/list 页面")
    assert m and m.group(1) == "/vm/list"  # \S+ 会在空格处停止

    # 测试7: 完整 URL 和相对路径混合格式（空格分隔）
    m = _URL_EXTRACT_RE.search("先访问 https://a.com 再访问 /b/c")
    assert m and m.group(1) == "https://a.com"  # 取第一个匹配

    print("[OK] All URL regex tests passed")


if __name__ == "__main__":
    test_resolve_step_url()
    test_url_regex()
    print("\n[PASS] All tests passed!")
