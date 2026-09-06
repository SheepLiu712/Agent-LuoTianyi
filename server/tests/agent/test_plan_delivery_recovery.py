"""真实临时 SQLite 下，公开 handle 重投只恢复持久计划而不重跑认知。"""
import asyncio
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sqlite3
import sys

import pytest
from sqlalchemy import event

import src.domain.agent as d
from plan_emission_support import DurablePlanSink, all_business_actions, draft, encoded, one_plan
from routing_support import Sink, request, settlement


@pytest.mark.asyncio
async def test_pre_outbox_database_terminal_survives_upgrade_and_new_plan_delivery(routed_runtime, runtime_dependencies):
    kwargs, _ = runtime_dependencies
    engine = kwargs["database_manager"].open_sql_session.kw["bind"]
    fixture = Path(__file__).with_name("fixtures") / "request_ledger_v1.sql"
    with closing(sqlite3.connect(engine.url.database)) as connection, connection:
        connection.executescript(fixture.read_text(encoding="utf-8"))
    runtime, _ = routed_runtime(handle=one_plan)
    sink = Sink()
    historical = await runtime.get_agent().handle_stimulus(request(), sink)
    assert historical == settlement(request(), emitted=("legacy-plan",))
    assert sink.values == []
    fresh = await runtime.get_agent().handle_stimulus(replace(request(), request_id="new-request"), sink)
    assert fresh.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.values) == 1 and sink.values[0].origin_request_id == "new-request"
    assert await runtime.get_agent().handle_stimulus(request(), sink) == historical


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "unknown", "wrong_id", "wrong_type", "backpressure"])
async def test_unknown_or_retryable_failure_recovers_same_plan_after_rebuild(routed_runtime, tmp_path, failure):
    original = DurablePlanSink(tmp_path / "stage.sqlite")
    async def fail(plan):
        if failure != "backpressure":
            await original.emit(plan)
        else:
            original.values.append(plan)
        if failure == "wrong_id":
            return d.PlanReceipt(plan_id="unrelated", status=d.PlanAcceptanceStatus.ACCEPTED)
        if failure == "wrong_type":
            return None
        if failure == "backpressure":
            raise d.SinkRejectedError("busy", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        raise (TimeoutError("lost") if failure == "timeout" else RuntimeError("lost"))
    first, _ = routed_runtime(handle=one_plan)
    initial = await first.get_agent().handle_stimulus(request(), Sink(fail))
    assert len(original.values) == 1
    assert initial.request_status is d.HandlingRequestStatus.FAILED
    assert initial.retryable is True and initial.emitted_plan_ids == ()
    await first.shutdown()
    async def must_not_run(req, plans):
        raise AssertionError("恢复不能重新执行 Handler")
    second, _ = routed_runtime(handle=must_not_run)
    recovered_sink = DurablePlanSink(tmp_path / "stage.sqlite")
    recovered = await second.get_agent().handle_stimulus(request(), recovered_sink)
    assert recovered_sink.values == original.values
    assert len(recovered_sink.accepted_payloads()) == 1
    assert recovered.emitted_plan_ids == (original.values[0].plan_id,)
    assert recovered.request_status is d.HandlingRequestStatus.FAILED
    assert recovered.error_code is initial.error_code and recovered.retryable is False
    assert recovered.consumed_pending_stimulus_ids == ()
    assert await second.get_agent().handle_stimulus(request(), Sink()) == recovered


@pytest.mark.asyncio
async def test_recovery_preserves_valid_partial_consumption_from_handler(routed_runtime, tmp_path):
    async def handle(req, plans):
        try:
            await plans.emit(draft())
        except TimeoutError:
            pass
        return settlement(req, consumed=("m2",))
    first, _ = routed_runtime(handle=handle)
    sink = DurablePlanSink(tmp_path / "stage.sqlite", lose_reply=True)
    initial = await first.get_agent().handle_stimulus(request(), sink)
    assert len(sink.values) == 1
    assert initial.request_status is d.HandlingRequestStatus.FAILED
    assert initial.consumed_pending_stimulus_ids == ("m2",)
    assert initial.retained_pending_stimulus_ids == ("m1",)
    second, _ = routed_runtime(handle=one_plan)
    final = await second.get_agent().handle_stimulus(request(), DurablePlanSink(tmp_path / "stage.sqlite"))
    assert final.consumed_pending_stimulus_ids == ("m2",)
    assert final.retained_pending_stimulus_ids == ("m1",)
    assert final.emitted_plan_ids == (sink.values[0].plan_id,)
    assert final.request_status is d.HandlingRequestStatus.FAILED and final.retryable is False


@pytest.mark.asyncio
async def test_recovery_emits_only_unconfirmed_suffix_preserving_accepted_prefix(routed_runtime, tmp_path):
    original = DurablePlanSink(tmp_path / "stage.sqlite")
    async def receive(plan):
        original.lose_reply = plan.plan_ordinal == 1
        return await original.emit(plan)
    async def handle(req, plans):
        await plans.emit(draft(text="已确认前缀"))
        await plans.emit(draft(text="未确认后缀"))
    first, _ = routed_runtime(handle=handle)
    initial = await first.get_agent().handle_stimulus(request(), Sink(receive))
    assert [p.plan_ordinal for p in original.values] == [0, 1]
    assert initial.emitted_plan_ids == (original.values[0].plan_id,)
    second, _ = routed_runtime(handle=one_plan)
    sink = DurablePlanSink(tmp_path / "stage.sqlite")
    recovered = await second.get_agent().handle_stimulus(request(), sink)
    assert sink.values == original.values[1:]
    assert recovered.emitted_plan_ids == tuple(p.plan_id for p in original.values)
    assert len(sink.accepted_payloads()) == 2 and recovered.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [d.SinkRejectionCode.STALE_INTERACTION, d.SinkRejectionCode.SINK_CLOSED,
                                  d.SinkRejectionCode.CONTENT_CONFLICT])
