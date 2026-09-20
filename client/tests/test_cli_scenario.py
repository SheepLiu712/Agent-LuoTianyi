import json

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.cli.output import Redactor
from src.cli.scenario import run_scenario
from src.session import SessionState


class FakeExecutor:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.executed = []
        self.session_id = "s-test"
        self.redactor = Redactor()
        self.closed = False

    def execute(self, raw):
        action = raw["action"]
        self.executed.append(action)
        status, exit_code, data = self.outcomes.get(
            action, ("passed", ExitCode.SUCCESS, {})
        )
        record = {
            "schema_version": "1.0",
            "timestamp": "2026-09-20T00:00:00Z",
            "session_id": self.session_id,
            "action_id": f"a-{len(self.executed)}",
            "action": action,
            "event": "action_result",
            "status": status,
            "duration_ms": 1,
            "correlation_id": None,
            "data": data,
            "error": None
            if exit_code == 0
            else {"code": "X", "message": "boom", "category": "assertion"},
        }
        return record, exit_code

    def close(self):
        self.closed = True


def _run(executor, scenario, report_path=None, include_content=False):
    records = []
    exit_code = run_scenario(
        executor,
        json.dumps(scenario) if isinstance(scenario, dict) else scenario,
        records.append,
        report_path=report_path,
        include_content=include_content,
    )
    return records, exit_code


def test_valid_scenario_executes_in_order_and_emits_summary():
    executor = FakeExecutor()
    records, exit_code = _run(
        executor,
        {"actions": [{"action": "session.status"}, {"action": "session.status"}]},
    )

    assert executor.executed == ["session.status", "session.status"]
    assert [r["status"] for r in records] == ["passed", "passed", "passed"]
    summary = records[-1]
    assert summary["action"] == "scenario.run"
    assert summary["event"] == "scenario_result"
    assert summary["data"] == {
        "action_count": 2,
        "passed": 2,
        "failed": 0,
        "timed_out": 0,
        "skipped": 0,
        "suppressed": 0,
        "exit_code": 0,
    }
    assert exit_code == 0


def test_failure_skips_side_effect_and_continues_readonly():
    executor = FakeExecutor({"chat.send_text": ("failed", ExitCode.ASSERTION_FAILED, {})})
    records, exit_code = _run(
        executor,
        {
            "actions": [
                {"action": "chat.send_text", "params": {"text": "hi"}},
                {"action": "dynamics.post", "params": {"content": "x"}},
                {"action": "session.status"},
                {"action": "reply.read", "params": {"reply_uuid": "r1"}},
            ]
        },
    )

    assert executor.executed == ["chat.send_text", "session.status", "reply.read"]
    statuses = [r["status"] for r in records]
    assert statuses == ["failed", "skipped", "passed", "passed", "failed"]
    skipped = records[1]
    assert skipped["action"] == "dynamics.post"
    assert skipped["data"] == {"reason": "after_failure"}
    summary = records[-1]
    assert summary["data"]["failed"] == 1
    assert summary["data"]["skipped"] == 1
    assert summary["data"]["passed"] == 2
    assert exit_code == ExitCode.ASSERTION_FAILED


def test_on_failure_continue_executes_everything():
    executor = FakeExecutor({"chat.send_text": ("failed", ExitCode.ASSERTION_FAILED, {})})
    records, exit_code = _run(
        executor,
        {
            "actions": [
                {"action": "chat.send_text", "params": {"text": "hi"}},
                {"action": "dynamics.post", "params": {"content": "x"}},
            ],
            "on_failure": "continue",
        },
    )

    assert executor.executed == ["chat.send_text", "dynamics.post"]
    assert [r["status"] for r in records] == ["failed", "passed", "failed"]
    assert exit_code == ExitCode.ASSERTION_FAILED


def test_suppressed_does_not_trigger_skip_or_nonzero_exit():
    executor = FakeExecutor({"touch.send": ("suppressed", ExitCode.SUCCESS, {"suppressed": True})})
    records, exit_code = _run(
        executor,
        {
            "actions": [
                {"action": "touch.send", "params": {"touch_area": "head"}},
                {"action": "chat.send_text", "params": {"text": "hi"}},
            ]
        },
    )

    assert executor.executed == ["touch.send", "chat.send_text"]
    assert [r["status"] for r in records] == ["suppressed", "passed", "passed"]
    summary = records[-1]
    assert summary["status"] == "passed"
    assert summary["data"]["suppressed"] == 1
    assert exit_code == 0


def test_timed_out_triggers_skip_and_exit_five():
    executor = FakeExecutor({"reply.wait": ("timed_out", ExitCode.TIMEOUT, {})})
    records, exit_code = _run(
        executor,
        {
            "actions": [
                {"action": "reply.wait", "params": {"reply_uuid": "r1", "timeout": 1}},
                {"action": "dynamics.post", "params": {"content": "x"}},
            ]
        },
    )

    assert executor.executed == ["reply.wait"]
    assert [r["status"] for r in records] == ["timed_out", "skipped", "failed"]
    assert exit_code == ExitCode.TIMEOUT


