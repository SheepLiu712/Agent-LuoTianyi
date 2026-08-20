import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.chat_session.call_memory_pool import CallMemoryPool
from src.chat_session.call_response_parser import CallResponseParser
from src.chat_session.call_models import CallExitCode, CallResponseState, CallState
from src.chat_session.call_stream import CallStream
from src.system.database.call_store import CallStore
from src.system.database.sql_database import Base, CallTurn, User
from src.system.user_interface.types import AudioStreamType, ChatResponse, WSEventType
from src.utils.realtime_dialogue.models import RealtimeEventType
from src.utils.realtime_dialogue.qwen_session import normalize_qwen_event
from src.utils.realtime_dialogue.qwen_session import QwenRealtimeSession


def test_call_response_parser_splits_lines_and_defaults_unknown_tone():
    parser = CallResponseParser("call-1")
    lines = parser.feed_text_delta("response-1", "[温柔]你好\n没有标签\n[不存在]继续")
    lines += parser.flush_response("response-1")
    assert [line.content for line in lines] == ["你好", "没有标签", "继续"]
    assert [line.tone for line in lines] == ["tender", "happy", "happy"]


def test_memory_pool_injects_system_items_and_evicts_oldest():
    class FakeSession:
        def __init__(self):
            self.created = []
            self.deleted = []

        async def append_context_item(self, **kwargs):
            self.created.append(kwargs)

        async def delete_context_item(self, item_id):
            self.deleted.append(item_id)

    session = FakeSession()
    pool = CallMemoryPool(session=session, limit=2)
    hits = [SimpleNamespace(record=SimpleNamespace(id=str(i)), rendered_text=f"记忆{i}") for i in range(3)]
    result = asyncio.run(pool.add_hits(hits))
    assert result.added_count == 3
    assert result.deleted_count == 0  # 一批超过上限时完整保留本批
    assert pool.memory_ids == ("0", "1", "2")
    assert all(item["role"] == "system" for item in session.created)

    result = asyncio.run(pool.add_hits([SimpleNamespace(record=SimpleNamespace(id="3"), rendered_text="记忆3")]))
    assert result.deleted_count == 2
    assert pool.memory_ids == ("2", "3")
    assert session.deleted == ["call-memory-0", "call-memory-1"]


def test_call_exit_codes_keep_contract():
    assert int(CallExitCode.NORMAL) == 0
    assert int(CallExitCode.HANGUP_BEFORE_CONNECTED) == 1
    assert int(CallExitCode.RECONNECT_TIMEOUT) == -1
    assert int(CallExitCode.REALTIME_PROVIDER_FAILED) == -2


def test_server_audio_packets_declare_their_stream_type():
    chat_packet = ChatResponse(uuid="chat-1", text="你好")
    assert chat_packet.stream_type is AudioStreamType.CHAT

    sent = []
    stream = CallStream.__new__(CallStream)
    stream.call_id = "call-1"
    stream.state = CallState.ACTIVE
    stream.ws_connection = object()
    stream._sent_audio_ids = set()
    stream._last_speech_stopped_at = None
    stream._audio_lines = {
        "audio-1": SimpleNamespace(response_id="response-1", expression="开心"),
    }
    stream._responses = {
        "response-1": CallResponseState(response_id="response-1"),
    }
    stream._record_call_event = lambda *args, **kwargs: None

    async def capture(event_type, payload):
        sent.append((event_type, payload))

    stream._send_event = capture
    asyncio.run(
        stream._send_tts_packet(
            SimpleNamespace(
                uuid="audio-1",
                audio="cGNt",
                is_final_package=True,
                expression="开心",
            )
        )
    )

    assert sent[0][0] is WSEventType.CALL_AUDIO_CHUNK
    assert sent[0][1]["stream_type"] == AudioStreamType.CALL.value


