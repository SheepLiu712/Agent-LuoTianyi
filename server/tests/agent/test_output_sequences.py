"""公开 realize 的生产者身份、连续序列与已持久槽位内容约束。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from output_support import accepted, draft, failed, fresh, reject, single
from routing_support import Sink, completed, full_output, plan_and_context

pytestmark = pytest.mark.asyncio


async def test_agent_assigns_cross_action_identity_and_preserves_all_output_fields(routed_runtime):
    plan, context = plan_and_context()
    context = fresh(context, execution_id="assigned-execution")
    plan = replace(plan, interaction_id="assigned-interaction")
    context = replace(context, interaction_id=plan.interaction_id)

    async def handler(action, current, outputs):
        for kind in ("TextFinal", "AudioChunk", "MessageEnd", "Expression"):
            await outputs.emit(draft(kind, action, current))
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert [value.sequence_no for value in sink.values] == list(range(8))
    assert [value.action_id for value in sink.values] == ["a2"] * 4 + ["a1"] * 4
    assert all(value.execution_id == "assigned-execution" and value.interaction_id == "assigned-interaction"
               for value in sink.values)
    for start in (0, 4):
        text, audio, end, expression = sink.values[start:start + 4]
        assert text.text == "原始文字"
        assert audio.data == b"RIFF\x00\xff\x10\x80WAVE" and audio.framing is d.AudioFraming.FILE_FRAGMENT
        assert end.status is d.MessageEndStatus.FAILED and end.error_code is d.AudioErrorCode.EMPTY_AUDIO
        assert expression.expression == d.ChangeExpression(expression_id="happy")
        assert all(value.delivery is d.OutputDelivery.CONVERSATION for value in (text, audio, end, expression))


async def test_concurrent_handler_emits_wait_for_prior_receipt_and_use_next_sequence(routed_runtime):
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    async def receiver(value):
        delivered.append(value)
        if len(delivered) == 1:
            entered.set()
            await release.wait()
        return accepted(value)

    async def handler(action, context, outputs):
        await asyncio.gather(*(outputs.emit(draft("TextFinal", action, context, text=str(index)))
                               for index in range(3)))
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    task = asyncio.create_task(runtime.get_agent().realize_action_plan(plan, context, Sink(receiver)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.sleep(0)
        assert len(delivered) == 1
        release.set()
        report = await asyncio.wait_for(task, 1)
        assert report.status is d.ExecutionStatus.COMPLETED
        assert [(value.sequence_no, value.text) for value in delivered] == [(0, "0"), (1, "1"), (2, "2")]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_completed_prefix_sequence_survives_runtime_rebuild(routed_runtime):
    async def initial(action, context, outputs):
        if action.action_id == "a1":
            return failed(action)
        await outputs.emit(draft("TextFinal", action, context))
        await outputs.emit(draft("AudioChunk", action, context))
        return completed(action)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = plan_and_context()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    assert first.retryable and first.output_started
    await runtime.shutdown()

    async def remaining(action, current, outputs):
        await outputs.emit(draft("Expression", action, current))
        return completed(action)

    replacement, _ = routed_runtime(realize=remaining)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert report.action_results[0].status is d.ActionExecutionStatus.ALREADY_COMPLETED
    assert [(value.action_id, value.sequence_no) for value in sink.values] == [("a1", 2)]
    duplicate_sink = Sink()
    duplicate = await replacement.get_agent().realize_action_plan(plan, fresh(context), duplicate_sink)
    assert duplicate.status is d.ExecutionStatus.COMPLETED and duplicate_sink.values == []


@pytest.mark.parametrize("kind,change", [
    ("TextFinal", {"text": "更换内容"}),
    ("TextFinal", {"delivery": d.OutputDelivery.EPHEMERAL_REACTION}),
    ("AudioChunk", {"data": b"other audio"}),
    ("AudioChunk", {"framing": d.AudioFraming.COMPLETE_FILE}),
    ("MessageEnd", {"status": d.MessageEndStatus.COMPLETED, "error_code": None}),
    ("MessageEnd", {"error_code": d.AudioErrorCode.GENERATION_FAILED}),
    ("Expression", {"expression": d.ChangeExpression(expression_id="normal")}),
])
async def test_safe_retry_cannot_replace_persisted_slot_content(routed_runtime, kind, change):
    async def initial(action, context, outputs):
        try:
            await outputs.emit(draft(kind, action, context))
        except d.SinkRejectedError:
            return failed(action)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = single()
    await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    await runtime.shutdown()

    async def changed(action, current, outputs):
        try:
            await outputs.emit(draft(kind, action, current, **change))
        except Exception:
            pass  # 冲突被吞掉也不能把本次行动伪造成成功。
        return completed(action)

    replacement, _ = routed_runtime(realize=changed)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.error_code is d.ExecutionErrorCode.CONTRACT_MISMATCH and not report.retryable
    assert sink.values == []


@pytest.mark.parametrize("cancelled", [False, True])
async def test_safe_handler_reentry_reuses_pending_before_allocating_next_slot(routed_runtime, cancelled):
    async def initial(action, context, outputs):
        try:
            await outputs.emit(draft("AudioChunk", action, context))
        except d.SinkRejectedError:
            return failed(action, cancelled=cancelled)

    runtime, _ = routed_runtime(realize=initial)
    plan, context = single()
    first = await runtime.get_agent().realize_action_plan(plan, context, Sink(reject))
    assert first.retryable
    await runtime.shutdown()
    trace = []

    async def receiver(value):
        trace.append("receive")
        sink.values.append(value)
        return accepted(value)

    async def resumed(action, current, outputs):
        trace.append("handler")
        await outputs.emit(draft("AudioChunk", action, current))
        await outputs.emit(draft("Expression", action, current))
        return completed(action)

    replacement, _ = routed_runtime(realize=resumed)
    sink = Sink(receiver)
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert trace == ["handler", "receive", "receive"]
    assert [value.sequence_no for value in sink.values] == [0, 1]
    assert sink.values[0].data == b"RIFF\x00\xff\x10\x80WAVE"


async def test_full_output_cannot_bypass_agent_identity_allocation(routed_runtime):
    async def handler(action, context, outputs):
        await outputs.emit(full_output(action.action_id))
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.error_code is d.ExecutionErrorCode.INTERNAL_ERROR and sink.values == []


async def test_rejected_slot_can_retry_same_content_before_next_sequence(routed_runtime):
    attempted = []

    async def receiver(value):
        attempted.append(value)
        if len(attempted) == 1:
            return await reject(value)
        return accepted(value)

    async def handler(action, context, outputs):
        try:
            await outputs.emit(draft("TextFinal", action, context))
        except d.SinkRejectedError:
            await outputs.emit(draft("TextFinal", action, context))
        await outputs.emit(draft("Expression", action, context))
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink(receiver))
    assert report.status is d.ExecutionStatus.COMPLETED
    assert [value.sequence_no for value in attempted] == [0, 0, 1]
    assert attempted[0] == attempted[1]
