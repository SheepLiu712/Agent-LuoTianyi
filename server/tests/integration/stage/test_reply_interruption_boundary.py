"""普通刺激只取消未形成正式计划的 chat handle；已交付计划不撤销。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from support.stage_support import RecordingAgent, cleanup, plan, report, setup, stimulus

import src.domain.agent as d
from src.domain.stage import CancelDelivery


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 2)


def trigger(kind):
    if kind == "typing":
        return stimulus(d.UserTyping, text_length=3)
    if kind == "voice_start":
        return stimulus(d.VoiceRecordingStarted, recording_id="recording")
    if kind == "image_open":
        return stimulus(d.ImageSelectionOpened)
    if kind == "image":
        return stimulus(d.ImageMessage, media_ref=d.MediaRef(media_id="image"), client_msg_id="image")
    if kind == "voice":
        return stimulus(
            d.VoiceMessage,
            media_ref=d.MediaRef(media_id="voice"),
            message_uuid=str(uuid4()),
            client_msg_id="voice",
            transcript=None,
            duration_ms=1000,
        )
    return stimulus()


TRIGGERS = ["typing", "voice_start", "image_open", "text", "image", "voice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TRIGGERS)
@pytest.mark.parametrize("phase", ["queued", "handle_running", "handle_done", "plans_done", "all_done"])
async def test_committed_reply_is_preserved_at_every_stage(kind, phase):  # noqa: C901
    handle_gate, execution_gate = asyncio.Event(), asyncio.Event()
    replies, accepted, executions = [], [], []
    if phase in ("queued", "handle_done", "all_done"):
        handle_gate.set()
    if phase in ("plans_done", "all_done"):
        execution_gate.set()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.TouchInteraction):
            value = plan(request)
            await sink.emit(value)
            return report(request, plans=(value.plan_id,))
        if isinstance(request.stimulus, d.InteractionDeadline):
            replies.append(request)
            values = (plan(request), plan(request, ordinal=1))
            for value in values:
                await sink.emit(value)
                accepted.append(value)
            await handle_gate.wait()
            return report(
                request,
                consumed=tuple(s.stimulus_id for s in request.interaction.pending_stimuli),
                plans=tuple(p.plan_id for p in values),
            )
        return report(request)

    async def realize(value, context, sink):
        executions.append((value, context))
        await execution_gate.wait()
        common = dict(
            interaction_id=context.interaction_id,
            execution_id=context.execution_id,
            action_id=value.actions[0].action_id,
            delivery=d.OutputDelivery.CONVERSATION,
        )
        await sink.emit(d.TextFinalOutput(**common, sequence_no=0, text=value.plan_id))
        await sink.emit(
            d.MessageEndOutput(**common, sequence_no=1, status=d.MessageEndStatus.COMPLETED, error_code=None)
        )
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)

    # Even an overly permissive Agent must not let Stage revoke an accepted plan.
    agent = RecordingAgent(handle, realize)
    stage, _, adapter, _, socket = await setup(agent, {"response_wait": 60})
    original = stimulus()
    try:
        if phase == "queued":
            stage.stimulus_input_sink.submit(
                stimulus(d.TouchInteraction, body_regions=(d.BodyRegion(value="head"),), click_frequency=None)
            )
            await until(lambda: len(executions) == 1)
        stage.stimulus_input_sink.submit(original)
        await until(lambda: stage._deadline is not None)
        stage._on_deadline(stage._schedule_revision)
        await until(lambda: len(accepted) == 2)
        old = replies[0]
        if phase in ("queued", "handle_done", "all_done"):
            await until(lambda: old.request_id not in stage._handles)
        if phase in ("plans_done", "all_done"):
            await until(lambda: stage._executing_plan is None and not stage._plans)
        old_ids = tuple(p.plan_id for p in accepted)
        expected_pending = phase in ("handle_running", "plans_done")
        assert (original.stimulus_id in stage._pending) == expected_pending
        with patch.object(adapter, "submit_output", wraps=adapter.submit_output) as submit:
            stage.stimulus_input_sink.submit(trigger(kind))
            await asyncio.sleep(0)
            assert not old.cancellation.is_cancelled
            assert all(not context.cancellation.is_cancelled for _, context in executions)
            assert (original.stimulus_id in stage._pending) == expected_pending
            if expected_pending:
                assert stage._pending[original.stimulus_id].status.value == "replying"
            assert not any(isinstance(call.args[0], CancelDelivery) for call in submit.call_args_list)
            handle_gate.set()
            execution_gate.set()
            await until(
                lambda: all(
                    any(event.get("payload", {}).get("text") == pid for event in socket.events) for pid in old_ids
                )
            )
            await until(lambda: old.request_id not in stage._handles and stage._executing_plan is None)
            assert not any(isinstance(call.args[0], CancelDelivery) for call in submit.call_args_list)
        assert len(replies) == 1
        assert original.stimulus_id not in stage._pending
        assert [p.plan_id for p, _ in executions if p.origin_request_id == old.request_id] == list(old_ids)
    finally:
        handle_gate.set()
        execution_gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TRIGGERS)
async def test_thinking_notification_does_not_prevent_cancelling_chat_handle(kind):
    replies = []
    cancelled = asyncio.Event()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionDeadline):
            await sink.emit(plan(request, thinking=True))
            replies.append(request)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return report(request)

    stage, agent, adapter, _, socket = await setup(RecordingAgent(handle), {"response_wait": 60})
    original = stimulus()
    try:
        stage.stimulus_input_sink.submit(original)
        await until(lambda: stage._deadline is not None)
        stage._on_deadline(stage._schedule_revision)
        await until(lambda: bool(replies))
        with patch.object(adapter, "submit_output", wraps=adapter.submit_output) as submit:
            stage.stimulus_input_sink.submit(trigger(kind))
            await asyncio.wait_for(cancelled.wait(), 1)
            assert replies[0].cancellation.reason is d.CancellationReason.SUPERSEDED
            assert stage._pending[original.stimulus_id].status.value == "ready"
            assert agent.executions.empty()
            await until(lambda: any(event.get("payload", {}).get("state") == "waiting" for event in socket.events))
            states = [event["payload"]["state"] for event in socket.events if event["type"] == "agent_state_changed"]
            assert states == ["thinking", "waiting"]
            assert not stage._thinking
            assert not any(isinstance(call.args[0], CancelDelivery) for call in submit.call_args_list)
    finally:
        await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["typing", "voice_start", "image_open"])
@pytest.mark.parametrize("input_kind", ["text", "image", "voice", "touch"])
async def test_other_handles_are_not_candidates_even_if_their_permission_is_true(kind, input_kind):
    gate = asyncio.Event()
    requests = []
    original = (
        stimulus(d.TouchInteraction, body_regions=(d.BodyRegion(value="head"),), click_frequency=None)
        if input_kind == "touch"
        else trigger(input_kind)
    )

    async def handle(request, sink):
        if request.stimulus.stimulus_id == original.stimulus_id:
            requests.append(request)
            await gate.wait()
        return report(request)

    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 60})
    try:
        stage.stimulus_input_sink.submit(original)
        await until(lambda: bool(requests))
        stage.stimulus_input_sink.submit(trigger(kind))
        await asyncio.sleep(0)
        assert not requests[0].cancellation.is_cancelled
        assert not stage._handles[requests[0].request_id].done()
        if input_kind != "touch":
            assert stage._pending[original.stimulus_id].status.value == "preprocessing"
    finally:
        gate.set()
        await cleanup(stage, adapter)
