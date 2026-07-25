#!/usr/bin/env python3
"""
单元测试：模块名翻译链路修复

测试覆盖：
  1. build_module_map.py 的三个数据源函数
  2. generate_from_excel.py 的 load_module_map() 优先级
  3. group_cases_by_module() 一个 sheet 多模块场景
  4. find_discovery_json() 文件名匹配（含历史中文文件名兼容）
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

# 添加 tools 目录到 sys.path
SCRIPT_DIR = Path(__file__).parent
TOOLS_DIR = SCRIPT_DIR.parent / 'tools'
sys.path.insert(0, str(TOOLS_DIR))

from build_module_map import (
    _scan_pages_dirs,
    _scan_yaml_comments,
    _scan_discovery_json,
    _build_mapping,
)
from generate_from_excel import (
    load_module_map,
    group_cases_by_module,
    find_discovery_json,
)


class TestBuildModuleMap:
    """测试 build_module_map.py 的核心函数"""

    def test_scan_pages_dirs(self):
        """测试扫描 pages/ 目录获取英文 slug"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir) / 'pages'
            pages_dir.mkdir()

            # 创建英文 slug 目录
            (pages_dir / 'question-manage').mkdir()
            (pages_dir / 'work-order').mkdir()
            (pages_dir / 'project').mkdir()

            # 创建应该被忽略的目录
            (pages_dir / '_internal').mkdir()
            (pages_dir / '.git').mkdir()

            slugs = _scan_pages_dirs(str(pages_dir))

            assert slugs == {'question-manage', 'work-order', 'project'}
            assert '_internal' not in slugs
            assert '.git' not in slugs

    def test_scan_yaml_comments(self):
        """测试扫描 YAML 注释获取中文模块名"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_dir = Path(tmpdir) / 'pages'
            pages_dir.mkdir()

            # 创建带注释的 YAML 文件
            qm_dir = pages_dir / 'question-manage'
            qm_dir.mkdir()
            qm_yaml = qm_dir / 'elements.yaml'
            qm_yaml.write_text(
                '# 模块: 问题管理\n'
                '# 自动生成，请勿修改\n'
                'question_form:\n'
                '  title: ${question_form.title}\n',
                encoding='utf-8'
            )

            wo_dir = pages_dir / 'work-order'
            wo_dir.mkdir()
            wo_yaml = wo_dir / 'elements.yaml'
            wo_yaml.write_text(
                '# 模块: 工单管理\n'
                'work_order_form:\n'
                '  status: ${work_order_form.status}\n',
                encoding='utf-8'
            )

            mapping = _scan_yaml_comments(str(pages_dir))

            assert mapping == {
                '问题管理': 'question-manage',
                '工单管理': 'work-order',
            }

    def test_scan_discovery_json(self):
        """测试扫描 discovery JSON 获取 cn_name"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建带 cn_name 的 discovery JSON
            disc1 = Path(tmpdir) / 'discovery_question-manage.json'
            disc1.write_text(
                json.dumps({
                    'module': 'question-manage',
                    'cn_name': '问题管理',
                    'elements': []
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            disc2 = Path(tmpdir) / 'discovery_work-order.json'
            disc2.write_text(
                json.dumps({
                    'module': 'work-order',
                    'cn_name': '工单管理',
                    'elements': []
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            # 创建没有 cn_name 的 JSON（应该被忽略）
            disc3 = Path(tmpdir) / 'discovery_project.json'
            disc3.write_text(
                json.dumps({
                    'module': 'project',
                    'elements': []
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            mapping = _scan_discovery_json(tmpdir)

            assert mapping == {
                '问题管理': 'question-manage',
                '工单管理': 'work-order',
            }
            assert 'project' not in mapping  # 没有 cn_name 的应该被忽略

    def test_build_mapping_priority(self):
        """测试 _build_mapping 的优先级逻辑"""
        cn_modules = ['问题管理', '工单管理', '项目管理', '系统配置']

        en_slugs = {'question-manage', 'work-order', 'project', 'sys-config'}

        yaml_comments = {
            '问题管理': 'question-manage',
            '工单管理': 'work-order',  # 这个会被 CLI 覆盖
        }

        discovery_map = {
            '项目管理': 'project',
            '工单管理': 'work-order-old',  # 这个会被 YAML 覆盖
        }

        cli_overrides = {
            '工单管理': 'work-order',  # 最高优先级
            '系统配置': 'sys-config',
        }

        result = _build_mapping(
            cn_modules, en_slugs, yaml_comments, discovery_map, cli_overrides
        )

        assert result == {
            '问题管理': 'question-manage',  # 来自 YAML
            '工单管理': 'work-order',  # 来自 CLI（覆盖 YAML 和 discovery）
            '项目管理': 'project',  # 来自 discovery
            '系统配置': 'sys-config',  # 来自 CLI
        }


class TestLoadModuleMap:
    """测试 generate_from_excel.py 的 load_module_map() 优先级"""

    def test_p0_module_map_json(self):
        """P0: 优先读 module_map.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 module_map.json
            map_path = Path(tmpdir) / 'module_map.json'
            map_path.write_text(
                json.dumps({
                    '问题管理': 'question-manage',
                    '工单管理': 'work-order',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            # 创建 discovery JSON（应该被忽略，因为 P0 存在）
            disc_path = Path(tmpdir) / 'discovery_question-manage.json'
            disc_path.write_text(
                json.dumps({
                    'module': 'question-manage',
                    'cn_name': '问题管理',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            mapping = load_module_map(tmpdir, '')

            assert mapping == {
                '问题管理': 'question-manage',
                '工单管理': 'work-order',
            }

    def test_p1_discovery_cn_name(self):
        """P1: 回退到 discovery JSON 的 cn_name"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 不创建 module_map.json

            # 创建 discovery JSON
            disc1 = Path(tmpdir) / 'discovery_question-manage.json'
            disc1.write_text(
                json.dumps({
                    'module': 'question-manage',
                    'cn_name': '问题管理',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            disc2 = Path(tmpdir) / 'discovery_work-order.json'
            disc2.write_text(
                json.dumps({
                    'module': 'work-order',
                    'cn_name': '工单管理',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            mapping = load_module_map(tmpdir, '')

            assert mapping == {
                '问题管理': 'question-manage',
                '工单管理': 'work-order',
            }

    def test_p2_cli_override(self):
        """P2: CLI 参数覆盖"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 module_map.json
            map_path = Path(tmpdir) / 'module_map.json'
            map_path.write_text(
                json.dumps({
                    '问题管理': 'question-manage',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            # CLI 覆盖
            cli_str = '问题管理=question,工单管理=work-order'

            mapping = load_module_map(tmpdir, cli_str)

            assert mapping == {
                '问题管理': 'question',  # 被 CLI 覆盖
                '工单管理': 'work-order',  # 新增
            }


class TestGroupCasesByModule:
    """测试 group_cases_by_module() 一个 sheet 多模块场景"""

    def test_one_sheet_multi_modules(self):
        """一个 sheet 包含多个模块的用例"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 module_map.json
            map_path = Path(tmpdir) / 'module_map.json'
            map_path.write_text(
                json.dumps({
                    '问题管理': 'question-manage',
                    '工单管理': 'work-order',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            # 创建 Excel JSON（一个 sheet，两个模块）
            excel_data = {
                'sheets': [
                    {
                        'sheet': '测试用例',
                        'cases': [
                            {
                                'module': '问题管理',
                                'case_name': '新建问题',
                                'steps': ['点击新建', '填写标题', '保存'],
                            },
                            {
                                'module': '问题管理',
                                'case_name': '编辑问题',
                                'steps': ['点击编辑', '修改标题', '保存'],
                            },
                            {
                                'module': '工单管理',
                                'case_name': '新建工单',
                                'steps': ['点击新建', '选择类型', '保存'],
                            },
                        ]
                    }
                ]
            }

            result = group_cases_by_module(excel_data, '', tmpdir)

            # 应该按 slug 分组
            assert set(result.keys()) == {'question-manage', 'work-order'}
            assert len(result['question-manage']) == 2
            assert len(result['work-order']) == 1

            # 验证用例内容
            qm_names = [c['case_name'] for c in result['question-manage']]
            assert '新建问题' in qm_names
            assert '编辑问题' in qm_names

    def test_multi_sheets(self):
        """多个 sheet，每个 sheet 一个模块"""
        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = Path(tmpdir) / 'module_map.json'
            map_path.write_text(
                json.dumps({
                    '问题管理': 'question-manage',
                    '工单管理': 'work-order',
                }, ensure_ascii=False),
                encoding='utf-8'
            )

            excel_data = {
                'sheets': [
                    {
                        'sheet': '问题管理',
                        'cases': [
                            {
                                'module': '问题管理',
                                'case_name': '新建问题',
                                'steps': ['步骤1'],
                            },
                        ]
                    },
                    {
                        'sheet': '工单管理',
                        'cases': [
                            {
                                'module': '工单管理',
                                'case_name': '新建工单',
                                'steps': ['步骤1'],
                            },
                        ]
                    },
                ]
            }

            result = group_cases_by_module(excel_data, '', tmpdir)

            assert set(result.keys()) == {'question-manage', 'work-order'}
            assert len(result['question-manage']) == 1
            assert len(result['work-order']) == 1


class TestFindDiscoveryJson:
    """测试 find_discovery_json() 文件名匹配"""

    def test_hyphen_underscore_variants(self):
        """连字符和下划线变体匹配"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建带下划线的文件
            (Path(tmpdir) / 'discovery_question_manage.json').touch()

            # 应该能找到（slug 转为下划线）
            result = find_discovery_json(tmpdir, 'question-manage')
            assert result is not None
            assert 'question_manage' in result

    def test_merged_file(self):
        """_merged.json 后缀匹配"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'discovery_work_order_merged.json').touch()

            result = find_discovery_json(tmpdir, 'work-order')
            assert result is not None
            assert 'merged' in result

    def test_chinese_filename_compat(self):
        """历史中文文件名兼容（子串模糊匹配）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建中文文件名（历史遗留）
            (Path(tmpdir) / 'discovery_问题管理.json').touch()

            # 子串匹配应该能找到
            result = find_discovery_json(tmpdir, '问题管理')
            assert result is not None
            assert '问题管理' in result


def run_tests():
    """运行所有测试"""
    test_classes = [
        TestBuildModuleMap,
        TestLoadModuleMap,
        TestGroupCasesByModule,
        TestFindDiscoveryJson,
    ]

    total = 0
    passed = 0
    failed = 0

    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"运行 {test_class.__name__}")
        print('='*60)

        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith('test_')]

        for method_name in methods:
            total += 1
            method = getattr(instance, method_name)

            try:
                method()
                print(f"  [PASS] {method_name}")
                passed += 1
            except Exception as e:
                print(f"  [FAIL] {method_name}")
                print(f"  错误: {e}")
                failed += 1

    print(f"\n{'='*60}")
    print(f"测试结果: {passed}/{total} 通过")
    print('='*60)

    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
