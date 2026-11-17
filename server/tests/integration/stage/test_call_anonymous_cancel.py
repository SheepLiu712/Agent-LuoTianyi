"""匿名取消仍能打断旧回复，并允许下一轮回答和记忆检索继续。"""

import asyncio
from uuid import uuid4

import pytest
from support.aliyun_realtime_speech import FakeAliyunWebSocket
from support.call_omni import _eventually, create_stage, factory, send_reply
from support.call_omni import call_setup as call_setup
from support.stage_lifecycle import finish_call

from src.domain.call.omni import MemoryLookupRequested, MemoryLookupResult, ReplyFinished, ReplySegment, ReplyStarted


async def cancel(socket):
    await socket.server_event(
        {
            "type": "response.done",
            "response": {"id": "", "status": "cancelled", "status_details": {"reason": "turn_detected"}},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("late", [False, True], ids=["before-next-reply", "after-next-reply"])
async def test_anonymous_interruption_stops_playback_and_next_reply_survives(call_setup, late):  # noqa: F811
    stage, socket, transport, _ = await create_stage(call_setup)

    def pcm(response):
        return [item for item in transport.items if isinstance(item, tuple) and item[:2] == ("pcm", response)]

    try:
        await send_reply(socket, text="旧回复。", done=False)
        await _eventually(lambda: pcm("r1-segment-0"))
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
        await _eventually(lambda: any(isinstance(item, tuple) and item[0] == "stop" for item in transport.items))
        for item in tuple(transport.items):
            if isinstance(item, tuple) and item[0] == "stop":
                for stream_id in item[2]:
                    stage.playback_stopped(item[1], stream_id)
        if not late:
            await cancel(socket)
        await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": "u2"})
        await socket.server_event({"type": "response.created", "response": {"id": "next"}})
        if late:
            await cancel(socket)
        await socket.server_event({"type": "response.text.delta", "response_id": "r1", "delta": "不应再播放。"})
        await socket.server_event({"type": "response.text.delta", "response_id": "next", "delta": "新的回答。"})
        await socket.server_event({"type": "response.done", "response": {"id": "next", "status": "completed"}})
        await _eventually(lambda: pcm("next-segment-0"))
        assert not pcm("r1-segment-1")
        assert not stage.termination_requested
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_turn", [False, True], ids=["sole-reply", "new-turn-before-local-cancel"])
async def test_anonymous_cancel_settles_generation_and_does_not_block_memory_reply(new_turn):
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    stream = session.events()
    try:
        await send_reply(socket, text="未完成", item_id=None, done=False)
        assert await asyncio.wait_for(anext(stream), 2) == ReplyStarted("r1", None)
        if new_turn:
            # 不消费 SpeechStarted、不调用 interrupt，模拟读取协程先收到取消回执。
            await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
        await cancel(socket)
        observed = []
        while not observed or not isinstance(observed[-1], ReplyFinished):
            observed.append(await asyncio.wait_for(anext(stream), 2))
        assert observed[-1] == ReplyFinished("r1")
        assert not any(isinstance(event, ReplySegment) for event in observed)
        await send_reply(socket, response_id="lookup", text="", item_id="question", done=False)
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "lookup",
                "call_id": "tool",
                "name": "lookup_call_memory",
                "arguments": '{"query":"偏好"}',
            }
        )
        while not isinstance(event := await asyncio.wait_for(anext(stream), 2), MemoryLookupRequested):
            pass
        await session.submit_tool_result(event.tool_call_id, MemoryLookupResult(()))
        await socket.server_event({"type": "response.done", "response": {"id": "lookup", "status": "completed"}})
        await _eventually(lambda: any(item["type"] == "response.create" for item in socket.sent))
        await send_reply(socket, response_id="answer", text="继续回答。", item_id=None)
        segments = []
        while (event := await asyncio.wait_for(anext(stream), 2)) != ReplyFinished("answer"):
            if isinstance(event, ReplySegment):
                segments.append(event.text)
        assert segments == ["继续回答。"]
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_ambiguous_anonymous_cancel_reports_candidates_without_guessing():
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        await send_reply(socket, response_id="old-one", item_id=None, text="", done=False)
        await send_reply(socket, response_id="old-two", item_id=None, text="", done=False)
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "new-input"})
        await cancel(socket)

        async def consume():
            async for _ in session.events():
                pass

        with pytest.raises(RuntimeError, match="receive failed") as caught:
            await asyncio.wait_for(consume(), 2)
        assert "Cannot correlate anonymous Qwen response" in str(caught.value.__cause__)
        assert "old-one" in str(caught.value.__cause__)
        assert "old-two" in str(caught.value.__cause__)
    finally:
        await session.close()
