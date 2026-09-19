"""计划交付失败后停止本次调用的后续交付。"""
import asyncio

import pytest

import src.domain.agent as d
from plan_emission_support import draft
from routing_support import Sink, request, settlement


@pytest.mark.asyncio
async def test_delivery_failure_blocks_next_plan_even_if_handler_catches_error(routed_runtime):
    seen = []
    async def fail(plan):
        seen.append(plan)
        raise TimeoutError("unknown")
    async def handle(req, plans):
        try:
            await plans.emit(draft())
        except TimeoutError:
            pass
        await plans.emit(draft(text="不应另建"))
    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(request(), Sink(fail))
    assert len(seen) == 1
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.retryable is False


@pytest.mark.asyncio
async def test_caught_delivery_task_cancel_stops_later_plans(routed_runtime):
    attempts = []

    async def receive(plan):
        attempts.append(plan)
        raise asyncio.CancelledError()

    async def handle(req, plans):
        for _ in range(2):
            try:
                await plans.emit(draft())
            except asyncio.CancelledError:
                pass
        return settlement(req)

    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(request(), Sink(receive))
    assert len(attempts) == 1
    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert report.emitted_plan_ids == ()
    assert not report.retryable
