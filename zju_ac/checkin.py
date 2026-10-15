"""Manual or configured automatic attendance; HTTP stays on the monitor thread."""

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass

from .client import CoursesClient, number_code
from .config import Settings
from .errors import AuthenticationExpired, SubmissionUncertain, ZjuError
from .gate import allows_auto_checkin
from .models import SIGNED, Rollcall


def display(value: str) -> str:
    return "".join(c for c in value if c.isprintable())[:160]


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
    ):
        self.client = client
        self.settings = settings if settings is not None else Settings()
        self.prompts = prompts if prompts is not None else TerminalPrompts()
        self.automatic: deque[Rollcall] = deque()
        self.asked: set[str] = set()
        self.pending: dict[str, Prompt] = {}
        self.closed = False

    def observe(self, records: list[Rollcall]) -> None:
        if self.closed:
            return
        for record in records:
            if record.kind in {"数字", "GPS"} and record.id not in self.asked:
                if self.settings.auto_checkin and not allows_auto_checkin(
                    record, self.settings.gate
                ):
                    continue
                self.asked.add(record.id)
                if record.kind == "GPS":
                    if self.settings.gps is None:
                        print("未配置 GPS 地点，本活动仅提醒，请检查 config.toml。", flush=True)
                        continue
                    print(f"GPS 将使用地点：{display(self.settings.gps.name)}。", flush=True)
                if self.settings.auto_checkin:
                    self.automatic.append(record)
                else:
                    self._ask(Prompt(record))

    def _ask(self, prompt: Prompt) -> None:
        self.pending[prompt.record.id] = prompt
        self.prompts.ask(prompt)

    def process(self) -> None:
        if self.closed:
            return
        while self.automatic:
            record = self.automatic.popleft()
            print(f"自动处理{record.kind}签到（编号 {display(record.id)}）。", flush=True)
            self._submit(record)
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
                    print(
                        f"已跳过{prompt.record.kind}签到（编号 {display(prompt.record.id)}）。",
                        flush=True,
                    )
                    continue
                code = None
            else:
                code = number_code(answer.value)
                if code is None:
                    print("数字码为空或格式无效，已取消本次提交。", flush=True)
                    continue
            self._submit(prompt.record, code)

    def _submit(self, record: Rollcall, code: str | None = None) -> None:
        try:
            if record.kind == "GPS":
                self._submit_gps(record)
            else:
                self._submit_number(record, code)
        except AuthenticationExpired:
            raise
        except ZjuError as exc:
            print(f"{record.kind}签到未完成：{exc}", flush=True)

    def _submit_number(self, record: Rollcall, code: str | None) -> None:
        fresh = self.client.fresh_number(record)
        if fresh is None:
            print("该签到已结束、已完成或类型已变化，已取消提交。", flush=True)
            return
        status = self.client.my_rollcall_status(fresh)
        if status in SIGNED:
            print("本人已签到，无需重复提交。", flush=True)
            return
        if status != "absent":
            print("本人状态不是明确的待签到状态，已取消提交。", flush=True)
            return
        if code is None:
            code = self.client.read_number_code(fresh)
            if code is None:
                if self.settings.auto_checkin:
                    print("自动取不到数字码，本次仅提醒，不提交或猜测数字码。", flush=True)
                else:
                    self._ask(Prompt(fresh, "code"))
                return
        # Code lookup or manual input can take time; check activity again just before PUT.
        if self.client.fresh_number(fresh) is None:
            print("提交前活动已结束或已完成，已取消提交。", flush=True)
            return
        try:
            self.client.submit_number(fresh, code)
        except SubmissionUncertain as exc:
            print(str(exc), flush=True)
        self._verify(fresh)

    def _submit_gps(self, record: Rollcall) -> None:
        location = self.settings.gps
        if location is None:
            print("未配置 GPS 地点，已取消提交。", flush=True)
            return
        fresh = self.client.fresh_gps(record)
        if fresh is None:
            print("GPS 活动已结束、已完成或类型已变化，已取消后续定位请求。", flush=True)
            return
        status = self.client.my_rollcall_status(fresh)
        if status in SIGNED:
            print("本人已签到，无需继续定位请求。", flush=True)
            return
        if status != "absent":
            print("本人状态不是明确的待签到状态，已取消后续定位请求。", flush=True)
            return
        try:
            self.client.submit_gps(fresh, location.coordinates, accuracy=location.accuracy)
        except SubmissionUncertain as exc:
            print(str(exc), flush=True)
        self._verify(fresh)

    def _verify(self, fresh: Rollcall) -> None:
        try:
            verified = self.client.verify_attendance(fresh)
        except AuthenticationExpired:
            print("[待核验] 提交后会话失效，请在畅课中查看签到结果。", flush=True)
            raise
        except ZjuError as exc:
            print(f"[待核验] 无法回查本人状态：{exc} 不会自动重复提交。", flush=True)
            return
        if verified:
            print(
                f"[签到成功] {display(fresh.course)}（编号 {display(fresh.id)}），本人状态已确认。",
                flush=True,
            )
        else:
            print("[待核验] 尚未确认本人签到成功，请在畅课中查看；不会自动重复提交。", flush=True)

    def wait(self, seconds: float) -> None:
        """Process decisions promptly between polls without sharing the HTTP session."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.process()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(1, remaining))

    def close(self) -> None:
        self.closed = True
        self.pending.clear()
        self.automatic.clear()
        self.prompts.close()
