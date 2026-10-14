"""Offline CAS/Keycloak conversations, including security and cleanup failures."""

from unittest.mock import Mock

import pytest
import requests

from zju_ac import auth
from zju_ac.errors import ProtocolError, TemporaryError, ZjuError

ENTRY = "https://courses.zju.edu.cn/user/index"
CAS = "https://zjuam.zju.edu.cn/cas/login?service=https%3A%2F%2Fcourses.zju.edu.cn%2Fuser%2Findex"
IDENTITY = "https://identity.zju.edu.cn/auth/realms/zju/protocol/cas/login"
ACTION = "https://identity.zju.edu.cn/auth/realms/zju/login-actions/authenticate?session_code=mock"
KEY = {"modulus": "c" + "f" * 127, "exponent": "10001"}
CAS_FORM = """<form method="post" action="/cas/login">
<input name="username"><input name="password" type="password">
<input type="hidden" name="execution" value="dynamic-token">
<input type="hidden" name="_eventId" value="submit"></form>"""
IDENTITY_FORM = f'''<form id="kc-form-login" method="post" action="{ACTION.replace("&", "&amp;")}">
<input name="username"><input name="password" type="password">
<input type="hidden" name="credentialId" value=""></form>'''


def response(url, text="", status=200, location=None, payload=None):
    result = Mock(url=url, text=text, status_code=status)
    result.headers = {"content-type": "text/html"}
    if location is not None:
        result.headers["location"] = location
    result.json.return_value = payload
    return result


def session_with(*responses):
    session = Mock()
    session.request.side_effect = responses
    # API requests use the same session and perform an independent profile check.
    profile = response("https://courses.zju.edu.cn/api/profile", payload={"id": 7})
    profile.headers = {"content-type": "application/json"}
    session.get.return_value = profile
    return session


def test_legacy_cas_dynamic_fields_encryption_and_service_redirects():
    initial = response(ENTRY, status=302, location=CAS)
    page = response(CAS, CAS_FORM)
    key = response("https://zjuam.zju.edu.cn/cas/v2/getPubKey", payload=KEY)
    submitted = response(
        "https://zjuam.zju.edu.cn/cas/login",
        status=302,
        location="https://courses.zju.edu.cn/login?ticket=mock",
    )
    done = response("https://courses.zju.edu.cn/login?ticket=mock", "Done")
    session = session_with(initial, page, key, submitted, done)
    auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    post = next(c for c in session.request.call_args_list if c.args[0] == "POST")
    assert post.kwargs["data"]["execution"] == "dynamic-token"
    encrypted = post.kwargs["data"]["password"]
    assert encrypted != "dummy-password"
    assert int(encrypted, 16) == pow(
        int.from_bytes(b"dummy-password", "big"), 65537, int(KEY["modulus"], 16)
    )
    assert len(encrypted) == 128
    session.get.assert_called_once()
    for item in (initial, page, key, submitted, done):
        assert item.close.called


def test_keycloak_login_over_https_and_meta_refresh():
    refresh = '<meta http-equiv="Refresh" content="0;URL=/user/index">'
    session = session_with(
        response(ENTRY, status=302, location=IDENTITY),
        response(IDENTITY, IDENTITY_FORM),
        response(ACTION, refresh),
        response("https://identity.zju.edu.cn/user/index", "Done"),
    )
    auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    post = next(c for c in session.request.call_args_list if c.args[0] == "POST")
    assert post.args[1] == ACTION
    assert post.kwargs["data"] == {
        "credentialId": "",
        "username": "student",
        "password": "dummy-password",
    }
    assert post.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("target", ["https://evil.example", "http://identity.zju.edu.cn/login"])
