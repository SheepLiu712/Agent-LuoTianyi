"""公开 realize 的执行身份、逐行动恢复和在途所有权契约。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from routing_support import Sink, completed, output, plan_and_context

pytestmark = pytest.mark.asyncio


def fresh(context, **changes):
    return replace(context, cancellation=d.CancellationToken(), **changes)


def failure(action, *, cancelled=False, effect=False):
    return completed(
        action, status=d.ActionExecutionStatus.CANCELLED if cancelled else d.ActionExecutionStatus.FAILED,
        error_code=d.ExecutionErrorCode.CANCELLED if cancelled else d.ExecutionErrorCode.PROVIDER_TIMEOUT,
        irreversible_effect_committed=effect,
        effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="post") if effect else None,
    )


def statuses(report):
    return tuple(item.status for item in report.action_results)


async def deliver(action, context, outputs):
    await outputs.emit(output())
    return completed(action, irreversible_effect_committed=True,
                     effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id=action.action_id))


@pytest.mark.parametrize("rebuild", [False, True])
async def test_completed_execution_replays_only_receipts_and_effect_facts(routed_runtime, rebuild):
    runtime, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    first_sink = Sink()
    first = await runtime.get_agent().realize_action_plan(plan, context, first_sink)
    if rebuild:
        await runtime.shutdown()
        runtime, _ = routed_runtime(realize=deliver)
    sink = Sink()
    replay = await runtime.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert statuses(replay) == (d.ActionExecutionStatus.ALREADY_COMPLETED,) * 2
    assert tuple(x.effect_ref for x in replay.action_results) == tuple(x.effect_ref for x in first.action_results)
    assert replay.output_started and replay.irreversible_effect_committed
    assert not replay.retryable and sink.values == []


@pytest.mark.parametrize("field", ["plan_id", "origin_request_id", "plan_ordinal", "sources", "order", "content", "tone", "song"])
async def test_execution_id_binds_complete_plan_values(routed_runtime, field):
    runtime, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    changes = {
        "plan_id": {"plan_id": "other"}, "origin_request_id": {"origin_request_id": "other"},
        "plan_ordinal": {"plan_ordinal": 2}, "sources": {"source_stimulus_ids": ("m1", "m2")},
        "order": {"actions": tuple(reversed(plan.actions))},
        "content": {"actions": (replace(plan.actions[0], content="不同内容"), plan.actions[1])},
        "tone": {"actions": (replace(plan.actions[0], tone=d.Tone(value="happy")), plan.actions[1])},
        "song": {"actions": (plan.actions[0], replace(plan.actions[1], song_id="another"))},
    }
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(replace(plan, **changes[field]), fresh(context), sink)
    assert report.error_code is d.ExecutionErrorCode.CONTRACT_MISMATCH
    assert not report.retryable and sink.values == []
    original = await runtime.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert statuses(original) == (d.ActionExecutionStatus.ALREADY_COMPLETED,) * 2


async def test_execution_and_character_keys_are_independent(routed_runtime):
    runtime, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    for agent, candidate, current in (
        (runtime.get_agent(), plan, fresh(context, execution_id="other")),
        (runtime.get_agent("miku"), replace(plan, target_character_id="miku"), fresh(context)),
    ):
        sink = Sink()
        report = await agent.realize_action_plan(candidate, current, sink)
        assert report.status is d.ExecutionStatus.COMPLETED and len(sink.values) == 2


@pytest.mark.parametrize("cancelled", [False, True])
async def test_completed_effect_and_output_prefix_does_not_block_safe_next_action(routed_runtime, cancelled):
    plan, context = plan_and_context()

    async def action_handler(action, current, outputs):
        if action.action_id == "a2":
            return await deliver(action, current, outputs)
        return failure(action, cancelled=cancelled)

    runtime, _ = routed_runtime(realize=action_handler)
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert first.retryable and first.output_started and first.irreversible_effect_committed
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert statuses(report) == (d.ActionExecutionStatus.ALREADY_COMPLETED, d.ActionExecutionStatus.COMPLETED)
    assert [value.action_id for value in sink.values] == ["a1"]


async def test_cancellation_after_completed_prefix_continues_only_unstarted_action(routed_runtime):
    plan, context = plan_and_context()

    async def action_handler(action, current, outputs):
        result = await deliver(action, current, outputs)
        current.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return result

    runtime, _ = routed_runtime(realize=action_handler)
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert first.status is d.ExecutionStatus.CANCELLED and first.retryable
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert statuses(report) == (d.ActionExecutionStatus.ALREADY_COMPLETED, d.ActionExecutionStatus.COMPLETED)
    assert [value.action_id for value in sink.values] == ["a1"]


@pytest.mark.parametrize("boundary", ["stale", "cancel", "route"])
async def test_resume_precheck_preserves_completed_prefix_and_allows_later_resume(routed_runtime, boundary):
    plan, context = plan_and_context()

    async def action_handler(action, current, outputs):
        return await deliver(action, current, outputs) if action.action_id == "a2" else failure(action)

    runtime, _ = routed_runtime(realize=action_handler)
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver, action_kinds=(d.ActionKind.SAY,) if boundary == "route"
                                    else (d.ActionKind.SAY, d.ActionKind.SING))
    current = fresh(context, current_interaction_revision=4 if boundary == "stale" else 3)
    if boundary == "cancel":
        current.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, current, sink)
    assert report.error_code is {"stale": d.ExecutionErrorCode.STALE_INTERACTION,
                                 "cancel": d.ExecutionErrorCode.CANCELLED,
                                 "route": d.ExecutionErrorCode.UNSUPPORTED_ACTION}[boundary]
    assert statuses(report) == (d.ActionExecutionStatus.ALREADY_COMPLETED, d.ActionExecutionStatus.NOT_STARTED)
    assert report.output_started and report.irreversible_effect_committed and not report.retryable
    assert sink.values == []
    await replacement.shutdown()
    final, _ = routed_runtime(realize=deliver)
    resumed = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert resumed.status is d.ExecutionStatus.COMPLETED
    assert [value.action_id for value in sink.values] == ["a1"]


async def test_completed_terminal_ignores_new_cancel_revision_and_missing_route(routed_runtime):
    runtime, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    await runtime.shutdown()
    replacement, _ = routed_runtime()
    current = fresh(context, current_interaction_revision=999)
    current.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, current, sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert statuses(report) == (d.ActionExecutionStatus.ALREADY_COMPLETED,) * 2
    assert report.output_started and sink.values == []


@pytest.mark.parametrize("mode", ["effect", "accepted", "unknown", "accepted_then_unknown", "unknown_then_rejected"])
async def test_unsafe_failed_action_never_reexecutes_even_if_handler_claims_no_effect(routed_runtime, mode):
    plan, context = plan_and_context()

    async def sink_emit(value):
        if mode == "unknown_then_rejected" and value.sequence_no == 1:
            raise d.SinkRejectedError("rejected", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        raise TimeoutError("receipt lost")

    sink = Sink(sink_emit) if "unknown" in mode else Sink()

    async def action_handler(action, current, outputs):
        if mode == "effect":
            return failure(action, effect=True)
        for sequence in range(2 if "then" in mode else 1):
            try:
                if mode == "accepted_then_unknown" and sequence == 0:
                    sink.callback = None
                elif mode == "accepted_then_unknown":
                    sink.callback = sink_emit
                await outputs.emit(output())
            except (TimeoutError, d.SinkRejectedError):
                pass
        return failure(action)

    runtime, _ = routed_runtime(realize=action_handler)
    first = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert not first.retryable
    assert first.output_started is (mode in {"accepted", "accepted_then_unknown"})
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    replay_sink = Sink()
    replay = await replacement.get_agent().realize_action_plan(plan, fresh(context), replay_sink)
    assert replay.status is d.ExecutionStatus.FAILED and not replay.retryable
    assert replay.action_results[0].effect_ref == first.action_results[0].effect_ref
    assert replay.output_started == first.output_started and replay_sink.values == []


async def test_unknown_handler_exception_cannot_be_retried_as_no_effect_timeout(routed_runtime):
    async def action_handler(action, context, outputs):
        raise TimeoutError("effect may have committed")
    runtime, _ = routed_runtime(realize=action_handler)
    plan, context = plan_and_context()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert first.error_code is d.ExecutionErrorCode.PROVIDER_TIMEOUT and not first.retryable
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    replay = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert replay.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert not replay.retryable and sink.values == []


@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_same_execution_singleflight_waiter_does_not_own_execution(routed_runtime, cancel_waiter):
    entered, release = asyncio.Event(), asyncio.Event()

    async def action_handler(action, context, outputs):
        entered.set()
        await release.wait()
        return await deliver(action, context, outputs)

    runtime, _ = routed_runtime(realize=action_handler)
    plan, context = plan_and_context()
    owner = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink()))
    await asyncio.wait_for(entered.wait(), 1)
    sink = Sink()
    waiter = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, fresh(context), sink))
    try:
        await asyncio.sleep(0)
        if cancel_waiter:
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not owner.done() and not context.cancellation.is_cancelled
        release.set()
        result = await asyncio.wait_for(owner, 1)
        if not cancel_waiter:
            assert await asyncio.wait_for(waiter, 1) == result
        assert sink.values == []
    finally:
        release.set()
        await asyncio.gather(owner, waiter, return_exceptions=True)


async def test_other_runtime_cannot_take_live_execution_and_conflict_does_not_wait(routed_runtime):
    entered, release = asyncio.Event(), asyncio.Event()

    async def action_handler(action, context, outputs):
        entered.set()
        await release.wait()
        return await deliver(action, context, outputs)

    runtime, _ = routed_runtime(realize=action_handler)
    second, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    owner = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink()))
    await asyncio.wait_for(entered.wait(), 1)
    sink = Sink()
    try:
        report = await asyncio.wait_for(second.get_agent().realize_action_plan(plan, fresh(context), sink), 1)
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
        conflict = await asyncio.wait_for(runtime.get_agent().realize_action_plan(
            replace(plan, plan_id="other"), fresh(context), sink), 1)
        assert conflict.error_code is d.ExecutionErrorCode.CONTRACT_MISMATCH
        assert sink.values == []
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)


async def test_owner_cancel_keeps_unknown_started_action_and_releases_waiter(routed_runtime):
    entered = asyncio.Event()

    async def action_handler(action, context, outputs):
        entered.set()
        await asyncio.Event().wait()

    runtime, _ = routed_runtime(realize=action_handler)
    plan, context = plan_and_context()
    owner = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink()))
    await asyncio.wait_for(entered.wait(), 1)
    waiter = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, fresh(context), Sink()))
    await asyncio.sleep(0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    try:
        report = await asyncio.wait_for(waiter, .1)
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and sink.values == []


async def test_owner_task_cancel_preserves_trusted_result_returned_during_cleanup(routed_runtime):
    entered = asyncio.Event()

    async def action_handler(action, context, outputs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return completed(action, irreversible_effect_committed=True,
                             effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="cleanup-effect"))

    runtime, _ = routed_runtime(realize=action_handler)
    plan, context = plan_and_context()
    owner = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink()))
    await asyncio.wait_for(entered.wait(), 1)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert statuses(report) == (d.ActionExecutionStatus.ALREADY_COMPLETED, d.ActionExecutionStatus.COMPLETED)
    assert report.action_results[0].effect_ref.effect_id == "cleanup-effect"
    assert [value.action_id for value in sink.values] == ["a1"]


async def test_cancelled_owner_waiter_keeps_facts_committed_after_it_joined(routed_runtime):
    entered, release, second = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def action_handler(action, context, outputs):
        if action.action_id == "a2":
            entered.set()
            await release.wait()
            return await deliver(action, context, outputs)
        second.set()
        await asyncio.Event().wait()

    runtime, _ = routed_runtime(realize=action_handler)
    plan, context = plan_and_context()
    owner = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink()))
    await asyncio.wait_for(entered.wait(), 1)
    sink = Sink()
    waiter = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, fresh(context), sink))
    try:
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(second.wait(), 1)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        report = await asyncio.wait_for(waiter, 1)
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
        assert report.output_started and report.irreversible_effect_committed
        assert report.action_results[0].status is d.ActionExecutionStatus.ALREADY_COMPLETED
        assert report.action_results[0].effect_ref.effect_id == "a2"
        assert sink.values == []
    finally:
        release.set()
        owner.cancel()
        await asyncio.gather(owner, waiter, return_exceptions=True)


async def test_shutdown_waits_for_execution_owner_and_joiner(routed_runtime):
    entered, release = asyncio.Event(), asyncio.Event()

    async def action_handler(action, context, outputs):
        entered.set()
        await release.wait()
        return await deliver(action, context, outputs)

    runtime, store = routed_runtime(realize=action_handler)
    runtime.shutdown_timeout_seconds = .02
    plan, context = plan_and_context()
    owner = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink()))
    await asyncio.wait_for(entered.wait(), 1)
    sink = Sink()
    waiter = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, fresh(context), sink))
    try:
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await runtime.shutdown()
        assert store.close_calls == 0
        release.set()
        left, right = await asyncio.wait_for(asyncio.gather(owner, waiter), 1)
        assert left == right and sink.values == []
        await runtime.shutdown()
        assert store.close_calls == 1
    finally:
        release.set()
        await asyncio.gather(owner, waiter, return_exceptions=True)
