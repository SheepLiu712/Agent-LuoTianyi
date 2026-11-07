"""实时模型通话测试的共享装配，仅替换供应商和付费端口。"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest
from support.aliyun_realtime_speech import FakeAliyunConnector, FakeAliyunWebSocket
from support.call_output import output_sink
from support.stage_lifecycle import observe_release
import src.domain.agent as d
from src.agent.context import ContextFactory
from src.agent.facade import Agent
from src.agent.processing.omni_background import CallSessionPrompt
from src.agent.handlers.action.call_settlement import FinalizeCallHandler
from src.agent.skills.cognitive.call_settlement import CallSummaryResult, CallSummaryStatus
from types import SimpleNamespace
from src.agent.handlers.action.call_memory import LookupCallMemoryHandler
from src.agent.handlers.stimulus.call import (
    CallAnswerRequestedHandler,
    CallEndingHandler,
    CallMemoryLookupRequestedHandler,
    CallReplyConfirmedHandler,
    CallReplySegmentReadyHandler,
    CallTimeLimitWarningHandler,
    CallTurnCompletedHandler,
)
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.output_drafts import TextFinalDraft, AudioChunkDraft, MessageEndDraft
from src.agent.skills.contracts import CharacterNarrative
from src.agent.skills.memory_retrieval import MemorySearchResult
from src.domain.call import CallState
from src.infrastructure.models.realtime_speech.config import AliyunRealtimeSpeechConfig
from src.infrastructure.models.realtime_speech.omni import QwenOmniSessionFactory
from src.infrastructure.persistence.call_sessions import BEIJING_TIMEZONE, CallSessionRecord, SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base
from src.stage.call.call_stage import CallStage, CallStageOwnership, CallIngressReceipt


class _ContextDatabase:
    def get_user_description(self, _user_id):
        return ""

    def get_user_preferences(self, _user_id):
        return {}

    def get_call_conversation_seed_state(self, _user_id, *, character_id, requested_at):
        assert character_id == "luotianyi"
        assert requested_at.tzinfo is None
        return {"summary": "", "conversations": []}


class _Clock:
    def __init__(self):
        self.wall = datetime(2026, 10, 11, 12, 0, tzinfo=BEIJING_TIMEZONE)
        self.monotonic = 100.0

    def now(self):
        self.wall += timedelta(milliseconds=1)
        return self.wall

    def tick(self):
        return self.monotonic

    def advance(self, seconds):
        self.monotonic += seconds


class _Transport:
    def __init__(self):
        self.items = []

    async def send_state(self, item):
        self.items.append(item)

    async def send_ended(self, snapshot):
        self.items.append(("ended", snapshot))

    async def send_failed(self, reason):
        self.items.append(("failed", reason))

    async def start_stream(self, response_id, stream_id, audio_format):
        self.items.append(("start", response_id, stream_id, audio_format))

    async def send_pcm(self, response_id, stream_id, payload, *, final):
        self.items.append(("pcm", response_id, stream_id, payload, final))

    async def stop_response(self, response_id, stream_ids):
        self.items.append(("stop", response_id, stream_ids))


class _NoOutputActionHandler:
    async def realize(self, action, execution_context, outputs):
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


class _SayHandler:
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
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )


async def _eventually(predicate, timeout=1.0):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


def _receipt(call_id, seq, payload):
    return CallIngressReceipt(
        call_id=str(call_id),
        direction="client_to_server",
        seq=seq,
        fingerprint=hashlib.sha256(b"audio\0" + payload).digest(),
    )


@pytest.fixture
def call_setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.db'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    clock = _Clock()
    call_id = uuid4()
    record = CallSessionRecord(
        call_id=call_id,
        client_request_id="request-1",
        user_id="user",
        character_id="luotianyi",
        state=CallState.PREPARING,
        requested_at=clock.now(),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    repository.create_if_absent(record)
    ownership = CallStageOwnership(
        call_id=str(call_id),
        user_id="user",
        character_id="luotianyi",
        client_request_id="request-1",
        setup_deadline=110.0,
        generation=1,
    )
    return repository, record, ownership, clock


def factory(*sockets):
    return QwenOmniSessionFactory(
        AliyunRealtimeSpeechConfig(
            api_key="offline",
            model="qwen3.5-omni-plus-realtime",
            endpoint="wss://example.test/api-ws/v1/realtime",
        ),
        connector=FakeAliyunConnector(*sockets),
    )


async def send_reply(socket, response_id="r1", text="第一句。第二句。", item_id="u1", done=True):
    if item_id:
        await socket.server_event({"type": "input_audio_buffer.speech_started", "item_id": item_id})
        await socket.server_event({"type": "input_audio_buffer.speech_stopped", "item_id": item_id})
    await socket.server_event({"type": "response.created", "response": {"id": response_id}})
    await socket.server_event({"type": "response.text.delta", "response_id": response_id, "delta": text})
    if done:
        await socket.server_event({"type": "response.done", "response": {"id": response_id, "status": "completed"}})


class Retrieval:
    def __init__(self, hits=(), *, block=False):
        self.hits = hits
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.invocation = None
        if not block:
            self.gate.set()

    async def search(self, invocation, *, query):
        self.invocation = invocation
        self.started.set()
        await self.gate.wait()
        return MemorySearchResult(self.hits)


async def create_stage(setup, *, retrieval=None, config=None, accept=True):
    repository, record, ownership, clock = setup
    socket = FakeAliyunWebSocket()
    omni = factory(socket)
    retrieval = retrieval or Retrieval()

    class Maintenance:
        async def maintain(self, invocation, *, request):
            return SimpleNamespace(status=d.MaintenanceStatus.COMPLETED)

    class Summary:
        def __init__(self):
            self.materials = []

        async def generate(self, invocation, *, material):
            self.materials.append(material)
            return CallSummaryResult(CallSummaryStatus.GENERATED, "本次通话总结")

    summary = Summary()
    agent = Agent(
        character_id="luotianyi",
        omni_factory=omni,
        narrative=CharacterNarrative(name="洛天依", persona="虚拟歌手", speaking_style="自然"),
        omni_prompt=CallSessionPrompt("res/agent/prompts/realtime_call_prompt.json"),
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.CALL_ANSWER_REQUESTED, CallAnswerRequestedHandler(accept=accept)),
                (d.StimulusKind.CALL_TURN_COMPLETED, CallTurnCompletedHandler()),
                (d.StimulusKind.CALL_REPLY_CONFIRMED, CallReplyConfirmedHandler()),
                (
                    d.StimulusKind.CALL_REPLY_SEGMENT_READY,
                    CallReplySegmentReadyHandler(
                        SimpleNamespace(expression_for_tone=lambda character_id, tone: (None, "normal"))
                    ),
                ),
                (d.StimulusKind.CALL_MEMORY_LOOKUP_REQUESTED, CallMemoryLookupRequestedHandler()),
                (d.StimulusKind.CALL_TIME_LIMIT_WARNING, CallTimeLimitWarningHandler()),
                (d.StimulusKind.CALL_ENDING, CallEndingHandler()),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.FINALIZE_CALL, FinalizeCallHandler("luotianyi", Maintenance(), summary)),
                (d.ActionKind.ANSWER_CALL, _NoOutputActionHandler()),
                (d.ActionKind.SAY, _SayHandler()),
                (d.ActionKind.LOOKUP_CALL_MEMORY, LookupCallMemoryHandler(retrieval)),
            )
        ),
    )
    transport = _Transport()
    stage = CallStage(
        ownership=ownership,
        record=record,
        agent=agent,
        context_factory=ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=repository,
        speech_factory=omni,
        output_sink=output_sink(transport),
        own_termination=observe_release(None, ownership),
        monotonic=clock.tick,
        wall_clock=clock.now,
        config=config,
    )
    stage._test_summary = summary
    await stage.start()
    await _eventually(lambda: stage.state is CallState.ACTIVE if accept else stage.snapshot is not None)
    if accept:
        await _eventually(lambda: any(e["type"] == "response.create" for e in socket.sent))
        # Acknowledge the once-only opening response before injecting user turns.
        await send_reply(socket, response_id="opening", text="你好。", item_id=None)
        await _eventually(lambda: any(item[0] == "pcm" for item in transport.items if isinstance(item, tuple)))
        start = next(item for item in transport.items if isinstance(item, tuple) and item[0] == "start")
        stage.playback_completed(start[1], start[2])
        await stage._drain_facts()
    return stage, socket, transport, retrieval
