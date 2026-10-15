"""Normalize attendance records independently of browser and notification code."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import ProtocolError

ACTIVE = {"in_progress", "active", "on_going", "started"}
TERMINAL = {"finished", "expired", "closed"}
NOT_STARTED = {"not_started", "waiting", "pending", "on_coming"}
COMPLETED = {"on_call", "on_call_fine", "on_personal_leave"}
SIGNED = {"on_call", "on_call_fine"}


@dataclass(frozen=True)
class Rollcall:
    id: str
    course: str
    title: str
    kind: str
    ends_at: datetime | None = None
    course_id: str | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class AttendanceProgress:
    signed: int
    total: int
    ends_at: datetime | None = None


def parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Do not guess a timezone for an undocumented server value.
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def attendance_progress(payload: Any) -> AttendanceProgress | None:
    """Reduce a full roster to counts; never infer attendance from status/timestamps."""
    if not isinstance(payload, dict):
        return None
    containers = [payload]
    if isinstance(payload.get("data"), dict):
        containers.append(payload["data"])
    container = next((item for item in containers if "student_rollcalls" in item), None)
    if container is None:
        return None
    students = container["student_rollcalls"]
    if not isinstance(students, list) or not students:
        return None
    # Do not use a known partial page as the whole-class denominator.
    for item in containers:
        pagination = item.get("pagination")
        metadata = [item, pagination] if isinstance(pagination, dict) else [item]
        for meta in metadata:
            if meta.get("has_more") is True or meta.get("next_page"):
                return None
            for key in ("total", "total_count"):
                if key in meta and (type(meta[key]) is not int or meta[key] != len(students)):
                    return None
    statuses = []
    for student in students:
        if not isinstance(student, dict):
            return None
        status = student.get("rollcall_status")
        if not isinstance(status, str) or not status.strip():
            return None
        statuses.append(status.strip().lower())
    ends = [end for item in containers if (end := parse_time(item.get("end_time"))) is not None]
    return AttendanceProgress(
        statuses.count("on_call_fine"), len(students), min(ends) if ends else None
    )


def active_rollcalls(payload: Any, now: datetime | None = None) -> list[Rollcall]:
    """Return unfinished attendance requests; reject ambiguous activity states."""
    if not isinstance(payload, dict) or not isinstance(payload.get("rollcalls"), list):
        raise ProtocolError("签到接口响应格式改变：缺少 rollcalls 列表。")
    now = now or datetime.now(UTC)
    result: dict[str, Rollcall] = {}
    for item in payload["rollcalls"]:
        if not isinstance(item, dict):
            raise ProtocolError("签到接口返回了无效记录。")
        if item.get("status") in COMPLETED or item.get("is_expired") is True:
            continue
        activity = item.get("rollcall_status")
        if activity in TERMINAL or activity in NOT_STARTED:
            continue
        if activity not in ACTIVE:
            raise ProtocolError("发现无法识别的点名活动状态，请核对接口后再监控。")
        end = parse_time(item.get("end_time"))
        if end is not None and end <= now:
            continue
        rid = item.get("rollcall_id") or item.get("id")
        if not isinstance(rid, (str, int)) or isinstance(rid, bool) or not str(rid):
            raise ProtocolError("签到记录缺少有效编号。")
        kind = (
            "GPS"
            if item.get("is_radar")
            else "数字"
            if item.get("is_number")
            else "二维码"
            if item.get("type") == "qr_rollcall"
            else "其他"
        )
        result[str(rid)] = Rollcall(
            str(rid),
            str(item.get("course_title") or "未命名课程"),
            str(item.get("title") or "课堂签到"),
            kind,
            end,
            str(item["course_id"]) if item.get("course_id") is not None else None,
            parse_time(item.get("rollcall_time")),
        )
    return list(result.values())
