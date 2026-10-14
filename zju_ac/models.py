"""Normalize attendance records independently of browser and notification code."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import ProtocolError

ACTIVE = {"in_progress", "active", "on_going", "started"}
TERMINAL = {"finished", "expired", "closed"}
NOT_STARTED = {"not_started", "waiting", "pending", "on_coming"}
COMPLETED = {"on_call", "on_call_fine", "on_personal_leave"}


@dataclass(frozen=True)
class Rollcall:
    id: str
    course: str
    title: str
    kind: str
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
        )
    return list(result.values())
