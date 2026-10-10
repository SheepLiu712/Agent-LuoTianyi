"""Offline component evidence for the production realtime-call object graph."""

from __future__ import annotations

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

import src.agent.skills.expression.speaking.backend as speaking_backend
import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.adapter.websocket.call_v1 import BinaryAudioFrameCodec, CallStageBinding, CallTransportSession
from src.agent_runtime import agent_runtime as runtime_module
from src.application.call import CallSettlementCoordinator
from src.domain.call import CallAudioSemantic, CallEndReason, CallState
from src.infrastructure.models.realtime_speech import SpeechStarted, SpeechStopped, TurnCompleted
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import Conversation, User
from src.stage import CallStage, StageManager


async def _eventually(predicate, timeout=2.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


def _controls(delivered):
    return [json.loads(item.text) for item in delivered if item.text is not None]


def _latest_stream(delivered, *, response_marker: str | None = None):
    streams = [item for item in _controls(delivered) if item["type"] == "audio.stream_started"]
    if response_marker is None:
        return streams[-1]
    matches = [item for item in streams if response_marker in item["response_id"]]
    return matches[-1]


def _completed(call_id, seq, stream):
    return json.dumps(
        {
            "protocol": "call.v1",
            "type": "playback.completed",
            "seq": seq,
            "call_id": call_id,
            "response_id": stream["response_id"],
            "stream_id": stream["stream_id"],
        }
    )


@pytest.mark.asyncio
async def test_real_runtime_stage_binding_transport_sql_and_settlement_form_one_call(monkeypatch, tmp_path):
    """Exercise production components; only paid/provider/vector/TTS ports are deterministic fakes."""
    vector = DeterministicVectorStore()
    tts = DeterministicCallTTSModule()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(speaking_backend, "init_tts_module", lambda _config: tts)

    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "coherent.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="call-user", password="offline", description="喜欢音乐"))
        sql.commit()
    llm = DeterministicLLMService()
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path),
        llm,
        database,
        media_resolver=NoopMediaResolver(),
    )
    adapter = WebSocketAdapter()
    manager = StageManager(
        get_agent=runtime.get_agent,
        adapter=adapter,
        get_context_factory=lambda character_id: runtime.context_factories[character_id],
        call_sessions=database.call_sessions,
    )
    delivered = []

    async def deliver(output):
        delivered.append(output)

    provider_factory = FakeRealtimeSpeechSessionFactory()
    settled = []

    class SettlementConsumer:
        async def settle(self, snapshot):
            settled.append(snapshot)

    settlement = CallSettlementCoordinator(consumer=SettlementConsumer(), resources=runtime)
    claim = await manager.start_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="component-evidence",
    )
    ownership = manager.take_call_claim(
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="component-evidence",
    )
    binding = CallStageBinding(call_id=str(claim.record.call_id), deliver=deliver)
    session = CallTransportSession(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
    )
    stage = CallStage(
        ownership=ownership,
        record=claim.record,
        agent=runtime.get_agent("luotianyi"),
        context_factory=runtime.context_factories["luotianyi"],
        call_sessions=database.call_sessions,
        speech_factory=provider_factory,
        transport=binding,
        release_ownership=manager.release_call,
        settlement_sink=settlement,
    )
    binding.bind(stage=stage, session=session)

    try:
        await stage.start()
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        provider = provider_factory.sessions[claim.record.call_id]
        assert provider.started_with is not None

        await _eventually(lambda: any(item["type"] == "audio.stream_started" for item in _controls(delivered)))
        opening = _latest_stream(delivered)
        await _eventually(
            lambda: any(
                item.binary is not None
                and BinaryAudioFrameCodec().decode(item.binary).stream_id == opening["stream_id"]
                for item in delivered
            )
        )
        await session.receive_text(_completed(binding.call_id, 1, opening))

        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="你还记得我喜欢什么吗")))
        await _eventually(
            lambda: any(
                item["type"] == "audio.stream_started" and "recall-ack" in item["response_id"]
                for item in _controls(delivered)
            )
        )
        provisional = _latest_stream(delivered, response_marker="recall-ack")
        await _eventually(
            lambda: any(
                item.binary is not None
                and BinaryAudioFrameCodec().decode(item.binary).stream_id == provisional["stream_id"]
                and BinaryAudioFrameCodec().decode(item.binary).flags == 1
                for item in delivered
            )
        )
        assert not tts.formal_started.is_set()
        assert runtime.skills.call_recall.pool_texts(claim.record.call_id) == ("用户喜欢音乐",)

        await session.receive_text(_completed(binding.call_id, 2, provisional))
        await _eventually(lambda: tts.formal_started.is_set())
        await _eventually(
            lambda: any(
                item["type"] == "audio.stream_started" and "turn-1" in item["response_id"]
                for item in _controls(delivered)
            )
        )
        formal = _latest_stream(delivered, response_marker="turn-1")
        assert formal["response_id"] in stage._responses
        assert stage._responses[formal["response_id"]].playback_completed is False
        await _eventually(
            lambda: any(
                item.binary is not None and BinaryAudioFrameCodec().decode(item.binary).stream_id == formal["stream_id"]
                for item in delivered
            )
        )
        before_interrupt = len(delivered)
        await provider.emit(SpeechStarted())
        await asyncio.sleep(0.1)
        assert stage._events_task is not None and not stage._events_task.done(), (
            stage._events_task.exception() if stage._events_task is not None and stage._events_task.done() else None
        )
        await _eventually(lambda: formal["response_id"] in stage._tombstones)
        await _eventually(
            lambda: any(
                item["type"] == "playback.stop" and item["response_id"] == formal["response_id"]
                for item in _controls(delivered)
            )
        )
        stop = next(
            item
            for item in reversed(_controls(delivered))
            if item["type"] == "playback.stop" and item["response_id"] == formal["response_id"]
        )
        await session.receive_text(
            json.dumps(
                {
                    "protocol": "call.v1",
                    "type": "playback.stopped",
                    "seq": 3,
                    "call_id": binding.call_id,
                    "response_id": formal["response_id"],
                    "stop_seq": stop["seq"],
                }
            )
        )
        await _eventually(lambda: tts.formal_cancelled.is_set())
        await asyncio.sleep(0)
        assert not any(
            item.binary is not None
            and BinaryAudioFrameCodec().decode(item.binary).stream_id == formal["stream_id"]
            and index >= before_interrupt
            for index, item in enumerate(delivered)
        )

        await provider.emit(SpeechStopped())
        await stage._submit_stimulus(
            d.CallSilenceElapsed(
                **stage._stimulus_fields(),
                call_id=claim.record.call_id,
                silence_ms=5000,
            )
        )
        await _eventually(
            lambda: any(
                item["type"] == "audio.stream_started" and "silence" in item["response_id"]
                for item in _controls(delivered)
            )
        )
        farewell = next(
            item
            for item in reversed(_controls(delivered))
            if item["type"] == "audio.stream_started" and "silence" in item["response_id"]
        )
        await _eventually(
            lambda: any(
                item.binary is not None
                and BinaryAudioFrameCodec().decode(item.binary).stream_id == farewell["stream_id"]
                and BinaryAudioFrameCodec().decode(item.binary).flags == 1
                for item in delivered
            )
        )
        assert stage.state is CallState.ACTIVE
        await session.receive_text(_completed(binding.call_id, 4, farewell))
        snapshot = await asyncio.wait_for(stage.wait_closed(), 2)
        await settlement.close()

        assert snapshot.terminal.end_reason is CallEndReason.AGENT_HANGUP
        assert stage.state is CallState.ENDED
        assert provider.closed is True
        assert stage.context is None
        assert manager.current_call_ownership(binding.call_id) is None
        assert settled == [snapshot]
        assert runtime.skills.call_recall.pool_texts(claim.record.call_id) == ()
        assert vector.searches == [("user", "用户喜欢的音乐", 3)]
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user").count() == 0
    finally:
        if stage.snapshot is None:
            await stage._cleanup()
        await settlement.close()
        await manager.close()
        await runtime.shutdown()
        await database.shutdown()
