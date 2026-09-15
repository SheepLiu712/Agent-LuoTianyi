import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent.handlers.action.dynamic import PublishDynamicHandler
from src.agent.handlers.stimulus.citywalk import CitywalkObservationHandler
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.capabilities.dynamic import DynamicCapability
from src.system.database.database_service import DatabaseManager
from src.system.database.sql_database import InviteCode
from src.world.citywalk.task import CitywalkTask
from src.world.dynamic_interaction.task import DynamicInteractionTask
from src.world.learn_sing_songs.task import LearnSingSongsTask
from src.world.world_settlements import WorldSettlementRouter


class PlanSink:
    """记录交付计划并返回确认回执。"""

    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


@pytest.fixture(scope="function")
def db_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    manager = DatabaseManager(
        {
            "sql_db_folder": str(tmp_path / "db"),
            "sql_db_file": "test.db",
        }
    )
    try:
        yield manager
    finally:
        asyncio.run(manager.shutdown())


def _add_invite_code(db_manager: DatabaseManager, code: str) -> None:
    session = db_manager.open_sql_session()
    session.add(InviteCode(code=code, is_used=False))
    session.commit()
    session.close()


def _register_and_login(db_manager: DatabaseManager, username: str, invite_code: str) -> dict:
    ok, message = db_manager.credential_service.register_user(username, "password123", invite_code)
    assert ok is True, message
    result = db_manager.credential_service.authenticate_password_login(username, "password123")
    assert result is not None
    return result


def test_citywalk_completion_publishes_global_dynamic(db_manager: DatabaseManager, tmp_path: Path):
    """散步完成后由 Agent 侧决定并发布动态，world 只投递事实。"""
    _add_invite_code(db_manager, "INVITE5")
    user = _register_and_login(db_manager, "cityuser", "INVITE5")

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    async def fake_generate_world_dynamic_content(**kwargs):
        return "今天在上海的武康路散步，风很舒服。"

    dynamic_capability.generate_world_dynamic_content = fake_generate_world_dynamic_content
    publishing = DynamicPublishingSkill(dynamic_capability)

    report_path = tmp_path / "citywalk_20260704_120000.json"
    report_path.write_text(
        '{"overview": {"city": "上海", "selected_destination": "武康路"}, '
        '"diary_text": "今天慢慢走了很多路，也看了不少风景。"}',
        encoding="utf-8",
    )

    class FakeCitywalkService:
        def run_once(self) -> str:
            return str(report_path)

    class FakeEventStore:
        async def add_event(self, payload):
            return payload

    class FakeFactSink:
        def __init__(self):
            self.facts = []

        async def submit(self, fact):
            self.facts.append(fact)
            return True

    sink = FakeFactSink()

    async def get_world_stage(character_id=None, world_id=None):
        return SimpleNamespace(fact_sink=sink)

    router = WorldSettlementRouter()
    task = CitywalkTask({"daily_run_probability": 1.0}, settlements=router)
    task.system_runtime = SimpleNamespace(
        capability_manager=SimpleNamespace(dynamics=dynamic_capability),
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        get_world_stage=get_world_stage,
    )
    task.database_manager = db_manager
    task.event_store = FakeEventStore()
    task.citywalk_service = FakeCitywalkService()

    result = asyncio.run(task.run_once())
    assert result.ok is True
    assert result.data["observation_submitted"] is True

    fact = sink.facts[0]
    request = d.HandleStimulusRequest(
        request_id="req", stimulus=fact,
        interaction=d.WorldInteractionSnapshot(
            interaction_id="wi", interaction_revision=1, user_id=None, pending_stimuli=(fact,),
            now=fact.occurred_at, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(),
            world_id="default", world_revision=fact.world_revision, activity_id=None,
            activity_revision=None, planning_cycle_id=None, schedule_revision=0,
        ),
        cancellation=d.CancellationToken(),
    )
    plan_sink = PlanSink()
    handling = asyncio.run(
        CitywalkObservationHandler(publishing).handle(
            request, PlanEmitter(character_id="luotianyi", request=request, sink=plan_sink),
        )
    )
    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    plan = plan_sink.plans[0]

    action_result = asyncio.run(PublishDynamicHandler("luotianyi", publishing).realize(
        plan.actions[0],
        d.ExecutionContext(execution_id="e", interaction_id="wi", current_interaction_revision=1,
                           cancellation=d.CancellationToken()),
        None,
    ))
    assert action_result.effect_ref.kind is d.EffectKind.DYNAMIC_POST

    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    assert feed["items"][0]["source_type"] == "citywalk"
    assert feed["items"][0]["content"]  # 内容不为空

    router.on_handling_settled(request, handling)
    router.on_execution_finished(plan, d.ExecutionReport(
        execution_id="e", plan_id=plan.plan_id, status=d.ExecutionStatus.COMPLETED,
        action_results=(action_result,), output_started=False, error_code=None, retryable=False,
    ))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dynamic_id"] == action_result.effect_ref.effect_id
    assert report["dynamic_content"] == "今天在上海的武康路散步，风很舒服。"


