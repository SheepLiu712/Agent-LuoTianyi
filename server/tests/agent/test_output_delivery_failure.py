"""公开 realize 的未完成交付阻断、未知接收和输出日志。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from output_support import accepted, draft, failed, reject, single
from routing_support import Sink, completed, plan_and_context

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("with_remaining_action", [False, True])
async def test_confirmed_output_cancellation_preserves_completion_and_stops_next_action(
    routed_runtime, with_remaining_action,
):
    # 确认后取消保留已完成结果，停止后续行动。
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
    assert not first.retryable
    assert [(value.action_id, value.sequence_no) for value in delivered] == [("a2", 0)]
    await runtime.shutdown()


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


async def test_handler_catching_delivery_task_cancel_cannot_continue_delivery(routed_runtime):
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
    assert report.error_code is d.ExecutionErrorCode.CANCELLED
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
    assert report.error_code is d.ExecutionErrorCode.BACKPRESSURE_TIMEOUT and not report.retryable
    assert report.action_results[0].effect_ref.effect_id == "kept-effect"
    assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
    assert len(attempts) == 1 and not report.output_started


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


async def test_caught_output_rejection_still_logs_identity_without_payload(routed_runtime, caplog):
    from src.utils.logger import get_logger

    loggers = [get_logger(name) for name in ("src.agent.facade", "src.agent.processing.output_emitter")]
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
