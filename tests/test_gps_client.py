from unittest.mock import Mock

import pytest
import requests

from zju_ac.checkin import Answer, ConfirmedCheckin, Prompt
from zju_ac.client import BASE_URL, CoursesClient
from zju_ac.config import GpsSettings, Settings
from zju_ac.errors import (
    AuthenticationExpired,
    CheckinRejected,
    PermissionDenied,
    ProtocolError,
    SubmissionUncertain,
)
from zju_ac.gps import Coordinates
from zju_ac.models import Rollcall

RECORD = Rollcall("42", "测试课程", "签到", "GPS", course_id="7")
LOCATION = Coordinates(30.30, 120.09)


def gps_client(payload, status=200):
    response = Mock(status_code=status, headers={"content-type": "application/json"})
    response.json.return_value = payload
    session = Mock()
    session.put.return_value = response
    return CoursesClient(session), session, response


def test_gps_payload_uses_stable_device_without_redirect_or_proxy():
    client, session, response = gps_client({"status": "on_call_fine"})
    assert client.submit_gps(RECORD, LOCATION) is None
    session.put.assert_called_once_with(
        BASE_URL + "/api/rollcall/42/answer",
        params={"api_version": "1.1.2"},
        json={
            "deviceId": client.device_id,
            "latitude": 30.30,
            "longitude": 120.09,
            "accuracy": 35,
            "altitude": None,
            "altitudeAccuracy": None,
            "heading": None,
            "speed": None,
        },
        timeout=15,
        allow_redirects=False,
        headers={"Accept": "application/json"},
    )
    assert session.trust_env is False
    session.proxies.clear.assert_called_once()
    response.close.assert_called_once()


@pytest.mark.parametrize("status", [200, 400])
@pytest.mark.parametrize("distance", [None, 123.5])
def test_outside_scope_rejection_stops_with_or_without_distance(status, distance):
    payload = {"error_code": "radar_out_of_scope"}
    if distance is not None:
        payload["distance"] = distance
    client, _, response = gps_client(payload, status)
    with pytest.raises(CheckinRejected, match="config.toml"):
        client.submit_gps(RECORD, LOCATION)
    response.close.assert_called_once()


@pytest.mark.parametrize("code", ["device_not_allowed", "wrong_rollcall_type", "unknown_error"])
def test_other_rejections_cannot_supply_distance_or_allow_another_position(code):
    client, _, _ = gps_client({"error_code": code, "distance": 123}, 400)
    with pytest.raises(CheckinRejected):
        client.submit_gps(RECORD, LOCATION)


@pytest.mark.parametrize("payload", [{}, {"distance": 123}, {"status": "on_call_fine"}])
def test_http_200_without_rejection_requires_own_status_verification(payload):
    client, _, _ = gps_client(payload)
    assert client.submit_gps(RECORD, LOCATION) is None


@pytest.mark.parametrize("value", [None, "123", True, 0, -1, float("nan"), float("inf")])
def test_invalid_distance_does_not_allow_another_position(value):
    client, _, _ = gps_client({"error_code": "radar_out_of_scope", "distance": value}, 400)
    with pytest.raises(CheckinRejected):
        client.submit_gps(RECORD, LOCATION)


@pytest.mark.parametrize(
    "payload",
    [
        {"error_code": "radar_out_of_scope"},
        {"error_code": "radar_out_of_scope", "distance": 100, "data": {"distance": 200}},
    ],
)
def test_missing_or_ambiguous_distances_stop(payload):
    client, _, _ = gps_client(payload, 400)
    with pytest.raises(CheckinRejected):
        client.submit_gps(RECORD, LOCATION)


@pytest.mark.parametrize(
    "status,error",
    [
        (401, AuthenticationExpired),
        (403, PermissionDenied),
        (500, SubmissionUncertain),
        (429, SubmissionUncertain),
    ],
)
def test_http_failures_do_not_become_distance_samples(status, error):
    client, _, response = gps_client({"error_code": "radar_out_of_scope", "distance": 123}, status)
    with pytest.raises(error):
        client.submit_gps(RECORD, LOCATION)
    response.close.assert_called_once()


