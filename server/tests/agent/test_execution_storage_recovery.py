"""通过公开 realize 验证真实 SQLite 故障与进程恢复。"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import MetaData, event, update

import src.domain.agent as d
from routing_support import Sink, completed, output, plan_and_context
from test_execution_idempotency import deliver, fresh, statuses

pytestmark = pytest.mark.asyncio


async def test_execution_storage_unavailable_prevents_handler_and_logs_safe_error(
    routed_runtime, runtime_dependencies, caplog,
):
    from src.utils.logger import get_logger

    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    unavailable = False

    def open_session():
        if unavailable:
            raise RuntimeError("private database credential")
        return sessions()

    kwargs["database_manager"].open_sql_session = open_session
    runtime, _ = routed_runtime(realize=deliver)
    unavailable = True
    logger = get_logger("src.agent.facade")
    logger.addHandler(caplog.handler)
    try:
        plan, context = plan_and_context()
        sink = Sink()
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        assert not report.retryable and sink.values == []
        assert "DEPENDENCY_UNAVAILABLE" in caplog.text
        assert "call_id=e" in caplog.text or "execution_id=e" in caplog.text
        assert "private database credential" not in caplog.text and "你好" not in caplog.text
    finally:
        logger.removeHandler(caplog.handler)


@pytest.mark.parametrize("phase", ["action_settlement", "output_before_send", "output_confirmation"])
async def test_storage_commit_failure_blocks_next_action_even_when_handler_swallows_it(
    routed_runtime, runtime_dependencies, phase,
):
    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    failing = False

    def reject_commit(session):
        if failing:
            raise RuntimeError("commit unavailable")

    async def accept(value):
        nonlocal failing
        sink.values.append(value)
        if phase == "output_confirmation":
            failing = True
        return d.OutputReceipt(execution_id=value.execution_id, sequence_no=value.sequence_no,
                               status=d.OutputAcceptanceStatus.ACCEPTED)

    async def action_handler(action, context, outputs):
        nonlocal failing
        if phase == "output_before_send":
            failing = True
        if phase != "action_settlement":
            try:
                await outputs.emit(output(action.action_id))
            except Exception:
                pass  # 验证门面不把协作者吞错当作存储已恢复。
        failing = True
        return completed(action, irreversible_effect_committed=True,
                         effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="committed"))

    runtime, _ = routed_runtime(realize=action_handler)
    plan, context = plan_and_context()
    sink = Sink(accept)
    event.listen(sessions, "before_commit", reject_commit)
    try:
        report = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
        assert report.action_results[0].effect_ref.effect_id == "committed"
        assert report.action_results[1].status is d.ActionExecutionStatus.NOT_STARTED
        assert report.output_started is (phase == "output_confirmation")
        assert len(sink.values) == (1 if phase == "output_confirmation" else 0)
    finally:
        failing = False
        event.remove(sessions, "before_commit", reject_commit)
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    replay = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert replay.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert not replay.retryable and sink.values == []


@pytest.mark.parametrize("damage", ["version", "json"])
async def test_corrupt_persisted_execution_is_not_discarded_and_reexecuted(routed_runtime, runtime_dependencies, damage):
    runtime, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    await runtime.shutdown()
    kwargs, _ = runtime_dependencies
    with kwargs["database_manager"].open_sql_session() as session:
        metadata = MetaData()
        metadata.reflect(bind=session.get_bind())
        # 仅在外部 SQL 边界破坏版本；尚无执行记录时公开重投本身证明 RED。
        for table in metadata.tables.values():
            if "execution_id" not in table.c:
                continue
            changes = {"version": 999} if damage == "version" and "version" in table.c else {
                column.name: "{" for column in table.c if column.name.endswith("_json")
            }
            if changes:
                session.execute(update(table).where(table.c.execution_id == "e").values(**changes))
        session.commit()
    replacement, _ = routed_runtime(realize=deliver)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert not report.retryable and sink.values == []


@pytest.mark.parametrize("crash", [False, True])
async def test_fresh_python_process_respects_completed_or_unknown_action_without_repeating_effect(
    routed_runtime, runtime_dependencies, tmp_path, crash,
):
    kwargs, _ = runtime_dependencies
    url = str(kwargs["database_manager"].open_sql_session.kw["bind"].url)
    marker = tmp_path / "external-effect.txt"
    result_file = tmp_path / "child-report.json"
    server = Path(__file__).resolve().parents[2]
    script = '''
import asyncio, json, os, sys
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
import src.domain.agent as d
from routing_support import Sink, completed, plan_and_context
engine = create_engine(sys.argv[1])
async def realize(action, context, outputs):
    with open(sys.argv[2], "a", encoding="utf-8") as stream:
        stream.write(action.action_id + "\\n")
    if sys.argv[4] == "crash":
        os._exit(23)
    return completed(action, irreversible_effect_committed=True,
        effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id=action.action_id))
agent = Agent(character_id="luotianyi", sql_session_factory=sessionmaker(bind=engine),
    action_router=ActionRouter(tuple((kind, SimpleNamespace(realize=realize))
        for kind in (d.ActionKind.SAY, d.ActionKind.SING))))
plan, context = plan_and_context()
report = asyncio.run(agent.realize_action_plan(plan, context, Sink()))
Path(sys.argv[3]).write_text(json.dumps({"status": report.status.value}), encoding="utf-8")
engine.dispose()
'''
    bootstrap = f"import sys; sys.path[:0] = {[str(server), str(server / 'tests'), str(server / 'tests/agent')]!r}\n"
    result = await asyncio.to_thread(
        subprocess.run, [sys.executable, "-X", "utf8", "-c", bootstrap + script, url,
                         str(marker), str(result_file), "crash" if crash else "complete"],
        cwd=server, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == (23 if crash else 0), result.stderr
    if not crash:
        assert json.loads(result_file.read_text(encoding="utf-8"))["status"] == "completed"
    before = marker.read_text(encoding="utf-8")

    async def replacement(action, context, outputs):
        with marker.open("a", encoding="utf-8") as stream:
            stream.write("duplicate\n")
        return completed(action)

    runtime, _ = routed_runtime(realize=replacement)
    plan, context = plan_and_context()
    report = await runtime.get_agent().realize_action_plan(plan, context, Sink())
    if crash:
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
    else:
        assert statuses(report) == (d.ActionExecutionStatus.ALREADY_COMPLETED,) * 2
        assert report.irreversible_effect_committed
    assert marker.read_text(encoding="utf-8") == before
