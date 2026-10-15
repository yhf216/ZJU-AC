"""Terminal reminders with optional desktop notifications."""

import logging
import sys
from datetime import datetime

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
        if self.desktop:
            try:
                from plyer import notification

                notification.notify(
                    title="ZJU-AC 签到提醒",
                    message=message[:240],
                    app_name="ZJU-AC",
                    timeout=10,
                )
            except Exception:
                LOGGER.warning("桌面通知不可用，已保留终端提醒。")
                self.desktop = False


def configure_terminal() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
