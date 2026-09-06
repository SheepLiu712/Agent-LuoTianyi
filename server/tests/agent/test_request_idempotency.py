"""通过公开 handle 和运行时关闭证明持久请求身份与安全重投。"""
import asyncio
from dataclasses import asdict, replace
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event

import src.domain.agent as d
from routing_support import Sink, plan_and_context, request, settlement
from plan_emission_support import draft


async def deliver(req, plans):
    plan, _ = plan_and_context()
    plan = replace(plan, origin_request_id=req.request_id,
                   target_character_id=req.stimulus.target_character_ids[0],
                   interaction_id=req.interaction.interaction_id,
                   basis_interaction_revision=req.interaction.interaction_revision)
    receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
    return settlement(req, emitted=(receipt.plan_id,), reconsider_at=req.interaction.now + timedelta(seconds=7))


def rejection(report, code):
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is code
    assert report.retryable is False
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == report.considered_pending_stimulus_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("result_kind", ["success", "failed", "cancelled", "zero"])
async def test_terminal_report_replay_preserves_settlement_without_delivery(routed_runtime, restart, result_kind):
    async def handle(req, plans):
        report = await deliver(req, plans) if result_kind != "zero" else settlement(req)
        if result_kind == "failed":
            return replace(report, request_status=d.HandlingRequestStatus.FAILED,
                           error_code=d.HandlingErrorCode.PROVIDER_TIMEOUT, retryable=True)
        if result_kind == "cancelled":
            return replace(report, request_status=d.HandlingRequestStatus.CANCELLED)
        return report

    runtime, _ = routed_runtime(handle=handle)
    first_sink = Sink()
    expected = await runtime.get_agent().handle_stimulus(request(), first_sink)
    if restart:
        await runtime.shutdown()
        runtime, _ = routed_runtime(handle=lambda req, plans: unexpected_result(req))
    second_sink = Sink()
    actual = await runtime.get_agent().handle_stimulus(request(), second_sink)
    assert actual == expected
    assert second_sink.values == []


async def unexpected_result(req):
    return settlement(req, consumed=(), request_status=d.HandlingRequestStatus.FAILED,
                      error_code=d.HandlingErrorCode.INTERNAL_ERROR)


