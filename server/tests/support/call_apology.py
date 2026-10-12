"""Shared call apology resources and handler fixtures."""

import json
import wave
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.context import ConversationSnapshot, UserContextSnapshot
from src.agent.context.memory_pool import CallMemoryPool
from src.agent.skills.contracts import ReplyDraft
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.domain.call import CallState, RecallMode


class _Conversation:
    def __init__(self):
        self.entries = []

    def read(self):
        return ConversationSnapshot(entries=tuple(self.entries))

    async def append(self, entries):
        self.entries.extend(entries)


class _Plans:
    def __init__(self):
        self.accepted_ids = []
        self.drafts = []
        self.context = SimpleNamespace(
            identity=SimpleNamespace(character_id="luotianyi", user_id="user", interaction_id="call"),
            user=SimpleNamespace(read=lambda: UserContextSnapshot()),
            conversation=_Conversation(),
            call_memory=CallMemoryPool(),
        )

    async def emit(self, draft):
        self.drafts.append(draft)
        self.accepted_ids.append(f"plan-{len(self.drafts)}")


def _request(stimulus):
    return d.HandleStimulusRequest(
        request_id="request",
        stimulus=stimulus,
        interaction=d.CallInteractionSnapshot(
            interaction_id="call",
            interaction_revision=1,
            user_id="user",
            pending_stimuli=(),
            now=datetime.now(timezone.utc),
            timezone=ZoneInfo("UTC"),
            supported_outputs=frozenset({d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.MESSAGE_END}),
            call_id=stimulus.call_id,
            state=CallState.ACTIVE,
            connection_state=d.ConnectionState.CONNECTED,
        ),
        cancellation=d.CancellationToken(),
    )


def _stimulus(cls, **kwargs):
    return cls(
        stimulus_id="stimulus",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.STAGE,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        **kwargs,
    )


def catalog(tmp_path, *, rate=24000, width=2, channels=1):
    with wave.open(str(tmp_path / "apology.wav"), "wb") as audio:
        audio.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0" * 960 * width * channels)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                dict(name=f"call_apology_{scene}_1", audio_path="apology.wav", text="sorry", expression="normal")
                for scene in ("opening", "turn", "silence")
            ]
        )
    )
    return PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})


class Recall:
    async def decide(self, *args, **kwargs):
        return SimpleNamespace(mode=RecallMode.DIRECT)


class Replies:
    def __init__(self, *, failing=False, texts=("answer",)):
        self.failing, self.texts = failing, texts

    async def generate(self, *args, **kwargs):
        if self.failing:
            raise RuntimeError("private reply should not be logged")
        return tuple(ReplyDraft(text, text, "normal", None) for text in self.texts)
