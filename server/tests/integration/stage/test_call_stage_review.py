"""Regressions for multi-segment replies and failure-safe terminal snapshots."""

from dataclasses import replace

import pytest

from src.domain.call import CallReplyStatus
from tests.integration.stage import test_call_stage as baseline

call_setup = baseline.call_setup


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
async def test_all_formal_segments_are_preserved_and_wait_for_playback(call_setup):
    stage, _, _, _ = await baseline._create(call_setup)
    handler = _MultiTurn()
    handler.gate.set()
    stage._agent = baseline._agent(handler)
    try:
        await stage._on_turn(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="用户发言")))
        await baseline._eventually(lambda: stage._realize_task.done())
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
        await baseline._eventually(lambda: stage._realize_task.done())
        stage._agent._action_router = baseline.ActionRouter(((baseline.d.ActionKind.SAY, baseline._SayHandler()),))
        await stage._on_turn(baseline.TurnCompleted(baseline.CallAudioSemantic(transcript="成功轮")))
        await baseline._eventually(lambda: stage._realize_task.done())
        for response_id, stream_id in tuple(stage._playback.pending_streams):
            stage.playback_completed(response_id, stream_id)
        snapshot = await stage.terminate(baseline.CallEndReason.USER_HANGUP)
        assert snapshot.completed_turns[0].reply_status is CallReplyStatus.FAILED
        assert snapshot.completed_turns[0].formal_agent_text is None
        assert snapshot.completed_turns[1].reply_status is CallReplyStatus.COMPLETED
        assert snapshot.completed_turns[1].formal_agent_text == "正式回答"
    finally:
        await stage.terminate(baseline.CallEndReason.USER_HANGUP)
