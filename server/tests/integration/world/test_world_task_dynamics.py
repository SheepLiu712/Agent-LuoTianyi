import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent.handlers.action.dynamic import PublishDynamicHandler
from src.agent.handlers.stimulus.citywalk import CitywalkObservationHandler
from src.agent.handlers.stimulus.song_learned import SongLearnedHandler
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.cognitive.learned_song_experience import (
    LearnedSongExperienceSkill,
)
from src.agent.skills.contracts import CharacterNarrative
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.expression.song_learning import SongLearningDispatchSkill
from src.agent.skills.expression._dynamic_operations import DynamicOperations
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


NARRATIVES = {"luotianyi": CharacterNarrative(name="洛天依", persona="", speaking_style="")}


def _publishing(dynamic_operations):
    return DynamicPublishingSkill(dynamic_operations, NARRATIVES)


def _emitter(request, sink):
    context = SimpleNamespace(identity=SimpleNamespace(character_id="luotianyi", user_id=None, interaction_id="wi"))
    return PlanEmitter(character_id="luotianyi", request=request, sink=sink, context=context)


class FakeFactSink:
    """记录世界事实并一律受理。"""

    def __init__(self):
        self.facts = []

    async def submit(self, fact):
        self.facts.append(fact)
        return True


class FakeMemory:
    """记录学会经验写入，默认成功。"""

    def __init__(self):
        self.calls = []

    async def write_event_memory(self, *, user_id, content, commit=True):
        self.calls.append((user_id, content))
        return True


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

    dynamic_operations = DynamicOperations()
    dynamic_operations.wire_dependencies(database_manager=db_manager)

    async def fake_generate_world_dynamic_content(**kwargs):
        return "今天在上海的武康路散步，风很舒服。"

    dynamic_operations.generate_world_dynamic_content = fake_generate_world_dynamic_content
    publishing = _publishing(dynamic_operations)

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
        request_id="req",
        stimulus=fact,
        interaction=d.WorldInteractionSnapshot(
            interaction_id="wi",
            interaction_revision=1,
            user_id=None,
            pending_stimuli=(fact,),
            now=fact.occurred_at,
            timezone=ZoneInfo("UTC"),
            supported_outputs=frozenset(),
            world_id="default",
            world_revision=fact.world_revision,
            activity_id=None,
            activity_revision=None,
            planning_cycle_id=None,
            schedule_revision=0,
        ),
        cancellation=d.CancellationToken(),
    )
    plan_sink = PlanSink()
    handling = asyncio.run(
        CitywalkObservationHandler(publishing).handle(
            request,
            _emitter(request, plan_sink),
        )
    )
    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    plan = plan_sink.plans[0]

    action_result = asyncio.run(
        PublishDynamicHandler("luotianyi", publishing).realize(
            plan.actions[0],
            d.ExecutionContext(
                execution_id="e",
                interaction_id="wi",
                current_interaction_revision=1,
                cancellation=d.CancellationToken(),
            ),
            None,
        )
    )
    assert action_result.effect_ref.kind is d.EffectKind.DYNAMIC_POST

    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    assert feed["items"][0]["source_type"] == "citywalk"
    assert feed["items"][0]["content"]  # 内容不为空

    router.on_handling_settled(request, handling)
    router.on_execution_finished(
        plan,
        d.ExecutionReport(
            execution_id="e",
            plan_id=plan.plan_id,
            status=d.ExecutionStatus.COMPLETED,
            action_results=(action_result,),
            output_started=False,
            error_code=None,
            retryable=False,
        ),
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dynamic_id"] == action_result.effect_ref.effect_id
    assert report["dynamic_content"] == "今天在上海的武康路散步，风很舒服。"


def test_learn_song_task_publishes_global_dynamic(db_manager: DatabaseManager):
    """学会新歌后由 Agent 侧写经验并发布动态，world 只投递学会事实。"""
    _add_invite_code(db_manager, "INVITE6")
    user = _register_and_login(db_manager, "songuser", "INVITE6")

    dynamic_operations = DynamicOperations()
    dynamic_operations.wire_dependencies(database_manager=db_manager)

    async def fake_generate_world_dynamic_content(**kwargs):
        return "今天学会了《告死鸟》，下次可以唱给你听。"

    dynamic_operations.generate_world_dynamic_content = fake_generate_world_dynamic_content
    publishing = _publishing(dynamic_operations)

    class FakeLearner:
        def check_qq_credential(self):
            return True

        def try_learn_pending(self):
            return SimpleNamespace(learned=["告死鸟"], abandoned=[], awaiting=[])

    class FakeEventStore:
        async def add_event(self, payload):
            return payload

    class FakeSinging:
        def add_wished_song(self, song_name: str):
            return True

        def reload_songs(self, character_id: str):
            return character_id

        async def tag_song_emotions(self, character_id: str, song_name: str):
            return []

        def can_i_sing_song(self, song_name: str):
            return song_name, ["主歌"]

        def get_full_lyrics(self, song_name: str):
            return "第一句歌词"

        def get_segment_lyrics(self, song_name: str, segment_description: str):
            return "第一句歌词"

    sink = FakeFactSink()

    async def get_world_stage(character_id=None, world_id=None):
        return SimpleNamespace(fact_sink=sink)

    task = LearnSingSongsTask({}, character_id="luotianyi", singing_manager=None)
    task.system_runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        get_world_stage=get_world_stage,
        infrastructure=SimpleNamespace(
            singing=FakeSinging(),
        ),
    )
    task.event_store = FakeEventStore()
    task.auto_song_learner = FakeLearner()

    result = asyncio.run(task.run_once())
    assert result.ok is True
    assert result.data["submitted_count"] == 1

    fact = sink.facts[0]
    request = d.HandleStimulusRequest(
        request_id="req",
        stimulus=fact,
        interaction=d.WorldInteractionSnapshot(
            interaction_id="wi",
            interaction_revision=1,
            user_id=None,
            pending_stimuli=(fact,),
            now=fact.occurred_at,
            timezone=ZoneInfo("UTC"),
            supported_outputs=frozenset(),
            world_id="default",
            world_revision=1,
            activity_id=None,
            activity_revision=None,
            planning_cycle_id=None,
            schedule_revision=0,
        ),
        cancellation=d.CancellationToken(),
    )
    plan_sink = PlanSink()
    handling = asyncio.run(
        SongLearnedHandler(
            "luotianyi",
            LearnedSongExperienceSkill({"luotianyi": FakeMemory()}),
            publishing,
            SongLearningDispatchSkill(SimpleNamespace(singing_manager={"luotianyi": FakeSinging()})),
        ).handle(request, _emitter(request, plan_sink))
    )
    plan = plan_sink.plans[0]
    action_result = asyncio.run(
        PublishDynamicHandler("luotianyi", publishing).realize(
            plan.actions[0],
            d.ExecutionContext(
                execution_id="e",
                interaction_id="wi",
                current_interaction_revision=1,
                cancellation=d.CancellationToken(),
            ),
            None,
        )
    )
    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    assert action_result.effect_ref.kind is d.EffectKind.DYNAMIC_POST

    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    assert feed["items"][0]["source_type"] == "song_learned"
    assert feed["items"][0]["content"]  # 内容不为空