async def test_permanent_rejection_is_terminal_without_fabricated_acceptance(routed_runtime, code):
    seen = []
    async def reject(plan):
        seen.append(plan)
        raise d.SinkRejectedError("rejected", code=code)
    runtime, _ = routed_runtime(handle=one_plan)
    report = await runtime.get_agent().handle_stimulus(request(), Sink(reject))
    assert len(seen) == 1
    assert report.emitted_plan_ids == () and report.retryable is False
    expected = {d.SinkRejectionCode.STALE_INTERACTION: d.HandlingErrorCode.STALE_INTERACTION,
                d.SinkRejectionCode.SINK_CLOSED: d.HandlingErrorCode.SINK_CLOSED,
                d.SinkRejectionCode.CONTENT_CONFLICT: d.HandlingErrorCode.INTERNAL_ERROR}[code]
    assert report.error_code is expected
    repeated = Sink()
    assert await runtime.get_agent().handle_stimulus(request(), repeated) == report
    assert repeated.values == []


@pytest.mark.asyncio
async def test_recovery_permanent_rejection_uses_final_rejection_error(routed_runtime, tmp_path):
    runtime, _ = routed_runtime(handle=one_plan)
    original = DurablePlanSink(tmp_path / "stage.sqlite", lose_reply=True)
    initial = await runtime.get_agent().handle_stimulus(request(), original)
    assert initial.retryable is True and len(original.values) == 1
    async def reject(plan):
        raise d.SinkRejectedError("obsolete", code=d.SinkRejectionCode.STALE_INTERACTION)
    report = await runtime.get_agent().handle_stimulus(request(), Sink(reject))
    assert report.error_code is d.HandlingErrorCode.STALE_INTERACTION
    assert report.retryable is False and report.emitted_plan_ids == ()
    final_sink = Sink()
    assert await runtime.get_agent().handle_stimulus(request(), final_sink) == report
    assert final_sink.values == []


@pytest.mark.asyncio
async def test_unconfirmed_slot_blocks_new_draft_even_if_handler_catches_failure(routed_runtime):
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
    assert report.retryable is True


@pytest.mark.asyncio
async def test_pending_slot_can_retry_same_draft_inside_handler(routed_runtime):
    seen = []
    async def receive(plan):
        seen.append(plan)
        if len(seen) == 1:
            raise d.SinkRejectedError("busy", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)
    async def handle(req, plans):
        try:
            await plans.emit(draft())
        except d.SinkRejectedError:
            pass
        receipt = await plans.emit(draft(), ordinal=0)
        return settlement(req, emitted=(receipt.plan_id,))
    runtime, _ = routed_runtime(handle=handle)
    report = await runtime.get_agent().handle_stimulus(request(), Sink(receive))
    assert len(seen) == 2 and seen[0] == seen[1]
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.emitted_plan_ids == (seen[0].plan_id,)


