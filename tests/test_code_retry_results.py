from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from zju_ac.checkin import ConfirmedCheckin
from zju_ac.client import CoursesClient
from zju_ac.config import CodeRetrySettings, GpsSettings, Settings, load_config
from zju_ac.errors import (
    AuthenticationExpired,
    CheckinRejected,
    SubmissionUncertain,
    TemporaryError,
)
from zju_ac.gps import Coordinates
from zju_ac.models import Rollcall

NOW = datetime(2026, 10, 18, 0, tzinfo=UTC)
RECORD = Rollcall("42", "课程", "数字签到", "数字", course_id="7")


@pytest.fixture
def workflow(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("zju_ac.checkin.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "zju_ac.checkin.datetime", Mock(now=lambda tz: NOW + timedelta(seconds=clock[0]))
    )
    client = Mock(spec=CoursesClient)
    client.fresh_number.return_value = RECORD
    client.my_rollcall_status.return_value = "absent"
    client.read_number_code.return_value = None
    client.verify_attendance.return_value = True
    prompts, notifier = Mock(), Mock()
    prompts.poll.return_value = []
    controller = ConfirmedCheckin(
        client, prompts, settings=Settings(gate="immediate"), notifier=notifier
    )
    controller.observe([RECORD])
    return controller, client, notifier, clock


def test_missing_code_reads_at_most_five_times_with_no_early_reads(workflow):
    checkin, client, notifier, clock = workflow
    for attempt in range(5):
        clock[0] = attempt * 30
        checkin.observe([RECORD])
        checkin.process()
        assert client.read_number_code.call_count == attempt + 1
        clock[0] += 29.999
        checkin.process()
        assert client.read_number_code.call_count == attempt + 1
    clock[0] = 10000
    checkin.observe([RECORD])
    checkin.process()
    assert client.read_number_code.call_count == 5
    assert not checkin.code_retries
    client.submit_number.assert_not_called()
    notifier.result.assert_called_once_with(RECORD, "failure")


def test_interval_starts_after_request_completion_and_never_catches_up(workflow):
    checkin, client, _, clock = workflow

    def slow_read(record):
        clock[0] += 10
        return None

    client.read_number_code.side_effect = slow_read
    checkin.process()
    clock[0] = 39.999
    checkin.process()
    assert client.read_number_code.call_count == 1
    clock[0] = 1000  # A late scheduler tick performs one read, not all missed intervals.
    checkin.process()
    assert client.read_number_code.call_count == 2
    assert checkin.code_retries[RECORD.id].next_read_at == 1040


def test_valid_code_on_later_read_submits_once_and_notifies_success(workflow):
    checkin, client, notifier, clock = workflow
    client.read_number_code.side_effect = [None, "0000"]
    checkin.process()
    clock[0] = 30
    checkin.process()
    clock[0] = 500
    checkin.observe([RECORD])
    checkin.process()
    client.submit_number.assert_called_once_with(RECORD, "0000")
    notifier.result.assert_called_once_with(RECORD, "success")
    assert not checkin.code_retries


@pytest.mark.parametrize("error", [CheckinRejected("wrong"), SubmissionUncertain("timeout")])
def test_write_errors_never_schedule_reads_or_repeat_submission(workflow, error):
    checkin, client, notifier, clock = workflow
    client.read_number_code.return_value = "0123"
    client.submit_number.side_effect = error
    client.verify_attendance.return_value = False
    checkin.process()
    clock[0] = 600
    checkin.observe([RECORD])
    checkin.process()
    client.submit_number.assert_called_once()
    client.read_number_code.assert_called_once()
    notifier.result.assert_called_once_with(
        RECORD, "pending" if isinstance(error, SubmissionUncertain) else "failure"
    )


@pytest.mark.parametrize("change", [None, "course", "kind", "expired", "close"])
def test_cancelled_retry_does_not_read_again(workflow, change):
    checkin, client, _, clock = workflow
    checkin.process()
    if change is None:
        checkin.observe([])
    elif change == "course":
        checkin.observe([replace(RECORD, course_id="8")])
    elif change == "kind":
        checkin.observe([replace(RECORD, kind="GPS")])
    elif change == "expired":
        checkin.observe([replace(RECORD, ends_at=NOW + timedelta(seconds=20))])
    else:
        checkin.close()
    clock[0] = 30
    checkin.process()
    client.read_number_code.assert_called_once()
    client.submit_number.assert_not_called()


def test_deadline_does_not_accelerate_retry(workflow):
    checkin, client, _, clock = workflow
    client.fresh_number.return_value = replace(RECORD, ends_at=NOW + timedelta(seconds=20))
    checkin.process()
    clock[0] = 19
    checkin.process()
    client.read_number_code.assert_called_once()
    clock[0] = 20
    checkin.process()
    assert not checkin.code_retries
    client.submit_number.assert_not_called()


def test_external_success_between_reads_prevents_write_and_notifies(workflow):
    checkin, client, notifier, clock = workflow
    checkin.process()
    client.my_rollcall_status.return_value = "on_call_fine"
    clock[0] = 30
    checkin.process()
    client.read_number_code.assert_called_once()
    client.submit_number.assert_not_called()
    notifier.result.assert_called_once_with(RECORD, "success")


def test_other_activity_proceeds_while_code_retry_waits(workflow):
    checkin, client, _, _ = workflow
    other = replace(RECORD, id="43", course_id="8")
    client.fresh_number.side_effect = lambda record: record
    client.read_number_code.side_effect = lambda record: None if record.id == "42" else "0123"
    checkin.observe([RECORD, other])
    checkin.process()
    client.submit_number.assert_called_once_with(other, "0123")
    assert set(checkin.code_retries) == {"42"}


def test_roster_deadline_survives_missing_code_and_new_poll_without_deadline(workflow):
    from zju_ac.models import AttendanceProgress

    checkin, client, _, clock = workflow
    checkin.settings = replace(checkin.settings, gate="attendance")
    client.attendance_progress.return_value = AttendanceProgress(
        21, 80, NOW + timedelta(seconds=20)
    )
    checkin.process()
    checkin.observe([RECORD])
    clock[0] = 20
    checkin.process()
    assert not checkin.code_retries
    client.read_number_code.assert_called_once()


def test_slow_code_read_crossing_deadline_does_not_submit(workflow):
    checkin, client, _, clock = workflow
    client.fresh_number.return_value = replace(RECORD, ends_at=NOW + timedelta(seconds=20))

    def read(record):
        clock[0] = 21
        return "0123"

    client.read_number_code.side_effect = read
    checkin.process()
    client.submit_number.assert_not_called()


@pytest.mark.parametrize("failure", [TemporaryError("secret"), AuthenticationExpired("secret")])
def test_verification_error_notifies_pending_once(workflow, failure):
    checkin, client, notifier, _ = workflow
    client.read_number_code.return_value = "0123"
    client.verify_attendance.side_effect = failure
    if isinstance(failure, AuthenticationExpired):
        with pytest.raises(AuthenticationExpired):
            checkin.process()
    else:
        checkin.process()
    notifier.result.assert_called_once_with(RECORD, "pending")
    client.submit_number.assert_called_once()


def test_configurable_lower_read_budget(workflow):
    checkin, client, notifier, clock = workflow
    checkin.settings = replace(checkin.settings, code_retry=CodeRetrySettings(1, 60))
    checkin.process()
    clock[0] = 1000
    checkin.process()
    client.read_number_code.assert_called_once()
    notifier.result.assert_called_once_with(RECORD, "failure")


@pytest.mark.parametrize(
    "entry",
    [
        "max_attempts = 6",
        "max_attempts = 0",
        "max_attempts = true",
        "interval_seconds = 29",
        "interval_seconds = 0",
        "interval_seconds = true",
        "unknown = 1",
    ],
)
def test_unsafe_read_settings_rejected(tmp_path, entry):
    from zju_ac.errors import ZjuError

    path = tmp_path / "config.toml"
    path.write_text("[checkin.code_retry]\n" + entry, encoding="utf-8")
    with pytest.raises(ZjuError):
        load_config(path)


def test_read_settings_load(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[checkin.code_retry]\nmax_attempts = 3\ninterval_seconds = 60", encoding="utf-8"
    )
    assert load_config(path).code_retry == CodeRetrySettings(3, 60)


@pytest.mark.parametrize("outcome", ["success", "failure", "pending"])
def test_gps_uses_manually_selected_location_and_reports_outcome(workflow, outcome):
    checkin, client, notifier, _ = workflow
    gps = replace(RECORD, kind="GPS")
    selected = GpsSettings("chosen", "手动地点", Coordinates(30.3, 120.09))
    checkin.settings = replace(checkin.settings, gps=selected)
    checkin.automatic.clear()
    checkin.asked.clear()
    checkin.observe([gps])
    client.fresh_gps.return_value = gps
    if outcome == "failure":
        client.submit_gps.side_effect = CheckinRejected("out of scope")
    client.verify_attendance.return_value = outcome == "success"
    checkin.process()
    client.submit_gps.assert_called_once_with(gps, selected.coordinates, accuracy=35.0)
    client.read_number_code.assert_not_called()
    notifier.result.assert_called_once_with(gps, outcome)
