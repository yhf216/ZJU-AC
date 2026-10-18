import json
import os
import threading
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock

import pytest

from zju_ac.checkin import ConfirmedCheckin
from zju_ac.config import Settings
from zju_ac.desktop.credentials import (
    CredentialError,
    CredentialVault,
    SessionClock,
    open_credentials,
    seal_credentials,
)
from zju_ac.desktop.worker import DesktopPrompts, DesktopSession
from zju_ac.models import Rollcall
from zju_ac.monitor import run_monitor


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_dpapi_cache_roundtrip_is_local_ciphertext_and_not_exported(tmp_path, monkeypatch):
    from zju_ac.diagnostics import export_bundle

    forbidden = Mock(side_effect=AssertionError("Credential protection must not use networking"))
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    vault = CredentialVault(tmp_path)
    blob = seal_credentials("private-student", "private-password-中文")
    assert b"private-student" not in blob and b"private-password" not in blob
    vault.save_blob(blob)
    assert vault.load() == ("private-student", "private-password-中文")
    assert vault.path.read_bytes() == blob
    assert not list(tmp_path.glob("*.tmp"))
    from zipfile import ZipFile

    with ZipFile(export_bundle(tmp_path)) as package:
        assert "credentials.dpapi" not in package.namelist()
    forbidden.assert_not_called()
    vault.forget()
    assert vault.load() is None


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_corrupt_ciphertext_fails_without_plaintext_fallback(tmp_path):
    vault = CredentialVault(tmp_path)
    blob = bytearray(seal_credentials("private", "password"))
    blob[-1] ^= 0xFF
    vault.path.write_bytes(blob)
    with pytest.raises(CredentialError):
        vault.load()
    with pytest.raises(CredentialError):
        open_credentials(b'{"student":"plain","password":"plain"}')


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_worker_accepts_encrypted_ipc_credentials_without_network(tmp_path, monkeypatch):
    from zju_ac.desktop import worker

    client, connection = Mock(), Connection()
    client.rollcalls.return_value = []

    @contextmanager
    def login(student, password, timeout, **kwargs):
        assert (student, password) == ("private-student", "private-password")
        yield client

    monkeypatch.setattr(worker, "login", login)
    monkeypatch.setattr(worker, "setup", lambda *args: None)
    with pytest.raises(SystemExit) as result:
        worker.worker_entry(
            Settings(mode="once"),
            seal_credentials("private-student", "private-password"),
            connection,
            threading.Event(),
            str(tmp_path),
            threading.Event(),
        )
    assert result.value.code == 0
    assert "private-password" not in json.dumps(connection.sent)
    client.submit_number.assert_not_called()


def test_session_clock_starts_at_authentication_and_freezes_after_logout():
    now = [0.0]
    clock = SessionClock(lambda: now[0])
    now[0] = 20
    assert clock.text == "00:00:00"
    now[0] = 0
    clock.start()  # Monotonic zero is a valid start value.
    now[0] = 3661
    assert clock.text == "01:01:01"
    clock.stop()
    now[0] = 7000
    assert clock.text == "01:01:01"
    clock.reset()
    assert clock.text == "00:00:00"


class Connection:
    def __init__(self):
        self.messages, self.sent = [], []

    def send(self, value):
        self.sent.append(value)

    def poll(self):
        return bool(self.messages)

    def recv(self):
        return self.messages.pop(0)

    def close(self):
        pass


def make_session():
    connection = Connection()
    stop, pause = threading.Event(), threading.Event()
    prompts = DesktopPrompts(connection, stop)
    notifier = Mock()
    control = DesktopSession(Settings(interval=5), prompts, notifier, stop, pause, connection.send)
    return control, connection, stop, pause


def test_paused_session_performs_no_poll_and_reuses_client_on_resume():
    control, connection, stop, pause = make_session()
    client, controller = Mock(), Mock()
    controller.pending = {}
    polled = threading.Event()
    pause.set()

    def poll():
        polled.set()
        stop.set()
        return []

    client.rollcalls.side_effect = poll
    thread = threading.Thread(
        target=run_monitor,
        args=(client, Mock()),
        kwargs={
            "checkin": controller,
            "stop_event": stop,
            "session_control": control,
        },
    )
    thread.start()
    try:
        assert not polled.wait(0.15)
        client.rollcalls.assert_not_called()
        pause.clear()
        assert polled.wait(1)
    finally:
        stop.set()
        thread.join(2)
    assert not thread.is_alive()
    client.rollcalls.assert_called_once()
    assert {event["type"] for event in connection.sent} >= {"paused", "resumed"}


def test_settings_sent_before_resume_are_applied_even_if_pause_flag_already_cleared():
    control, connection, _, _ = make_session()
    control.was_paused = True
    replacement = replace(control.settings, auto_checkin=False, interval=60)
    connection.messages.append({"type": "settings", "settings": replacement})
    controller = Mock()
    assert control.before_poll(controller)
    assert control.settings == replacement
    assert controller.settings == replacement


def test_pause_during_code_read_prevents_put_and_allows_fresh_resume():
    pause, stop = threading.Event(), threading.Event()
    activity = Rollcall("42", "课程", "签到", "数字", course_id="7")
    client, prompts = Mock(), Mock()
    prompts.poll.return_value = []
    client.fresh_number.return_value = activity
    client.my_rollcall_status.return_value = "absent"

    def read(record):
        pause.set()
        return "0123"

    client.read_number_code.side_effect = read
    checkin = ConfirmedCheckin(
        client, prompts, settings=Settings(gate="immediate"), stop_event=stop, pause_event=pause
    )
    checkin.observe([activity])
    checkin.process()
    client.submit_number.assert_not_called()
    assert activity.id not in checkin.asked
    pause.clear()
    client.read_number_code.side_effect = None
    client.read_number_code.return_value = "4567"
    client.verify_attendance.return_value = True
    checkin.observe([activity])
    checkin.process()
    client.submit_number.assert_called_once_with(activity, "4567")


def test_pause_cancels_queued_manual_consent_and_requires_new_confirmation():
    from zju_ac.checkin import Prompt

    control, connection, _, _ = make_session()
    activity = Rollcall("42", "课程", "签到", "数字", course_id="7")
    prompts = control.prompts
    checkin = ConfirmedCheckin(Mock(), prompts, settings=Settings(auto_checkin=False))
    checkin.observe([activity])
    token = next(iter(prompts.pending))
    connection.messages.append({"type": "answer", "token": token, "value": "y"})
    prompts.pump()
    checkin.cancel_pending_prompts()
    prompts.cancel_pending()
    assert prompts.poll() == []
    checkin.observe([activity])
    assert checkin.pending[activity.id] == Prompt(activity)
    assert next(iter(prompts.pending)) != token
