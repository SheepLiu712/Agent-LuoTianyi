"""Controllable external ports for CallStage transport-failure integration tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.domain.agent as d
from src.agent.context import ContextFactory
from src.agent.facade import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.output_drafts import AudioChunkDraft, MessageEndDraft, TextFinalDraft
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.domain.call import CallAnswerDecision, CallSpeechDelivery, CallState
from src.infrastructure.persistence.call_sessions import BEIJING_TIMEZONE, CallSessionRecord, SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage.call_stage import CallStage
from src.stage.stage_manager import CallStageOwnership
from support.realtime_speech import FakeRealtimeSpeechSessionFactory


class ContextDatabase:
    def get_user_description(self, _user_id):
        return ""

    def get_user_preferences(self, _user_id):
        return {}

    def get_call_conversation_seed_state(self, _user_id, *, character_id, requested_at):
        return {"summary": "", "conversations": []}


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 10, 11, 12, 0, tzinfo=BEIJING_TIMEZONE)
        self.monotonic = 100.0

    def now(self):
        self.wall += timedelta(milliseconds=1)
        return self.wall

    def tick(self):
        return self.monotonic


class FailingTransport:
    def __init__(self):
        self.fail: set[str] = set()
        self.events: list[tuple] = []

    async def send_state(self, item):
        if "state_active" in self.fail and item.state is CallState.ACTIVE:
            raise RuntimeError("state_active failed")
        self.events.append(("state", item.state))

    async def send_ended(self, snapshot):
        self.events.append(("ended", snapshot))

    async def send_failed(self, reason):
        self.events.append(("failed", reason))

    async def start_stream(self, response_id, stream_id, audio_format):
        if "start_stream" in self.fail:
            raise RuntimeError("start_stream failed")
        self.events.append(("start", response_id, stream_id))

    async def send_pcm(self, response_id, stream_id, payload, *, final):
        if "send_pcm" in self.fail:
            raise RuntimeError("send_pcm failed")
        self.events.append(("pcm", response_id, stream_id, final))

    async def stop_response(self, response_id, stream_ids):
        if "stop_response" in self.fail:
            raise RuntimeError("stop_response failed")
        self.events.append(("stop", response_id, tuple(stream_ids)))

    def count(self, event: str) -> int:
        return sum(item[0] == event for item in self.events)


class Settlement:
    def __init__(self):
        self.snapshots = []

    async def emit(self, snapshot):
        self.snapshots.append(snapshot)


class TurnHandler:
    def __init__(self, *, response_count: int = 1):
        self.response_count = response_count

    async def handle(self, request, plans):
        actions = tuple(
            d.Say(
                action_id=f"{request.request_id}-say-{index}",
                content="正式回答",
                sound_content=None,
                prepared_audio_ref=None,
                tone=d.Tone(value="normal"),
                expression=None,
                delivery=d.OutputDelivery.EPHEMERAL_REACTION,
                call_delivery=CallSpeechDelivery(
                    audio_route=d.CallAudioRoute.CALL,
                    display_in_chat=False,
                    is_ephemeral=True,
                    response_id=f"response-{request.stimulus.turn_seq}-{index}",
                ),
            )
            for index in range(self.response_count)
        )
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(request.stimulus.stimulus_id,), actions=actions))
        return report(request, plans)


class NoPlanHandler:
    async def handle(self, request, plans):
        return report(request, plans)


class NoOutputActionHandler:
    async def realize(self, action, execution_context, outputs):
        return action_result(action)


class SayHandler:
    async def realize(self, action, execution_context, outputs):
        await outputs.emit(TextFinalDraft(delivery=action.delivery, text=action.content))
        await outputs.emit(
            AudioChunkDraft(
                delivery=action.delivery,
                data=b"\x00\x00",
                framing=d.AudioFraming.RAW_PCM,
                audio_format=d.CALL_PCM_FORMAT,
                final=True,
            )
        )
        await outputs.emit(
            MessageEndDraft(delivery=action.delivery, status=d.MessageEndStatus.COMPLETED, error_code=None)
        )
        return action_result(action)


def report(request, plans):
    return d.HandlingReport(
        request_id=request.request_id,
        request_status=d.HandlingRequestStatus.COMPLETED,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        considered_pending_stimulus_ids=(),
        consumed_pending_stimulus_ids=(),
        retained_pending_stimulus_ids=(),
        emitted_plan_ids=tuple(plans.accepted_ids),
        error_code=None,
        retryable=False,
    )


def action_result(action):
    return d.ActionResult(
        action_id=action.action_id,
        status=d.ActionExecutionStatus.COMPLETED,
        error_code=None,
        irreversible_effect_committed=False,
        effect_ref=None,
    )


def build_agent(*, response_count: int = 1) -> Agent:
    no_plan = NoPlanHandler()
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.CALL_ANSWER_REQUESTED, no_plan),
                (d.StimulusKind.CALL_STARTED, no_plan),
                (d.StimulusKind.CALL_TURN_COMPLETED, TurnHandler(response_count=response_count)),
                (d.StimulusKind.CALL_SILENCE_ELAPSED, no_plan),
                (d.StimulusKind.CALL_ENDING, no_plan),
            )
        ),
        action_router=ActionRouter(
            ((d.ActionKind.ANSWER_CALL, NoOutputActionHandler()), (d.ActionKind.SAY, SayHandler()))
        ),
    )


async def create_active_stage(tmp_path, *, response_count: int = 1):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.db'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    clock = Clock()
    call_id = uuid4()
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id=f"request-{call_id}",
        user_id="user",
        character_id="luotianyi",
        state=CallState.PREPARING,
        requested_at=clock.now(),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    repository.create_if_absent(record)
    ownership = CallStageOwnership(str(call_id), "user", "luotianyi", record.client_request_id, 110.0, 1)
    provider_factory = FakeRealtimeSpeechSessionFactory()
    transport = FailingTransport()
    settlement = Settlement()
    released = []
    stage = await CallStage.create(
        ownership=ownership,
        record=record,
        agent=build_agent(response_count=response_count),
        context_factory=ContextFactory(character_id="luotianyi", database=ContextDatabase()),
        call_sessions=repository,
        speech_factory=provider_factory,
        transport=transport,
        release_ownership=lambda value: not released.append(value),
        settlement_sink=settlement,
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    return stage, repository, record, ownership, provider_factory.sessions[call_id], transport, settlement, released


async def activate(stage: CallStage, call_id) -> None:
    await stage.apply_answer(d.AnswerCall(action_id="answer", call_id=call_id, decision=CallAnswerDecision.ACCEPT))


async def eventually(predicate, timeout: float = 2.0) -> None:
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)
