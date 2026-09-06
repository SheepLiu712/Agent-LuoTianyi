"""处理器路由公开契约使用的离线装配和领域样例。"""
import importlib
from types import SimpleNamespace

import pytest_asyncio

from src.agent import Agent
from src.agent_runtime import agent_runtime as runtime_module
import src.domain.agent as d
from test_facade_contract import request, plan_and_context  # noqa: F401


def router_type(side):
    module = importlib.import_module(f"src.agent.handlers.{side}.router")
    return getattr(module, "StimulusRouter" if side == "stimulus" else "ActionRouter")


@pytest_asyncio.fixture
async def routed_runtime(monkeypatch, runtime_dependencies):
    instances = []

    def build(handle=None, realize=None, action_kinds=(d.ActionKind.SAY, d.ActionKind.SING)):
        def assemble(*, character_id, **kwargs):
            kwargs["stimulus_router"] = router_type("stimulus")(
                [(d.StimulusKind.TEXT_MESSAGE, SimpleNamespace(handle=handle))] if handle else [],
            )
            kwargs["action_router"] = router_type("action")(
                [(kind, SimpleNamespace(realize=realize)) for kind in action_kinds] if realize else [],
            )
            return Agent(character_id=character_id, **kwargs)

        monkeypatch.setattr(runtime_module, "Agent", assemble)
        kwargs, store = runtime_dependencies
        runtime = runtime_module.AgentRuntime(**kwargs)
        instances.append(runtime)
        return runtime, store

    yield build
    for runtime in instances:
        runtime.shutdown_timeout_seconds = 1
        await runtime.shutdown()


def settlement(req, *, emitted=(), consumed=("m2",), **changes):
    values = dict(
        request_id=req.request_id, trigger_stimulus_id=req.stimulus.stimulus_id,
        basis_interaction_revision=req.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=("m2", "m1"), consumed_pending_stimulus_ids=consumed,
        retained_pending_stimulus_ids=tuple(i for i in ("m2", "m1") if i not in consumed),
        emitted_plan_ids=emitted, reconsider_at=None, error_code=None, retryable=False,
    )
    values.update(changes)
    return d.HandlingReport(**values)


def completed(action, **changes):
    values = dict(action_id=action.action_id, status=d.ActionExecutionStatus.COMPLETED,
                  error_code=None, irreversible_effect_committed=False, effect_ref=None)
    values.update(changes)
    return d.ActionResult(**values)


def full_output(action_id="a2", **changes):
    values = dict(interaction_id="i", execution_id="e", action_id=action_id, sequence_no=0,
                  delivery=d.OutputDelivery.CONVERSATION, text="输出")
    values.update(changes)
    return d.TextFinalOutput(**values)


class Sink:
    def __init__(self, callback=None):
        self.values = []
        self.callback = callback

    async def emit(self, value):
        if self.callback:
            return await self.callback(value)
        self.values.append(value)
        if isinstance(value, d.ActionPlan):
            return d.PlanReceipt(plan_id=value.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)
        return d.OutputReceipt(execution_id=value.execution_id, sequence_no=value.sequence_no,
                               status=d.OutputAcceptanceStatus.ACCEPTED)


def output():
    """只提供内容，由 Agent 分配身份和序号。"""
    from src.agent.outputs.drafts import TextFinalDraft
    return TextFinalDraft(delivery=d.OutputDelivery.CONVERSATION, text="输出")