def test_untrusted_redirect_rejected_before_following(target):
    initial = response(ENTRY, status=302, location=target)
    session = session_with(initial)
    with pytest.raises(ProtocolError, match="不可信"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    assert session.request.call_count == 1
    initial.close.assert_called_once()


def test_untrusted_form_action_never_receives_password():
    html = IDENTITY_FORM.replace(ACTION, "https://evil.example/login")
    session = session_with(response(ENTRY, html))
    with pytest.raises(ProtocolError, match="不可信"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    assert session.request.call_count == 1


def test_non_post_form_never_receives_password():
    session = session_with(
        response(IDENTITY, IDENTITY_FORM.replace('method="post"', 'method="get"'))
    )
    with pytest.raises(ProtocolError, match="POST"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    assert session.request.call_count == 1


def test_failed_password_is_not_retried():
    session = session_with(response(IDENTITY, IDENTITY_FORM), response(ACTION, IDENTITY_FORM))
    with pytest.raises(ZjuError, match="不会自动重试"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    assert sum(c.args[0] == "POST" for c in session.request.call_args_list) == 1
    session.get.assert_not_called()


def test_otp_step_uses_terminal_not_browser(monkeypatch):
    otp = f'<form method="post" action="{ACTION}"><input name="otp"></form>'
    session = session_with(
        response(IDENTITY, IDENTITY_FORM),
        response(ACTION, otp),
        response(ACTION, "Done"),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "123456")
    auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    posts = [c for c in session.request.call_args_list if c.args[0] == "POST"]
    assert len(posts) == 2
    assert posts[1].kwargs["data"] == {"otp": "123456"}


def test_login_requires_profile_not_http_200():
    session = session_with(response(ENTRY, "An error page"))
    session.get.return_value = response(ENTRY, "Sign in")
    with pytest.raises(ZjuError, match="未取得有效登录会话"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")


def test_credential_preserving_redirect_not_replayed():
    session = session_with(
        response(IDENTITY, IDENTITY_FORM),
        response(ACTION, status=307, location=ACTION),
    )
    with pytest.raises(ProtocolError, match="重新发送密码"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    assert session.request.call_count == 2


def test_redirect_loop_bounded():
    session = Mock()
    session.request.side_effect = lambda *a, **kw: response(ENTRY, status=302, location=ENTRY)
    with pytest.raises(ProtocolError, match="跳转次数过多"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy-password")
    assert session.request.call_count == 21


@pytest.mark.parametrize(
    "key", [{}, None, {"modulus": "x", "exponent": "3"}, {"modulus": "ff", "exponent": "1"}]
)
def test_invalid_rsa_keys_rejected(key):
    with pytest.raises(ProtocolError):
        auth.encrypt_cas_password("dummy", key)


def test_auth_deadline_checked_before_request(monkeypatch):
    session = Mock()
    monkeypatch.setattr(auth.time, "monotonic", Mock(side_effect=[0, 999]))
    with pytest.raises(ZjuError, match="登录超时"):
        auth.HttpAuthenticator(session, 5).authenticate("student", "dummy-password")
    session.request.assert_not_called()


def test_network_exception_is_redacted():
    session = Mock()
    session.request.side_effect = requests.ConnectionError("private-ticket")
    with pytest.raises(TemporaryError) as error:
        auth.HttpAuthenticator(session, 5).authenticate("student", "dummy-password")
    assert "private-ticket" not in str(error.value)


@pytest.mark.parametrize("failure", [False, True])
def test_session_closed_and_cookies_cleared_on_success_or_failure(monkeypatch, failure):
    session = Mock()
    monkeypatch.setattr(auth.requests, "Session", lambda: session)
    authenticate = Mock()
    if failure:
        authenticate.side_effect = ZjuError("failed")
    monkeypatch.setattr(auth.HttpAuthenticator, "authenticate", authenticate)
    if failure:
        with pytest.raises(ZjuError), auth.login("student", "dummy"):
            pytest.fail("No client should be yielded after failed login")
    else:
        with auth.login("student", "dummy") as client:
            assert client.session is session
            session.close.assert_not_called()
    session.cookies.clear.assert_called_once()
    session.close.assert_called_once()


def test_session_cleared_when_monitor_is_interrupted(monkeypatch):
    session = Mock()
    monkeypatch.setattr(auth.requests, "Session", lambda: session)
    monkeypatch.setattr(auth.HttpAuthenticator, "authenticate", Mock())
    with pytest.raises(KeyboardInterrupt), auth.login("student", "dummy"):
        raise KeyboardInterrupt
    session.cookies.clear.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "status,error", [(401, ZjuError), (429, TemporaryError), (500, TemporaryError)]
)
def test_auth_http_errors_are_classified_and_closed(status, error):
    failed = response(ENTRY, status=status)
    session = session_with(failed)
    with pytest.raises(error):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy")
    failed.close.assert_called_once()


def test_unknown_custom_login_form_does_not_receive_credentials():
    custom = IDENTITY_FORM.replace(ACTION, "https://identity.zju.edu.cn/custom-login")
    session = session_with(response(IDENTITY, custom))
    with pytest.raises(ProtocolError, match="尚未支持"):
        auth.HttpAuthenticator(session, 180).authenticate("student", "dummy")
    assert session.request.call_count == 1
