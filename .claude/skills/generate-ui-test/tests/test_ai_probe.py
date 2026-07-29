#!/usr/bin/env python3
"""_ai_probe_test.py — R6 AI 探测模块单元测试"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

from probe.ai_probe import (
    init, ai_probe_locator, flush_diagnostics,
    _verify_xpath, _build_prompt, _make_result,
    _TYPE_TAG_MAP, MARKER_MAP,
)


class MockLocator:
    def __init__(self, count_val, tag_val='input', visible=True, raises=False):
        self._count = count_val
        self._tag = tag_val
        self._visible = visible
        self._raises = raises

    def count(self):
        if self._raises:
            raise Exception("invalid xpath")
        return self._count

    @property
    def first(self):
        return self

    def evaluate(self, js):
        if 'tagName' in js:
            return self._tag
        if 'className' in js:
            return 'el-input__inner'
        return ''

    def is_visible(self):
        return self._visible


class MockPage:
    def __init__(self, count_val=1, tag_val='input', visible=True, raises=False):
        self._loc = MockLocator(count_val, tag_val, visible, raises)
        self.url = 'http://example.com'

    def locator(self, xpath_str):
        return self._loc

    def evaluate(self, js, args=None):
        return {'matches': [], 'container': None}


# ── 测试 init / flush ──

def test_init_resets_state():
    init({'enabled': True, 'max_calls': 10})
    count = flush_diagnostics('/tmp')
    assert count == 0


def test_disabled_returns_none():
    init({'enabled': False})
    result = ai_probe_locator(None, {}, '', '', None, [], None, lambda x: x)
    assert result is None


def test_no_config_returns_none():
    init(None)
    result = ai_probe_locator(MockPage(), {'desc': 'test'}, '标签', 'input-generic',
                               None, [], None, lambda x: x)
    assert result is None


def test_no_label_returns_none():
    init({'enabled': True})
    result = ai_probe_locator(MockPage(), {'desc': 'test'}, '', 'input-generic',
                               None, [], None, lambda x: x)
    assert result is None


def test_no_page_returns_none():
    init({'enabled': True})
    result = ai_probe_locator(None, {'desc': 'test'}, '标签', 'input-generic',
                               None, [], None, lambda x: x)
    assert result is None


# ── 测试 _verify_xpath ──

def test_verify_high():
    page = MockPage(count_val=1, tag_val='input', visible=True)
    conf, det = _verify_xpath(page, '//input', 'input-generic', lambda x: x)
    assert conf == 'high'
    assert det['count'] == 1


def test_verify_semantic_mismatch():
    page = MockPage(count_val=1, tag_val='div', visible=True)
    conf, det = _verify_xpath(page, '//div', 'input-generic', lambda x: x)
    assert conf == 'semantic-mismatch'
    assert 'tag=div' in det['notes']


def test_verify_hidden():
    page = MockPage(count_val=1, tag_val='input', visible=False)
    conf, det = _verify_xpath(page, '//input', 'input-generic', lambda x: x)
    assert conf == 'semantic-mismatch'
    assert 'not visible' in det['notes']


def test_verify_multiple():
    page = MockPage(count_val=3, tag_val='button', visible=True)
    conf, det = _verify_xpath(page, '//button', 'button', lambda x: x)
    assert conf == 'multiple'
    assert det['count'] == 3


def test_verify_zero():
    page = MockPage(count_val=0)
    conf, det = _verify_xpath(page, '//input', 'input-generic', lambda x: x)
    assert conf == 'zero'
    assert det['count'] == 0


def test_verify_error():
    page = MockPage(raises=True)
    conf, det = _verify_xpath(page, '[[[', 'input-generic', lambda x: x)
    assert conf == 'error'
    assert 'error' in det


# ── 测试 _build_prompt ──

def test_prompt_with_dom():
    dom = {'matches': [{'html': '<div class="el-form-item">...</div>',
                         'tag': 'div', 'classes': 'el-form-item',
                         'parentTag': 'div', 'parentClasses': ''}],
           'container': None}
    prompt = _build_prompt('在「备注」中输入', '备注', 'textarea-generic',
                            'drawer', 'http://example.com', [], dom)
    assert 'el-form-item' in prompt
    assert '备注' in prompt
    assert 'drawer' in prompt
    assert 'XPath' in prompt


def test_prompt_no_dom():
    prompt = _build_prompt('test', '标签', 'input-generic', None, '', [], None)
    assert 'DOM 中未找到' in prompt


def test_prompt_with_container():
    dom = {'matches': [],
           'container': {'tag': 'div', 'classes': 'el-drawer',
                         'children': [{'tag': 'div', 'classes': 'el-drawer__body',
                                       'text': ''}]}}
    prompt = _build_prompt('test', '标签', 'input-generic', 'drawer', '', [], dom)
    assert 'el-drawer' in prompt


def test_prompt_with_steps():
    steps = [
        {'desc': '点击新增', 'keyword': 'click_element'},
        {'desc': '填写名称', 'keyword': 'fill_value'},
    ]
    prompt = _build_prompt('test', '标签', 'input-generic', None, '', steps, None)
    assert '点击新增' in prompt
    assert '填写名称' in prompt


# ── 测试 _make_result ──

def test_make_result_high():
    r = _make_result('xpath=//input', 'ai-probe-high')
    assert r['locator'] == 'xpath=//input'
    assert r['is_best_guess'] == True
    assert r['hit_source'] == 'ai-probe-high'
    assert r['marker'] == '[AI-PROBE]'


def test_make_result_l0():
    r = _make_result('xpath=//button', 'ai-probe-l0')
    assert r['marker'] == '[AI-PROBE-L0]'


def test_make_result_medium():
    r = _make_result('xpath=(//input)[1]', 'ai-probe-medium')
    assert r['marker'] == '[AI-PROBE-WARN]'


def test_make_result_unknown_source():
    r = _make_result('xpath=//input', 'unknown')
    assert r['marker'] == '[AI-PROBE]'  # 默认 fallback


# ── 测试 marker 映射完整性 ──

def test_marker_map():
    assert MARKER_MAP['ai-probe-l0'] == '[AI-PROBE-L0]'
    assert MARKER_MAP['ai-probe-high'] == '[AI-PROBE]'
    assert MARKER_MAP['ai-probe-medium'] == '[AI-PROBE-WARN]'
    assert len(MARKER_MAP) == 3


# ── 测试 type tag map 完整性 ──

def test_type_tag_map_covers_common_types():
    required = {'input-generic', 'textarea-generic', 'button',
                'table-action-button', 'el-select', 'el-cascader',
                'submit-btn', 'tab'}
    assert required.issubset(set(_TYPE_TAG_MAP.keys()))


def test_type_tag_map_values_are_tuples():
    for k, v in _TYPE_TAG_MAP.items():
        assert isinstance(v, tuple), f"{k} should be tuple, got {type(v)}"
        assert all(isinstance(t, str) for t in v), f"{k} contains non-string"


# ── 测试 flush_diagnostics ──

def test_flush_resets_state():
    init({'enabled': True})
    # 模拟添加诊断
    from probe import ai_probe as ap
    ap._diagnoses.append({'test': True})
    ap._ai_call_count = 5

    count = flush_diagnostics('/tmp')
    assert count == 1
    assert ap._ai_call_count == 0
    assert len(ap._diagnoses) == 0


def test_flush_empty():
    init({'enabled': True})
    count = flush_diagnostics('/tmp')
    assert count == 0


# ── 测试 ai_probe_locator 边界条件 ──

def test_ai_probe_max_calls_reached():
    init({'enabled': True, 'max_calls': 0, 'layer0_enabled': False})
    page = MockPage(count_val=1, tag_val='input', visible=True)
    result = ai_probe_locator(page, {'desc': 'test'}, '标签', 'input-generic',
                               None, [], None, lambda x: x)
    assert result is None


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in sorted(globals().items())
             if k.startswith('test_') and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    sys.exit(1 if failed else 0)
