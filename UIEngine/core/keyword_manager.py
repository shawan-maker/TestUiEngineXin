"""关键字管理器：维护关键字名称与函数的映射关系

支持功能：
- 装饰器注册（中英文双名）
- 动态字符串代码注册
- 大小写兼容查找
- 自动注册类方法
"""
import inspect


class KeyWordManager:
    """关键字的映射关系管理"""
    maps = {}

    @classmethod
    def register(cls, *keywords):
        """装饰器注册关键字，支持同时注册中英文名称

        用法示例：
            @KeyWordManager.register("click_element", "点击元素")
            def click_element(self, locator, timeout=3000):
                ...

        :param keywords: 一个或多个关键字名称（建议：英文在前，中文在后）
        :return: 装饰器函数
        """
        def wrapper(func):
            for kw in keywords:
                cls.maps[kw] = func
            return func
        return wrapper

    @classmethod
    def register_keyword(cls, keywords, func_code):
        """动态注册关键字（从字符串代码）

        :param keywords: str 或 list[str]，一个或多个关键字名称
        :param func_code: 字符串形式的函数定义代码
        :return: None

        用法示例：
            KeyWordManager.register_keyword(
                ["open_browser", "打开浏览器"],
                '''
def open_browser(self, browser_type):
    print(f"打开{browser_type}浏览器")
                '''
            )
        """
        if isinstance(keywords, str):
            keywords = [keywords]
        temp_map = {}
        exec(func_code, temp_map)
        for k, v in temp_map.items():
            if inspect.isfunction(v):
                for kw in keywords:
                    cls.maps[kw] = v
                # 动态挂载到 BaseCase 类（延迟导入避免循环依赖）
                from UIEngine.basecase import BaseCase
                setattr(BaseCase, k, v)

    @classmethod
    def get_keyword_maps(cls, keyword):
        """查找关键字对应的函数，支持大小写兼容

        :param keyword: 关键字名称
        :return: 对应的函数对象，未找到返回 None
        """
        if keyword is None:
            return None
        # 精确匹配优先
        result = cls.maps.get(keyword)
        if result is not None:
            return result
        # 大小写不敏感兜底匹配
        return cls.maps.get(keyword.lower())

    @classmethod
    def auto_register_methods(cls, target_class):
        """自动注册目标类的所有公共方法到关键字映射表

        用于在 BaseCase 定义完成后，将所有 Mixin 方法自动注册到 maps 中。
        已通过 @register 装饰器注册的方法不会被覆盖。

        :param target_class: 要扫描注册的类
        """
        # 不需要注册为关键字的内部方法列表
        excluded = {
            'perform', 'replace_params', 'close', 'open_browser',
            'create_browser', 'reset_browser_context', 'find_page',
            'switch_to_page', 'close_page',
            'save_page_img',
        }
        for name, method in inspect.getmembers(target_class, predicate=inspect.isfunction):
            if name.startswith('_'):
                continue
            if name in excluded:
                continue
            if name not in cls.maps:
                cls.maps[name] = method

    @classmethod
    def list_keywords(cls):
        """列出所有已注册的关键字

        :return: 关键字名称列表
        """
        return list(cls.maps.keys())
