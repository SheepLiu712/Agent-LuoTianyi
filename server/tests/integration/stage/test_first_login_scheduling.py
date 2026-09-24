"""首次登录事实的角色作用域与 handle 容量编排。"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.stage import StageManager
from src.web.websocket.service import WebSocketConnection


class Socket:
    async def send_json(self, event: dict) -> None:
        return None


class ContextFactory:
    def __init__(self, character_id: str) -> None:
        self._character_id = character_id

    async def create(self, interaction_id: str, *, user_id: str):
        return SimpleNamespace(
            identity=SimpleNamespace(
                interaction_id=interaction_id,
                user_id=user_id,
                character_id=self._character_id,
            ),
            recalled_memory=SimpleNamespace(remove_by_stimulus_id=lambda _: None),
            close=self._close,
        )

    async def _close(self) -> None:
        return None


def completed_report(request: d.HandleStimulusRequest) -> d.HandlingReport:
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


class RecordingAgent:
    def __init__(self, character_id: str, typing_gate: asyncio.Event | None = None) -> None:
        self.character_id = character_id
        self.typing_gate = typing_gate
        self.first_logins: list[d.ProactivePromptDue] = []

    async def handle_stimulus(self, request, sink, *, context=None):
        if isinstance(request.stimulus, d.UserTyping) and self.typing_gate is not None:
            await self.typing_gate.wait()
        if isinstance(request.stimulus, d.ProactivePromptDue):
            self.first_logins.append(request.stimulus)
        return completed_report(request)

    async def realize_action_plan(self, plan, context, sink):
        pytest.fail("scheduling tests do not emit plans")


async def wait_for_count(values: list, count: int) -> None:
    while len(values) < count:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_one_login_dispatches_once_to_each_character():
    # Given: one user's first login is recorded for two enabled characters, including duplicate notifications.
    agents = {
        character_id: RecordingAgent(character_id)
        for character_id in ("luotianyi", "miku")
    }
    manager = StageManager(
        get_agent=agents.__getitem__,
        adapter=WebSocketAdapter(),
        get_context_factory=ContextFactory,
        config={"stage": {"first_login_wait": 0.01}},
    )
    for character_id in agents:
        manager.record_login("user", character_id, elapsed_from_last_login=None)
        manager.record_login("user", character_id, elapsed_from_last_login=None)

    # When: both character stages become ready for the same login.
    connection = WebSocketConnection(Socket(), "user", "用户")
    for character_id in agents:
        await manager.connect(connection, character_id)
    await asyncio.wait_for(
        asyncio.gather(*(wait_for_count(agent.first_logins, 1) for agent in agents.values())),
        1,
    )
    for character_id in agents:
        await manager.connect(connection, character_id)
    await asyncio.sleep(0.02)

    # Then: each character receives one character-scoped fact and reconnect does not replay it.
    for character_id, agent in agents.items():
        assert len(agent.first_logins) == 1
        assert agent.first_logins[0].target_character_ids == (character_id,)
        assert agent.first_logins[0].dedup_key == f"first-login:user:{character_id}"
    await manager.close()


@pytest.mark.asyncio
async def test_first_login_waits_for_handle_capacity_then_dispatches():
    # Given: a ready Stage has its only handle slot occupied when first-login becomes due.
    typing_gate = asyncio.Event()
    agent = RecordingAgent("luotianyi", typing_gate)
    manager = StageManager(
        get_agent=lambda _: agent,
        adapter=WebSocketAdapter(),
        get_context_factory=ContextFactory,
        config={"stage": {"first_login_wait": 0.03, "max_stimuli": 1}},
    )
    manager.record_login("user", "luotianyi", elapsed_from_last_login=None)
    stage = await manager.connect(
        WebSocketConnection(Socket(), "user", "用户"),
        "luotianyi",
    )
    typing = d.UserTyping(
        stimulus_id="typing",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        text_length=1,
    )
    assert stage.stimulus_input_sink.submit(typing)
    await asyncio.sleep(0.035)

    # When: capacity becomes available after the original due time.
    assert agent.first_logins == []
    assert stage._first_login_pending
    typing_gate.set()
    await asyncio.wait_for(wait_for_count(agent.first_logins, 1), 1)

    # Then: the pending fact is dispatched once without exceeding the handle bound.
    assert len(agent.first_logins) == 1
    assert len(stage._handles) <= 1
    await manager.close()
