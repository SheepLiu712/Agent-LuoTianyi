"""通话 ContextFactory 的显式时间、Store 选择、锁和取消边界。"""

import asyncio
import threading
from datetime import datetime, timezone

import pytest

from src.agent.context import ContextFactory, ConversationEntry, ConversationSnapshot, TextContent, UserPreferences
from src.agent.context.conversation_store import EphemeralCallConversationStore


class Database:
    def __init__(self) -> None:
        self.seed_calls = []
        self.chat_loads = 0
        self.writes = 0
        self.started = threading.Event()
        self.proceed = threading.Event()
        self.block_seed = False

    def get_user_description(self, user_id):
        return "画像"

    def get_user_preferences(self, user_id):
        return {"relationship": "朋友"}

    def get_conversation_context_state(self, user_id, *, character_id):
        self.chat_loads += 1
        return {"summary": "", "conversations": [], "context_count": 0}

    def get_call_conversation_seed_state(self, user_id, *, character_id, requested_at):
        self.seed_calls.append((user_id, character_id, requested_at))
        self.started.set()
        if self.block_seed:
            assert self.proceed.wait(5)
        return {
            "summary": "旧总结",
            "conversations": [
                {
                    "uuid": "b",
                    "timestamp": "2026-10-10 12:00:02.000000",
                    "source": "agent",
                    "type": "text",
                    "content": "后",
                    "meta_data": None,
                },
                {
                    "uuid": "a",
                    "timestamp": "2026-10-10 12:00:01.000000",
                    "source": "user",
                    "type": "text",
                    "content": "前",
                    "meta_data": None,
                },
            ],
        }

    def add_conversations(self, *args, **kwargs):
        self.writes += 1
        raise AssertionError("通话上下文不得写正式对话")

    def compact_conversation_context(self, *args, **kwargs):
        self.writes += 1
        raise AssertionError("通话上下文不得写正式总结")


def factory(database):
    return ContextFactory(character_id="luotianyi", database=database)


@pytest.mark.asyncio
async def test_create_call_passes_explicit_time_loads_profile_and_uses_ephemeral_store():
    database = Database()
    requested_at = datetime(2026, 10, 10, 12, 3)
    context = await factory(database).create_call("call", user_id="u", requested_at=requested_at)

    assert database.seed_calls == [("u", "luotianyi", requested_at)]
    assert database.chat_loads == 0
    assert context.user.read().profile.description == "画像"
    assert context.user.read().preferences == UserPreferences(relationship="朋友")
    assert [item.entry_id for item in context.conversation.read().entries] == ["a", "b"]

    extra = ConversationEntry("c", datetime(2026, 10, 10, 12, 0, 3), "user", TextContent("新内容"))
    await context.conversation.append((extra,))
    assert database.writes == 0
    with pytest.raises(NotImplementedError):
        await context.conversation.read_maintenance_progress()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "requested_at", "error"),
    [
        ("", datetime(2026, 10, 10), ValueError),
        ("u", "2026-10-10", ValueError),
        ("u", datetime(2026, 10, 10, tzinfo=timezone.utc), ValueError),
    ],
)
async def test_create_call_requires_user_and_naive_server_time(user_id, requested_at, error):
    with pytest.raises(error):
        await factory(Database()).create_call("call", user_id=user_id, requested_at=requested_at)


@pytest.mark.asyncio
async def test_create_call_close_clears_store_and_public_context_references():
    context = await factory(Database()).create_call("call", user_id="u", requested_at=datetime(2026, 10, 10, 12, 3))
    store = context.conversation._store
    await context.close()

    assert store.load()[0] == ConversationSnapshot()
    with pytest.raises(RuntimeError):
        context.conversation.read()
    with pytest.raises(RuntimeError):
        context.user.read()


