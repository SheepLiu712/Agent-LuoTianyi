"""可观察的实时通话行为：单会话、流式朗读、插话、工具与挂断全文。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from support.aliyun_realtime_speech import FakeAliyunConnector, FakeAliyunWebSocket
from support.call_output import output_sink
from support.stage_lifecycle import finish_call, observe_release, wait_call_finished
from support.call_omni import (
    factory,
    send_reply,
    create_stage,
    Retrieval,
    _eventually,
    _receipt,
    call_setup,
)
import src.domain.agent as d
from src.agent.context import ContextFactory
from src.agent.facade import Agent
from src.agent.handlers.action.call_memory import LookupCallMemoryHandler
from src.agent.handlers.stimulus.call import (
    CallAnswerRequestedHandler,
    CallEndingHandler,
    CallMemoryLookupRequestedHandler,
    CallReplyConfirmedHandler,
    CallReplySegmentReadyHandler,
    CallTimeLimitWarningHandler,
    CallTurnCompletedHandler,
)
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.contracts import CharacterNarrative
from src.agent.skills.memory_retrieval import MemorySearchResult
from src.agent.skills.cognitive.call_settlement import render_call_turns
from src.domain import MemoryHit
from src.domain.call import CallState, CallEndReason
from src.domain.call.omni import (
    AudioFrame,
    InstructionText,
    MemoryLookupResult,
    MemoryLookupHit,
    MemoryLookupRequested,
    ReplyStarted,
    ReplySegment,
    ReplyFinished,
    TranscriptFinal,
)
from src.infrastructure.models.realtime_speech.config import AliyunRealtimeSpeechConfig
from src.infrastructure.models.realtime_speech.omni import QwenOmniSessionFactory
from src.stage.call.call_stage import CallStage


@pytest.mark.asyncio
@pytest.mark.parametrize("found", [False, True], ids=["empty", "known_fact"])
async def test_memory_action_returns_typed_value_without_presentation_outputs(call_setup, found):
    hits = (MemoryHit("用户喜欢音乐", 1.0, "偏好", source_record_id="memory-1"),) if found else ()
    stage, _, _, _ = await create_stage(call_setup, retrieval=Retrieval(hits))

    class RejectPresentation:
        async def emit(self, output):
            pytest.fail("记忆查询只能返回行动结果，不能提交呈现输出")

    try:
        action = d.LookupCallMemory(
            action_id="lookup", response_id="model-response", tool_call_id="tool", query="用户偏好"
        )
        plan = d.ActionPlan(
            plan_id="lookup-plan",
            origin_request_id="request",
            plan_ordinal=0,
            target_character_id=stage.character_id,
            interaction_id=stage.interaction_id,
            basis_interaction_revision=stage._revision,
            source_stimulus_ids=("lookup-request",),
            actions=(action,),
        )
        report = await stage._agent.realize_action_plan(
            plan,
            d.ExecutionContext(
                execution_id="lookup-execution",
                interaction_id=stage.interaction_id,
                current_interaction_revision=stage._revision,
                cancellation=d.CancellationToken(),
                interaction_context=stage.context,
            ),
            RejectPresentation(),
        )
        assert report.status is d.ExecutionStatus.COMPLETED
        assert report.output_started is False
        expected = (MemoryLookupHit("memory-1", "用户喜欢音乐"),) if found else ()
        assert report.action_results[0].value == MemoryLookupResult(expected)
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_sessions_are_isolated_and_stream_before_generation_finishes():
    sockets = [FakeAliyunWebSocket(), FakeAliyunWebSocket()]
    sessions = [await factory(s).open(uuid4(), "背景") for s in sockets]
    try:
        first, second = sessions
        config = sockets[0].sent[0]["session"]
        assert config["modalities"] == ["text"]
        assert config["input_audio_transcription"]["model"] == "qwen3-asr-flash-realtime"
        assert config["tools"][0]["function"]["parameters"]["required"] == ["query"]
        await first.push(AudioFrame(b"\0\0", "pcm_s16le", 16000, 1))
        assert not any(e["type"] == "input_audio_buffer.append" for e in sockets[1].sent)
        await first.push(InstructionText("opening", "opening"))
        await send_reply(sockets[0], text="你好。剩余", item_id=None, done=False)
        stream = first.events()
        assert await anext(stream) == ReplyStarted("r1", None)
        assert await anext(stream) == ReplySegment("r1", 0, "你好。")
        await first.interrupt("r1")
        await first.interrupt("r1")
        await sockets[0].server_event({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}})
        assert await anext(stream) == ReplyFinished("r1")
        assert len([e for e in sockets[0].sent if e["type"] == "response.cancel"]) == 1
        await stream.aclose()
    finally:
        await asyncio.gather(*(s.close() for s in sessions))
        await sessions[0].close()
    assert all(s.closed for s in sockets)
    assert all(s._reader.done() for s in sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("result_before_done", [False, True])
async def test_memory_results_continue_once_after_tool_response_done(result_before_done):
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    stream = session.events()
    try:
        await send_reply(socket, text="", item_id=None, done=False)
        assert isinstance(await anext(stream), ReplyStarted)
        await socket.server_event({"type": "response.function_call_arguments.delta", "delta": '{"query":'})
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "r1",
                "call_id": "tool1",
                "name": "lookup_call_memory",
                "arguments": '{"query":"旧事"}',
            }
        )
        assert await anext(stream) == MemoryLookupRequested("r1", "tool1", "旧事")
        if result_before_done:
            await session.submit_tool_result("tool1", MemoryLookupResult(()))
            assert not any(e["type"] == "response.create" for e in socket.sent)
        await socket.server_event({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        assert await anext(stream) == ReplyFinished("r1")
        await session.submit_tool_result("tool1", MemoryLookupResult(()))
        await session.submit_tool_result("tool1", MemoryLookupResult(()))
        assert len([e for e in socket.sent if e["type"] == "response.create"]) == 1
        assert len([e for e in socket.sent if e["type"] == "conversation.item.create"]) == 1
        await session.interrupt("r1")
        assert not any(e["type"] == "response.cancel" for e in socket.sent)
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.asyncio
async def test_late_tool_result_after_interrupt_does_not_continue():
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        await send_reply(socket, text="", item_id=None)
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "r1",
                "call_id": "tool1",
                "name": "lookup_call_memory",
                "arguments": '{"query":"旧事"}',
            }
        )
        await _eventually(lambda: "tool1" in session._tools)
        await session.interrupt("r1")
        await session.submit_tool_result("tool1", MemoryLookupResult(()))
        assert not any(e["type"] in {"response.create", "response.cancel"} for e in socket.sent)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_next_segment_is_sent_before_playback_completion_and_both_streams_can_be_stopped(call_setup):
    stage, socket, transport, _ = await create_stage(call_setup)
    first, second = "r1-segment-0", "r1-segment-1"

    def packets():
        return [
            item
            for item in transport.items
            if isinstance(item, tuple) and item[0] == "pcm" and item[1] in (first, second)
        ]

    try:
        await send_reply(socket, done=False)
        # 客户端尚未确认第一句播完，模型也尚未报告生成结束。
        await _eventually(lambda: any(packet[1] == second for packet in packets()))
        audio = packets()
        assert [packet[1] for packet in audio] == [first, second]
        assert audio[0][-1] and audio[1][3]  # 第一条流已发尾包，第二条已有非空 PCM
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "interrupt"})
        for _, response, stream, _, _ in audio:
            await _eventually(lambda: ("stop", response, (stream,)) in transport.items)
            assert stage.playback_stopped(response, stream)
        assert [
            item[1]
            for item in transport.items
            if isinstance(item, tuple) and item[0] == "stop" and item[1] in (first, second)
        ] == [second, first]
        await socket.server_event({"type": "response.text.delta", "response_id": "r1", "delta": "过期。"})
        await socket.server_event({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}})
        snapshot = await finish_call(stage)
        assert not any(segment.response_id == "r1" for segment in snapshot.confirmed_segments)
        assert not any(isinstance(item, tuple) and item[:2] == ("pcm", "r1-segment-2") for item in transport.items)
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_new_model_reply_waits_for_previous_reply_playback(call_setup):
    stage, socket, transport, _ = await create_stage(call_setup)

    def pcm(response):
        return [item for item in transport.items if isinstance(item, tuple) and item[:2] == ("pcm", response)]

    try:
        await send_reply(socket, response_id="one", text="第一条。")
        await _eventually(lambda: pcm("one-segment-0"))
        await send_reply(socket, response_id="two", text="另一条。", item_id=None)
        await _eventually(lambda: "two-segment-0" in stage._responses)
        assert not pcm("two-segment-0")
        stage.playback_completed("one-segment-0", pcm("one-segment-0")[0][2])
        await _eventually(lambda: pcm("two-segment-0"))
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_reply_before_transcript_plays_once_and_summary_contains_only_confirmed_segments(call_setup):
    stage, socket, transport, _ = await create_stage(call_setup)
    try:
        await send_reply(socket, done=False)
        await _eventually(
            lambda: "r1-segment-0" in stage._responses and stage._responses["r1-segment-0"].stream_id is not None
        )
        assert not stage._turns[1].semantic
        first = stage._responses["r1-segment-0"]
        stage.playback_completed("r1-segment-0", first.stream_id)
        await stage._drain_facts()
        await socket.server_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "u1",
                "transcript": "我今天很开心",
            }
        )
        await _eventually(lambda: stage._turns[1].semantic == "我今天很开心")
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
        await _eventually(lambda: "r1" in stage._cancelled_replies)
        await socket.server_event({"type": "response.text.delta", "response_id": "r1", "delta": "取消后不该播放。"})
        snapshot = await finish_call(stage)
        full = "\n".join(render_call_turns(snapshot))
        assert "你好。" in full and "我今天很开心" in full and "第一句。" in full
        assert "第二句。" not in full and "取消后" not in full
        assert len([x for x in snapshot.confirmed_segments if x.response_id == "r1"]) == 1
        assert not stage.tasks and socket.closed
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
@pytest.mark.parametrize("hits", [(), (MemoryHit("用户喜欢小笼包", 1.0, "偏好", source_record_id="m1"),)])
async def test_authorized_tool_returns_all_hits_and_audio_continues(call_setup, hits):
    stage, socket, _, retrieval = await create_stage(call_setup, retrieval=Retrieval(hits, block=True))
    try:
        await send_reply(socket, response_id="tool-response", text="", done=False)
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "tool-response",
                "call_id": "tool1",
                "name": "lookup_call_memory",
                "arguments": '{"query":"用户偏好"}',
            }
        )
        await asyncio.wait_for(retrieval.started.wait(), 1)
        payload = b"\0\0"
        assert stage.accept_pcm(_receipt(stage.call_id, 1, payload), payload)
        await _eventually(lambda: any(e["type"] == "input_audio_buffer.append" for e in socket.sent))
        assert retrieval.invocation.user_id == "user" and retrieval.invocation.character_id == "luotianyi"
        await socket.server_event({"type": "response.done", "response": {"id": "tool-response", "status": "completed"}})
        retrieval.gate.set()
        await _eventually(lambda: "tool1" in stage._tool_results)
        assert len(stage.context.call_memory.snapshot()) == len(hits)
        results = [e for e in socket.sent if e.get("item", {}).get("type") == "function_call_output"]
        assert len(results) == 1
        assert len([e for e in socket.sent if e["type"] == "response.create"]) == 2  # opening + tool continuation
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_hangup_does_not_wait_for_memory_query(call_setup):
    stage, socket, _, retrieval = await create_stage(call_setup, retrieval=Retrieval(block=True))
    await send_reply(socket, text="", done=False)
    await socket.server_event(
        {
            "type": "response.function_call_arguments.done",
            "response_id": "r1",
            "call_id": "tool1",
            "name": "lookup_call_memory",
            "arguments": '{"query":"旧事"}',
        }
    )
    await asyncio.wait_for(retrieval.started.wait(), 1)
    await asyncio.wait_for(finish_call(stage), 1)
    assert socket.closed and not stage.tasks
    assert not any(e.get("item", {}).get("type") == "function_call_output" for e in socket.sent)


@pytest.mark.asyncio
async def test_provider_failure_ends_call_and_releases_session(call_setup):
    stage, socket, _, _ = await create_stage(call_setup)
    await socket.abnormal_close()
    snapshot = await asyncio.wait_for(wait_call_finished(stage), 1)
    assert snapshot.terminal.end_reason is CallEndReason.PROVIDER_FAILED
    assert socket.closed and not stage.tasks


@pytest.mark.asyncio
async def test_hard_time_limit_and_warning_stay_stage_owned(call_setup):
    stage, socket, transport, _ = await create_stage(
        call_setup, config={"time_limit_seconds": 2, "time_limit_warning_seconds": 1}
    )
    _, _, _, clock = call_setup
    clock.advance(1)
    stage._time_limit_changed.set()
    await _eventually(lambda: len([i for i in transport.items if isinstance(i, tuple) and i[0] == "start"]) == 2)
    clock.advance(1)
    stage._time_limit_changed.set()
    snapshot = await asyncio.wait_for(wait_call_finished(stage), 1)
    assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
    assert socket.closed and not stage.tasks


@pytest.mark.asyncio
async def test_decline_closes_without_opening_or_user_history(call_setup):
    stage, socket, _, _ = await create_stage(call_setup, accept=False)
    await finish_call(stage)
    assert stage.snapshot.completed_turns == ()
    assert not any(e["type"] == "response.create" for e in socket.sent)
    assert socket.closed and not stage.tasks


@pytest.mark.asyncio
async def test_lookup_failure_is_reported_and_releases_wait_without_ending_call(call_setup):
    class BrokenRetrieval(Retrieval):
        async def search(self, invocation, *, query):
            raise RuntimeError("查询失败")

    stage, socket, _, _ = await create_stage(call_setup, retrieval=BrokenRetrieval())
    try:
        await send_reply(socket, response_id="broken", text="", done=False)
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "broken",
                "call_id": "failed-tool",
                "name": "lookup_call_memory",
                "arguments": '{"query":"旧事"}',
            }
        )
        await socket.server_event({"type": "response.done", "response": {"id": "broken", "status": "completed"}})
        await _eventually(lambda: "failed-tool" in stage._tool_results)
        assert stage.state is CallState.ACTIVE and not stage.termination_requested
        results = [e["item"]["output"] for e in socket.sent if e.get("item", {}).get("type") == "function_call_output"]
        assert len(results) == 1 and '"error": "lookup_failed"' in results[0]
        assert stage.context.call_memory.snapshot() == ()
        await send_reply(socket, response_id="continued", text="暂时没有查到，我们先聊聊现在吧。", item_id=None)
        await _eventually(lambda: "continued-segment-0" in stage._responses)
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_pending_tool_continuation_inherits_interruption_before_response_id_arrives():
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        await send_reply(socket, text="", done=False)
        await socket.server_event(
            {
                "type": "response.function_call_arguments.done",
                "response_id": "r1",
                "call_id": "tool1",
                "name": "lookup_call_memory",
                "arguments": '{"query":"旧事"}',
            }
        )
        await socket.server_event({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        await _eventually(lambda: "tool1" in session._tools)
        await session.submit_tool_result("tool1", MemoryLookupResult(()))
        await session.interrupt("r1")
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "u2"})
        await socket.server_event({"type": "response.created", "response": {"id": "late"}})
        await socket.server_event({"type": "response.text.delta", "response_id": "late", "delta": "过期续答。"})
        await _eventually(lambda: "late" in session._replies)
        assert session._replies["late"].cancelled
        assert not any(isinstance(e, ReplySegment) and e.response_id == "late" for e in session._events._queue)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_late_transcripts_follow_input_order_and_do_not_trigger_extra_reply(call_setup):
    from src.domain.call.omni import SpeechStarted, SpeechStopped

    stage, socket, _, _ = await create_stage(call_setup)
    try:
        for item in ("one", "two"):
            await stage._on_omni_event(SpeechStarted(item))
            await stage._on_omni_event(SpeechStopped(item))
        await stage._on_omni_event(TranscriptFinal("two", "第二句话"))
        await stage._on_omni_event(TranscriptFinal("one", "第一句话"))
        await stage._on_omni_event(TranscriptFinal("one", "第一句话"))
        snapshot = await finish_call(stage)
        assert [turn.user_semantic for turn in snapshot.completed_turns] == ["第一句话", "第二句话"]
        assert len([e for e in socket.sent if e["type"] == "response.create"]) == 1
        assert stage._finalization_error is None
        assert stage._test_summary.materials[0].final_snapshot is snapshot
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_silence_uses_one_control_request_after_playback_and_waits_during_tool(call_setup, monkeypatch):
    stage, socket, _, _ = await create_stage(call_setup)
    try:
        stage._cancel_task(stage._silence_task)
        monkeypatch.setattr(stage._playback, "silence_elapsed", lambda: True)
        stage._tool_calls["pending"] = "opening"
        await stage._await_silence()
        assert len([e for e in socket.sent if e["type"] == "response.create"]) == 1
        stage._tool_results.add("pending")
        await stage._await_silence()
        assert len([e for e in socket.sent if e["type"] == "response.create"]) == 2
    finally:
        await finish_call(stage)


@pytest.mark.asyncio
async def test_streamed_tone_tags_are_not_spoken_and_survive_delta_boundaries():
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        await socket.server_event({"type": "response.created", "response": {"id": "tones"}})
        for delta in ("[温", "柔]别着急。", "我在听。\n[欣", "喜]太好了", "！[中性]再见"):
            await socket.server_event({"type": "response.text.delta", "response_id": "tones", "delta": delta})
        await socket.server_event({"type": "response.done", "response": {"id": "tones", "status": "completed"}})
        segments = []
        async for event in session.events():
            if isinstance(event, ReplySegment):
                segments.append(event)
            if isinstance(event, ReplyFinished):
                break
        assert [(e.segment_index, e.text, e.tone) for e in segments] == [
            (0, "别着急。", "温柔"),
            (1, "我在听。", "温柔"),
            (2, "太好了！", "欣喜"),
            (3, "再见", "中性"),
        ]
    finally:
        await session.close()

@pytest.mark.asyncio
async def test_endpoint_estimate_ignores_silence_and_audio_after_reported_end(monkeypatch):
    from src.domain.call.omni import SpeechStarted, SpeechStopped
    from src.infrastructure.models.realtime_speech import omni

    events = []
    monkeypatch.setattr(omni, "call_latency", lambda name, *args, **fields: events.append(name))
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        for ms, value in enumerate([0, 1000, 0, 1000], 1):
            pcm = value.to_bytes(2, "little", signed=True) * 160
            await session.push(AudioFrame(pcm, "pcm_s16le", 16000, 1, ingress_ns=ms * 10_000_000))
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": "a", "audio_start_ms": 0})
        await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": "a", "audio_end_ms": 30})
        stream = session.events()
        assert await anext(stream) == SpeechStarted("a")
        assert await anext(stream) == SpeechStopped("a", 20_000_000)
        await socket.server_event({"type": "response.created", "response": {"id": "r"}})
        for part in ("", "第", "一句。"):
            await socket.server_event({"type": "response.text.delta", "response_id": "r", "delta": part})
        assert await anext(stream) == ReplyStarted("r", "a")
        assert (await anext(stream)).text == "第一句。"
        assert events.count("reply.first_text_delta") == 1
        await stream.aclose()
    finally:
        await session.close()

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_anonymous_empty_done_keeps_next_spoken_turn_usable(status):
    from src.domain.call.omni import SpeechStopped

    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": "no-reply"})
        await socket.server_event({"type": "response.done", "response": {"id": "", "status": status, "output": []}})
        await send_reply(socket, response_id="next", item_id="next-user", text="你好。")
        observed = []
        stream = session.events()
        for _ in range(6):
            observed.append(await asyncio.wait_for(anext(stream), 2))
        assert observed[-1] == ReplyFinished("next")
        assert observed[0] == SpeechStopped("no-reply")
        assert [e for e in observed if isinstance(e, ReplyStarted)] == [ReplyStarted("next", "next-user")]
        assert [e.text for e in observed if isinstance(e, ReplySegment)] == ["你好。"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_anonymous_failed_done_retains_provider_error():
    socket = FakeAliyunWebSocket()
    session = await factory(socket).open(uuid4(), "背景")
    try:
        await socket.server_event({
            "type": "response.done", "event_id": "event-error",
            "response": {"id": "", "status": "failed", "status_details": {"error": {"code": "invalid_value"}}},
        })
        with pytest.raises(RuntimeError, match="receive failed") as caught:
            await asyncio.wait_for(anext(session.events()), 2)
        assert "invalid_value" in str(caught.value.__cause__)
        assert "event-error" in str(caught.value.__cause__)
    finally:
        await session.close()