def test_learn_song_task_publishes_global_dynamic(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE6")
    user = _register_and_login(db_manager, "songuser", "INVITE6")

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    async def fake_generate_world_dynamic_content(**kwargs):
        return "今天学会了《告死鸟》，下次可以唱给你听。"

    dynamic_capability.generate_world_dynamic_content = fake_generate_world_dynamic_content

    class FakeLearner:
        def check_qq_credential(self):
            return True

        def try_learn_pending(self):
            return SimpleNamespace(learned=["告死鸟"], abandoned=[], awaiting=[])

    class FakeEventStore:
        async def add_event(self, payload):
            return payload

    class FakeSinging:
        def reload_songs(self, character_id: str):
            return character_id

    class FakeCharacterRuntime:
        async def publish_learned_song_dynamic(self, **kwargs):
            return await dynamic_capability.publish_learned_song_dynamic(
                character_id="luotianyi",
                character_name="洛天依",
                character_persona="",
                speaking_style="",
                **kwargs,
            )

    task = LearnSingSongsTask({}, character_id="luotianyi", singing_manager=None)
    task.system_runtime = SimpleNamespace(
        capability_manager=SimpleNamespace(
            dynamics=dynamic_capability,
            singing=FakeSinging(),
        ),
    )
    task.event_store = FakeEventStore()
    task.character_runtime = FakeCharacterRuntime()
    task.auto_song_learner = FakeLearner()

    result = task.run_once()
    assert result.ok is True
    assert result.data["dynamic_ids"]

    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    assert feed["items"][0]["source_type"] == "song_learned"
    assert feed["items"][0]["content"]  # 内容不为空


def test_learned_song_dynamic_is_idempotent_by_character_and_song(
    db_manager: DatabaseManager,
):
    _add_invite_code(db_manager, "INVITE6B")
    user = _register_and_login(db_manager, "songuser2", "INVITE6B")
    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)
    compose_calls = []

    async def fake_compose(**kwargs):
        compose_calls.append(kwargs["song_name"])
        return f"学会了《{kwargs['song_name']}》"

    dynamic_capability.compose_learned_song_dynamic_content = fake_compose

    first = asyncio.run(
        dynamic_capability.publish_learned_song_dynamic(
            character_id="luotianyi",
            character_name="洛天依",
            character_persona="",
            speaking_style="",
            song_name="告死鸟",
        )
    )
    second = asyncio.run(
        dynamic_capability.publish_learned_song_dynamic(
            character_id="luotianyi",
            character_name="洛天依",
            character_persona="",
            speaking_style="",
            song_name="告死鸟",
        )
    )

    assert first["dynamic_id"] == second["dynamic_id"]
    assert first["created"] is True
    assert second["created"] is False
    assert compose_calls == ["告死鸟"]
    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    learned_items = [
        item
        for item in feed["items"]
        if item["source_type"] == "song_learned" and item["source_id"] == "告死鸟"
    ]
    assert len(learned_items) == 1


