"""Persisted call facts remain usable by the next chat and call contexts."""

from datetime import datetime
from uuid import uuid4

import pytest
from support.context_support import database, factory  # noqa: F401

from src.agent.context import ConversationEntry, ConversationMode
from src.domain import ConversationItem
from src.domain.call import CallContent, CallEndReason, CallOutcome


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", list(CallOutcome))
async def test_settled_call_loads_in_new_chat_and_call_seed(database, outcome):  # noqa: F811
    now = datetime.now()
    content = CallContent(
        call_id=uuid4(),
        outcome=outcome,
        active_duration_ms=1234 if outcome is CallOutcome.CONNECTED else 0,
        summary="用户喜欢音乐" if outcome is CallOutcome.CONNECTED else None,
        end_reason=CallEndReason.USER_HANGUP,
    )
    item = ConversationItem(
        uuid=str(uuid4()),
        timestamp=now.isoformat(sep=" ", timespec="microseconds"),
        source="user",
        type="call",
        content=content.text,
        data={
            "call_id": str(content.call_id),
            "outcome": outcome.value,
            "active_duration_ms": content.active_duration_ms,
            "summary": content.summary,
            "end_reason": content.end_reason.value,
        },
    )
    database.add_call_conversation("u", "luotianyi", item)
    contexts = factory(database)
    chat = await contexts.create("next-chat", mode=ConversationMode.CHAT, user_id="u")
    assert chat.conversation.read().entries[0].content == content
    await chat.close()
    call = await contexts.create("next-call", mode=ConversationMode.CALL, user_id="u", requested_at=now)
    assert call.conversation.read().entries[0].content == content
    await call.close()


@pytest.mark.asyncio
async def test_call_content_round_trips_through_conversation_store(database):  # noqa: F811
    content = CallContent(uuid4(), CallOutcome.CONNECTED, 1000, "用户喜欢音乐", CallEndReason.USER_HANGUP)
    contexts = factory(database)
    chat = await contexts.create("chat", mode=ConversationMode.CHAT, user_id="u")
    entry = ConversationEntry(str(uuid4()), datetime.now(), "user", content)
    await chat.conversation.append((entry,))
    await chat.close()
    restored = await contexts.create("restored", mode=ConversationMode.CHAT, user_id="u")
    assert restored.conversation.read().entries == (entry,)
    await restored.close()
