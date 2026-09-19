"""WorldStage 测试共享的领域对象和轻量 fake。"""
import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import src.domain.agent as d
from src.agent.context import RecalledMemoryContext
from src.stage import WorldStage


def world_observation(*, stimulus_id: str | None = None, revision: int = 1) -> d.WorldObservation:
    return d.WorldObservation(
        stimulus_id=stimulus_id or str(uuid4()), schema_version=1,
        occurred_at=datetime.now(timezone.utc), source=d.StimulusSource.WORLD,
        target_character_ids=("luotianyi",), user_id=None, ephemeral=False,
        observation_kind=d.WorldObservationKind(value="weather"),
        fact=d.WorldFact(fact_id=str(uuid4()), summary="晴朗"), evidence_refs=(),
        world_revision=revision,
    )


def activity_observation(*, activity_id: str = "walk", revision: int = 1) -> d.ActivityObservation:
    return d.ActivityObservation(
        stimulus_id=str(uuid4()), schema_version=1, occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.WORLD, target_character_ids=("luotianyi",), user_id=None,
        ephemeral=False, activity_id=activity_id,
        observation=d.ActivityFact(fact_id=str(uuid4()), summary="散步中"),
        activity_revision=revision,
    )


def handling_report(
    request: d.HandleStimulusRequest, *, plans: tuple[str, ...] = (),
    status: d.HandlingRequestStatus = d.HandlingRequestStatus.COMPLETED,
) -> d.HandlingReport:
    pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
    consumed = (request.stimulus.stimulus_id,) if status is d.HandlingRequestStatus.COMPLETED else ()
    return d.HandlingReport(
        request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=status, considered_pending_stimulus_ids=pending,
        consumed_pending_stimulus_ids=consumed,
        retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
        emitted_plan_ids=plans,
        error_code=(d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
                    if status is d.HandlingRequestStatus.FAILED else None),
        retryable=False,
    )


def action_plan(request: d.HandleStimulusRequest, ordinal: int = 0) -> d.ActionPlan:
    return d.ActionPlan(
        plan_id=str(uuid4()), origin_request_id=request.request_id, plan_ordinal=ordinal,
        target_character_id="luotianyi", interaction_id=request.interaction.interaction_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        source_stimulus_ids=(request.stimulus.stimulus_id,),
        actions=(d.Say(action_id=str(uuid4()), content="你好", sound_content=None,
                       prepared_audio_ref=None, tone=d.Tone(value="normal"), expression=None,
                       delivery=d.OutputDelivery.CONVERSATION),),
    )


class ContextFactory:
    def __init__(self) -> None:
        self.created = []

    async def create(self, interaction_id: str, *, user_id: str | None):
        context = SimpleNamespace(
            identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id,
                                     character_id="luotianyi"),
            recalled_memory=RecalledMemoryContext(), closed=False,
        )

        async def close() -> None:
            context.closed = True

        context.close = close
        self.created.append(context)
        return context


class RecordingAgent:
    def __init__(self) -> None:
        self.requests: asyncio.Queue[d.HandleStimulusRequest] = asyncio.Queue()
        self.executions = []
        self.handle_gate: asyncio.Event | None = None
        self.realize_gate: asyncio.Event | None = None
        self.active_realizations = 0
        self.max_active_realizations = 0

    async def handle_stimulus(self, request, sink, *, context=None):
        self.requests.put_nowait(request)
        if self.handle_gate is not None:
            await self.handle_gate.wait()
        return handling_report(request)

    async def realize_action_plan(self, plan, context, sink):
        self.executions.append((plan, context, sink))
        self.active_realizations += 1
        self.max_active_realizations = max(self.max_active_realizations, self.active_realizations)
        try:
            if self.realize_gate is not None:
                await self.realize_gate.wait()
            return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)
        finally:
            self.active_realizations -= 1


async def create_stage(
    agent: RecordingAgent | None = None, *, config=None,
    on_execution_finished: Callable[[d.ActionPlan, d.ExecutionReport], None] | None = None,
):
    factory = ContextFactory()
    actual_agent = agent or RecordingAgent()
    stage = await WorldStage.create(
        character_id="luotianyi", world_id="default", agent=actual_agent,
        context_factory=factory, config=config, on_execution_finished=on_execution_finished,
    )
    return stage, actual_agent, factory