def test_dynamic_interaction_task_replies_and_updates_status(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")

    ok, _, created = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="今天其实有点紧张，不过也算坚持下来了。",
        source_type="user_post",
    )
    assert ok is True
    dynamic_id = created["id"]

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    class FakeReplier:
        def ensure_llm(self) -> bool:
            return True

        async def generate_reply_for_post(self, item, **kwargs):
            return "我看到你很努力地撑过来了，辛苦啦。"

        async def generate_reply_for_comment(self, item, **kwargs):
            return {"should_reply": False, "reply": ""}

    class FakeCharacterRuntime:
        capability_manager = SimpleNamespace(dynamics=dynamic_capability)

        async def generate_dynamic_reply_for_post(self, item):
            return await dynamic_capability.replier.generate_reply_for_post(item, character_name="洛天依")

        async def generate_dynamic_reply_for_comment(self, item):
            return await dynamic_capability.replier.generate_reply_for_comment(item, character_name="洛天依")

        def publish_dynamic_comment(self, **kwargs):
            return dynamic_capability.publish_agent_comment(character_id="luotianyi", **kwargs)

    class FakeAgentRuntime:
        async def write_topic_memories(self, **kwargs):
            return {"payload": {"user_memory": [], "event_memory": []}, "items": []}

    task = DynamicInteractionTask({})
    task.system_runtime = SimpleNamespace()
    task.database_manager = db_manager
    dynamic_capability.replier = FakeReplier()
    task.character_runtime = FakeCharacterRuntime()
    task.agent_runtime = FakeAgentRuntime()

    result = asyncio.run(task.run_once())
    assert result.ok is True
    assert result.data["reply_replied"] == 1

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "replied"
    ok, _, comments = db_manager.dynamic_store.list_dynamic_comments_for_user(auth["user_uuid"], dynamic_id)
    assert ok is True
    assert comments["items"][0]["author_type"] == "agent"
    assert "辛苦" in comments["items"][0]["content"]


def test_dynamic_interaction_task_processes_memory_status(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE8")
    auth = _register_and_login(db_manager, "memoryuser", "INVITE8")

    ok, _, created = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="我最近开始重新练吉他了。",
        source_type="user_post",
    )
    assert ok is True
    dynamic_id = created["id"]

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    class FakeReplier:
        def ensure_llm(self) -> bool:
            return True

        async def generate_reply_for_post(self, item, **kwargs):
            return "我看到你很努力地撑过来了，辛苦啦。"

        async def generate_reply_for_comment(self, item, **kwargs):
            return {"should_reply": False, "reply": ""}

    class FakeCharacterRuntime:
        capability_manager = SimpleNamespace(dynamics=dynamic_capability)

        async def generate_dynamic_reply_for_post(self, item):
            return await dynamic_capability.replier.generate_reply_for_post(item, character_name="洛天依")

        async def generate_dynamic_reply_for_comment(self, item):
            return await dynamic_capability.replier.generate_reply_for_comment(item, character_name="洛天依")

        def publish_dynamic_comment(self, **kwargs):
            return dynamic_capability.publish_agent_comment(character_id="luotianyi", **kwargs)

    class FakeAgentRuntime:
        async def write_topic_memories(self, **kwargs):
            return {
                "payload": {"user_memory": ["用户最近重新开始练吉他"], "event_memory": []},
                "items": [
                    {
                        "memory_type": "user_memory",
                        "content": "用户最近重新开始练吉他",
                        "status": "written",
                    }
                ],
            }

    task = DynamicInteractionTask({})
    task.system_runtime = SimpleNamespace()
    task.database_manager = db_manager
    dynamic_capability.replier = FakeReplier()
    task.character_runtime = FakeCharacterRuntime()
    task.agent_runtime = FakeAgentRuntime()

    result = asyncio.run(task.run_once())
    assert result.ok is True
    assert result.data["memory_written"] == 1

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["memory_status"] == "written"
