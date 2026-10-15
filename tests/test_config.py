import pickle
from pathlib import Path
from unittest.mock import Mock

import pytest

from zju_ac import cli
from zju_ac.config import CONFIG_PATH, GpsSettings, Settings, load_config
from zju_ac.errors import ZjuError
from zju_ac.gate import allows_auto_checkin
from zju_ac.gps import Coordinates
from zju_ac.models import Rollcall


def read_settings(tmp_path, content):
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return load_config(path)


def test_project_config_contains_manual_default_and_selected_reference_coordinates():
    config = load_config()
    assert not config.auto_checkin
    assert config.gate == "immediate"
    assert config.watchdog
    assert config.gps.location == "ZJGD1"
    assert config.gps.coordinates == Coordinates(30.302331, 120.089136)


def test_config_path_does_not_depend_on_shell_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert CONFIG_PATH == Path(__file__).resolve().parents[1] / "config.toml"
    assert load_config().mode == "monitor"


def test_automatic_switch_and_all_operational_settings_are_loaded(tmp_path):
    settings = read_settings(
        tmp_path,
        """
[runtime]
mode = "reminders"
interval = 20
remind_every = 60
login_timeout = 120
[checkin]
auto_checkin = true
gate = "immediate"
[notifications]
desktop = false
bell = false
[watchdog]
enabled = false
restart_delay = 10
max_restarts = 3
[gps]
location = "classroom"
accuracy = 68.0
[gps.locations.classroom]
name = "实际课堂"
latitude = 30.2
longitude = 120.1
""",
    )
    assert settings == Settings(
        mode="reminders",
        interval=20,
        remind_every=60,
        login_timeout=120,
        auto_checkin=True,
        desktop=False,
        bell=False,
        watchdog=False,
        restart_delay=10,
        max_restarts=3,
        gps=GpsSettings("classroom", "实际课堂", Coordinates(30.2, 120.1), 68.0),
    )


@pytest.mark.parametrize("mode", ["monitor", "reminders", "once", "demo"])
def test_runtime_modes(tmp_path, mode):
    settings = read_settings(tmp_path, f'[runtime]\nmode = "{mode}"\n')
    assert settings.once is (mode == "once")
    assert settings.demo is (mode == "demo")
    assert settings.reminders_only is (mode == "reminders")


@pytest.mark.parametrize(
    "content",
    [
        '[checkin]\nauto_checkin = "false"',
        "[checkin]\nauto_checkin = 1",
        '[checkin]\ngate = "percentage"',
        "[checkin]\nauto_chekin = true",
        '[runtime]\nmode = "unknown"',
        "[runtime]\ninterval = 1",
        "[runtime]\ninterval = true",
        "[runtime]\ninterval = 5.5",
        "[runtime]\nremind_every = 1",
        "[runtime]\nlogin_timeout = 0",
        '[watchdog]\nenabled = "true"',
        "[watchdog]\nrestart_delay = 0",
        "[watchdog]\nmax_restarts = -1",
        '[notifications]\ndesktop = "false"',
        '[gps]\nlocation = "missing"',
        "[gps]\naccuracy = nan",
        "[gps]\naccuracy = inf",
        "[gps]\naccuracy = true",
        "[gps]\naccuracy = 0",
        "[gps.locations.test]\nlatitude = 91\nlongitude = 0",
        "[gps.locations.test]\nlatitude = 30",
        "[gps.locations.test]\nlatitude = 30\nlongitude = 120\nname = 1",
        "[gps.locations.test]\nlatitude = 30\nlongitude = 120\nlongtitude = 120",
        '[unknown]\npassword = "private-password"',
        "checkin = []",
        "invalid TOML private-password",
    ],
)
def test_invalid_settings_cannot_silently_enable_submission(tmp_path, content):
    with pytest.raises(ZjuError) as error:
        read_settings(tmp_path, content)
    assert "private-password" not in str(error.value)


def test_utf8_bom_and_chinese_comments_supported(tmp_path):
    settings = read_settings(tmp_path, "\ufeff# 中文注释\n[checkin]\nauto_checkin = false\n")
    assert not settings.auto_checkin


def test_missing_config_reports_actionable_error(tmp_path):
    with pytest.raises(ZjuError, match="config.toml"):
        load_config(tmp_path / "missing.toml")


def test_config_error_occurs_before_credentials(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", Mock(side_effect=ZjuError("config.toml invalid")))
    prompt = Mock(side_effect=AssertionError("No credentials should be requested"))
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr("getpass.getpass", prompt)
    assert cli.main([]) == 2
    prompt.assert_not_called()
    assert "config.toml" in capsys.readouterr().err


def test_config_snapshot_is_picklable_for_watchdog_worker():
    settings = load_config()
    assert pickle.loads(pickle.dumps(settings)) == settings


def test_unknown_gate_fails_instead_of_defaulting_to_immediate():
    with pytest.raises(ZjuError):
        allows_auto_checkin(Rollcall("1", "课程", "签到", "数字"), "unknown")


@pytest.mark.parametrize(
    "flag",
    [
        "--interval",
        "--watchdog",
        "--no-watchdog",
        "--demo",
        "--once",
        "--reminders-only",
        "--no-desktop",
    ],
)
def test_operational_flags_rejected_in_favor_of_config(flag):
    with pytest.raises(SystemExit):
        cli.parser().parse_args([flag])
