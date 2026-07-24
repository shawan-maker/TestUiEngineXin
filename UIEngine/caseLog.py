"""用例日志处理类

基于 Python 标准 logging 模块实现，对外接口与原版完全兼容。
- log_data 属性保持 [(level, msg), ...] 格式
- debug_log/info_log/warning_log/error_log 等方法名不变
- 支持日志级别过滤、文件输出等 logging 原生能力
"""
import logging
import os
import time
from pathlib import Path


class _MemoryHandler(logging.Handler):
    """内存日志 Handler：将日志记录存储为兼容原有格式的列表"""

    def __init__(self):
        super().__init__()
        self.log_data = []

    def emit(self, record):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        msg = f"{ts} | {record.getMessage()}"
        self.log_data.append((record.levelname, msg))


class CaseLogHandler:
    """用例日志处理类（基于 logging 模块）

    对外接口与原版完全兼容：
    - debug_log / info_log / warning_log / error_log / critical_log / print_log
    - log_data 属性返回 [(level, msg), ...] 列表
    """

    def __init__(self, name="testcase", console=True, level=logging.DEBUG):
        """
        :param name: logger 名称（不同用例建议使用不同名称避免日志混合）
        :param console: 是否输出到控制台
        :param level: 最低日志级别
        """
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        # 避免重复添加 handler（同名 logger 多次实例化时）
        if not self._logger.handlers:
            # 内存 Handler（用于结果数据收集）
            self._memory = _MemoryHandler()
            self._logger.addHandler(self._memory)
            # 控制台 Handler（用于实时输出）
            if console:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(
                    logging.Formatter("%(levelname)s | %(message)s")
                )
                self._logger.addHandler(console_handler)
        else:
            # 复用已有 handler，找到 memory handler
            self._memory = next(
                (h for h in self._logger.handlers if isinstance(h, _MemoryHandler)),
                _MemoryHandler()
            )

    @property
    def log_data(self):
        """兼容 Runner 中 getattr(self.log, 'log_data') 的访问方式"""
        return self._memory.log_data

    def _format_args(self, args):
        """将可变参数拼接为字符串"""
        return " ".join(str(i) for i in args)

    def debug_log(self, *args):
        """记录 debug 日志"""
        self._logger.debug(self._format_args(args))

    def info_log(self, *args):
        """记录 info 日志"""
        self._logger.info(self._format_args(args))

    def warning_log(self, *args):
        """记录 warning 日志"""
        self._logger.warning(self._format_args(args))

    def error_log(self, *args):
        """记录 error 日志"""
        self._logger.error(self._format_args(args))

    def critical_log(self, *args):
        """记录 critical 日志"""
        self._logger.critical(self._format_args(args))

    def print_log(self, *args):
        """记录日志（等同 info 级别）"""
        self._logger.info(self._format_args(args))

    def add_file_handler(self, filepath=None, level=logging.DEBUG, max_files=20):
        """添加文件输出 Handler

        :param filepath: 日志文件路径（默认保存到 <project_dir>/files/logs/<name>_<timestamp>.log）
        :param level: 文件日志的最低级别
        :param max_files: 日志文件最大保留数量（默认 20）
        """
        if not filepath:
            from UIEngine.utils.path_helper import get_project_dir
            project_dir = get_project_dir()
            log_dir = Path(project_dir) / "files" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            filepath = str(log_dir / f"{self._logger.name}_{ts}.log")
            # 清理超出限制的旧日志文件
            self._cleanup_log_files(str(log_dir), max_files)

        file_handler = logging.FileHandler(filepath, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        self._logger.addHandler(file_handler)

    @staticmethod
    def _cleanup_log_files(log_dir, max_files):
        """清理旧日志文件，保留最新的 max_files 个"""
        files = []
        for entry in os.listdir(log_dir):
            if entry.endswith('.log'):
                full_path = os.path.join(log_dir, entry)
                files.append((full_path, os.path.getmtime(full_path)))
        files.sort(key=lambda x: x[1], reverse=True)
        for old_file, _ in files[max_files:]:
            try:
                os.remove(old_file)
            except OSError:
                pass

    def set_level(self, level):
        """动态调整日志级别（logging 新增能力）

        :param level: logging.DEBUG / logging.INFO / logging.WARNING 等
        """
        self._logger.setLevel(level)


class PreconditionChainError(Exception):
    """前置条件链执行错误（用于 stop 模式中止）"""
    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"前置条件链中止，共 {len(errors)} 个错误")
