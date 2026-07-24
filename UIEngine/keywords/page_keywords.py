"""页面级操作关键字

包含：URL 导航、截图、JS 执行、弹窗处理、下载等。
"""
import time
from UIEngine.browser.base_browser import BaseBrowser
from UIEngine.core.keyword_manager import KeyWordManager


class PageMixin(BaseBrowser):
    """封装页面对象的常用操作"""

    @KeyWordManager.register("open_url", "打开页面")
    def open_url(self, url, wait_until='load', timeout=30000):
        """
        打开 url
        :param url: 网页地址
        :param wait_until: 等待的状态
        :param timeout: 超时时间
        """
        if all([not url.startswith("http"), not url.startswith("https")]):
            url = self.config.get("host", "") + url
        self.log.debug_log(f"正在打开页面：{url}")
        self.page.goto(url, wait_until=wait_until, timeout=timeout)
        self.log.debug_log(f"成功打开页面：{url}")

    @KeyWordManager.register("refresh", "刷新页面")
    def refresh(self):
        """刷新页面"""
        self.log.debug_log("正在刷新页面")
        self.page.reload()

    @KeyWordManager.register("go_back", "返回上一页")
    def go_back(self):
        """返回上一页"""
        self.log.debug_log("正在返回上一页")
        self.page.go_back()

    @KeyWordManager.register("go_forward", "前进下一页")
    def go_forward(self):
        """前进到下一页"""
        self.log.debug_log("正在前进到下一页")
        self.page.go_forward()

    @KeyWordManager.register("scroll_to_height", "滚动到高度")
    def scroll_to_height(self, height):
        """
        滚动到指定位置
        :param height: 高度
        """
        self.page.evaluate(f"window.scrollTo(0, {height})")

    @KeyWordManager.register("execute_script", "执行脚本")
    def execute_script(self, script, *args):
        """执行 JavaScript 脚本"""
        self.log.debug_log("正在执行JavaScript脚本....")
        return self.page.evaluate(script, *args)

    @KeyWordManager.register("save_page_img", "保存截图")
    def save_page_img(self, name='', path=''):
        """
        保存页面截图
        :param name: 截图的名称
        :param path: 截图保存的路径（为空时默认保存到 <project_dir>/files/shortcuts/default/）
        :return: 截图保存的路径
        """
        try:
            from pathlib import Path
            if not name:
                name = "error_img_" + time.strftime("%Y%m%d%H%M%S", time.localtime())
            else:
                name = name + "_" + time.strftime("%Y%m%d%H%M%S", time.localtime())
            if not path:
                # 默认路径：<project_dir>/files/shortcuts/default/
                from UIEngine.utils.path_helper import get_project_dir
                project_dir = get_project_dir(self.config)
                path = str(Path(project_dir) / "files" / "shortcuts" / "default")
            Path(path).mkdir(parents=True, exist_ok=True)
            self.log.debug_log(f"正在保存页面截图，截图名称：{name}，截图保存路径：{path}")
            full_path = str(Path(path) / f"{name}.png")
            self.page.screenshot(path=full_path)
            return full_path
        except Exception as e:
            self.log.error_log(f"保存页面截图失败，失败原因：{e}")
            return ''

    @KeyWordManager.register("download_file", "下载文件")
    def download_file(self, locator, save_path=None, timeout=30000):
        """
        下载文件：点击触发下载的元素并等待下载完成
        :param locator: 触发下载的元素定位
        :param save_path: 文件保存路径（可选，默认保存到 <project_dir>/files/downloads/）
        :param timeout: 下载超时时间
        :return: 下载的文件名
        """
        from pathlib import Path
        self.log.debug_log(f"正在等待下载文件，触发元素:{locator}")
        with self.page.expect_download(timeout=timeout) as download_info:
            self.page.locator(locator).click()
        download = download_info.value
        filename = download.suggested_filename
        if not save_path:
            # 默认保存到 <project_dir>/files/downloads/
            from UIEngine.utils.path_helper import get_project_dir
            project_dir = get_project_dir(self.config)
            save_path = str(Path(project_dir) / "files" / "downloads" / filename)
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        download.save_as(save_path)
        self.log.debug_log(f"文件已保存到:{save_path}")
        return filename

    @KeyWordManager.register("accept_dialog", "接受弹窗")
    def accept_dialog(self, prompt_text=None):
        """
        接受浏览器弹窗（alert/confirm/prompt）
        :param prompt_text: prompt 类型弹窗的输入文本（可选）
        """
        self.log.debug_log("正在接受弹窗")
        self.page.on("dialog", lambda dialog: dialog.accept(prompt_text) if prompt_text else dialog.accept())

    @KeyWordManager.register("dismiss_dialog", "关闭弹窗")
    def dismiss_dialog(self):
        """关闭浏览器弹窗（cancel/dismiss）"""
        self.log.debug_log("正在关闭弹窗")
        self.page.on("dialog", lambda dialog: dialog.dismiss())

    @KeyWordManager.register("get_page_title", "获取页面标题")
    def get_page_title(self):
        """获取当前页面标题"""
        self.log.debug_log("正在获取页面标题")
        return self.page.title()

    @KeyWordManager.register("get_page_url", "获取页面URL")
    def get_page_url(self):
        """获取当前页面 URL"""
        self.log.debug_log("正在获取页面URL")
        return self.page.url

    @KeyWordManager.register("set_viewport_size", "设置窗口大小")
    def set_viewport_size(self, width, height):
        """
        设置浏览器视口大小
        :param width: 宽度
        :param height: 高度
        """
        self.log.debug_log(f"正在设置视口大小：{width}x{height}")
        self.page.set_viewport_size({"width": width, "height": height})

    @KeyWordManager.register("set_cookie", "设置Cookie")
    def set_cookie(self, cookie, domain=None):
        """
        运行时注入 cookie 到浏览器上下文

        :param cookie: cookie 字符串（如 "name1=value1; name2=value2"）或 Playwright cookie 字典列表
        :param domain: cookie 所属域名（可选，自动从 host 配置中提取）
        """
        from UIEngine.browser.base_browser import parse_cookie_string
        from urllib.parse import urlparse

        if isinstance(cookie, str):
            # 自动提取域名
            if not domain:
                host = self.config.get("host", "")
                if host:
                    domain = urlparse(host).hostname or ""
            if not domain:
                self.log.error_log("设置 cookie 失败：未指定域名（domain 或 host 配置）")
                return
            cookies = parse_cookie_string(cookie, domain)
        elif isinstance(cookie, list):
            cookies = cookie
        else:
            self.log.error_log(f"设置 cookie 失败：不支持的 cookie 类型 {type(cookie)}")
            return

        if cookies:
            self.context.add_cookies(cookies)
            self.log.debug_log(f"已注入 {len(cookies)} 个 cookie（域名: {domain or '自定义'}）")
