"""交互上下文的数据库边界、并发释放与刺激归属。"""

import asyncio
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.context import (
    ContextFactory, ConversationCompaction, ConversationEntry, ConversationSummary,
    ImageContent, JargonExplanation, RecallEntry, RecalledMemoryContext,
    SongContent, TextContent, UserPreferences, UserProfile,
)
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
    return ConversationEntry(str(number), datetime(2026, 9, 7) + timedelta(seconds=number),
                             "user", content or TextContent(f"消息{number}", ("关键词",)))


@pytest.mark.asyncio
async def test_factory_creates_independent_contexts_without_registry(database):
    contexts = factory(database)
    a, b = await asyncio.gather(contexts.create("i", user_id="u"), contexts.create("i", user_id="u"))
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
        await contexts.create("i", user_id="u")
    monkeypatch.setattr(database, "get_conversation_context_state", original)
    restored = await contexts.create("i", user_id="u")
    assert restored.user.read().profile == UserProfile("画像")


@pytest.mark.asyncio
async def test_userless_context_never_accesses_database(database, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("world interaction accessed user database")
    monkeypatch.setattr(database, "get_user_description", forbidden)
    monkeypatch.setattr(database, "get_conversation_context_state", forbidden)
    context = await factory(database).create("world", user_id=None)
    assert context.conversation.read().entries == ()
    with pytest.raises(ValueError):
        await context.user.update_profile(UserProfile("不应写入"))
    with pytest.raises(ValueError):
        await context.conversation.append((entry(1),))


@pytest.mark.asyncio
async def test_profile_preferences_persist_without_overwriting_each_other(database, monkeypatch):
    database.save_user_preferences("u", {"future_field": "保留"})
    contexts = factory(database)
    context = await contexts.create("i", user_id="u")
    await context.user.update_profile(UserProfile("新画像"))
    preferences = UserPreferences(relationship="朋友", personality_traits=("耐心",))
    await context.user.update_preferences(preferences)
    assert context.user.read().profile.description == "新画像"
    assert database.get_user_preferences("u")["future_field"] == "保留"
    await context.close()
    restored = await contexts.create("i", user_id="u")
    assert restored.user.read().preferences == preferences
    assert restored.user.read().profile.description == "新画像"
    monkeypatch.setattr(database, "save_user_preferences", lambda *args: False)
    with pytest.raises(RuntimeError):
        await restored.user.update_preferences(UserPreferences(relationship="失败"))
    assert restored.user.read().preferences == preferences
    assert database.get_user_preferences("u")["relationship"] == "朋友"


@pytest.mark.asyncio
async def test_profile_write_failure_keeps_memory(database, monkeypatch):
    context = await factory(database).create("i", user_id="u")
    monkeypatch.setattr(database, "update_user_description", lambda *args: False)
    with pytest.raises(RuntimeError):
        await context.user.update_profile(UserProfile("失败"))
    assert context.user.read().profile.description == "画像"


@pytest.mark.asyncio
async def test_history_round_trip_and_character_isolation(database):
    contexts = factory(database)
    context = await contexts.create("i", user_id="u")
    entries = (entry(1), entry(2, ImageContent("图片", "client", "server", "image/png", ("树",))),
               entry(3, SongContent("唱歌", "歌曲", "副歌")))
    await context.conversation.append(entries)
    assert context.conversation.read().entries == entries
    await context.close()
    # 清空缓存后从 SQL 重新构建，覆盖数据库 JSON 和缓存 JSON 两种格式。
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.create("i", user_id="u")
    assert restored.conversation.read().entries == entries
    other = await ContextFactory(character_id="miku", database=database).create("i", user_id="u")
    assert other.conversation.read().entries == ()


@pytest.mark.asyncio
async def test_conversation_read_orders_parallel_appends_by_fact_time(database):
    contexts = factory(database)
    context = await contexts.create("i", user_id="u")
    earlier = entry(1, ImageContent("", mime_type="image/png", media_id="image"))
    later = entry(2)

    await context.conversation.append((later,))
    await context.conversation.append((earlier,))

    assert context.conversation.read().entries == (earlier, later)
    assert [item.content for item in database.get_history_from_db("u", 0, 2)] == [
        earlier.content.text, later.content.text]
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.create("restored", user_id="u")
    assert restored.conversation.read().entries == (earlier, later)


def compaction_for(snapshot, covered=1, text="新的总结"):
    return ConversationCompaction(snapshot.summary,
                                 tuple(e.entry_id for e in snapshot.entries[:covered]),
                                 ConversationSummary(text))


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [0, 1])
async def test_compact_preserves_history_and_uncovered_entries(database, keep):
    contexts = factory(database)
    context = await contexts.create("i", user_id="u")
    entries = tuple(entry(i) for i in range(3))
    await context.conversation.append(entries)
    result = compaction_for(context.conversation.read(), 3 - keep)
    assert await context.conversation.compact(result) is None
    assert context.conversation.read().entries == (entries[-keep:] if keep else ())
    assert context.conversation.read().summary == result.summary
    assert len(database.get_history_from_db("u", 0, 10, "luotianyi")) == 3
    await context.close()
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.create("i", user_id="u")
    assert restored.conversation.read().summary == result.summary
    assert restored.conversation.read().entries == (entries[-keep:] if keep else ())


@pytest.mark.asyncio
async def test_append_after_external_snapshot_is_preserved(database):
    context = await factory(database).create("i", user_id="u")
    await context.conversation.append((entry(1), entry(2)))
    result = compaction_for(context.conversation.read())
    await context.conversation.append((entry(3),))
    await context.conversation.compact(result)
    assert [e.entry_id for e in context.conversation.read().entries] == ["2", "3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [("2",), ("2", "1"), ("1", "missing"), ("1", "2", "3")])
async def test_compaction_rejects_non_prefix_records(database, ids):
    context = await factory(database).create("i", user_id="u")
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
    a = await contexts.create("a", user_id="u")
    await a.conversation.append((entry(1), entry(2)))
    stale = ConversationCompaction(ConversationSummary(), ("2",), ConversationSummary("过时总结"))
    b = await contexts.create("b", user_id="u")
    await b.conversation.compact(compaction_for(b.conversation.read()))
    with pytest.raises(ValueError):
        await a.conversation.compact(stale)
    assert database.get_conversation_context_state("u")["summary"] == "新的总结"


@pytest.mark.asyncio
async def test_none_is_handled_by_caller_and_is_not_a_compaction(database):
    context = await factory(database).create("i", user_id="u")
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
    a = await contexts.create("a", user_id="u")
    b = await contexts.create("b", user_id="u")
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
    context = await contexts.create("i", user_id="u")
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
    task = asyncio.create_task(factory(database).create("i", user_id="u"))
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
    context = await factory(database).create("i", user_id="u")
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
    from src.agent import Agent
    from src.stage import ChatStage
    from src.adapter.websocket import WebSocketAdapter
    from src.agent.handlers.stimulus.router import StimulusRouter
    from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler())]))
    stage = await ChatStage.create(user_id="u", character_id="luotianyi", agent=agent,
        adapter=WebSocketAdapter(), context_factory=factory(database))
    context = stage.context
    assert context.identity.interaction_id == stage.interaction_id
    assert context.user.read().profile == UserProfile("画像")
    result = await stage.terminate(d.InteractionEndingReason.USER_LEFT)
    assert result.error is None
    with pytest.raises(RuntimeError):
        context.user.read()
    assert database.get_user_description("u") == "画像"
