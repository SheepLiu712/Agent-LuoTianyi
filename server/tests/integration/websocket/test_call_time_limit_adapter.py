"""Public call.v1 admission, warning audio, receipt and deadline settlement."""

import asyncio
import json

import pytest
from support.call_coherent_runtime import (
    DeterministicCallTTSModule,
    DeterministicLLMService,
    DeterministicVectorStore,
    NoopMediaResolver,
    runtime_config,
)
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import make_call_adapter, make_stage_manager

import src.agent.skills.expression.speaking.backend as speaking_backend
from src.adapter.websocket.call_v1 import CallTransportError
from src.adapter.websocket.call_v1._audio_codec import BinaryAudioFrameCodec
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent_runtime import agent_runtime as runtime_module
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallEndReason, CallState
from src.infrastructure.persistence.call_sessions import SettlementStatus
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import Conversation, User
from src.stage._call_warning import WarningState
from tests.integration.stage.test_call_stage import _Clock, _eventually
from tests.integration.websocket.test_call_websocket_adapter import start_message


@pytest.mark.asyncio
async def test_public_config_warning_audio_playback_ack_and_complete_deadline_settlement(tmp_path, monkeypatch):
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(speaking_backend, "init_tts_module", lambda _config: DeterministicCallTTSModule())
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "deadline.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="deadline-user", password="offline", description=""))
        sql.commit()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path), DeterministicLLMService(), database, media_resolver=NoopMediaResolver()
    )
    clock = _Clock()
    manager = make_stage_manager(
        get_agent=runtime.get_agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda character: runtime.context_factories[character],
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
        realtime_speech_factory=FakeRealtimeSpeechSessionFactory(),
        user_reset_fence=UserResetFence(),
        monotonic=clock.tick,
        wall_clock=clock.now,
        config={"call_stage": {"time_limit_seconds": 20, "time_limit_warning_seconds": 8}},
    )
    adapter = make_call_adapter(
        manager=manager, user_reset_fence=manager._user_reset_fence, enabled=True, supports_character=lambda _: True
    )
    delivered = []
    pumping = None

    async def pump(connection):
        while True:
            try:
                output = await adapter.next_output(connection)
            except (ConnectionError, CallTransportError):
                return
            delivered.append(output.message)
            adapter.complete_output(connection, output.delivery_id)

    def stream(marker):
        return next(
            (
                item
                for raw in delivered
                if isinstance(raw, str)
                for item in [json.loads(raw)]
                if item.get("type") == "audio.stream_started" and marker in item["response_id"]
            ),
            None,
        )

    async def confirm(connection, stage, marker, sequence):
        await _eventually(lambda: stream(marker) is not None, timeout=5)
        audio = stream(marker)
        codec = BinaryAudioFrameCodec()
        await _eventually(
            lambda: any(
                isinstance(raw, bytes)
                and codec.decode(raw).stream_id == audio["stream_id"]
                and codec.decode(raw).flags == 1
                for raw in delivered
            )
        )
        assert stage._responses[audio["response_id"]].confirmed is False
        raw = json.dumps(
            {
                "protocol": "call.v1",
                "type": "playback.completed",
                "seq": sequence,
                "call_id": stage.call_id,
                "response_id": audio["response_id"],
                "stream_id": audio["stream_id"],
            }
        )
        await adapter.receive(connection, raw)
        await adapter.receive(connection, raw)
        await _eventually(lambda: stage._responses[audio["response_id"]].confirmed)

    try:
        connection = await adapter.open(initial_message=start_message(), user_id="user", connection_id=object())
        stage = next(iter(manager._call_stages.values()))
        pumping = asyncio.create_task(pump(connection))
        await _eventually(lambda: stage.state is CallState.ACTIVE, timeout=5)
        assert stage._time_limit_seconds == 20 and stage._time_limit_warning_seconds == 8
        await confirm(connection, stage, "opening", 2)
        clock.advance(12)
        stage._time_limit_changed.set()
        await confirm(connection, stage, "time-limit-warning", 3)
        await _eventually(lambda: stage._warning.state is WarningState.DELIVERED)
        assert (
            sum(
                e.content.text == "通话时间快到了，我们很快就要结束啦。"
                for e in stage.context.conversation.read_working().entries
            )
            == 1
        )
        clock.advance(8)
        stage._time_limit_changed.set()
        snapshot = await asyncio.wait_for(stage.wait_closed(), 5)
        await asyncio.wait_for(pumping, 3)
        await manager._finalizations.close()
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert snapshot.terminal.active_duration_ms == 20_000
        controls = [json.loads(raw) for raw in delivered if isinstance(raw, str)]
        assert any(item["type"] == "call.ended" and item["end_reason"] == "time_limit" for item in controls)
        persisted = database.call_sessions.find_by_id(snapshot.terminal.call_id)
        assert persisted.summary_status is SettlementStatus.SUCCEEDED
        assert persisted.maintenance_status is SettlementStatus.SUCCEEDED
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user").count() == 1
        assert stage.context is None and not stage.tasks
        assert not manager._call_stages and not manager._call_ownerships
        assert not adapter._bindings and not adapter._sessions
    finally:
        await adapter.close()
        await manager.close()
        if pumping is not None:
            pumping.cancel()
            await asyncio.gather(pumping, return_exceptions=True)
        await runtime.shutdown()
        await database.shutdown()
