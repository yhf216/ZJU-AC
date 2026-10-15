from datetime import datetime
from unittest.mock import Mock

import pytest
import requests

from zju_ac.client import BASE_URL, CoursesClient, number_code
from zju_ac.errors import AuthenticationExpired, CheckinRejected, ProtocolError, SubmissionUncertain
from zju_ac.models import Rollcall

RECORD = Rollcall(
    "42",
    "测试课程",
    "签到",
    "数字",
    course_id="7",
    started_at=datetime.fromisoformat("2026-10-15T00:30:00+08:00"),
)


def json_response(payload, status=200):
    response = Mock(status_code=status, headers={"content-type": "application/json"})
    response.json.return_value = payload
    return response


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0000", "0000"),
        (0, "0000"),
        (123, "0123"),
        ("123456", "123456"),
        (True, None),
        ("１２３４", None),
        ("1", None),
        (None, None),
    ],
)
def test_code_validation_preserves_zeroes(value, expected):
    assert number_code(value) == expected


def test_detail_code_channel():
    session = Mock()
    session.get.return_value = json_response({"number_code": "0000"})
    assert CoursesClient(session).read_number_code(RECORD) == "0000"
    assert session.get.call_args.args == (BASE_URL + "/api/rollcall/42/student_rollcalls",)


def test_timetable_channel_uses_utc_date_and_matching_activity():
    session = Mock()
    session.get.side_effect = [
        json_response({"number_code": None}),
        json_response(
            {"rollcalls": [{"id": 41, "number_code": "9999"}, {"id": 42, "number_code": "0123"}]}
        ),
    ]
    assert CoursesClient(session).read_number_code(RECORD) == "0123"
    assert session.get.call_args.kwargs["params"] == {
        "course_ids": "7",
        "rollcall_date": "2026-10-14",
    }


def test_forbidden_code_endpoints_allow_manual_fallback():
    session = Mock()
    session.get.return_value = json_response({}, status=403)
    assert CoursesClient(session).read_number_code(RECORD) is None


def test_no_guessed_date_when_timestamp_unavailable():
    session = Mock()
    session.get.return_value = json_response({"number_code": None})
    record = Rollcall("42", "课程", "签到", "数字", course_id="7")
    assert CoursesClient(session).read_number_code(record) is None
    session.get.assert_called_once()


def test_codes_are_not_cached_across_queries():
    session = Mock()
    session.get.side_effect = [
        json_response({"number_code": "0123"}),
        json_response({"number_code": "4567"}),
    ]
    client = CoursesClient(session)
    assert client.read_number_code(RECORD) == "0123"
    assert client.read_number_code(RECORD) == "4567"


def test_submit_payload_and_single_attempt():
    session = Mock()
    response = json_response({"status": "on_call"})
    session.put.return_value = response
    client = CoursesClient(session)
    client.submit_number(RECORD, "0123")
    session.put.assert_called_once_with(
        BASE_URL + "/api/rollcall/42/answer_number_rollcall",
        json={"deviceId": client.device_id, "numberCode": "0123"},
        timeout=15,
        allow_redirects=False,
        headers={"Accept": "application/json"},
    )
    response.close.assert_called_once()


@pytest.mark.parametrize(
    "payload,status",
    [({"success": False}, 200), ({"error_code": "wrong_number_code"}, 200), ({}, 400)],
)
def test_explicit_submission_failures_are_not_success(payload, status):
    session = Mock()
    session.put.return_value = json_response(payload, status)
    with pytest.raises(CheckinRejected):
        CoursesClient(session).submit_number(RECORD, "0123")
    session.put.assert_called_once()


def test_write_timeout_is_uncertain_and_never_retried():
    session = Mock()
    session.put.side_effect = requests.Timeout("private-response")
    with pytest.raises(SubmissionUncertain) as error:
        CoursesClient(session).submit_number(RECORD, "0123")
    assert "private-response" not in str(error.value)
    session.put.assert_called_once()


def test_server_error_after_write_is_uncertain():
    session = Mock()
    session.put.return_value = json_response({}, 500)
    with pytest.raises(SubmissionUncertain):
        CoursesClient(session).submit_number(RECORD, "0123")


