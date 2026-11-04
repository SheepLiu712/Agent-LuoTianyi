"""交互上下文的数据库边界、并发释放与刺激归属。"""

import asyncio
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.retrieval import stub_retrieval

from src.agent.context import (
    ContextFactory,
    ConversationCompaction,
    ConversationEntry,
    ConversationMode,
    ConversationSnapshot,
    ConversationSummary,
    ImageContent,
    JargonExplanation,
    RecalledMemoryContext,
    RecallEntry,
    SongContent,
    TextContent,
    UserPreferences,
    UserProfile,
)
from src.domain.stage.lifecycle import StageEndReason
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import Base, User


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'context.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(uuid="u", username="user", password="unused", description="画像"))
        session.commit()
    cache = RedisBuffer()
    store = UserStore({}, sessions, cache)
    service = ConversationService(sql_session_factory=sessions, redis_buffer=cache, user_store=store)
    yield service
    engine.dispose()


def factory(database, **kwargs):
    return ContextFactory(character_id="luotianyi", database=database, **kwargs)


def entry(number, content=None):
    return ConversationEntry(
        str(number),
        datetime(2026, 9, 7) + timedelta(seconds=number),
        "user",
        content or TextContent(f"消息{number}", ("关键词",)),
    )


@pytest.mark.asyncio
async def test_factory_creates_independent_contexts_without_registry(database):
    contexts = factory(database)
    a, b = await asyncio.gather(
        contexts.create("i", mode=ConversationMode.CHAT, user_id="u"),
        contexts.create("i", mode=ConversationMode.CHAT, user_id="u"),
    )
    assert a is not b
    assert a.user.read().profile == UserProfile("画像")
    assert a.recalled_memory.read() == ()
    assert not any(hasattr(contexts, name) for name in ("get", "find", "release", "_contexts"))
    await a.close()
    assert b.user.read().profile == UserProfile("画像")
    await b.close()


@pytest.mark.asyncio
async def test_failed_initialization_does_not_cache_partial_context(database, monkeypatch):
    contexts = factory(database)
    original = database.get_conversation_context_state

    def fail(*args, **kwargs):
        raise RuntimeError("load failed")

    monkeypatch.setattr(database, "get_conversation_context_state", fail)
    with pytest.raises(RuntimeError):
        await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    monkeypatch.setattr(database, "get_conversation_context_state", original)
    restored = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    assert restored.user.read().profile == UserProfile("画像")


