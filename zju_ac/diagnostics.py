"""Bounded, allowlisted diagnostics; never serialize exceptions or HTTP payloads."""

import hashlib
import json
import logging
import os
import platform
import sys
import traceback
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from . import __version__

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
EVENTS = {
    "startup",
    "config_error",
    "application_error",
    "poll_ok",
    "poll_error",
    "code_read",
    "code_missing",
    "code_retry",
    "code_exhausted",
    "code_cancelled",
    "channel_error",
    "http_response",
    "own_status",
    "submit_cancelled",
    "network_error",
    "submit_started",
    "submit_uncertain",
    "checkin_error",
    "verification_error",
    "result",
    "worker_exit",
    "worker_error",
    "notification_error",
    "activity_detected",
    "manual_prompt",
    "manual_decision",
    "gate_evaluated",
    "precheck_fallback",
    "code_available",
    "verification_started",
    "notification_requested",
    "notification_dispatched",
}
CHANNELS = {"profile", "discovery", "detail", "timetable", "own_status", "number", "gps"}
OUTCOMES = {"success", "failure", "pending"}
_recorder = None


class Recorder:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.salt = uuid.uuid4().hex
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = directory / f"diagnostic-{stamp}-{os.getpid()}.jsonl"
        # Separate files avoid parent/worker rotation races on Windows.
        self.handler = RotatingFileHandler(
            self.path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8", delay=True
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        for old in sorted(directory.glob("diagnostic-*.jsonl"))[:-9]:
            for candidate in (old, Path(str(old) + ".1"), Path(str(old) + ".2")):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass

    def emit(
        self,
        event: str,
        *,
        error: BaseException | None = None,
        activity: str | None = None,
        attempt: int | None = None,
        delay: int | None = None,
        count: int | None = None,
        total: int | None = None,
        channel: str | None = None,
        http_status: int | None = None,
        outcome: str | None = None,
        source: str | None = None,
        reason: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        action: str | None = None,
    ) -> None:
        if event not in EVENTS:
            return
        data = {"time": datetime.now(UTC).isoformat(), "event": event, "version": __version__}
        if activity is not None:
            data["activity"] = hashlib.sha256((self.salt + activity).encode()).hexdigest()[:12]
        for key, value in (
            ("attempt", attempt),
            ("delay", delay),
            ("count", count),
            ("total", total),
        ):
            if type(value) is int and 0 <= value <= 1000000:
                data[key] = value
        if channel in CHANNELS:
            data["channel"] = channel
        if type(http_status) is int and 100 <= http_status <= 599:
            data["http_status"] = http_status
        if outcome in OUTCOMES:
            data["outcome"] = outcome
        if source in {"course", "radar"}:
            data["source"] = source
        if reason in {
            "matched",
            "missing_record",
            "missing_status",
            "unsupported_shape",
            "conflicting_records",
            "own_state_not_absent",
            "expired",
            "immediate",
            "max_wait",
            "ending",
            "no_roster",
            "threshold_met",
            "threshold_wait",
            "gate_error",
            "no_location",
        }:
            data["reason"] = reason
        if stage in {"confirm", "code", "display", "activity", "own_status", "gate"}:
            data["stage"] = stage
        if action in {"submit", "wait", "cancel"}:
            data["action"] = action
        if event in {"own_status", "submit_cancelled", "precheck_fallback"}:
            data["status"] = (
                status
                if status in {"absent", "on_call", "on_call_fine", "on_personal_leave"}
                else "missing"
                if status is None
                else "unknown"
            )
        if error is not None:
            chain, visited = [], set()
            while error is not None and id(error) not in visited and len(chain) < 5:
                visited.add(id(error))
                chain.append(
                    {
                        "type": type(error).__name__,
                        "frames": [
                            {
                                "file": Path(frame.filename).name,
                                "line": frame.lineno,
                                "function": frame.name,
                            }
                            for frame in traceback.extract_tb(error.__traceback__)[-20:]
                        ],
                    }
                )
                error = error.__cause__ or error.__context__
            data["errors"] = chain
        message = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        self.handler.handle(
            logging.LogRecord("diagnostics", logging.INFO, "", 0, message, (), None)
        )

    def close(self) -> None:
        self.handler.close()


def setup(directory: Path | None = None) -> None:
    global _recorder
    if _recorder is not None:
        return
    try:
        _recorder = Recorder(LOG_DIR if directory is None else directory)
        record("startup")
    except OSError:
        print("诊断日志无法写入，程序继续运行。", file=sys.stderr)


def record(event: str, **fields) -> None:
    if _recorder is not None:
        try:
            _recorder.emit(event, **fields)
        except (OSError, ValueError):
            pass  # Diagnostics must never interrupt attendance or mask the original error.


def export_bundle(directory: Path | None = None) -> Path:
    directory = directory or (_recorder.directory if _recorder is not None else LOG_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    if _recorder is not None:
        _recorder.handler.flush()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"support-{stamp}.zip"
    # Read only our structured files. No terminal logs, config, source or credentials.
    snapshots = []
    for base in sorted(directory.glob("diagnostic-*.jsonl"))[-10:]:
        for path in (Path(str(base) + ".2"), Path(str(base) + ".1"), base):
            try:
                snapshots.append((path.name, path.read_bytes()[-512 * 1024 :]))
            except OSError:
                pass
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as bundle:
        metadata = {
            "version": __version__,
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        }
        bundle.writestr("environment.json", json.dumps(metadata, ensure_ascii=False))
        for name, data in snapshots:
            bundle.writestr(name, data)
    return target


def report_error(event: str, error: BaseException) -> None:
    record(event, error=error)
    if _recorder is None:
        print("诊断日志不可用，未生成诊断包。", file=sys.stderr)
        return
    try:
        path = export_bundle()
    except OSError:
        print("诊断包导出失败，请检查 logs 目录权限和磁盘空间。", file=sys.stderr)
    else:
        print(f"脱敏诊断包已导出：{path}", file=sys.stderr)


def main() -> int:
    try:
        print(f"脱敏诊断包已导出：{export_bundle()}")
        return 0
    except OSError:
        print("诊断包导出失败，请检查 logs 目录权限和磁盘空间。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
