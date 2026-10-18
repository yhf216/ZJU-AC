"""Spawn-safe desktop worker. No Qt, console input or disk credentials."""

import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..auth import login
from ..checkin import Answer, ConfirmedCheckin, display
from ..diagnostics import export_bundle, record, setup
from ..errors import AuthenticationExpired, TemporaryError, ZjuError
from ..monitor import run_monitor


def activity_data(activity):
    return {
        "id": activity.id,
        "course": display(activity.course),
        "kind": activity.kind,
        "title": display(activity.title),
        "stage": "waiting",
        "message": "等待处理",
    }


class Cancelled(Exception):
    pass


class EventStream:
    def __init__(self, send):
        self.send = send
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = "".join(char for char in line if char.isprintable())[:600]
            if line.strip():
                self.send({"type": "log", "message": line})
        self.buffer = self.buffer[-1200:]
        return len(text)

    def flush(self):
        pass


class DesktopPrompts:
    def __init__(self, connection, stop_event):
        self.connection, self.stop_event = connection, stop_event
        self.pending = {}

    def ask(self, prompt):
        token = uuid.uuid4().hex
        self.pending[token] = prompt
        self.connection.send(
            {
                "type": "prompt",
                "token": token,
                "stage": prompt.stage,
                "activity": activity_data(prompt.record),
            }
        )

    def poll(self):
        answers = []
        while self.connection.poll():
            message = self.connection.recv()
            if message.get("type") != "answer":
                continue
            prompt = self.pending.pop(message.get("token"), None)
            if prompt is not None:
                answers.append(Answer(prompt, str(message.get("value", ""))))
        return answers

    def otp(self, message):
        token = uuid.uuid4().hex
        self.connection.send({"type": "otp", "token": token})
        while not self.stop_event.wait(0.1):
            if self.connection.poll():
                answer = self.connection.recv()
                if answer.get("token") == token:
                    return str(answer.get("value", ""))
        raise Cancelled

    def close(self):
        self.pending.clear()


class DesktopNotifier:
    def __init__(self, connection, settings):
        self.connection, self.settings = connection, settings

    def send(self, activity):
        if (
            self.settings.reminders_only
            or self.settings.once
            or activity.kind not in {"数字", "GPS"}
        ):
            self.connection.send(
                {
                    "type": "activity",
                    "activity": {
                        **activity_data(activity),
                        "stage": "reminder",
                        "message": "请在畅课中处理",
                    },
                }
            )
        self.connection.send(
            {"type": "notification", "outcome": "new", "activity": activity_data(activity)}
        )

    def result(self, activity, outcome):
        self.connection.send(
            {"type": "notification", "outcome": outcome, "activity": activity_data(activity)}
        )


def worker_entry(settings, credentials, connection, stop_event, directory: str):
    setup(Path(directory) / "logs")
    original_out, original_err = sys.stdout, sys.stderr
    stream = EventStream(connection.send)
    sys.stdout = sys.stderr = stream
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("zju_ac")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    prompts = DesktopPrompts(connection, stop_event)
    controller = None
    code = 0
    try:
        if settings.demo:
            for outcome in ("new", "success", "failure", "pending"):
                connection.send(
                    {
                        "type": "notification",
                        "outcome": outcome,
                        "activity": {
                            "id": "demo",
                            "course": "离线演示",
                            "kind": "数字",
                            "title": "通知演示",
                            "stage": "waiting",
                            "message": "离线演示",
                        },
                    }
                )
            return
        student, password = credentials
        del credentials
        with login(student, password, settings.login_timeout, otp_reader=prompts.otp) as client:
            password = ""
            connection.send({"type": "connected"})
            notifier = DesktopNotifier(connection, settings)

            def status(activity, stage, message):
                connection.send(
                    {
                        "type": "activity",
                        "activity": {**activity_data(activity), "stage": stage, "message": message},
                    }
                )

            controller = (
                None
                if settings.reminders_only or settings.once
                else ConfirmedCheckin(
                    client,
                    prompts,
                    settings=settings,
                    notifier=notifier,
                    stop_event=stop_event,
                    on_status=status,
                )
            )
            run_monitor(
                client,
                notifier,
                settings.interval,
                settings.remind_every,
                settings.once,
                checkin=controller,
                stop_event=stop_event,
                on_poll=lambda activities: connection.send(
                    {
                        "type": "poll",
                        "activities": [activity_data(item) for item in activities],
                        "time": datetime.now(UTC).isoformat(),
                    }
                ),
                on_failure=lambda delay: connection.send({"type": "retry", "delay": int(delay)}),
            )
    except (Cancelled, EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        code = 1 if isinstance(exc, (AuthenticationExpired, TemporaryError)) else 2
        if not isinstance(exc, ZjuError):
            code = 1
        record("application_error", error=exc)
        try:
            bundle = str(export_bundle(Path(directory) / "logs"))
        except OSError:
            bundle = ""
        # Expected errors in core are safe; unknown exception messages may contain credentials.
        message = (
            str(exc) if isinstance(exc, ZjuError) else f"程序遇到异常（{type(exc).__name__}）。"
        )
        try:
            connection.send({"type": "error", "message": message, "bundle": bundle})
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        if controller is not None:
            controller.close()
        prompts.close()
        logger.removeHandler(handler)
        sys.stdout, sys.stderr = original_out, original_err
        connection.close()
    raise SystemExit(code)


def smoke_test(directory: Path) -> int:
    """Exercise real spawn/freeze routing with demo notifications and no network."""
    import json
    import multiprocessing
    import time

    from ..config import Settings

    directory.mkdir(parents=True, exist_ok=True)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    stop = context.Event()
    process = context.Process(
        target=worker_entry,
        args=(
            Settings(mode="demo", desktop=False, bell=False),
            ("offline", "unused"),
            child,
            stop,
            str(directory),
        ),
    )
    outcomes = []
    try:
        process.start()
        child.close()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if parent.poll(0.1):
                    event = parent.recv()
                    if event.get("type") == "notification":
                        outcomes.append(event["outcome"])
            except (EOFError, OSError):
                break
        process.join(timeout=1)
        result = {"exitcode": process.exitcode, "outcomes": outcomes}
        (directory / "worker-smoke.json").write_text(json.dumps(result), encoding="utf-8")
        return (
            0
            if result == {"exitcode": 0, "outcomes": ["new", "success", "failure", "pending"]}
            else 1
        )
    finally:
        stop.set()
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
        process.close()
        parent.close()
