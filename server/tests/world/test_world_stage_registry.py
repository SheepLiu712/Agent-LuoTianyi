"""SystemRuntime 对长期 WorldStage 的显式作用域装配。"""
from types import SimpleNamespace

import pytest

from src.stage import WorldStage
from src.system.system_runtime import DEFAULT_WORLD_ID, SystemRuntime


class ContextFactory:
    async def create(self, interaction_id: str, *, user_id: str | None):
        context = SimpleNamespace(
            identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id,
                                     character_id="luotianyi"),
            closed=False,
        )

        async def close() -> None:
            context.closed = True

        context.close = close
        return context


class Agent:
    async def handle_stimulus(self, request, sink, *, context=None):
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        from src.domain.agent import HandlingReport, HandlingRequestStatus
        return HandlingReport(
            request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=(request.stimulus.stimulus_id,),
            retained_pending_stimulus_ids=tuple(
                item for item in pending if item != request.stimulus.stimulus_id
            ), emitted_plan_ids=(), error_code=None, retryable=False,
        )

    async def realize_action_plan(self, plan, context, sink):
        raise AssertionError("no plans expected")


def runtime() -> SystemRuntime:
    agent = Agent()
    return SystemRuntime(
        user_interface=SimpleNamespace(), world=SimpleNamespace(),
        database_manager=SimpleNamespace(),
        agent_runtime=SimpleNamespace(
            default_character_id="luotianyi", get_agent=lambda character_id=None: agent,
            context_factories={"luotianyi": ContextFactory()},
        ), capability_manager=SimpleNamespace(),
        llm_service=SimpleNamespace(), client_llm_executor=SimpleNamespace(),
        observability=SimpleNamespace(), owns_observability=False,
    )


@pytest.mark.asyncio
async def test_registry_reuses_same_scope_and_isolates_different_worlds():
    system = runtime()

    default = await system.get_world_stage("luotianyi")
    same = await system.get_world_stage("luotianyi", DEFAULT_WORLD_ID)
    other = await system.get_world_stage("luotianyi", "mirror")

    assert isinstance(default, WorldStage)
    assert same is default and other is not default
    assert system.get_agent("luotianyi") is system.agent_runtime.get_agent("luotianyi")
    await system.close_world_stages()
    assert default.state.value == "terminated" and other.state.value == "terminated"
