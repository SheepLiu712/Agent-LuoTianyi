"""真实 SAY 路由、语音技能及异步 TTS 适配的离线测试。"""

import asyncio
import threading
from contextlib import aclosing
from dataclasses import replace
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent_runtime.agent_runtime import AgentRuntime
from src.agent.skills.expression.speaking import SpeakingSkill, EmptySpeechError
from src.capabilities.speech.streaming import AsyncTTS
from src.capabilities.speech.stream_errors import TTSStreamCancelled
from routing_support import Sink, plan_and_context


class Module:
    def __init__(self, chunks=(b"wav-header", b"pcm-data"), error=None):
        self.chunks = chunks
        self.error = error
        self.calls = []
        self.closed = threading.Event()

    def stream_synthesize_speech_with_tone(self, text, tone, *, cancel_event):
        self.calls.append((text, tone, threading.get_ident()))
        try:
            yield from self.chunks
            if self.error:
                raise self.error
        finally:
            self.closed.set()


def speaking(module):
    return SpeakingSkill({}, AsyncTTS(SimpleNamespace(tts_module={"luotianyi": module})))


def say_plan():
    plan, context = plan_and_context()
    say = replace(plan.actions[0], content="显示文字", sound_content="朗读文字",
                  expression=d.ChangeExpression(expression_id="happy"))
    return replace(plan, actions=(say,)), context


