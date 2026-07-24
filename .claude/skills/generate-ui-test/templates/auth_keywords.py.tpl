"""认证关键字模块

提供三种认证注入方式，在套件 setup_step 中自动执行。
认证凭据统一在 config.yaml 中配置，suite 通过关键字读取，禁止在 suite 中硬编码。

支持的认证方式：
  - inject_cookies       / 注入Cookie        — 将 Cookie 列表注入浏览器上下文
  - inject_token_header  / 注入Token请求头    — 将 Bearer Token 设为 Authorization 请求头
  - inject_local_storage / 注入LocalStorage   — 将 config.local_storage 全部字段 + cookie token 写入 localStorage

用户名密码登录无需使用此模块，直接通过用例步骤操作登录页面即可。
"""
from UIEngine.core.keyword_manager import KeyWordManager


def inject_cookies(self, cookies=None):
    """将 Cookie 列表注入浏览器上下文

    支持两种配置格式：
    1. config['auth']['cookies'] — Cookie 字典列表（每个含 name/value/domain/path）
    2. config['cookie'] — Cookie 字符串 "name1=value1; name2=value2"（自动解析）

    :param cookies: Cookie 字典列表，每个包含 name/value/domain/path
    """
    if cookies is None:
        # 优先读取 auth.cookies 列表格式
        cookies = self.config.get('auth', {}).get('cookies', [])
    if not cookies:
        # 回退到顶层 cookie 字符串格式
        cookie_str = self.config.get('cookie', '')
        domain = self.config.get('cookie_domain', '')
        if cookie_str:
            cookies = []
            for part in cookie_str.split(';'):
                part = part.strip()
                if '=' in part:
                    name, value = part.split('=', 1)
                    ck = {'name': name.strip(), 'value': value.strip()}
                    if domain:
                        ck['domain'] = domain
                    cookies.append(ck)
    if not cookies:
        self.log.debug_log("[认证] 没有需要注入的 Cookie")
        return
    self.context.add_cookies(cookies)
    self.log.debug_log(f"[认证] 已注入 {len(cookies)} 个 Cookie")


def inject_token_header(self, token=None):
    """将 Bearer Token 设置为所有后续请求的 Authorization 头

    支持两种配置格式：
    1. config['auth']['token'] — Token 字符串
    2. config['token'] — 顶层 Token 字符串

    自动补全 'Bearer ' 前缀。

    :param token: Token 字符串
    """
    if token is None:
        token = self.config.get('auth', {}).get('token', '')
    if not token:
        # 回退到顶层 token 字段
        token = self.config.get('token', '')
    if not token:
        self.log.debug_log("[认证] 没有需要注入的 Token")
        return
    # 自动补全 Bearer 前缀
    if not token.lower().startswith('bearer '):
        token = f'Bearer {token}'
    self.context.set_extra_http_headers({"Authorization": token})
    self.log.debug_log("[认证] 已注入 Authorization 请求头")


def inject_local_storage(self, key=None, value=None, navigate_url=None):
    """将键值对写入浏览器 localStorage

    两种使用方式：
    1. 无参数调用（推荐）：自动从 config.local_storage 读取全部字段，
       并从 config.cookie 提取 token 合并注入。
    2. 指定 key/value 参数：注入单个键值对（兼容旧用法）。
    """
    # 方式2：指定了 key/value 参数，走单字段注入
    if key and value:
        navigate_url = navigate_url or self.config.get('auth', {}).get('storage', {}).get('navigate_url', '')
        if navigate_url:
            host = self.config.get('host', '')
            full_url = navigate_url if navigate_url.startswith('http') else host + navigate_url
            self.page.goto(full_url, wait_until='domcontentloaded')
        self.page.evaluate("(k, v) => localStorage.setItem(k, v)", key, value)
        self.log.debug_log(f"[认证] 已写入 localStorage: {key}")
        return

    # 方式1：从 config 批量读取
    storage_items = dict(self.config.get('local_storage', {}))

    # 自动从 cookie 提取第一个 token 并合并到 localStorage
    cookie_str = self.config.get('cookie', '')
    if cookie_str:
        for part in cookie_str.split(';'):
            part = part.strip()
            if '=' in part:
                ck, cv = part.split('=', 1)
                ck = ck.strip()
                # 只合并 token 类字段（以 _token 结尾或名为 token）
                if 'token' in ck.lower():
                    storage_items.setdefault(ck, cv)
                    break  # 只取第一个 token

    if not storage_items:
        self.log.debug_log("[认证] localStorage 注入缺少配置，跳过")
        return

    # 批量写入
    js_items = ', '.join([f"'{k}', '{v}'" for k, v in storage_items.items()])
    js_script = f"var items=[{js_items}]; for(var i=0;i<items.length;i+=2){{ localStorage.setItem(items[i], items[i+1]); }}"
    self.page.evaluate(js_script)
    self.log.debug_log(f"[认证] 已写入 localStorage: {list(storage_items.keys())}")


def register_auth_keywords():
    """注册所有认证关键字到引擎

    通过 setattr 挂载到 BaseCase 类，并添加到 KeyWordManager.maps 映射表。
    这样 perform() 调度时可以通过关键字名称查找到对应函数。
    """
    from UIEngine.basecase import BaseCase

    # 注册表：(函数对象, [英文名称, 中文名称])
    keywords = [
        (inject_cookies,        ["inject_cookies", "注入Cookie"]),
        (inject_token_header,   ["inject_token_header", "注入Token请求头"]),
        (inject_local_storage,  ["inject_local_storage", "注入LocalStorage"]),
    ]

    for func, names in keywords:
        # 挂载到 BaseCase 类，使 self.func() 可用
        setattr(BaseCase, func.__name__, func)
        # 注册中英文名称到映射表，使 perform() 可以通过名称调度
        for name in names:
            KeyWordManager.maps[name] = func
