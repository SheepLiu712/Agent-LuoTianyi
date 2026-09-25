"""WorldStage 的接入、修订、结算与执行 receipt 契约。"""
import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from support.world_stage_fakes import (
    RecordingAgent,
    action_plan,
    activity_observation,
    create_stage,
    handling_report,
    world_observation,
)

import src.domain.agent as d


@pytest.mark.asyncio
async def test_older_inflight_handle_can_emit_after_new_fact_revision():
    emitted = asyncio.Event()
    release = asyncio.Event()

    class ConcurrentAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            self.requests.put_nowait(request)
            if request.stimulus.stimulus_id == first.stimulus_id:
                emitted.set()
                await release.wait()
                plan = action_plan(request)
                await sink.emit(plan)
                return handling_report(request, plans=(plan.plan_id,))
            return handling_report(request)

    first, second = world_observation(revision=1), world_observation(revision=2)
    stage, agent, _ = await create_stage(ConcurrentAgent())
    assert await stage.fact_sink.submit(first)
    await emitted.wait()
    assert await stage.fact_sink.submit(second)
    release.set()
    await stage.wait_idle()
    assert len(agent.executions) == 1
    await stage.close()


@pytest.mark.asyncio
async def test_plan_identity_mismatch_is_rejected():
    class MismatchAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            with pytest.raises(d.SinkRejectedError) as error:
                await sink.emit(replace(action_plan(request), origin_request_id=str(uuid4())))
            assert error.value.code is d.SinkRejectionCode.IDENTITY_MISMATCH
            return handling_report(request)

    stage, agent, _ = await create_stage(MismatchAgent())
    assert await stage.fact_sink.submit(world_observation())
    await stage.wait_idle()
    assert agent.executions == []
    await stage.close()


@pytest.mark.asyncio
async def test_ingress_rejects_unsupported_kind_and_full_retained_pending():
    class RetainingAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
            return d.HandlingReport(
                request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
                basis_interaction_revision=request.interaction.interaction_revision,
                request_status=d.HandlingRequestStatus.COMPLETED,
                considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=(),
                retained_pending_stimulus_ids=pending, emitted_plan_ids=(), error_code=None,
                retryable=False,
            )

    stage, _, _ = await create_stage(RetainingAgent(), config={"max_stimuli": 1})
    first = world_observation(revision=1)
    assert await stage.fact_sink.submit(first)
    await stage.wait_idle()
    unsupported = d.TextMessage(
        stimulus_id=str(uuid4()), schema_version=1, occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.WORLD, target_character_ids=("luotianyi",), user_id=None,
        ephemeral=False, text="not a world fact", client_msg_id=str(uuid4()),
    )
    assert not await stage.fact_sink.submit(unsupported)
    assert not await stage.fact_sink.submit(world_observation(revision=2))
    assert stage.pending_stimuli == (first,)
    await stage.close()


@pytest.mark.asyncio
async def test_nonretryable_failed_fact_is_terminally_removed():
    class FailedAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            return handling_report(request, status=d.HandlingRequestStatus.FAILED)

    stage, _, _ = await create_stage(FailedAgent())
    assert await stage.fact_sink.submit(world_observation())
    await stage.wait_idle()
    assert stage.pending_stimuli == ()
    await stage.close()


@pytest.mark.asyncio
async def test_owner_revisions_reject_regression_and_allow_activity_transition():
    stage, agent, _ = await create_stage()
    assert await stage.fact_sink.submit(world_observation(revision=5))
    await stage.wait_idle()
    current_revision = stage.interaction_revision
    assert not await stage.fact_sink.submit(world_observation(revision=4))
    assert stage.interaction_revision == current_revision

    assert await stage.fact_sink.submit(activity_observation(activity_id="walk", revision=3))
    await stage.wait_idle()
    assert not await stage.fact_sink.submit(activity_observation(activity_id="walk", revision=2))
    while not agent.requests.empty():
        agent.requests.get_nowait()
    assert await stage.fact_sink.submit(activity_observation(activity_id="concert", revision=1))
    transitioned = await asyncio.wait_for(agent.requests.get(), 1)
    assert transitioned.interaction.activity_id == "concert"
    assert transitioned.interaction.activity_revision == 1
    await stage.wait_idle()
    await stage.close()


@pytest.mark.asyncio
async def test_execution_failure_is_logged_and_delivered_to_completion_callback(caplog, capture_project_log):
    capture_project_log("src.stage.world_stage")
    receipts = []

    class FailedExecutionAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            plan = action_plan(request)
            await sink.emit(plan)
            return handling_report(request, plans=(plan.plan_id,))

        async def realize_action_plan(self, plan, context, sink):
            return d.ExecutionReport(
                execution_id=context.execution_id, plan_id=plan.plan_id,
                status=d.ExecutionStatus.FAILED,
                action_results=(d.ActionResult(
                    action_id=plan.actions[0].action_id, status=d.ActionExecutionStatus.FAILED,
                    error_code=d.ExecutionErrorCode.SINK_CLOSED,
                    irreversible_effect_committed=False, effect_ref=None,
                ),), output_started=False, error_code=d.ExecutionErrorCode.SINK_CLOSED,
                retryable=False,
            )

    caplog.set_level(logging.ERROR)
    stage, _, _ = await create_stage(
        FailedExecutionAgent(), on_execution_finished=lambda plan, report: receipts.append((plan, report)),
    )
    assert await stage.fact_sink.submit(world_observation())
    await stage.wait_idle()
    assert len(receipts) == 1
    plan, report = receipts[0]
    assert report.plan_id == plan.plan_id
    assert f"plan={plan.plan_id}" in caplog.text
    assert d.ExecutionErrorCode.SINK_CLOSED.value in caplog.text
    await stage.close()
