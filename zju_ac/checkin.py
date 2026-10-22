"""Manual or configured automatic attendance; HTTP stays on the monitor thread."""

import queue
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .client import CoursesClient, number_code
from .config import Settings
from .diagnostics import record as diagnostic
from .errors import AuthenticationExpired, SubmissionUncertain, ZjuError
from .gate import WaitingActivity, deadline_decision, evaluate_gate
from .models import SIGNED, AttendanceProgress, Rollcall
from .notify import Notifier


def display(value: str) -> str:
    return "".join(c for c in value if c.isprintable())[:160]


@dataclass(frozen=True)
class CodeRetry:
    record: Rollcall
    next_read_at: float


class MonitoringPaused(Exception):
    """Internal scheduling signal; no write has been started."""


@dataclass(frozen=True)
class Prompt:
    record: Rollcall
    stage: str = "confirm"

    def message(self) -> str:
        label = (
            f"《{display(self.record.course)}》{display(self.record.title)}"
            f"（编号 {display(self.record.id)}）"
        )
        if self.stage == "code":
            return f"未能自动读取 {label} 的数字码。请输入课堂公布的码（回车取消）："
        if self.record.kind == "GPS":
            return (
                f"确认提交 {label} 的 GPS 签到？将使用 config.toml 选定地点的坐标，"
                "只提交一次，不读取本机真实位置。[y/N]："
            )
        return f"确认提交 {label} 的数字签到？[y/N]："


@dataclass(frozen=True)
class Answer:
    prompt: Prompt
    value: str | None


class TerminalPrompts:
    """One daemon reads stdin; queues carry decisions back to the main thread."""

    def __init__(self):
        self.requests: queue.Queue[Prompt | None] = queue.Queue()
        self.answers: queue.Queue[Answer] = queue.Queue()
        self.closed = threading.Event()
        self.worker: threading.Thread | None = None

    def ask(self, prompt: Prompt) -> None:
        self.requests.put(prompt)
        if self.worker is None:
            self.worker = threading.Thread(target=self._read, name="attendance-input", daemon=True)
            self.worker.start()

    def _read(self) -> None:
        while not self.closed.is_set():
            prompt = self.requests.get()
            if prompt is None or self.closed.is_set():
                return
            try:
                answer = input(prompt.message()).strip()
            except (EOFError, KeyboardInterrupt, OSError):
                self.answers.put(Answer(prompt, None))
                return
            if not self.closed.is_set():
                self.answers.put(Answer(prompt, answer))

    def poll(self) -> list[Answer]:
        answers = []
        while True:
            try:
                answers.append(self.answers.get_nowait())
            except queue.Empty:
                return answers

    def close(self) -> None:
        self.closed.set()
        self.requests.put(None)


