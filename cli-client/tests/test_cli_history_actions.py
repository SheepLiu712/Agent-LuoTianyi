from types import SimpleNamespace

from cli_client.cli.actions import ActionExecutor, ExitCode
from cli_client.session import SessionState


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


def test_audio_history_keeps_placeholder_without_media_actions():
    session = Session()
    session.initial_history = (
        [
            SimpleNamespace(
                timestamp="2026-09-26",
                source="user",
                type="audio",
                content="[语音消息]",
                uuid="audio-one",
                duration_ms=900,
                audio_available=True,
            )
        ],
        0,
        1,
    )
    executor = ActionExecutor(session_factory=lambda **_: session)
    executor._session = session

    result, code = executor.execute({"action": "history.initial"})

    assert code == ExitCode.SUCCESS
    assert result["data"]["items"] == [
        {
            "timestamp": "2026-09-26",
            "source": "user",
            "type": "audio",
            "content": "[语音消息]",
            "uuid": "audio-one",
        }
    ]


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


def test_history_items_ignore_unknown_server_fields():
    """服务端向历史项新增字段时，CLI 必须忽略而不是让整页历史静默清空（AC-26）。"""
    from cli_client.network.network_client import _conversation_item_from_dict

    item = _conversation_item_from_dict(
        {
            "timestamp": "2026-09-26",
            "source": "user",
            "type": "audio",
            "content": "[语音消息]",
            "uuid": "audio-one",
            "duration_ms": 900,
            "audio_available": True,
            "transcript": "未公开字段",
            "future_field": {"nested": True},
        }
    )

    assert item.uuid == "audio-one"
    assert item.duration_ms == 900
    assert item.audio_available is True
    assert not hasattr(item, "transcript")


def test_network_client_get_history_ignores_unknown_server_fields():
    """调用点级回归：服务端新增历史字段时 NetworkClient.get_history 必须忽略而不是整页返回空。"""
    from cli_client.network.network_client import NetworkClient

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "history": [
                    {
                        "timestamp": "2026-09-26",
                        "source": "user",
                        "type": "audio",
                        "content": "[语音消息]",
                        "uuid": "audio-one",
                        "duration_ms": 900,
                        "audio_available": True,
                        "transcript": "未公开字段",
                        "future_field": {"nested": True},
                    }
                ],
                "start_index": 0,
            }

    client = NetworkClient("http://localhost:60030")
    client.user_id = "user"
    client.message_token = "token"
    client.session = SimpleNamespace(get=lambda *args, **kwargs: _Response())

    items, start_index = client.get_history(20, -1)

    assert start_index == 0
    assert len(items) == 1
    assert items[0].uuid == "audio-one"
    assert items[0].duration_ms == 900
    assert not hasattr(items[0], "transcript")
