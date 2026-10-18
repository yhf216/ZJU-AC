"""Terminal reminders with optional desktop notifications."""

import logging
import sys
from datetime import datetime

from .diagnostics import record as diagnostic
from .models import Rollcall

LOGGER = logging.getLogger(__name__)


class Notifier:
    def __init__(self, desktop: bool = True, bell: bool = True):
        self.desktop = desktop
        self.bell = bell

    def send(self, rollcall: Rollcall) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        # Keep untrusted server titles on a single terminal line without control codes.
        course = "".join(c for c in rollcall.course if c.isprintable())[:160]
        title = "".join(c for c in rollcall.title if c.isprintable())[:160]
        rid = "".join(c for c in rollcall.id if c.isprintable())[:80]
        message = f"{course} · {rollcall.kind}签到 · {title}（编号 {rid}）"
        print(
            f"[{stamp}] 签到提醒：{message}\n请查看终端处理提示，或在畅课/学在浙大中完成签到。",
            flush=True,
        )
        if self.bell:
            print("\a", end="", flush=True)
        self._desktop("ZJU-AC 签到提醒", message)

    def result(self, rollcall: Rollcall, outcome: str) -> None:
        labels = {
            "success": ("签到成功", "已核实本人签到状态。"),
            "failure": ("签到未完成", "请查看终端原因，必要时使用畅课处理。"),
            "pending": ("签到待核验", "提交结果尚未确认，请在畅课核验；不会自动重发。"),
        }
        if outcome not in labels:
            raise ValueError("Unsupported check-in outcome")
        label, detail = labels[outcome]
        course = "".join(c for c in rollcall.course if c.isprintable())[:160]
        message = f"{course} · {rollcall.kind}签到。{detail}"
        if self.bell:
            print("\a", end="", flush=True)
        self._desktop(f"ZJU-AC {label}", message)

    def _desktop(self, title: str, message: str) -> None:
        if self.desktop:
            try:
                from plyer import notification

                notification.notify(
                    title=title,
                    message=message[:240],
                    app_name="ZJU-AC",
                    timeout=10,
                )
            except Exception as exc:
                diagnostic("notification_error", error=exc)
                LOGGER.warning("桌面通知不可用，已保留终端提醒。")
                self.desktop = False


def configure_terminal() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
