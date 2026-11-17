"""Offline component evidence for the production realtime-call object graph."""

from __future__ import annotations

import asyncio
import json
import time
from functools import partial
from types import SimpleNamespace

import pytest
from support.call_coherent_runtime import (
    DeterministicCallTTSModule,
    DeterministicLLMService,
    DeterministicVectorStore,
    NoopMediaResolver,
    runtime_config,
)
from support.call_output import output_sink
from support.call_protocol import ProtocolDriver, StageOutputDriver
from support.call_omni import factory, send_reply
from support.aliyun_realtime_speech import FakeAliyunWebSocket
from support.stage_lifecycle import wait_call_finished
from support.stage_manager import make_stage_manager

import src.agent.skills.expression.speaking.backend as speaking_backend
import src.domain.agent as d
from src.adapter.websocket.call_v1._audio_codec import BinaryAudioFrameCodec
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent_runtime import agent_runtime as runtime_module
from src.domain.call import CallAudioSemantic, CallEndReason, CallState
from src.infrastructure.models.realtime_speech import (
    SpeechStarted,
    SpeechStopped,
    TranscriptUpdated,
    TurnCompleted,
)
from src.infrastructure.observability.call_metrics import CallMetrics
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import Conversation, User
from src.stage import CallStage
from src.stage.call._call_history import CallHistory


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
        sql.add(
            User(
                uuid="user",
                username="call-user",
                password="offline",
                description="喜欢音乐",
            )
        )
        sql.commit()
    llm = DeterministicLLMService()
    socket = FakeAliyunWebSocket()
    provider_factory = factory(socket)
    runtime = runtime_module.AgentRuntime(
        runtime_config(tmp_path),
        llm,
        database,
        media_resolver=NoopMediaResolver(),
        omni_factory=provider_factory,
    )
    adapter = WebSocketAdapter()
    manager = make_stage_manager(
        get_agent=runtime.get_agent,
        adapter=adapter,
        get_context_factory=lambda character_id: runtime.context_factories[character_id],
        call_sessions=database.call_sessions,
    )
    delivered = []
    timing_rows = []
    metrics = CallMetrics(SimpleNamespace(record_pipeline_span=lambda **row: timing_rows.append(row)))

    async def deliver(output):
        delivered.append(output)

    settled = []

    history = CallHistory(call_sessions=database.call_sessions, conversation_service=database.conversation_service)

    async def save(snapshot, *, result):
        settled.append(snapshot)
        await history.save(snapshot, result=result)

    claim = await manager._claim_call(
        user_id="user",
        character_id="luotianyi",
        source_interaction_id=None,
        client_request_id="component-evidence",
    )
    ownership = manager._take_call_claim(
        claim,
        user_id="user",
        character_id="luotianyi",
        client_request_id="component-evidence",
    )
    binding = StageOutputDriver(call_id=str(claim.prepared._record.call_id), deliver=deliver)
    session = ProtocolDriver(
        call_id=binding.call_id,
        user_id="user",
        character_id="luotianyi",
        sink=binding,
    )
    stage = CallStage(
        ownership=ownership,
        record=claim.prepared._record,
        agent=runtime.get_agent("luotianyi"),
        context_factory=runtime.context_factories["luotianyi"],
        call_sessions=database.call_sessions,
        speech_factory=provider_factory,
        call_metrics=metrics,
        output_sink=output_sink(binding),
        save_history=save,
        own_initialization=partial(manager._own_initialization, user_id="user", release=manager._release_call_stage),
        own_termination=manager._own_termination,
        finish_source_interaction=manager._finish_source_interaction,
    )
    binding.bind(stage=stage, session=session)

    try:
        await stage.start()
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        await _eventually(lambda: any(e["type"] == "response.create" for e in socket.sent))
        await send_reply(socket, response_id="opening", text="你好，我在这里。", item_id=None)
        await _eventually(lambda: any(item["type"] == "audio.stream_started" for item in _controls(delivered)))
        opening = _latest_stream(delivered)
        await _eventually(lambda: stage._responses[opening["response_id"]].message_completed)
        await session.receive_text(_completed(binding.call_id, 1, opening))
        await stage._drain_facts()

        await send_reply(socket, response_id="lookup", text="", item_id="user-1", done=False)
        await socket.server_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "user-1",
                "transcript": "你还记得我喜欢什么吗",
            }
        )
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "lookup",
                "call_id": "memory-1",
                "name": "lookup_call_memory",
                "arguments": '{"query":"用户喜欢什么"}',
            }
        )
        await socket.server_event({"type": "response.done", "response": {"id": "lookup", "status": "completed"}})
        await _eventually(lambda: "memory-1" in stage._tool_results)
        call_memory = stage.context.call_memory
        assert tuple(item.content for item in call_memory.snapshot()) == ("用户喜欢音乐",)
        assert len(vector.searches) == 1
        await send_reply(
            socket, response_id="answer", text="我记得你喜欢音乐，我们继续聊吧。未播第二句。", item_id=None, done=False
        )
        await _eventually(lambda: tts.formal_started.is_set())
        await _eventually(
            lambda: any(
                i["type"] == "audio.stream_started" and "answer" in i["response_id"] for i in _controls(delivered)
            )
        )
        formal = _latest_stream(delivered, response_marker="answer")
        await _eventually(lambda: any(item.binary is not None for item in delivered))
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "user-2"})
        await _eventually(lambda: formal["response_id"] in stage._tombstones)
        await _eventually(lambda: tts.formal_cancelled.is_set())
        stop = next(item for item in reversed(_controls(delivered)) if item["type"] == "playback.stop")
        await session.receive_text(
            json.dumps(
                {
                    "protocol": "call.v1",
                    "type": "playback.stopped",
                    "seq": 2,
                    "call_id": binding.call_id,
                    "response_id": formal["response_id"],
                    "stop_seq": stop["seq"],
                }
            )
        )
        await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": "user-2"})
        await socket.server_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "user-2",
                "transcript": "先等一下",
            }
        )
        await _eventually(lambda: len(stage._completed_items) == 2)
        await session.receive_text(
            json.dumps(
                {
                    "protocol": "call.v1",
                    "type": "call.hangup",
                    "seq": 3,
                    "call_id": binding.call_id,
                    "reason": "user_hangup",
                }
            )
        )
        snapshot = await asyncio.wait_for(wait_call_finished(stage), 2)
        await manager._finalizations.close()
        assert snapshot.terminal.end_reason is CallEndReason.USER_HANGUP
        assert socket.closed and stage.context is None and not stage.tasks
        assert manager._current_call_ownership(binding.call_id) is None
        assert settled == [snapshot]
        summaries = llm.modules["skill.call_summary.generate.luotianyi"].calls
        assert len(summaries) == 1
        summary_input = "\n".join(summaries[0]["completed_turns"])
        assert "你好，我在这里。" in summary_input
        assert "你还记得我喜欢什么吗" in summary_input and "先等一下" in summary_input
        assert "未播第二句" not in summary_input and "我们继续聊吧" not in summary_input
        with database.open_sql_session() as sql:
            assert sql.query(Conversation).filter_by(user_id="user").count() == 1
    finally:
        if stage.snapshot is None:
            await stage._cleanup()
        await manager._finalizations.close()
        await manager.close()
        await runtime.shutdown()
        await database.shutdown()
