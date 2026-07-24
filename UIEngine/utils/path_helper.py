"""项目路径工具

提供统一的项目目录解析逻辑，确保引擎层的日志、截图、报告
都输出到用户项目目录，而非引擎安装目录。
"""
import inspect
import os


def get_project_dir(config=None):
    """解析项目目录，优先级从高到低：

    1. config["project_dir"] —— 用户显式指定
    2. 环境变量 UIENGINE_PROJECT_DIR
    3. 调用栈中 run.py 所在目录
    4. 当前工作目录（兜底）

    :param config: 配置字典（可选）
    :return: 项目目录的绝对路径
    """
    # 1. 配置显式指定
    if config and config.get("project_dir"):
        return os.path.abspath(config["project_dir"])

    # 2. 环境变量
    env_dir = os.environ.get("UIENGINE_PROJECT_DIR", "").strip()
    if env_dir and os.path.isdir(env_dir):
        return os.path.abspath(env_dir)

    # 3. 调用栈中查找 run.py
    for frame_info in inspect.stack():
        filename = os.path.basename(frame_info.filename)
        if filename == 'run.py':
            return os.path.dirname(os.path.abspath(frame_info.filename))

    # 4. 兜底：当前工作目录
    return os.getcwd()
