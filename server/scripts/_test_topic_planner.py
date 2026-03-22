import asyncio

from src.pipeline.chat_events import ChatInputEvent, ChatInputEventType
from src.pipeline.topic_planner import TopicPlanner


async def main():
    planner = TopicPlanner(username="test", user_id="u1")
    captured = []

    async def consumer(topics):
        captured.extend(topics)

    planner.set_topic_consumer(consumer)
    planner.start_processing()

    # 不完整输入：先进入等待
    await planner.feed_unread_message(
        ChatInputEvent(event_type=ChatInputEventType.USER_TEXT, text="我想", client_msg_id="m1")
    )
    await asyncio.sleep(0.3)

    # typing 重置计时
    await planner.feed_unread_message(
        ChatInputEvent(event_type=ChatInputEventType.USER_TYPING)
    )

    # 补全输入
    await planner.feed_unread_message(
        ChatInputEvent(event_type=ChatInputEventType.USER_TEXT, text="问你个问题？", client_msg_id="m2")
    )

    await asyncio.sleep(2.3)

    if planner.processor_task and not planner.processor_task.done():
        planner.processor_task.cancel()
        try:
            await planner.processor_task
        except asyncio.CancelledError:
            pass

    print("captured_topics", len(captured))
    if captured:
        t = captured[0]
        print("first_topic_type", t.topic_type)
        print("source_count", len(t.source_message_ids))


if __name__ == "__main__":
    asyncio.run(main())
