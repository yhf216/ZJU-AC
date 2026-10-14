from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from zju_ac.auth import trusted_login_url
from zju_ac.cli import main, parser


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
        "https://identity.zju.edu.cn:8443/login",
        "https://identity.zju.edu.cn:bad/login",
    ],
)
def test_untrusted_auth_origins(url):
    assert not trusted_login_url(url)


def test_offline_demo_never_reads_credentials(monkeypatch, capsys):
    prompt = Mock(side_effect=AssertionError("Unexpected credential request"))
    monkeypatch.setattr("builtins.input", prompt)
    assert main(["--demo", "--no-desktop", "--no-bell"]) == 0
    assert "签到提醒" in capsys.readouterr().out


@pytest.mark.parametrize("option", ["--interval", "--remind-every", "--login-timeout"])
def test_too_short_intervals_rejected(option):
    with pytest.raises(SystemExit):
        parser().parse_args([option, "1"])


def test_browser_option_removed():
    with pytest.raises(SystemExit):
        parser().parse_args(["--browser", "msedge"])


def test_interactive_cli_uses_http_login_then_monitor(monkeypatch):
    from zju_ac import auth, monitor

    client = Mock()
    calls = []

    @contextmanager
    def fake_login(student_id, password, timeout):
        calls.append((student_id, password, timeout))
        yield client

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "student")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "dummy-password")
    monkeypatch.setattr(auth, "login", fake_login)
    run = Mock()
    monkeypatch.setattr(monitor, "run_monitor", run)
    assert main(["--once", "--no-desktop", "--no-bell"]) == 0
    assert calls == [("student", "dummy-password", 180)]
    assert run.call_args.args[0] is client
    assert run.call_args.args[-1] is True
