"""Automatic submission policy, ready for subsequently specified conditions."""

from .errors import ZjuError
from .models import Rollcall


def allows_auto_checkin(record: Rollcall, mode: str) -> bool:
    """The only currently specified gate is immediate submission."""
    if mode != "immediate":
        raise ZjuError("自动签到门控尚未支持此条件，请修改 config.toml。")
    return True
