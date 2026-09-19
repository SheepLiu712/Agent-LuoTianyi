"""日记事实的正文生成、私密发布和来源幂等。"""

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.handlers.action.write_diary import WriteDiaryHandler
from src.agent.handlers.stimulus.diary_due import DiaryPlanningDueHandler
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.expression.diary_writing import DiaryWritingSkill


class DiaryCapability:
    def __init__(self, body: str = "2026-09-15\n\n今天聊了很多值得记住的事情。") -> None:
        self.body = body
        self.calls = []

    def ensure_llm(self) -> bool:
        return True

    async def generate_diary_body(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.body

    @staticmethod
    def _diary_source_id(character_id: str, user_id: str, target_date: str) -> str:
        return f"diary:{character_id}:{user_id}:{target_date}"


class Dynamics:
    def __init__(self, *, publish_ok: bool = True) -> None:
        self.publish_ok = publish_ok
        self.calls = []
        self.by_source = {}

    def publish_agent_dynamic(self, **kwargs):
        self.calls.append(kwargs)
        key = (kwargs["character_id"], kwargs["source_type"], kwargs["source_id"])
        if not self.publish_ok:
            return False, "failed", None
        item = self.by_source.setdefault(key, {
            "id": f"dynamic-{len(self.by_source) + 1}",
            "owner_user_id": kwargs["owner_user_id"],
        })
        return True, "created", item


class Sink:
    def __init__(self) -> None:
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


def _fact(owner_user_id: str = "user-1") -> d.DiaryPlanningDue:
    return d.DiaryPlanningDue(
        stimulus_id="diary-fact", schema_version=1,
        occurred_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
        source=d.StimulusSource.WORLD, target_character_ids=("luotianyi",),
        user_id=None, ephemeral=False, local_date=date(2026, 9, 15),
        timezone=ZoneInfo("Asia/Shanghai"), trigger_id="diary:luotianyi:2026-09-15",
        owner_user_id=owner_user_id,
    )


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


def _skill(diary: DiaryCapability, dynamics: Dynamics) -> DiaryWritingSkill:
    return DiaryWritingSkill(
        diary, dynamics, character_id="luotianyi", character_name="洛天依",
        character_persona="温柔的虚拟歌手", speaking_style="自然细腻",
    )


def test_diary_fact_generates_write_diary_plan_for_explicit_owner():
    diary = DiaryCapability()
    dynamics = Dynamics()
    handler = DiaryPlanningDueHandler(_skill(diary, dynamics))
    fact = _fact("user-2")
    sink = Sink()

    report = asyncio.run(handler.handle(
        _request(fact), PlanEmitter(character_id="luotianyi", request=_request(fact), sink=sink),
    ))

    action = sink.plans[0].actions[0]
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert isinstance(action, d.WriteDiary)
    assert action.owner_user_id == "user-2"
    assert action.local_date == date(2026, 9, 15)
    assert diary.calls[0]["user_id"] == "user-2"


def test_write_diary_publishes_private_non_commentable_dynamic_with_old_source_id():
    diary = DiaryCapability()
    dynamics = Dynamics()
    action = d.WriteDiary(
        action_id="action", owner_user_id="user-1", local_date=date(2026, 9, 15),
        body="今天聊了很多值得记住的事情。",
    )

    result = asyncio.run(WriteDiaryHandler(_skill(diary, dynamics)).realize(
        action,
        d.ExecutionContext(execution_id="e", interaction_id="wi",
                           current_interaction_revision=1, cancellation=d.CancellationToken()),
        None,
    ))

    assert result.effect_ref == d.EffectRef(
        kind=d.EffectKind.DYNAMIC_POST, effect_id="dynamic-1",
    )
    call = dynamics.calls[0]
    assert call["source_type"] == "diary"
    assert call["source_id"] == "diary:luotianyi:user-1:2026-09-15"
    assert call["visibility"] == "private"
    assert call["owner_user_id"] == "user-1"
    assert call["allow_comment"] is False
    assert call["idempotent_by_source"] is True


def test_diary_source_isolated_by_user_and_same_source_is_idempotent():
    diary = DiaryCapability()
    dynamics = Dynamics()
    handler = WriteDiaryHandler(_skill(diary, dynamics))
    context = d.ExecutionContext(
        execution_id="e", interaction_id="wi", current_interaction_revision=1,
        cancellation=d.CancellationToken(),
    )
    first = d.WriteDiary(action_id="a1", owner_user_id="user-1",
                         local_date=date(2026, 9, 15), body="第一位用户的日记")
    duplicate = d.WriteDiary(action_id="a2", owner_user_id="user-1",
                             local_date=date(2026, 9, 15), body="重复投递")
    other = d.WriteDiary(action_id="a3", owner_user_id="user-2",
                         local_date=date(2026, 9, 15), body="第二位用户的日记")

    results = [asyncio.run(handler.realize(action, context, None))
               for action in (first, duplicate, other)]

    assert [result.effect_ref.effect_id for result in results] == [
        "dynamic-1", "dynamic-1", "dynamic-2",
    ]
    assert len(dynamics.by_source) == 2


def test_empty_body_fails_handling_without_plan_or_created_claim():
    handler = DiaryPlanningDueHandler(_skill(DiaryCapability(body="  "), Dynamics()))
    fact = _fact()
    sink = Sink()

    report = asyncio.run(handler.handle(
        _request(fact), PlanEmitter(character_id="luotianyi", request=_request(fact), sink=sink),
    ))

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert report.emitted_plan_ids == ()
    assert report.consumed_pending_stimulus_ids == ()
    assert sink.plans == []


def test_publish_failure_returns_dependency_unavailable_without_effect():
    result = asyncio.run(WriteDiaryHandler(
        _skill(DiaryCapability(), Dynamics(publish_ok=False)),
    ).realize(
        d.WriteDiary(action_id="action", owner_user_id="user-1",
                     local_date=date(2026, 9, 15), body="日记"),
        d.ExecutionContext(execution_id="e", interaction_id="wi",
                           current_interaction_revision=1, cancellation=d.CancellationToken()),
        None,
    ))

    assert result.status is d.ActionExecutionStatus.FAILED
    assert result.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert result.irreversible_effect_committed is False
    assert result.effect_ref is None
