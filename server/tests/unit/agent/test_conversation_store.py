"""Conversation Store 的持久化包装与呼叫内存窗口行为。"""

import asyncio
import threading
from datetime import datetime, timedelta

import pytest

from src.agent.context import (
    ContextIdentity,
    ConversationCompaction,
    ConversationContext,
    ConversationEntry,
    ConversationSnapshot,
    ConversationSummary,
    DatabaseConversationStore,
    EphemeralCallConversationStore,
    TextContent,
)


def entry(number: int) -> ConversationEntry:
    return ConversationEntry(
        str(number), datetime(2026, 10, 9) + timedelta(seconds=number), "user", TextContent(f"消息{number}")
    )


def compaction(entries: tuple[ConversationEntry, ...], covered: int = 1) -> ConversationCompaction:
    return ConversationCompaction(
        ConversationSummary(),
        tuple(item.entry_id for item in entries[:covered]),
        ConversationSummary("总结"),
    )


class Database:
    def __init__(self) -> None:
        self.appended = []
        self.compactions = []
        self.maintenance_progress = None

    def get_conversation_context_state(self, user_id, *, character_id):
        return {"summary": "", "conversations": [], "context_count": 0}

    def add_conversations(self, user_id, items, *, character_id):
        self.appended.append((user_id, items, character_id))
        return [item.uuid for item in items]

    def compact_conversation_context(self, user_id, summary, keep, *, expected_context_count, character_id):
        self.compactions.append((user_id, summary, keep, expected_context_count, character_id))
        return True

    def get_user_description(self, user_id):
        return ""

    def get_user_preferences(self, user_id):
        return {}

    def get_cognitive_maintenance_progress(self, user_id, *, character_id):
        return self.maintenance_progress

    def advance_cognitive_maintenance_progress(self, user_id, *, character_id, expected_entry_id, new_entry_id):
        if self.maintenance_progress != expected_entry_id:
            return False
        self.maintenance_progress = new_entry_id
        return True


def test_database_store_preserves_existing_storage_calls():
    database = Database()
    store = DatabaseConversationStore(database, ContextIdentity("luotianyi", "chat", "u"))
    first = entry(1)

    store.append((first,))
    assert database.appended[0][0] == "u"
    assert database.appended[0][1][0].uuid == "1"
    assert database.appended[0][2] == "luotianyi"


@pytest.mark.asyncio
async def test_call_context_only_updates_memory_and_never_calls_database():
    store = EphemeralCallConversationStore()
    context = ConversationContext(identity=ContextIdentity("luotianyi", "call", "u"), store=store)
    entries = (entry(2), entry(1))

    await context.append(entries)
    assert context.read().entries == (entry(1), entry(2))
    assert not hasattr(store, "_database")


@pytest.mark.asyncio
async def test_call_store_compacts_prefix_and_rejects_wrong_basis_without_mutating_window():
    entries = (entry(1), entry(2), entry(3))
    context = ConversationContext(
        identity=ContextIdentity("luotianyi", "call", "u"), store=EphemeralCallConversationStore()
    )
    await context.append(entries)

    with pytest.raises(ValueError):
        await context.compact(ConversationCompaction(ConversationSummary(), ("2",), ConversationSummary("错误总结")))
    assert context.read().entries == entries

    await context.compact(compaction(entries, covered=2))
    assert context.read().summary == ConversationSummary("总结")
    assert context.read().entries == (entry(3),)


@pytest.mark.asyncio
async def test_interaction_close_clears_ephemeral_store_even_through_external_reference():
    from src.agent.context import InteractionContext

    database = Database()
    store = EphemeralCallConversationStore()
    context = InteractionContext(
        identity=ContextIdentity("luotianyi", "call", "u"), database=database, conversation_store=store
    )
    await context.conversation.append((entry(1),))

    await context.close()

    assert store.load()[0] == ConversationSnapshot()


def test_database_store_close_is_noop_for_persisted_facts():
    database = Database()
    store = DatabaseConversationStore(database, ContextIdentity("luotianyi", "chat", "u"))
    store.close()
    store.append((entry(1),))
    assert len(database.appended) == 1


@pytest.mark.asyncio
async def test_database_context_delegates_maintenance_progress_within_its_operation_lock():
    database = Database()
    context = ConversationContext(identity=ContextIdentity("luotianyi", "chat", "u"), database=database)

    assert await context.read_maintenance_progress() is None
    assert await context.advance_maintenance_progress(expected_entry_id=None, new_entry_id="1") is True
    assert await context.read_maintenance_progress() == "1"
    assert await context.advance_maintenance_progress(expected_entry_id=None, new_entry_id="2") is False


@pytest.mark.asyncio
async def test_ephemeral_store_does_not_fake_conversation_maintenance_progress():
    context = ConversationContext(
        identity=ContextIdentity("luotianyi", "call", "u"), store=EphemeralCallConversationStore()
    )

    with pytest.raises(NotImplementedError):
        await context.read_maintenance_progress()
    with pytest.raises(NotImplementedError):
        await context.advance_maintenance_progress(expected_entry_id=None, new_entry_id="1")


@pytest.mark.asyncio
async def test_cancelled_maintenance_commit_waits_for_atomic_store_completion():
    class BlockingStore(EphemeralCallConversationStore):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.proceed = threading.Event()
            self.committed = False

        def commit_cognitive_maintenance(self, **kwargs):
            self.started.set()
            assert self.proceed.wait(5)
            self.committed = True
            return True

    store = BlockingStore()
    context = ConversationContext(identity=ContextIdentity("luotianyi", "chat", "u"), store=store)
    task = asyncio.create_task(
        context.commit_cognitive_maintenance(compaction=None, expected_progress=None, new_progress="1")
    )
    assert await asyncio.to_thread(store.started.wait, 5)
    task.cancel()
    assert not task.done()
    store.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.committed is True


@pytest.mark.asyncio
async def test_anonymous_empty_append_preserves_require_user_invariant():
    context = ConversationContext(
        identity=ContextIdentity("luotianyi", "world", None),
        database=Database(),
    )

    with pytest.raises(ValueError, match="无用户"):
        await context.append(())
