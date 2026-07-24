"""变量解析器：处理参数中的 ${variable} 占位符替换

采用递归遍历数据结构的方式，直接替换字符串值中的变量，
避免 str(dict) + literal_eval 导致的特殊字符解析崩溃问题。
"""
import re


class VariableResolver:
    """解析参数中的变量占位符 ${var_name}

    从 config["global_variable"] 字典中查找变量值并替换。
    递归遍历 dict/list/str，保持原始数据结构不变。
    """

    _pattern = re.compile(r'\$\{(.+?)\}')

    def __init__(self, config, log):
        """
        :param config: 配置字典，包含 global_variable 字段
        :param log: 日志处理器实例
        """
        self.config = config
        self.log = log

    def resolve(self, value):
        """替换参数中的变量占位符，保持原始数据结构

        :param value: 要进行变量替换的参数（dict / list / str / 其他）
        :return: 替换后的参数，类型与输入保持一致
        """
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, str):
            return self._resolve_string(value)
        return value

    def _get_var(self, key):
        """查找变量值，优先 runtime_variables，其次 global_variable"""
        rv = self.config.get('runtime_variables', {})
        if key in rv:
            return rv[key]
        gv = self.config.get('global_variable', {})
        return gv.get(key)

    def _resolve_string(self, text):
        """替换单个字符串中的变量占位符

        处理逻辑：
        - 如果整个字符串就是一个占位符 ${var}，且变量值是非字符串类型，
          直接返回原始类型（int/float/bool/list/dict），保持类型不变
        - 如果字符串包含多个占位符或混合文本，变量值统一转为字符串拼接
        - 支持多层嵌套变量解析（最多 3 层），如 pages 定位器中引用 data 变量

        :param text: 包含 ${var} 占位符的字符串
        :return: 替换后的值（可能是 str，也可能是变量的原始类型）
        """
        # 快速检查：字符串中是否包含占位符
        if '${' not in text:
            return text

        # 特殊情况：整个字符串就是单个占位符，保留变量原始类型
        match = self._pattern.fullmatch(text.strip())
        if match:
            key = match.group(1)
            var_value = self._get_var(key)
            if var_value is not None:
                # 如果变量值本身也是字符串且包含 ${}，递归解析（支持嵌套变量）
                if isinstance(var_value, str) and '${' in var_value:
                    return self._resolve_string(var_value)
                return var_value
            self.log.warning_log(f"变量未解析: {key} 在 runtime_variables 和 global_variable 中均不存在，保留原始占位符")
            return text

        # 通用情况：字符串中混合了文本和占位符，统一替换为字符串
        # 支持多层嵌套：替换后如果仍有 ${}，继续解析（最多 3 层防止循环引用）
        for _round in range(3):
            if '${' not in text:
                break

            def _replacer(m):
                key = m.group(1)
                var_value = self._get_var(key)
                if var_value is not None:
                    return str(var_value)
                self.log.warning_log(f"变量未解析: {key} 在 runtime_variables 和 global_variable 中均不存在，保留原始占位符")
                return m.group(0)

            text = self._pattern.sub(_replacer, text)

        return text
