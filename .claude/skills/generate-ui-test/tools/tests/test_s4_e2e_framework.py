"""端到端框架兼容性测试

验证 framework_registry 在实际项目中的端到端行为
"""
import os
import json
import tempfile
import shutil
import pytest
from pathlib import Path

# 测试项目结构
TEST_PROJECT = {
    "config.yaml": """
browser:
  headless: true
  slow_mo: 0

ai_probe:
  enabled: true
  model: "gpt-4"
  max_calls: 10
""",
    "framework.json": {"framework": "element-ui"},
    "_probe": {
        "framework.json": {"framework": "element-ui"},
    },
}


@pytest.fixture
def element_ui_project(tmp_path):
    """创建 Element UI 测试项目"""
    project_dir = tmp_path / "element_ui_project"
    project_dir.mkdir()

    # 创建目录结构
    (project_dir / "_probe").mkdir()
    (project_dir / "pages").mkdir()

    # 写入文件
    for filename, content in TEST_PROJECT.items():
        if isinstance(content, dict):
            continue
        file_path = project_dir / filename
        if not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    # 写入 framework.json
    fw_path = project_dir / "_probe" / "framework.json"
    fw_path.write_text(json.dumps(TEST_PROJECT["_probe"]["framework.json"]), encoding="utf-8")

    # 创建空的 discovery.json（ElementResolver 需要）
    discovery_path = project_dir / "_probe" / "discovery.json"
    discovery_path.write_text("{}", encoding="utf-8")

    return project_dir


@pytest.fixture
def antd_project(tmp_path):
    """创建 Ant Design 测试项目"""
    project_dir = tmp_path / "antd_project"
    project_dir.mkdir()

    # 创建目录结构
    (project_dir / "_probe").mkdir()
    (project_dir / "pages").mkdir()

    # 写入文件（Ant Design）
    config_content = TEST_PROJECT["config.yaml"]
    (project_dir / "config.yaml").write_text(config_content, encoding="utf-8")

    fw_content = {"framework": "ant-design"}
    fw_path = project_dir / "_probe" / "framework.json"
    fw_path.write_text(json.dumps(fw_content), encoding="utf-8")

    # 创建空的 discovery.json（ElementResolver 需要）
    discovery_path = project_dir / "_probe" / "discovery.json"
    discovery_path.write_text("{}", encoding="utf-8")

    return project_dir


class TestEndToEndElementUI:
    """Element UI 端到端测试"""

    def test_ai_probe_initialization(self, element_ui_project):
        """测试 AI 探针初始化（Element UI）"""
        from probe.ai_probe import init, flush_diagnostics

        # 读取配置
        config_path = element_ui_project / "config.yaml"
        import yaml
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 读取框架
        fw_path = element_ui_project / "_probe" / "framework.json"
        with open(fw_path, encoding="utf-8") as f:
            fw_data = json.load(f)
            framework = fw_data.get("framework")

        # 初始化
        init(config["ai_probe"], framework=framework)

        # 验证框架变量
        from probe import ai_probe
        assert ai_probe._framework == "element-ui"
        assert ai_probe._XPATH_FROM_ELEMENT_JS is not None
        assert ai_probe._DOM_EXTRACT_JS is not None
        assert ai_probe._PAGE_SUMMARY_JS is not None

        # 验证 JS 代码包含 Element UI 特征
        assert "el-dialog" in ai_probe._XPATH_FROM_ELEMENT_JS
        assert "el-form-item" in ai_probe._XPATH_FROM_ELEMENT_JS

        # 清理
        flush_diagnostics(element_ui_project)

    def test_case_generator_framework_awareness(self, element_ui_project):
        """测试用例生成器的框架感知（Element UI）"""
        from generation.case_generator import CaseGenerator
        from core.element_resolver import ElementResolver

        # 使用正确的 API：discovery_paths 列表
        discovery_file = element_ui_project / "_probe" / "discovery.json"
        resolver = ElementResolver(
            discovery_paths=[str(discovery_file)],
            project_dir=str(element_ui_project),
        )

        # 创建生成器
        generator = CaseGenerator(
            resolver=resolver,
            module_name="test_module",
            project_dir=str(element_ui_project),
            framework="element-ui",
        )

        # 验证框架感知
        assert generator._framework == "element-ui"

        # 测试下拉选项 XPath 生成
        option_xpath = generator._build_dropdown_option_xpath("删除")
        assert "xpath=" in option_xpath
        assert "dropdown" in option_xpath.lower() or "menu" in option_xpath.lower()

    def test_pages_writer_element_ui_templates(self, element_ui_project):
        """测试页面写入器的 Element UI 模板"""
        from generation.pages_writer import (
            PagesWriter,
            DEFAULT_COMMON_ELEMENTS,
        )
        from core.element_resolver import ElementResolver

        # 验证 Element UI 默认模板包含常见元素
        assert "confirm_btn" in DEFAULT_COMMON_ELEMENTS
        assert "cancel_btn" in DEFAULT_COMMON_ELEMENTS

        # 创建 resolver 和写入器
        discovery_file = element_ui_project / "_probe" / "discovery.json"
        resolver = ElementResolver(
            discovery_paths=[str(discovery_file)],
            project_dir=str(element_ui_project),
        )

        writer = PagesWriter(
            element_resolver=resolver,
            framework="element-ui",
        )

        # 验证框架感知
        assert writer._framework == "element-ui"


