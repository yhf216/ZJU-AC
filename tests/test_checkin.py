import threading
from unittest.mock import Mock

import pytest

from zju_ac.checkin import Answer, NumericCheckin, Prompt, TerminalPrompts
from zju_ac.errors import (
    AuthenticationExpired,
    CheckinRejected,
    SubmissionUncertain,
    TemporaryError,
)
from zju_ac.models import Rollcall

RECORD = Rollcall("42", "测试课程", "签到", "数字", course_id="7")


class FakePrompts:
    def __init__(self):
        self.requests = []
        self.answers = []
        self.closed = False

    def ask(self, prompt):
        self.requests.append(prompt)

    def poll(self):
        answers, self.answers = self.answers, []
        return answers

    def close(self):
        self.closed = True

    def reply(self, value):
        self.answers.append(Answer(self.requests[-1], value))


@pytest.fixture
def workflow():
    client = Mock()
    client.fresh_number.return_value = RECORD
    client.my_rollcall_status.return_value = "absent"
    client.read_number_code.return_value = "0123"
    client.verify_number.return_value = True
    prompts = FakePrompts()
    checkin = NumericCheckin(client, prompts)
    checkin.observe([RECORD])
    return client, prompts, checkin


def test_no_code_lookup_or_write_before_confirmation(workflow):
    client, prompts, checkin = workflow
    checkin.process()
    assert len(prompts.requests) == 1
    client.read_number_code.assert_not_called()
    client.submit_number.assert_not_called()


@pytest.mark.parametrize("answer", ["", "n", "no", "anything"])
def test_default_or_negative_answer_skips_without_submission(workflow, answer):
    client, prompts, checkin = workflow
    prompts.reply(answer)
    checkin.process()
    checkin.observe([RECORD])
    client.submit_number.assert_not_called()
    assert len(prompts.requests) == 1


def test_yes_submits_once_and_verifies(workflow, capsys):
    client, prompts, checkin = workflow
    prompts.reply("y")
    checkin.process()
    checkin.observe([RECORD])
    checkin.process()
    client.submit_number.assert_called_once_with(RECORD, "0123")
    client.verify_number.assert_called_once_with(RECORD)
    assert "签到成功" in capsys.readouterr().out


def test_duplicate_decision_cannot_submit_twice(workflow):
    client, prompts, checkin = workflow
    prompts.reply("yes")
    prompts.reply("yes")
    checkin.process()
    client.submit_number.assert_called_once()


def test_missing_code_prompts_for_manual_code_after_consent(workflow):
    client, prompts, checkin = workflow
    client.read_number_code.return_value = None
    prompts.reply("y")
    checkin.process()
    client.submit_number.assert_not_called()
    assert prompts.requests[-1].stage == "code"
    prompts.reply("0000")
    checkin.process()
    client.submit_number.assert_called_once_with(RECORD, "0000")


def test_manual_code_can_be_cancelled(workflow):
    client, prompts, checkin = workflow
    client.read_number_code.return_value = None
    prompts.reply("y")
    checkin.process()
    prompts.reply("")
    checkin.process()
    client.submit_number.assert_not_called()


def test_activity_expires_while_waiting_for_confirmation(workflow):
    client, prompts, checkin = workflow
    client.fresh_number.return_value = None
    prompts.reply("y")
    checkin.process()
    client.submit_number.assert_not_called()


def test_activity_expires_while_waiting_for_manual_code(workflow):
    client, prompts, checkin = workflow
    client.read_number_code.return_value = None
    prompts.reply("y")
    checkin.process()
    client.fresh_number.return_value = None
    prompts.reply("0123")
    checkin.process()
    client.submit_number.assert_not_called()


@pytest.mark.parametrize(
    "status", [None, "on_call", "on_call_fine", "on_personal_leave", "unknown"]
)
def test_missing_or_completed_personal_record_prevents_write(workflow, status):
    client, prompts, checkin = workflow
    client.my_rollcall_status.return_value = status
    prompts.reply("y")
    checkin.process()
    client.submit_number.assert_not_called()