def test_learned_song_dynamic_is_idempotent_by_character_and_song(
    db_manager: DatabaseManager,
):
    _add_invite_code(db_manager, "INVITE6B")
    user = _register_and_login(db_manager, "songuser2", "INVITE6B")
    dynamic_operations = DynamicOperations()
    dynamic_operations.wire_dependencies(database_manager=db_manager)
    compose_calls = []

    async def fake_compose(**kwargs):
        compose_calls.append(kwargs["song_name"])
        return f"学会了《{kwargs['song_name']}》"

    dynamic_operations.compose_learned_song_dynamic_content = fake_compose

    first = asyncio.run(
        dynamic_operations.publish_learned_song_dynamic(
            character_id="luotianyi",
            character_name="洛天依",
            character_persona="",
            speaking_style="",
            song_name="告死鸟",
        )
    )
    second = asyncio.run(
        dynamic_operations.publish_learned_song_dynamic(
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
        item for item in feed["items"] if item["source_type"] == "song_learned" and item["source_id"] == "告死鸟"
    ]
    assert len(learned_items) == 1


def _build_dynamic_task(
    db_manager: DatabaseManager,
    sink: "FakeFactSink",
    *,
    router: WorldSettlementRouter | None = None,
    config: dict | None = None,
) -> DynamicInteractionTask:
    """构造只依赖 system_runtime/database 的动态互动任务，不提供 CharacterRuntime。"""

    async def get_world_stage(character_id=None, world_id=None):
        return SimpleNamespace(fact_sink=sink)

    task = DynamicInteractionTask(config or {}, settlements=router or WorldSettlementRouter())
    task.initialize(
        SimpleNamespace(
            database_manager=db_manager,
            agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
            get_world_stage=get_world_stage,
        )
    )
    return task


def _dynamic_observation_request(fact: d.DynamicObserved) -> d.HandleStimulusRequest:
    """按事实构造一次处理请求，供结算回调使用。"""
    return d.HandleStimulusRequest(
        request_id="req",
        stimulus=fact,
        interaction=d.WorldInteractionSnapshot(
            interaction_id="wi",
            interaction_revision=1,
            user_id=None,
            pending_stimuli=(fact,),
            now=fact.occurred_at,
            timezone=ZoneInfo("UTC"),
            supported_outputs=frozenset(),
            world_id="default",
            world_revision=fact.revision,
            activity_id=None,
            activity_revision=None,
            planning_cycle_id=None,
            schedule_revision=0,
        ),
        cancellation=d.CancellationToken(),
    )


def _handling_report(
    fact: d.DynamicObserved,
    *,
    status: d.HandlingRequestStatus = d.HandlingRequestStatus.COMPLETED,
    plan_ids: tuple[str, ...] = (),
    error_code: d.HandlingErrorCode | None = None,
) -> d.HandlingReport:
    """构造处理结算：无计划且被消费即「明确忽略」。"""
    consumed = (fact.stimulus_id,) if status is not d.HandlingRequestStatus.FAILED else ()
    return d.HandlingReport(
        request_id="req",
        trigger_stimulus_id=fact.stimulus_id,
        basis_interaction_revision=1,
        request_status=status,
        considered_pending_stimulus_ids=(fact.stimulus_id,),
        consumed_pending_stimulus_ids=consumed,
        retained_pending_stimulus_ids=(() if consumed else (fact.stimulus_id,)),
        emitted_plan_ids=plan_ids,
        error_code=error_code,
        retryable=False,
    )


def _create_user_post(db_manager: DatabaseManager, auth: dict, content: str) -> str:
    ok, _, created = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content=content,
        source_type="user_post",
    )
    assert ok is True
    return created["id"]


