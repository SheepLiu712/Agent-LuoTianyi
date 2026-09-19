import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import src.domain.agent as d
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.system.database.sql_database import Base, Conversation, DynamicPost, User
from src.world.diary.task import DiaryTask
from src.world.world_settlements import WorldSettlementRouter


class FactSink:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.facts: list[d.DiaryPlanningDue] = []

    async def submit(self, fact: d.DiaryPlanningDue) -> bool:
        self.facts.append(fact)
        return self.accepted


def _diary_query_database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _task(active_users: list[str], sink: FactSink, *, limit: int = 20,
          router: WorldSettlementRouter | None = None) -> DiaryTask:
    task = DiaryTask(
        {"max_users_per_run": limit, "timezone": "Asia/Shanghai"},
        character_id="luotianyi", settlements=router or WorldSettlementRouter(),
    )
    task.initialize(SimpleNamespace(
        database_manager=SimpleNamespace(get_sql_session=lambda: None),
        get_world_stage=lambda character_id: _stage(sink, character_id),
    ))
    task._find_active_users = lambda target_date: active_users
    return task


async def _stage(sink: FactSink, character_id: str):
    assert character_id == "luotianyi"
    return SimpleNamespace(fact_sink=sink)


def _request(fact: d.DiaryPlanningDue) -> d.HandleStimulusRequest:
    return d.HandleStimulusRequest(
        request_id="req", stimulus=fact,
        interaction=d.WorldInteractionSnapshot(
            interaction_id="wi", interaction_revision=1, user_id=None,
            pending_stimuli=(fact,), now=fact.occurred_at, timezone=fact.timezone,
            supported_outputs=frozenset(), world_id="default", world_revision=1,
            activity_id=None, activity_revision=None, planning_cycle_id=None,
            schedule_revision=0,
        ),
        cancellation=d.CancellationToken(),
    )


def _handling(fact: d.DiaryPlanningDue, *, plan_id: str | None = "plan") -> d.HandlingReport:
    return d.HandlingReport(
        request_id="req", trigger_stimulus_id=fact.stimulus_id,
        basis_interaction_revision=1, request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=(fact.stimulus_id,),
        consumed_pending_stimulus_ids=(fact.stimulus_id,), retained_pending_stimulus_ids=(),
        emitted_plan_ids=(plan_id,) if plan_id else (), error_code=None, retryable=False,
    )


def _execution(fact: d.DiaryPlanningDue, *, committed: bool) -> tuple[d.ActionPlan, d.ExecutionReport]:
    action = d.WriteDiary(
        action_id="action", owner_user_id=fact.owner_user_id,
        local_date=fact.local_date, body="今天聊了很多值得记住的事情。",
    )
    plan = d.ActionPlan(
        plan_id="plan", origin_request_id="req", plan_ordinal=1,
        target_character_id="luotianyi", interaction_id="wi",
        basis_interaction_revision=1, source_stimulus_ids=(fact.stimulus_id,),
        actions=(action,),
    )
    result = d.ActionResult(
        action_id=action.action_id,
        status=(d.ActionExecutionStatus.COMPLETED if committed else d.ActionExecutionStatus.FAILED),
        error_code=(None if committed else d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE),
        irreversible_effect_committed=committed,
        effect_ref=(d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="diary-1")
                    if committed else None),
    )
    report = d.ExecutionReport(
        execution_id="execution", plan_id=plan.plan_id,
        status=(d.ExecutionStatus.COMPLETED if committed else d.ExecutionStatus.FAILED),
        action_results=(result,), output_started=False,
        error_code=(None if committed else d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE),
        retryable=False,
    )
    return plan, report


def test_diary_task_defaults_and_no_character_runtime_dependency():
    task = DiaryTask({}, character_id="luotianyi")
    assert task.get_task_type() == "daily"
    assert task.get_task_params() == {"hour": 0, "minute": 0}
    assert task.min_daily_conversations == 50
    assert task.max_users_per_run == 20
    assert not hasattr(task, "character_runtime")


