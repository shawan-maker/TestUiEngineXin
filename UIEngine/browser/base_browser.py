"""浏览器生命周期管理

包含：浏览器创建/关闭、上下文管理、多页面管理。
修复：self.pages 未初始化、headless 逻辑反转。
新增：上下文管理器（__enter__/__exit__）。
新增：Cookie 注入支持（配置级 + 运行时关键字）。
"""
import re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from UIEngine.core.keyword_manager import KeyWordManager


def parse_cookie_string(cookie_str, domain=None):
    """将 cookie 请求头字符串解析为 Playwright add_cookies 所需的格式

    :param cookie_str: cookie 请求头字符串，如 "name1=value1; name2=value2"
    :param domain: cookie 所属域名（必须提供，否则 cookie 无法生效）
    :return: Playwright cookie 字典列表
    """
    if not cookie_str:
        return []
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookie = {"name": name, "value": value}
        if domain:
            cookie["domain"] = domain
            cookie["path"] = "/"
        cookies.append(cookie)
    return cookies


class BaseBrowser:
    """浏览器基类：管理 browser/context/page 三层对象"""

    def __init__(self, config, log, browser=None, context=None, page=None):
        """
        :param config: 环境配置字典
        :param log: 日志处理器
        :param browser: 可选，复用的浏览器实例
        :param context: 可选，复用的上下文实例
        :param page: 可选，复用的页面实例
        """
        self.config = config
        self.log = log
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.pages = {}  # 修复：初始化 pages 字典
        self._current_frame = None  # iframe 上下文状态
        # 三个对象全部存在才复用
        if all([browser, context, page]):
            self.browser = browser
            self.context = context
            self.page = page
            self.pages['default'] = self.page

    def __getattr__(self, item):
        """当浏览器没有创建时，自动创建浏览器"""
        if item in ["browser", "context", "page"]:
            self.log.debug_log(f"当前浏览器没有启动，{item}属性不存在，正在为您启动浏览器")
            self.open_browser(self.config.get("browser_type"))
            return getattr(self, item)
        else:
            raise AttributeError(f"{item}属性不存在")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口：确保浏览器资源被释放"""
        try:
            self.close()
        except Exception:
            pass
        return False

    @KeyWordManager.register("open_browser", "打开浏览器")
    def open_browser(self, browser_type):
        """打开浏览器"""
        browser_type = browser_type or self.config.get("browser_type")
        self.browser, self.context, self.page = self.create_browser(browser_type)
        self.pages['default'] = self.page
        # 输出实际视口尺寸（诊断 DPI 缩放和窗口大小问题）
        try:
            vp = self.page.viewport_size
            self.log.debug_log(f"打开浏览器成功 (viewport: {vp})")
        except Exception:
            self.log.debug_log("打开浏览器成功")

    def create_browser(self, browser_type):
        """创建浏览器对象"""
        # 1. 启动 Playwright 运行时核心
        self.pw = sync_playwright().start()
        # 2. 动态获取浏览器启动器（chromium/firefox/webkit）
        browser_type_obj = getattr(self.pw, browser_type)
        # 3. 启动浏览器实例（最大化窗口 + is_debug 控制有头/无头）
        is_debug = self.config.get("is_debug", False)
        launch_args = ["--start-maximized"] if browser_type == "chromium" else []
        browser = browser_type_obj.launch(
            headless=not is_debug,
            args=launch_args,
        )
        # 4. 创建隔离浏览器上下文
        if is_debug:
            # 有头模式：不设 viewport，--start-maximized 让窗口铺满屏幕，
            # Playwright 自动使用窗口实际尺寸作为视口（含 DPI 缩放）
            context = browser.new_context(no_viewport=True)
        else:
            # 无头模式：固定 1920×1080 保证截图一致性
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
        # 5. 注入配置级 cookie（如果配置了 cookie 字段）
        self._apply_config_cookies(context)
        # 6. 创建页面 Tab（对应浏览器标签页）
        page = context.new_page()
        # 7. 返回三层对象
        return browser, context, page

    def _apply_config_cookies(self, context):
        """从配置中读取 cookie 并注入到浏览器上下文

        支持的配置字段：
        - cookie: cookie 请求头字符串，如 "name1=value1; name2=value2"
        - cookie_domain: cookie 所属域名（可选，自动从 host 字段提取）
        """
        cookie_str = self.config.get("cookie", "")
        if not cookie_str:
            return
        # 优先使用 cookie_domain，否则从 host 自动提取
        domain = self.config.get("cookie_domain", "")
        if not domain:
            host = self.config.get("host", "")
            if host:
                parsed = urlparse(host)
                domain = parsed.hostname or ""
        if not domain:
            self.log.warning_log("cookie 已配置但未指定域名（cookie_domain 或 host），cookie 可能无法生效")
            return
        cookies = parse_cookie_string(cookie_str, domain)
        if cookies:
            context.add_cookies(cookies)
            self.log.debug_log(f"已注入 {len(cookies)} 个 cookie 到浏览器上下文（域名: {domain}）")

    def reset_browser_context(self):
        """重置浏览器运行环境：清除 cookie 和浏览器的缓存信息，并重新注入配置级 cookie"""
        self.page.close()
        self.context.close()
        # 与 create_browser 保持一致：有头模式 no_viewport，无头模式固定 1920x1080
        is_debug = self.config.get("is_debug", False)
        if is_debug:
            self.context = self.browser.new_context(no_viewport=True)
        else:
            self.context = self.browser.new_context(viewport={"width": 1920, "height": 1080})
        # 重置后重新注入配置中的 cookie
        self._apply_config_cookies(self.context)
        self.page = self.context.new_page()

    def close(self):
        """关闭浏览器"""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.pw:
                self.pw.stop()
        except Exception:
            pass

    # ── 共享 loading mask 选择器（与 system_workflows.yaml 对齐）──
    _LOADING_MASK_SELECTORS = [
        "//div[contains(@class,'el-loading-mask')]",
        "//p[@class='el-loading-text']",
        "//div[@ng-show='loading' and not(contains(@class,'ng-hide'))]",
        "//div[@class='el-loading-spinner']/p[@class='el-loading-text']",
    ]

    def _wait_for_visible_mask(self, timeout=10000):
        """检测页面上是否有可见的 loading mask，如果有则等待消失。

        用于 click 失败后的重试策略：当 click 被 mask 拦截时，
        等待 mask 消失后重试 click，解决异步 loading 间隙问题。

        :param timeout: 等待 mask 消失的最大超时时间（毫秒）
        :return: True 表示发现并等待了 mask 消失，False 表示未发现 mask
        """
        for selector in self._LOADING_MASK_SELECTORS:
            mask = self.page.locator(f"xpath={selector}")
            try:
                if mask.count() > 0 and mask.first.is_visible():
                    self.log.debug_log(f"[mask-retry] 检测到 loading mask，等待消失: {selector}")
                    mask.first.wait_for(state="hidden", timeout=timeout)
                    self.log.debug_log(f"[mask-retry] loading mask 已消失")
                    return True
            except Exception:
                pass
        return False

    def open_new_page(self, tag, timeout=3000):
        """
        打开新页面
        :param tag: 页面标签
        :param timeout: 超时时间
        """
        self.pages[tag] = self.context.new_page()
        self.log.debug_log("页面已经打开")

    def find_page(self, tag='', index='', title='', url=''):
        """查找页面

        :param tag: 页面标签
        :param index: 页面索引
        :param title: 页面标题
        :param url: 页面 URL（支持正则匹配）
        :return: 匹配的页面对象
        """
        if tag:
            return self.pages[tag]
        elif index:
            return self.context.pages[int(index)]
        elif title:
            for page in self.context.pages:
                if page.title() == title:
                    return page
        elif url:
            for page in self.context.pages:
                if re.search(url, page.url):
                    return page
        else:
            return self.context.pages[-1]

    def switch_to_page(self, tag='', index='', title='', url=''):
        """
        切换到指定页面：默认切换到最新的窗口页面
        :param tag: 页面标签
        :param index: 页面打开的顺序
        :param title: 页面标题
        :param url: 页面的 url
        """
        page = self.find_page(tag, index, title, url)
        self.page = page

    def close_page(self, tag='', index='', title='', url=''):
        """
        关闭页面：默认关闭最新打开的页面
        :param tag: 页面标签
        :param index: 页面打开的顺序
        :param title: 页面标题
        :param url: 页面的 url
        """
        page = self.find_page(tag, index, title, url)
        if page == self.page and len(self.context.pages) > 1:
            page.close()
            self.page = self.context.pages[0]
        else:
            page.close()
