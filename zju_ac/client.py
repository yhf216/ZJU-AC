"""Read-only API access using an authenticated HTTP session."""

from typing import Any

import requests

from .errors import AuthenticationExpired, ProtocolError, TemporaryError, ZjuError
from .models import Rollcall, active_rollcalls

BASE_URL = "https://courses.zju.edu.cn"


class CoursesClient:
    def __init__(self, session: requests.Session, timeout: float = 15):
        self.session = session
        self.timeout = timeout

    def get_json(self, path: str) -> Any:
        # No caller-supplied origins and no automatic API redirects to login HTML.
        if path not in {"/api/profile", "/api/radar/rollcalls"}:
            raise ValueError("Unsupported read-only API path")
        try:
            response = self.session.get(
                BASE_URL + path,
                timeout=self.timeout,
                allow_redirects=False,
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            raise TemporaryError("请求失败，请检查网络、代理或校园网连接。") from exc
        try:
            if response.status_code in {301, 302, 303, 307, 308, 401}:
                raise AuthenticationExpired("登录会话已失效，请重新运行并登录。")
            if response.status_code == 403:
                raise ZjuError("接口访问被拒绝（403），请检查账号权限或登录状态。")
            if response.status_code == 429 or response.status_code >= 500:
                raise TemporaryError(f"服务暂时不可用（HTTP {response.status_code}）。")
            if response.status_code != 200:
                raise ProtocolError(f"接口请求失败（HTTP {response.status_code}）。")
            if "json" not in response.headers.get("content-type", "").lower():
                raise AuthenticationExpired("接口未返回 JSON，可能已退出登录。")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProtocolError("接口返回了无效 JSON。") from exc
            if isinstance(payload, dict) and (
                payload.get("error_code") or payload.get("success") is False
            ):
                raise ProtocolError("接口返回业务错误，请核对平台接口。")
            return payload
        finally:
            response.close()

    def profile(self) -> dict:
        payload = self.get_json("/api/profile")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise AuthenticationExpired("尚未取得有效的学在浙大登录会话。")
        return payload

    def rollcalls(self) -> list[Rollcall]:
        return active_rollcalls(self.get_json("/api/radar/rollcalls"))