def test_dynamic_interaction_submits_one_observation_per_pending_target(
    db_manager: DatabaseManager,
):
    """world 只投递结构化事实：同一目标一轮只投递一次，且不依赖 CharacterRuntime。"""
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")
    dynamic_id = _create_user_post(db_manager, auth, "今天其实有点紧张，不过也算坚持下来了。")

    sink = FakeFactSink()
    task = _build_dynamic_task(db_manager, sink)

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["reply_processed"] == 1
    assert result.data["memory_processed"] == 1
    assert not hasattr(task, "character_runtime")
    assert len(sink.facts) == 1  # 回复与记忆两方面共享同一条事实

    fact = sink.facts[0]
    assert fact.dynamic_id == dynamic_id
    assert fact.target_message_id == dynamic_id
    assert fact.target_kind is d.DynamicTargetKind.POST
    assert fact.messages[0].message_id == dynamic_id
    assert fact.messages[0].parent_message_id is None
    assert fact.messages[0].author_ref.actor_id == auth["user_uuid"]
    assert fact.revision == len(fact.messages)


def test_dynamic_interaction_keeps_pending_until_settlement(db_manager: DatabaseManager):
    """未收到结算时世界侧不猜测状态：目标保持 pending，并计入本轮的未结算数。"""
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")
    dynamic_id = _create_user_post(db_manager, auth, "刚刚把这段话写下来了。")

    sink = FakeFactSink()
    task = _build_dynamic_task(db_manager, sink)
    result = asyncio.run(task.run_once())

    assert result.data["reply_pending"] == 1
    assert result.data["memory_pending"] == 1
    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "pending"
    assert target["memory_status"] == "pending"