@pytest.mark.asyncio
async def test_production_say_route_outputs_expression_audio_and_end_without_restore(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    module = Module()
    kwargs["capability_manager"].speech.tts_module["luotianyi"] = module
    runtime = AgentRuntime(**kwargs)
    try:
        sink = Sink()
        plan, context = say_plan()
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.status is d.ExecutionStatus.COMPLETED
        assert [o.kind for o in sink.values] == [d.AgentOutputKind.TEXT_FINAL, d.AgentOutputKind.EXPRESSION,
            d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.MESSAGE_END]
        assert sink.values[0].text == "显示文字"
        assert sink.values[1].expression.expression_id == "happy"
        assert sink.values[-1].status is d.MessageEndStatus.COMPLETED
        assert [o.sequence_no for o in sink.values] == list(range(5))
        assert all(o.action_id == plan.actions[0].action_id for o in sink.values)
        assert sink.values[2].data == b"wav-header"
        assert sink.values[2].framing is d.AudioFraming.FILE_FRAGMENT
        assert module.calls[0][:2] == ("朗读文字", "normal")
        assert module.calls[0][2] != threading.get_ident()
        assert module.closed.is_set()
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks,error,code,audio_code", [
    ((), None, d.ExecutionErrorCode.AUDIO_EMPTY, d.AudioErrorCode.EMPTY_AUDIO),
    ((b"first",), RuntimeError("failed"), d.ExecutionErrorCode.AUDIO_GENERATION_FAILED, d.AudioErrorCode.GENERATION_FAILED),
    ((), TimeoutError("timeout"), d.ExecutionErrorCode.PROVIDER_TIMEOUT, d.AudioErrorCode.GENERATION_FAILED),
])
async def test_say_generation_failure_ends_message_and_stops_plan(runtime_dependencies, chunks, error, code, audio_code):
    kwargs, _ = runtime_dependencies
    module = Module(chunks, error)
    kwargs["capability_manager"].speech.tts_module["luotianyi"] = module
    runtime = AgentRuntime(**kwargs)
    try:
        plan, context = say_plan()
        plan = replace(plan, actions=(*plan.actions, replace(plan.actions[0], action_id="later")))
        sink = Sink()
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.error_code is code
        assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
        assert sink.values[-1].status is d.MessageEndStatus.FAILED
        assert sink.values[-1].error_code is audio_code
        assert len(module.calls) == 1
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_sink_failure_closes_stream_without_more_output(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    module = Module()
    kwargs["capability_manager"].speech.tts_module["luotianyi"] = module
    runtime = AgentRuntime(**kwargs)
    class FailedSink(Sink):
        async def emit(self, value):
            if isinstance(value, d.AudioChunkOutput):
                raise RuntimeError("sink failed")
            return await super().emit(value)
    try:
        plan, context = say_plan()
        sink = FailedSink()
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.status is d.ExecutionStatus.FAILED
        assert len(sink.values) == 2
        assert module.closed.is_set()
    finally:
        await runtime.shutdown()


class BlockingModule(Module):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()

    def stream_synthesize_speech_with_tone(self, text, tone, *, cancel_event):
        self.started.set()
        try:
            assert cancel_event.wait(5)
            raise TTSStreamCancelled()
            yield b"unused"
        finally:
            self.closed.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_cancel", [False, True])
async def test_waiting_tts_can_be_cancelled_without_blocking_loop(task_cancel):
    module = BlockingModule()
    skill = speaking(module)
    token = d.CancellationToken()
    async def consume():
        async with aclosing(skill.speak(character_id="luotianyi", text="文字", tone=d.Tone(value="normal"),
                                        cancellation=token)) as stream:
            return [chunk async for chunk in stream]
    task = asyncio.create_task(consume())
    assert await asyncio.to_thread(module.started.wait, 2)
    if task_cancel:
        task.cancel()
        expected = asyncio.CancelledError
    else:
        token.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        expected = TTSStreamCancelled
    with pytest.raises(expected):
        await asyncio.wait_for(task, 2)
    assert module.closed.is_set()


@pytest.mark.asyncio
async def test_early_close_does_not_prefetch_remaining_audio():
    produced = []
    class Counting(Module):
        def stream_synthesize_speech_with_tone(self, text, tone, *, cancel_event):
            try:
                for i in range(10):
                    produced.append(i)
                    yield bytes([i])
            finally:
                self.closed.set()
    module = Counting()
    async with aclosing(speaking(module).speak(character_id="luotianyi", text="文字", tone=d.Tone(value="normal"),
                                              cancellation=d.CancellationToken())) as stream:
        await anext(stream)
        await asyncio.sleep(0.05)
        assert produced == [0]
    assert module.closed.is_set()


@pytest.mark.asyncio
async def test_shared_skill_selects_character_voice():
    a, b = Module((b"a",)), Module((b"b",))
    skill = SpeakingSkill({}, AsyncTTS(SimpleNamespace(tts_module={"a": a, "b": b})))
    async def collect(character):
        return [chunk.data async for chunk in skill.speak(character_id=character, text=character,
                   tone=d.Tone(value="normal"), cancellation=d.CancellationToken())]
    assert await asyncio.gather(collect("a"), collect("b")) == [[b"a"], [b"b"]]


@pytest.mark.asyncio
async def test_text_only_say_is_rejected_before_output(runtime):
    plan, context = say_plan()
    plan = replace(plan, actions=(replace(plan.actions[0], sound_content=None),))
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.error_code is d.ExecutionErrorCode.UNSUPPORTED_ACTION
    assert sink.values == []


@pytest.mark.asyncio
async def test_server_request_cancellation_releases_lock_and_active_request():
    from queue import Queue
    from src.capabilities.speech.tts_server import TTSServer
    server = object.__new__(TTSServer)
    server.server_process = SimpleNamespace(is_alive=lambda: True)
    server.request_queue = Queue()
    server.response_queue = Queue()
    server._synthesize_lock = threading.Lock()
    server._request_counter = 0
    server._stopping = False
    server.stop_event = threading.Event()
    active = []
    server._begin_request = lambda: active.append("start")
    server._end_request = lambda: active.append("end")
    class ServerModule:
        def stream_synthesize_speech_with_tone(self, text, tone, *, cancel_event):
            return server.stream_synthesize(text, "ref", "ref", "prompt", cancel_event=cancel_event)
    module = ServerModule()
    token = d.CancellationToken()
    async def consume():
        return [chunk async for chunk in speaking(module).speak(character_id="luotianyi", text="文字",
                           tone=d.Tone(value="normal"), cancellation=token)]
    task = asyncio.create_task(consume())
    request = await asyncio.to_thread(server.request_queue.get, True, 2)
    token.cancel(d.CancellationReason.NO_LONGER_NEEDED)
    with pytest.raises(TTSStreamCancelled):
        await asyncio.wait_for(task, 2)
    assert active == ["start", "end"]
    assert server._synthesize_lock.acquire(blocking=False)
    server._synthesize_lock.release()
    assert not server.stop_event.is_set()
    # 旧请求的晚到响应不交给新请求。
    server.logger = SimpleNamespace(warning=lambda *args: None)
    server.response_queue.put({"request_id": request["request_id"], "ok": True, "audio_bytes": b"old"})
    server.response_queue.put({"request_id": "req-2", "ok": True, "audio_bytes": b"new", "is_final": True})
    output = [chunk async for chunk in speaking(module).speak(character_id="luotianyi", text="新文字",
                         tone=d.Tone(value="normal"), cancellation=d.CancellationToken())]
    assert [chunk.data for chunk in output] == [b"new"]
    assert active == ["start", "end", "start", "end"]


@pytest.mark.asyncio
async def test_server_stream_lock_wait_is_cancellable():
    from src.capabilities.speech.tts_server import TTSServer
    server = object.__new__(TTSServer)
    server._synthesize_lock = threading.Lock()
    server._stopping = False
    server._synthesize_lock.acquire()
    stop = threading.Event()
    def acquire():
        with server._stream_lock(stop):
            pytest.fail("取消请求不应取得繁忙引擎")
    task = asyncio.create_task(asyncio.to_thread(acquire))
    stop.set()
    try:
        with pytest.raises(TTSStreamCancelled):
            await asyncio.wait_for(task, 2)
    finally:
        server._synthesize_lock.release()


@pytest.fixture
def prepared_manifest(tmp_path):
    import json
    import wave
    audio = tmp_path / "voice.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 100)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"name": "voice", "audio_path": "voice.wav", "text": "资源文字",
                                    "expression": ""}]), encoding="utf-8")
    return manifest, audio


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery,text,expression", [
    (d.OutputDelivery.CONVERSATION, "计划文字", "happy"),
    (d.OutputDelivery.CONVERSATION, "", None),
    (d.OutputDelivery.EPHEMERAL_REACTION, "不会显示", "happy"),
    (d.OutputDelivery.EPHEMERAL_REACTION, "", None),
])
async def test_prepared_say_delivery_and_complete_file(runtime_dependencies, prepared_manifest,
                                                      delivery, text, expression):
    kwargs, _ = runtime_dependencies
    manifest, audio = prepared_manifest
    kwargs["config"]["prepared_speech"] = {"manifest": str(manifest)}
    module = Module()
    kwargs["capability_manager"].speech.tts_module["luotianyi"] = module
    runtime = AgentRuntime(**kwargs)
    try:
        plan, context = say_plan()
        action = replace(plan.actions[0], content=text, sound_content=None,
                         prepared_audio_ref=d.MediaRef(media_id="voice"), delivery=delivery,
                         expression=d.ChangeExpression(expression_id=expression) if expression else None)
        plan = replace(plan, actions=(action,))
        sink = Sink()
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.status is d.ExecutionStatus.COMPLETED
        expected = []
        if delivery is d.OutputDelivery.CONVERSATION and text:
            expected.append(d.AgentOutputKind.TEXT_FINAL)
            assert sink.values[0].text == text
        if expression:
            expected.append(d.AgentOutputKind.EXPRESSION)
        expected.extend([d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.MESSAGE_END])
        assert [out.kind for out in sink.values] == expected
        assert all(out.delivery is delivery for out in sink.values)
        assert sink.values[-2].data == audio.read_bytes()
        assert sink.values[-2].framing is d.AudioFraming.COMPLETE_FILE
        assert sink.values[-1].status is d.MessageEndStatus.COMPLETED
        assert module.calls == []
        assert [out.sequence_no for out in sink.values] == list(range(len(expected)))
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["deleted", "empty", "corrupt", "unknown"])
async def test_prepared_audio_is_read_at_execution_and_fails_before_output(runtime_dependencies, prepared_manifest, failure):
    kwargs, _ = runtime_dependencies
    manifest, audio = prepared_manifest
    kwargs["config"]["prepared_speech"] = {"manifest": str(manifest)}
    runtime = AgentRuntime(**kwargs)
    try:
        if failure == "deleted":
            audio.unlink()
        elif failure == "empty":
            audio.write_bytes(b"")
        elif failure == "corrupt":
            audio.write_bytes(b"not a wav")
        plan, context = say_plan()
        action = replace(plan.actions[0], sound_content=None,
                         prepared_audio_ref=d.MediaRef(media_id="unknown" if failure == "unknown" else "voice"))
        sink = Sink()
        report = await runtime.get_agent().realize_action_plan(replace(plan, actions=(action,)), context, sink)
        assert report.error_code is (d.ExecutionErrorCode.AUDIO_EMPTY if failure == "empty"
                                     else d.ExecutionErrorCode.AUDIO_GENERATION_FAILED)
        assert sink.values == []
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_tts_ephemeral_delivery_suppresses_text_and_preserves_terminal_flag(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    kwargs["capability_manager"].speech.tts_module["luotianyi"] = Module()
    runtime = AgentRuntime(**kwargs)
    try:
        plan, context = say_plan()
        plan = replace(plan, actions=(replace(plan.actions[0], delivery=d.OutputDelivery.EPHEMERAL_REACTION),))
        sink = Sink()
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.status is d.ExecutionStatus.COMPLETED
        assert not any(isinstance(out, d.TextFinalOutput) for out in sink.values)
        assert all(out.delivery is d.OutputDelivery.EPHEMERAL_REACTION for out in sink.values)
        assert isinstance(sink.values[-1], d.MessageEndOutput)
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_prepared_read_cancellation_stops_all_delivery(runtime_dependencies, prepared_manifest, monkeypatch):
    kwargs, _ = runtime_dependencies
    manifest, _ = prepared_manifest
    kwargs["config"]["prepared_speech"] = {"manifest": str(manifest)}
    runtime = AgentRuntime(**kwargs)
    started, proceed = threading.Event(), threading.Event()
    read = runtime.prepared_speech._read_audio
    def delayed(name):
        started.set()
        assert proceed.wait(3)
        return read(name)
    monkeypatch.setattr(runtime.prepared_speech, "_read_audio", delayed)
    try:
        plan, context = say_plan()
        plan = replace(plan, actions=(replace(plan.actions[0], sound_content=None,
                        prepared_audio_ref=d.MediaRef(media_id="voice")),))
        sink = Sink()
        task = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, sink))
        assert await asyncio.to_thread(started.wait, 2)
        context.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        proceed.set()
        report = await task
        assert report.status is d.ExecutionStatus.CANCELLED
        assert sink.values == []
    finally:
        proceed.set()
        await runtime.shutdown()