@pytest.mark.asyncio
async def test_recovery_checks_fingerprint_and_current_token_without_overwriting_pending(routed_runtime, tmp_path):
    runtime, _ = routed_runtime(handle=one_plan)
    original = DurablePlanSink(tmp_path / "stage.sqlite", lose_reply=True)
    initial = await runtime.get_agent().handle_stimulus(request(), original)
    assert initial.retryable is True and len(original.values) == 1
    req = request()
    conflict = replace(req, interaction=replace(req.interaction, interaction_revision=4))
    sink = Sink()
    report = await runtime.get_agent().handle_stimulus(conflict, sink)
    assert report.error_code is d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH
    req.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
    cancelled = await runtime.get_agent().handle_stimulus(req, sink)
    assert cancelled.request_status is d.HandlingRequestStatus.CANCELLED
    assert sink.values == []
    recovered = await runtime.get_agent().handle_stimulus(request(), sink)
    assert sink.values == original.values
    assert recovered.request_status is d.HandlingRequestStatus.FAILED
    assert recovered.error_code is initial.error_code


@pytest.mark.asyncio
async def test_ack_commit_failure_keeps_same_plan_available_for_recovery(routed_runtime, runtime_dependencies):
    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    fail_next = False
    seen = []
    def before_commit(session):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError("ack commit unavailable")
    async def receive(plan):
        nonlocal fail_next
        seen.append(plan)
        fail_next = True
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)
    runtime, _ = routed_runtime(handle=one_plan)
    event.listen(sessions, "before_commit", before_commit)
    try:
        report = await runtime.get_agent().handle_stimulus(request(), Sink(receive))
        assert len(seen) == 1
        assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        assert report.emitted_plan_ids == (seen[0].plan_id,)
        replacement, _ = routed_runtime(handle=one_plan)
        sink = Sink()
        recovered = await replacement.get_agent().handle_stimulus(request(), sink)
        assert sink.values == seen
        assert recovered.emitted_plan_ids == (seen[0].plan_id,) and recovered.retryable is False
    finally:
        event.remove(sessions, "before_commit", before_commit)


@pytest.mark.asyncio
async def test_outbox_commit_failure_prevents_any_external_delivery(routed_runtime, runtime_dependencies):
    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    fail_next = False
    def before_commit(session):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError("outbox unavailable")
    async def handle(req, plans):
        nonlocal fail_next
        await plans.emit(draft())
        fail_next = True
        await plans.emit(draft(text="未落盘不得投递"))
    runtime, _ = routed_runtime(handle=handle)
    event.listen(sessions, "before_commit", before_commit)
    try:
        sink = Sink()
        report = await runtime.get_agent().handle_stimulus(request(), sink)
        assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        assert len(sink.values) == 1
        assert report.emitted_plan_ids == (sink.values[0].plan_id,)
    finally:
        event.remove(sessions, "before_commit", before_commit)