def test_dynamic_interaction_writes_status_from_settlement_only(db_manager: DatabaseManager):
    """只有实际提交的评论效果才写 replied；处理完成即记忆方面已处理。"""
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")
    dynamic_id = _create_user_post(db_manager, auth, "今天把该做的事都做完了。")

    sink = FakeFactSink()
    router = WorldSettlementRouter()
    task = _build_dynamic_task(db_manager, sink, router=router)
    asyncio.run(task.run_once())
    fact = sink.facts[0]

    request = _dynamic_observation_request(fact)
    plan_sink = PlanSink()
    action = d.ReplyDynamic(
        action_id="a1",
        body="我看到你坚持下来了，辛苦啦。",
        target=d.DynamicReplyTarget(dynamic_id=dynamic_id, parent_comment_id=None),
        owner_user_id=auth["user_uuid"],
    )
    receipt = asyncio.run(
        PlanEmitter(character_id="luotianyi", request=request, sink=plan_sink).emit(
            ActionPlanDraft(source_stimulus_ids=(fact.stimulus_id,), actions=(action,)),
        )
    )
    router.on_handling_settled(request, _handling_report(fact, plan_ids=(receipt.plan_id,)))
    router.on_execution_finished(
        plan_sink.plans[0],
        d.ExecutionReport(
            execution_id="e",
            plan_id=receipt.plan_id,
            status=d.ExecutionStatus.COMPLETED,
            action_results=(
                d.ActionResult(
                    action_id="a1",
                    status=d.ActionExecutionStatus.COMPLETED,
                    error_code=None,
                    irreversible_effect_committed=True,
                    effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_COMMENT, effect_id="comment-1"),
                ),
            ),
            output_started=False,
            error_code=None,
            retryable=False,
        ),
    )

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "replied"
    assert target["memory_status"] == "written"


def test_dynamic_interaction_records_explicit_ignore(db_manager: DatabaseManager):
    """明确不回复时由处理结算写 ignored，而不是把「计划被接受」当发布成功。"""
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")
    dynamic_id = _create_user_post(db_manager, auth, "今天想在评论区安静一会儿。")

    sink = FakeFactSink()
    router = WorldSettlementRouter()
    task = _build_dynamic_task(db_manager, sink, router=router)
    asyncio.run(task.run_once())
    fact = sink.facts[0]

    router.on_handling_settled(_dynamic_observation_request(fact), _handling_report(fact))

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "ignored"
    assert target["memory_status"] == "written"


def test_dynamic_interaction_failure_marks_both_aspects_failed(db_manager: DatabaseManager):
    """处理失败时回复与记忆两个方面都不得停留在 pending。"""
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")
    dynamic_id = _create_user_post(db_manager, auth, "今天有点累。")

    sink = FakeFactSink()
    router = WorldSettlementRouter()
    task = _build_dynamic_task(db_manager, sink, router=router)
    asyncio.run(task.run_once())
    fact = sink.facts[0]

    router.on_handling_settled(
        _dynamic_observation_request(fact),
        _handling_report(
            fact,
            status=d.HandlingRequestStatus.FAILED,
            error_code=d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE,
        ),
    )

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "failed"
    assert target["memory_status"] == "failed"


def test_dynamic_interaction_marks_memory_only_target_written(db_manager: DatabaseManager):
    """已回复的目标只承担记忆方面：结算后只写记忆列，不重复投递回复。"""
    _add_invite_code(db_manager, "INVITE8")
    auth = _register_and_login(db_manager, "memoryuser", "INVITE8")
    dynamic_id = _create_user_post(db_manager, auth, "我最近开始重新练吉他了。")
    assert (
        db_manager.dynamic_store.update_dynamic_post_reply_state(
            dynamic_id,
            status="replied",
            error=None,
        )
        is True
    )

    sink = FakeFactSink()
    router = WorldSettlementRouter()
    task = _build_dynamic_task(db_manager, sink, router=router)

    result = asyncio.run(task.run_once())

    assert result.data["reply_processed"] == 0
    assert result.data["memory_processed"] == 1
    assert len(sink.facts) == 1

    router.on_handling_settled(_dynamic_observation_request(sink.facts[0]), _handling_report(sink.facts[0]))

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "replied"
    assert target["memory_status"] == "written"


def test_dynamic_interaction_limits_targets_per_pass(db_manager: DatabaseManager):
    """批量上限仍然由 world 决定：正文与评论各自按配置取件。"""
    _add_invite_code(db_manager, "INVITE9")
    auth = _register_and_login(db_manager, "limituser", "INVITE9")
    for index in range(3):
        _create_user_post(db_manager, auth, f"第 {index} 条动态正文。")

    sink = FakeFactSink()
    task = _build_dynamic_task(
        db_manager,
        sink,
        config={"reply_post_limit": 2, "memory_post_limit": 2},
    )
    result = asyncio.run(task.run_once())

    assert result.data["reply_processed"] == 2
    assert result.data["memory_processed"] == 2
    assert len(sink.facts) == 2
