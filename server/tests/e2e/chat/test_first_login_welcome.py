"""首次登录从 Stage readiness 到最终欢迎包的公开链路。"""

import asyncio
import base64
import io
import json
import wave
from datetime import datetime
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.resources.prepared_speech import PreparedSpeechResources
from src.stage import StageManager
from src.system.user_interface.websocket_service import WebSocketConnection


class Socket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, event: dict) -> None:
        self.events.append(event)


class Conversation:
    def __init__(self) -> None:
        self.entries = []

    async def append(self, entries) -> None:
        self.entries.extend(entries)


class ContextFactory:
    def __init__(self) -> None:
        self.context = None

    async def create(self, interaction_id: str, *, user_id: str):
        conversation = Conversation()
        self.context = SimpleNamespace(
            identity=SimpleNamespace(
                interaction_id=interaction_id,
                user_id=user_id,
                character_id="luotianyi",
            ),
            conversation=conversation,
            recalled_memory=SimpleNamespace(remove_by_stimulus_id=lambda _: None),
            close=self._close,
        )
        return self.context

    async def _close(self) -> None:
        return None


def wav_bytes(seed: int) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes((seed, seed + 1)) * 120)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_first_login_waits_for_ready_then_emits_two_persistent_final_packages(tmp_path):
    # Given: login is recorded before a ChatStage exists and two manifest-backed welcomes are configured.
    first_audio = wav_bytes(1)
    second_audio = wav_bytes(3)
    (tmp_path / "one.wav").write_bytes(first_audio)
    (tmp_path / "two.wav").write_bytes(second_audio)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([
        {"name": "welcome_1", "audio_path": "one.wav", "text": "欢迎一", "expression": "smile"},
        {"name": "welcome_2", "audio_path": "two.wav", "text": "欢迎二", "expression": "happy"},
    ]), encoding="utf-8")
    resources = PreparedSpeechResources({"manifest": str(manifest)})
    handler = FirstLoginHandler(
        prepared_names=("welcome_1", "welcome_2"),
        prepared_speech=resources,
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter((
            (d.StimulusKind.PROACTIVE_PROMPT_DUE, handler),
            (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
        )),
        action_router=ActionRouter(((
            d.ActionKind.SAY,
            SayHandler("luotianyi", SimpleNamespace(), resources),
        ),)),
    )
    adapter = WebSocketAdapter()
    factory = ContextFactory()
    manager = StageManager(
        get_agent=lambda _: agent,
        adapter=adapter,
        get_context_factory=lambda _: factory,
        config={"stage": {"first_login_wait": 0.04}},
    )
    manager.record_login("user", "luotianyi", elapsed_from_last_login=None)
    manager.record_login("user", "luotianyi", elapsed_from_last_login=None)
    await asyncio.sleep(0.05)
    assert factory.context is None

    socket = Socket()
    connection = WebSocketConnection(socket, "user", "用户")
    started_at = asyncio.get_running_loop().time()

    # When: the real manager establishes and binds the ChatStage.
    await manager.connect(connection, "luotianyi")
    await asyncio.sleep(0.015)
    assert socket.events == []

    async def two_final_packages() -> None:
        while sum(
            event["payload"]["is_final_package"]
            for event in socket.events
            if event["type"] == "agent_message"
        ) < 2:
            await asyncio.sleep(0)

    await asyncio.wait_for(two_final_packages(), 1)

    # Then: delay starts after readiness, messages/plans retain order, and each package is persisted and final.
    assert asyncio.get_running_loop().time() - started_at >= 0.035
    packets = [event["payload"] for event in socket.events if event["type"] == "agent_message"]
    finals = [index for index, packet in enumerate(packets) if packet["is_final_package"]]
    assert len(finals) == 2
    first = packets[: finals[0] + 1]
    second = packets[finals[0] + 1 : finals[1] + 1]
    assert first[0]["text"] == "欢迎一"
    assert second[0]["text"] == "欢迎二"
    assert any(packet["expression"] == "normal" for packet in first)
    assert any(packet["expression"] == "normal" for packet in second)
    assert b"".join(base64.b64decode(packet["audio"]) for packet in first) == first_audio
    assert b"".join(base64.b64decode(packet["audio"]) for packet in second) == second_audio
    assert factory.context is not None
    entries = factory.context.conversation.entries
    assert [entry.source for entry in entries] == ["agent", "agent"]
    assert [entry.content.text for entry in entries] == ["欢迎一", "欢迎二"]
    assert all(isinstance(entry.timestamp, datetime) and entry.timestamp.tzinfo is None for entry in entries)

    await manager.close()


@pytest.mark.asyncio
async def test_return_login_remains_disabled_after_stage_connection():
    # Given: a long-absence login is recorded and a real Stage is connected.
    requests = []

    class RecordingAgent:
        def is_handle_interruptible(self, interaction_id, request_id=None):
            return True

        def is_realize_interruptible(self, interaction_id):
            return False

        async def handle_stimulus(self, request, sink, *, context=None):
            requests.append(request)
            return d.HandlingReport(
                request_id=request.request_id,
                trigger_stimulus_id=request.stimulus.stimulus_id,
                basis_interaction_revision=request.interaction.interaction_revision,
                request_status=d.HandlingRequestStatus.COMPLETED,
                considered_pending_stimulus_ids=(),
                consumed_pending_stimulus_ids=(),
                retained_pending_stimulus_ids=(),
                emitted_plan_ids=(),
                retryable=False,
                error_code=None,
            )

        async def realize_action_plan(self, plan, context, sink):
            pytest.fail("long-absence login must not realize a welcome")

    adapter = WebSocketAdapter()
    factory = ContextFactory()
    manager = StageManager(
        get_agent=lambda _: RecordingAgent(),
        adapter=adapter,
        get_context_factory=lambda _: factory,
        config={"stage": {"first_login_wait": 0.02}},
    )
    manager.record_login("user", "luotianyi", elapsed_from_last_login=5 * 24 * 60 * 60)

    # When: the Stage becomes ready and more than the welcome delay elapses.
    await manager.connect(WebSocketConnection(Socket(), "user", "用户"), "luotianyi")
    await asyncio.sleep(0.04)

    # Then: no proactive stimulus is dispatched; RETURN_LOGIN stays disabled.
    assert requests == []
    await manager.close()
