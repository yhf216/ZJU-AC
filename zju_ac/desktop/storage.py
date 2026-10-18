"""Atomic desktop preferences, independent of the source-tree configuration."""

import copy
import json
import os
import sys
import tomllib
from pathlib import Path

from ..config import Settings, parse_config
from ..errors import ZjuError
from ..gps import Coordinates

FIELDS = {
    "auto": "checkin.auto_checkin",
    "gate": "checkin.gate",
    "location": "gps.location",
    "interval": "runtime.interval",
    "mode": "runtime.mode",
    "desktop": "notifications.desktop",
    "bell": "notifications.bell",
    "ratio": "checkin.gate_settings.signed_ratio",
    "count": "checkin.gate_settings.signed_count",
    "maxWait": "checkin.gate_settings.max_wait_seconds",
    "remaining": "checkin.gate_settings.min_remaining_seconds",
    "gateInterval": "checkin.gate_settings.poll_interval_seconds",
    "attempts": "checkin.code_retry.max_attempts",
    "retryInterval": "checkin.code_retry.interval_seconds",
    "watchdog": "watchdog.enabled",
    "restartDelay": "watchdog.restart_delay",
    "maxRestarts": "watchdog.max_restarts",
    "accuracy": "gps.accuracy",
    "loginTimeout": "runtime.login_timeout",
    "remindEvery": "runtime.remind_every",
}


def default_directory() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ZJU-AC"
    return Path.home() / ".local/share/ZJU-AC"


def template_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "config.toml"
    return Path(__file__).resolve().parents[2] / "config.toml"


def toml_dump(data: dict) -> str:
    lines = []

    def table(value, path):
        if path:
            lines.append("[" + ".".join(json.dumps(key, ensure_ascii=False) for key in path) + "]")
        for key, item in value.items():
            if not isinstance(item, dict):
                if not isinstance(item, (str, int, float, bool)):
                    raise ZjuError("配置值格式不支持。")
                lines.append(
                    json.dumps(key, ensure_ascii=False)
                    + " = "
                    + json.dumps(item, ensure_ascii=False)
                )
        lines.append("")
        for key, item in value.items():
            if isinstance(item, dict):
                table(item, path + [key])

    table(data, [])
    return "\n".join(lines)


class ConfigStore:
    def __init__(self, directory: Path, template: Path | None = None):
        self.directory = directory
        self.path = directory / "config.toml"
        directory.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            content = (template or template_path()).read_text(encoding="utf-8-sig")
            parse_config(tomllib.loads(content))
            self.path.write_text(content, encoding="utf-8")
        self.data = tomllib.loads(self.path.read_text(encoding="utf-8-sig"))
        self.settings = parse_config(self.data)

    @property
    def values(self) -> dict:
        s = self.settings
        return {
            "auto": s.auto_checkin,
            "gate": s.gate,
            "location": s.gps.location if s.gps else "",
            "interval": s.interval,
            "mode": s.mode,
            "desktop": s.desktop,
            "bell": s.bell,
            "ratio": s.gate_settings.signed_ratio,
            "count": s.gate_settings.signed_count,
            "maxWait": s.gate_settings.max_wait_seconds,
            "remaining": s.gate_settings.min_remaining_seconds,
            "gateInterval": s.gate_settings.poll_interval_seconds,
            "attempts": s.code_retry.max_attempts,
            "retryInterval": s.code_retry.interval_seconds,
            "watchdog": s.watchdog,
            "restartDelay": s.restart_delay,
            "maxRestarts": s.max_restarts,
            "accuracy": s.gps.accuracy if s.gps else self.data.get("gps", {}).get("accuracy", 35),
            "loginTimeout": s.login_timeout,
            "remindEvery": s.remind_every,
        }

    @property
    def locations(self) -> list[dict]:
        return [{"key": "", "name": "暂不选择地点"}] + [
            {"key": key, "name": item.get("name", key)}
            for key, item in self.data.get("gps", {}).get("locations", {}).items()
        ]

    def save(self, updates: dict) -> Settings:
        if updates.keys() - FIELDS.keys():
            raise ZjuError("设置包含未知字段。")
        data = copy.deepcopy(self.data)
        for name, value in updates.items():
            *parents, key = FIELDS[name].split(".")
            container = data
            for parent in parents:
                container = container.setdefault(parent, {})
            container[key] = value
        return self._write(data)

    def save_location(self, name: str, latitude: float, longitude: float) -> None:
        if not name.strip():
            raise ZjuError("请填写地点名称。")
        Coordinates(latitude, longitude)
        data = copy.deepcopy(self.data)
        gps = data.setdefault("gps", {})
        gps.setdefault("locations", {})["custom"] = {
            "name": name.strip()[:80],
            "latitude": latitude,
            "longitude": longitude,
        }
        gps["location"] = "custom"
        self._write(data)

    def _write(self, data: dict) -> Settings:
        settings = parse_config(data)
        content = toml_dump(data)
        parse_config(tomllib.loads(content))
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.data, self.settings = data, settings
        return settings
