"""Normal browser authentication; credentials and cookies stay in memory."""

import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from playwright.sync_api import Error, Page, TimeoutError, sync_playwright

from .client import BASE_URL, CoursesClient
from .errors import AuthenticationExpired, TemporaryError, ZjuError

AUTH_HOSTS = {"courses.zju.edu.cn", "identity.zju.edu.cn", "zjuam.zju.edu.cn"}


def trusted_login_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in AUTH_HOSTS


def fill_login_form(page: Page, student_id: str, password: str) -> bool:
    """Submit visible standard CAS/Keycloak fields only on trusted HTTPS origins."""
    if not trusted_login_url(page.url):
        return False
    users = page.locator('input[name="username"]:visible, input#username:visible')
    passwords = page.locator('input[type="password"]:visible')
    if users.count() != 1 or passwords.count() != 1:
        return False
    users.fill(student_id, timeout=2000)
    passwords.fill(password, timeout=2000)
    passwords.press("Enter", timeout=2000)
    return True


@contextmanager
def login(student_id: str, password: str, channel: str, login_timeout: int):
    with sync_playwright() as engine:
        browser = None
        try:
            try:
                browser = engine.chromium.launch(
                    headless=False,
                    channel=None if channel == "chromium" else channel,
                )
            except Error as exc:
                raise ZjuError(
                    "无法启动浏览器。可选择 --browser msedge，或先运行 "
                    "python -m playwright install chromium。"
                ) from exc
            context = browser.new_context(locale="zh-CN")
            page = context.new_page()
            deadline = time.monotonic() + login_timeout
            try:
                page.goto(BASE_URL + "/user/index", timeout=30_000, wait_until="domcontentloaded")
            except TimeoutError:
                print("登录页加载较慢，将继续等待；可在浏览器中检查网络。", flush=True)
            except Error as exc:
                raise TemporaryError("无法打开浙大登录页，请检查网络或代理。") from exc
            client = CoursesClient(context, timeout=5)
            submitted = False
            print("正在登录；如有验证码或二次验证，请在浏览器中完成。", flush=True)
            while time.monotonic() < deadline:
                if page.is_closed():
                    raise ZjuError("登录窗口已关闭。")
                if not submitted:
                    try:
                        submitted = fill_login_form(page, student_id, password)
                    except Error:
                        # Redirecting frames can disappear between visibility checks and filling.
                        pass
                try:
                    client.profile()
                    break
                except (AuthenticationExpired, TemporaryError):
                    page.wait_for_timeout(2000)
            else:
                raise ZjuError("登录超时，请检查账号密码，或在浏览器中完成验证后重试。")
            password = ""
            print("登录成功，开始监控签到。浏览器需保持打开，Ctrl+C 退出。", flush=True)
            yield CoursesClient(context)
        finally:
            if browser is not None:
                browser.close()
