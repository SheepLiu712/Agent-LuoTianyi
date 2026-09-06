"""公开 realize 的未完成交付阻断、未知接收和输出日志。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from output_support import accepted, draft, failed, fresh, no_reentry, reject, single
from routing_support import Sink, completed, plan_and_context

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("with_remaining_action", [False, True])
async def test_confirmed_output_cancellation_preserves_completion_and_safe_continuation(
    routed_runtime, with_remaining_action,
):
    # execution-ledger: 确认后取消保留可信完成，只从未开始行动继续。
    plan, context = plan_and_context() if with_remaining_action else single()
    delivered = []
    effect = d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="completed-before-cancellation")

    async def receiver(value):
        delivered.append(value)
        context.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return accepted(value)

    async def handler(action, current, outputs):
        try:
            await outputs.emit(draft("TextFinal", action, current))
        except Exception:
            pass  # 已完成业务的清理可以捕获取消，随后返回可信完成事实。
        return completed(action, irreversible_effect_committed=True, effect_ref=effect)

    runtime, _ = routed_runtime(realize=handler)
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    assert first.status is d.ExecutionStatus.CANCELLED
    assert first.error_code is d.ExecutionErrorCode.CANCELLED
    assert first.output_started
    assert first.action_results[0] == completed(
        plan.actions[0], irreversible_effect_committed=True, effect_ref=effect,
    )
    assert [result.status for result in first.action_results[1:]] == (
        [d.ActionExecutionStatus.NOT_STARTED] if with_remaining_action else []
    )
    assert first.retryable is with_remaining_action
    assert [(value.action_id, value.sequence_no) for value in delivered] == [("a2", 0)]
    await runtime.shutdown()

    async def remaining(action, current, outputs):
        await outputs.emit(draft("TextFinal", action, current))
        return completed(action)

    replacement, _ = routed_runtime(realize=remaining)
    replay_sink = Sink()
    replay = await replacement.get_agent().realize_action_plan(plan, fresh(context), replay_sink)
    assert replay.status is d.ExecutionStatus.COMPLETED and replay.output_started
    assert not replay.retryable
    assert replay.action_results[0] == completed(
        plan.actions[0], status=d.ActionExecutionStatus.ALREADY_COMPLETED,
        irreversible_effect_committed=True, effect_ref=effect,
    )
    assert [result.status for result in replay.action_results[1:]] == (
        [d.ActionExecutionStatus.COMPLETED] if with_remaining_action else []
    )
    assert [(value.action_id, value.sequence_no) for value in replay_sink.values] == (
        [("a1", 1)] if with_remaining_action else []
    )


async def test_confirmed_output_cancellation_cannot_override_trusted_failure(routed_runtime):
    # handler-routing: 可信 FAILED 优先于晚到取消，并保留实际效果及确认事实。
    plan, context = plan_and_context()
    delivered = []

    async def receiver(value):
        delivered.append(value)
        context.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return accepted(value)

    async def handler(action, current, outputs):
        try:
            await outputs.emit(draft("TextFinal", action, current))
        except Exception:
            pass
        return failed(action, effect=True)

    runtime, _ = routed_runtime(realize=handler)
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    assert first.status is d.ExecutionStatus.FAILED
    assert first.error_code is d.ExecutionErrorCode.PROVIDER_TIMEOUT
    assert first.action_results[0] == failed(plan.actions[0], effect=True)
    assert first.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert first.output_started and not first.retryable
    assert [(value.action_id, value.sequence_no) for value in delivered] == [("a2", 0)]
    await runtime.shutdown()

    replacement, _ = routed_runtime(realize=no_reentry)
    replay_sink = Sink()
    replay = await replacement.get_agent().realize_action_plan(plan, fresh(context), replay_sink)
    assert replay == first
    assert replay_sink.values == []


async def test_handler_catching_delivery_task_cancel_cannot_reemit_unknown_slot(routed_runtime):
    attempts = []

    async def receiver(value):
        attempts.append(value)
        if len(attempts) == 1:
            raise asyncio.CancelledError()
        return accepted(value)

    async def handler(action, context, outputs):
        for _ in range(2):
            try:
                await outputs.emit(draft("TextFinal", action, context))
            except (asyncio.CancelledError, Exception):
                pass
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    assert len(attempts) == 1
    assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert not report.retryable and not report.output_started


async def pending_completed(action, context, outputs):
    try:
        await outputs.emit(draft("AudioChunk", action, context,
                                 delivery=d.OutputDelivery.EPHEMERAL_REACTION))
    except d.SinkRejectedError:
        pass
    return completed(action, irreversible_effect_committed=True,
                     effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="kept-effect"))


async def test_completed_handler_with_rejected_output_cannot_start_next_action(routed_runtime):
    runtime, _ = routed_runtime(realize=pending_completed)
    plan, context = plan_and_context()
    attempts = []

    async def receiver(value):
        attempts.append(value)
        return await reject(value)

    report = await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    assert report.error_code is d.ExecutionErrorCode.BACKPRESSURE_TIMEOUT and report.retryable
    assert report.action_results[0].effect_ref.effect_id == "kept-effect"
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert len(attempts) == 1 and not report.output_started


async def test_safe_reentry_that_omits_pending_cannot_drop_it_or_begin_next_action(routed_runtime):
    async def initial(action, context, outputs):
        try:
            await outputs.emit(draft("TextFinal", action, context))
        except d.SinkRejectedError:
            pass
        return failed(action)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = plan_and_context()
    await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    await runtime.shutdown()

    async def omit(action, current, outputs):
        return completed(action)

    replacement, _ = routed_runtime(realize=omit)
    intermediate_sink = Sink()
    intermediate = await replacement.get_agent().realize_action_plan(plan, fresh(context), intermediate_sink)
    assert intermediate.status is d.ExecutionStatus.FAILED and intermediate.retryable
    assert intermediate.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert intermediate_sink.values == []
    await replacement.shutdown()

    async def remainder(action, current, outputs):
        if action.action_id == "a2":
            return await no_reentry(action, current, outputs)
        return completed(action)

    final, _ = routed_runtime(realize=remainder)
    sink = Sink()
    report = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert [(value.action_id, value.sequence_no, value.text) for value in sink.values] == [("a2", 0, "原始文字")]


@pytest.mark.parametrize("mode", ["timeout", "wrong_receipt", "accepted_then_timeout"])
async def test_unknown_delivery_remains_blocked_even_when_handler_returns_completed(routed_runtime, mode):
    attempts = []

    async def receiver(value):
        attempts.append(value)
        if mode == "accepted_then_timeout" and len(attempts) == 1:
            return accepted(value)
        if mode == "wrong_receipt":
            return replace(accepted(value), sequence_no=99)
        raise TimeoutError("unconfirmed receipt")

    async def handler(action, context, outputs):
        for index in range(3):
            try:
                await outputs.emit(draft("TextFinal", action, context, text=str(index)))
            except Exception:
                pass
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = plan_and_context()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    expected = d.ExecutionErrorCode.INTERNAL_ERROR if mode == "wrong_receipt" else d.ExecutionErrorCode.PROVIDER_TIMEOUT
    assert first.error_code is expected and not first.retryable
    assert first.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert len(attempts) == (2 if mode == "accepted_then_timeout" else 1)
    assert first.output_started is (mode == "accepted_then_timeout")
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
    assert report.output_started is first.output_started and sink.values == []
    assert report.action_results[0].status is d.ActionExecutionStatus.FAILED
    assert report.action_results[0].error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE


async def test_caught_output_rejection_still_logs_identity_without_payload(routed_runtime, caplog):
    from src.utils.logger import get_logger

    loggers = [get_logger(name) for name in ("src.agent.facade", "src.agent.outputs.emitter")]
    for logger in loggers:
        logger.addHandler(caplog.handler)
    try:
        runtime, _ = routed_runtime(realize=pending_completed)
        plan, context = single()
        await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
        assert "BACKPRESSURE_TIMEOUT" in caplog.text
        assert "action_id=a2" in caplog.text and "sequence" in caplog.text
        assert "private receiver content" not in caplog.text and "RIFF" not in caplog.text
    finally:
        for logger in loggers:
            logger.removeHandler(caplog.handler)


@pytest.mark.parametrize("kind", ["TextFinal", "AudioChunk", "MessageEnd", "Expression"])
@pytest.mark.parametrize("with_remaining_action", [False, True])
async def test_completed_action_recovers_original_payload_without_handler_reentry(
    routed_runtime, kind, with_remaining_action,
):
    attempted = []

    async def receiver(value):
        attempted.append(value)
        return await reject(value)

    async def initial(action, context, outputs):
        try:
            await outputs.emit(draft(kind, action, context, delivery=d.OutputDelivery.EPHEMERAL_REACTION))
        except d.SinkRejectedError:
            pass
        return completed(action)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = plan_and_context() if with_remaining_action else single()
    await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    await runtime.shutdown()

    async def remaining(action, current, outputs):
        if action.action_id == "a2":
            return await no_reentry(action, current, outputs)
        await outputs.emit(draft("Expression", action, current))
        return completed(action)

    replacement, _ = routed_runtime(realize=remaining)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED and report.output_started and not report.retryable
    assert report.action_results[0].status is d.ActionExecutionStatus.ALREADY_COMPLETED
    assert sink.values[:1] == attempted and len(attempted) == 1
    assert [(value.action_id, value.sequence_no) for value in sink.values] == (
        [("a2", 0), ("a1", 1)] if with_remaining_action else [("a2", 0)]
    )
    assert [result.status for result in report.action_results[1:]] == (
        [d.ActionExecutionStatus.COMPLETED] if with_remaining_action else []
    )
    await replacement.shutdown()
    final, _ = routed_runtime(realize=no_reentry)
    final_sink = Sink()
    replay = await final.get_agent().realize_action_plan(plan, fresh(context), final_sink)
    assert replay.status is d.ExecutionStatus.COMPLETED and replay.output_started
    assert final_sink.values == []


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("unsafe_fact", ["effect", "confirmed"])
@pytest.mark.parametrize("reject_recovery", [False, True])
async def test_unsafe_failed_action_only_recovers_output_and_retains_original_failure(
    routed_runtime, cancelled, unsafe_fact, reject_recovery,
):
    attempted = []

    async def initial_receiver(value):
        attempted.append(value)
        if unsafe_fact == "confirmed" and value.sequence_no == 0:
            return accepted(value)
        return await reject(value)

    async def initial(action, context, outputs):
        try:
            if unsafe_fact == "confirmed":
                await outputs.emit(draft("Expression", action, context))
            await outputs.emit(draft("TextFinal", action, context))
        except d.SinkRejectedError:
            pass
        return failed(action, cancelled=cancelled, effect=unsafe_fact == "effect")

    runtime, _ = routed_runtime(realize=initial)
    plan, context = plan_and_context()
    original = await runtime.get_agent().realize_action_plan(plan, context, Sink(initial_receiver))
    assert original.retryable  # 这里只允许补投原输出，不表示可以重跑有副作用的行动。
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    if reject_recovery:
        rejected = []

        async def reject_again(value):
            rejected.append(value)
            return await reject(value)

        incomplete = await replacement.get_agent().realize_action_plan(plan, fresh(context), Sink(reject_again))
        assert incomplete.status is original.status and incomplete.error_code is original.error_code
        assert incomplete.action_results == original.action_results and incomplete.retryable
        assert rejected == attempted[-1:]  # 一次调用只补投一次，且使用持久原值。
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert sink.values == attempted[-1:]
    assert report.status is original.status and report.error_code is original.error_code
    assert report.action_results[0].effect_ref == original.action_results[0].effect_ref
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert report.output_started and not report.retryable


@pytest.mark.parametrize("gate", ["revision", "cancel", "route", "later_route"])
@pytest.mark.parametrize("settlement", ["completed", "failed", "cancelled"])
async def test_output_only_recovery_checks_current_admission_without_losing_facts(
    routed_runtime, gate, settlement,
):
    async def initial(action, current, outputs):
        result = await pending_completed(action, current, outputs)
        return result if settlement == "completed" else failed(
            action, cancelled=settlement == "cancelled", effect=True,
        )

    runtime, _ = routed_runtime(realize=initial)
    plan, context = plan_and_context()
    original = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    await runtime.shutdown()
    kinds = {"route": (), "later_route": (d.ActionKind.SAY,)}.get(
        gate, (d.ActionKind.SAY, d.ActionKind.SING),
    )
    replacement, _ = routed_runtime(realize=no_reentry,
                                    action_kinds=kinds)
    current = fresh(context, current_interaction_revision=99 if gate == "revision" else 3)
    if gate == "cancel":
        current.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, current, sink)
    assert report.error_code is {"revision": d.ExecutionErrorCode.STALE_INTERACTION,
                                 "cancel": d.ExecutionErrorCode.CANCELLED,
                                 "route": d.ExecutionErrorCode.UNSUPPORTED_ACTION,
                                 "later_route": d.ExecutionErrorCode.UNSUPPORTED_ACTION}[gate]
    assert report.irreversible_effect_committed and not report.retryable and sink.values == []
    assert report.action_results[0].effect_ref == original.action_results[0].effect_ref
    assert report.output_started is original.output_started
    if settlement == "completed":
        assert report.action_results[0].status is d.ActionExecutionStatus.ALREADY_COMPLETED
    else:
        assert report.action_results[0].error_code is report.error_code
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    await replacement.shutdown()

    async def remaining(action, current, outputs):
        if action.action_id == "a2":
            return await no_reentry(action, current, outputs)
        return completed(action)

    final, _ = routed_runtime(realize=remaining)
    recovered = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert len(sink.values) == 1 and not recovered.retryable
    if settlement == "completed":
        assert recovered.status is d.ExecutionStatus.COMPLETED
        assert recovered.action_results[0].status is d.ActionExecutionStatus.ALREADY_COMPLETED
    else:
        assert recovered.status is original.status and recovered.error_code is original.error_code
        assert recovered.action_results == original.action_results


@pytest.mark.parametrize("mode", ["timeout", "wrong_receipt"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_output_recovery_unknown_projects_error_without_erasing_effects(routed_runtime, mode, cancelled):
    async def initial(action, context, outputs):
        await pending_completed(action, context, outputs)
        return failed(action, cancelled=cancelled, effect=True)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = single()
    original = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    attempts = []

    async def receiver(value):
        attempts.append(value)
        if mode == "wrong_receipt":
            return replace(accepted(value), sequence_no=99)
        raise TimeoutError("unknown recovery receipt")

    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), Sink(receiver))
    expected = d.ExecutionErrorCode.INTERNAL_ERROR if mode == "wrong_receipt" else d.ExecutionErrorCode.PROVIDER_TIMEOUT
    assert len(attempts) == 1
    assert report.status is d.ExecutionStatus.FAILED and report.error_code is expected
    assert report.action_results[0].effect_ref == original.action_results[0].effect_ref
    assert report.irreversible_effect_committed and not report.output_started and not report.retryable
    await replacement.shutdown()
    final, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    replay = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert replay.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not replay.retryable
    assert replay.action_results[0].effect_ref == original.action_results[0].effect_ref
    assert sink.values == []
