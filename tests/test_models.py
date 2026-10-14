from datetime import UTC, datetime, timedelta

import pytest

from zju_ac.errors import ProtocolError
from zju_ac.models import active_rollcalls, parse_time

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


def record(**changes):
    return {
        "rollcall_id": 42,
        "course_title": "测试课程",
        "title": "课堂签到",
        "rollcall_status": "in_progress",
        "status": "absent",
        "is_number": True,
        **changes,
    }


def test_active_absence_is_reminded():
    result = active_rollcalls({"rollcalls": [record()]}, NOW)
    assert result[0].id == "42"
    assert result[0].course == "测试课程"
    assert result[0].kind == "数字"


@pytest.mark.parametrize("status", ["on_call", "on_call_fine", "on_personal_leave"])
def test_completed_person_is_not_reminded(status):
    assert active_rollcalls({"rollcalls": [record(status=status)]}, NOW) == []


@pytest.mark.parametrize("status", ["finished", "expired", "closed"])
def test_finished_activity_is_not_reminded_even_without_end_time(status):
    assert active_rollcalls({"rollcalls": [record(rollcall_status=status)]}, NOW) == []


@pytest.mark.parametrize("delta", [-1, 0])
def test_deadline_passed(delta):
    end = (NOW + timedelta(seconds=delta)).isoformat()
    assert active_rollcalls({"rollcalls": [record(end_time=end)]}, NOW) == []


def test_server_expiry_flag():
    assert active_rollcalls({"rollcalls": [record(is_expired=True)]}, NOW) == []


def test_timezone_offset_compared_correctly():
    end = "2026-10-14T20:00:01+08:00"
    assert len(active_rollcalls({"rollcalls": [record(end_time=end)]}, NOW)) == 1


@pytest.mark.parametrize("value", [None, "", "garbage", "2026-10-14T20:00:00"])
def test_invalid_or_naive_time_is_not_guessed(value):
    assert parse_time(value) is None


@pytest.mark.parametrize("payload", [None, [], {}, {"rollcalls": {}}, {"rollcalls": [None]}])
def test_malformed_response_is_not_silently_treated_as_empty(payload):
    with pytest.raises(ProtocolError):
        active_rollcalls(payload, NOW)


@pytest.mark.parametrize("status", [None, "new_unknown_status"])
def test_unknown_status_fails_explicitly(status):
    with pytest.raises(ProtocolError):
        active_rollcalls({"rollcalls": [record(rollcall_status=status)]}, NOW)


@pytest.mark.parametrize("status", ["not_started", "waiting", "pending", "on_coming"])
def test_not_started_activity_is_not_reminded(status):
    assert active_rollcalls({"rollcalls": [record(rollcall_status=status)]}, NOW) == []


def test_duplicate_records_are_collapsed():
    assert len(active_rollcalls({"rollcalls": [record(), record()]}, NOW)) == 1


@pytest.mark.parametrize(
    "changes,kind",
    [
        ({"is_radar": True}, "GPS"),
        ({"is_number": False, "type": "qr_rollcall"}, "二维码"),
        ({"is_number": False}, "其他"),
    ],
)
def test_reminds_for_each_signin_type(changes, kind):
    assert active_rollcalls({"rollcalls": [record(**changes)]}, NOW)[0].kind == kind
