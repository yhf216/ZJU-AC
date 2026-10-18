"""Deduplicate reminders and retry transient read failures with bounded backoff."""

import logging
import time
from collections import OrderedDict

from .checkin import ConfirmedCheckin
from .client import CoursesClient
from .diagnostics import record as diagnostic
from .errors import TemporaryError
from .models import Rollcall
from .notify import Notifier

LOGGER = logging.getLogger(__name__)


class ReminderTracker:
    def __init__(self, repeat_after: float = 0):
        self.repeat_after = repeat_after
        self.sent: OrderedDict[str, float] = OrderedDict()

    def due(self, record: Rollcall, now: float) -> bool:
        previous = self.sent.get(record.id)
        return previous is None or (self.repeat_after > 0 and now - previous >= self.repeat_after)

    def mark(self, record: Rollcall, now: float) -> None:
        self.sent[record.id] = now
        self.sent.move_to_end(record.id)
        while len(self.sent) > 2000:
            self.sent.popitem(last=False)


def run_monitor(
    client: CoursesClient,
    notifier: Notifier,
    interval: float = 15,
    repeat_after: float = 0,
    once: bool = False,
    checkin: ConfirmedCheckin | None = None,
) -> None:
    tracker = ReminderTracker(repeat_after)
    failures = 0
    while True:
        started = time.monotonic()
        try:
            records = client.rollcalls()
        except TemporaryError as exc:
            diagnostic("poll_error", error=exc)
            if once:
                raise
            failures += 1
            delay = min(300, interval * 2 ** min(failures, 5))
            LOGGER.warning("%s %.0f 秒后重试。", exc, delay)
            if checkin is None:
                time.sleep(delay)
            else:
                checkin.wait(delay)
            continue
        failures = 0
        diagnostic("poll_ok", count=len(records))
        LOGGER.info("监控正常：当前有 %d 项待签到。", len(records))
        for record in records:
            if tracker.due(record, started):
                notifier.send(record)
                tracker.mark(record, started)
        if checkin is not None and not once:
            checkin.observe(records)
            checkin.process()
        if once:
            return
        delay = max(0, interval - (time.monotonic() - started))
        if checkin is None:
            time.sleep(delay)
        else:
            checkin.wait(delay)
