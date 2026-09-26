from types import SimpleNamespace

from src.cli.actions import ActionExecutor, ExitCode
from src.session import SessionState


class Session:
    state = SessionState.READY
    initial_history = (
        [SimpleNamespace(timestamp="2026-09-26", source="agent", type="text", content="欢迎", uuid="one")],
        0,
        1,
    )

    def get_history(self, count, end_index):
        assert (count, end_index) == (20, -1)
        return self.initial_history[:2]

    def read_events(self, after_seq=0, kind=None):
        return [{"seq": 2, "kind": "agent_state", "value": "thinking", "timestamp_ms": 10}]

    def wait_for_event(self, kind, *, after_seq, timeout, value=None, contains=None):
        assert (kind, after_seq, timeout, value) == ("agent_state", 1, 3.0, "thinking")
        return self.read_events()[0]

    def send_typing(self, length, *, client_msg_id, ack_timeout):
        assert (length, client_msg_id) == (0, "typing-1")
        return {"ok": True}


def test_initial_and_explicit_history_are_observable_cli_actions():
    executor = ActionExecutor(session_factory=lambda **_: Session())
    executor._session = Session()
    initial, initial_code = executor.execute({"action": "history.initial"})
    loaded, loaded_code = executor.execute({"action": "history.load"})

    assert (initial_code, loaded_code) == (ExitCode.SUCCESS, ExitCode.SUCCESS)
    assert initial["data"]["load_count"] == 1
    assert initial["data"]["items"][0]["content"] == "欢迎"
    assert loaded["data"]["items"][0]["source"] == "agent"


def test_cli_exposes_event_stream_and_waits_for_matching_state():
    executor = ActionExecutor(session_factory=lambda **_: Session())
    executor._session = Session()
    read, read_code = executor.execute({"action": "events.read", "params": {"after_seq": 0}})
    waited, wait_code = executor.execute(
        {
            "action": "events.wait",
            "params": {"kind": "agent_state", "value": "thinking", "after_seq": 1, "timeout": 3},
        }
    )
    assert (read_code, wait_code) == (ExitCode.SUCCESS, ExitCode.SUCCESS)
    assert read["data"]["events"][0]["value"] == "thinking"
    assert waited["data"]["event"]["seq"] == 2


def test_cli_sends_zero_length_typing_signal_with_ack():
    executor = ActionExecutor(session_factory=lambda **_: Session())
    executor._session = Session()
    record, code = executor.execute(
        {
            "action": "chat.send_typing",
            "params": {"text_length": 0, "client_msg_id": "typing-1"},
        }
    )
    assert code == ExitCode.SUCCESS
    assert record["data"]["ack"] is True