class TestEndToEndAntDesign:
    """Ant Design 端到端测试"""

    def test_ai_probe_initialization(self, antd_project):
        """测试 AI 探针初始化（Ant Design）"""
        from probe.ai_probe import init, flush_diagnostics

        # 读取配置
        config_path = antd_project / "config.yaml"
        import yaml
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 读取框架
        fw_path = antd_project / "_probe" / "framework.json"
        with open(fw_path, encoding="utf-8") as f:
            fw_data = json.load(f)
            framework = fw_data.get("framework")

        # 初始化
        init(config["ai_probe"], framework=framework)

        # 验证框架变量
        from probe import ai_probe
        assert ai_probe._framework == "ant-design"
        assert ai_probe._XPATH_FROM_ELEMENT_JS is not None
        assert ai_probe._DOM_EXTRACT_JS is not None
        assert ai_probe._PAGE_SUMMARY_JS is not None

        # 验证 JS 代码包含 Ant Design 特征
        assert "ant-modal" in ai_probe._XPATH_FROM_ELEMENT_JS
        assert "ant-form-item" in ai_probe._XPATH_FROM_ELEMENT_JS

        # 清理
        flush_diagnostics(antd_project)

    def test_case_generator_framework_awareness(self, antd_project):
        """测试用例生成器的框架感知（Ant Design）"""
        from generation.case_generator import CaseGenerator
        from core.element_resolver import ElementResolver

        # 使用正确的 API：discovery_paths 列表
        discovery_file = antd_project / "_probe" / "discovery.json"
        resolver = ElementResolver(
            discovery_paths=[str(discovery_file)],
            project_dir=str(antd_project),
        )

        # 创建生成器
        generator = CaseGenerator(
            resolver=resolver,
            module_name="test_module",
            project_dir=str(antd_project),
            framework="ant-design",
        )

        # 验证框架感知
        assert generator._framework == "ant-design"

        # 测试下拉选项 XPath 生成
        option_xpath = generator._build_dropdown_option_xpath("删除")
        assert "xpath=" in option_xpath
        assert "ant-dropdown" in option_xpath or "menu" in option_xpath.lower()

    def test_pages_writer_antd_templates(self, antd_project):
        """测试页面写入器的 Ant Design 模板"""
        from generation.pages_writer import (
            PagesWriter,
            DEFAULT_COMMON_ELEMENTS_ANTD,
        )
        from core.element_resolver import ElementResolver

        # 验证 Ant Design 模板包含常见元素
        assert "confirm_btn" in DEFAULT_COMMON_ELEMENTS_ANTD
        assert "cancel_btn" in DEFAULT_COMMON_ELEMENTS_ANTD

        # 创建 resolver 和写入器
        discovery_file = antd_project / "_probe" / "discovery.json"
        resolver = ElementResolver(
            discovery_paths=[str(discovery_file)],
            project_dir=str(antd_project),
        )

        writer = PagesWriter(
            element_resolver=resolver,
            framework="ant-design",
        )

        # 验证框架感知
        assert writer._framework == "ant-design"