@pytest.mark.parametrize("rid", ["../profile", "42/answer", "42?x=1"])
def test_activity_id_cannot_inject_an_endpoint(rid):
    session = Mock()
    with pytest.raises(ProtocolError):
        CoursesClient(session).submit_number(
            Rollcall(rid, "课程", "签到", "数字", course_id="7"),
            "0123",
        )
    session.put.assert_not_called()


def test_verification_reads_only_own_records_with_pagination():
    session = Mock()
    session.get.side_effect = [
        json_response({"id": 99}),
        json_response({"rollcalls": [{"id": i, "status": "absent"} for i in range(100, 200)]}),
        json_response({"rollcalls": [{"id": 42, "status": "on_call_fine"}]}),
    ]
    assert CoursesClient(session).verify_attendance(RECORD)
    assert session.get.call_args.args == (BASE_URL + "/api/course/7/student/99/rollcalls",)
    assert session.get.call_args.kwargs["params"] == {"page": 2, "page_size": 100}
    session.put.assert_not_called()


def test_verification_waits_for_own_status_not_activity_status(monkeypatch):
    client = CoursesClient(Mock())
    client.my_rollcall_status = Mock(side_effect=["absent", "absent", "on_call"])
    monkeypatch.setattr("zju_ac.client.time.sleep", Mock())
    assert client.verify_attendance(RECORD)
    assert client.my_rollcall_status.call_count == 3


def test_absence_from_active_list_does_not_count_as_success(monkeypatch):
    client = CoursesClient(Mock())
    client.my_rollcall_status = Mock(return_value=None)
    monkeypatch.setattr("zju_ac.client.time.sleep", Mock())
    assert not client.verify_attendance(RECORD)


def test_freshness_check_rejects_type_or_course_changes():
    client = CoursesClient(Mock())
    client.rollcalls = Mock(return_value=[Rollcall("42", "课程", "签到", "GPS", course_id="7")])
    assert client.fresh_number(RECORD) is None


@pytest.mark.parametrize(
    "failure", [requests.Timeout("offline"), requests.ConnectionError("offline")]
)
def test_detail_network_failure_falls_back_to_timetable(failure):
    session = Mock()
    session.get.side_effect = [
        failure,
        json_response(
            {
                "rollcalls": [{"id": 42, "number_code": "0123"}],
            }
        ),
    ]
    assert CoursesClient(session).read_number_code(RECORD) == "0123"
    assert session.get.call_count == 2
    assert session.get.call_args.args == (BASE_URL + "/api/timetable_rollcalls",)


def test_detail_server_error_falls_back_to_timetable():
    session = Mock()
    session.get.side_effect = [
        json_response({}, 500),
        json_response(
            {
                "rollcalls": [{"id": 42, "number_code": "0123"}],
            }
        ),
    ]
    assert CoursesClient(session).read_number_code(RECORD) == "0123"


def test_both_channels_temporarily_unavailable_allow_manual_input():
    session = Mock()
    session.get.side_effect = [
        requests.Timeout("private-ticket"),
        requests.Timeout("private-ticket"),
    ]
    assert CoursesClient(session).read_number_code(RECORD) is None
    assert session.get.call_count == 2
    session.put.assert_not_called()


def test_expired_session_does_not_fall_back_or_prompt_for_code():
    session = Mock()
    session.get.return_value = json_response({}, 401)
    with pytest.raises(AuthenticationExpired):
        CoursesClient(session).read_number_code(RECORD)
    session.get.assert_called_once()


def test_missing_detail_code_falls_back_but_wrong_activity_never_supplies_code():
    session = Mock()
    session.get.side_effect = [
        json_response({"number_code": None}),
        json_response(
            {
                "rollcalls": [{"id": 41, "number_code": "0123"}],
            }
        ),
    ]
    assert CoursesClient(session).read_number_code(RECORD) is None


def test_channel_logging_never_prints_the_code(caplog):
    session = Mock()
    session.get.return_value = json_response({"number_code": "0123"})
    with caplog.at_level("INFO", logger="zju_ac.client"):
        assert CoursesClient(session).read_number_code(RECORD) == "0123"
    assert "点名详情通道" in caplog.text
    assert "0123" not in caplog.text