def changed(req, field):
    snapshot = req.interaction
    first, second = snapshot.pending_stimuli
    if field == "trigger":
        return replace(req, stimulus=second)
    if field.startswith("stimulus."):
        field = field.split(".")[1]
        values = {"text": "改变的正文", "client_msg_id": "other-client", "ephemeral": True,
                  "source": d.StimulusSource.WORLD, "occurred_at": first.occurred_at + timedelta(seconds=1)}
        first = replace(first, **{field: values[field]})
        return replace(req, stimulus=first, interaction=replace(snapshot, pending_stimuli=(first, second)))
    values = {
        "interaction_revision": 4, "interaction_id": "another-i", "user_id": "other-user",
        "now": snapshot.now + timedelta(seconds=1), "timezone": ZoneInfo("Asia/Shanghai"),
        "response_deadline": snapshot.now + timedelta(seconds=2),
        "connection_state": d.ConnectionState.DISCONNECTED,
        "supported_outputs": frozenset({d.AgentOutputKind.TEXT_FINAL}),
        "pending_order": (second, first), "pending_text": (first, replace(second, text="新内容")),
    }
    key = "pending_stimuli" if field.startswith("pending_") else field
    return replace(req, interaction=replace(snapshot, **{key: values[field]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "trigger", "stimulus.text", "stimulus.client_msg_id", "stimulus.ephemeral",
    "stimulus.source", "stimulus.occurred_at", "interaction_revision", "interaction_id",
    "user_id", "now", "timezone", "response_deadline", "connection_state",
    "supported_outputs", "pending_order", "pending_text",
])
async def test_same_request_id_changed_semantics_is_conflict_and_preserves_original(routed_runtime, field):
    runtime, _ = routed_runtime(handle=deliver)
    agent = runtime.get_agent()
    original = await agent.handle_stimulus(request(), Sink())
    sink = Sink()
    conflict = await agent.handle_stimulus(changed(request(), field), sink)
    rejection(conflict, d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH)
    assert sink.values == []
    assert conflict.emitted_plan_ids == ()
    assert await agent.handle_stimulus(request(), Sink()) == original


@pytest.mark.asyncio
async def test_terminal_report_wins_over_new_cancelled_token_and_set_order(routed_runtime):
    runtime, _ = routed_runtime(handle=deliver)
    req = request()
    req = replace(req, interaction=replace(req.interaction, supported_outputs=frozenset([
        d.AgentOutputKind.TEXT_FINAL, d.AgentOutputKind.MESSAGE_END,
    ])))
    expected = await runtime.get_agent().handle_stimulus(req, Sink())
    token = d.CancellationToken()
    token.cancel(d.CancellationReason.SUPERSEDED)
    duplicate = replace(req, cancellation=token, interaction=replace(req.interaction, supported_outputs=frozenset([
        d.AgentOutputKind.MESSAGE_END, d.AgentOutputKind.TEXT_FINAL,
    ])))
    sink = Sink()
    assert await runtime.get_agent().handle_stimulus(duplicate, sink) == expected
    assert sink.values == []


@pytest.mark.asyncio
async def test_pre_cancelled_request_is_terminal_after_new_token(routed_runtime):
    runtime, _ = routed_runtime(handle=deliver)
    req = request()
    req.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
    expected = await runtime.get_agent().handle_stimulus(req, Sink())
    sink = Sink()
    assert await runtime.get_agent().handle_stimulus(replace(req, cancellation=d.CancellationToken()), sink) == expected
    assert sink.values == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scene,field,value", [
    ("toy", "device_id", "other-device"), ("toy", "online", False),
    ("world", "world_id", "other-world"), ("world", "world_revision", 2),
    ("world", "activity_revision", 2), ("world", "planning_cycle_id", "cycle-2"),
    ("world", "schedule_revision", 2),
])
async def test_scene_specific_facts_are_part_of_request_identity(routed_runtime, scene, field, value):
    runtime, _ = routed_runtime(handle=deliver)
    req = request()
    facts = {name: getattr(req.interaction, name) for name in (
        "interaction_id", "interaction_revision", "user_id", "pending_stimuli", "now", "timezone", "supported_outputs",
    )}
    snapshot = (d.ToyInteractionSnapshot(**facts, device_id="device", online=True) if scene == "toy" else
                d.WorldInteractionSnapshot(**facts, world_id="world", world_revision=1, activity_id="activity",
                                           activity_revision=1, planning_cycle_id="cycle", schedule_revision=1))
    req = replace(req, interaction=snapshot)
    await runtime.get_agent().handle_stimulus(req, Sink())
    sink = Sink()
    rejection(await runtime.get_agent().handle_stimulus(replace(req, interaction=replace(snapshot, **{field: value})), sink),
              d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH)
    assert sink.values == []


@pytest.mark.asyncio
async def test_unsupported_terminal_survives_runtime_reconstruction_with_new_registration(routed_runtime):
    first, _ = routed_runtime()
    expected = await first.get_agent().handle_stimulus(request(), Sink())
    await first.shutdown()
    second, _ = routed_runtime(handle=deliver)
    sink = Sink()
    assert await second.get_agent().handle_stimulus(request(), sink) == expected
    assert sink.values == []


def test_ledger_initialization_failure_rolls_back_runtime(routed_runtime, runtime_dependencies):
    kwargs, store = runtime_dependencies
    def unavailable():
        raise RuntimeError("unavailable database")
    kwargs["database_manager"].open_sql_session = unavailable
    with pytest.raises(RuntimeError):
        routed_runtime(handle=deliver)
    assert store.close_calls == 1


