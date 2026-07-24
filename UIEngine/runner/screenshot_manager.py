"""截图目录管理器

管理测试套件的截图目录：
- 每个套件自动创建独立目录（套件名为目录名）
- 引擎项目内最多保留 10 个套件目录（自动清理最旧的）
- 用户自定义的外部路径不限制，由用户自行管理
"""
import os
import shutil


class ScreenshotManager:
    """截图目录管理器"""

    DEFAULT_MAX_DIRS = 10  # 引擎项目内默认最大套件目录数

    def __init__(self, base_path, log, max_dirs=None):
        """
        :param base_path: 截图基础路径（默认 <project_dir>/files/shortcuts，用户可通过 config 自定义）
        :param log: 日志处理器
        :param max_dirs: 最大保留套件目录数（默认 10）
        """
        self.base_path = base_path
        self.log = log
        self.max_dirs = max_dirs or self.DEFAULT_MAX_DIRS

    def create_suite_dir(self, suite_name):
        """创建套件截图目录

        如果基础路径在引擎项目内，执行清理策略（保留 max_dirs 个）。
        如果基础路径在引擎项目外（用户自定义），不做限制。

        :param suite_name: 测试套件名称
        :return: 套件截图目录的完整路径
        """
        suite_dir = os.path.join(self.base_path, suite_name)
        if not os.path.exists(suite_dir):
            os.makedirs(suite_dir)
        # 仅在引擎项目内执行清理
        if self._is_inside_engine_project():
            self._cleanup_old_dirs()
        return suite_dir

    def _is_inside_engine_project(self):
        """判断基础路径是否在引擎项目目录内"""
        engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.abspath(self.base_path).startswith(engine_root)

    def _cleanup_old_dirs(self):
        """清理旧的套件目录，保留最新的 max_dirs 个"""
        if not os.path.exists(self.base_path):
            return
        # 收集所有子目录及其修改时间
        dirs = []
        for entry in os.listdir(self.base_path):
            full_path = os.path.join(self.base_path, entry)
            if os.path.isdir(full_path):
                dirs.append((full_path, os.path.getmtime(full_path)))
        # 按修改时间倒序排列（最新在前）
        dirs.sort(key=lambda x: x[1], reverse=True)
        # 删除超出限制的旧目录
        for old_dir, _ in dirs[self.max_dirs:]:
            try:
                shutil.rmtree(old_dir)
                self.log.debug_log(f"清理旧截图目录: {old_dir}")
            except Exception as e:
                self.log.warning_log(f"清理截图目录失败: {old_dir}, 原因: {e}")
