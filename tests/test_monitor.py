from unittest.mock import Mock

import pytest

from zju_ac.errors import AuthenticationExpired, TemporaryError
from zju_ac.models import Rollcall
from zju_ac.monitor import ReminderTracker, run_monitor

RECORD = Rollcall("1", "测试课程", "签到", "数字")


def test_default_reminder_deduplication():
    tracker = ReminderTracker()
    assert tracker.due(RECORD, 10)
    tracker.mark(RECORD, 10)
    assert not tracker.due(RECORD, 10000)
    assert tracker.due(Rollcall("2", "测试课程", "第二次签到", "数字"), 20)


def test_repeat_reminder_boundary():
    tracker = ReminderTracker(60)
    tracker.mark(RECORD, 10)
    assert not tracker.due(RECORD, 69)
    assert tracker.due(RECORD, 70)


def test_monitor_notifies_current_records_and_exits_once():
    client, notifier = Mock(), Mock()
    client.rollcalls.return_value = [RECORD]
    run_monitor(client, notifier, once=True)
    notifier.send.assert_called_once_with(RECORD)


def test_once_does_not_hide_network_failure():
    client = Mock()
    client.rollcalls.side_effect = TemporaryError("offline")
    with pytest.raises(TemporaryError):
        run_monitor(client, Mock(), once=True)


def test_auth_expiry_stops_instead_of_retrying_credentials():
    client = Mock()
    client.rollcalls.side_effect = AuthenticationExpired("expired")
    with pytest.raises(AuthenticationExpired):
        run_monitor(client, Mock())
    client.rollcalls.assert_called_once()


def test_transient_failures_back_off_then_recover(monkeypatch):
    client, notifier = Mock(), Mock()
    client.rollcalls.side_effect = [
        TemporaryError("offline"),
        TemporaryError("offline"),
        [RECORD],
        AuthenticationExpired("stop"),
    ]
    sleep = Mock()
    monkeypatch.setattr("zju_ac.monitor.time.sleep", sleep)
    with pytest.raises(AuthenticationExpired):
        run_monitor(client, notifier, interval=15)
    assert sleep.call_args_list[0].args == (30,)
    assert sleep.call_args_list[1].args == (60,)
    notifier.send.assert_called_once_with(RECORD)


def test_numeric_confirmation_is_processed_without_preventing_next_poll():
    client, notifier, checkin = Mock(), Mock(), Mock()
    client.rollcalls.side_effect = [[RECORD], AuthenticationExpired("stop")]
    with pytest.raises(AuthenticationExpired):
        run_monitor(client, notifier, checkin=checkin)
    notifier.send.assert_called_once_with(RECORD)
    checkin.observe.assert_called_once_with([RECORD])
    checkin.process.assert_called_once()
    checkin.wait.assert_called_once()
    assert client.rollcalls.call_count == 2


def test_once_is_read_only_even_if_confirmation_handler_supplied():
    client, notifier, checkin = Mock(), Mock(), Mock()
    client.rollcalls.return_value = [RECORD]
    run_monitor(client, notifier, once=True, checkin=checkin)
    checkin.observe.assert_not_called()
    checkin.process.assert_not_called()
    checkin.wait.assert_not_called()
