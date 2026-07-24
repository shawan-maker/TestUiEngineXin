"""UIEngine - 基于 Playwright 的关键字驱动 UI 自动化测试引擎"""
__version__ = "0.0.1"

from UIEngine.basecase import BaseCase
from UIEngine.core.keyword_manager import KeyWordManager
from UIEngine.core.variable_resolver import VariableResolver
from UIEngine.runner.runner import Runner
from UIEngine.reporting.result import TestResult
from UIEngine.caseLog import CaseLogHandler