@pytest.mark.asyncio
async def test_create_call_cancellation_waits_for_read_and_closes_unclaimed_context(monkeypatch):
    from src.agent.context import InteractionContext

    database = Database()
    database.block_seed = True
    closed = []
    original_close = InteractionContext.close

    async def record_close(self):
        closed.append(self)
        await original_close(self)

    monkeypatch.setattr(InteractionContext, "close", record_close)
    task = asyncio.create_task(
        factory(database).create_call("call", user_id="u", requested_at=datetime(2026, 10, 10, 12, 3))
    )
    assert await asyncio.to_thread(database.started.wait, 5)
    task.cancel()
    assert not task.done()
    database.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(closed) == 1
    with pytest.raises(RuntimeError):
        closed[0].conversation.read()


@pytest.mark.asyncio
async def test_same_user_reads_serialize_while_different_users_can_load_independently():
    class BlockingDatabase(Database):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_by_user = {}
            self.all_entered = threading.Event()
            self.release = threading.Event()
            self.guard = threading.Lock()

        def get_call_conversation_seed_state(self, user_id, *, character_id, requested_at):
            with self.guard:
                self.active += 1
                self.max_by_user[user_id] = max(self.max_by_user.get(user_id, 0), self.active)
                if self.active >= 2:
                    self.all_entered.set()
            assert self.release.wait(5)
            with self.guard:
                self.active -= 1
            return {"summary": "", "conversations": []}

    database = BlockingDatabase()
    contexts = factory(database)
    different = [
        asyncio.create_task(contexts.create_call("a", user_id="u1", requested_at=datetime(2026, 10, 10))),
        asyncio.create_task(contexts.create_call("b", user_id="u2", requested_at=datetime(2026, 10, 10))),
    ]
    assert await asyncio.to_thread(database.all_entered.wait, 5)
    database.release.set()
    await asyncio.gather(*different)

    database.release.clear()
    database.all_entered.clear()
    same = [
        asyncio.create_task(contexts.create_call("c", user_id="u", requested_at=datetime(2026, 10, 10))),
        asyncio.create_task(contexts.create_call("d", user_id="u", requested_at=datetime(2026, 10, 10))),
    ]
    await asyncio.sleep(0.05)
    assert database.active == 1
    database.release.set()
    await asyncio.gather(*same)


@pytest.mark.asyncio
async def test_unknown_or_future_seed_state_becomes_whole_empty_snapshot():
    database = Database()
    database.get_call_conversation_seed_state = lambda *args, **kwargs: {
        "summary": None,
        "conversations": [
            {
                "uuid": "future",
                "timestamp": "2026-10-11 00:00:00",
                "source": "user",
                "type": "text",
                "content": "不应部分加载",
                "meta_data": None,
            }
        ],
    }
    context = await factory(database).create_call("call", user_id="u", requested_at=datetime(2026, 10, 10, 12, 3))
    assert context.conversation.read() == ConversationSnapshot()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_read", ["profile", "preferences"])
async def test_create_call_closes_unclaimed_ephemeral_store_when_user_loading_fails(monkeypatch, failing_read):
    import src.agent.context.context_factory as context_factory_module

    class FailingDatabase(Database):
        def get_user_description(self, user_id):
            if failing_read == "profile":
                raise RuntimeError("profile failed")
            return super().get_user_description(user_id)

        def get_user_preferences(self, user_id):
            if failing_read == "preferences":
                raise RuntimeError("preferences failed")
            return super().get_user_preferences(user_id)

    stores = []

    def capture_store(seed):
        store = EphemeralCallConversationStore(seed)
        stores.append(store)
        return store

    monkeypatch.setattr(context_factory_module, "EphemeralCallConversationStore", capture_store)

    with pytest.raises(RuntimeError, match=failing_read):
        await factory(FailingDatabase()).create_call("call", user_id="u", requested_at=datetime(2026, 10, 10, 12, 3))

    assert len(stores) == 1
    assert stores[0].load()[0] == ConversationSnapshot()


@pytest.mark.asyncio
async def test_chat_create_keeps_database_store_behavior():
    database = Database()
    await factory(database).create("chat", user_id="u")
    assert database.chat_loads == 1
    assert database.seed_calls == []