@pytest.mark.asyncio
async def test_same_request_concurrent_waiter_cancel_does_not_duplicate_delivery(routed_runtime):
    started, release = asyncio.Event(), asyncio.Event()
    async def handle(req, plans):
        started.set()
        await release.wait()
        return await deliver(req, plans)
    runtime, _ = routed_runtime(handle=handle)
    agent = runtime.get_agent()
    owner_sink, duplicate_sink = Sink(), Sink()
    owner = asyncio.create_task(agent.handle_stimulus(request(), owner_sink))
    await asyncio.wait_for(started.wait(), 1)
    cancelled_waiter = asyncio.create_task(agent.handle_stimulus(request(), Sink()))
    duplicate = asyncio.create_task(agent.handle_stimulus(request(), duplicate_sink))
    try:
        await asyncio.sleep(0)
        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_waiter
        assert not owner.done()
        release.set()
        first, second = await asyncio.wait_for(asyncio.gather(owner, duplicate), 1)
        assert first == second
        assert len(owner_sink.values) == 1
        assert duplicate_sink.values == []
    finally:
        release.set()
        await asyncio.gather(owner, duplicate, cancelled_waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_active_conflict_does_not_wait_for_owner(routed_runtime):
    started, release = asyncio.Event(), asyncio.Event()
    async def handle(req, plans):
        started.set()
        await release.wait()
        return await deliver(req, plans)
    runtime, _ = routed_runtime(handle=handle)
    owner = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink()))
    await asyncio.wait_for(started.wait(), 1)
    try:
        report = await asyncio.wait_for(runtime.get_agent().handle_stimulus(changed(request(), "now"), Sink()), .1)
        rejection(report, d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH)
    finally:
        release.set()
        await owner