def test_cancelled_call_response_rejects_late_playback_completion():
    appended = []
    stream = CallStream.__new__(CallStream)
    stream.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    stream._audio_lines = {
        "audio-1": SimpleNamespace(response_id="response-1", content="不应落库"),
    }
    stream._responses = {
        "response-1": CallResponseState(response_id="response-1", cancelled=True),
    }

    async def append_turn(*args, **kwargs):
        appended.append((args, kwargs))

    stream._append_turn = append_turn
    stream._record_call_event = lambda *args, **kwargs: None
    stream._schedule_proactive_check = lambda *args, **kwargs: None

    asyncio.run(
        stream._playback_completed(
            {"audio_id": "audio-1", "response_id": "response-1"}
        )
    )
    assert appended == []


def test_qwen_event_normalization_keeps_response_and_function_call_ids():
    text_event = normalize_qwen_event(
        {"type": "response.text.delta", "response_id": "resp-1", "delta": "你好", "event_id": "evt-1"}
    )
    function_event = normalize_qwen_event(
        {
            "type": "response.function_call_arguments.done",
            "response_id": "resp-1",
            "call_id": "call-1",
            "name": "search_memory",
            "arguments": "{}",
        }
    )
    assert text_event.response_id == "resp-1"
    assert text_event.type is RealtimeEventType.TEXT_DELTA
    assert function_event.call_id == "call-1"
    assert function_event.name == "search_memory"
    assert function_event.type is RealtimeEventType.FUNCTION_ARGUMENTS_DONE


def test_realtime_event_type_uses_provider_protocol_values():
    assert RealtimeEventType.SESSION_UPDATE.value == "session.update"
    assert RealtimeEventType.SPEECH_STARTED.value == "input_audio_buffer.speech_started"
    assert RealtimeEventType.RESPONSE_DONE.value == "response.done"
    assert normalize_qwen_event({"type": "provider.future_event"}).type == "provider.future_event"


def test_qwen_context_adapter_uses_documented_session_update_fallback():
    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def send(self, value):
            self.sent.append(json.loads(value))

    session = QwenRealtimeSession(
        config={"api_key": "key", "model": "qwen-audio-3.0-realtime-flash", "base_url": "wss://example"},
        trace_id="trace-1",
        call_id="call-1",
        instructions="基础人设",
        tools=[],
    )
    session.ws = FakeWebSocket()
    session._connected = True
    asyncio.run(session.append_context_item(role="system", text="记忆内容", item_id="memory-1"))
    assert session.ws.sent[-1]["type"] == "session.update"
    assert "role: system" in session.ws.sent[-1]["session"]["instructions"]
    asyncio.run(session.delete_context_item("memory-1"))
    assert "记忆内容" not in session.ws.sent[-1]["session"]["instructions"]


def test_call_store_settlement_and_turn_insert_are_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = Session()
    db.add(User(uuid="user-1", username="user-1", password="x"))
    db.commit()
    db.close()
    store = CallStore(SimpleNamespace(open_sql_session=Session))
    from datetime import datetime
    from src.chat_session.call_models import CallTurnDraft

    now = datetime.now()
    assert store.create_active_session(
        call_id="call-1", user_id="user-1", character_id="luotianyi", requested_at=now, connected_at=now
    )
    turn = CallTurnDraft(
        call_id="call-1",
        seq=0,
        speaker="user",
        text="你好",
        raw_events=[{"type": "response.audio.delta", "delta": "secret"}],
    )
    assert store.append_turn(turn)
    assert store.append_turn(turn)
    assert store.settle_call_and_conversation(call_id="call-1", ended_at=now, exit_code=0, duration_seconds=3)
    assert store.settle_call_and_conversation(call_id="call-1", ended_at=now, exit_code=0, duration_seconds=3)
    db = Session()
    assert db.query(CallTurn).filter(CallTurn.call_id == "call-1").count() == 1
    raw_events = json.loads(db.query(CallTurn).filter(CallTurn.call_id == "call-1").one().raw_events_json)
    assert raw_events[0]["delta"]["redacted"] is True
    db.close()
    assert store.get_session_summary("call-1")["turn_count"] == 1
