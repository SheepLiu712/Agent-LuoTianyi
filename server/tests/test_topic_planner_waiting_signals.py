import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.chat_pipeline.topic_planner import TopicPlanner
from src.domain.chat import ChatInputEvent, ChatInputEventType, ExtractedTopic


def _planner() -> TopicPlanner:
    return TopicPlanner({}, username="test", user_id="user-1")


async def _begin_extraction(planner: TopicPlanner):
    await planner.feed_unread_message(
        ChatInputEvent(
            event_type=ChatInputEventType.USER_TEXT,
            text="上一句还没说完",
            payload={},
            client_msg_id="msg-1",
        )
    )
    snapshot = await planner.unread_store.snapshot()
    await planner.listen_timer.remove_deadline()
    planner._extraction_in_progress = True
    return snapshot


def _extracted_topic(snapshot) -> ExtractedTopic:
    return ExtractedTopic(
        topic_id="topic-1",
        source_messages=snapshot.messages,
        topic_content="上一句还没说完",
        memory_attempts=[],
        fact_constraints=[],
        sing_attempts=[],
    )


@pytest.mark.asyncio
async def test_typing_during_topic_extraction_discards_result_and_restarts_waiting():
    planner = _planner()
    snapshot = await _begin_extraction(planner)

    await planner._handle_user_typing(
        ChatInputEvent(
            event_type=ChatInputEventType.USER_TYPING,
            payload={"text_length": 4},
            client_msg_id="typing-1",
        )
    )
    committed = await planner._commit_extraction_result(
        snapshot=snapshot,
        extracted_topics=[_extracted_topic(snapshot)],
        remaining_unread=[],
    )

    assert committed == []
    assert await planner.unread_store.has_unread() is True
    assert (await planner.listen_timer.deadline) is not None
    assert planner.unread_store.unread_messages[0].content == "上一句还没说完"


@pytest.mark.asyncio
async def test_image_selecting_during_topic_extraction_discards_result_and_restarts_waiting():
    planner = _planner()
    snapshot = await _begin_extraction(planner)

    await planner._handle_user_image_selecting(
        ChatInputEvent(
            event_type=ChatInputEventType.USER_IMAGE_SELECTING,
            payload={},
            client_msg_id="selecting-1",
        )
    )
    committed = await planner._commit_extraction_result(
        snapshot=snapshot,
        extracted_topics=[_extracted_topic(snapshot)],
        remaining_unread=[],
    )

    assert committed == []
    assert await planner.unread_store.has_unread() is True
    assert (await planner.listen_timer.deadline) is not None
    assert planner.unread_store.unread_messages[0].content == "上一句还没说完"
