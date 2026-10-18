"""Qt main-thread model and nonblocking process supervision."""

import json
import multiprocessing
import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .. import __version__
from ..diagnostics import export_bundle, record, setup
from ..errors import ZjuError
from .storage import ConfigStore
from .worker import worker_entry


class DesktopBridge(QObject):
    changed = Signal()
    preferencesChanged = Signal()
    activitiesChanged = Signal()
    eventsChanged = Signal()
    promptChanged = Signal()
    notification = Signal(str, str, str)
    hideRequested = Signal()
    quitReady = Signal()

    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store
        setup(store.directory / "logs")
        self.context = multiprocessing.get_context("spawn")
        self.process = self.connection = self.stop_event = None
        self._credentials = None
        self._status, self._message = "准备就绪", ""
        self._connected = self._stopping = self._quitting = False
        self._restart_at = 0
        self._stop_deadline = 0
        self._restarts = deque()
        self._started = 0
        self._last_poll = "—"
        self._polls = 0
        self._success = set()
        self._activities = {}
        self._events = []
        self._prompts = []
        self._dark = False
        self.tray_available = False
        try:
            self._dark = (
                json.loads((store.directory / "appearance.json").read_text("utf-8")).get("dark")
                is True
            )
        except (OSError, ValueError, AttributeError):
            pass
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self._last_second = -1

    @Property("QVariantMap", notify=changed)
    def state(self):
        elapsed = max(0, int(time.monotonic() - self._started)) if self._started else 0
        return {
            "running": self.process is not None or bool(self._restart_at),
            "connected": self._connected,
            "stopping": self._stopping,
            "status": self._status,
            "message": self._message,
            "dark": self._dark,
            "lastPoll": self._last_poll,
            "polls": self._polls,
            "success": len(self._success),
            "uptime": f"{elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}",
            "version": __version__,
            "date": datetime.now().strftime("%Y / %m / %d"),
        }

    @Property("QVariantMap", notify=preferencesChanged)
    def preferences(self):
        return self.store.values

    @Property("QVariantList", notify=preferencesChanged)
    def locations(self):
        return self.store.locations

    @Property("QVariantList", notify=activitiesChanged)
    def activities(self):
        return list(self._activities.values())[-30:][::-1]

    @Property("QVariantList", notify=eventsChanged)
    def events(self):
        return self._events[::-1]

    @Property("QVariantMap", notify=promptChanged)
    def prompt(self):
        return self._prompts[0] if self._prompts else {}

    def log(self, message: str, level="info"):
        text = "".join(c for c in message if c.isprintable())[:600]
        self._events.append(
            {"time": datetime.now().strftime("%H:%M:%S"), "message": text, "level": level}
        )
        self._events = self._events[-200:]
        self.eventsChanged.emit()

    @Slot(str, str)
    def startMonitor(self, student: str, password: str):
        if self.state["running"]:
            return
        if not student.strip() or not password:
            self._message = "请输入学号和密码。"
            self.changed.emit()
            return
        self._credentials = (student.strip(), password)
        self._stopping = self._quitting = False
        self._restarts.clear()
        self._activities.clear()
        self._success.clear()
        self._polls = 0
        self._last_poll = "—"
        self._started = time.monotonic()
        self._message = ""
        self.activitiesChanged.emit()
        self._spawn()

    def _spawn(self):
        self._restart_at = 0
        parent, child = self.context.Pipe()
        self.stop_event = self.context.Event()
        process = self.context.Process(
            target=worker_entry,
            args=(
                self.store.settings,
                self._credentials,
                child,
                self.stop_event,
                str(self.store.directory),
            ),
            name="zju-ac-desktop-worker",
        )
        try:
            process.start()
        except (OSError, ValueError) as exc:
            parent.close()
            self._credentials = None
            self._status, self._message = "无法启动", "工作进程启动失败，请导出日志。"
            record("worker_error", error=exc)
        else:
            self.process, self.connection = process, parent
            self._status = "正在登录"
            self.log("正在建立连接。")
        finally:
            child.close()
        self.changed.emit()

    @Slot()
    def stopMonitor(self):
        self._restart_at = 0
        self._credentials = None
        self._prompts.clear()
        self.promptChanged.emit()
        if self.process is not None:
            self._stopping = True
            self.stop_event.set()
            self._stop_deadline = time.monotonic() + 20
            self._status = "正在停止"
        else:
            self._connected = self._stopping = False
            self._status = "已暂停"
            if self._quitting:
                self.quitReady.emit()
        self.changed.emit()

    @Slot()
    def tick(self):
        if self.connection is not None:
            try:
                for _ in range(100):
                    if not self.connection.poll():
                        break
                    self.handle(self.connection.recv())
            except (EOFError, OSError):
                pass
        if self.process is not None and not self.process.is_alive():
            code = self.process.exitcode
            self.process.join(timeout=0)
            self.process.close()
            self.process = None
            self.connection.close()
            self.connection = None
            self._connected = False
            self._prompts.clear()
            self.promptChanged.emit()
            if self._quitting:
                self.quitReady.emit()
            elif self._stopping or code == 0:
                self._credentials = None
                self._status, self._stopping = "已暂停", False
                self.log("监控已停止。")
            else:
                now = time.monotonic()
                while self._restarts and now - self._restarts[0] >= 600:
                    self._restarts.popleft()
                settings = self.store.settings
                if (
                    code != 2
                    and settings.watchdog
                    and self._credentials
                    and len(self._restarts) < settings.max_restarts
                ):
                    self._restarts.append(now)
                    self._restart_at = now + settings.restart_delay
                    self._status = "等待恢复"
                    self.log(f"连接中断，{settings.restart_delay} 秒后尝试恢复。", "warning")
                else:
                    self._credentials = None
                    self._status = "需要处理"
                    self._message = self._message or "监控已停止，请检查网络或重新登录。"
            self.changed.emit()
        if self._stopping and self.process is not None and time.monotonic() >= self._stop_deadline:
            self.process.terminate()
            self._stop_deadline = time.monotonic() + 5
            self.log("工作进程未响应，已请求停止。请核验尚未完成的活动。", "warning")
        if self._restart_at and time.monotonic() >= self._restart_at:
            self._spawn()
        second = int(time.monotonic())
        if second != self._last_second:
            self._last_second = second
            self.changed.emit()

    def handle(self, event: dict):
        kind = event.get("type")
        if kind == "log":
            self.log(event["message"])
        elif kind == "connected":
            self._connected, self._status, self._message = True, "正在监控", ""
            self.changed.emit()
        elif kind == "poll":
            self._connected = True
            self._polls += 1
            self._last_poll = datetime.now().strftime("%H:%M:%S")
            self._status = "正在监控"
            live = {item["id"] for item in event["activities"]}
            for item in event["activities"]:
                self._activities.setdefault(item["id"], item)
            for rid, activity in list(self._activities.items()):
                if rid not in live and activity["stage"] not in {"success", "failure", "pending"}:
                    self._activities[rid] = {
                        **activity,
                        "stage": "closed",
                        "message": "活动已结束或已处理",
                    }
            self._activities = dict(list(self._activities.items())[-100:])
            self.activitiesChanged.emit()
            self.changed.emit()
        elif kind == "retry":
            self._connected = False
            self._status = "等待网络恢复"
            self.changed.emit()
        elif kind == "activity":
            item = event["activity"]
            self._activities[item["id"]] = item
            self.activitiesChanged.emit()
        elif kind in {"prompt", "otp"}:
            self._prompts.append(event)
            self.promptChanged.emit()
            if self.store.settings.desktop:
                self.notification.emit("需要确认", "请打开 ZJU-AC 完成确认。", "new")
        elif kind == "notification":
            outcome, item = event["outcome"], event["activity"]
            titles = {
                "new": "有新的待处理活动",
                "success": "签到成功",
                "failure": "签到未完成",
                "pending": "签到待核验",
            }
            if outcome == "success":
                self._success.add(item["id"])
                self.changed.emit()
            if self.store.settings.desktop:
                self.notification.emit(
                    titles[outcome], f"{item['course']} · {item['kind']}", outcome
                )
            if self.store.settings.bell:
                from PySide6.QtWidgets import QApplication

                QApplication.beep()
        elif kind == "error":
            self._message = event["message"]
            self.log(event["message"], "error")
            if event.get("bundle"):
                self.log("已生成诊断包，可在数据目录查看。", "warning")
            if self.store.settings.desktop:
                self.notification.emit("监控已中断", event["message"], "failure")
            self.changed.emit()

    @Slot(str)
    def replyPrompt(self, value: str):
        if not self._prompts:
            return
        prompt = self._prompts.pop(0)
        if self.connection is not None:
            try:
                self.connection.send({"type": "answer", "token": prompt["token"], "value": value})
            except (EOFError, OSError):
                self.log("连接已中断，请重新登录。", "warning")
        self.promptChanged.emit()

    @Slot(str, result=bool)
    def saveSettings(self, content: str):
        if self.state["running"]:
            self._message = "请先暂停监控，再修改设置。"
            self.changed.emit()
            return False
        try:
            updates = json.loads(content)
            if not isinstance(updates, dict):
                raise ValueError
            self.store.save(updates)
        except ZjuError as exc:
            self._message = str(exc)
        except (ValueError, TypeError, OSError):
            self._message = "设置未保存，请检查填写的数值与目录权限。"
        else:
            self._message = "设置已保存。"
            self.preferencesChanged.emit()
            self.changed.emit()
            return True
        self.changed.emit()
        return False

    @Slot()
    def clearMessage(self):
        self._message = ""
        self.changed.emit()

    @Slot(str, float, float, result=bool)
    def saveLocation(self, name, latitude, longitude):
        if self.state["running"]:
            return False
        try:
            self.store.save_location(name, latitude, longitude)
        except (ValueError, TypeError, OSError, ZjuError):
            self._message = "地点未保存，请填写名称与有效的经纬度。"
            self.changed.emit()
            return False
        self._message = "手动地点已保存并选中。"
        self.preferencesChanged.emit()
        self.changed.emit()
        return True

    @Slot()
    def toggleTheme(self):
        self._dark = not self._dark
        try:
            (self.store.directory / "appearance.json").write_text(
                json.dumps({"dark": self._dark}), "utf-8"
            )
        except OSError:
            pass
        self.changed.emit()

    @Slot()
    def exportLogs(self):
        try:
            target = export_bundle(self.store.directory / "logs")
        except OSError:
            self._message = "导出失败，请检查数据目录权限。"
        else:
            self._message = f"诊断包已保存：{target.name}"
            self.log(self._message)
        self.changed.emit()

    @Slot()
    def openDirectory(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.directory)))

    @Slot()
    def testNotification(self):
        self.notification.emit("ZJU-AC", "通知已连接，一切就绪。", "success")

    @Slot()
    def closeWindow(self):
        if self.tray_available and self.state["running"]:
            self.hideRequested.emit()
        else:
            self.requestQuit()

    @Slot()
    def requestQuit(self):
        self._quitting = True
        self.stopMonitor()

    def shutdown(self):
        self.timer.stop()
        self._credentials = None
        if self.stop_event is not None:
            self.stop_event.set()
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
            self.process.close()
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
