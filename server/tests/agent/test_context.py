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
from src.system.database.redis_buffer import RedisBuffer
from src.system.database.services.conversation_service import ConversationService
from src.system.database.services.user_store import UserStore
from src.system.database.sql_database import Base, User


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
async def test_factory_initializes_once_and_rejects_rebinding(database, monkeypatch):
    contexts = factory(database)
    calls = []
    original = database.get_user_description
    monkeypatch.setattr(database, "get_user_description", lambda user: calls.append(user) or original(user))
    a, b = await asyncio.gather(contexts.get("i", user_id="u"), contexts.get("i", user_id="u"))
    assert a is b is contexts.find("i")
    assert calls == ["u"]
    assert a.user.read().profile == UserProfile("画像")
    assert a.recalled_memory.read() == ()
    with pytest.raises(ValueError):
        await contexts.get("i", user_id=None)


@pytest.mark.asyncio
async def test_failed_initialization_does_not_cache_partial_context(database, monkeypatch):
    contexts = factory(database)
    original = database.get_conversation_context_state
    def fail(*args, **kwargs):
        raise RuntimeError("load failed")
    monkeypatch.setattr(database, "get_conversation_context_state", fail)
    with pytest.raises(RuntimeError):
        await contexts.get("i", user_id="u")
    assert contexts.find("i") is None
    monkeypatch.setattr(database, "get_conversation_context_state", original)
    assert await contexts.get("i", user_id="u") is contexts.find("i")


@pytest.mark.asyncio
async def test_userless_context_never_accesses_database(database, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("world interaction accessed user database")
    monkeypatch.setattr(database, "get_user_description", forbidden)
    monkeypatch.setattr(database, "get_conversation_context_state", forbidden)
    context = await factory(database).get("world", user_id=None)
    assert context.conversation.read().entries == ()
    with pytest.raises(ValueError):
        await context.user.update_profile(UserProfile("不应写入"))
    with pytest.raises(ValueError):
        await context.conversation.append((entry(1),))


@pytest.mark.asyncio
async def test_profile_preferences_persist_without_overwriting_each_other(database, monkeypatch):
    database.save_user_preferences("u", {"future_field": "保留"})
    contexts = factory(database)
    context = await contexts.get("i", user_id="u")
    await context.user.update_profile(UserProfile("新画像"))
    preferences = UserPreferences(relationship="朋友", personality_traits=("耐心",))
    await context.user.update_preferences(preferences)
    assert context.user.read().profile.description == "新画像"
    assert database.get_user_preferences("u")["future_field"] == "保留"
    await contexts.release("i")
    restored = await contexts.get("i", user_id="u")
    assert restored.user.read().preferences == preferences
    assert restored.user.read().profile.description == "新画像"
    monkeypatch.setattr(database, "save_user_preferences", lambda *args: False)
    with pytest.raises(RuntimeError):
        await restored.user.update_preferences(UserPreferences(relationship="失败"))
    assert restored.user.read().preferences == preferences
    assert database.get_user_preferences("u")["relationship"] == "朋友"


@pytest.mark.asyncio
async def test_profile_write_failure_keeps_memory(database, monkeypatch):
    context = await factory(database).get("i", user_id="u")
    monkeypatch.setattr(database, "update_user_description", lambda *args: False)
    with pytest.raises(RuntimeError):
        await context.user.update_profile(UserProfile("失败"))
    assert context.user.read().profile.description == "画像"


@pytest.mark.asyncio
async def test_history_round_trip_and_character_isolation(database):
    contexts = factory(database)
    context = await contexts.get("i", user_id="u")
    entries = (entry(1), entry(2, ImageContent("图片", "client", "server", "image/png", ("树",))),
               entry(3, SongContent("唱歌", "歌曲", "副歌")))
    await context.conversation.append(entries)
    assert context.conversation.read().entries == entries
    await contexts.release("i")
    # 清空缓存后从 SQL 重新构建，覆盖数据库 JSON 和缓存 JSON 两种格式。
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.get("i", user_id="u")
    assert restored.conversation.read().entries == entries
    other = await ContextFactory(character_id="miku", database=database).get("i", user_id="u")
    assert other.conversation.read().entries == ()


def compaction_for(snapshot, covered=1, text="新的总结"):
    return ConversationCompaction(snapshot.summary,
                                 tuple(e.entry_id for e in snapshot.entries[:covered]),
                                 ConversationSummary(text))


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [0, 1])
async def test_compact_preserves_history_and_uncovered_entries(database, keep):
    contexts = factory(database)
    context = await contexts.get("i", user_id="u")
    entries = tuple(entry(i) for i in range(3))
    await context.conversation.append(entries)
    result = compaction_for(context.conversation.read(), 3 - keep)
    assert await context.conversation.compact(result) is None
    assert context.conversation.read().entries == (entries[-keep:] if keep else ())
    assert context.conversation.read().summary == result.summary
    assert len(database.get_history_from_db("u", 0, 10, "luotianyi")) == 3
    await contexts.release("i")
    database._redis.delete("user_context:u:luotianyi")
    restored = await contexts.get("i", user_id="u")
    assert restored.conversation.read().summary == result.summary
    assert restored.conversation.read().entries == (entries[-keep:] if keep else ())