@pytest.mark.asyncio
async def test_cancelled_recovery_releases_ownership_after_sink_cleanup(routed_runtime, tmp_path):
    runtime, _ = routed_runtime(handle=one_plan)
    first = DurablePlanSink(tmp_path / "stage.sqlite", lose_reply=True)
    initial = await runtime.get_agent().handle_stimulus(request(), first)
    assert initial.retryable is True and len(first.values) == 1
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def blocked(plan):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    task = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink(blocked)))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        replacement, _ = routed_runtime(handle=one_plan)
        sink = Sink()
        final = await replacement.get_agent().handle_stimulus(request(), sink)
        assert sink.values == first.values
        assert final.emitted_plan_ids == (first.values[0].plan_id,)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_recovery_has_one_owner_and_shutdown_retains_dependencies(routed_runtime, tmp_path):
    runtime, store = routed_runtime(handle=one_plan)
    original = DurablePlanSink(tmp_path / "stage.sqlite", lose_reply=True)
    initial = await runtime.get_agent().handle_stimulus(request(), original)
    assert initial.retryable is True and len(original.values) == 1
    other, _ = routed_runtime(handle=one_plan)
    started, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def blocked(plan):
        seen.append(plan)
        started.set()
        await release.wait()
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ALREADY_ACCEPTED)
    owner = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink(blocked)))
    waiter = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        unused = Sink()
        waiter = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), unused))
        await asyncio.sleep(0)
        rejection = await other.get_agent().handle_stimulus(request(), unused)
        assert rejection.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        runtime.shutdown_timeout_seconds = .02
        with pytest.raises(RuntimeError):
            await runtime.shutdown()
        assert store.close_calls == 0
        release.set()
        first_report, second_report = await asyncio.gather(owner, waiter)
        assert first_report == second_report
        assert unused.values == [] and seen == original.values
        await runtime.shutdown()
    finally:
        release.set()
        await asyncio.gather(owner, *([waiter] if waiter else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_unfinished_cognition_cannot_be_restarted_to_replay_pending_outbox(routed_runtime, tmp_path):
    waiting = asyncio.Event()
    async def handle(req, plans):
        try:
            await plans.emit(draft())
        except TimeoutError:
            waiting.set()
            await asyncio.Event().wait()
    runtime, _ = routed_runtime(handle=handle)
    original = DurablePlanSink(tmp_path / "stage.sqlite", lose_reply=True)
    owner = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), original))
    reached = asyncio.create_task(waiting.wait())
    try:
        await asyncio.wait((owner, reached), timeout=1, return_when=asyncio.FIRST_COMPLETED)
        assert waiting.is_set(), "未产生待恢复计划，处理器已经提前失败"
    finally:
        owner.cancel()
        reached.cancel()
        await asyncio.gather(owner, reached, return_exceptions=True)
    replacement, _ = routed_runtime(handle=one_plan)
    sink = Sink()
    report = await replacement.get_agent().handle_stimulus(request(), sink)
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert sink.values == [] and len(original.values) == 1


@pytest.mark.asyncio
async def test_fresh_python_process_recovers_full_plan_then_terminal_replay_emits_nothing(
    routed_runtime, runtime_dependencies, tmp_path,
):
    runtime, _ = routed_runtime(handle=all_business_actions)
    stage_path = tmp_path / "stage.sqlite"
    original = DurablePlanSink(stage_path, lose_reply=True)
    initial = await runtime.get_agent().handle_stimulus(request(), original)
    assert initial.retryable is True and len(original.values) == 1
    expected = encoded(original.values[0])
    await runtime.shutdown()
    kwargs, _ = runtime_dependencies
    url = str(kwargs["database_manager"].open_sql_session.kw["bind"].url)
    result_file = tmp_path / "child.json"
    server = Path(__file__).resolve().parents[2]
    script = '''
import asyncio, json, sys
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.agent import Agent
from src.agent.handlers.stimulus.router import StimulusRouter
import src.domain.agent as d
from routing_support import Sink, request
from plan_emission_support import DurablePlanSink, encoded
async def forbidden(req, plans):
    raise AssertionError("must not repeat cognition")
async def main():
    engine = create_engine(sys.argv[1])
    agent = Agent(character_id="luotianyi", sql_session_factory=sessionmaker(bind=engine),
        stimulus_router=StimulusRouter(((d.StimulusKind.TEXT_MESSAGE, SimpleNamespace(handle=forbidden)),)))
    sink = DurablePlanSink(sys.argv[2])
    result = await agent.handle_stimulus(request(), sink)
    again = Sink()
    repeated = await agent.handle_stimulus(request(), again)
    data = dict(payloads=[encoded(p) for p in sink.values], accepted=sink.accepted_payloads(),
        emitted=result.emitted_plan_ids, retryable=result.retryable, status=result.request_status.value,
        terminal_equal=(result == repeated), repeated_count=len(again.values))
    with open(sys.argv[3], "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
    engine.dispose()
asyncio.run(main())
'''
    bootstrap = f"import sys; sys.path[:0] = {[str(server), str(server / 'tests'), str(server / 'tests/agent')]!r}\n"
    result = await asyncio.to_thread(subprocess.run,
        [sys.executable, "-X", "utf8", "-c", bootstrap + script, url, str(stage_path), str(result_file)],
        cwd=server, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result_file.read_text(encoding="utf-8"))
    assert data["payloads"] == data["accepted"] == [expected]
    assert data["emitted"] == [original.values[0].plan_id]
    assert data["status"] == "failed" and data["retryable"] is False
    assert data["terminal_equal"] is True and data["repeated_count"] == 0
