"""Regressions for multi-segment replies and failure-safe terminal snapshots."""

import asyncio
from dataclasses import replace
from datetime import datetime

import pytest

from src.domain.call import CallReplyStatus
from src.infrastructure.observability.call_metrics import CallMetricName
from src.stage.call_stage import CallPCM
from tests.integration.stage import test_call_stage as baseline

call_setup = baseline.call_setup


async def _create_with_immediate_network(*, transport, **kwargs):
    """Stage 级测试以探针成功返回模拟网络完成；真实队列边界另由集成测试覆盖。"""
    send = baseline.output_sink(transport)

    async def output_sink(call_id, output):
        await send(call_id, output)
        if isinstance(output, CallPCM) and output.payload:
            stage.audio_sent(output.response_id)

    stage = await baseline.start_call_stage(output_sink=output_sink, **kwargs)
    return stage


async def _await_realized(stage, *, target=None):
    # Input admission now precedes the asynchronously scheduled batch reply.
    if target is None:
        target = len(stage._turns) + (1 if stage._provider is not None and not stage._provider._events.empty() else 0)
    await baseline._eventually(lambda: target in stage._request_turn.values())
    await baseline._eventually(
        lambda: not stage._handle_tasks and stage._realize_task is not None and stage._realize_task.done()
    )


async def _complete_playback(stage):
    for response_id, stream_id in stage._playback.pending_streams:
        if stage._responses[response_id].failed:
            stage.playback_stopped(response_id, stream_id)
        else:
            stage.playback_completed(response_id, stream_id)
    await baseline._eventually(lambda: not stage._fact_tasks)


