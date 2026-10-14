from unittest.mock import MagicMock, Mock

import pytest

from zju_ac.auth import fill_login_form, trusted_login_url
from zju_ac.cli import main, parser
from zju_ac.errors import AuthenticationExpired, ZjuError


@pytest.mark.parametrize(
    "url",
    [
        "https://identity.zju.edu.cn/auth",
        "https://zjuam.zju.edu.cn/cas/login",
        "https://courses.zju.edu.cn/login",
    ],
)
def test_trusted_auth_origins(url):
    assert trusted_login_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://identity.zju.edu.cn/login",
        "https://identity.zju.edu.cn.evil.example",
        "https://identity.zju.edu.cn@evil.example",
        "about:blank",
    ],
)
def test_credentials_not_filled_on_untrusted_pages(url):
    page = Mock(url=url)
    assert not trusted_login_url(url)
    assert not fill_login_form(page, "test", "secret")
    page.locator.assert_not_called()


def test_offline_demo_never_reads_credentials(monkeypatch, capsys):
    prompt = Mock(side_effect=AssertionError("Unexpected credential request"))
    monkeypatch.setattr("builtins.input", prompt)
    assert main(["--demo", "--no-desktop", "--no-bell"]) == 0
    assert "签到提醒" in capsys.readouterr().out


@pytest.mark.parametrize("option", ["--interval", "--remind-every", "--login-timeout"])
def test_too_short_intervals_rejected(option):
    with pytest.raises(SystemExit):
        parser().parse_args([option, "1"])


def login_mocks(monkeypatch, profiles):
    from zju_ac import auth

    engine = Mock()
    manager = MagicMock()
    manager.__enter__.return_value = engine
    browser = engine.chromium.launch.return_value
    context = browser.new_context.return_value
    page = context.new_page.return_value
    page.is_closed.return_value = False
    client = Mock()
    client.profile.side_effect = profiles
    monkeypatch.setattr(auth, "sync_playwright", lambda: manager)
    monkeypatch.setattr(auth, "CoursesClient", Mock(return_value=client))
    fill = Mock(return_value=True)
    monkeypatch.setattr(auth, "fill_login_form", fill)
    return auth, browser, page, client, fill


def test_login_waits_for_profile_and_submits_password_only_once(monkeypatch, capsys):
    auth, browser, page, client, fill = login_mocks(
        monkeypatch, [AuthenticationExpired("not ready"), {"id": 1}]
    )
    with auth.login("test-user", "private-password", "msedge", 180) as result:
        assert result is client
        browser.close.assert_not_called()
    browser.close.assert_called_once()
    fill.assert_called_once_with(page, "test-user", "private-password")
    assert "private-password" not in capsys.readouterr().out


def test_login_timeout_closes_browser(monkeypatch):
    auth, browser, _, _, _ = login_mocks(monkeypatch, [AuthenticationExpired("not ready")])
    monkeypatch.setattr(auth.time, "monotonic", Mock(side_effect=[0, 0, 999]))
    with pytest.raises(ZjuError, match="登录超时"), auth.login("test", "dummy", "msedge", 5):
        pytest.fail("An unverified session must not be yielded")
    browser.close.assert_called_once()


def test_closed_login_window_closes_browser(monkeypatch):
    auth, browser, page, _, _ = login_mocks(monkeypatch, [])
    page.is_closed.return_value = True
    with pytest.raises(ZjuError, match="窗口已关闭"), auth.login("test", "dummy", "msedge", 5):
        pytest.fail("A closed login window must stop authentication")
    browser.close.assert_called_once()