def test_timeout_is_uncertain_and_never_retried_or_logged_verbatim():
    client, session, _ = gps_client({})
    session.put.side_effect = requests.Timeout("private-cookie-and-location")
    with pytest.raises(SubmissionUncertain) as error:
        client.submit_gps(RECORD, LOCATION)
    assert "private-cookie" not in str(error.value)
    session.put.assert_called_once()


@pytest.mark.parametrize("rid,kind", [("../profile", "GPS"), ("42", "数字")])
def test_wrong_activity_or_injected_id_never_writes(rid, kind):
    client, session, _ = gps_client({})
    with pytest.raises(ProtocolError):
        client.submit_gps(Rollcall(rid, "课程", "签到", kind, course_id="7"), LOCATION)
    session.put.assert_not_called()


def test_gps_freshness_checks_course_type_and_activity():
    client, _, _ = gps_client({})
    client.rollcalls = Mock(return_value=[RECORD])
    assert client.fresh_gps(RECORD) == RECORD
    client.rollcalls.return_value = [Rollcall("42", "课程", "签到", "数字", course_id="7")]
    assert client.fresh_gps(RECORD) is None
    client.rollcalls.return_value = [Rollcall("42", "课程", "签到", "GPS", course_id="8")]
    assert client.fresh_gps(RECORD) is None


@pytest.mark.parametrize("automatic", [False, True])
def test_full_workflow_with_real_client_and_simulated_http_backend(capsys, automatic):
    session = Mock()
    state = {"status": "absent"}

    def response(payload, status=200):
        result = Mock(status_code=status, headers={"content-type": "application/json"})
        result.json.return_value = payload
        return result

    def get(url, **options):
        if url.endswith("/api/profile"):
            return response({"id": 99})
        if url.endswith("/api/rollcall/42/student_rollcalls"):
            return response(
                {
                    "student_rollcalls": [
                        {"rollcall_status": "on_call_fine" if n < 21 else "absent"}
                        for n in range(80)
                    ]
                }
            )
        if url.endswith("/api/radar/rollcalls"):
            return response(
                {
                    "rollcalls": [
                        {
                            "rollcall_id": 42,
                            "course_id": 7,
                            "course_title": "测试课程",
                            "title": "签到",
                            "is_radar": True,
                            "rollcall_status": "in_progress",
                            "status": state["status"],
                        }
                    ]
                }
            )
        assert url == BASE_URL + "/api/course/7/student/99/rollcalls"
        return response({"rollcalls": [{"rollcall_id": 42, "status": state["status"]}]})

    def put(url, **options):
        assert url == BASE_URL + "/api/rollcall/42/answer"
        payload = options["json"]
        assert payload["latitude"] == LOCATION.latitude
        assert payload["longitude"] == LOCATION.longitude
        state["status"] = "on_call_fine"
        return response({"status_name": "on_call_fine"})

    session.get.side_effect = get
    session.put.side_effect = put
    client = CoursesClient(session)
    prompts = Mock()
    prompts.poll.return_value = []
    checkin = ConfirmedCheckin(
        client,
        prompts,
        settings=Settings(auto_checkin=automatic, gps=GpsSettings("test", "测试地点", LOCATION)),
    )
    checkin.observe(client.rollcalls())
    if not automatic:
        checkin.process()
        session.put.assert_not_called()
        prompts.poll.return_value = [Answer(Prompt(RECORD), "y")]
    checkin.process()
    assert session.put.call_count == 1
    assert state["status"] == "on_call_fine"
    assert "[签到成功]" in capsys.readouterr().out
    assert {call.kwargs["json"]["deviceId"] for call in session.put.call_args_list} == {
        client.device_id
    }


def test_configured_accuracy_is_submitted():
    client, session, _ = gps_client({"status": "on_call_fine"})
    client.submit_gps(RECORD, LOCATION, accuracy=68.0)
    assert session.put.call_args.kwargs["json"]["accuracy"] == 68.0


@pytest.mark.parametrize("accuracy", [True, "35", 0, -1, float("nan"), float("inf")])
def test_invalid_accuracy_never_writes(accuracy):
    client, session, _ = gps_client({})
    with pytest.raises(ProtocolError):
        client.submit_gps(RECORD, LOCATION, accuracy=accuracy)
    session.put.assert_not_called()
