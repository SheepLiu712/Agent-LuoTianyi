from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.context import RecalledMemoryContext
from src.agent.handlers.action.cognitive_maintenance import CognitiveMaintenanceActionHandler


class Skill:
    def __init__(self):
        self.threshold = []
        self.ending = []

    async def maintain_if_compaction_needed(self, invocation, context):
        self.threshold.append((invocation, context))

    async def maintain(self, invocation, context, *, reason):
        self.ending.append((invocation, context, reason))


def context():
    return SimpleNamespace(
        identity=SimpleNamespace(user_id="u"),
        conversation=SimpleNamespace(),
        user=SimpleNamespace(),
        recalled_memory=RecalledMemoryContext(),
    )


def action(reason):
    return d.CognitiveMaintenance(action_id="maintenance", reason=reason)


def execution_context(interaction_context):
    return d.ExecutionContext(
        execution_id="execution",
        interaction_id="interaction",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
        interaction_context=interaction_context,
    )


@pytest.mark.asyncio
async def test_action_routes_threshold_and_clears_recalled_memory():
    skill, ctx = Skill(), context()
    result = await CognitiveMaintenanceActionHandler("luotianyi", skill).realize(
        action(d.MaintenanceReason.COMPACTION_THRESHOLD),
        execution_context(interaction_context=ctx),
        None,
    )
    assert result.status is d.ActionExecutionStatus.COMPLETED
    assert len(skill.threshold) == 1
    assert skill.ending == []
    assert ctx.recalled_memory.read() == ()


@pytest.mark.asyncio
async def test_action_routes_interaction_ending():
    skill, ctx = Skill(), context()
    result = await CognitiveMaintenanceActionHandler("luotianyi", skill).realize(
        action(d.MaintenanceReason.INTERACTION_ENDING),
        execution_context(interaction_context=ctx),
        None,
    )
    assert result.status is d.ActionExecutionStatus.COMPLETED
    assert skill.ending[0][2] is d.MaintenanceReason.INTERACTION_ENDING


@pytest.mark.asyncio
async def test_missing_context_returns_dependency_failure_without_output():
    result = await CognitiveMaintenanceActionHandler("luotianyi", Skill()).realize(
        action(d.MaintenanceReason.INTERACTION_ENDING),
        execution_context(interaction_context=None),
        None,
    )
    assert result.status is d.ActionExecutionStatus.FAILED
    assert result.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
