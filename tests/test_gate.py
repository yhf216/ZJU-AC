from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from zju_ac.client import CoursesClient
from zju_ac.config import GateSettings
from zju_ac.errors import AuthenticationExpired, PermissionDenied, ProtocolError, TemporaryError
from zju_ac.gate import WaitingActivity, evaluate_gate
from zju_ac.models import AttendanceProgress, Rollcall, attendance_progress

NOW = datetime(2026, 10, 15, 0, tzinfo=UTC)
RECORD = Rollcall("42", "测试课程", "签到", "数字", course_id="7")


def decide(signed=0, total=80, waited=0, remaining=None, policy=None):
    record = (
        replace(RECORD, ends_at=NOW + timedelta(seconds=remaining))
        if remaining is not None
        else RECORD
    )
    return evaluate_gate(
        WaitingActivity(record, 100),
        policy or GateSettings(),
        "attendance",
        AttendanceProgress(signed, total),
        100 + waited,
        NOW,
    )


@pytest.mark.parametrize(
    "signed,total,action",
    [
        (0, 80, "wait"),
        (20, 80, "wait"),
        (21, 80, "submit"),
        (20, 400, "wait"),
        (21, 400, "submit"),
        (10, 40, "wait"),
        (11, 40, "submit"),
    ],
)
def test_strict_ratio_or_count_threshold(signed, total, action):
    assert decide(signed, total).action == action


def test_custom_ratio_equal_boundary_does_not_round_into_success():
    policy = GateSettings(signed_ratio=0.58, signed_count=100)
    assert decide(29, 50, policy=policy).action == "wait"
    assert decide(30, 50, policy=policy).action == "submit"


@pytest.mark.parametrize("waited,action", [(119.999, "wait"), (120, "submit"), (121, "submit")])
def test_wait_timeout_is_measured_from_first_detection(waited, action):
    assert decide(waited=waited).action == action


@pytest.mark.parametrize(
    "remaining,action", [(31, "wait"), (30, "submit"), (1, "submit"), (0, "cancel"), (-1, "cancel")]
)
def test_deadline_fallback_never_submits_after_end(remaining, action):
    assert decide(remaining=remaining).action == action


def test_roster_end_time_supplies_deadline_when_aggregate_has_none():
    result = evaluate_gate(
        WaitingActivity(RECORD, 100),
        GateSettings(),
        "attendance",
        AttendanceProgress(0, 80, NOW + timedelta(seconds=20)),
        100,
        NOW,
    )
    assert result.action == "submit"
    assert "距结束" in result.reason


@pytest.mark.parametrize("progress", [None, AttendanceProgress(0, 0), AttendanceProgress(3, 2)])
def test_unavailable_or_invalid_roster_releases_gate(progress):
    result = evaluate_gate(
        WaitingActivity(RECORD, 100), GateSettings(), "attendance", progress, 100, NOW
    )
    assert result.action == "submit"
    assert "名单" in result.reason


def test_all_numeric_thresholds_can_be_customized():
    policy = GateSettings(
        signed_ratio=0.5,
        signed_count=3,
        max_wait_seconds=10,
        min_remaining_seconds=4,
        poll_interval_seconds=2,
    )
    assert decide(3, 100, policy=policy).action == "wait"
    assert decide(4, 100, policy=policy).action == "submit"
    assert decide(waited=10, policy=policy).action == "submit"
    assert decide(remaining=4, policy=policy).action == "submit"


def test_roster_counts_only_positive_rollcall_status_not_status_or_updated_at():
    payload = {
        "student_rollcalls": [
            {"rollcall_status": "on_call_fine", "status": "on_call"},
            {"rollcall_status": "absent", "status": "on_call_fine", "updated_at": "2026-10-15"},
            {"rollcall_status": "on_call", "status": "on_call", "updated_at": "2026-10-15"},
            {"rollcall_status": "on_personal_leave"},
        ],
        "end_time": "2026-10-15T08:01:00+08:00",
    }
    assert attendance_progress(payload) == AttendanceProgress(1, 4, NOW + timedelta(seconds=60))


def test_nested_roster_is_supported_and_only_counts_leave_the_parser():
    payload = {
        "data": {
            "student_rollcalls": [{"rollcall_status": "on_call_fine", "name": "private-name"}],
            "total": 1,
        }
    }
    result = attendance_progress(payload)
    assert result == AttendanceProgress(1, 1)
    assert "private-name" not in repr(result)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"student_rollcalls": []},
        {"student_rollcalls": {}},
        {"student_rollcalls": [None]},
        {"student_rollcalls": [{"status": "on_call_fine"}]},
        {"student_rollcalls": [{"rollcall_status": None}]},
        {"student_rollcalls": [{"rollcall_status": ""}]},
        {"student_rollcalls": [{"rollcall_status": "absent"}], "total": 80},
        {"student_rollcalls": [{"rollcall_status": "absent"}], "has_more": True},
        {"student_rollcalls": [{"rollcall_status": "absent"}], "pagination": {"next_page": 2}},
    ],
)
def test_missing_malformed_or_known_partial_roster_is_unavailable(payload):
    assert attendance_progress(payload) is None


@pytest.mark.parametrize(
    "failure", [PermissionDenied("denied"), ProtocolError("changed"), TemporaryError("offline")]
)
def test_roster_fetch_failures_return_unavailable_without_writes(failure):
    client = CoursesClient(Mock())
    client.get_json = Mock(side_effect=failure)
    assert client.attendance_progress(RECORD) is None
    client.session.put.assert_not_called()


def test_expired_session_is_not_treated_as_an_unavailable_roster():
    client = CoursesClient(Mock())
    client.get_json = Mock(side_effect=AuthenticationExpired("expired"))
    with pytest.raises(AuthenticationExpired):
        client.attendance_progress(RECORD)


def test_roster_client_reduces_response_without_retaining_or_logging_names(caplog):
    client = CoursesClient(Mock())
    client.get_json = Mock(
        return_value={
            "student_rollcalls": [{"rollcall_status": "on_call_fine", "name": "private-name"}]
        }
    )
    assert client.attendance_progress(RECORD) == AttendanceProgress(1, 1)
    client.get_json.assert_called_once_with("/api/rollcall/42/student_rollcalls")
    assert "private-name" not in caplog.text


def test_invalid_id_cannot_inject_roster_endpoint():
    client = CoursesClient(Mock())
    client.get_json = Mock()
    assert client.attendance_progress(replace(RECORD, id="../profile")) is None
    client.get_json.assert_not_called()
