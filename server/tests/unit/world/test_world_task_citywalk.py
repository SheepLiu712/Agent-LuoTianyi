import asyncio
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.world.citywalk.errors import AMapRequestError
from src.world.citywalk.task import CitywalkTask
from src.world.world_settlements import WorldSettlementRouter


class FakeEventStore:
    def __init__(self):
        self.events = []

    async def add_event(self, event):
        self.events.append(event)
        return "event-id"


class FakeFactSink:
    def __init__(self, accept=True):
        self.facts = []
        self.accept = accept

    async def submit(self, fact):
        self.facts.append(fact)
        return self.accept


def server_runtime(*, accept=True, event_store=None):
    stage = SimpleNamespace(fact_sink=FakeFactSink(accept))

    async def get_world_stage(character_id=None, world_id=None):
        return stage

    runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        get_world_stage=get_world_stage,
        database_manager=SimpleNamespace(event_store=event_store or FakeEventStore()),
    )
    return runtime, stage


def write_report(tmp_path, **overrides):
    payload = {
        "overview": {"city": "上海", "selected_destination": "武康路", "total_duration_minutes": 90},
        "places": ["武康路", "安福路"],
        "event_cards": [],
        "diary_text": "今天在武康路散步，风很舒服。",
    }
    payload.update(overrides)
    path = tmp_path / "citywalk_20260705_120000.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def execution_report(plan):
    return d.ExecutionReport(
        execution_id="exec", plan_id=plan.plan_id, status=d.ExecutionStatus.COMPLETED,
        action_results=(d.ActionResult(
            action_id=plan.actions[0].action_id, status=d.ActionExecutionStatus.COMPLETED,
            error_code=None, irreversible_effect_committed=True,
            effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="dynamic-citywalk"),
        ),),
        output_started=False, error_code=None, retryable=False,
    )


def dynamic_plan(fact, body="今天在武康路散步，风很舒服。"):
    return d.ActionPlan(
        plan_id="plan-citywalk", origin_request_id="req", plan_ordinal=0,
        target_character_id="luotianyi", interaction_id="wi", basis_interaction_revision=1,
        source_stimulus_ids=(fact.stimulus_id,),
        actions=(d.PublishDynamic(
            action_id="action-citywalk", body=body, media_refs=(), visibility=d.Visibility.GLOBAL,
            owner_user_id=None,
            source=d.DynamicSource(source_type="citywalk", source_id=fact.fact.fact_id),
            allow_comment=True,
        ),),
    )


def test_citywalk_normalize_overview():
    assert CitywalkTask._normalize_overview("report.md").endswith("report.md")
    assert CitywalkTask._normalize_overview("plain summary") == "plain summary"


def test_citywalk_run_once_skips_without_service():
    task = CitywalkTask({})

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.skipped is True


def test_citywalk_run_once_writes_travel_event():
    event_store = FakeEventStore()
    task = CitywalkTask({"daily_run_probability": 1.0})
    task.event_store = event_store
    task.citywalk_service = SimpleNamespace(run_once=lambda: "data/citywalk_reports/today.md")

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["output_path"].endswith("today.md")
    assert result.data["observation_submitted"] is False
    assert len(event_store.events) == 1
    event = event_store.events[0]
    assert event["event_type"] == "travel"
    assert event["source"] == "world_citywalk"
    assert "today.md" in event["description"]


def test_citywalk_run_once_submits_world_observation(tmp_path):
    router = WorldSettlementRouter()
    report_path = write_report(tmp_path)
    runtime, stage = server_runtime()
    task = CitywalkTask({"daily_run_probability": 1.0}, settlements=router)
    task.server_runtime = runtime
    task.event_store = runtime.database_manager.event_store
    task.citywalk_service = SimpleNamespace(run_once=lambda: str(report_path))

    result = asyncio.run(task.run_once())

    assert result.data["observation_submitted"] is True
    assert len(stage.fact_sink.facts) == 1
    fact = stage.fact_sink.facts[0]
    assert isinstance(fact, d.WorldObservation)
    assert fact.observation_kind.value == "citywalk_completed"
    assert fact.fact.fact_id == f"citywalk:{report_path}"
    assert fact.fact.summary == "今天在武康路散步，风很舒服。"
    assert fact.source is d.StimulusSource.WORLD
    assert fact.user_id is None
    assert fact.target_character_ids == ("luotianyi",)
    assert fact.world_revision > 0
    assert router.awaiting_settlement == (fact.stimulus_id,)


