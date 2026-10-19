import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
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
    account = window.findChild(QObject, "currentAccount")
    assert not account.property("visible")
    bridge._session_account = "test-account"
    bridge.handle({"type": "connected"})
    application.processEvents()
    assert account.property("visible")
    assert account.property("text") == "已登录学号：test-account"
    bridge.stopMonitor()
    application.processEvents()
    assert not account.property("visible")
    for page in (0, 1, 2):
        window.setProperty("page", page)
        application.processEvents()
    window.setProperty("page", 0)
    window.setWidth(620)
    window.setHeight(480)
    QTest.qWait(100)
    scroll = window.findChild(QObject, "mainScroll")
    flickable = scroll.property("contentItem")
    assert flickable.property("contentHeight") > flickable.property("height")
    event = QWheelEvent(
        QPointF(550, 80),
        QPointF(550, 80),
        QPoint(),
        QPoint(0, -120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    application.sendEvent(window, event)
    QTest.qWait(150)
    assert flickable.property("contentY") > 0
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


def test_current_account_shown_only_for_authenticated_session(bridge, monkeypatch):
    monkeypatch.setattr("zju_ac.desktop.bridge.seal_credentials", lambda *args: b"encrypted")
    monkeypatch.setattr(bridge, "_spawn", Mock())
    bridge._saved_account = "previous-account"
    assert bridge.state["account"] == ""
    bridge.startMonitor("  current-account  ", "password", False)
    assert bridge.state["account"] == ""
    bridge.handle({"type": "connected"})
    assert bridge.state["account"] == "current-account"
    bridge.handle({"type": "paused"})
    bridge.forgetPassword()
    assert bridge.state["account"] == "current-account"
    bridge.handle({"type": "retry", "delay": 30})
    assert bridge.state["account"] == "current-account"
    bridge.stopMonitor()
    assert bridge.state["account"] == ""
    bridge.startMonitor("next-account", "password", False)
    assert bridge.state["account"] == ""
    assert "current-account" not in json.dumps(bridge.events)


def test_default_theme_is_dark_and_pause_keeps_credentials_and_clock(bridge, monkeypatch):
    import threading

    now = [100.0]
    monkeypatch.setattr("zju_ac.desktop.bridge.time.monotonic", lambda: now[0])
    assert bridge.state["dark"]
    bridge.process = Mock()
    bridge.pause_event = threading.Event()
    bridge._credentials = b"encrypted-session"
    bridge.handle({"type": "connected"})
    now[0] = 110
    bridge.pauseMonitor()
    assert bridge.pause_event.is_set()
    bridge.handle({"type": "paused"})
    assert bridge._credentials == b"encrypted-session"
    assert bridge.state["authenticated"]
    assert bridge.state["canEdit"]
    now[0] = 130
    assert bridge.state["uptime"] == "00:00:30"
    bridge.resumeMonitor()
    assert not bridge.pause_event.is_set()
    assert not bridge.state["canEdit"]
    bridge.handle({"type": "resumed"})
    assert not bridge.state["paused"]
    bridge.process = None
    bridge.stopMonitor()
    now[0] = 200
    assert bridge.state["uptime"] == "00:00:30"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_remembered_credentials_saved_only_after_success_and_never_exposed_to_qml(
    bridge, monkeypatch
):
    from zju_ac.desktop.credentials import open_credentials

    monkeypatch.setattr(bridge, "_spawn", Mock())
    bridge.startMonitor("private-student", "private-password", True)
    assert not bridge.vault.path.exists()
    assert open_credentials(bridge._credentials) == ("private-student", "private-password")
    assert "private-password" not in json.dumps(bridge.state)
    bridge.handle({"type": "connected"})
    assert bridge.vault.load() == ("private-student", "private-password")
    bridge._credentials = None
    bridge.startMonitor("private-student", "", True)
    assert open_credentials(bridge._credentials)[1] == "private-password"
    bridge.forgetPassword()
    assert not bridge.vault.path.exists()
    assert not bridge.state["hasSavedPassword"]


def test_old_theme_defaults_migrate_to_dark_and_explicit_new_choice_persists(bridge):
    appearance = bridge.store.directory / "appearance.json"
    appearance.write_text(json.dumps({"dark": False}), encoding="utf-8")
    upgraded = DesktopBridge(bridge.store)
    try:
        assert upgraded.state["dark"]
        upgraded.toggleTheme()
    finally:
        upgraded.shutdown()
    restored = DesktopBridge(bridge.store)
    try:
        assert not restored.state["dark"]
    finally:
        restored.shutdown()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_spawn_transports_ciphertext_and_unchecked_remember_never_writes_cache(bridge):
    from zju_ac.desktop.credentials import open_credentials

    parent, child, process = Mock(), Mock(), Mock()
    context = Mock()
    context.Pipe.return_value = (parent, child)
    context.Process.return_value = process
    bridge.context = context
    bridge.startMonitor("private-student", "private-password", False)
    transferred = context.Process.call_args.kwargs["args"][1]
    assert isinstance(transferred, bytes)
    assert b"private-password" not in transferred
    assert open_credentials(transferred)[1] == "private-password"
    bridge.handle({"type": "connected"})
    assert not bridge.vault.path.exists()