@pytest.mark.asyncio
async def test_append_after_external_snapshot_is_preserved(database):
    context = await factory(database).get("i", user_id="u")
    await context.conversation.append((entry(1), entry(2)))
    result = compaction_for(context.conversation.read())
    await context.conversation.append((entry(3),))
    await context.conversation.compact(result)
    assert [e.entry_id for e in context.conversation.read().entries] == ["2", "3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [("2",), ("2", "1"), ("1", "missing"), ("1", "2", "3")])
async def test_compaction_rejects_non_prefix_records(database, ids):
    context = await factory(database).get("i", user_id="u")
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
    a = await contexts.get("a", user_id="u")
    await a.conversation.append((entry(1), entry(2)))
    stale = ConversationCompaction(ConversationSummary(), ("2",), ConversationSummary("过时总结"))
    b = await contexts.get("b", user_id="u")
    await b.conversation.compact(compaction_for(b.conversation.read()))
    with pytest.raises(ValueError):
        await a.conversation.compact(stale)
    assert database.get_conversation_context_state("u")["summary"] == "新的总结"


@pytest.mark.asyncio
async def test_none_is_handled_by_caller_and_is_not_a_compaction(database):
    context = await factory(database).get("i", user_id="u")
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
    a = await contexts.get("a", user_id="u")
    b = await contexts.get("b", user_id="u")
    a.recalled_memory.append((RecallEntry("r", "s", JargonExplanation("词", "解释")),))
    assert b.recalled_memory.read() == ()
    await contexts.release("a")
    await contexts.release("a")
    assert contexts.find("a") is None
    with pytest.raises(RuntimeError):
        a.recalled_memory.clear()
    with pytest.raises(RuntimeError):
        await a.user.update_profile(UserProfile())
    assert b.user.read().profile.description == "画像"


@pytest.mark.asyncio
async def test_cancellation_waits_for_write_and_memory_sync(database, monkeypatch):
    contexts = factory(database)
    context = await contexts.get("i", user_id="u")
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
async def test_release_waits_for_creation_even_if_get_is_cancelled(database, monkeypatch):
    started, proceed = threading.Event(), threading.Event()
    original = database.get_user_description
    def load(*args):
        started.set()
        assert proceed.wait(5)
        return original(*args)
    monkeypatch.setattr(database, "get_user_description", load)
    contexts = factory(database)
    get = asyncio.create_task(contexts.get("i", user_id="u"))
    assert await asyncio.to_thread(started.wait, 5)
    get.cancel()
    release = asyncio.create_task(contexts.release("i"))
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await get
    await asyncio.wait_for(release, 5)
    assert contexts.find("i") is None


@pytest.mark.asyncio
async def test_failed_append_and_failed_summary_save_preserve_window(database, monkeypatch):
    context = await factory(database).get("i", user_id="u")
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
