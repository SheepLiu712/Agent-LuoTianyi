"""Production-shaped evidence for call Context handoff and final settlement."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from support.call_coherent_runtime import (
    DeterministicCallTTSModule,
    DeterministicLLMService,
    DeterministicVectorStore,
    NoopMediaResolver,
    runtime_config,
)
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import create_call_stage, make_stage_manager

import src.agent.skills.expression.speaking.backend as speaking_backend
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import (
    ConversationCompaction,
    ConversationEntry,
    ConversationMode,
    ConversationSummary,
    TextContent,
)
from src.agent_runtime import agent_runtime as runtime_module
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallEndReason, CallReplyStatus, CallState
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import Conversation, User
from src.stage._finalization import InteractionFinalizing
from src.stage.call_stage import _Turn


class _StrictClock:
    def __init__(self) -> None:
        self._value = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self._value += timedelta(microseconds=1)
        return self._value


class _Transport:
    def __init__(self) -> None:
        self.stage = None

    def bind_stage(self, stage) -> None:
        self.stage = stage

    async def send_state(self, _event) -> None:
        return None

    async def start_stream(self, response_id, stream_id, audio_format) -> None:
        return None

    async def send_pcm(self, response_id, stream_id, payload, *, final) -> None:
        return None

    async def stop_response(self, *_args, **_kwargs) -> None:
        return None

    async def send_ended(self, _snapshot) -> None:
        return None

    async def send_failed(self, _reason) -> None:
        return None


def _entry(entry_id: str, second: int, source: str, text: str) -> ConversationEntry:
    return ConversationEntry(
        entry_id,
        datetime(2026, 10, 14, 11, 0) + timedelta(seconds=second),
        source,
        TextContent(text),
    )


async def _eventually(predicate, timeout: float = 5.0) -> None:
    async def wait() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


@pytest.mark.asyncio
async def test_stage_handoff_uses_one_context_until_real_sqlite_settlement_finishes(monkeypatch, tmp_path):
    """The Stage-owned Context remains readable and admission stays busy through the real SQL write."""
    vector = DeterministicVectorStore()
    monkeypatch.setattr(runtime_module, "get_vector_store", lambda: vector)
    monkeypatch.setattr(runtime_module, "clear_vector_store", lambda expected: expected is vector)
    monkeypatch.setattr(
        speaking_backend,
        "init_tts_module",
        lambda _config: DeterministicCallTTSModule(),
    )

    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "handoff.sqlite"})
    with database.open_sql_session() as sql:
        sql.add(User(uuid="user", username="handoff-user", password="offline", description=""))
        sql.commit()
    llm = DeterministicLLMService()
    runtime = runtime_module.AgentRuntime(runtime_config(tmp_path), llm, database, media_resolver=NoopMediaResolver())
    factory = runtime.context_factories["luotianyi"]

    seed = await factory.create("seed-chat", mode=ConversationMode.CHAT, user_id="user")
    await seed.conversation.append(
        (
            _entry("seed-user", 1, "user", "seed history must stay out"),
            _entry("seed-agent", 2, "agent", "seed reply must stay out"),
        )
    )
    await seed.close()

    created = []
    original_create = factory.create

    async def observed_create(*args, **kwargs):
        context = await original_create(*args, **kwargs)
        created.append(context)
        return context

    monkeypatch.setattr(factory, "create", observed_create)
    agent_lookups = []

    def resolve_agent(character_id):
        agent_lookups.append(character_id)
        assert len(agent_lookups) == 1, "settlement must reuse the Stage agent"
        return runtime.get_agent(character_id)

    clock = _StrictClock()
    manager = make_stage_manager(
        get_agent=resolve_agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character_id: factory,
        call_sessions=database.call_sessions,
        conversation_service=database.conversation_service,
        call_maintenance_batches=database.call_maintenance_batches,
        realtime_speech_factory=FakeRealtimeSpeechSessionFactory(),
        user_reset_fence=UserResetFence(),
        wall_clock=clock.now,
    )
    transport = _Transport()
    order: list[str] = []
    write_entered = threading.Event()
    write_release = threading.Event()
    close_count = 0

    maintenance = runtime.skills.call_maintenance
    original_maintenance = maintenance.maintain_ending

    async def observed_maintenance(invocation, context, snapshot, *, settlement_input_digest):
        assert context is created[0]
        assert invocation.interaction_id == str(snapshot.terminal.call_id)
        order.append("maintenance")
        return await original_maintenance(
            invocation,
            context,
            snapshot,
            settlement_input_digest=settlement_input_digest,
        )

    monkeypatch.setattr(maintenance, "maintain_ending", observed_maintenance)
    summary_skill = runtime.skills.call_summary
    original_summary = summary_skill.summarize

    async def observed_summary(invocation, snapshot, *, context=None):
        assert context is created[0]
        assert invocation.interaction_id == str(snapshot.terminal.call_id)
        order.append("summary")
        return await original_summary(invocation, snapshot, context=context)

    monkeypatch.setattr(summary_skill, "summarize", observed_summary)
    original_write = database.conversation_service.add_call_conversation

    def blocked_real_write(*args, **kwargs):
        order.append("sqlite-write-start")
        write_entered.set()
        assert write_release.wait(10)
        result = original_write(*args, **kwargs)
        order.append("sqlite-write-end")
        return result

    monkeypatch.setattr(database.conversation_service, "add_call_conversation", blocked_real_write)

    stage = None
    try:
        claim = await manager._claim_call(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id=None,
            client_request_id="real-handoff",
        )
        stage = await create_call_stage(
            manager,
            claim,
            user_id="user",
            character_id="luotianyi",
            client_request_id="real-handoff",
            speech_factory=manager._test_call_resources["speech_factory"],
            transport=transport,
            stage_created=transport.bind_stage,
        )
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        assert len(created) == 1
        context = created[0]
        assert context.identity.interaction_id == str(claim.prepared._record.call_id)
        assert stage.context is context

        close_original = context.close

        async def observed_close():
            nonlocal close_count
            close_count += 1
            order.append("context-close-start")
            await close_original()
            order.append("context-close-end")

        monkeypatch.setattr(context, "close", observed_close)
        await context.conversation.append(
            (
                _entry("call-turn-1-user", 10, "user", "turn one user"),
                _entry("call-turn-1-agent-0", 11, "agent", "turn one agent"),
                _entry("call-turn-2-user", 12, "user", "uncompressed tail user"),
                _entry("call-turn-2-agent-0", 13, "agent", "uncompressed tail agent"),
            )
        )
        await context.conversation.compact(
            ConversationCompaction(
                ConversationSummary(),
                ("call-turn-1-user", "call-turn-1-agent-0"),
                ConversationSummary("maintained working prefix"),
            )
        )
        stage._turns = {
            1: _Turn("turn one user", CallReplyStatus.COMPLETED, "turn one agent"),
            2: _Turn(
                "uncompressed tail user",
                CallReplyStatus.COMPLETED,
                "uncompressed tail agent",
            ),
        }

        snapshot = await stage.terminate(CallEndReason.USER_HANGUP)
        assert snapshot is not None
        assert stage.context is None
        assert await asyncio.to_thread(write_entered.wait, 10)

        working_during_write = context.conversation.read_working()
        assert working_during_write.summary.text
        working_by_id = {item.entry_id: item.content.text for item in working_during_write.entries}
        assert working_by_id["call-turn-2-user"] == "uncompressed tail user"
        assert working_by_id["call-turn-2-agent-0"] == "uncompressed tail agent"
        assert all(not entry_id.startswith("seed-") for entry_id in working_by_id)
        assert close_count == 0
        with pytest.raises(InteractionFinalizing):
            manager._require_chat_admission(("user", "luotianyi"))
        with pytest.raises(InteractionFinalizing):
            await manager._claim_call(
                user_id="user",
                character_id="luotianyi",
                source_interaction_id=None,
                client_request_id="blocked-new-call",
            )
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await manager.begin_user_data_reset("user")

        summary_calls = llm.modules["luotianyi_call_summary"].calls
        assert len(summary_calls) == 1
        rendered = repr(summary_calls[0]["completed_turns"])
        assert "maintained working prefix" in rendered
        assert "uncompressed tail user" in rendered
        assert "uncompressed tail agent" in rendered
        assert "seed history must stay out" not in rendered
        assert order.index("maintenance") < order.index("summary") < order.index("sqlite-write-start")

        write_release.set()
        await manager._finalizations.close()
        order.append("finalizing-release")

        assert len(created) == 1
        assert close_count == 1
        assert order.index("sqlite-write-end") < order.index("context-close-start")
        assert order.index("context-close-end") < order.index("finalizing-release")
        with pytest.raises(RuntimeError):
            context.conversation.read_working()
        store = context.conversation._store
        assert store._snapshot.entries == ()
        assert store._snapshot.summary.text == ""
        assert store._base_snapshot.entries == ()
        assert manager._current_call_ownership(str(claim.prepared._record.call_id)) is None
        manager._require_chat_admission(("user", "luotianyi"))
        token = await manager.begin_user_data_reset("user")
        await manager.end_user_data_reset("user", token)

        persisted = database.call_sessions.find_by_id(claim.prepared._record.call_id)
        assert persisted.summary_status.value == "succeeded"
        assert persisted.maintenance_status.value == "succeeded"
        assert persisted.maintenance_turn_seq == 2
        with database.open_sql_session() as sql:
            row = sql.query(Conversation).filter_by(user_id="user", type="call").one()
            metadata = json.loads(row.meta_data)
            assert metadata["summary"] == working_during_write.summary.text
    finally:
        write_release.set()
        if stage is not None and stage.snapshot is None:
            await stage.close()
        await manager._finalizations.close()
        await manager.close()
        await runtime.shutdown()
        await database.shutdown()
