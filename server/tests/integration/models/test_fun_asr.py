"""验证真实协议序列映射后的打断、句尾、故障和关闭行为。"""

import asyncio
import json
from uuid import uuid4

import pytest

from src.infrastructure.models.realtime_speech import (
    AliyunRealtimeSpeechSessionFactory,
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
    TurnInvalid,
)
from tests.support.aliyun_realtime_speech import FakeAliyunConnector, FakeAliyunWebSocket


class AsrSocket(FakeAliyunWebSocket):
    def __init__(self, *, finish=True):
        super().__init__()
        self.task_id = None
        self.finish = finish

    async def send(self, message):
        if isinstance(message, bytes):
            self.sent.append(message)
            return
        value = json.loads(message)
        self.sent.append(value)
        self.task_id = value["header"]["task_id"]
        action = value["header"]["action"]
        if action == "run-task":
            await self.event("task-started")
        elif action == "finish-task" and self.finish:
            await self.event("task-finished")

    async def event(self, kind, **payload):
        await self.server_event({"header": {"task_id": self.task_id, "event": kind}, "payload": payload})

    async def sentence(self, identity, text="", *, final=False, heartbeat=False):
        await self.event(
            "result-generated",
            output={
                "sentence": {
                    "sentence_id": identity,
                    "text": text,
                    "sentence_end": final,
                    "heartbeat": heartbeat,
                }
            },
        )


async def started(socket, **overrides):
    factory = AliyunRealtimeSpeechSessionFactory.from_mapping(
        {
            "enabled": True,
            "api_key": "test",
            "model": "fun-asr-realtime",
            "endpoint": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
            **overrides,
        },
        connector=FakeAliyunConnector(socket),
    )
    session = await factory.create(uuid4())
    await session.start(RealtimeSpeechConfig(language="zh"))
    return session


async def next_event(events):
    return await asyncio.wait_for(anext(events), 1)


@pytest.mark.asyncio
async def test_sentence_start_interrupts_once_and_final_delivers_once_across_silence():
    socket = AsrSocket()
    session = await started(socket)
    events = session.events()
    await socket.sentence(0, heartbeat=True)
    await socket.sentence(1)
    await socket.sentence(1, "你好")
    assert isinstance(await next_event(events), SpeechStarted)
    await socket.sentence(1, "你好啊")
    await socket.sentence(1, "你好。", final=True)
    stop = await next_event(events)
    turn = await next_event(events)
    assert isinstance(stop, SpeechStopped)
    assert isinstance(turn, TurnCompleted)
    assert turn.semantic.transcript == "你好。"
    assert turn.item_id == stop.item_id
    await socket.sentence(1, "你好。", final=True)
    await socket.sentence(2, "嗯")
    assert isinstance(await next_event(events), SpeechStarted)
    await socket.sentence(2, final=True)
    assert isinstance(await next_event(events), SpeechStopped)
    assert isinstance(await next_event(events), TurnInvalid)
    await session.close()
    await events.aclose()
    assert await session.wait_failure() is None
    assert [s["header"]["action"] for s in socket.sent] == ["run-task", "finish-task"]


@pytest.mark.asyncio
async def test_initial_silence_and_empty_sentences_emit_no_call_events():
    socket = AsrSocket()
    session = await started(socket)
    for identity in (1, 2):
        await socket.sentence(identity)
        await socket.sentence(identity, "  ")
        await socket.sentence(identity, final=True)
    await session.close()
    assert [event async for event in session.events()] == []
    assert await session.wait_failure() is None


@pytest.mark.asyncio
async def test_empty_sentence_then_real_speech_does_not_block_next_turn():
    socket = AsrSocket()
    session = await started(socket)
    await socket.sentence(1, final=True)
    await socket.sentence(2)
    await socket.sentence(2, "你好")
    await socket.sentence(2, "你好", final=True)
    await session.close()
    result = [event async for event in session.events()]
    assert [type(event) for event in result] == [SpeechStarted, SpeechStopped, TurnCompleted]
    assert result[-1].semantic.transcript == "你好"


@pytest.mark.asyncio
async def test_audio_is_binary_and_finish_flushes_tail_before_event_stream_ends():
    socket = AsrSocket(finish=False)
    session = await started(socket)
    await session.push_audio(AudioFrame(b"\0\0" * 160, "pcm_s16le", 16000, 1))
    closing = asyncio.create_task(session.close())
    for _ in range(100):
        if any(isinstance(s, dict) and s["header"]["action"] == "finish-task" for s in socket.sent):
            break
        await asyncio.sleep(0.001)
    await socket.sentence(1, "尾句", final=True)
    await socket.event("task-finished")
    await closing
    result = [e async for e in session.events()]
    assert [type(e) for e in result] == [SpeechStarted, SpeechStopped, TurnCompleted]
    assert result[-1].semantic.transcript == "尾句"
    assert isinstance(socket.sent[1], bytes)
    assert socket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["task-failed", "disconnect", "overflow"])
async def test_provider_failure_ends_call_even_without_event_consumer(failure):
    socket = AsrSocket()
    session = await started(socket, event_queue_size=1)
    if failure == "disconnect":
        await socket.abnormal_close()
    elif failure == "overflow":
        await socket.sentence(1, "你好", final=True)
    else:
        await socket.event("task-failed")
    result = await asyncio.wait_for(session.wait_failure(), 1)
    assert isinstance(result, ProviderFailed)
    with pytest.raises(RuntimeError):
        await session.push_audio(AudioFrame(b"\0\0", "pcm_s16le", 16000, 1))
    await session.close()


@pytest.mark.asyncio
async def test_finish_timeout_is_reported_and_releases_socket():
    socket = AsrSocket(finish=False)
    session = await started(socket, close_timeout_seconds=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await session.close()
    assert (await session.wait_failure()).error_code == "provider_finish_failed"
    assert socket.closed


@pytest.mark.asyncio
async def test_final_transcript_carries_audio_end_estimate_not_final_arrival_time(monkeypatch):
    from src.infrastructure.models.realtime_speech import fun_asr

    clock = [10.0]
    monkeypatch.setattr(fun_asr.time, "monotonic", lambda: clock[0])
    socket = AsrSocket()
    session = await started(socket)
    await session.push_audio(AudioFrame(bytes(3200), "pcm_s16le", 16000, 1))
    clock[0] = 10.1
    await session.push_audio(AudioFrame(bytes(3200), "pcm_s16le", 16000, 1))
    clock[0] = 11.0
    await socket.event(
        "result-generated",
        output={
            "sentence": {
                "sentence_id": 1,
                "sentence_end": True,
                "text": "你好",
                "end_time": 150,
            }
        },
    )
    await session.close()
    result = [e async for e in session.events()]
    final = result[-1]
    assert final.speech_ended_at == pytest.approx(10.05)
    assert final.recognized_at == 11.0
