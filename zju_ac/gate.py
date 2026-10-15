"""Nonblocking attendance gate with per-activity deadlines and explicit fallbacks."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from .config import GateSettings
from .errors import ZjuError
from .models import AttendanceProgress, Rollcall


@dataclass
class WaitingActivity:
    record: Rollcall
    started_at: float
    next_check_at: float = 0
    roster_ends_at: datetime | None = None

    @property
    def ends_at(self) -> datetime | None:
        ends = [value for value in (self.record.ends_at, self.roster_ends_at) if value is not None]
        return min(ends) if ends else None


@dataclass(frozen=True)
class GateDecision:
    action: str
    reason: str


def deadline_decision(
    activity: WaitingActivity,
    settings: GateSettings,
    mode: str,
    now: float,
    now_utc: datetime,
) -> GateDecision | None:
    if mode not in {"immediate", "attendance"}:
        raise ZjuError("自动签到门控尚未支持此条件，请修改 config.toml。")
    remaining = (activity.ends_at - now_utc).total_seconds() if activity.ends_at else None
    if remaining is not None and remaining <= 0:
        return GateDecision("cancel", "签到已结束，取消等待")
    if mode == "immediate":
        return GateDecision("submit", "已配置直接签到")
    if now - activity.started_at >= settings.max_wait_seconds:
        return GateDecision("submit", f"等待达到 {settings.max_wait_seconds} 秒，保底放行")
    if remaining is not None and remaining <= settings.min_remaining_seconds:
        return GateDecision("submit", f"距结束不超过 {settings.min_remaining_seconds} 秒，保底放行")
    return None


def evaluate_gate(
    activity: WaitingActivity,
    settings: GateSettings,
    mode: str,
    progress: AttendanceProgress | None,
    now: float,
    now_utc: datetime,
) -> GateDecision:
    if isinstance(progress, AttendanceProgress) and progress.ends_at is not None:
        activity = replace(activity, roster_ends_at=progress.ends_at)
    decision = deadline_decision(activity, settings, mode, now, now_utc)
    if decision is not None:
        return decision
    if (
        not isinstance(progress, AttendanceProgress)
        or type(progress.total) is not int
        or type(progress.signed) is not int
        or progress.total <= 0
        or not 0 <= progress.signed <= progress.total
    ):
        return GateDecision("submit", "拿不到有效完整名单，保底放行")
    ratio_met = Decimal(progress.signed) > Decimal(progress.total) * Decimal(
        str(settings.signed_ratio)
    )
    counts = f"已签 {progress.signed}/{progress.total}"
    if ratio_met or progress.signed > settings.signed_count:
        return GateDecision("submit", f"{counts}，人数门控达标")
    return GateDecision("wait", f"{counts}，未超过比例或人数阈值，继续等待")
