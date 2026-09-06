"""公开 realize 的原输出恢复、可信行动分流和取消所有权。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from output_support import accepted, draft, failed, fresh, no_reentry, reject, single
from routing_support import Sink, completed, plan_and_context

pytestmark = pytest.mark.asyncio


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


@pytest.mark.parametrize("kind", ["TextFinal", "AudioChunk", "MessageEnd", "Expression"])
async def test_completed_action_recovers_original_payload_without_handler_reentry(routed_runtime, kind):
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
    plan, context = single()
    await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED and report.output_started and not report.retryable
    assert report.action_results[0].status is d.ActionExecutionStatus.ALREADY_COMPLETED
    assert sink.values == attempted and len(sink.values) == 1
    await replacement.shutdown()
    final, _ = routed_runtime(realize=no_reentry)
    final_sink = Sink()
    replay = await final.get_agent().realize_action_plan(plan, fresh(context), final_sink)
    assert replay.status is d.ExecutionStatus.COMPLETED and replay.output_started
    assert final_sink.values == []


@pytest.mark.parametrize("cancelled", [False, True])
async def test_unsafe_failed_action_only_recovers_output_and_retains_original_failure(routed_runtime, cancelled):
    async def initial(action, context, outputs):
        try:
            await outputs.emit(draft("TextFinal", action, context))
        except d.SinkRejectedError:
            pass
        return failed(action, cancelled=cancelled, effect=True)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = plan_and_context()
    original = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    assert original.retryable  # 这里只允许补投原输出，不表示可以重跑有副作用的行动。
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert len(sink.values) == 1 and sink.values[0].sequence_no == 0
    assert report.status is original.status and report.error_code is original.error_code
    assert report.action_results[0].effect_ref == original.action_results[0].effect_ref
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert report.output_started and not report.retryable


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


@pytest.mark.parametrize("gate", ["revision", "cancel", "route"])
async def test_output_only_recovery_checks_current_admission_without_losing_facts(routed_runtime, gate):
    runtime, _ = routed_runtime(realize=pending_completed)
    plan, context = single()
    await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry,
                                    action_kinds=() if gate == "route" else (d.ActionKind.SAY,))
    current = fresh(context, current_interaction_revision=99 if gate == "revision" else 3)
    if gate == "cancel":
        current.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, current, sink)
    assert report.error_code is {"revision": d.ExecutionErrorCode.STALE_INTERACTION,
                                 "cancel": d.ExecutionErrorCode.CANCELLED,
                                 "route": d.ExecutionErrorCode.UNSUPPORTED_ACTION}[gate]
    assert report.irreversible_effect_committed and not report.retryable and sink.values == []
    await replacement.shutdown()
    final, _ = routed_runtime(realize=no_reentry)
    recovered = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert recovered.status is d.ExecutionStatus.COMPLETED and len(sink.values) == 1


async def test_recovery_waiter_cancel_and_shutdown_wait_for_owned_sink(routed_runtime):
    runtime, _ = routed_runtime(realize=pending_completed)
    plan, context = single()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    assert first.retryable  # 当前实现没有 pending，必须先证明缺失，不能用等待超时制造 RED。
    await runtime.shutdown()
    replacement, store = routed_runtime(realize=no_reentry)
    close_before = store.close_calls
    replacement.shutdown_timeout_seconds = .02
    entered, release = asyncio.Event(), asyncio.Event()

    async def receiver(value):
        entered.set()
        await release.wait()
        return accepted(value)

    owner = asyncio.create_task(replacement.get_agent().realize_action_plan(plan, fresh(context), Sink(receiver)))
    waiter = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        waiter_sink = Sink()
        waiter = asyncio.create_task(replacement.get_agent().realize_action_plan(plan, fresh(context), waiter_sink))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        with pytest.raises(RuntimeError):
            await replacement.shutdown()
        assert not owner.done() and store.close_calls == close_before
        release.set()
        report = await asyncio.wait_for(owner, 1)
        assert report.status is d.ExecutionStatus.COMPLETED and report.output_started
        assert waiter_sink.values == []
        await replacement.shutdown()
        assert store.close_calls == close_before + 1
    finally:
        release.set()
        await asyncio.gather(*(task for task in (owner, waiter) if task is not None), return_exceptions=True)


@pytest.mark.parametrize("trusted_receipt", [False, True])
async def test_recovery_owner_cancel_keeps_receipt_or_unknown_after_cleanup(routed_runtime, trusted_receipt):
    runtime, _ = routed_runtime(realize=pending_completed)
    plan, context = single()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    assert first.retryable
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    entered = asyncio.Event()

    async def receiver(value):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if trusted_receipt:
                return accepted(value)
            raise

    owner = asyncio.create_task(replacement.get_agent().realize_action_plan(plan, fresh(context), Sink(receiver)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
    finally:
        owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
    await replacement.shutdown()
    final, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    if trusted_receipt:
        assert report.status is d.ExecutionStatus.COMPLETED and report.output_started
    else:
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
    assert report.irreversible_effect_committed and sink.values == []


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
