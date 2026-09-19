"""世界事实结算端口：路由生命周期、订阅隔离与 WorldStage 装配。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from world_stage_fakes import (
    ContextFactory,
    action_plan,
    handling_report,
    world_observation,
)

import src.domain.agent as d
from src.stage import WorldStage
from src.world.world_settlements import (
    FactHandlingOutcome,
    FactPlanOutcome,
    WorldSettlementRouter,
)


class Subscriber:
    def __init__(self, *, fail=False):
        self.handled = []
        self.executed = []
        self.fail = fail

    def on_fact_handled(self, outcome):
        if self.fail:
            raise RuntimeError("subscriber boom")
        self.handled.append(outcome)

    def on_fact_plan_executed(self, outcome):
        if self.fail:
            raise RuntimeError("subscriber boom")
        self.executed.append(outcome)


def world_request(fact, *, request_id="req", interaction_id="wi", revision=1):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    snapshot = d.WorldInteractionSnapshot(
        interaction_id=interaction_id, interaction_revision=revision, user_id=None,
        pending_stimuli=(fact,), now=now, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(),
        world_id="default", world_revision=0, activity_id=None, activity_revision=None,
        planning_cycle_id=None, schedule_revision=0,
    )
    return d.HandleStimulusRequest(
        request_id=request_id, stimulus=fact, interaction=snapshot, cancellation=d.CancellationToken(),
    )


def execution_report(plan, *, with_effect=True):
    return d.ExecutionReport(
        execution_id="exec", plan_id=plan.plan_id, status=d.ExecutionStatus.COMPLETED,
        action_results=(d.ActionResult(
            action_id=plan.actions[0].action_id, status=d.ActionExecutionStatus.COMPLETED,
            error_code=None, irreversible_effect_committed=with_effect,
            effect_ref=(d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="dyn-1")
                        if with_effect else None),
        ),),
        output_started=False, error_code=None, retryable=False,
    )


def test_handling_without_plans_notifies_and_forgets_registration():
    router = WorldSettlementRouter()
    subscriber = Subscriber()
    fact = world_observation()
    request = world_request(fact)
    router.register(fact.stimulus_id, subscriber)

    router.on_handling_settled(request, handling_report(request))

    assert subscriber.handled == [FactHandlingOutcome(
        stimulus_id=fact.stimulus_id, request_status=d.HandlingRequestStatus.COMPLETED,
        consumed=True, error_code=None, plan_ids=(),
    )]
    assert subscriber.handled[0].ignored is True
    assert subscriber.executed == []
    assert router.awaiting_settlement == ()
    assert router.unmatched_settlements == 0


def test_failed_handling_is_reported_without_consumption():
    router = WorldSettlementRouter()
    subscriber = Subscriber()
    fact = world_observation()
    request = world_request(fact)
    router.register(fact.stimulus_id, subscriber)

    router.on_handling_settled(request, handling_report(
        request, status=d.HandlingRequestStatus.FAILED,
    ))

    outcome = subscriber.handled[0]
    assert outcome.consumed is False
    assert outcome.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert outcome.ignored is False
    assert router.awaiting_settlement == ()


def test_execution_settlement_follows_handling_and_forgets_after_last_plan():
    router = WorldSettlementRouter()
    subscriber = Subscriber()
    fact = world_observation()
    request = world_request(fact)
    first, second = action_plan(request, ordinal=0), action_plan(request, ordinal=1)
    router.register(fact.stimulus_id, subscriber)

    router.on_handling_settled(request, handling_report(
        request, plans=(first.plan_id, second.plan_id),
    ))
    assert router.awaiting_settlement == (fact.stimulus_id,)
    assert subscriber.handled[0].plan_ids == (first.plan_id, second.plan_id)

    router.on_execution_finished(first, execution_report(first))
    assert router.awaiting_settlement == (fact.stimulus_id,)

    router.on_execution_finished(second, execution_report(second, with_effect=False))
    assert router.awaiting_settlement == ()
    assert [item.stimulus_id for item in subscriber.executed] == [fact.stimulus_id, fact.stimulus_id]
    assert subscriber.executed[0].effect_refs == (
        d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="dyn-1"),
    )
    assert subscriber.executed[1].effect_refs == ()


def test_unmatched_settlements_are_counted_without_raising():
    router = WorldSettlementRouter()
    fact = world_observation()
    request = world_request(fact)

    router.on_handling_settled(request, handling_report(request))
    router.on_execution_finished(action_plan(request, ordinal=0), execution_report(action_plan(request, ordinal=0)))

    assert router.unmatched_settlements == 2
    assert router.awaiting_settlement == ()


def test_subscriber_failure_is_isolated_and_registration_still_settles():
    router = WorldSettlementRouter()
    fact = world_observation()
    request = world_request(fact)
    router.register(fact.stimulus_id, Subscriber(fail=True))

    router.on_handling_settled(request, handling_report(request))

    assert router.subscriber_failures == 1
    assert router.awaiting_settlement == ()


def test_registration_rejects_blank_and_duplicate_ids_and_discard_is_idempotent():
    router = WorldSettlementRouter()
    fact = world_observation()
    subscriber = Subscriber()

    for blank in ("", "   "):
        try:
            router.register(blank, subscriber)
        except ValueError:
            pass
        else:
            raise AssertionError("空刺激 ID 不应被登记")

    router.register(fact.stimulus_id, subscriber)
    try:
        router.register(fact.stimulus_id, Subscriber())
    except ValueError:
        pass
    else:
        raise AssertionError("重复登记应被拒绝")

    router.discard(fact.stimulus_id)
    router.discard(fact.stimulus_id)
    assert router.awaiting_settlement == ()


class NoPlanAgent:
    async def handle_stimulus(self, request, sink, *, context=None):
        return handling_report(request)

    async def realize_action_plan(self, plan, context, sink):
        raise AssertionError("无计划的处理不应触发执行")


class PlanAgent:
    async def handle_stimulus(self, request, sink, *, context=None):
        plan = action_plan(request, ordinal=0)
        await sink.emit(plan)
        return handling_report(request, plans=(plan.plan_id,))

    async def realize_action_plan(self, plan, context, sink):
        return execution_report(plan)


async def build_stage(agent, router):
    return await WorldStage.create(
        character_id="luotianyi", world_id="default", agent=agent,
        context_factory=ContextFactory(),
        on_handling_settled=router.on_handling_settled,
        on_execution_finished=router.on_execution_finished,
    )


async def test_stage_reports_handling_settlement_to_subscriber():
    router = WorldSettlementRouter()
    subscriber = Subscriber()
    fact = world_observation()
    stage = await build_stage(NoPlanAgent(), router)
    try:
        router.register(fact.stimulus_id, subscriber)
        assert await stage.fact_sink.submit(fact) is True
        await stage.wait_idle()
    finally:
        await stage.close()

    assert [item.stimulus_id for item in subscriber.handled] == [fact.stimulus_id]
    assert subscriber.handled[0].consumed is True
    assert subscriber.handled[0].plan_ids == ()
    assert subscriber.executed == []
    assert router.awaiting_settlement == ()
    assert router.unmatched_settlements == 0


async def test_stage_reports_plan_execution_with_committed_effects():
    router = WorldSettlementRouter()
    subscriber = Subscriber()
    fact = world_observation()
    stage = await build_stage(PlanAgent(), router)
    try:
        router.register(fact.stimulus_id, subscriber)
        assert await stage.fact_sink.submit(fact) is True
        await stage.wait_idle()
    finally:
        await stage.close()

    assert len(subscriber.handled) == 1
    assert subscriber.handled[0].plan_ids == (subscriber.executed[0].plan.plan_id,)
    assert [item.stimulus_id for item in subscriber.executed] == [fact.stimulus_id]
    assert subscriber.executed[0].effect_refs[0].effect_id == "dyn-1"
    assert isinstance(subscriber.executed[0], FactPlanOutcome)
    assert router.awaiting_settlement == ()
