from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from zju_ac.checkin import ConfirmedCheckin
from zju_ac.client import CoursesClient
from zju_ac.config import GateSettings, GpsSettings, Settings
from zju_ac.errors import AuthenticationExpired
from zju_ac.gps import Coordinates
from zju_ac.models import AttendanceProgress, Rollcall

NOW = datetime(2026, 10, 15, 0, tzinfo=UTC)
NUMBER = Rollcall("42", "测试课程", "数字签到", "数字", course_id="7")
GPS = Rollcall("43", "第二门课", "定位签到", "GPS", course_id="8")


@pytest.fixture
def workflow(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("zju_ac.checkin.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "zju_ac.checkin.datetime", Mock(now=lambda tz: NOW + timedelta(seconds=clock[0]))
    )
    client = Mock(spec=CoursesClient)
    client.attendance_progress.return_value = AttendanceProgress(0, 80)
    client.fresh_number.return_value = NUMBER
    client.fresh_gps.return_value = GPS
    client.my_rollcall_status.return_value = "absent"
    client.read_number_code.return_value = "0123"
    client.verify_attendance.return_value = True
    prompts = Mock()
    prompts.poll.return_value = []
    settings = Settings(gps=GpsSettings("test", "测试地点", Coordinates(30.3, 120.09)))
    checkin = ConfirmedCheckin(client, prompts, settings=settings)
    return client, prompts, checkin, clock


def test_wait_does_not_read_code_or_write_and_checks_only_at_configured_interval(workflow):
    client, prompts, checkin, clock = workflow
    client.attendance_progress.side_effect = [
        AttendanceProgress(0, 80),
        AttendanceProgress(20, 80),
        AttendanceProgress(21, 80),
    ]
    checkin.observe([NUMBER, NUMBER])
    checkin.process()
    client.read_number_code.assert_not_called()
    client.submit_number.assert_not_called()
    clock[0] = 4.999
    checkin.process()
    assert client.attendance_progress.call_count == 1
    clock[0] = 5
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_not_called()
    clock[0] = 10
    checkin.process()
    checkin.observe([NUMBER])
    checkin.process()
    assert client.attendance_progress.call_count == 3
    client.read_number_code.assert_called_once()
    client.submit_number.assert_called_once_with(NUMBER, "0123")
    prompts.ask.assert_not_called()


def test_timeout_preempts_long_roster_poll_interval(workflow):
    client, _, checkin, clock = workflow
    checkin.settings = replace(
        checkin.settings, gate_settings=GateSettings(poll_interval_seconds=500)
    )
    checkin.observe([NUMBER])
    checkin.process()
    clock[0] = 119.999
    checkin.process()
    client.submit_number.assert_not_called()
    clock[0] = 120
    checkin.process()
    assert client.attendance_progress.call_count == 1
    client.submit_number.assert_called_once()


def test_cached_roster_deadline_preempts_long_poll_interval(workflow):
    client, _, checkin, clock = workflow
    checkin.settings = replace(
        checkin.settings, gate_settings=GateSettings(poll_interval_seconds=500)
    )
    client.attendance_progress.return_value = AttendanceProgress(0, 80, NOW + timedelta(seconds=40))
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_not_called()
    clock[0] = 10
    checkin.process()
    assert client.attendance_progress.call_count == 1
    client.submit_number.assert_called_once()


def test_slow_roster_request_counts_toward_wait_timeout(workflow):
    client, _, checkin, clock = workflow

    def slow_read(record):
        clock[0] = 121
        return AttendanceProgress(0, 80)

    client.attendance_progress.side_effect = slow_read
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_called_once()


def test_one_waiting_course_does_not_block_another_ready_course(workflow):
    client, _, checkin, _ = workflow
    client.attendance_progress.side_effect = (
        lambda record: AttendanceProgress(0, 80)
        if record.id == NUMBER.id
        else AttendanceProgress(21, 400)
    )
    checkin.observe([NUMBER, GPS])
    checkin.process()
    client.submit_number.assert_not_called()
    client.submit_gps.assert_called_once()
    assert NUMBER.id in checkin.automatic
    assert GPS.id not in checkin.automatic


def test_first_detection_timer_is_not_reset_on_each_poll(workflow):
    client, _, checkin, clock = workflow
    checkin.observe([NUMBER])
    checkin.process()
    clock[0] = 119
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_not_called()
    clock[0] = 120
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_called_once()


def test_disappearing_activity_keeps_gate_and_eventually_attempts_submission(workflow):
    client, _, checkin, clock = workflow
    checkin.observe([NUMBER])
    checkin.process()
    checkin.observe([])
    clock[0] = 130
    checkin.process()
    assert not checkin.automatic
    client.submit_number.assert_called_once()


def test_activity_expiring_while_waiting_cancels_instead_of_using_fallback(workflow):
    client, _, checkin, clock = workflow
    checkin.settings = replace(
        checkin.settings, gate_settings=GateSettings(min_remaining_seconds=0)
    )
    checkin.observe([replace(NUMBER, ends_at=NOW + timedelta(seconds=2))])
    checkin.process()
    clock[0] = 2
    checkin.process()
    assert not checkin.automatic
    client.submit_number.assert_not_called()


def test_new_deadline_from_monitor_releases_gate_immediately(workflow):
    client, _, checkin, _ = workflow
    checkin.observe([NUMBER])
    checkin.process()
    checkin.observe([replace(NUMBER, ends_at=NOW + timedelta(seconds=29))])
    checkin.process()
    client.submit_number.assert_called_once()


@pytest.mark.parametrize("own_status", [None, "on_call", "on_call_fine", "on_personal_leave"])
def test_roster_unavailable_fallback_still_checks_own_status(workflow, own_status):
    client, _, checkin, _ = workflow
    client.attendance_progress.return_value = None
    client.my_rollcall_status.return_value = own_status
    checkin.observe([NUMBER])
    checkin.process()
    assert client.submit_number.call_count == (
        0 if own_status in {"on_call", "on_call_fine"} else 1
    )


def test_roster_and_fresh_activity_unavailable_still_attempts_submission(workflow):
    client, _, checkin, _ = workflow
    client.attendance_progress.return_value = None
    client.fresh_number.return_value = None
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_called_once()


def test_session_error_in_gate_does_not_cancel_submission_attempt(workflow):
    client, _, checkin, _ = workflow
    client.attendance_progress.side_effect = AuthenticationExpired("expired")
    checkin.observe([NUMBER])
    checkin.process()
    client.submit_number.assert_called_once()


def test_manual_confirmation_does_not_query_roster_or_wait_for_gate(workflow):
    from zju_ac.checkin import Answer

    client, prompts, checkin, _ = workflow
    checkin.settings = replace(checkin.settings, auto_checkin=False)
    checkin.observe([NUMBER])
    prompt = prompts.ask.call_args.args[0]
    prompts.poll.return_value = [Answer(prompt, "y")]
    checkin.process()
    client.attendance_progress.assert_not_called()
    client.submit_number.assert_called_once()


def test_close_cancels_gate_wait_and_prevents_deadline_submission(workflow):
    client, _, checkin, clock = workflow
    checkin.observe([NUMBER])
    checkin.process()
    checkin.close()
    clock[0] = 130
    checkin.process()
    client.submit_number.assert_not_called()


def test_monitor_continues_polling_and_notifies_other_courses_during_gate_wait(workflow):
    from zju_ac.monitor import run_monitor

    client, _, checkin, clock = workflow
    client.rollcalls.side_effect = [[NUMBER], [NUMBER, GPS], AuthenticationExpired("stop")]
    client.attendance_progress.side_effect = lambda record: (
        AttendanceProgress(0, 80) if record.id == NUMBER.id else AttendanceProgress(21, 400)
    )

    def advance(seconds):
        clock[0] += seconds

    checkin.wait = advance
    notifier = Mock()
    with pytest.raises(AuthenticationExpired):
        run_monitor(client, notifier, interval=15, checkin=checkin)
    assert client.rollcalls.call_count == 3
    assert [call.args[0] for call in notifier.send.call_args_list] == [NUMBER, GPS]
    client.submit_number.assert_not_called()
    client.submit_gps.assert_called_once()