def test_citywalk_dynamic_identity_is_written_back_from_settlement(tmp_path):
    router = WorldSettlementRouter()
    report_path = write_report(tmp_path)
    runtime, stage = server_runtime()
    task = CitywalkTask({"daily_run_probability": 1.0}, settlements=router)
    task.server_runtime = runtime
    task.event_store = runtime.database_manager.event_store
    task.citywalk_service = SimpleNamespace(run_once=lambda: str(report_path))

    asyncio.run(task.run_once())
    fact = stage.fact_sink.facts[0]
    plan = dynamic_plan(fact)

    router.on_handling_settled(
        d.HandleStimulusRequest(
            request_id="req", stimulus=fact,
            interaction=d.WorldInteractionSnapshot(
                interaction_id="wi", interaction_revision=1, user_id=None, pending_stimuli=(fact,),
                now=fact.occurred_at, timezone=ZoneInfo("UTC"),
                supported_outputs=frozenset(), world_id="default", world_revision=fact.world_revision,
                activity_id=None, activity_revision=None, planning_cycle_id=None, schedule_revision=0,
            ),
            cancellation=d.CancellationToken(),
        ),
        d.HandlingReport(
            request_id="req", trigger_stimulus_id=fact.stimulus_id, basis_interaction_revision=1,
            request_status=d.HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=(fact.stimulus_id,),
            consumed_pending_stimulus_ids=(fact.stimulus_id,), retained_pending_stimulus_ids=(),
            emitted_plan_ids=(plan.plan_id,), error_code=None, retryable=False,
        ),
    )
    router.on_execution_finished(plan, execution_report(plan))

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["diary_text"] == "今天在武康路散步，风很舒服。"
    assert report["dynamic_content"] == "今天在武康路散步，风很舒服。"
    assert report["dynamic_id"] == "dynamic-citywalk"
    assert router.awaiting_settlement == ()


def test_citywalk_rejected_observation_is_reported_and_discarded(tmp_path):
    router = WorldSettlementRouter()
    report_path = write_report(tmp_path)
    runtime, stage = server_runtime(accept=False)
    task = CitywalkTask({"daily_run_probability": 1.0}, settlements=router)
    task.server_runtime = runtime
    task.event_store = runtime.database_manager.event_store
    task.citywalk_service = SimpleNamespace(run_once=lambda: str(report_path))

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["observation_submitted"] is False
    assert len(stage.fact_sink.facts) == 1
    assert router.awaiting_settlement == ()
    assert len(runtime.database_manager.event_store.events) == 1


def test_citywalk_observation_summary_falls_back_without_narrative():
    summary = CitywalkTask.build_observation_summary(
        {"overview": {"selected_destination": "武康路", "total_duration_minutes": 90},
         "places": ["武康路", "安福路"], "diary_text": ""}
    )

    assert "武康路" in summary and "安福路" in summary and "90分钟" in summary
    assert CitywalkTask.build_observation_summary({}) == "完成了一次城市散步"


def test_citywalk_run_once_skips_when_no_diary():
    task = CitywalkTask({"daily_run_probability": 1.0})
    task.citywalk_service = SimpleNamespace(run_once=lambda: "")

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.skipped is True


def test_citywalk_run_once_skips_runtime_error():
    task = CitywalkTask({"daily_run_probability": 1.0})

    def fail():
        raise AMapRequestError("AMap timed out")

    task.citywalk_service = SimpleNamespace(run_once=fail)

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.skipped is True
    assert result.data["error"] == "AMap timed out"


def test_citywalk_run_once_skips_when_daily_sample_misses():
    calls = []
    task = CitywalkTask({"daily_run_probability": 0.0})
    task.citywalk_service = SimpleNamespace(run_once=lambda: calls.append("run"))

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.skipped is True
    assert result.message == "citywalk daily sample skipped"
    assert result.data["probability"] == 0.0
    assert calls == []


def test_citywalk_build_llm_modules_registers_expected_modules():
    class FakeLLMService:
        def __init__(self):
            self.llm_names = []
            self.vlm_names = []

        def register_llm_module(self, name, config):
            self.llm_names.append((name, config))
            return SimpleNamespace(name=name)

        def register_vlm_module(self, name, config):
            self.vlm_names.append((name, config))
            return SimpleNamespace(name=name)

    llm_service = FakeLLMService()
    task = CitywalkTask({"decision": {"llm": {"name": "test-model"}}})
    task.server_runtime = SimpleNamespace(llm_service=llm_service)

    modules = task._build_llm_modules()

    assert modules.json_module.name == "luotianyi_citywalk_json"
    assert modules.text_module.name == "luotianyi_citywalk_text"
    assert modules.vlm_module.name == "luotianyi_citywalk_vlm"
    assert [name for name, _ in llm_service.llm_names] == ["luotianyi_citywalk_json", "luotianyi_citywalk_text"]
    assert [name for name, _ in llm_service.vlm_names] == ["luotianyi_citywalk_vlm"]


def test_citywalk_build_citywalk_service_skips_without_runtime():
    task = CitywalkTask({})

    assert task._build_citywalk_service() is None


def test_citywalk_build_citywalk_service_skips_without_vector_store():
    task = CitywalkTask({})
    task.server_runtime = SimpleNamespace(agent_runtime=SimpleNamespace(vector_store=None))

    assert task._build_citywalk_service() is None


def test_citywalk_initialize_uses_runtime_dependencies(monkeypatch):
    task = CitywalkTask({})
    built = object()
    monkeypatch.setattr(task, "_build_citywalk_service", lambda: built)
    event_store = object()
    runtime = SimpleNamespace(
        database_manager=SimpleNamespace(event_store=event_store),
        agent_runtime=SimpleNamespace(vector_store=object()),
    )

    task.initialize(runtime)

    assert task.server_runtime is runtime
    assert task.event_store is event_store
    assert task.citywalk_service is built
    assert not hasattr(task, "character_runtime")