class TestEndToEndFallback:
    """回退机制测试"""

    def test_none_framework_fallbacks_to_element_ui(self, tmp_path):
        """测试 framework=None 回退到 Element UI"""
        project_dir = tmp_path / "fallback_project"
        project_dir.mkdir()
        (project_dir / "_probe").mkdir()

        from probe.ai_probe import init, flush_diagnostics

        config = {
            "enabled": True,
            "model": "gpt-4",
            "max_calls": 10,
        }

        # 初始化（framework=None）
        init(config, framework=None)

        # 验证回退到 Element UI
        from probe import ai_probe
        assert ai_probe._framework == "element-ui"
        assert "el-dialog" in ai_probe._XPATH_FROM_ELEMENT_JS

        # 清理
        flush_diagnostics(project_dir)


class TestEndToEndIntegration:
    """集成测试：验证各组件协同工作"""

    def test_full_pipeline_element_ui(self, element_ui_project):
        """测试完整管线（Element UI）"""
        from probe.ai_probe import init as ai_probe_init, flush_diagnostics
        from generation.case_generator import CaseGenerator
        from core.element_resolver import ElementResolver
        from generation.pages_writer import PagesWriter
        import yaml

        # 1. 初始化 AI 探针
        config_path = element_ui_project / "config.yaml"
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        fw_path = element_ui_project / "_probe" / "framework.json"
        with open(fw_path, encoding="utf-8") as f:
            fw_data = json.load(f)
            framework = fw_data.get("framework")

        ai_probe_init(config["ai_probe"], framework=framework)

        # 2. 创建用例生成器
        discovery_file = element_ui_project / "_probe" / "discovery.json"
        resolver = ElementResolver(
            discovery_paths=[str(discovery_file)],
            project_dir=str(element_ui_project),
        )
        generator = CaseGenerator(
            resolver=resolver,
            module_name="test_module",
            project_dir=str(element_ui_project),
            framework=framework,
        )

        # 3. 创建页面写入器
        writer = PagesWriter(
            element_resolver=resolver,
            framework=framework,
        )

        # 验证所有组件使用相同框架
        from probe import ai_probe
        assert ai_probe._framework == "element-ui"
        assert generator._framework == "element-ui"
        assert writer._framework == "element-ui"

        # 清理
        flush_diagnostics(element_ui_project)

    def test_full_pipeline_antd(self, antd_project):
        """测试完整管线（Ant Design）"""
        from probe.ai_probe import init as ai_probe_init, flush_diagnostics
        from generation.case_generator import CaseGenerator
        from core.element_resolver import ElementResolver
        from generation.pages_writer import PagesWriter
        import yaml

        # 1. 初始化 AI 探针
        config_path = antd_project / "config.yaml"
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        fw_path = antd_project / "_probe" / "framework.json"
        with open(fw_path, encoding="utf-8") as f:
            fw_data = json.load(f)
            framework = fw_data.get("framework")

        ai_probe_init(config["ai_probe"], framework=framework)

        # 2. 创建用例生成器
        discovery_file = antd_project / "_probe" / "discovery.json"
        resolver = ElementResolver(
            discovery_paths=[str(discovery_file)],
            project_dir=str(antd_project),
        )
        generator = CaseGenerator(
            resolver=resolver,
            module_name="test_module",
            project_dir=str(antd_project),
            framework=framework,
        )

        # 3. 创建页面写入器
        writer = PagesWriter(
            element_resolver=resolver,
            framework=framework,
        )

        # 验证所有组件使用相同框架
        from probe import ai_probe
        assert ai_probe._framework == "ant-design"
        assert generator._framework == "ant-design"
        assert writer._framework == "ant-design"

        # 清理
        flush_diagnostics(antd_project)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