def test_run_once_randomly_samples_and_submits_one_world_fact_per_user(monkeypatch):
    users = [f"user-{index}" for index in range(25)]
    sink = FactSink()
    task = _task(users, sink, limit=20)
    monkeypatch.setattr("src.world.diary.task.random.sample", lambda population, count: population[-count:])

    result = asyncio.run(task.run_once())

    assert [fact.owner_user_id for fact in sink.facts] == users[-20:]
    assert result.data["selected_users_count"] == 20
    assert result.data["diaries_pending"] == 20
    assert {fact.trigger_id for fact in sink.facts} == {
        f"diary:luotianyi:{date.today().isoformat()}"
    }
    for fact in sink.facts:
        assert fact.source is d.StimulusSource.WORLD
        assert fact.user_id is None
        assert fact.target_character_ids == ("luotianyi",)
        assert fact.occurred_at.tzinfo is not None
        assert fact.timezone == ZoneInfo("Asia/Shanghai")


def test_rejected_fact_is_not_retried_and_remains_pending():
    sink = FactSink(accepted=False)
    task = _task(["user-1"], sink)

    result = asyncio.run(task.run_once())

    assert len(sink.facts) == 1
    assert result.data["facts_rejected"] == 1
    assert result.data["diaries_pending"] == 1


def test_settlement_maps_effect_to_created_and_failure_to_failed():
    sink = FactSink()
    router = WorldSettlementRouter()
    task = _task(["user-created", "user-failed"], sink, router=router)
    asyncio.run(task.run_once())

    for fact, committed in zip(sink.facts, (True, False), strict=True):
        request = _request(fact)
        router.on_handling_settled(request, _handling(fact))
        plan, report = _execution(fact, committed=committed)
        router.on_execution_finished(plan, report)

    assert task._outcomes == {"user-created": "created", "user-failed": "failed"}


def test_model_availability_is_not_checked_by_world():
    sink = FactSink()
    runtime = SimpleNamespace(
        database_manager=SimpleNamespace(get_sql_session=lambda: None),
        infrastructure=SimpleNamespace(diary=SimpleNamespace(ensure_llm=lambda: False)),
        get_world_stage=lambda character_id: _stage(sink, character_id),
    )
    task = DiaryTask({}, settlements=WorldSettlementRouter())
    task.initialize(runtime)
    task._find_active_users = lambda target_date: ["user-1"]

    result = asyncio.run(task.run_once())

    assert len(sink.facts) == 1
    assert result.data["diaries_pending"] == 1


def test_find_active_users_applies_threshold_character_and_existing_diary_dedup():
    engine, session_factory = _diary_query_database()
    session = session_factory()
    try:
        for user_id in ("eligible", "below", "has-diary"):
            session.add(User(uuid=user_id, username=user_id, password="hash"))
        for index in range(2):
            session.add(Conversation(
                uuid=f"eligible-{index}", user_id="eligible", character_id="luotianyi",
                timestamp=datetime(2026, 7, 16, 12, index), source="user", type="text",
                content="hello",
            ))
            session.add(Conversation(
                uuid=f"diary-{index}", user_id="has-diary", character_id="luotianyi",
                timestamp=datetime(2026, 7, 16, 13, index), source="user", type="text",
                content="hello",
            ))
        session.add(Conversation(
            uuid="below-0", user_id="below", character_id="luotianyi",
            timestamp=datetime(2026, 7, 16, 14, 0), source="user", type="text", content="hello",
        ))
        session.add(DynamicPost(
            id="existing", author_type="agent", author_id="luotianyi",
            owner_user_id="has-diary", visibility="private", content="diary",
            source_type="diary", source_id="diary:luotianyi:has-diary:2026-07-16",
            status="published", created_at=datetime(2026, 7, 16, 23, 59),
        ))
        session.commit()
        task = DiaryTask({"min_daily_conversations": 2})
        task.database_manager = SimpleNamespace(get_sql_session=session_factory)

        assert task._find_active_users("2026-07-16") == ["eligible"]
    finally:
        session.close()
        engine.dispose()