@pytest.mark.asyncio
async def test_userless_context_never_accesses_database(database, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("world interaction accessed user database")

    monkeypatch.setattr(database, "get_user_description", forbidden)
    monkeypatch.setattr(database, "get_conversation_context_state", forbidden)
    context = await factory(database).create("world", mode=ConversationMode.CHAT, user_id=None)
    assert context.conversation.read().entries == ()
    with pytest.raises(ValueError):
        await context.user.update_profile(UserProfile("不应写入"))
    with pytest.raises(ValueError):
        await context.conversation.append((entry(1),))


@pytest.mark.asyncio
async def test_profile_preferences_persist_without_overwriting_each_other(database, monkeypatch):
    database.save_user_preferences("u", {"future_field": "保留"})
    contexts = factory(database)
    context = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    await context.user.update_profile(UserProfile("新画像"))
    preferences = UserPreferences(relationship="朋友", personality_traits=("耐心",))
    await context.user.update_preferences(preferences)
    assert context.user.read().profile.description == "新画像"
    assert database.get_user_preferences("u")["future_field"] == "保留"
    await context.close()
    restored = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    assert restored.user.read().preferences == preferences
    assert restored.user.read().profile.description == "新画像"
    monkeypatch.setattr(database, "save_user_preferences", lambda *args: False)
    with pytest.raises(RuntimeError):
        await restored.user.update_preferences(UserPreferences(relationship="失败"))
    assert restored.user.read().preferences == preferences
    assert database.get_user_preferences("u")["relationship"] == "朋友"


@pytest.mark.asyncio
async def test_profile_write_failure_keeps_memory(database, monkeypatch):
    context = await factory(database).create("i", mode=ConversationMode.CHAT, user_id="u")
    monkeypatch.setattr(database, "update_user_description", lambda *args: False)
    with pytest.raises(RuntimeError):
        await context.user.update_profile(UserProfile("失败"))
    assert context.user.read().profile.description == "画像"


@pytest.mark.asyncio
async def test_history_round_trip_and_character_isolation(database):
    contexts = factory(database)
    context = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    entries = (
        entry(1),
        entry(2, ImageContent("图片", "client", "server", "image/png", ("树",))),
        entry(3, SongContent("唱歌", "歌曲", "副歌")),
    )
    await context.conversation.append(entries)
    assert context.conversation.read().entries == entries
    await context.close()
    # 清空缓存后从 SQL 重新构建，覆盖数据库 JSON 和缓存 JSON 两种格式。
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    assert restored.conversation.read().entries == entries
    other = await ContextFactory(character_id="miku", database=database).create(
        "i", mode=ConversationMode.CHAT, user_id="u"
    )
    assert other.conversation.read().entries == ()


@pytest.mark.asyncio
async def test_call_factory_uses_read_only_seed_and_ephemeral_working_copy(database):
    contexts = factory(database)
    chat = await contexts.create("chat", mode=ConversationMode.CHAT, user_id="u")
    recent = ConversationEntry(
        "recent",
        datetime(2026, 10, 10, 12, 0),
        "user",
        TextContent("通话前内容"),
    )
    await chat.conversation.append((recent,))
    before = database.get_conversation_context_state("u", character_id="luotianyi")

    call = await contexts.create(
        "call",
        mode=ConversationMode.CALL,
        user_id="u",
        requested_at=datetime(2026, 10, 10, 12, 2),
    )
    assert call.user.read().profile == UserProfile("画像")
    assert call.conversation.read().entries == (recent,)

    local = ConversationEntry("local", datetime(2026, 10, 10, 12, 2, 1), "agent", TextContent("通话内回复"))
    await call.conversation.append((local,))
    assert database.get_conversation_context_state("u", character_id="luotianyi") == before

    store = call.conversation._store
    await call.close()
    assert store.load()[0] == ConversationSnapshot()
    with pytest.raises(RuntimeError):
        call.conversation.read()


@pytest.mark.asyncio
async def test_conversation_read_orders_parallel_appends_by_fact_time(database):
    contexts = factory(database)
    context = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    earlier = entry(1, ImageContent("", mime_type="image/png", media_id="image"))
    later = entry(2)

    await context.conversation.append((later,))
    await context.conversation.append((earlier,))

    assert context.conversation.read().entries == (earlier, later)
    assert [item.content for item in database.get_history_from_db("u", 0, 2)] == [
        earlier.content.text,
        later.content.text,
    ]
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.create("restored", mode=ConversationMode.CHAT, user_id="u")
    assert restored.conversation.read().entries == (earlier, later)


def compaction_for(snapshot, covered=1, text="新的总结"):
    return ConversationCompaction(
        snapshot.summary, tuple(e.entry_id for e in snapshot.entries[:covered]), ConversationSummary(text)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [0, 1])
async def test_compact_preserves_history_and_uncovered_entries(database, keep):
    contexts = factory(database)
    context = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    entries = tuple(entry(i) for i in range(3))
    await context.conversation.append(entries)
    result = compaction_for(context.conversation.read(), 3 - keep)
    assert await context.conversation.compact(result) is None
    assert context.conversation.read().entries == (entries[-keep:] if keep else ())
    assert context.conversation.read().summary == result.summary
    assert len(database.get_history_from_db("u", 0, 10, "luotianyi")) == 3
    await context.close()
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    assert restored.conversation.read().summary == result.summary
    assert restored.conversation.read().entries == (entries[-keep:] if keep else ())


@pytest.mark.asyncio
async def test_append_after_external_snapshot_is_preserved(database):
    context = await factory(database).create("i", mode=ConversationMode.CHAT, user_id="u")
    await context.conversation.append((entry(1), entry(2)))
    result = compaction_for(context.conversation.read())
    await context.conversation.append((entry(3),))
    await context.conversation.compact(result)
    assert [e.entry_id for e in context.conversation.read().entries] == ["2", "3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [("2",), ("2", "1"), ("1", "missing"), ("1", "2", "3")])
async def test_compaction_rejects_non_prefix_records(database, ids):
    context = await factory(database).create("i", mode=ConversationMode.CHAT, user_id="u")
    await context.conversation.append((entry(1), entry(2)))
    before = context.conversation.read()
    result = ConversationCompaction(before.summary, ids, ConversationSummary("总结"))
    with pytest.raises(ValueError):
        await context.conversation.compact(result)
    assert context.conversation.read() == before
    assert database.get_conversation_context_state("u")["summary"] == ""


@pytest.mark.asyncio
async def test_compaction_rejects_changed_summary_from_another_interaction(database):
    contexts = factory(database)
    a = await contexts.create("a", mode=ConversationMode.CHAT, user_id="u")
    await a.conversation.append((entry(1), entry(2)))
    stale = ConversationCompaction(ConversationSummary(), ("2",), ConversationSummary("过时总结"))
    b = await contexts.create("b", mode=ConversationMode.CHAT, user_id="u")
    await b.conversation.compact(compaction_for(b.conversation.read()))
    with pytest.raises(ValueError):
        await a.conversation.compact(stale)
    assert database.get_conversation_context_state("u")["summary"] == "新的总结"


@pytest.mark.asyncio
async def test_none_is_handled_by_caller_and_is_not_a_compaction(database):
    context = await factory(database).create("i", mode=ConversationMode.CHAT, user_id="u")
    with pytest.raises(TypeError):
        await context.conversation.compact(None)
    assert context.conversation.read().entries == ()


@pytest.mark.parametrize("ids,text", [((), "总结"), (("1", "1"), "总结"), (("",), "总结"), (("1",), " ")])
def test_compaction_requires_complete_result(ids, text):
    with pytest.raises(ValueError):
        ConversationCompaction(ConversationSummary(), ids, ConversationSummary(text))


def test_recall_stimulus_cleanup_and_generic_removal():
    recall = RecalledMemoryContext()
    a = RecallEntry("a", "text-a", JargonExplanation("关键词", "解释"))
    b = RecallEntry("b", "text-b", JargonExplanation("另一个", "解释"))
    recall.append((a, b))
    recall.remove_by_stimulus_id("text-a")
    assert recall.read() == (b,)
    recalled = RecallEntry("retrieved", "countdown", JargonExplanation("检索", "结果"))
    recall.remove_by_stimulus_id("text-b")
    recall.append((recalled,))
    recall.remove_by_stimulus_id("countdown")
    assert recall.read() == ()
    recall.append((a, b))
    recall.remove(frozenset({"a", "missing"}))
    assert recall.read() == (b,)
    recall.clear()
    assert recall.read() == ()


@pytest.mark.asyncio
async def test_release_closes_existing_references_and_isolates_interactions(database):
    contexts = factory(database)
    a = await contexts.create("a", mode=ConversationMode.CHAT, user_id="u")
    b = await contexts.create("b", mode=ConversationMode.CHAT, user_id="u")
    a.recalled_memory.append((RecallEntry("r", "s", JargonExplanation("词", "解释")),))
    assert b.recalled_memory.read() == ()
    await a.close()
    await a.close()
    with pytest.raises(RuntimeError):
        a.recalled_memory.clear()
    with pytest.raises(RuntimeError):
        await a.user.update_profile(UserProfile())
    assert b.user.read().profile.description == "画像"


@pytest.mark.asyncio
async def test_cancellation_waits_for_write_and_memory_sync(database, monkeypatch):
    contexts = factory(database)
    context = await contexts.create("i", mode=ConversationMode.CHAT, user_id="u")
    started, proceed = threading.Event(), threading.Event()
    original = database.update_user_description

    def write(*args):
        started.set()
        assert proceed.wait(5)
        return original(*args)

    monkeypatch.setattr(database, "update_user_description", write)
    task = asyncio.create_task(context.user.update_profile(UserProfile("完成写入")))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    assert not task.done()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert context.user.read().profile.description == database.get_user_description("u") == "完成写入"


def test_database_profile_update_reports_missing_user(database):
    assert database.update_user_description("missing", "画像") is False
    assert database.update_user_description("u", "更新") is True


@pytest.mark.asyncio
async def test_cancelled_creation_waits_and_closes_unclaimed_context(database, monkeypatch):
    from src.agent.context import InteractionContext

    started, proceed = threading.Event(), threading.Event()
    original = database.get_user_description
    closed = []
    close = InteractionContext.close

    async def record_close(self):
        closed.append(self)
        await close(self)

    def load(*args):
        started.set()
        assert proceed.wait(5)
        return original(*args)

    monkeypatch.setattr(database, "get_user_description", load)
    monkeypatch.setattr(InteractionContext, "close", record_close)
    task = asyncio.create_task(factory(database).create("i", mode=ConversationMode.CHAT, user_id="u"))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(closed) == 1
    with pytest.raises(RuntimeError):
        closed[0].recalled_memory.read()


@pytest.mark.asyncio
async def test_failed_append_and_failed_summary_save_preserve_window(database, monkeypatch):
    context = await factory(database).create("i", mode=ConversationMode.CHAT, user_id="u")
    await context.conversation.append((entry(1),))
    before = context.conversation.read()
    monkeypatch.setattr(database, "add_conversations", lambda *args, **kwargs: [])
    with pytest.raises(RuntimeError):
        await context.conversation.append((entry(2),))
    assert context.conversation.read() == before
    monkeypatch.setattr(database, "compact_conversation_context", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError):
        await context.conversation.compact(compaction_for(before))
    assert context.conversation.read() == before


def test_recall_duplicate_batch_is_rejected_without_partial_append():
    recall = RecalledMemoryContext()
    a = RecallEntry("a", "text", JargonExplanation("词", "解释"))
    b = RecallEntry("b", "text", JargonExplanation("词", "解释"))
    recall.append((a,))
    with pytest.raises(ValueError):
        recall.append((b, a))
    assert recall.read() == (a,)


@pytest.mark.asyncio
async def test_real_stage_owns_and_closes_loaded_context(database):
    import src.domain.agent as d
    from src.adapter.websocket.chat import WebSocketAdapter
    from src.agent import Agent
    from src.agent.handlers.action.router import ActionRouter
    from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
    from src.agent.handlers.stimulus.router import StimulusRouter
    from src.stage import ChatStage

    class Maintenance:
        async def realize(self, action, execution_context, outputs):
            return d.ActionResult(
                action_id=action.action_id,
                status=d.ActionExecutionStatus.COMPLETED,
                error_code=None,
                irreversible_effect_committed=False,
                effect_ref=None,
            )

    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter([(d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler())]),
        action_router=ActionRouter([(d.ActionKind.COGNITIVE_MAINTENANCE, Maintenance())]),
    )
    stage = await ChatStage.create(
        user_id="u",
        character_id="luotianyi",
        agent=agent,
        output_sink=WebSocketAdapter(),
        context_factory=factory(database),
    )
    await stage.start()
    context = stage.context
    assert context.identity.interaction_id == stage.interaction_id
    assert context.user.read().profile == UserProfile("画像")
    result = await stage.terminate(StageEndReason.IDLE_TIMEOUT)
    assert result.finalization_error is None and result.cleanup_error is None
    with pytest.raises(RuntimeError):
        context.user.read()
    assert database.get_user_description("u") == "画像"


@pytest.mark.asyncio
async def test_same_user_call_windows_are_independent_and_close_preserves_chat(database):
    contexts = factory(database)
    chat = await contexts.create("chat", mode=ConversationMode.CHAT, user_id="u")
    seed = ConversationEntry("e1", datetime(2026, 10, 10, 12), "user", TextContent("persisted chat"))
    await chat.conversation.append((seed,))
    calls = await asyncio.gather(
        *(
            contexts.create(name, mode=ConversationMode.CALL, user_id="u", requested_at=datetime(2026, 10, 10, 12, 1))
            for name in ("call-a", "call-b")
        )
    )
    a, b = calls
    local = ConversationEntry("c1", datetime(2026, 10, 10, 12, 1), "user", TextContent("private call"))
    await a.conversation.append((local,))
    # 聊天种子只用于理解上下文，不能作为本次通话的压缩前缀。
    with pytest.raises(ValueError, match="压缩依据与当前对话上下文不匹配"):
        await a.conversation.compact(
            ConversationCompaction(ConversationSummary(), ("e1",), ConversationSummary("invalid summary"))
        )
    assert a.conversation.read() == ConversationSnapshot(entries=(seed, local))
    assert a.conversation.read_working() == ConversationSnapshot(entries=(local,))
    await a.conversation.compact(
        ConversationCompaction(ConversationSummary(), ("c1",), ConversationSummary("local summary"))
    )
    assert a.conversation.read() == ConversationSnapshot(ConversationSummary("local summary"), (seed,))
    assert a.conversation.read_working() == ConversationSnapshot(ConversationSummary("local summary"), ())
    assert b.conversation.read() == ConversationSnapshot(entries=(seed,))
    await a.close()
    assert b.conversation.read() == ConversationSnapshot(entries=(seed,))
    await b.close()
    await chat.close()
    restored = await contexts.create("restored", mode=ConversationMode.CHAT, user_id="u")
    assert restored.conversation.read() == ConversationSnapshot(entries=(seed,))
    await restored.close()


@pytest.mark.asyncio
async def test_context_owns_call_memory_and_close_rejects_late_recall(database):
    from types import SimpleNamespace

    from src.agent.context.memory_pool import CallMemory

    contexts = factory(database)
    first = await contexts.create("a", mode=ConversationMode.CALL, user_id="u", requested_at=datetime(2026, 10, 10))
    second = await contexts.create("b", mode=ConversationMode.CALL, user_id="u", requested_at=datetime(2026, 10, 10))
    pool = first.call_memory
    pool.remember(CallMemory("one", "private memory"))
    assert second.call_memory.snapshot() == ()
    entered, release = asyncio.Event(), asyncio.Event()

    class Memory:
        async def search_memory_context_for_topic(self, user_id, queries):
            entered.set()
            await release.wait()
            return SimpleNamespace(hits=(SimpleNamespace(rendered_text="late", memory_record_id="late"),))

    skill = stub_retrieval({"luotianyi": Memory()})

    async def retrieve():
        result = await skill.search(
            SimpleNamespace(character_id="luotianyi", require_user_id=lambda: "u"),
            query=SimpleNamespace(clues=("query",)),
        )
        pool.remember_hits(result.hits)

    recall = asyncio.create_task(retrieve())
    await entered.wait()
    await first.close()
    await first.close()
    release.set()
    with pytest.raises(RuntimeError):
        await recall
    with pytest.raises(RuntimeError):
        pool.snapshot()
    assert not pool._items
    assert second.call_memory.snapshot() == ()
    await second.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_fails", [False, True])
async def test_cancelled_call_restores_same_chat_with_committed_history(database, monkeypatch, caplog, refresh_fails):
    """初始化挂断：先回复协议，迟到资源关闭后恢复原聊天及其最新历史。"""
    import json

    from support.call_session_repository import InMemoryCallSessionRepository
    from support.chat_connection import StubChatConnection
    from support.realtime_speech import FakeRealtimeSpeechSessionFactory
    from support.stage_manager import make_call_adapter, make_stage_manager

    from src.adapter.websocket.chat import WebSocketAdapter
    from src.domain.call import CallContent, CallOutcome
    from src.domain.stage.lifecycle import StageEndReason, StageLifecycleState, StageStartAborted
    from src.utils.logger import get_logger
    from tests.integration.stage.test_call_stage import _eventually
    from tests.integration.stage.test_chat_stage import Socket
    from tests.integration.stage.test_proactive_due_dispatch import DueEvents, event
    from tests.integration.websocket.test_call_websocket_adapter import start_message

    class LateSpeech(FakeRealtimeSpeechSessionFactory):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()
            self.cancelled = asyncio.Event()

        async def create(self, call_id):
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                await self.release.wait()
            return await super().create(call_id)

    speech = LateSpeech()
    chat_adapter = WebSocketAdapter()
    contexts = factory(database)
    agent, generation_calls = _reminder_agent()
    due_events = DueEvents((event("after-cancel"),))
    stages = make_stage_manager(
        adapter=chat_adapter,
        get_agent=lambda _: agent,
        get_context_factory=lambda _: contexts,
        call_sessions=InMemoryCallSessionRepository(),
        conversation_service=database,
        realtime_speech_factory=speech,
        due_event_provider=due_events,
    )
    calls = make_call_adapter(manager=stages, enabled=True, supports_character=lambda _: True)
    connection = StubChatConnection(Socket(), "u", "device")
    chat = await chat_adapter._open(connection, "luotianyi")
    original_context = chat.context
    if refresh_fails:

        async def fail_refresh():
            raise OSError("conversation refresh unavailable")

        monkeypatch.setattr(original_context.conversation, "refresh", fail_refresh)
        monkeypatch.setattr(get_logger("src.stage.chat.chat_stage"), "propagate", True)
    await stages.prepare_call_transition(connection, character_id="luotianyi", client_request_id="cancel")
    handle = await calls.open(initial_message=start_message("cancel"), user_id="u", connection_id=object())
    first = await calls.next_output(handle)
    preparing = json.loads(first.message)
    calls.complete_output(handle, first.delivery_id)
    second = await calls.next_output(handle)
    assert preparing["state"] == "preparing" and json.loads(second.message)["ack_seq"] == 1
    calls.complete_output(handle, second.delivery_id)
    call = stages._call_stages[preparing["call_id"]]
    await asyncio.wait_for(speech.entered.wait(), 1)
    original_context.conversation.read()
    assert chat.input_suspended
    try:
        await asyncio.wait_for(
            calls.receive(
                handle,
                json.dumps(
                    {
                        "protocol": "call.v1",
                        "type": "call.hangup",
                        "call_id": call.call_id,
                        "seq": 2,
                        "reason": "user_hangup",
                    }
                ),
            ),
            1,
        )
        received = []
        while len(received) < 2:
            delivery = await asyncio.wait_for(calls.next_output(handle), 1)
            received.append(json.loads(delivery.message))
            calls.complete_output(handle, delivery.delivery_id)
        assert {item["type"] for item in received} == {"ack", "call.ended"}
        await _eventually(lambda: not calls._sessions)
        await asyncio.wait_for(speech.cancelled.wait(), 1)
        assert chat.input_suspended
        assert not await chat.dispatch_due_events(merge_all=True)
        assert not generation_calls
        speech.release.set()
        result = await asyncio.wait_for(call.terminate(StageEndReason.USER_REQUESTED), 2)
        assert result.resources_released
        with pytest.raises(StageStartAborted):
            await call.start()
        if refresh_fails:
            assert chat.lifecycle_state is StageLifecycleState.TERMINATED
            assert not await chat.dispatch_due_events(merge_all=True)
            assert not generation_calls
            assert "Chat rollback refresh failed" in caplog.text
            connection = StubChatConnection(Socket(), "u", "replacement")
            resumed = await chat_adapter._open(connection, "luotianyi")
            assert resumed is not chat
        else:
            resumed = chat
            assert resumed.context is original_context and not resumed.input_suspended
        contents = [entry.content for entry in resumed.context.conversation.read().entries]
        records = [content for content in contents if isinstance(content, CallContent)]
        assert len(records) == 1 and records[0].outcome is CallOutcome.CANCELLED_BEFORE_ANSWER
        assert await resumed.dispatch_due_events(merge_all=True)
        await _eventually(lambda: any(item["type"] == "agent_message" for item in connection.websocket.events))
        assert generation_calls["extract"]["conversation_history"].count(records[0].text) == 1
        assert generation_calls["replier"]["conversation_history"].count(records[0].text) == 1
        assert all(provider.closed for provider in speech.sessions.values())
        assert len(speech.sessions) == 1
    finally:
        speech.release.set()
        await calls.close()
        await stages.close()


def _reminder_agent():
    """真实提醒生成与交付链路，仅替换模型响应和语音输出。"""
    import src.domain.agent as d
    from src.agent import Agent
    from src.agent.handlers.action.router import ActionRouter
    from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
    from src.agent.handlers.stimulus.proactive import FirstLoginHandler
    from src.agent.handlers.stimulus.router import StimulusRouter
    from src.agent.processing.output_drafts import MessageEndDraft, TextFinalDraft
    from tests.integration.agent.test_topic_reply_pipeline import pipeline
    from tests.support.call_stage_failure_harness import NoOutputActionHandler, action_result

    class TextOutput:
        async def realize(self, action, context, outputs):
            await outputs.emit(TextFinalDraft(delivery=action.delivery, text=action.content))
            await outputs.emit(
                MessageEndDraft(delivery=action.delivery, status=d.MessageEndStatus.COMPLETED, error_code=None)
            )
            return action_result(action)

    composition, _, calls = pipeline(attempts=(), queries=())
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [
                (
                    d.StimulusKind.PROACTIVE_PROMPT_DUE,
                    FirstLoginHandler(prepared_names=(), prepared_speech=None, skills=composition),
                ),
                (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
            ]
        ),
        action_router=ActionRouter(
            [
                (d.ActionKind.SAY, TextOutput()),
                (d.ActionKind.COGNITIVE_MAINTENANCE, NoOutputActionHandler()),
            ]
        ),
    )
    return agent, calls
