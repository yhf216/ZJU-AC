import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QObject, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from zju_ac.config import CONFIG_PATH
from zju_ac.desktop.bridge import DesktopBridge
from zju_ac.desktop.storage import ConfigStore


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QQuickStyle.setStyle("Basic")
    if os.name == "nt":
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/msyh.ttc"))
    return app


@pytest.fixture
def bridge(application, tmp_path, monkeypatch):
    monkeypatch.setattr("zju_ac.desktop.bridge.setup", lambda *args: None)
    bridge = DesktopBridge(ConfigStore(tmp_path, CONFIG_PATH))
    yield bridge
    bridge.shutdown()


def test_qml_pages_and_password_clearing(application, bridge):
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
    engine.rootContext().setContextProperty("backend", bridge)
    path = Path(__file__).resolve().parents[1] / "zju_ac/desktop/qml/Main.qml"
    engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    window.show()
    for page in (0, 1, 2):
        window.setProperty("page", page)
        application.processEvents()
    dialog = window.findChild(QObject, "loginDialog")
    password = window.findChild(QObject, "passwordField")
    QMetaObject.invokeMethod(dialog, "open")
    password.setProperty("text", "private-password")
    QMetaObject.invokeMethod(dialog, "close")
    application.processEvents()
    assert password.property("text") == ""
    assert not warnings
    window.hide()
    engine.deleteLater()
    application.processEvents()


def test_prompt_reply_uses_exact_token_and_never_logs_answer(bridge):
    connection = Mock()
    bridge.connection = connection
    bridge.handle({"type": "otp", "token": "challenge"})
    bridge.replyPrompt("123456")
    connection.send.assert_called_once_with(
        {"type": "answer", "token": "challenge", "value": "123456"}
    )
    assert not bridge.prompt
    assert "123456" not in json.dumps(bridge.events)
    bridge.connection = None


def test_settings_locked_during_monitor_and_unlock_after_stop(bridge):
    bridge._restart_at = 100
    assert not bridge.saveSettings(json.dumps({"attempts": 1}))
    assert bridge.preferences["attempts"] == 5
    bridge.stopMonitor()
    assert bridge.saveSettings(json.dumps({"attempts": 1}))
    assert bridge.preferences["attempts"] == 1


def test_stop_signals_worker_without_waiting_on_network(bridge):
    process, stop = Mock(), Mock()
    bridge.process, bridge.stop_event = process, stop
    bridge._credentials = ("private", "secret")
    bridge.stopMonitor()
    stop.set.assert_called_once()
    process.join.assert_not_called()
    process.terminate.assert_not_called()
    assert bridge._credentials is None
    bridge.process = None


def test_result_notifications_keep_pending_separate_and_deduplicate_count(bridge):
    notices = []
    bridge.notification.connect(lambda *values: notices.append(values))
    bridge.store.save({"bell": False})
    activity = {"id": "42", "course": "课程", "kind": "数字"}
    for outcome in ("pending", "success", "success"):
        bridge.handle({"type": "notification", "outcome": outcome, "activity": activity})
    assert notices[0][0] == "签到待核验"
    assert bridge.state["success"] == 1


@pytest.mark.parametrize("code,restart", [(1, True), (-1, True), (2, False), (0, False)])
def test_desktop_supervisor_restarts_only_recoverable_exits(bridge, monkeypatch, code, restart):
    now = [1000.0]
    monkeypatch.setattr("zju_ac.desktop.bridge.time.monotonic", lambda: now[0])
    process, connection = Mock(), Mock()
    process.is_alive.return_value = False
    process.exitcode = code
    connection.poll.return_value = False
    bridge.process, bridge.connection = process, connection
    bridge._credentials = ("student", "secret")
    bridge.tick()
    assert bool(bridge._restart_at) is restart
    if restart:
        spawn = Mock()
        monkeypatch.setattr(bridge, "_spawn", spawn)
        now[0] += bridge.store.settings.restart_delay
        bridge.tick()
        spawn.assert_called_once()
    else:
        assert bridge._credentials is None


def test_network_status_recovers_after_next_successful_poll(bridge):
    bridge.handle({"type": "retry", "delay": 30})
    assert not bridge.state["connected"]
    assert bridge.state["status"] == "等待网络恢复"
    bridge.handle({"type": "poll", "activities": []})
    assert bridge.state["connected"]
    assert bridge.state["status"] == "正在监控"
