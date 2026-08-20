import asyncio
from types import SimpleNamespace

import pytest

from src.chat_session.chat_pipeline.chat_stream import ChatStream
from src.chat_session.chat_pipeline.ingress_helper import IngressHelper
from src.chat_session.chat_pipeline.reflection_worker import ReflectionWorker
from src.chat_session.chat_pipeline.topic_replier import TopicReplier
from src.chat_session.chat_pipeline.unread_store import UnreadStore
from src.domain.chat import ChatInputEvent, ChatInputEventType, UnreadMessage


class FakeConnection:
    user_name = "alice"
    user_uuid = "user-1"
    websocket = None


def _event(index: int) -> ChatInputEvent:
    return ChatInputEvent(
        event_type=ChatInputEventType.USER_TEXT,
        text=f"message-{index}",
        client_msg_id=f"msg-{index}",
    )


def test_ingress_queue_rejects_above_configured_capacity():
    helper = IngressHelper(
        {"queue_maxsize": 2},
        username="alice",
        user_id="user-1",
    )

    assert helper.put_nowait(_event(1)) is True
    assert helper.put_nowait(_event(2)) is True
    assert helper.put_nowait(_event(3)) is False
    assert helper.ingress_queue.qsize() == 2


def test_all_pipeline_queues_have_configured_bounds():
    stream = ChatStream(
        {
            "response_queue_maxsize": 7,
            "ingress_helper": {"queue_maxsize": 3},
            "topic_planner": {"unread_store": {"maxsize": 4}},
            "topic_replier": {"queue_maxsize": 5},
            "reflection_worker": {"queue_maxsize": 6},
        },
        FakeConnection(),
    )

    assert stream.ingress_helper.ingress_queue.maxsize == 3
    assert stream.topic_planner.unread_store.maxsize == 4
    assert stream.topic_replier.topic_queue.maxsize == 5
    assert stream.reflection_worker.reflection_queue.maxsize == 6
    assert stream.response_queue.maxsize == 7


def test_standalone_internal_workers_use_bounded_defaults():
    topic_replier = TopicReplier({}, "alice", "user-1")
    reflection_worker = ReflectionWorker({}, "alice", "user-1")

    assert topic_replier.topic_queue.maxsize == 64
    assert reflection_worker.reflection_queue.maxsize == 64


@pytest.mark.asyncio
async def test_unread_snapshot_keeps_capacity_until_commit():
    store = UnreadStore({"maxsize": 2}, "alice", "user-1")
    first = UnreadMessage("msg-1", "text", "one")
    second = UnreadMessage("msg-2", "text", "two")
    third = UnreadMessage("msg-3", "text", "three")
    await store.append(first)
    await store.append(second)

    snapshot = await store.snapshot()
    blocked_append = asyncio.create_task(store.append(third))
    await asyncio.sleep(0)

    assert blocked_append.done() is False
    assert await store.pending_count() == 2

    await store.update_unread_message(snapshot, [second])
    await asyncio.wait_for(blocked_append, timeout=0.5)

    assert await store.pending_count() == 2


@pytest.mark.asyncio
async def test_full_unread_store_blocks_worker_until_ingress_rejects():
    store = UnreadStore({"maxsize": 1}, "alice", "user-1")
    await store.append(UnreadMessage("existing", "text", "existing"))
    consumer_started = asyncio.Event()

    async def consume(event):
        consumer_started.set()
        await store.append(UnreadMessage(event.client_msg_id, "text", event.text or ""))

    class FakeAgentRuntime:
        async def try_handle_reflex(self, **_kwargs):
            return False

    helper = IngressHelper({"queue_maxsize": 1}, "alice", "user-1")
    helper.set_system_runtime(SimpleNamespace(agent_runtime=FakeAgentRuntime()))
    helper.set_msg_consumer(consume)
    helper.send_reply_callback = lambda _response: None
    helper.start_processing()
    held = ChatInputEvent(ChatInputEventType.SYSTEM_EVENT, "held", client_msg_id="held")
    queued = ChatInputEvent(ChatInputEventType.SYSTEM_EVENT, "queued", client_msg_id="queued")
    rejected = ChatInputEvent(ChatInputEventType.SYSTEM_EVENT, "rejected", client_msg_id="rejected")

    try:
        assert helper.put_nowait(held) is True
        await asyncio.wait_for(consumer_started.wait(), timeout=0.5)
        assert helper.put_nowait(queued) is True
        assert helper.put_nowait(rejected) is False
    finally:
        await store.clear()
        helper.ingress_worker_task.cancel()
        await asyncio.gather(helper.ingress_worker_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_reflection_topic_callback_is_awaited():
    callback_started = asyncio.Event()
    release_callback = asyncio.Event()

    async def callback(_topic):
        callback_started.set()
        await release_callback.wait()

    worker = ReflectionWorker({}, "alice", "user-1", reply_topic_callback=callback)
    dispatch = asyncio.create_task(worker._safe_reply_topic(object()))
    await asyncio.wait_for(callback_started.wait(), timeout=0.5)

    assert dispatch.done() is False

    release_callback.set()
    await asyncio.wait_for(dispatch, timeout=0.5)
