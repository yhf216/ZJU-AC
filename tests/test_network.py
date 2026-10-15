"""Verify proxy bypass through real Requests preparation, without network I/O."""

from unittest.mock import Mock

import pytest
import requests

from zju_ac.auth import HttpAuthenticator
from zju_ac.client import CoursesClient
from zju_ac.models import Rollcall
from zju_ac.network import configure_direct_session, create_direct_session


@pytest.fixture
def proxy_environment(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    discover = Mock(side_effect=AssertionError("System/environment proxies must not be consulted"))
    monkeypatch.setattr(requests.sessions, "get_environ_proxies", discover)
    return discover


def fake_transport(session):
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"id": 99, "status": "on_call", "rollcalls": []}'
    response._content_consumed = True
    response.headers["Content-Type"] = "application/json"
    response.url = "https://courses.zju.edu.cn/api/profile"
    session.send = Mock(return_value=response)
    return session.send


@pytest.mark.parametrize("operation", ["auth_get", "auth_post", "profile", "poll", "submit"])
def test_all_application_requests_ignore_invalid_proxies(proxy_environment, operation):
    session = requests.Session()
    session.proxies["https"] = "http://127.0.0.1:8"
    send = fake_transport(session)
    try:
        if operation.startswith("auth"):
            auth = HttpAuthenticator(session, 30)
            response = auth.request(
                "POST" if operation == "auth_post" else "GET",
                "https://identity.zju.edu.cn/auth/realms/zju/protocol/cas/login",
            )
            response.close()
        else:
            client = CoursesClient(session)
            if operation == "profile":
                client.profile()
            elif operation == "poll":
                client.rollcalls()
            else:
                client.submit_number(Rollcall("42", "课程", "签到", "数字", course_id="7"), "0123")
        send.assert_called_once()
        assert dict(send.call_args.kwargs["proxies"]) == {}
        assert send.call_args.kwargs["verify"] is True
        assert session.trust_env is False
        assert session.proxies == {}
        proxy_environment.assert_not_called()
    finally:
        session.close()


def test_factory_does_not_replace_global_requests_session(proxy_environment):
    session_class = requests.Session
    direct = create_direct_session()
    unrelated = requests.Session()
    try:
        assert requests.Session is session_class
        assert direct.trust_env is False
        assert unrelated.trust_env is True
    finally:
        direct.close()
        unrelated.close()


def test_direct_configuration_preserves_session_identity_and_cookies():
    session = requests.Session()
    session.cookies.set("session", "offline-cookie", domain="courses.zju.edu.cn")
    session.headers["X-Test"] = "unchanged"
    try:
        assert configure_direct_session(session) is session
        assert session.cookies.get("session") == "offline-cookie"
        assert session.headers["X-Test"] == "unchanged"
        assert session.verify is True
    finally:
        session.close()
