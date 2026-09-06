"""公开 handle 的投递错误日志保留诊断位置，隔离源码及异常正文。"""
import re

import pytest

import src.domain.agent as d
from src.utils.logger import get_logger
from plan_emission_support import draft
from routing_support import Sink, request, settlement


@pytest.mark.asyncio
async def test_caught_plan_failure_logs_location_without_source_or_exception_chain(
    routed_runtime, caplog,
):
    offered = []

    async def receive_plan(plan):
        offered.append(plan)
        cause = ValueError("synthetic-plan-cause-private-content")
        raise RuntimeError("synthetic-plan-literal-private-content") from cause

    async def handle(req, plans):
        try:
            await plans.emit(draft(text="synthetic-plan-body-private-content"))
        except RuntimeError:
            pass
        return settlement(req)

    runtime, _ = routed_runtime(handle=handle)
    logger = get_logger("src.agent.planning.emitter")
    logger.addHandler(caplog.handler)
    try:
        report = await runtime.get_agent().handle_stimulus(request(), Sink(receive_plan))
    finally:
        logger.removeHandler(caplog.handler)

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.retryable is True
    assert report.consumed_pending_stimulus_ids == ("m2",)
    assert report.retained_pending_stimulus_ids == ("m1",)
    assert report.emitted_plan_ids == ()
    assert len(offered) == 1

    log_text = caplog.text
    for field in (
        "character_id=luotianyi", "request_id=r", "interaction_id=i",
        f"plan_id={offered[0].plan_id}", "ordinal=0", "INTERNAL_ERROR", "RuntimeError",
    ):
        assert field in log_text
    assert "receive_plan" in log_text
    assert re.search(r"test_plan_logging\.py[^\n]*\b\d+\b", log_text)
    for private_text in (
        "synthetic-plan-literal-private-content", "synthetic-plan-cause-private-content",
        "synthetic-plan-body-private-content", "raise RuntimeError(", "from cause",
    ):
        assert private_text not in log_text
