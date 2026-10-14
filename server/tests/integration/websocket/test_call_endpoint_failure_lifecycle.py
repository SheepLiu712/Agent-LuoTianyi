"""Physical call endpoint failure evidence over the production Adapter facade."""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.realtime_speech import FakeRealtimeSpeechSessionFactory

from src.adapter.websocket import WebSocketAdapter
from src.adapter.websocket.call_v1 import CallTransportError, CallWebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.infrastructure.persistence.call_sessions import SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage import StageManager
from src.web.websocket import call_endpoint
from tests.integration.stage.test_call_stage import _ContextDatabase
from tests.integration.stage.test_chat_stage import RecordingAgent


def _start_message() -> str:
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.start",
            "seq": 1,
            "client_request_id": "endpoint-send-failure",
            "character_id": "luotianyi",
            "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        },
        separators=(",", ":"),
    )


def _resume_message(call_id: str) -> str:
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": call_id,
            "character_id": "luotianyi",
            "last_contiguous_server_seq": 0,
        },
        separators=(",", ":"),
    )


class _PhysicalSendFailureSocket:
    """A deterministic physical WebSocket whose first server send fails."""

    def __init__(self) -> None:
        self.receive_started = asyncio.Event()
        self.receive_cancelled = asyncio.Event()
        self.closed: tuple[int, str] | None = None

    async def receive(self):
        self.receive_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.receive_cancelled.set()

    async def send_text(self, _text: str) -> None:
        await self.receive_started.wait()
        raise RuntimeError("injected physical send failure")

    async def send_bytes(self, _data: bytes) -> None:
        raise AssertionError("test only queues a text frame")

    async def close(self, *, code: int, reason: str) -> None:
        self.closed = (code, reason)


@pytest.mark.asyncio
async def test_physical_send_failure_cancels_receive_disconnects_and_allows_resume(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'endpoint-call.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    speech = FakeRealtimeSpeechSessionFactory()
    manager = StageManager(
        get_agent=lambda _character: RecordingAgent(),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        realtime_speech_factory=speech,
        user_reset_fence=UserResetFence(),
    )
    adapter = CallWebSocketAdapter(
        manager=manager,
        user_reset_fence=manager._user_reset_fence,
        enabled=True,
        supports_character=lambda _character: True,
    )
    call = await adapter.open(raw=_start_message(), user_id="user", connection_id=object())
    preparing = json.loads((await adapter.next_output(call)).text)
    call_id = preparing["call_id"]
    socket = _PhysicalSendFailureSocket()

    async def return_open_call(*_args, **_kwargs):
        return call

    monkeypatch.setattr(call_endpoint, "_authenticate_and_open", return_open_call)
    try:
        await asyncio.wait_for(call_endpoint._serve_call(socket, object(), adapter), 1)
        assert socket.closed == (1011, "internal call transport error")
        assert socket.receive_cancelled.is_set()

        with pytest.raises(CallTransportError, match="STALE_CALL_CONNECTION"):
            await adapter.next_output(call)

        resumed = await adapter.open(raw=_resume_message(call_id), user_id="user", connection_id=object())
        resumed_frame = json.loads((await adapter.next_output(resumed)).text)
        assert resumed_frame["type"] == "call.resumed"
        assert resumed_frame["call_id"] == call_id
        await adapter.disconnect(resumed)
    finally:
        await adapter.close()
        await manager.close()
        engine.dispose()
