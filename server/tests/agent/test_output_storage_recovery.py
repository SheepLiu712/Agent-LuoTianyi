"""真实 SQL 故障、旧账本与新 Python 进程的公开输出恢复契约。"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import MetaData, delete, event, update

import src.domain.agent as d
from output_support import accepted, draft, fresh, no_reentry, single
from routing_support import Sink, completed, plan_and_context

pytestmark = pytest.mark.asyncio


async def test_prepared_payload_survives_failure_before_external_attempt(routed_runtime, runtime_dependencies):
    sessions = runtime_dependencies[0]["database_manager"].open_sql_session
    engine = sessions.kw["bind"]
    failed_once = False

    def stop_before_unknown(connection, cursor, statement, parameters, context, executemany):
        nonlocal failed_once
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if (not failed_once and "output" in statement.lower()
                and statement.lstrip().upper().startswith(("INSERT", "UPDATE"))
                and any(isinstance(value, str) and value.lower() == "unknown" for value in values)):
            failed_once = True
            raise RuntimeError("cannot mark external attempt")

    async def handler(action, context, outputs):
        try:
            await outputs.emit(draft("AudioChunk", action, context))
        except Exception:
            pass
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    first_sink = Sink()
    event.listen(engine, "before_cursor_execute", stop_before_unknown)
    try:
        first = await runtime.get_agent().realize_action_plan(plan, context, first_sink)
        assert first.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        assert not first.output_started and first_sink.values == []
    finally:
        event.remove(engine, "before_cursor_execute", stop_before_unknown)
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.status is d.ExecutionStatus.COMPLETED
    assert len(sink.values) == 1 and sink.values[0].sequence_no == 0
    assert sink.values[0].data == b"RIFF\x00\xff\x10\x80WAVE"


@pytest.mark.parametrize("mode", ["legacy_terminal", "legacy_partial", "legacy_no_output", "legacy_unknown"])
async def test_pre_output_ledger_history_does_not_restart_sequence_unsafely(routed_runtime, runtime_dependencies, mode):
    async def handler(action, context, outputs):
        await outputs.emit(draft("TextFinal", action, context))
        return completed(action)

    sessions = runtime_dependencies[0]["database_manager"].open_sql_session
    fixture = Path(__file__).with_name("fixtures") / "execution_v1_outputs.sql"
    with sessions() as session:
        session.connection().connection.driver_connection.executescript(fixture.read_text(encoding="utf-8"))
        session.commit()
    runtime, _ = routed_runtime(realize=handler)
    plan, context = plan_and_context()
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, fresh(context, execution_id=mode), sink)
    if mode == "legacy_terminal":
        assert report.status is d.ExecutionStatus.COMPLETED and report.output_started
        assert all(result.status is d.ActionExecutionStatus.ALREADY_COMPLETED for result in report.action_results)
        assert sink.values == []
    elif mode == "legacy_no_output":
        assert report.status is d.ExecutionStatus.COMPLETED
        assert [value.sequence_no for value in sink.values] == [0, 1]
    else:
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
        assert report.output_started is (mode == "legacy_partial")
        assert sink.values == []


@pytest.mark.parametrize("phase", ["prepare", "prepare_once", "ack_once", "ack_persistent"])
async def test_output_storage_fault_preserves_known_receipt_and_final_settlement(
    routed_runtime, runtime_dependencies, phase,
):
    sessions = runtime_dependencies[0]["database_manager"].open_sql_session
    failing = False

    def fail_commit(session):
        nonlocal failing
        if failing:
            if phase.endswith("_once"):
                failing = False
            raise RuntimeError("private audio and database secret")

    async def receiver(value):
        nonlocal failing
        sink.values.append(value)
        failing = True
        return accepted(value)

    async def handler(action, context, outputs):
        nonlocal failing
        if phase.startswith("prepare"):
            failing = True
        try:
            await outputs.emit(draft("AudioChunk", action, context))
        except Exception:
            pass
        return completed(action, irreversible_effect_committed=True,
                         effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="stored-effect"))

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    sink = Sink(receiver)
    event.listen(sessions, "before_commit", fail_commit)
    try:
        first = await runtime.get_agent().realize_action_plan(plan, context, sink)
        assert first.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        assert first.output_started is (not phase.startswith("prepare"))
        assert first.irreversible_effect_committed
        assert len(sink.values) == (0 if phase.startswith("prepare") else 1)
    finally:
        failing = False
        event.remove(sessions, "before_commit", fail_commit)
    await runtime.shutdown()
    replacement, _ = routed_runtime(realize=no_reentry)
    replay_sink = Sink()
    replay = await replacement.get_agent().realize_action_plan(plan, fresh(context), replay_sink)
    if phase == "ack_once":
        assert replay.status is d.ExecutionStatus.COMPLETED and replay.output_started
        assert replay.action_results[0].effect_ref.effect_id == "stored-effect"
    else:
        assert replay.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not replay.retryable
    assert replay_sink.values == []


@pytest.mark.parametrize("damage", ["version", "payload", "fingerprint", "sequence", "missing"])
async def test_corrupt_output_records_fail_closed_before_replay(routed_runtime, runtime_dependencies, damage):
    async def handler(action, context, outputs):
        await outputs.emit(draft("AudioChunk", action, context))
        return completed(action)

    runtime, _ = routed_runtime(realize=handler)
    plan, context = single()
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    await runtime.shutdown()
    sessions = runtime_dependencies[0]["database_manager"].open_sql_session
    with sessions() as session:
        metadata = MetaData()
        metadata.reflect(bind=session.get_bind())
        # 仅破坏外部存储；旧版没有输出表时，公开重投未识别损坏即是目标缺失。
        for table in metadata.tables.values():
            if not {"execution_id", "sequence_no"}.issubset(table.c.keys()):
                continue
            if damage == "missing":
                session.execute(delete(table).where(table.c.execution_id == "e"))
                continue
            changes = {}
            for column in table.c:
                if damage == "version" and column.name == "version":
                    changes[column.name] = 999
                elif damage == "payload" and column.name.endswith("_json"):
                    changes[column.name] = "{"
                elif damage == "fingerprint" and column.name == "fingerprint":
                    changes[column.name] = "different"
                elif damage == "sequence" and column.name == "sequence_no":
                    changes[column.name] = 7
            if changes:
                session.execute(update(table).where(table.c.execution_id == "e").values(**changes))
        session.commit()
    replacement, _ = routed_runtime(realize=no_reentry)
    sink = Sink()
    report = await replacement.get_agent().realize_action_plan(plan, fresh(context), sink)
    assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
    assert sink.values == []


@pytest.mark.parametrize("mode", ["safe_pending", "unknown_crash"])
async def test_fresh_python_process_preserves_original_audio_and_never_takes_unknown_action(
    routed_runtime, runtime_dependencies, tmp_path, mode,
):
    sessions = runtime_dependencies[0]["database_manager"].open_sql_session
    url = str(sessions.kw["bind"].url)
    marker, result_path = tmp_path / "effect.txt", tmp_path / "result.json"
    server = Path(__file__).resolve().parents[2]
    script = '''
import asyncio, json, os, sys
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from routing_support import Sink, completed
from output_support import draft, reject, single
import src.domain.agent as d
engine = create_engine(sys.argv[1])
async def receiver(value):
    if sys.argv[4] == "unknown_crash":
        os._exit(23)
    return await reject(value)
async def handler(action, context, outputs):
    Path(sys.argv[2]).write_text("effect committed", encoding="utf-8")
    try:
        await outputs.emit(draft("AudioChunk", action, context,
            data=b"RIFF\\x00\\xff\\x10\\x80WAVE", delivery=d.OutputDelivery.EPHEMERAL_REACTION))
    except d.SinkRejectedError:
        pass
    return completed(action, irreversible_effect_committed=True,
        effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="child-effect"))
agent = Agent(character_id="luotianyi", sql_session_factory=sessionmaker(bind=engine),
    action_router=ActionRouter(((d.ActionKind.SAY, SimpleNamespace(realize=handler)),)))
plan, context = single()
report = asyncio.run(agent.realize_action_plan(plan, context, Sink(receiver)))
Path(sys.argv[3]).write_text(json.dumps({"status": report.status.value}), encoding="utf-8")
engine.dispose()
'''
    bootstrap = f"import sys; sys.path[:0] = {[str(server), str(server / 'tests'), str(server / 'tests/agent')]!r}\n"
    process = await asyncio.to_thread(subprocess.run,
        [sys.executable, "-X", "utf8", "-c", bootstrap + script, url, str(marker), str(result_path), mode],
        cwd=server, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert process.returncode == (23 if mode == "unknown_crash" else 0), process.stderr
    assert marker.read_text(encoding="utf-8") == "effect committed"

    async def replacement(action, context, outputs):
        marker.write_text("duplicate effect", encoding="utf-8")
        return completed(action)

    runtime, _ = routed_runtime(realize=replacement)
    plan, context = single()
    sink = Sink()
    report = await runtime.get_agent().realize_action_plan(plan, context, sink)
    if mode == "safe_pending":
        assert len(sink.values) == 1 and sink.values[0].data == b"RIFF\x00\xff\x10\x80WAVE"
        assert sink.values[0].delivery is d.OutputDelivery.EPHEMERAL_REACTION
        assert sink.values[0].sequence_no == 0 and report.status is d.ExecutionStatus.COMPLETED
        assert report.action_results[0].effect_ref.effect_id == "child-effect"
        assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "failed"
    else:
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE and not report.retryable
        assert sink.values == []
    assert marker.read_text(encoding="utf-8") == "effect committed"
