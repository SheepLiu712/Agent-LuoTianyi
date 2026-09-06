"""公开 handle 的草稿封装、稳定身份、顺序、拒绝、取消及日志契约。"""
import asyncio
from dataclasses import replace

import pytest

import src.domain.agent as d
from plan_emission_support import draft, one_plan
from routing_support import Sink, request, settlement


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 3])
async def test_handle_delivers_zero_or_more_complete_plans_in_order(routed_runtime, count):
    async def handle(req, plans):
        receipts = [await plans.emit(draft(text=f"回复 {i}")) for i in range(count)]
        return settlement(req, emitted=tuple(item.plan_id for item in receipts))
    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.values) == count
    assert [p.plan_ordinal for p in sink.values] == list(range(count))
    assert [p.actions[0].content for p in sink.values] == [f"回复 {i}" for i in range(count)]
    assert len({p.plan_id for p in sink.values}) == count
    assert report.emitted_plan_ids == tuple(p.plan_id for p in sink.values)
    for plan in sink.values:
        assert (plan.origin_request_id, plan.target_character_id, plan.interaction_id) == ("r", "luotianyi", "i")
        assert plan.basis_interaction_revision == 3 and plan.source_stimulus_ids == ("m2", "m1")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unknown_source", "empty_actions", "duplicate_action", "late_thinking"])
async def test_invalid_next_draft_does_not_reach_sink(routed_runtime, case):
    async def handle(req, plans):
        await plans.emit(draft())
        if case == "unknown_source":
            value = draft(sources=("outside",))
        elif case == "empty_actions":
            value = draft(actions=())
        elif case == "duplicate_action":
            action = draft().actions[0]
            value = draft(actions=(action, action))
        else:
            value = draft(actions=(d.StartThinking(action_id="thinking"),))
        await plans.emit(value)
    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert len(sink.values) == 1
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.emitted_plan_ids == (sink.values[0].plan_id,)


@pytest.mark.asyncio
async def test_thinking_is_complete_first_plan_then_business_plan(routed_runtime):
    async def handle(req, plans):
        start = await plans.emit(draft(actions=(d.StartThinking(action_id="thinking"),), sources=()))
        reply = await plans.emit(draft())
        return settlement(req, emitted=(start.plan_id, reply.plan_id))
    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert [p.plan_ordinal for p in sink.values] == [0, 1]
    assert sink.values[0].actions == (d.StartThinking(action_id="thinking"),)


@pytest.mark.asyncio
async def test_same_request_different_characters_get_distinct_plan_ids(routed_runtime):
    runtime, _ = routed_runtime(handle=one_plan)
    sink = Sink()
    await runtime.get_agent().handle_stimulus(request(), sink)
    req = request()
    pending = tuple(replace(item, target_character_ids=("miku",)) for item in req.interaction.pending_stimuli)
    other = replace(req, stimulus=pending[0], interaction=replace(req.interaction, pending_stimuli=pending))
    await runtime.get_agent("miku").handle_stimulus(other, sink)
    assert len(sink.values) == 2
    assert sink.values[0].plan_id != sink.values[1].plan_id
    assert [p.plan_ordinal for p in sink.values] == [0, 0]


@pytest.mark.asyncio
async def test_cancellation_after_acceptance_prevents_next_plan_and_retains_receipt(routed_runtime):
    req = request()
    values = []
    async def receive(plan):
        values.append(plan)
        req.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)
    async def handle(request, plans):
        await plans.emit(draft())
        await plans.emit(draft(text="不可交付"))
    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(req, Sink(receive))
    assert len(values) == 1
    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert report.emitted_plan_ids == (values[0].plan_id,)


@pytest.mark.asyncio
async def test_closed_emitter_cannot_deliver_after_handle_returns(routed_runtime):
    retained = []
    async def handle(req, plans):
        retained.append(plans)
        return await one_plan(req, plans)
    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    with pytest.raises(RuntimeError):
        await retained[0].emit(draft(text="过期调用"))
    assert len(sink.values) == 1


@pytest.mark.asyncio
async def test_caught_delivery_failure_still_logs_plan_identity_without_payload(routed_runtime, caplog):
    from src.utils.logger import get_logger

    secret = "sensitive provider response"
    async def receive(plan):
        raise RuntimeError(secret)
    async def handle(req, plans):
        try:
            await plans.emit(draft())
        except Exception:
            pass
        return settlement(req)
    runtime, _ = routed_runtime(handle=handle)
    loggers = [get_logger(name) for name in ("src.agent.facade", "src.agent.processing.plan_emitter")]
    for logger in loggers:
        logger.addHandler(caplog.handler)
    try:
        report = await runtime.get_agent().handle_stimulus(request(), Sink(receive))
    finally:
        for logger in loggers:
            logger.removeHandler(caplog.handler)
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.retryable is False
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "plan_id=" in messages and "ordinal=0" in messages and "INTERNAL_ERROR" in messages
    assert "luotianyi" in messages and "interaction_id=i" in messages
    assert secret not in caplog.text and "计划正文" not in caplog.text and "你好" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_drafts_have_serialized_contiguous_delivery(routed_runtime):
    active = 0
    overlap = False
    values = []
    async def receive(plan):
        nonlocal active, overlap
        active += 1
        overlap = overlap or active > 1
        await asyncio.sleep(0)
        values.append(plan)
        active -= 1
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)
    async def handle(req, plans):
        receipts = await asyncio.gather(plans.emit(draft(text="一")), plans.emit(draft(text="二")))
        return settlement(req, emitted=tuple(receipt.plan_id for receipt in receipts))
    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(request(), Sink(receive))
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert [plan.plan_ordinal for plan in values] == [0, 1]
    assert overlap is False


@pytest.mark.asyncio
@pytest.mark.parametrize("extended_type", ["action", "tone"])
async def test_non_whitelisted_plan_value_is_contract_failure_without_delivery(routed_runtime, extended_type):
    class ExtendedSay(d.Say):
        pass

    class ExtendedTone(d.Tone):
        pass

    async def handle(req, plans):
        action_type = ExtendedSay if extended_type == "action" else d.Say
        tone_type = ExtendedTone if extended_type == "tone" else d.Tone
        action = action_type(action_id="custom", content="自定义值", sound_content=None,
                             prepared_audio_ref=None, tone=tone_type(value="normal"),
                             expression=None, delivery=d.OutputDelivery.CONVERSATION)
        await plans.emit(draft(actions=(action,)))

    runtime, _ = routed_runtime(handle=handle)
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.retryable is False and sink.values == []
