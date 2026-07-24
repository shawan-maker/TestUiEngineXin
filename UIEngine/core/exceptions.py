"""自定义异常类"""


class KeywordNotFoundError(AttributeError):
    """关键字未找到异常

    当 perform() 在 KeyWordManager.maps 和实例方法中都找不到对应的关键字时抛出。
    """
    pass
