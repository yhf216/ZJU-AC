import json
import threading
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from zju_ac.checkin import ConfirmedCheckin
from zju_ac.config import CONFIG_PATH, Settings
from zju_ac.desktop import worker
from zju_ac.desktop.storage import ConfigStore
from zju_ac.errors import ZjuError
from zju_ac.models import Rollcall
from zju_ac.monitor import run_monitor


def test_desktop_config_roundtrip_and_manual_selection(tmp_path):
    store = ConfigStore(tmp_path, CONFIG_PATH)
    store.save({"auto": False, "location": "YQ4", "attempts": 3, "retryInterval": 60})
    loaded = ConfigStore(tmp_path)
    assert not loaded.settings.auto_checkin
    assert loaded.settings.gps.location == "YQ4"
    assert loaded.settings.code_retry.max_attempts == 3
    assert loaded.settings.code_retry.interval_seconds == 60
    assert loaded.values == store.values
    assert len(loaded.locations) >= 13


@pytest.mark.parametrize(
    "updates",
    [{"attempts": 6}, {"retryInterval": 10}, {"password": "private"}, {"location": "missing"}],
)
def test_invalid_desktop_settings_never_replace_valid_file(tmp_path, updates):
    store = ConfigStore(tmp_path, CONFIG_PATH)
    original = store.path.read_bytes()
    with pytest.raises(ZjuError):
        store.save(updates)
    assert store.path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_custom_location_is_explicit_and_preserves_reference_locations(tmp_path):
    store = ConfigStore(tmp_path, CONFIG_PATH)
    references = store.data["gps"]["locations"].copy()
    store.save_location("自己的地点", 30.3, 120.08)
    assert store.settings.gps.location == "custom"
    assert store.settings.gps.name == "自己的地点"
    assert all(store.data["gps"]["locations"][key] == value for key, value in references.items())
    with pytest.raises(ZjuError):
        store.save_location("无效", 91, 120)
    assert ConfigStore(tmp_path).settings.gps.name == "自己的地点"


def test_preexisting_desktop_config_is_not_overwritten_by_source(tmp_path):
    store = ConfigStore(tmp_path, CONFIG_PATH)
    store.save({"location": "YQ7", "auto": False})
    assert ConfigStore(tmp_path, CONFIG_PATH).settings == store.settings


def test_stop_during_poll_prevents_notifications_and_submission():
    stop, client, notifier, checkin = threading.Event(), Mock(), Mock(), Mock()

    def poll():
        stop.set()
        return [Rollcall("1", "课程", "签到", "数字")]

    client.rollcalls.side_effect = poll
    run_monitor(client, notifier, checkin=checkin, stop_event=stop)
    notifier.send.assert_not_called()
    checkin.observe.assert_not_called()
    checkin.process.assert_not_called()


def test_stop_during_code_lookup_never_sends_put():
    stop, client = threading.Event(), Mock()
    activity = Rollcall("42", "课程", "签到", "数字", course_id="7")
    client.fresh_number.return_value = activity
    client.my_rollcall_status.return_value = "absent"

    def lookup(record):
        stop.set()
        return "0123"

    client.read_number_code.side_effect = lookup
    prompts = Mock()
    prompts.poll.return_value = []
    controller = ConfirmedCheckin(
        client, prompts, settings=Settings(gate="immediate"), stop_event=stop
    )
    controller.observe([activity])
    controller.process()
    client.submit_number.assert_not_called()


class FakeConnection:
    def __init__(self):
        self.events, self.answers = [], []

    def send(self, message):
        self.events.append(message)
        if message["type"] in {"prompt", "otp"}:
            value = (
                "654321"
                if message["type"] == "otp"
                else "0123"
                if message["stage"] == "code"
                else "y"
            )
            self.answers.append({"type": "answer", "token": message["token"], "value": value})

    def poll(self):
        return bool(self.answers)

    def recv(self):
        return self.answers.pop(0)

    def close(self):
        pass


def test_desktop_worker_handles_otp_consent_and_manual_code_without_console(tmp_path, monkeypatch):
    client, connection = Mock(), FakeConnection()
    activity = Rollcall("42", "课程", "签到", "数字", course_id="7")
    client.fresh_number.return_value = activity
    client.my_rollcall_status.return_value = "absent"
    client.read_number_code.return_value = None
    client.verify_attendance.return_value = True

    @contextmanager
    def fake_login(student, password, timeout, *, otp_reader):
        assert (student, password) == ("private-student", "private-password")
        assert otp_reader("challenge") == "654321"
        yield client

    def fake_monitor(client, notifier, *args, checkin, stop_event, on_poll, on_failure):
        on_poll([activity])
        checkin.observe([activity])
        checkin.process()
        checkin.process()

    monkeypatch.setattr(worker, "login", fake_login)
    monkeypatch.setattr(worker, "run_monitor", fake_monitor)
    monkeypatch.setattr(worker, "setup", lambda *args: None)
    with pytest.raises(SystemExit) as result:
        worker.worker_entry(
            Settings(auto_checkin=False),
            ("private-student", "private-password"),
            connection,
            threading.Event(),
            str(tmp_path),
        )
    assert result.value.code == 0
    client.submit_number.assert_called_once_with(activity, "0123")
    kinds = [event["type"] for event in connection.events]
    assert "otp" in kinds and kinds.count("prompt") == 2
    assert any(event.get("outcome") == "success" for event in connection.events)
    payload = json.dumps(connection.events)
    for secret in ("private-student", "private-password", "654321", "0123"):
        assert secret not in payload


def test_desktop_demo_never_authenticates_or_reads_credentials(tmp_path, monkeypatch):
    login = Mock(side_effect=AssertionError("No login for demo"))
    monkeypatch.setattr(worker, "login", login)
    monkeypatch.setattr(worker, "setup", lambda *args: None)
    connection = FakeConnection()
    worker.worker_entry(
        Settings(mode="demo"), ("unused", "unused"), connection, threading.Event(), str(tmp_path)
    )
    login.assert_not_called()
    assert [event["outcome"] for event in connection.events] == [
        "new",
        "success",
        "failure",
        "pending",
    ]
