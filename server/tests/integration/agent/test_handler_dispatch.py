"""从真实运行时的两个业务入口观察注册处理器的交付与结算。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from src.agent.processing.output_drafts import MessageEndDraft
from routing_support import full_output
from plan_emission_support import draft
from routing_support import (Sink, completed, output, plan_and_context, request, settlement)  # noqa: F401


async def test_registered_handle_delivers_plan_and_settles_consumption(routed_runtime):
    plan, _ = plan_and_context()
    external = Sink()
    saved = []

    async def handle(req, plans):
        assert plans is not external
        saved.append(plans)
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id,))

    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(request(), external)
    assert report == settlement(request(), emitted=(external.values[0].plan_id,))
    assert len(external.values) == 1
    assert external.values[0].actions == plan.actions
    assert external.values[0].origin_request_id == "r"
    assert external.values[0].target_character_id == "luotianyi"
    assert external.values[0].interaction_id == "i"
    assert external.values[0].basis_interaction_revision == 3
    assert external.values[0].source_stimulus_ids == plan.source_stimulus_ids
    with pytest.raises(Exception):
        await saved[0].emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
    assert len(external.values) == 1


@pytest.mark.parametrize("error,code,retryable", [
    (TimeoutError("provider detail"), d.HandlingErrorCode.PROVIDER_TIMEOUT, False),
    (KeyError("business detail"), d.HandlingErrorCode.INTERNAL_ERROR, False),
    (ValueError("business detail"), d.HandlingErrorCode.INTERNAL_ERROR, False),
])
async def test_handle_exception_preserves_confirmed_plan(routed_runtime, error, code, retryable):
    plan, _ = plan_and_context()

    async def handle(req, plans):
        await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        raise error

    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is code
    assert report.retryable is retryable
    assert report.emitted_plan_ids == (sink.values[0].plan_id,)
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == ("m2", "m1")


@pytest.mark.parametrize("side", ["handle", "realize"])
@pytest.mark.parametrize("rejection", list(d.SinkRejectionCode))
async def test_sink_rejection_is_stable_and_never_accepted(routed_runtime, side, rejection):
    plan, context = plan_and_context()

    async def reject(value):
        raise d.SinkRejectedError("rejected", code=rejection)

    async def handle(req, plans):
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id,))

    async def realize(action, ctx, outputs):
        await outputs.emit(output())
        return completed(action)

    runtime, _ = routed_runtime(handle, realize)
    common = {"STALE_INTERACTION", "SINK_CLOSED", "BACKPRESSURE_TIMEOUT"}
    expected = rejection.name if rejection.name in common else "INTERNAL_ERROR"
    if side == "handle":
        report = await runtime.get_agent().handle_stimulus(request(), Sink(reject))
        assert report.emitted_plan_ids == ()
    else:
        if rejection in (d.SinkRejectionCode.IDENTITY_MISMATCH, d.SinkRejectionCode.CONTENT_CONFLICT):
            expected = "CONTRACT_MISMATCH"
        elif rejection is d.SinkRejectionCode.UNSUPPORTED_OUTPUT:
            expected = "UNSUPPORTED_OUTPUT"
        report = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
        assert report.output_started is False
        assert report.action_results[0].status is d.ActionExecutionStatus.FAILED
        assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert report.error_code.name == expected
    assert report.retryable is False


@pytest.mark.parametrize("change", [
    {"request_id": "foreign"}, {"trigger_stimulus_id": "foreign"},
    {"basis_interaction_revision": 4}, {"emitted_plan_ids": ("invented",)},
    {"considered_pending_stimulus_ids": ("foreign",), "consumed_pending_stimulus_ids": ("foreign",),
     "retained_pending_stimulus_ids": ()},
])
async def test_forged_handling_report_cannot_consume_pending(routed_runtime, change):
    plan, _ = plan_and_context()

    async def handle(req, plans):
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id,), **change) if "emitted_plan_ids" not in change else settlement(req, **change)

    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.emitted_plan_ids == (sink.values[0].plan_id,)
    assert report.retained_pending_stimulus_ids == ("m2", "m1")
    assert report.consumed_pending_stimulus_ids == ()


@pytest.mark.parametrize("invalid", ["complete_plan", "foreign_source", "dict", "list", "none"])
async def test_invalid_draft_is_rejected_before_external_sink(routed_runtime, invalid):
    # 绑定身份已不由 Handler 填写；保留来源拒绝，增加非法草稿输入覆盖同一入口边界。
    plan, _ = plan_and_context()
    sink = Sink()

    async def handle(req, plans):
        value = {"complete_plan": plan, "foreign_source": draft(sources=("foreign",)),
                 "dict": {}, "list": [], "none": None}[invalid]
        await plans.emit(value)
        return settlement(req)

    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.emitted_plan_ids == ()
    assert sink.values == []


@pytest.mark.parametrize("side", ["handle", "realize"])
async def test_receipt_identity_mismatch_is_not_success(routed_runtime, side):
    plan, context = plan_and_context()

    async def wrong_receipt(value):
        if side == "handle":
            return d.PlanReceipt(plan_id="foreign", status=d.PlanAcceptanceStatus.ACCEPTED)
        return d.OutputReceipt(execution_id="foreign", sequence_no=0, status=d.OutputAcceptanceStatus.ACCEPTED)

    async def handle(req, plans):
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id,))

    async def realize(action, ctx, outputs):
        await outputs.emit(output())
        return completed(action)

    runtime, _ = routed_runtime(handle, realize)
    if side == "handle":
        report = await runtime.get_agent().handle_stimulus(request(), Sink(wrong_receipt))
        assert report.emitted_plan_ids == ()
    else:
        report = await runtime.get_agent().realize_action_plan(plan, context, Sink(wrong_receipt))
        assert report.output_started is False
    assert report.error_code.name == "INTERNAL_ERROR"


async def test_successful_actions_preserve_plan_and_message_end_order(routed_runtime):
    plan, context = plan_and_context()
    sink = Sink()
    saved = []

    async def realize(action, ctx, outputs):
        assert outputs is not sink
        saved.append(outputs)
        if action.action_id == "a2":
            await outputs.emit(output())
            await outputs.emit(MessageEndDraft(
                delivery=d.OutputDelivery.CONVERSATION, status=d.MessageEndStatus.COMPLETED, error_code=None,
            ))
        else:
            await outputs.emit(output())
        return completed(action)

    runtime, _ = routed_runtime(realize=realize)
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert [r.action_id for r in report.action_results] == ["a2", "a1"]
    assert [v.kind for v in sink.values] == [d.AgentOutputKind.TEXT_FINAL, d.AgentOutputKind.MESSAGE_END, d.AgentOutputKind.TEXT_FINAL]
    assert report.output_started is True
    with pytest.raises(Exception):
        await saved[0].emit(output())
    assert len(sink.values) == 3


async def test_preflight_checks_later_unregistered_action_before_first_effect(routed_runtime):
    plan, context = plan_and_context()
    sink = Sink()

    async def realize(action, ctx, outputs):
        pytest.fail("整个计划预检失败不得执行首行动")

    runtime, _ = routed_runtime(realize=realize, action_kinds=(d.ActionKind.SAY,))
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.error_code is d.ExecutionErrorCode.UNSUPPORTED_ACTION
    assert all(r.status is d.ActionExecutionStatus.NOT_STARTED for r in report.action_results)
    assert sink.values == []


@pytest.mark.parametrize("error,code", [(TimeoutError(), d.ExecutionErrorCode.PROVIDER_TIMEOUT), (KeyError(), d.ExecutionErrorCode.INTERNAL_ERROR)])
async def test_action_error_keeps_prior_completion_and_output(routed_runtime, error, code):
    plan, context = plan_and_context()

    async def realize(action, ctx, outputs):
        if action.action_id == "a1":
            raise error
        await outputs.emit(output())
        return completed(action, irreversible_effect_committed=True,
                         effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="post"))

    runtime, _ = routed_runtime(realize=realize)
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert report.error_code is code
    assert report.output_started is True
    assert report.action_results[0].status is d.ActionExecutionStatus.COMPLETED
    assert report.action_results[0].effect_ref.effect_id == "post"
    assert report.action_results[1].status is d.ActionExecutionStatus.FAILED


@pytest.mark.parametrize("change", [{"action_id": "foreign"}, {"status": d.ActionExecutionStatus.NOT_STARTED}])
async def test_invalid_action_result_is_not_completed(routed_runtime, change):
    async def realize(action, ctx, outputs):
        await outputs.emit(output())
        return completed(action, **change)

    runtime, _ = routed_runtime(realize=realize)
    plan, context = plan_and_context()
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert report.error_code is d.ExecutionErrorCode.INTERNAL_ERROR
    assert report.output_started is True
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED


@pytest.mark.parametrize("change", [{"execution_id": "foreign"}, {"interaction_id": "foreign"}, {"action_id": "foreign"}])
async def test_foreign_output_is_rejected_before_sink(routed_runtime, change):
    async def realize(action, ctx, outputs):
        await outputs.emit(full_output(**change))
        return completed(action)

    runtime, _ = routed_runtime(realize=realize)
    plan, context = plan_and_context()
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.error_code is d.ExecutionErrorCode.INTERNAL_ERROR
    assert sink.values == []


async def test_cancellation_during_plan_acceptance_retains_receipt_and_stops_next_emit(routed_runtime):
    req = request()
    plan, _ = plan_and_context()
    accepted = []

    async def accept(value):
        accepted.append(value.plan_id)
        req.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return d.PlanReceipt(plan_id=value.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)

    async def handle(req, plans):
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        second = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id, second.plan_id))

    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(req, Sink(accept))
    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert report.emitted_plan_ids == tuple(accepted)
    assert len(accepted) == 1


async def test_cancel_after_action_preserves_effect_and_does_not_start_next(routed_runtime):
    plan, context = plan_and_context()
    observed = []

    async def realize(action, ctx, outputs):
        observed.append(action.action_id)
        ctx.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return completed(action, irreversible_effect_committed=True,
                         effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="post"))

    runtime, _ = routed_runtime(realize=realize)
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert report.status is d.ExecutionStatus.CANCELLED
    assert report.error_code is d.ExecutionErrorCode.CANCELLED
    assert report.action_results[0].status is d.ActionExecutionStatus.COMPLETED
    assert report.action_results[0].effect_ref.effect_id == "post"
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert observed == ["a2"]


async def test_concurrent_interactions_keep_receipts_separate(routed_runtime):
    started = asyncio.Event()
    release = asyncio.Event()
    plan, _ = plan_and_context()

    async def handle(req, plans):
        if req.request_id == "r":
            started.set()
            await release.wait()
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id,))

    runtime, _ = routed_runtime(handle=handle)
    first_sink, second_sink = Sink(), Sink()
    first = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), first_sink))
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        req = request()
        second_req = replace(req, request_id="other", interaction=replace(req.interaction, interaction_id="other"))
        second = await asyncio.wait_for(runtime.get_agent().handle_stimulus(second_req, second_sink), 0.5)
        assert second.emitted_plan_ids == (second_sink.values[0].plan_id,)
        assert second_sink.values[0].interaction_id == "other"
        release.set()
        assert (await first).emitted_plan_ids == (first_sink.values[0].plan_id,)
        assert first_sink.values[0].interaction_id == "i"
        assert first_sink.values[0].plan_id != second_sink.values[0].plan_id
    finally:
        release.set()
        await first

async def test_handler_can_reject_interaction_without_consumption(routed_runtime):
    async def handle(req, plans):
        return settlement(req, consumed=(), request_status=d.HandlingRequestStatus.FAILED,
                          error_code=d.HandlingErrorCode.UNSUPPORTED_INTERACTION)

    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is d.HandlingErrorCode.UNSUPPORTED_INTERACTION
    assert report.retained_pending_stimulus_ids == ("m2", "m1")


async def test_failed_handler_preserves_explicit_partial_settlement(routed_runtime):
    plan, _ = plan_and_context()

    async def handle(req, plans):
        receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
        return settlement(req, emitted=(receipt.plan_id,), request_status=d.HandlingRequestStatus.FAILED,
                          error_code=d.HandlingErrorCode.PROVIDER_TIMEOUT, retryable=True)

    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is d.HandlingErrorCode.PROVIDER_TIMEOUT
    assert report.consumed_pending_stimulus_ids == ("m2",)
    assert report.retained_pending_stimulus_ids == ("m1",)
    assert report.emitted_plan_ids == (sink.values[0].plan_id,)


async def test_failed_action_preserves_its_partial_effect(routed_runtime):
    async def realize(action, ctx, outputs):
        return completed(action, status=d.ActionExecutionStatus.FAILED,
                         error_code=d.ExecutionErrorCode.PROVIDER_TIMEOUT,
                         irreversible_effect_committed=True,
                         effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="post"))

    runtime, _ = routed_runtime(realize=realize)
    plan, context = plan_and_context()
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert report.error_code is d.ExecutionErrorCode.PROVIDER_TIMEOUT
    assert report.action_results[0].effect_ref.effect_id == "post"
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED


async def test_cancellation_during_output_acceptance_preserves_output_fact(routed_runtime):
    plan, context = plan_and_context()
    accepted = []

    async def accept(value):
        accepted.append(value)
        context.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return d.OutputReceipt(execution_id="e", sequence_no=0, status=d.OutputAcceptanceStatus.ACCEPTED)

    async def realize(action, ctx, outputs):
        await outputs.emit(output())
        await outputs.emit(output())
        return completed(action)

    runtime, _ = routed_runtime(realize=realize)
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink(accept))
    assert report.status is d.ExecutionStatus.CANCELLED
    assert report.output_started is True
    assert len(accepted) == 1
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED


async def test_late_handle_cancellation_preserves_returned_consumption(routed_runtime):
    async def handle(req, plans):
        req.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        return settlement(req)

    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert report.consumed_pending_stimulus_ids == ("m2",)
    assert report.retained_pending_stimulus_ids == ("m1",)


async def test_handler_error_logs_identity_and_stable_code(routed_runtime, caplog):
    from src.utils.logger import get_logger

    async def handle(req, plans):
        raise RuntimeError("fake-provider-error")

    logger = get_logger("src.agent.facade")
    logger.addHandler(caplog.handler)
    try:
        runtime, _ = routed_runtime(handle=handle)
        await runtime.get_agent().handle_stimulus(request(), Sink())
    finally:
        logger.removeHandler(caplog.handler)
    records = "\n".join(record.getMessage() for record in caplog.records)
    assert "INTERNAL_ERROR" in records
    assert "luotianyi" in records and "interaction_id=i" in records
    assert "fake-provider-error" in records or any(record.exc_info for record in caplog.records)
    assert "你好" not in records


@pytest.mark.parametrize("side", ["handle", "realize"])
async def test_cancel_before_worker_starts_does_not_invoke_handler(routed_runtime, side):
    calls = []

    async def handle(req, plans):
        calls.append("handle")
        return settlement(req)

    async def realize(action, ctx, outputs):
        calls.append(action.action_id)
        return completed(action)

    runtime, _ = routed_runtime(handle, realize)
    req = request()
    plan, context = plan_and_context()
    token = req.cancellation if side == "handle" else context.cancellation
    # 门面校验同步完成；已排队的取消先于新建处理器任务执行。
    asyncio.get_running_loop().call_soon(token.cancel, d.CancellationReason.SUPERSEDED)
    sink = Sink()
    if side == "handle":
        report = await runtime.get_agent().handle_stimulus(req, sink)
        assert report.request_status is d.HandlingRequestStatus.CANCELLED
        assert report.consumed_pending_stimulus_ids == ()
        assert report.retained_pending_stimulus_ids == ("m2", "m1")
    else:
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.status is d.ExecutionStatus.CANCELLED
        assert all(result.status is d.ActionExecutionStatus.NOT_STARTED for result in report.action_results)
    assert calls == []
    assert sink.values == []
