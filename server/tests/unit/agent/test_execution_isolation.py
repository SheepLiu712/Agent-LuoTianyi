"""不同执行和角色的单次行动处理互相隔离。"""
from dataclasses import replace

import pytest

import src.domain.agent as d
from routing_support import Sink, completed, output, plan_and_context

pytestmark = pytest.mark.asyncio


def fresh(context, **changes):
    return replace(context, cancellation=d.CancellationToken(), **changes)


async def deliver(action, context, outputs):
    await outputs.emit(output())
    return completed(action, irreversible_effect_committed=True,
                     effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id=action.action_id))


async def test_execution_and_character_keys_are_independent(routed_runtime):
    runtime, _ = routed_runtime(realize=deliver)
    plan, context = plan_and_context()
    await runtime.get_agent().realize_action_plan(plan, context, Sink())
    for agent, candidate, current in (
        (runtime.get_agent(), plan, fresh(context, execution_id="other")),
        (runtime.get_agent("miku"), replace(plan, target_character_id="miku"), fresh(context)),
    ):
        sink = Sink()
        report = await agent.realize_action_plan(candidate, current, sink)
        assert report.status is d.ExecutionStatus.COMPLETED and len(sink.values) == 2
