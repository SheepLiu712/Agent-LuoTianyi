from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.context import RecalledMemoryContext
from src.agent.handlers.action.cognitive_maintenance import CognitiveMaintenanceActionHandler


class Skill:
    def __init__(self):
        self.threshold = []
        self.ending = []

    async def maintain(self, invocation, *, request):
        if request.reason is d.MaintenanceReason.COMPACTION_THRESHOLD:
            self.threshold.append((invocation, request.context))
        else:
            self.ending.append((invocation, request.context, request.reason))
        return SimpleNamespace(status=d.MaintenanceStatus.COMPLETED)


def context():
    return SimpleNamespace(
        identity=SimpleNamespace(user_id="u"),
        conversation=SimpleNamespace(read=lambda: SimpleNamespace(entries=())),
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


@pytest.mark.asyncio
async def test_conflicted_batch_is_not_reported_as_completed_action():
    class Conflicted:
        async def maintain(self, invocation, *, request):
            return SimpleNamespace(status=d.MaintenanceStatus.CONFLICT)

    with pytest.raises(RuntimeError, match="COGNITIVE_MAINTENANCE_CONFLICT"):
        await CognitiveMaintenanceActionHandler("luotianyi", Conflicted()).realize(
            action(d.MaintenanceReason.INTERACTION_ENDING), execution_context(context()), None
        )


@pytest.mark.asyncio
async def test_background_maintenance_preserves_new_reply_recall():
    from src.agent.context import RecallEntry, JargonExplanation

    ctx = context()
    old = RecallEntry("old", "old-input", JargonExplanation("old", "old"))
    new = RecallEntry("new", "new-input", JargonExplanation("new", "new"))
    ctx.recalled_memory.append((old,))

    class ConcurrentSkill:
        async def maintain(self, *args, **kwargs):
            ctx.recalled_memory.append((new,))
            return SimpleNamespace(status=d.MaintenanceStatus.COMPLETED)

    await CognitiveMaintenanceActionHandler("luotianyi", ConcurrentSkill()).realize(
        action(d.MaintenanceReason.COMPACTION_THRESHOLD), execution_context(ctx), None
    )
    assert ctx.recalled_memory.read() == (new,)
