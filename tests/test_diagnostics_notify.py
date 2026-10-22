import json
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from zju_ac import cli, diagnostics
from zju_ac.config import Settings
from zju_ac.models import Rollcall
from zju_ac.notify import Notifier


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    recorder = diagnostics.Recorder(tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    yield recorder
    recorder.close()


def test_error_chain_contains_code_locations_but_no_values_or_source_lines(recorder):
    private = "secret-password-cookie-ticket-code-0123-latitude-30.3"
    try:
        try:
            raise ValueError(private)
        except ValueError as exc:
            raise RuntimeError(private) from exc
    except RuntimeError as exc:
        diagnostics.record("application_error", error=exc, activity="987654321")
    data = recorder.path.read_text(encoding="utf-8")
    assert private not in data
    assert "987654321" not in data
    entry = json.loads(data)
    assert [item["type"] for item in entry["errors"]] == ["RuntimeError", "ValueError"]
    assert entry["errors"][0]["frames"][-1]["file"] == "test_diagnostics_notify.py"
    assert "line" in entry["errors"][0]["frames"][-1]
    assert all(
        set(frame) == {"file", "line", "function"}
        for error in entry["errors"]
        for frame in error["frames"]
    )


def test_allowlist_drops_unknown_events_and_untrusted_channel_values(recorder):
    diagnostics.record("SECRET")
    diagnostics.record("channel_error", channel="secret-cookie", http_status=503)
    entries = [json.loads(line) for line in recorder.path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert "channel" not in entries[0]
    assert entries[0]["http_status"] == 503


def test_own_status_diagnostics_keep_only_allowlisted_states_and_sources(recorder):
    diagnostics.record("own_status", source="radar", reason="matched", status="absent")
    diagnostics.record(
        "submit_cancelled",
        source="private-account",
        reason="private-code",
        status="private-password",
        activity="private-activity",
    )
    data = recorder.path.read_text("utf-8")
    assert "private" not in data
    entries = [json.loads(line) for line in data.splitlines()]
    assert entries[0]["status"] == "absent"
    assert entries[0]["source"] == "radar"
    assert entries[1]["status"] == "unknown"
    assert "source" not in entries[1]


def test_bundle_exports_only_diagnostics_and_minimal_environment(recorder):
    diagnostics.record("code_read", activity="42", attempt=1)
    (recorder.directory / "config.toml").write_text("private-password", encoding="utf-8")
    (recorder.directory / "cookies.json").write_text("private-cookie", encoding="utf-8")
    (recorder.directory / "terminal.log").write_text("private-course", encoding="utf-8")
    target = diagnostics.export_bundle()
    with ZipFile(target) as bundle:
        assert set(bundle.namelist()) == {recorder.path.name, "environment.json"}
        data = "\n".join(bundle.read(name).decode("utf-8") for name in bundle.namelist())
        assert "private" not in data
        environment = json.loads(bundle.read("environment.json"))
        assert set(environment) == {"version", "python", "system", "machine"}


def test_rotation_and_retention_limit_diagnostic_storage(tmp_path):
    recorder = diagnostics.Recorder(tmp_path)
    try:
        recorder.handler.maxBytes = 100
        for _ in range(20):
            recorder.emit("code_read", activity="42", attempt=1)
        assert len(list(tmp_path.iterdir())) <= 3
    finally:
        recorder.close()
    for _ in range(12):
        recorder = diagnostics.Recorder(tmp_path)
        recorder.emit("startup")
        recorder.close()
    assert len(list(tmp_path.glob("diagnostic-*.jsonl"))) <= 10


def test_cli_unexpected_error_automatically_exports_private_safe_bundle(recorder, monkeypatch):
    from zju_ac import auth

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "private-student")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "private-password")
    monkeypatch.setattr(auth, "login", Mock(side_effect=RuntimeError("private-ticket")))
    assert cli.run_application(Settings(watchdog=False, desktop=False, bell=False)) == 1
    (target,) = recorder.directory.glob("support-*.zip")
    with ZipFile(target) as bundle:
        content = "\n".join(bundle.read(name).decode("utf-8") for name in bundle.namelist())
    assert "private-student" not in content
    assert "private-password" not in content
    assert "private-ticket" not in content
    assert "RuntimeError" in content


def test_manual_export_and_disk_failure_have_actionable_output(recorder, monkeypatch, capsys):
    diagnostics.record("startup")
    assert diagnostics.main() == 0
    assert "脱敏诊断包已导出" in capsys.readouterr().out
    monkeypatch.setattr(diagnostics, "export_bundle", Mock(side_effect=OSError("private")))
    assert diagnostics.main() == 1
    diagnostics.report_error("application_error", RuntimeError("private"))
    output = capsys.readouterr().err
    assert "导出失败" in output
    assert "private" not in output


@pytest.mark.parametrize(
    "outcome,label", [("success", "签到成功"), ("failure", "签到未完成"), ("pending", "签到待核验")]
)
def test_result_notification_titles_and_sanitized_course(monkeypatch, outcome, label):
    backend = Mock()
    monkeypatch.setitem(__import__("sys").modules, "plyer", SimpleNamespace(notification=backend))
    notifier = Notifier(bell=False)
    notifier.result(Rollcall("42", "课程\n\x1b", "签到", "数字"), outcome)
    options = backend.notify.call_args.kwargs
    assert label in options["title"]
    assert "课程" in options["message"]
    assert "\n" not in options["message"]
    assert "\x1b" not in options["message"]


def test_desktop_failure_does_not_interrupt_workflow(monkeypatch):
    backend = Mock()
    backend.notify.side_effect = RuntimeError("unavailable")
    monkeypatch.setitem(__import__("sys").modules, "plyer", SimpleNamespace(notification=backend))
    notifier = Notifier(bell=False)
    notifier.result(Rollcall("42", "课程", "签到", "GPS"), "failure")
    assert not notifier.desktop
    notifier.result(Rollcall("43", "课程", "签到", "数字"), "success")
    backend.notify.assert_called_once()


def test_disabled_desktop_never_loads_backend(monkeypatch):
    backend = Mock()
    monkeypatch.setitem(__import__("sys").modules, "plyer", SimpleNamespace(notification=backend))
    Notifier(desktop=False, bell=False).result(Rollcall("42", "课程", "签到", "数字"), "success")
    backend.notify.assert_not_called()


def test_offline_demo_delivers_all_outcome_types_without_login(recorder, monkeypatch):
    backend = Mock()
    monkeypatch.setitem(__import__("sys").modules, "plyer", SimpleNamespace(notification=backend))
    prompt = Mock(side_effect=AssertionError("No login for demo"))
    monkeypatch.setattr("builtins.input", prompt)
    assert cli.run_application(Settings(mode="demo", bell=False)) == 0
    assert [call.kwargs["title"] for call in backend.notify.call_args_list] == [
        "ZJU-AC 签到提醒",
        "ZJU-AC 签到成功",
        "ZJU-AC 签到未完成",
        "ZJU-AC 签到待核验",
    ]
    prompt.assert_not_called()