class _FailedSay:
    async def realize(self, action, context, outputs):
        await outputs.emit(baseline.TextFinalDraft(delivery=action.delivery, text=action.content))
        await outputs.emit(
            baseline.MessageEndDraft(
                delivery=action.delivery,
                status=baseline.d.MessageEndStatus.FAILED,
                error_code=baseline.d.AudioErrorCode.GENERATION_FAILED,
            )
        )
        return baseline.d.ActionResult(
            action_id=action.action_id,
            status=baseline.d.ActionExecutionStatus.FAILED,
            error_code=baseline.d.ExecutionErrorCode.AUDIO_GENERATION_FAILED,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _TimedMultiChunkSay:
    def __init__(self, clock, delays):
        self._clock = clock
        self._delays = iter(delays)

    async def realize(self, action, context, outputs):
        await outputs.emit(baseline.TextFinalDraft(delivery=action.delivery, text=action.content))
        self._clock.advance(next(self._delays))
        for final in (False, True):
            await outputs.emit(
                baseline.AudioChunkDraft(
                    delivery=action.delivery,
                    data=b"\x00\x00",
                    framing=baseline.d.AudioFraming.RAW_PCM,
                    audio_format=baseline.d.CALL_PCM_FORMAT,
                    final=final,
                )
            )
        await outputs.emit(
            baseline.MessageEndDraft(
                delivery=action.delivery,
                status=baseline.d.MessageEndStatus.COMPLETED,
                error_code=None,
            )
        )
        return baseline.d.ActionResult(
            action_id=action.action_id,
            status=baseline.d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _FailingPcmTransport(baseline._Transport):
    async def send_pcm(self, response_id, stream_id, payload, *, final):
        raise RuntimeError("send failed")


class _BlockingPcmTransport(baseline._Transport):
    def __init__(self):
        super().__init__()
        self.send_started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_pcm(self, response_id, stream_id, payload, *, final):
        self.send_started.set()
        await self.release.wait()
        await super().send_pcm(response_id, stream_id, payload, final=final)


class _BlockedAudioSay:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def realize(self, action, context, outputs):
        await outputs.emit(baseline.TextFinalDraft(delivery=action.delivery, text=action.content))
        self.started.set()
        await self.release.wait()
        await outputs.emit(
            baseline.AudioChunkDraft(
                delivery=action.delivery,
                data=b"\x00\x00",
                framing=baseline.d.AudioFraming.RAW_PCM,
                audio_format=baseline.d.CALL_PCM_FORMAT,
                final=True,
            )
        )
        return baseline.d.ActionResult(
            action_id=action.action_id,
            status=baseline.d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _RetryOnceSay:
    def __init__(self, clock):
        self._clock = clock
        self._attempts = 0

    async def realize(self, action, context, outputs):
        self._attempts += 1
        if self._attempts == 1:
            self._clock.advance(0.100)
            return baseline.d.ActionResult(
                action_id=action.action_id,
                status=baseline.d.ActionExecutionStatus.FAILED,
                error_code=baseline.d.ExecutionErrorCode.AUDIO_GENERATION_FAILED,
                irreversible_effect_committed=False,
                effect_ref=None,
            )
        self._clock.advance(0.150)
        await outputs.emit(
            baseline.AudioChunkDraft(
                delivery=action.delivery,
                data=b"\x00\x00",
                framing=baseline.d.AudioFraming.RAW_PCM,
                audio_format=baseline.d.CALL_PCM_FORMAT,
                final=True,
            )
        )
        return baseline.d.ActionResult(
            action_id=action.action_id,
            status=baseline.d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _LateAudioAfterCancellationSay:
    def __init__(self):
        self.started = asyncio.Event()

    async def realize(self, action, context, outputs):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await outputs.emit(
                baseline.AudioChunkDraft(
                    delivery=action.delivery,
                    data=b"\x00\x00",
                    framing=baseline.d.AudioFraming.RAW_PCM,
                    audio_format=baseline.d.CALL_PCM_FORMAT,
                    final=True,
                )
            )
            raise


class _TextOnlySay:
    async def realize(self, action, context, outputs):
        await outputs.emit(baseline.TextFinalDraft(delivery=action.delivery, text=action.content))
        await outputs.emit(
            baseline.MessageEndDraft(
                delivery=action.delivery,
                status=baseline.d.MessageEndStatus.COMPLETED,
                error_code=None,
            )
        )
        return baseline.d.ActionResult(
            action_id=action.action_id,
            status=baseline.d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _MultiTurn(baseline._TurnHandler):
    async def handle(self, request, plans):
        class TwoSegments:
            accepted_ids = plans.accepted_ids

            async def emit(self, draft):
                original = draft.actions[0]
                first = replace(original, content="第一段")
                second = replace(
                    original,
                    action_id=original.action_id + "-second",
                    content="第二段",
                    call_delivery=replace(
                        original.call_delivery, response_id=original.call_delivery.response_id + "-second"
                    ),
                )
                await plans.emit(replace(draft, actions=(first, second)))

        await super().handle(request, TwoSegments())
        return baseline._report(request, plans)


@pytest.mark.asyncio
async def test_first_audio_is_measured_once_per_turn_after_successful_pcm_send(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = _MultiTurn()
    handler.gate.set()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=baseline._Transport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(
        ((baseline.d.ActionKind.SAY, _TimedMultiChunkSay(clock, (0.125, 0.010, 0.250, 0.010))),)
    )
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="第一轮")))
        await _await_realized(stage)
        await _complete_playback(stage)
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="第二轮")))
        await _await_realized(stage)

        first_audio = [metric for metric in captured if metric.name is CallMetricName.FIRST_AUDIO]
        assert [metric.duration_ms for metric in first_audio] == [125.0, 250.0]
        assert all(metric.labels == {"result": "succeeded"} for metric in first_audio)
        assert all(
            datetime.fromisoformat(metric.start_ts) < datetime.fromisoformat(metric.end_ts) for metric in first_audio
        )
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_first_audio_is_not_recorded_when_pcm_send_fails(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=_FailingPcmTransport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="发送失败")))
        await _await_realized(stage)

        assert CallMetricName.FIRST_AUDIO not in [metric.name for metric in captured]
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_first_audio_is_not_recorded_for_interrupted_response(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    action_handler = _BlockedAudioSay()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=baseline._Transport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, action_handler),))
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="被打断")))
        await action_handler.started.wait()
        stage._interrupt()
        await _await_realized(stage)

        assert CallMetricName.FIRST_AUDIO not in [metric.name for metric in captured]
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_first_audio_excludes_turns_crossing_reconnect_and_accepts_new_turn_after_resume(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=baseline._Transport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(
        ((baseline.d.ActionKind.SAY, _TimedMultiChunkSay(clock, (0.125, 0.250))),)
    )
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None

        handler.gate.clear()
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="断线前轮次")))
        await baseline._eventually(lambda: bool(stage._handle_tasks))
        await stage.disconnect()
        handler.gate.set()
        await _await_realized(stage)
        assert await stage.resume() is True

        await _complete_playback(stage)
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="恢复后新轮次")))
        await _await_realized(stage)

        first_audio = [metric for metric in captured if metric.name is CallMetricName.FIRST_AUDIO]
        assert [metric.duration_ms for metric in first_audio] == [250.0]
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_first_audio_remains_excluded_when_inflight_pcm_returns_after_resume(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    transport = _BlockingPcmTransport()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=transport,
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(
        ((baseline.d.ActionKind.SAY, _TimedMultiChunkSay(clock, (0.125, 0.250))),)
    )
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="在途发送轮次")))
        await transport.send_started.wait()

        await stage.disconnect()
        assert await stage.resume() is True
        transport.release.set()
        await _await_realized(stage)

        await _complete_playback(stage)
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="恢复后轮次")))
        await _await_realized(stage)

        first_audio = [metric for metric in captured if metric.name is CallMetricName.FIRST_AUDIO]
        assert [metric.duration_ms for metric in first_audio] == [250.0]
        assert stage.state is baseline.CallState.ACTIVE
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)
        assert not stage.tasks
    finally:
        transport.release.set()
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_successful_text_only_response_does_not_record_first_audio(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=baseline._Transport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, _TextOnlySay()),))
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="纯文本成功轮次")))
        await _await_realized(stage)

        assert CallMetricName.FIRST_AUDIO not in [metric.name for metric in captured]
        assert stage._turns[1].status is baseline.CallReplyStatus.NOT_STARTED
        assert stage._unfinished_turns == {1}
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)
        assert not stage.tasks
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_first_audio_uses_original_turn_start_when_say_retries(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=baseline._Transport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, _RetryOnceSay(clock)),))
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="重试轮次")))
        await _await_realized(stage)

        first_audio = [metric for metric in captured if metric.name is CallMetricName.FIRST_AUDIO]
        assert [metric.duration_ms for metric in first_audio] == [250.0]
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_late_interrupted_generation_audio_is_excluded_and_new_provider_turn_is_measured(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = baseline._TurnHandler()
    handler.gate.set()
    late_handler = _LateAudioAfterCancellationSay()
    stage = await _create_with_immediate_network(
        ownership=ownership,
        record=record,
        agent=baseline._agent(handler),
        context_factory=baseline.ContextFactory(character_id="luotianyi", database=baseline._ContextDatabase()),
        call_sessions=repository,
        speech_factory=baseline.FakeRealtimeSpeechSessionFactory(),
        transport=baseline._Transport(),
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, late_handler),))
    try:
        await stage.apply_answer(
            baseline.d.AnswerCall(
                action_id="answer", call_id=record.call_id, decision=baseline.CallAnswerDecision.ACCEPT
            )
        )
        await baseline._eventually(lambda: stage.state is baseline.CallState.ACTIVE)
        provider = stage._provider
        assert provider is not None
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="旧轮次")))
        await late_handler.started.wait()
        await provider.emit(baseline.SpeechStarted())
        await baseline._eventually(lambda: stage._user_speaking)
        await _await_realized(stage, target=1)

        stage._agent._action_router = baseline.ActionRouter(
            ((baseline.d.ActionKind.SAY, _TimedMultiChunkSay(clock, (0.125,))),)
        )
        await provider.emit(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="新轮次")))
        await _await_realized(stage)

        first_audio = [metric for metric in captured if metric.name is CallMetricName.FIRST_AUDIO]
        assert [metric.duration_ms for metric in first_audio] == [125.0]
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_all_formal_segments_are_preserved_and_wait_for_playback(call_setup):
    stage, _, _, _ = await baseline._create(call_setup)
    handler = _MultiTurn()
    handler.gate.set()
    stage._agent = baseline._agent(handler)
    try:
        await stage._on_turn(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="用户发言")))
        await _await_realized(stage)
        streams = tuple(stage._playback.pending_streams)
        assert len(streams) == 2
        stage.playback_completed(*streams[0])
        assert stage._turns[1].status is not CallReplyStatus.COMPLETED
        stage.playback_completed(*streams[1])
        snapshot = await stage.terminate(baseline.CallEndReason.USER_HANGUP)
        assert snapshot.completed_turns[0].reply_status is CallReplyStatus.COMPLETED
        assert snapshot.completed_turns[0].formal_agent_text == "第一段\n第二段"
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_failed_reply_then_success_can_settle_terminal_snapshot(call_setup):
    stage, _, _, handler = await baseline._create(call_setup)
    handler.gate.set()
    stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, _FailedSay()),))
    try:
        await stage._on_turn(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="失败轮")))
        await _await_realized(stage)
        stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, baseline._SayHandler()),))
        await stage._on_turn(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="成功轮")))
        await _await_realized(stage)
        for response_id, stream_id in tuple(stage._playback.pending_streams):
            stage.playback_completed(response_id, stream_id)
        snapshot = await stage.terminate(baseline.CallEndReason.USER_HANGUP)
        assert snapshot.completed_turns[0].reply_status is CallReplyStatus.COMPLETED
        assert snapshot.completed_turns[0].reply_turn_seq == 2
        assert snapshot.completed_turns[0].formal_agent_text is None
        assert snapshot.completed_turns[1].reply_status is CallReplyStatus.COMPLETED
        assert snapshot.completed_turns[1].formal_agent_text == "正式回答"
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)
