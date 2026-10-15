import builtins
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


@pytest.mark.parametrize(
    "module,package",
    [
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
        ("unknown_dependency", None),
    ],
)
def test_missing_dependency_reported_before_credentials(monkeypatch, capsys, module, package):
    original_import = builtins.__import__

    def missing_import(name, *args, **kwargs):
        if name == "auth":
            raise ModuleNotFoundError("private-ticket-must-not-be-printed", name=module)
        return original_import(name, *args, **kwargs)

    prompt = Mock(side_effect=AssertionError("Credentials must not be requested"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr("getpass.getpass", prompt)
    monkeypatch.setattr("builtins.__import__", missing_import)
    assert main(["--no-desktop", "--no-bell"]) == 1
    prompt.assert_not_called()
    output = capsys.readouterr().err
    assert "python -m pip install -r requirements.txt" in output
    if package:
        assert package in output
    assert "private-ticket" not in output
    assert "网络" not in output


def test_unexpected_failure_reports_location_without_private_message(monkeypatch, capsys):
    original_import = builtins.__import__

    def failed_import(name, *args, **kwargs):
        if name == "auth":
            raise RuntimeError("private-password-and-ticket")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.__import__", failed_import)
    assert main(["--no-desktop", "--no-bell"]) == 1
    output = capsys.readouterr().err
    assert "RuntimeError" in output
    assert "test_auth_cli.py:" in output
    assert "private-password" not in output


@pytest.mark.parametrize("options", [["--reminders-only"], ["--once"]])
def test_read_only_modes_do_not_construct_submission_handler(monkeypatch, options):
    from zju_ac import auth, checkin, monitor

    @contextmanager
    def fake_login(*args):
        yield Mock()

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "student")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "dummy-password")
    monkeypatch.setattr(auth, "login", fake_login)
    handler = Mock(side_effect=AssertionError("Submission handler must not be constructed"))
    monkeypatch.setattr(checkin, "ConfirmedCheckin", handler)
    run = Mock()
    monkeypatch.setattr(monitor, "run_monitor", run)
    assert main(["--no-watchdog", *options]) == 0
    handler.assert_not_called()
    assert run.call_args.kwargs["checkin"] is None
