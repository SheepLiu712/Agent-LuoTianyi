"""citywalk 完成事实的 Agent 侧表达与 PUBLISH_DYNAMIC 行动。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.handlers.action.dynamic import PublishDynamicHandler
from src.agent.handlers.stimulus.citywalk import CitywalkObservationHandler
from src.agent.handlers.stimulus.world_activity import WorldActivityHandler
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill

BODY = "今天在武康路散步，风很舒服。"


class FakeDynamics:
    def __init__(self, *, body=BODY, publish_ok=True, publish_id="dynamic-citywalk"):
        self.body = body
        self.publish_ok = publish_ok
        self.publish_id = publish_id
        self.published = []
        self.composed = []

    async def generate_world_dynamic_content(self, **kwargs):
        self.composed.append(kwargs)
        return self.body

    def publish_agent_dynamic(self, **kwargs):
        self.published.append(kwargs)
        if not self.publish_ok:
            return False, "duplicate", None
        return True, "created", {"id": self.publish_id}


class Sink:
    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


def observation(summary="今天在武康路散步，风很舒服。", kind="citywalk_completed"):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    return d.WorldObservation(
        stimulus_id="wo1", schema_version=1, occurred_at=now, source=d.StimulusSource.WORLD,
        target_character_ids=("luotianyi",), user_id=None, ephemeral=False,
        observation_kind=d.WorldObservationKind(value=kind),
        fact=d.WorldFact(fact_id="citywalk:data/citywalk_reports/today.json", summary=summary),
        evidence_refs=(), world_revision=1,
    )


def request_for(fact):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    snapshot = d.WorldInteractionSnapshot(
        interaction_id="wi", interaction_revision=1, user_id=None, pending_stimuli=(fact,),
        now=now, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(), world_id="default",
        world_revision=fact.world_revision, activity_id=None, activity_revision=None,
        planning_cycle_id=None, schedule_revision=0,
    )
    return d.HandleStimulusRequest(
        request_id="req", stimulus=fact, interaction=snapshot, cancellation=d.CancellationToken(),
    )


def emitter(request, sink):
    return PlanEmitter(character_id="luotianyi", request=request, sink=sink)


def skill(dynamics):
    return DynamicPublishingSkill(dynamics)


async def test_citywalk_branch_emits_publish_dynamic_plan():
    dynamics = FakeDynamics()
    handler = CitywalkObservationHandler(skill(dynamics))
    fact = observation()
    request = request_for(fact)
    sink = Sink()

    report = await handler.handle(request, emitter(request, sink))

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.consumed_pending_stimulus_ids == ("wo1",)
    assert report.retained_pending_stimulus_ids == ()
    assert report.emitted_plan_ids == (sink.plans[0].plan_id,)
    assert dynamics.composed[0]["dynamic_type"] == "citywalk"
    assert dynamics.composed[0]["structured_context"] == fact.fact.summary
    action = sink.plans[0].actions[0]
    assert isinstance(action, d.PublishDynamic)
    assert action.body == BODY
    assert action.visibility is d.Visibility.GLOBAL
    assert action.owner_user_id is None
    assert action.allow_comment is True
    assert action.source == d.DynamicSource(
        source_type="citywalk", source_id="citywalk:data/citywalk_reports/today.json",
    )
    assert action.media_refs == ()


async def test_citywalk_branch_fails_without_plan_when_body_is_empty():
    handler = CitywalkObservationHandler(skill(FakeDynamics(body="  ")))
    fact = observation()
    request = request_for(fact)
    sink = Sink()

    report = await handler.handle(request, emitter(request, sink))

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert report.consumed_pending_stimulus_ids == ()
    assert report.emitted_plan_ids == ()
    assert sink.plans == []


async def test_world_activity_handler_dispatches_registered_branch_only():
    dynamics = FakeDynamics()
    handler = WorldActivityHandler(branches={
        "citywalk_completed": CitywalkObservationHandler(skill(dynamics)),
    })
    known = observation()
    unknown = observation(kind="weather")
    known_request, unknown_request = request_for(known), request_for(unknown)

    known_report = await handler.handle(known_request, emitter(known_request, Sink()))
    unknown_report = await handler.handle(unknown_request, emitter(unknown_request, Sink()))

    assert known_report.emitted_plan_ids != ()
    assert unknown_report.emitted_plan_ids == ()
    assert unknown_report.consumed_pending_stimulus_ids == ("wo1",)
    assert unknown_report.error_code is None
    assert len(dynamics.composed) == 1


async def test_publish_dynamic_handler_reports_committed_effect():
    dynamics = FakeDynamics()
    handler = PublishDynamicHandler("luotianyi", skill(dynamics))
    action = d.PublishDynamic(
        action_id="a1", body=BODY, media_refs=(), visibility=d.Visibility.GLOBAL,
        owner_user_id=None, source=d.DynamicSource(source_type="citywalk", source_id="s"), allow_comment=True,
    )
    context = d.ExecutionContext(
        execution_id="e", interaction_id="i", current_interaction_revision=1,
        cancellation=d.CancellationToken(),
    )

    result = await handler.realize(action, context, None)

    assert result.status is d.ActionExecutionStatus.COMPLETED
    assert result.irreversible_effect_committed is True
    assert result.effect_ref == d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="dynamic-citywalk")
    assert dynamics.published[0]["source_type"] == "citywalk"
    assert dynamics.published[0]["idempotent_by_source"] is True
    assert dynamics.published[0]["visibility"] == "global"


async def test_publish_dynamic_handler_reports_failure_without_effect():
    dynamics = FakeDynamics(publish_ok=False)
    handler = PublishDynamicHandler("luotianyi", skill(dynamics))
    action = d.PublishDynamic(
        action_id="a1", body=BODY, media_refs=(), visibility=d.Visibility.GLOBAL,
        owner_user_id=None, source=d.DynamicSource(source_type="citywalk", source_id="s"), allow_comment=True,
    )
    context = d.ExecutionContext(
        execution_id="e", interaction_id="i", current_interaction_revision=1,
        cancellation=d.CancellationToken(),
    )

    result = await handler.realize(action, context, None)

    assert result.status is d.ActionExecutionStatus.FAILED
    assert result.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert result.effect_ref is None
    assert result.irreversible_effect_committed is False


async def test_publish_dynamic_handler_honours_cancellation():
    dynamics = FakeDynamics()
    handler = PublishDynamicHandler("luotianyi", skill(dynamics))
    action = d.PublishDynamic(
        action_id="a1", body=BODY, media_refs=(), visibility=d.Visibility.GLOBAL,
        owner_user_id=None, source=d.DynamicSource(source_type="citywalk", source_id="s"), allow_comment=True,
    )
    cancellation = d.CancellationToken()
    cancellation.cancel(d.CancellationReason.SUPERSEDED)
    context = d.ExecutionContext(
        execution_id="e", interaction_id="i", current_interaction_revision=1, cancellation=cancellation,
    )

    result = await handler.realize(action, context, None)

    assert result.status is d.ActionExecutionStatus.CANCELLED
    assert dynamics.published == []