@pytest.mark.asyncio
async def test_independent_instances_refuse_active_claim_then_read_terminal(routed_runtime):
    started, release = asyncio.Event(), asyncio.Event()
    async def handle(req, plans):
        started.set()
        await release.wait()
        return await deliver(req, plans)
    first, _ = routed_runtime(handle=handle)
    second, _ = routed_runtime(handle=deliver)
    owner = asyncio.create_task(first.get_agent().handle_stimulus(request(), Sink()))
    await asyncio.wait_for(started.wait(), 1)
    sink = Sink()
    try:
        report = await second.get_agent().handle_stimulus(request(), sink)
        rejection(report, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
        assert sink.values == []
    finally:
        release.set()
        terminal = await owner
    assert await second.get_agent().handle_stimulus(request(), sink) == terminal
    assert sink.values == []


@pytest.mark.asyncio
async def test_cancelled_owner_does_not_allow_waiter_or_restart_to_take_over(routed_runtime):
    started = asyncio.Event()
    async def handle(req, plans):
        await deliver(req, plans)
        started.set()
        await asyncio.Event().wait()
    runtime, _ = routed_runtime(handle=handle)
    owner = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink()))
    await asyncio.wait_for(started.wait(), 1)
    waiter_sink = Sink()
    waiter = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), waiter_sink))
    await asyncio.sleep(0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    try:
        report = await asyncio.wait_for(waiter, .1)
        rejection(report, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
        assert waiter_sink.values == []
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
    await runtime.shutdown()
    replacement, _ = routed_runtime(handle=deliver)
    sink = Sink()
    rejection(await replacement.get_agent().handle_stimulus(request(), sink), d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
    assert sink.values == []


@pytest.mark.asyncio
async def test_request_and_character_keys_remain_independent(routed_runtime):
    runtime, _ = routed_runtime(handle=deliver)
    await runtime.get_agent().handle_stimulus(request(), Sink())
    sink = Sink()
    assert (await runtime.get_agent().handle_stimulus(replace(request(), request_id="r2"), sink)).emitted_plan_ids == (sink.values[0].plan_id,)
    req = request()
    items = tuple(replace(item, target_character_ids=("miku",)) for item in req.interaction.pending_stimuli)
    req = replace(req, stimulus=items[0], interaction=replace(req.interaction, pending_stimuli=items))
    assert (await runtime.get_agent("miku").handle_stimulus(req, sink)).request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.values) == 2


@pytest.mark.asyncio
async def test_storage_unavailable_does_not_run_handler(routed_runtime, runtime_dependencies, caplog):
    from src.utils.logger import get_logger

    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    unavailable = False
    secret = "database secret should not enter logs"
    def open_session():
        if unavailable:
            raise RuntimeError(secret)
        return sessions()
    kwargs["database_manager"].open_sql_session = open_session
    runtime, _ = routed_runtime(handle=deliver)
    unavailable = True
    sink = Sink()
    logger = get_logger("src.agent.facade")
    logger.addHandler(caplog.handler)
    try:
        rejection(await runtime.get_agent().handle_stimulus(request(), sink), d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
        assert sink.values == []
    finally:
        logger.removeHandler(caplog.handler)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "DEPENDENCY_UNAVAILABLE" in text and "luotianyi" in text and "call_id=r" in text
    assert secret not in caplog.text and "你好" not in caplog.text


@pytest.mark.asyncio
async def test_report_commit_failure_preserves_accepted_ids_and_blocks_reprocessing(routed_runtime, runtime_dependencies):
    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    failing = False
    def reject_commit(session):
        if failing:
            raise RuntimeError("commit unavailable")
    event.listen(sessions, "before_commit", reject_commit)
    async def handle(req, plans):
        nonlocal failing
        report = await deliver(req, plans)
        failing = True
        return report
    runtime, _ = routed_runtime(handle=handle)
    try:
        sink = Sink()
        report = await runtime.get_agent().handle_stimulus(request(), sink)
        assert report.request_status is d.HandlingRequestStatus.FAILED
        assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        assert report.retryable is False
        assert report.emitted_plan_ids == (sink.values[0].plan_id,)
        failing = False
        second, _ = routed_runtime(handle=deliver)
        rejection(await second.get_agent().handle_stimulus(request(), sink), d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE)
        assert len(sink.values) == 1
    finally:
        event.remove(sessions, "before_commit", reject_commit)


@pytest.mark.asyncio
async def test_shutdown_waits_for_owner_and_duplicate_before_releasing_dependencies(routed_runtime):
    started, release = asyncio.Event(), asyncio.Event()
    async def handle(req, plans):
        started.set()
        await release.wait()
        return await deliver(req, plans)
    runtime, store = routed_runtime(handle=handle)
    runtime.shutdown_timeout_seconds = .02
    first = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink()))
    await asyncio.wait_for(started.wait(), 1)
    duplicate_sink = Sink()
    second = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), duplicate_sink))
    try:
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await runtime.shutdown()
        assert store.close_calls == 0
        release.set()
        left, right = await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert left == right
        assert duplicate_sink.values == []
        runtime.shutdown_timeout_seconds = 1
        await runtime.shutdown()
        assert store.close_calls == 1
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_fresh_process_reads_terminal_without_running_replacement_handler(routed_runtime, runtime_dependencies, tmp_path):
    runtime, _ = routed_runtime(handle=deliver)
    expected = await runtime.get_agent().handle_stimulus(request(), Sink())
    await runtime.shutdown()
    kwargs, _ = runtime_dependencies
    url = str(kwargs["database_manager"].open_sql_session.kw["bind"].url)
    result_file = tmp_path / "child-report.json"
    server = Path(__file__).resolve().parents[2]
    script = '''
import asyncio, inspect, json, sys
from dataclasses import asdict
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.agent import Agent
from src.agent.handlers.stimulus.router import StimulusRouter
import src.domain.agent as d
from routing_support import Sink, request, settlement
async def replacement(req, plans):
    return settlement(req, consumed=())
engine = create_engine(sys.argv[1])
kwargs = dict(character_id="luotianyi", stimulus_router=StimulusRouter(((d.StimulusKind.TEXT_MESSAGE, SimpleNamespace(handle=replacement)),)))
if "sql_session_factory" in inspect.signature(Agent).parameters:
    kwargs["sql_session_factory"] = sessionmaker(bind=engine)
agent = Agent(**kwargs)
report = asyncio.run(agent.handle_stimulus(request(), Sink()))
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump(asdict(report), stream, default=str)
engine.dispose()
'''
    bootstrap = f"import sys; sys.path[:0] = {[str(server), str(server / 'tests'), str(server / 'tests/agent')]!r}\n"
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", bootstrap + script, url, str(result_file)],
                                    cwd=server, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result_file.read_text(encoding="utf-8")) == json.loads(json.dumps(asdict(expected), default=str))
