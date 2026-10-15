import argparse
import os
import runpy
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from zju_ac import cli, watchdog
from zju_ac.errors import AuthenticationExpired, ProtocolError, TemporaryError, ZjuError


def settings(**changes):
    return argparse.Namespace(restart_delay=15, max_restarts=2, **changes)


def fake_process(code, pid=1234):
    worker = Mock(pid=pid, exitcode=code)
    worker.is_alive.return_value = False
    return worker


def fake_context(monkeypatch, *workers):
    context = Mock()
    context.Process.side_effect = workers
    monkeypatch.setattr(watchdog.multiprocessing, "get_context", Mock(return_value=context))
    sleep = Mock()
    monkeypatch.setattr(watchdog.time, "sleep", sleep)
    return context, sleep


@pytest.mark.parametrize("code,result", [(0, 0), (watchdog.USER_ACTION_REQUIRED, 1)])
def test_normal_exit_and_user_action_do_not_restart(monkeypatch, code, result):
    worker = fake_process(code)
    context, sleep = fake_context(monkeypatch, worker)
    assert watchdog.run_watchdog(settings(), watchdog.Credentials("offline", "dummy")) == result
    context.Process.assert_called_once()
    sleep.assert_not_called()
    worker.close.assert_called_once()


@pytest.mark.parametrize("crash_code", [1, 7, -9, 0xC0000005])
def test_crash_restarts_then_stops_on_normal_exit(monkeypatch, crash_code):
    first, second = fake_process(crash_code), fake_process(0, 5678)
    context, sleep = fake_context(monkeypatch, first, second)
    credentials = watchdog.Credentials("offline", "dummy")
    args = settings()
    assert watchdog.run_watchdog(args, credentials) == 0
    assert context.Process.call_count == 2
    assert context.Process.call_args.kwargs["args"] == (args, credentials)
    sleep.assert_called_once_with(15)


def test_restart_limit_prevents_endless_crash_loop(monkeypatch):
    context, sleep = fake_context(monkeypatch, *(fake_process(1) for _ in range(3)))
    assert watchdog.run_watchdog(settings(), watchdog.Credentials("offline", "dummy")) == 1
    assert context.Process.call_count == 3  # Initial launch and two restarts.
    assert sleep.call_count == 2


def test_old_restarts_expire_from_sliding_window(monkeypatch):
    context, sleep = fake_context(monkeypatch, fake_process(1), fake_process(1), fake_process(0))
    monkeypatch.setattr(watchdog.time, "monotonic", Mock(side_effect=[0, 601]))
    args = settings()
    args.max_restarts = 1
    assert watchdog.run_watchdog(args, watchdog.Credentials("offline", "dummy")) == 0
    assert context.Process.call_count == 3
    assert sleep.call_count == 2


def test_ctrl_c_during_restart_wait_stops(monkeypatch):
    context, sleep = fake_context(monkeypatch, fake_process(1))
    sleep.side_effect = KeyboardInterrupt
    assert watchdog.run_watchdog(settings(), watchdog.Credentials("offline", "dummy")) == 0
    context.Process.assert_called_once()


def test_ctrl_c_stops_only_owned_worker(monkeypatch):
    worker = fake_process(1)
    worker.join.side_effect = [KeyboardInterrupt, None, None]
    worker.is_alive.side_effect = [True, True, False]
    context, _ = fake_context(monkeypatch, worker)
    assert watchdog.run_watchdog(settings(), watchdog.Credentials("offline", "dummy")) == 0
    context.Process.assert_called_once()
    worker.terminate.assert_called_once()
    worker.kill.assert_not_called()
    worker.close.assert_called_once()


def test_unresponsive_owned_worker_is_killed():
    worker = fake_process(1)
    worker.is_alive.return_value = True
    watchdog.stop_worker(worker)
    worker.terminate.assert_called_once()
    worker.kill.assert_called_once()


def test_spawn_failure_is_reported_without_restart(monkeypatch):
    worker = fake_process(None, pid=None)
    worker.start.side_effect = OSError("private-details")
    context, sleep = fake_context(monkeypatch, worker)
    assert watchdog.run_watchdog(settings(), watchdog.Credentials("offline", "dummy")) == 1
    context.Process.assert_called_once()
    sleep.assert_not_called()


def test_credentials_are_not_in_repr_or_logs(monkeypatch, caplog):
    credentials = watchdog.Credentials("private-student-id", "private-password")
    assert "private" not in repr(credentials)
    fake_context(monkeypatch, fake_process(1), fake_process(0))
    with caplog.at_level("INFO", logger="zju_ac.watchdog"):
        watchdog.run_watchdog(settings(), credentials)
    assert "private-password" not in caplog.text
    assert "private-student-id" not in caplog.text


