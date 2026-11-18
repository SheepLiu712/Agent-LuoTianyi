"""实时通话前锁定聊天 Reflection 与 TTS 流式取消的现状。"""

import threading
from contextlib import aclosing
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from support.skill_support import invocation

import src.domain.agent as d
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.skills.expression.speaking import SpeakingSkill
from src.agent.skills.expression.speaking.errors import TTSStreamCancelled
from src.agent.skills.expression.speaking.streaming import AsyncTTS


class _StreamModule:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.closed = threading.Event()

    def stream_synthesize_speech_with_tone(self, text, tone, *, cancel_event):
        self.started.set()
        try:
            yield b"complete-first-chunk"
            assert cancel_event.wait(5)
            raise TTSStreamCancelled()
        finally:
            self.closed.set()


@pytest.mark.asyncio
async def test_tts_cancellation_keeps_completed_chunk_but_drops_unfinished_tail():
    module = _StreamModule()
    skill = SpeakingSkill({}, AsyncTTS(SimpleNamespace(tts_module={"luotianyi": module})))
    cancellation = d.CancellationToken()

    speech = skill.speak(invocation(cancellation=cancellation), text="文字", tone=d.Tone(value="normal"))
    async with aclosing(speech) as stream:
        assert (await anext(stream)).data == b"complete-first-chunk"
        cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        with pytest.raises(TTSStreamCancelled):
            await anext(stream)
    assert module.closed.is_set()


@pytest.mark.asyncio
async def test_interaction_ending_emits_only_ending_maintenance_plan():
    handler = InteractionEndingHandler()
    ending = d.InteractionEnding(
        stimulus_id="ending",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.STAGE,
        target_character_ids=("luotianyi",),
        user_id="u",
        ephemeral=True,
        reason=d.InteractionEndingReason.USER_LEFT,
    )
    request = d.HandleStimulusRequest(
        request_id="ending-request",
        stimulus=ending,
        interaction=d.ChatInteractionSnapshot(
            interaction_id="interaction",
            interaction_revision=0,
            user_id="u",
            pending_stimuli=(),
            now=datetime.now(timezone.utc),
            timezone=ZoneInfo("UTC"),
            supported_outputs=frozenset(),
            response_deadline=None,
            connection_state=d.ConnectionState.CONNECTED,
        ),
        cancellation=d.CancellationToken(),
    )
    emitted = []

    async def accept(draft):
        emitted.append(draft)
        return d.PlanReceipt(plan_id="draft", status=d.PlanAcceptanceStatus.ACCEPTED)

    class Plans:
        accepted_ids = ["ending-plan"]

        async def emit(self, draft):
            return await accept(draft)

    sink = Plans()

    report = await handler.handle(request, sink)

    assert report.emitted_plan_ids == ("ending-plan",)
    assert len(emitted) == 1
    assert isinstance(emitted[0].actions[0], d.CognitiveMaintenance)
    assert emitted[0].actions[0].reason is d.MaintenanceReason.INTERACTION_ENDING