class ConfirmedCheckin:
    def __init__(
        self,
        client: CoursesClient,
        prompts: TerminalPrompts | None = None,
        *,
        settings: Settings | None = None,
        notifier: Notifier | None = None,
        stop_event=None,
        on_status=None,
        pause_event=None,
    ):
        self.client = client
        self.settings = settings if settings is not None else Settings()
        self.prompts = prompts if prompts is not None else TerminalPrompts()
        self.notifier = notifier if notifier is not None else Notifier(desktop=False, bell=False)
        self.stop_event = stop_event
        self.on_status = on_status
        self.pause_event = pause_event
        self.automatic: dict[str, WaitingActivity] = {}
        self.code_retries: dict[str, CodeRetry] = {}
        self.code_reads: dict[str, int] = {}
        self.results: set[str] = set()
        self.asked: set[str] = set()
        self.pending: dict[str, Prompt] = {}
        self.closed = False

    def observe(self, records: list[Rollcall]) -> None:
        if self.closed:
            return
        live = {record.id for record in records}
        current = {record.id: record for record in records}
        for rid, retry in list(self.code_retries.items()):
            latest = current.get(rid)
            if (
                latest is None
                or latest.kind != "数字"
                or latest.course_id != retry.record.course_id
            ):
                self.code_retries.pop(rid)
                diagnostic("code_cancelled", activity=rid)
            else:
                ends = [end for end in (latest.ends_at, retry.record.ends_at) if end is not None]
                self.code_retries[rid] = CodeRetry(
                    replace(latest, ends_at=min(ends) if ends else None), retry.next_read_at
                )
        for rid in self.automatic.keys() - live:
            self.automatic.pop(rid)
            print(f"[门控取消] 活动 {display(rid)} 已不在待签到列表。", flush=True)
        for record in records:
            if record.id in self.automatic:
                previous = self.automatic[record.id].record
                if previous.kind != record.kind or previous.course_id != record.course_id:
                    self.automatic.pop(record.id)
                    print(f"[门控取消] 活动 {display(record.id)} 类型或课程已变化。", flush=True)
                else:
                    self.automatic[record.id].record = record
                continue
            if record.kind in {"数字", "GPS"} and record.id not in self.asked:
                self.asked.add(record.id)
                if record.kind == "GPS":
                    if self.settings.gps is None:
                        self._status(record, "reminder", "未选择地点，请手动处理")
                        print("未配置 GPS 地点，本活动仅提醒，请检查 config.toml。", flush=True)
                        continue
                    print(f"GPS 将使用地点：{display(self.settings.gps.name)}。", flush=True)
                if self.settings.auto_checkin:
                    self.automatic[record.id] = WaitingActivity(record, time.monotonic())
                else:
                    self._ask(Prompt(record))

    def _ask(self, prompt: Prompt) -> None:
        self._status(
            prompt.record, "confirm", "等待确认" if prompt.stage == "confirm" else "等待补码"
        )
        self.pending[prompt.record.id] = prompt
        self.prompts.ask(prompt)

    def _status(self, record: Rollcall, stage: str, message: str) -> None:
        if self.on_status is not None:
            self.on_status(record, stage, message)

    def process(self) -> None:
        if self.pause_event is not None and self.pause_event.is_set():
            return
        if self.stop_event is not None and self.stop_event.is_set():
            return
        if self.closed:
            return
        self._process_automatic()
        if self.pause_event is not None and self.pause_event.is_set():
            return
        self._process_code_retries()
        for answer in self.prompts.poll():
            prompt = answer.prompt
            if self.pending.get(prompt.record.id) != prompt:
                continue
            self.pending.pop(prompt.record.id)
            if answer.value is None:
                print("终端输入已关闭，已取消待确认提交，继续仅提醒。", flush=True)
                self.close()
                return
            if prompt.stage == "confirm":
                if answer.value.lower() not in {"y", "yes"}:
                    self._status(prompt.record, "skipped", "已跳过")
                    print(
                        f"已跳过{prompt.record.kind}签到（编号 {display(prompt.record.id)}）。",
                        flush=True,
                    )
                    continue
                code = None
            else:
                code = number_code(answer.value)
                if code is None:
                    self._status(prompt.record, "skipped", "已取消")
                    print("数字码为空或格式无效，已取消本次提交。", flush=True)
                    continue
            self._submit(prompt.record, code)

    def _process_automatic(self) -> None:
        policy = self.settings.gate_settings
        for rid, activity in list(self.automatic.items()):
            if self.pause_event is not None and self.pause_event.is_set():
                return
            now, now_utc = time.monotonic(), datetime.now(UTC)
            decision = deadline_decision(activity, policy, self.settings.gate, now, now_utc)
            if decision is None:
                if now < activity.next_check_at:
                    continue
                progress = self.client.attendance_progress(activity.record)
                if isinstance(progress, AttendanceProgress) and progress.ends_at is not None:
                    activity.roster_ends_at = progress.ends_at
                # A roster read may take time; evaluate deadlines after it finishes too.
                now, now_utc = time.monotonic(), datetime.now(UTC)
                decision = evaluate_gate(
                    activity, policy, self.settings.gate, progress, now, now_utc
                )
            print(f"[门控] 活动 {display(rid)}：{decision.reason}。", flush=True)
            self._status(activity.record, "waiting", decision.reason)
            if decision.action == "wait":
                activity.next_check_at = now + policy.poll_interval_seconds
                continue
            self.automatic.pop(rid)
            if decision.action == "submit":
                print(f"自动处理{activity.record.kind}签到（编号 {display(rid)}）。", flush=True)
                self._submit(replace(activity.record, ends_at=activity.ends_at))
            else:
                self._result(activity.record, "failure")

    def _submit(self, record: Rollcall, code: str | None = None) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            return
        self._status(record, "checking", "正在核对活动状态")
        try:
            self._guard_pause()
            if record.kind == "GPS":
                self._submit_gps(record)
            else:
                self._submit_number(record, code)
        except MonitoringPaused:
            self.asked.discard(record.id)
        except AuthenticationExpired as exc:
            diagnostic("checkin_error", error=exc, activity=record.id)
            self._result(record, "failure")
            raise
        except ZjuError as exc:
            diagnostic("checkin_error", error=exc, activity=record.id)
            print(f"{record.kind}签到未完成：{exc}", flush=True)
            self._result(record, "failure")

    def _guard_pause(self):
        if self.pause_event is not None and self.pause_event.is_set():
            raise MonitoringPaused

    def cancel_pending_prompts(self):
        for rid in self.pending:
            self.asked.discard(rid)
        self.pending.clear()

    def _result(self, record: Rollcall, outcome: str) -> None:
        if record.id not in self.results:
            self.results.add(record.id)
            self._status(
                record,
                outcome,
                {"success": "已确认成功", "failure": "未完成", "pending": "待核验"}[outcome],
            )
            diagnostic("result", activity=record.id, outcome=outcome)
            self.notifier.result(record, outcome)

    def _process_code_retries(self) -> None:
        for rid, retry in list(self.code_retries.items()):
            if self.pause_event is not None and self.pause_event.is_set():
                return
            if retry.record.ends_at is not None and retry.record.ends_at <= datetime.now(UTC):
                self.code_retries.pop(rid)
                diagnostic("code_cancelled", activity=rid)
                print(f"[取码结束] 活动 {display(rid)} 已截止。", flush=True)
                self._result(retry.record, "failure")
            elif time.monotonic() >= retry.next_read_at:
                self.code_retries.pop(rid)
                self._submit(retry.record)

    def _missing_code(self, record: Rollcall) -> None:
        attempts = self.code_reads[record.id]
        diagnostic("code_missing", activity=record.id, attempt=attempts)
        if not self.settings.auto_checkin:
            self._ask(Prompt(record, "code"))
            return
        policy = self.settings.code_retry
        if attempts < policy.max_attempts:
            self.code_retries[record.id] = CodeRetry(
                record, time.monotonic() + policy.interval_seconds
            )
            self._status(record, "code_wait", f"等待取码 · {attempts}/{policy.max_attempts} 轮")
            diagnostic(
                "code_retry", activity=record.id, attempt=attempts, delay=policy.interval_seconds
            )
            print(
                f"自动取不到数字码（第 {attempts}/{policy.max_attempts} 轮），"
                f"至少 {policy.interval_seconds} 秒后重读，不提交或猜测数字码。",
                flush=True,
            )
        else:
            diagnostic("code_exhausted", activity=record.id, attempt=attempts)
            print(f"[取码结束] 已读 {attempts} 轮仍无数字码，请使用畅课处理。", flush=True)
            self._result(record, "failure")

    def _submit_number(self, record: Rollcall, code: str | None) -> None:
        self._guard_pause()
        fresh = self.client.fresh_number(record)
        if fresh is None:
            print("该签到已结束、已完成或类型已变化，已取消提交。", flush=True)
            diagnostic("code_cancelled", activity=record.id)
            return
        ends = [end for end in (fresh.ends_at, record.ends_at) if end is not None]
        fresh = replace(fresh, ends_at=min(ends) if ends else None)
        if fresh.ends_at is not None and fresh.ends_at <= datetime.now(UTC):
            self._result(fresh, "failure")
            return
        self._guard_pause()
        status = self.client.my_rollcall_status(fresh)
        if status in SIGNED:
            print("本人已签到，无需重复提交。", flush=True)
            self._result(fresh, "success")
            return
        if status != "absent":
            diagnostic(
                "submit_cancelled",
                activity=fresh.id,
                channel="number",
                reason="own_state_not_absent",
                status=status,
            )
            print("本人状态不是明确的待签到状态，已取消提交。", flush=True)
            self._result(fresh, "failure")
            return
        if code is None:
            self._guard_pause()
            if self.code_reads.get(record.id, 0) >= self.settings.code_retry.max_attempts:
                self._result(fresh, "failure")
                return
            self.code_reads[record.id] = self.code_reads.get(record.id, 0) + 1
            diagnostic("code_read", activity=record.id, attempt=self.code_reads[record.id])
            code = self.client.read_number_code(fresh)
            if code is None:
                self._missing_code(fresh)
                return
        # Code lookup or manual input can take time; check activity again just before PUT.
        self._guard_pause()
        if (
            fresh.ends_at is not None and fresh.ends_at <= datetime.now(UTC)
        ) or self.client.fresh_number(fresh) is None:
            print("提交前活动已结束或已完成，已取消提交。", flush=True)
            return
        try:
            self._guard_pause()
            if self.stop_event is not None and self.stop_event.is_set():
                return
            self._status(fresh, "submitting", "正在提交")
            diagnostic("submit_started", activity=fresh.id, channel="number")
            self.client.submit_number(fresh, code)
        except SubmissionUncertain as exc:
            diagnostic("submit_uncertain", activity=fresh.id, error=exc)
            print(str(exc), flush=True)
        self._verify(fresh)

    def _submit_gps(self, record: Rollcall) -> None:
        self._guard_pause()
        location = self.settings.gps
        if location is None:
            print("未配置 GPS 地点，已取消提交。", flush=True)
            return
        fresh = self.client.fresh_gps(record)
        if fresh is None:
            print("GPS 活动已结束、已完成或类型已变化，已取消后续定位请求。", flush=True)
            return
        self._guard_pause()
        status = self.client.my_rollcall_status(fresh)
        if status in SIGNED:
            print("本人已签到，无需继续定位请求。", flush=True)
            self._result(fresh, "success")
            return
        if status != "absent":
            diagnostic(
                "submit_cancelled",
                activity=fresh.id,
                channel="gps",
                reason="own_state_not_absent",
                status=status,
            )
            print("本人状态不是明确的待签到状态，已取消后续定位请求。", flush=True)
            self._result(fresh, "failure")
            return
        try:
            self._guard_pause()
            if self.stop_event is not None and self.stop_event.is_set():
                return
            self._status(fresh, "submitting", "正在提交")
            diagnostic("submit_started", activity=fresh.id, channel="gps")
            self.client.submit_gps(fresh, location.coordinates, accuracy=location.accuracy)
        except SubmissionUncertain as exc:
            diagnostic("submit_uncertain", activity=fresh.id, error=exc)
            print(str(exc), flush=True)
        self._verify(fresh)

    def _verify(self, fresh: Rollcall) -> None:
        try:
            verified = self.client.verify_attendance(fresh)
        except AuthenticationExpired as exc:
            diagnostic("verification_error", activity=fresh.id, error=exc)
            self._result(fresh, "pending")
            print("[待核验] 提交后会话失效，请在畅课中查看签到结果。", flush=True)
            raise
        except ZjuError as exc:
            diagnostic("verification_error", activity=fresh.id, error=exc)
            self._result(fresh, "pending")
            print(f"[待核验] 无法回查本人状态：{exc} 不会自动重复提交。", flush=True)
            return
        if verified:
            self._result(fresh, "success")
            print(
                f"[签到成功] {display(fresh.course)}（编号 {display(fresh.id)}），本人状态已确认。",
                flush=True,
            )
        else:
            self._result(fresh, "pending")
            print("[待核验] 尚未确认本人签到成功，请在畅课中查看；不会自动重复提交。", flush=True)

    def wait(self, seconds: float) -> None:
        """Process decisions promptly between polls without sharing the HTTP session."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.stop_event is not None and self.stop_event.is_set():
                return
            self.process()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                if self.stop_event is not None:
                    self.stop_event.wait(min(1, remaining))
                else:
                    time.sleep(min(1, remaining))

    def close(self) -> None:
        self.closed = True
        self.pending.clear()
        self.automatic.clear()
        self.code_retries.clear()
        self.prompts.close()