def test_worker_restores_interactive_terminal(monkeypatch):
    original, terminal = Mock(), Mock()
    original.isatty.return_value = False
    monkeypatch.setattr(sys, "stdin", original)
    opened = Mock(return_value=terminal)
    monkeypatch.setattr("builtins.open", opened)
    with watchdog.worker_terminal():
        assert sys.stdin is terminal
    assert sys.stdin is original
    assert opened.call_args.args == ("CONIN$" if os.name == "nt" else "/dev/tty",)
    terminal.close.assert_called_once()


def test_worker_reports_terminal_unavailable_as_user_action(monkeypatch):
    monkeypatch.setattr(watchdog, "worker_terminal", Mock(side_effect=ZjuError("no terminal")))
    with pytest.raises(SystemExit) as error:
        watchdog.worker_entry(settings(), watchdog.Credentials("offline", "dummy"))
    assert error.value.code == watchdog.USER_ACTION_REQUIRED


def test_spawn_entry_does_not_reenter_cli(monkeypatch):
    entry = Mock(side_effect=AssertionError("CLI must not run while importing a spawned main"))
    monkeypatch.setattr(cli, "main", entry)
    runpy.run_module("zju_ac", run_name="__mp_main__")
    entry.assert_not_called()


@pytest.mark.parametrize(
    "failure,code",
    [
        (ProtocolError("invalid protocol"), 2),
        (ZjuError("incorrect credentials"), 2),
        (AuthenticationExpired("expired"), 1),
        (TemporaryError("offline"), 1),
        (RuntimeError("private-password"), 1),
    ],
)
def test_supervised_exit_classification(monkeypatch, capsys, failure, code):
    from zju_ac import auth

    monkeypatch.setattr(auth, "login", Mock(side_effect=failure))
    prompt = Mock(side_effect=AssertionError("Stored in-memory credentials should be reused"))
    monkeypatch.setattr("builtins.input", prompt)
    args = cli.parser().parse_args(["--watchdog", "--once", "--no-desktop", "--no-bell"])
    assert (
        cli.run_application(args, watchdog.Credentials("offline", "dummy"), supervised=True) == code
    )
    prompt.assert_not_called()
    assert "private-password" not in capsys.readouterr().err


@pytest.mark.parametrize("options", [[], ["--watchdog"], ["--reminders-only"]])
def test_cli_prompts_once_then_hands_credentials_to_supervisor(monkeypatch, options):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    username, password = Mock(return_value="offline"), Mock(return_value="dummy")
    monkeypatch.setattr("builtins.input", username)
    monkeypatch.setattr("getpass.getpass", password)
    supervisor = Mock(return_value=0)
    monkeypatch.setattr(cli, "run_watchdog", supervisor)
    assert cli.main(options) == 0
    username.assert_called_once()
    password.assert_called_once()
    assert supervisor.call_args.args[1].student_id == "offline"
    assert supervisor.call_args.args[1].password == "dummy"


@pytest.mark.parametrize("option", ["--restart-delay", "--max-restarts"])
def test_invalid_restart_parameters_rejected(option):
    with pytest.raises(SystemExit):
        cli.parser().parse_args([option, "0"])


def test_worker_entry_uses_supervised_mode(monkeypatch):
    monkeypatch.setattr(watchdog, "worker_terminal", nullcontext)
    application = Mock(return_value=0)
    monkeypatch.setattr(cli, "run_application", application)
    args, credentials = settings(), watchdog.Credentials("offline", "dummy")
    with pytest.raises(SystemExit) as error:
        watchdog.worker_entry(args, credentials)
    assert error.value.code == 0
    application.assert_called_once_with(args, credentials, supervised=True)


def test_real_spawn_recovers_from_hard_exit_without_network(tmp_path):
    script = tmp_path / "watchdog_smoke.py"
    script.write_text(
        """
import argparse
import logging
import os
from pathlib import Path
from zju_ac import watchdog

def crash_once(args, credentials):
    marker = Path(args.marker)
    if not marker.exists():
        marker.write_text("crashed", encoding="utf-8")
        os._exit(7)
    raise SystemExit(0)

if __name__ == "__main__":
    watchdog.configure_terminal()
    logging.basicConfig(level=logging.INFO)
    watchdog.worker_entry = crash_once
    args = argparse.Namespace(
        restart_delay=1, max_restarts=2, marker=str(Path(__file__).with_suffix(".txt")),
    )
    credentials = watchdog.Credentials("offline-test", "dummy-password")
    raise SystemExit(watchdog.run_watchdog(args, credentials))
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "退出码 7" in result.stderr
    assert result.stderr.count("工作进程已启动") == 2
    assert "dummy-password" not in result.stderr
