"""单次执行中的输出身份、连续序号和完整内容。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from output_support import accepted, draft, fresh, single
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


async def test_full_output_cannot_bypass_agent_identity_allocation(routed_runtime):
    async def handler(action, context, outputs):
        await outputs.emit(full_output(action.action_id))
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    assert report.error_code is d.ExecutionErrorCode.INTERNAL_ERROR and sink.values == []
