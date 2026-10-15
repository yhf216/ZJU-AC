"""Validate root UTF-8 TOML settings before requesting credentials."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ZjuError
from .gps import Coordinates

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"


@dataclass(frozen=True, repr=False)
class GpsSettings:
    location: str
    name: str
    coordinates: Coordinates
    accuracy: float = 35.0


@dataclass(frozen=True)
class GateSettings:
    signed_ratio: float = 0.25
    signed_count: int = 20
    max_wait_seconds: int = 120
    min_remaining_seconds: int = 30
    poll_interval_seconds: int = 5


@dataclass(frozen=True)
class Settings:
    mode: str = "monitor"
    interval: int = 15
    remind_every: int = 0
    login_timeout: int = 180
    auto_checkin: bool = True
    gate: str = "attendance"
    gate_settings: GateSettings = field(default_factory=GateSettings)
    desktop: bool = True
    bell: bool = True
    watchdog: bool = True
    restart_delay: int = 15
    max_restarts: int = 5
    gps: GpsSettings | None = None

    @property
    def once(self) -> bool:
        return self.mode == "once"

    @property
    def demo(self) -> bool:
        return self.mode == "demo"

    @property
    def reminders_only(self) -> bool:
        return self.mode == "reminders"


def _table(data: dict, key: str, allowed: set[str]) -> dict:
    table = data.get(key, {})
    if not isinstance(table, dict) or table.keys() - allowed:
        raise ZjuError(f"config.toml 的 {key} 配置结构或字段名无效。")
    return table


def _boolean(data: dict, key: str, default: bool) -> bool:
    value = data.get(key, default)
    if type(value) is not bool:
        raise ZjuError(f"config.toml 的 {key} 必须为 true 或 false。")
    return value


def _integer(data: dict, key: str, default: int, minimum: int, zero: bool = False) -> int:
    value = data.get(key, default)
    if type(value) is not int or not (value >= minimum or zero and value == 0):
        suffix = "，也可设为 0" if zero else ""
        raise ZjuError(f"config.toml 的 {key} 必须为至少 {minimum} 的整数{suffix}。")
    return value


def _choice(data: dict, key: str, default: str, choices: set[str]) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or value not in choices:
        raise ZjuError(f"config.toml 的 {key} 必须为 {' / '.join(sorted(choices))}。")
    return value


def _gps(data: dict) -> GpsSettings | None:
    gps = _table(data, "gps", {"location", "accuracy", "locations"})
    selected = gps.get("location", "")
    locations = gps.get("locations", {})
    accuracy = gps.get("accuracy", 35.0)
    if not isinstance(selected, str) or not isinstance(locations, dict):
        raise ZjuError("config.toml 的 gps.location 或 gps.locations 格式无效。")
    if (
        isinstance(accuracy, bool)
        or not isinstance(accuracy, (int, float))
        or not 0 < accuracy <= 10000
    ):
        raise ZjuError("config.toml 的 gps.accuracy 必须大于 0 且不超过 10000 米。")
    validated = {}
    for key in locations:
        item = _table(locations, key, {"name", "latitude", "longitude"})
        name = item.get("name", key)
        if not isinstance(name, str) or not name.strip():
            raise ZjuError("config.toml 的 GPS 地点名称必须为非空文本。")
        coordinates = Coordinates(item.get("latitude"), item.get("longitude"))
        validated[key] = GpsSettings(key, name, coordinates, float(accuracy))
    if not selected:
        return None
    if selected not in validated:
        raise ZjuError("config.toml 的 gps.location 没有对应的地点坐标。")
    return validated[selected]


def load_config(path: Path | None = None) -> Settings:
    path = CONFIG_PATH if path is None else path
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ZjuError("无法读取 config.toml，请检查根目录文件及 UTF-8 TOML 格式。") from exc
    if data.keys() - {"runtime", "checkin", "notifications", "watchdog", "gps"}:
        raise ZjuError("config.toml 存在未知配置节，请对照项目示例。")
    runtime = _table(data, "runtime", {"mode", "interval", "remind_every", "login_timeout"})
    checkin = _table(data, "checkin", {"auto_checkin", "gate", "gate_settings"})
    gate = _table(
        checkin,
        "gate_settings",
        {
            "signed_ratio",
            "signed_count",
            "max_wait_seconds",
            "min_remaining_seconds",
            "poll_interval_seconds",
        },
    )
    ratio = gate.get("signed_ratio", 0.25)
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
        raise ZjuError("config.toml 的 signed_ratio 必须为 0 到 1 之间的数值。")
    notifications = _table(data, "notifications", {"desktop", "bell"})
    watchdog = _table(data, "watchdog", {"enabled", "restart_delay", "max_restarts"})
    return Settings(
        mode=_choice(runtime, "mode", "monitor", {"monitor", "reminders", "once", "demo"}),
        interval=_integer(runtime, "interval", 15, 5),
        remind_every=_integer(runtime, "remind_every", 0, 5, zero=True),
        login_timeout=_integer(runtime, "login_timeout", 180, 5),
        auto_checkin=_boolean(checkin, "auto_checkin", True),
        gate=_choice(checkin, "gate", "attendance", {"immediate", "attendance"}),
        gate_settings=GateSettings(
            signed_ratio=float(ratio),
            signed_count=_integer(gate, "signed_count", 20, 0),
            max_wait_seconds=_integer(gate, "max_wait_seconds", 120, 1),
            min_remaining_seconds=_integer(gate, "min_remaining_seconds", 30, 0),
            poll_interval_seconds=_integer(gate, "poll_interval_seconds", 5, 1),
        ),
        desktop=_boolean(notifications, "desktop", True),
        bell=_boolean(notifications, "bell", True),
        watchdog=_boolean(watchdog, "enabled", True),
        restart_delay=_integer(watchdog, "restart_delay", 15, 1),
        max_restarts=_integer(watchdog, "max_restarts", 5, 1),
        gps=_gps(data),
    )
