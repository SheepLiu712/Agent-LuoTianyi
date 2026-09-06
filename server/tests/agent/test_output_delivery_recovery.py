"""公开 realize 的未完成交付阻断、未知接收和输出日志。"""
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
    assert report.error_code is d.ExecutionErrorCode.BACKPRESSURE_TIMEOUT and not report.retryable
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
    assert intermediate.status is d.ExecutionStatus.FAILED and not intermediate.retryable
    assert intermediate.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert intermediate_sink.values == []
    await replacement.shutdown()

    final, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.FAILED and not report.retryable
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert sink.values == []


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