def test_write_timeout_only_verifies_and_never_retries(workflow, capsys):
    client, prompts, checkin = workflow
    client.submit_number.side_effect = SubmissionUncertain("uncertain")
    prompts.reply("y")
    checkin.process()
    client.submit_number.assert_called_once()
    client.verify_number.assert_called_once()
    assert "签到成功" in capsys.readouterr().out


def test_http_200_without_confirmed_status_does_not_report_success(workflow, capsys):
    client, prompts, checkin = workflow
    client.verify_number.return_value = False
    prompts.reply("y")
    checkin.process()
    output = capsys.readouterr().out
    assert "待核验" in output
    assert "[签到成功]" not in output


def test_verification_network_failure_is_pending_not_success(workflow, capsys):
    client, prompts, checkin = workflow
    client.verify_number.side_effect = TemporaryError("offline")
    prompts.reply("y")
    checkin.process()
    assert "待核验" in capsys.readouterr().out
    client.submit_number.assert_called_once()


def test_rejected_code_does_not_stop_monitor_or_retry(workflow, capsys):
    client, prompts, checkin = workflow
    client.submit_number.side_effect = CheckinRejected("wrong code")
    prompts.reply("y")
    checkin.process()
    assert "未完成" in capsys.readouterr().out
    client.submit_number.assert_called_once()
    client.verify_number.assert_not_called()


def test_expired_session_propagates_to_main(workflow):
    client, prompts, checkin = workflow
    client.fresh_number.side_effect = AuthenticationExpired("expired")
    prompts.reply("y")
    with pytest.raises(AuthenticationExpired):
        checkin.process()


def test_eof_cancels_pending_decisions(workflow):
    client, prompts, checkin = workflow
    prompts.reply(None)
    prompts.reply("y")
    checkin.process()
    assert checkin.closed
    client.submit_number.assert_not_called()


def test_only_numeric_activities_get_confirmation(workflow):
    _, prompts, checkin = workflow
    checkin.observe([Rollcall("43", "课程", "签到", "GPS")])
    assert len(prompts.requests) == 1


def test_waiting_for_terminal_input_does_not_block_main_thread(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def waiting_input(message):
        entered.set()
        release.wait(3)
        return "y"

    monkeypatch.setattr("builtins.input", waiting_input)
    prompts = TerminalPrompts()
    try:
        prompts.ask(Prompt(RECORD))
        assert entered.wait(1)
        assert prompts.poll() == []
        prompts.close()
    finally:
        release.set()
        prompts.worker.join(timeout=2)
    assert prompts.poll() == []  # No late consent after shutdown.


def test_untrusted_course_text_cannot_control_terminal():
    prompt = Prompt(Rollcall("42", "课程\x1b\n", "签到\r", "数字"))
    assert "\x1b" not in prompt.message()
    assert "\n" not in prompt.message()


def test_activity_closes_during_automatic_code_lookup(workflow):
    client, prompts, checkin = workflow
    client.fresh_number.side_effect = [RECORD, None]
    prompts.reply("y")
    checkin.process()
    client.submit_number.assert_not_called()


def test_real_input_worker_delivers_confirmation_while_monitor_runs(monkeypatch):
    from zju_ac.monitor import run_monitor

    client, notifier = Mock(), Mock()
    finished = threading.Event()
    request_threads = []
    main_thread = threading.get_ident()

    def rollcalls():
        if finished.is_set():
            raise KeyboardInterrupt
        return [RECORD]

    def submit(*args):
        request_threads.append(threading.get_ident())

    def verify(*args):
        finished.set()
        return True

    client.rollcalls.side_effect = rollcalls
    client.fresh_number.return_value = RECORD
    client.my_rollcall_status.return_value = "absent"
    client.read_number_code.return_value = "0123"
    client.submit_number.side_effect = submit
    client.verify_number.side_effect = verify
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    checkin = NumericCheckin(client)
    try:
        with pytest.raises(KeyboardInterrupt):
            run_monitor(client, notifier, interval=0.02, checkin=checkin)
    finally:
        checkin.close()
        checkin.prompts.worker.join(timeout=2)
    client.submit_number.assert_called_once_with(RECORD, "0123")
    assert request_threads == [main_thread]
