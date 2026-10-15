"""Authenticated course queries and explicit numeric attendance submissions."""

import re
import time
import uuid
from datetime import UTC
from typing import Any

import requests

from .errors import (
    AuthenticationExpired,
    CheckinRejected,
    PermissionDenied,
    ProtocolError,
    SubmissionUncertain,
    TemporaryError,
)
from .models import SIGNED, Rollcall, active_rollcalls

BASE_URL = "https://courses.zju.edu.cn"


def api_id(value: str | None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise ProtocolError("签到记录缺少有效的课程或活动编号。")
    return value


def number_code(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        value = str(value).zfill(4)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4,8}", value):
        return value
    return None


class CoursesClient:
    def __init__(self, session: requests.Session, timeout: float = 15):
        self.session = session
        self.timeout = timeout
        self.device_id = str(uuid.uuid4())
        self._student_id: str | None = None

    def get_json(self, path: str, params: dict | None = None) -> Any:
        # No caller-supplied origins and no automatic API redirects to login HTML.
        if path not in {
            "/api/profile",
            "/api/radar/rollcalls",
            "/api/timetable_rollcalls",
        } and not (
            re.fullmatch(r"/api/rollcall/[0-9]+/student_rollcalls", path)
            or re.fullmatch(r"/api/course/[0-9]+/student/[0-9]+/rollcalls", path)
        ):
            raise ValueError("Unsupported read-only API path")
        options = {"params": params} if params is not None else {}
        try:
            response = self.session.get(
                BASE_URL + path,
                timeout=self.timeout,
                allow_redirects=False,
                headers={"Accept": "application/json"},
                **options,
            )
        except requests.RequestException as exc:
            raise TemporaryError("请求失败，请检查网络、代理或校园网连接。") from exc
        return self._read_response(response)

    @staticmethod
    def _read_response(response: requests.Response, submitting: bool = False) -> Any:
        try:
            if response.status_code in {301, 302, 303, 307, 308, 401}:
                raise AuthenticationExpired("登录会话已失效，请重新运行并登录。")
            if response.status_code == 403:
                raise PermissionDenied("接口访问被拒绝（403），请检查账号权限或登录状态。")
            if response.status_code == 429 or response.status_code >= 500:
                if submitting:
                    raise SubmissionUncertain(
                        "提交结果不确定，正在回查本人状态，不会自动重复提交。"
                    )
                raise TemporaryError(f"服务暂时不可用（HTTP {response.status_code}）。")
            if response.status_code != 200:
                if submitting:
                    raise CheckinRejected(
                        f"签到提交被拒绝（HTTP {response.status_code}），请核对数字码。"
                    )
                raise ProtocolError(f"接口请求失败（HTTP {response.status_code}）。")
            if "json" not in response.headers.get("content-type", "").lower():
                if submitting:
                    raise SubmissionUncertain("提交响应无法识别，正在回查本人状态。")
                raise AuthenticationExpired("接口未返回 JSON，可能已退出登录。")
            try:
                payload = response.json()
            except ValueError as exc:
                if submitting:
                    raise SubmissionUncertain("提交响应无法解析，正在回查本人状态。") from exc
                raise ProtocolError("接口返回了无效 JSON。") from exc
            if isinstance(payload, dict) and (
                payload.get("error_code") or payload.get("success") is False
            ):
                if submitting:
                    raise CheckinRejected("服务端拒绝签到，请核对数字码及活动状态。")
                raise ProtocolError("接口返回业务错误，请核对平台接口。")
            return payload
        finally:
            response.close()

    def profile(self) -> dict:
        payload = self.get_json("/api/profile")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise AuthenticationExpired("尚未取得有效的学在浙大登录会话。")
        self._student_id = api_id(str(payload["id"]))
        return payload

    def rollcalls(self) -> list[Rollcall]:
        return active_rollcalls(self.get_json("/api/radar/rollcalls"))

    def fresh_number(self, record: Rollcall) -> Rollcall | None:
        """Recheck after the user's potentially long wait before any write."""
        api_id(record.id)
        api_id(record.course_id)
        return next(
            (
                rc
                for rc in self.rollcalls()
                if rc.id == record.id and rc.course_id == record.course_id and rc.kind == "数字"
            ),
            None,
        )

    def read_number_code(self, record: Rollcall) -> str | None:
        rid = api_id(record.id)
        try:
            detail = self.get_json(f"/api/rollcall/{rid}/student_rollcalls")
            if isinstance(detail, dict) and (code := number_code(detail.get("number_code"))):
                return code
        except (PermissionDenied, ProtocolError):
            pass
        if record.course_id is None or record.started_at is None:
            return None
        try:
            payload = self.get_json(
                "/api/timetable_rollcalls",
                params={
                    "course_ids": api_id(record.course_id),
                    "rollcall_date": record.started_at.astimezone(UTC).date().isoformat(),
                },
            )
        except (PermissionDenied, ProtocolError):
            return None
        items = payload.get("rollcalls", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and str(item.get("id")) == rid:
                return number_code(item.get("number_code"))
        return None

    def my_rollcall_status(self, record: Rollcall) -> str | None:
        cid, rid = api_id(record.course_id), api_id(record.id)
        if self._student_id is None:
            self.profile()
        path = f"/api/course/{cid}/student/{self._student_id}/rollcalls"
        # Query only this student's records; stop rather than guess if not found.
        for page in range(1, 6):
            payload = self.get_json(path, params={"page": page, "page_size": 100})
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = payload.get("rollcalls", payload.get("data"))
            else:
                items = None
            if not isinstance(items, list):
                raise ProtocolError("本人签到记录响应格式改变，无法核验结果。")
            for item in items:
                if isinstance(item, dict) and str(item.get("rollcall_id") or item.get("id")) == rid:
                    status = item.get("status")
                    return status if isinstance(status, str) else None
            if len(items) < 100:
                break
        return None

    def submit_number(self, record: Rollcall, code: str) -> None:
        rid = api_id(record.id)
        api_id(record.course_id)
        if record.kind != "数字" or number_code(code) is None:
            raise ProtocolError("仅支持提交有效的数字签到码。")
        try:
            response = self.session.put(
                f"{BASE_URL}/api/rollcall/{rid}/answer_number_rollcall",
                json={"deviceId": self.device_id, "numberCode": code},
                timeout=self.timeout,
                allow_redirects=False,
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            raise SubmissionUncertain("提交连接中断，正在回查本人状态，不会自动重复提交。") from exc
        self._read_response(response, submitting=True)

    def verify_number(self, record: Rollcall) -> bool:
        for attempt in range(3):
            if self.my_rollcall_status(record) in SIGNED:
                return True
            if attempt < 2:
                time.sleep(0.4)
        return False
