from unittest.mock import Mock

import pytest
import requests

from zju_ac.client import BASE_URL, CoursesClient
from zju_ac.errors import AuthenticationExpired, ProtocolError, TemporaryError, ZjuError


def client_response(status=200, payload=None, content_type="application/json"):
    response = Mock(status_code=status, headers={"content-type": content_type})
    response.json.return_value = payload if payload is not None else {"rollcalls": []}
    session = Mock()
    session.get.return_value = response
    return CoursesClient(session), session, response


def test_reads_only_expected_endpoint_without_redirects():
    client, session, response = client_response()
    assert client.rollcalls() == []
    session.get.assert_called_once_with(
        BASE_URL + "/api/radar/rollcalls",
        timeout=15,
        allow_redirects=False,
        headers={"Accept": "application/json"},
    )
    response.close.assert_called_once()


@pytest.mark.parametrize("path", ["https://evil.example", "/api/rollcall/1/answer", "//evil"])
def test_rejects_unapproved_api_paths(path):
    client, session, _ = client_response()
    with pytest.raises(ValueError):
        client.get_json(path)
    session.get.assert_not_called()


@pytest.mark.parametrize(
    "status,error",
    [
        (302, AuthenticationExpired),
        (401, AuthenticationExpired),
        (403, ZjuError),
        (404, ProtocolError),
        (429, TemporaryError),
        (500, TemporaryError),
    ],
)
def test_http_failure_classification_and_response_cleanup(status, error):
    client, _, response = client_response(status=status)
    with pytest.raises(error):
        client.rollcalls()
    response.close.assert_called_once()


def test_login_html_never_looks_like_no_attendance():
    client, _, _ = client_response(content_type="text/html")
    with pytest.raises(AuthenticationExpired):
        client.rollcalls()


@pytest.mark.parametrize("body", [{"success": False}, {"error_code": "denied"}])
def test_http_200_business_failure_is_not_success(body):
    client, _, _ = client_response(payload=body)
    with pytest.raises(ProtocolError):
        client.rollcalls()


def test_invalid_json_reports_protocol_error():
    client, _, response = client_response()
    response.json.side_effect = ValueError("private response")
    with pytest.raises(ProtocolError, match="无效 JSON"):
        client.rollcalls()
    response.close.assert_called_once()


def test_network_error_does_not_expose_ticket_in_display_message():
    client, session, _ = client_response()
    session.get.side_effect = requests.ConnectionError("private-ticket-value")
    with pytest.raises(TemporaryError) as error:
        client.rollcalls()
    assert "private-ticket-value" not in str(error.value)


def test_profile_requires_user_id():
    client, _, _ = client_response(payload={"name": "test"})
    with pytest.raises(AuthenticationExpired):
        client.profile()