@pytest.mark.parametrize(
    "scenario",
    [
        "{not json",
        "[1, 2]",
        {},
        {"actions": []},
        {"actions": ["x"]},
        {"actions": [{}]},
        {"actions": [{"action": "session.status"}], "on_failure": "nope"},
    ],
)
def test_invalid_scenario_emits_single_record_and_exit_three(scenario):
    executor = FakeExecutor()
    records, exit_code = _run(executor, scenario)

    assert executor.executed == []
    assert len(records) == 1
    record = records[0]
    assert record["action"] == "scenario.run"
    assert record["status"] == "failed"
    assert record["error"]["code"] == "INVALID_SCENARIO"
    assert record["error"]["category"] == "input"
    assert exit_code == ExitCode.INPUT_ERROR


def test_report_default_contains_metadata_only(tmp_path):
    executor = FakeExecutor(
        {
            "reply.read": (
                "passed",
                ExitCode.SUCCESS,
                {"text": "SECRET REPLY TEXT", "password": "TOPSECRET"},
            )
        }
    )
    report_path = tmp_path / "report.json"

    records, exit_code = _run(
        executor,
        {"actions": [{"action": "reply.read", "params": {"reply_uuid": "r1"}}]},
        report_path=report_path,
    )

    assert exit_code == 0
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["exit_code"] == 0
    assert report["summary"]["passed"] == 1
    action_entry = report["actions"][0]
    assert action_entry["action"] == "reply.read"
    assert action_entry["data_keys"] == ["text", "password"]
    assert "data" not in action_entry
    text = report_path.read_text(encoding="utf-8")
    assert "SECRET REPLY TEXT" not in text
    assert "TOPSECRET" not in text
    assert len(list(tmp_path.iterdir())) == 1


def test_report_include_content_keeps_redaction(tmp_path):
    executor = FakeExecutor(
        {
            "reply.read": (
                "passed",
                ExitCode.SUCCESS,
                {"text": "SECRET REPLY TEXT", "password": "TOPSECRET"},
            )
        }
    )
    report_path = tmp_path / "report.json"

    _run(
        executor,
        {"actions": [{"action": "reply.read", "params": {"reply_uuid": "r1"}}]},
        report_path=report_path,
        include_content=True,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    action_entry = report["actions"][0]
    assert action_entry["data"]["text"] == "SECRET REPLY TEXT"
    assert action_entry["data"]["password"] == "***"
    assert "TOPSECRET" not in report_path.read_text(encoding="utf-8")


def test_report_write_failure_is_reported_and_counted(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    executor = FakeExecutor()

    records, exit_code = _run(
        executor,
        {"actions": [{"action": "session.status"}]},
        report_path=blocker / "report.json",
    )

    summary = records[-1]
    assert summary["error"]["code"] == "REPORT_WRITE_FAILED"
    assert summary["status"] == "failed"
    assert exit_code == ExitCode.INPUT_ERROR


class FakeSession:
    def __init__(self, *, audio_active=True):
        self.state = SessionState.READY
        self.is_server_audio_active = audio_active

    def close(self):
        self.state = SessionState.CLOSED


def test_real_executor_suppressed_counts_as_success():
    session = FakeSession(audio_active=True)
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session, session_id="s-real"
    )
    executor._session = session

    records, exit_code = _run(
        executor,
        {
            "actions": [
                {"action": "touch.send", "params": {"touch_area": "head"}},
                {"action": "session.status"},
            ]
        },
    )

    assert [r["status"] for r in records] == ["suppressed", "passed", "passed"]
    assert exit_code == 0


def test_main_wiring_runs_scenario_file(tmp_path, monkeypatch):
    import src.cli.main as cli_main

    monkeypatch.setattr(cli_main, "ActionExecutor", FakeExecutor)
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps({"actions": [{"action": "session.status"}]}), encoding="utf-8"
    )
    out, err = _io_sinks()

    code = cli_main.main(["--scenario", str(scenario_file)], stdout=out, stderr=err)

    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2  # action + summary
    assert json.loads(lines[0])["action"] == "session.status"
    assert json.loads(lines[1])["action"] == "scenario.run"
    assert code == 0

    out2, err2 = _io_sinks()
    missing_code = cli_main.main(
        ["--scenario", str(tmp_path / "missing.json")], stdout=out2, stderr=err2
    )
    lines2 = [line for line in out2.getvalue().splitlines() if line.strip()]
    assert len(lines2) == 1
    assert json.loads(lines2[0])["error"]["code"] == "INVALID_SCENARIO"
    assert missing_code == ExitCode.INPUT_ERROR


def _io_sinks():
    import io

    return io.StringIO(), io.StringIO()
