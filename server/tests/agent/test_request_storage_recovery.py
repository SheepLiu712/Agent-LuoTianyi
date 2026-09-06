"""真实 SQL 存储故障注入；仅通过公开 handle 检查损坏记录不触发重跑。"""
import json

import pytest
from sqlalchemy import MetaData, Table, select, update

import src.domain.agent as d
from routing_support import Sink, plan_and_context, request, settlement


async def _deliver(req, plans):
    plan, _ = plan_and_context()
    await plans.emit(plan)
    return settlement(req, emitted=(plan.plan_id,))


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", [
    "row_version", "fingerprint", "invalid_json", "report_version", "missing_field",
    "status", "identity_tuple", "wrong_request", "wrong_trigger", "wrong_revision", "wrong_pending",
])
async def test_corrupt_persisted_record_refuses_replay_without_reprocessing(
    routed_runtime, runtime_dependencies, damage,
):
    runtime, _ = routed_runtime(handle=_deliver)
    await runtime.get_agent().handle_stimulus(request(), Sink())
    await runtime.shutdown()
    kwargs, _ = runtime_dependencies
    sessions = kwargs["database_manager"].open_sql_session
    # SQL 是外部故障注入边界；表仅用于破坏输入，不断言账本内部查询步骤。
    with sessions() as session:
        table = Table("agent_handle_requests", MetaData(), autoload_with=session.get_bind())
        key = (table.c.character_id == "luotianyi") & (table.c.request_id == "r")
        payload = session.execute(select(table.c.report_json).where(key)).scalar_one()
        data = json.loads(payload)
        changes = {}
        if damage == "row_version":
            changes["version"] = 999
        elif damage == "fingerprint":
            changes["fingerprint"] = "broken"
        elif damage == "invalid_json":
            changes["report_json"] = "{"
        else:
            if damage == "report_version":
                data["version"] = 999
            elif damage == "missing_field":
                del data["report"]["retryable"]
            else:
                name, value = {
                    "status": ("request_status", "unknown"),
                    "identity_tuple": ("emitted_plan_ids", "p"),
                    "wrong_request": ("request_id", "other"),
                    "wrong_trigger": ("trigger_stimulus_id", "other"),
                    "wrong_revision": ("basis_interaction_revision", 999),
                    "wrong_pending": ("considered_pending_stimulus_ids", ["other"]),
                }[damage]
                data["report"][name] = value
            changes["report_json"] = json.dumps(data)
        session.execute(update(table).where(key).values(**changes))
        session.commit()
    replacement, _ = routed_runtime(handle=_deliver)
    sink = Sink()
    for _ in range(2):
        report = await replacement.get_agent().handle_stimulus(request(), sink)
        assert report.request_status is d.HandlingRequestStatus.FAILED
        assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        assert report.retryable is False
    assert sink.values == []
