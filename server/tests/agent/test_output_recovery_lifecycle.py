"""仅投递恢复的执行所有权、取消清理和关闭等待。"""
import asyncio

import pytest
from sqlalchemy import event

import src.domain.agent as d
from output_support import accepted, draft, fresh, no_reentry, reject, single
from routing_support import Sink, completed

pytestmark = pytest.mark.asyncio


async def pending_completed(action, context, outputs):
    try:
        await outputs.emit(draft("AudioChunk", action, context))
    except d.SinkRejectedError:
        pass
    return completed(action, irreversible_effect_committed=True,
                     effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="kept-effect"))


@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_recovery_waiter_cancel_and_shutdown_wait_for_owned_sink(routed_runtime, cancel_waiter):
    runtime, _ = routed_runtime(realize=pending_completed)
    plan, context = single()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    assert first.retryable  # 先观察恢复资格；尚未实现时不以等待事件超时制造 RED。
    await runtime.shutdown()
    replacement, store = routed_runtime(realize=no_reentry)
    other, _ = routed_runtime(realize=no_reentry)
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
        other_sink = Sink()
        occupied = await other.get_agent().realize_action_plan(plan, fresh(context), other_sink)
        assert occupied.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        assert occupied.irreversible_effect_committed and not occupied.retryable
        assert other_sink.values == []
        if cancel_waiter:
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        with pytest.raises(RuntimeError):
            await replacement.shutdown()
        assert not owner.done() and store.close_calls == close_before
        release.set()
        report = await asyncio.wait_for(owner, 1)
        assert report.status is d.ExecutionStatus.COMPLETED and report.output_started
        if not cancel_waiter:
            assert await asyncio.wait_for(waiter, 1) == report
        assert waiter_sink.values == []
        replacement.shutdown_timeout_seconds = 1
        await replacement.shutdown()
        assert store.close_calls == close_before + 1
    finally:
        release.set()
        await asyncio.gather(*(task for task in (owner, waiter) if task is not None), return_exceptions=True)


@pytest.mark.parametrize("receipt_mode", ["unknown", "accepted", "ack_once", "ack_persistent"])
async def test_recovery_owner_cancel_keeps_receipt_or_unknown_after_cleanup(
    routed_runtime, runtime_dependencies, receipt_mode,
):
    runtime, _ = routed_runtime(realize=pending_completed)
    plan, context = single()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    assert first.retryable
    await runtime.shutdown()
    replacement, store = routed_runtime(realize=no_reentry)
    close_before = store.close_calls
    replacement.shutdown_timeout_seconds = .02
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sessions = runtime_dependencies[0]["database_manager"].open_sql_session
    failing = False

    def fail_commit(session):
        nonlocal failing
        if failing:
            failing = receipt_mode == "ack_persistent"
            raise RuntimeError("cannot save cleanup receipt")

    async def receiver(value):
        nonlocal failing
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            if receipt_mode != "unknown":
                failing = receipt_mode.startswith("ack_")
                return accepted(value)
            raise

    event.listen(sessions, "before_commit", fail_commit)
    owner = asyncio.create_task(replacement.get_agent().realize_action_plan(plan, fresh(context), Sink(receiver)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        owner.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        owner.cancel()  # 第二次取消不能击穿 sink 清理或提前释放恢复执行权。
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await replacement.shutdown()
        assert not owner.done() and store.close_calls == close_before
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, 1)
    finally:
        release.set()
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
        failing = False
        event.remove(sessions, "before_commit", fail_commit)
    replacement.shutdown_timeout_seconds = 1
    await replacement.shutdown()
    final, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await final.get_agent().realize_action_plan(plan, fresh(context), sink)
    if receipt_mode in {"accepted", "ack_once"}:
        assert report.status is d.ExecutionStatus.COMPLETED and report.output_started
    else:
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
    assert report.irreversible_effect_committed and sink.values == []
