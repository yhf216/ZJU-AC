"""CAS/Keycloak form authentication over HTTPS, with no browser or stored credentials."""

import re
import time
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Tag

from . import __version__
from .client import BASE_URL, CoursesClient
from .errors import AuthenticationExpired, ProtocolError, TemporaryError, ZjuError

AUTH_HOSTS = {"courses.zju.edu.cn", "identity.zju.edu.cn", "zjuam.zju.edu.cn"}
REDIRECTS = {301, 302, 303, 307, 308}


def trusted_login_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in AUTH_HOSTS
            and parsed.port in {None, 443}
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def checked_url(base: str, target: str) -> str:
    url = urljoin(base, target)
    if not trusted_login_url(url):
        raise ProtocolError("认证跳转或表单地址不可信，已停止登录。")
    return url


def encrypt_cas_password(password: str, key: dict) -> str:
    """Implement the legacy CAS frontend's raw RSA protocol (not PKCS#1)."""
    try:
        modulus = int(key["modulus"], 16)
        exponent = int(key["exponent"], 16)
        value = int.from_bytes(password.encode("utf-8"), "big")
        if modulus <= value or exponent <= 1 or modulus.bit_length() < 512:
            raise ValueError("Invalid key or oversized password")
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError("统一认证返回的 RSA 公钥无效，或密码长度超出协议限制。") from exc
    width = (modulus.bit_length() + 7) // 8 * 2
    return format(pow(value, exponent, modulus), f"0{width}x")


def form_values(form: Tag) -> dict[str, str]:
    """Preserve server hidden fields without executing page JavaScript."""
    return {
        str(field["name"]): str(field.get("value", ""))
        for field in form.select("input[name]")
        if field.get("type", "text").lower() == "hidden" and not field.has_attr("disabled")
    }


class HttpAuthenticator:
    def __init__(self, session: requests.Session, timeout: float):
        self.session = session
        self.deadline = time.monotonic() + timeout

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        checked_url(url, url)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ZjuError("登录超时，请检查网络后重试。")
        try:
            response = self.session.request(
                method,
                url,
                timeout=min(15, remaining),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise TemporaryError("认证请求失败，请检查网络、代理或校园网连接。") from exc
        if response.status_code >= 400:
            status = response.status_code
            response.close()
            if status == 429 or status >= 500:
                raise TemporaryError(f"认证服务暂时不可用（HTTP {status}）。")
            raise ZjuError(f"认证服务拒绝请求（HTTP {status}）。")
        return response

    def follow(self, response: requests.Response, posted: bool = False) -> requests.Response:
        for _ in range(20):
            try:
                if response.status_code in REDIRECTS:
                    if posted and response.status_code in {307, 308}:
                        raise ProtocolError("认证要求重新发送密码，已停止以避免重复提交。")
                    location = response.headers.get("location")
                    if not location:
                        raise ProtocolError("认证跳转缺少目标地址。")
                else:
                    soup = BeautifulSoup(response.text, "html.parser")
                    refresh = soup.find("meta", attrs={"http-equiv": re.compile("^refresh$", re.I)})
                    if refresh is None:
                        return response
                    match = re.search(r"url\s*=\s*(.+)$", str(refresh.get("content", "")), re.I)
                    if not match:
                        raise ProtocolError("无法解析认证页面跳转。")
                    location = match[1].strip().strip("\"'")
                target = checked_url(response.url, location)
            except BaseException:
                response.close()
                raise
            response.close()
            response = self.request("GET", target)
            posted = False
        response.close()
        raise ProtocolError("认证跳转次数过多，已停止登录。")

    def authenticate(self, student_id: str, password: str) -> None:
        response = self.follow(self.request("GET", BASE_URL + "/user/index"))
        submitted = False
        # One password submission, followed by at most two explicit OTP challenges.
        try:
            for _ in range(3):
                soup = BeautifulSoup(response.text, "html.parser")
                form = next(
                    (
                        f
                        for f in soup.find_all("form")
                        if f.select_one('input[name="username"]') is not None
                        and f.select_one('input[name="password"]') is not None
                    ),
                    None,
                )
                if form is not None:
                    if submitted:
                        raise ZjuError("登录未通过，请检查学号密码或认证要求；不会自动重试密码。")
                    if str(form.get("method", "get")).lower() != "post":
                        raise ProtocolError("认证表单不支持安全的 POST 提交。")
                    action = checked_url(response.url, str(form.get("action") or response.url))
                    data = form_values(form)
                    if "execution" in data and urlsplit(action).hostname == "zjuam.zju.edu.cn":
                        key_response = self.request(
                            "GET", "https://zjuam.zju.edu.cn/cas/v2/getPubKey"
                        )
                        try:
                            key = key_response.json()
                        except ValueError as exc:
                            raise ProtocolError("无法读取统一认证 RSA 公钥。") from exc
                        finally:
                            key_response.close()
                        data["password"] = encrypt_cas_password(password, key)
                        data.setdefault("_eventId", "submit")
                        data.setdefault("authcode", "")
                    elif (
                        urlsplit(action).hostname == "identity.zju.edu.cn"
                        and "/login-actions/authenticate" in urlsplit(action).path
                    ):
                        data["password"] = password
                    else:
                        raise ProtocolError("发现尚未支持的认证表单，未发送密码。")
                    data["username"] = student_id
                    submitted = True
                    password = ""
                else:
                    otp_form = next(
                        (
                            f
                            for f in soup.find_all("form")
                            if f.select_one('input[name="otp"], input[name="totp"]') is not None
                        ),
                        None,
                    )
                    if submitted and otp_form is not None:
                        action = checked_url(
                            response.url, str(otp_form.get("action") or response.url)
                        )
                        if str(otp_form.get("method", "get")).lower() != "post":
                            raise ProtocolError("二次验证表单不是 POST，已停止。")
                        field = otp_form.select_one('input[name="otp"], input[name="totp"]')
                        code = input("请输入统一认证动态验证码：").strip()
                        if not code or not code.isascii() or not code.isdigit():
                            raise ZjuError("动态验证码必须是数字。")
                        data = form_values(otp_form)
                        data[str(field["name"])] = code
                    else:
                        # Final success is verified through the API, never by page text or HTTP 200.
                        break
                referer = response.url
                response.close()
                response = self.follow(
                    self.request("POST", action, data=data, headers={"Referer": referer}),
                    posted=True,
                )
            try:
                CoursesClient(self.session).profile()
            except AuthenticationExpired as exc:
                raise ZjuError(
                    "未取得有效登录会话：账号密码未通过，或认证要求尚未支持的验证码/验证步骤。"
                ) from exc
        finally:
            response.close()


@contextmanager
def login(student_id: str, password: str, login_timeout: int = 180):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": f"ZJU-AC/{__version__}",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    try:
        print("正在通过 HTTPS 登录统一身份认证……", flush=True)
        HttpAuthenticator(session, login_timeout).authenticate(student_id, password)
        password = ""
        print("登录成功，开始监控签到。Ctrl+C 退出。", flush=True)
        yield CoursesClient(session)
    finally:
        session.cookies.clear()
        session.close()
