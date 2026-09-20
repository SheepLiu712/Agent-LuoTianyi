"""生产 WebSocket 入口与 adapter、Stage 的完整聊天生命周期。"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.agent.context import RecalledMemoryContext
from src.stage import StageManager
from src.web.websocket import WSMessage
from src.web.websocket.service import (
    WebSocketConnection,
    WebSocketService,
)


class Socket:
    def __init__(self, client_msg_id: str) -> None:
        self.client_msg_id = client_msg_id
        self.events: list[dict] = []
        self.output_finished = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def send_json(self, event: dict) -> None:
        self.events.append(event)
        if sum(item.get("type") == "agent_message" for item in self.events) >= 2:
            self.output_finished.set()


class ContextFactory:
    async def create(self, interaction_id: str, *, user_id: str):
        async def close() -> None:
            return None

        return SimpleNamespace(
            identity=SimpleNamespace(
                interaction_id=interaction_id,
                user_id=user_id,
                character_id="luotianyi",
            ),
            recalled_memory=RecalledMemoryContext(),
            close=close,
        )


def completed_report(
    request: d.HandleStimulusRequest,
    *,
    consumed: tuple[str, ...] = (),
    emitted: tuple[str, ...] = (),
) -> d.HandlingReport:
    pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
    preprocessed = None
    if isinstance(request.stimulus, d.TextMessage):
        preprocessed = d.PreprocessedInput(
            stimulus_id=request.stimulus.stimulus_id,
            text=request.stimulus.text,
        )
    return d.HandlingReport(
        request_id=request.request_id,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=pending,
        consumed_pending_stimulus_ids=consumed,
        retained_pending_stimulus_ids=tuple(stimulus_id for stimulus_id in pending if stimulus_id not in consumed),
        preprocessed_input=preprocessed,
        emitted_plan_ids=emitted,
        error_code=None,
        retryable=False,
    )


class ReplyingAgent:
    def __init__(self) -> None:
        self.text_interaction_ids: list[str] = []

    def is_handle_interruptible(self, interaction_id: str, request_id: str | None = None) -> bool:
        return True

    def is_realize_interruptible(self, interaction_id: str) -> bool:
        return False

    async def handle_stimulus(self, request, plans, *, context=None):
        if isinstance(request.stimulus, d.TextMessage):
            self.text_interaction_ids.append(request.interaction.interaction_id)
            return completed_report(request)
        if isinstance(request.stimulus, d.InteractionDeadline):
            action = d.Say(
                action_id=f"say-{request.request_id}",
                content="收到",
                sound_content=None,
                prepared_audio_ref=None,
                tone=d.Tone(value="normal"),
                expression=None,
                delivery=d.OutputDelivery.CONVERSATION,
            )
            accepted = await plans.emit(
                d.ActionPlan(
                    plan_id=f"plan-{request.request_id}",
                    origin_request_id=request.request_id,
                    plan_ordinal=0,
                    target_character_id="luotianyi",
                    interaction_id=request.interaction.interaction_id,
                    basis_interaction_revision=request.interaction.interaction_revision,
                    source_stimulus_ids=(request.stimulus.stimulus_id,),
                    actions=(action,),
                )
            )
            consumed = tuple(stimulus.stimulus_id for stimulus in request.interaction.pending_stimuli)
            return completed_report(request, consumed=consumed, emitted=(accepted.plan_id,))
        return completed_report(request)

    async def realize_action_plan(self, plan, context, output_sink):
        action = plan.actions[0]
        await output_sink.emit(
            d.TextFinalOutput(
                interaction_id=context.interaction_id,
                execution_id=context.execution_id,
                action_id=action.action_id,
                sequence_no=0,
                delivery=d.OutputDelivery.CONVERSATION,
                text="收到",
            )
        )
        await output_sink.emit(
            d.MessageEndOutput(
                interaction_id=context.interaction_id,
                execution_id=context.execution_id,
                action_id=action.action_id,
                sequence_no=1,
                delivery=d.OutputDelivery.CONVERSATION,
                status=d.MessageEndStatus.COMPLETED,
                error_code=None,
            )
        )
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)


@pytest.mark.asyncio
async def test_production_chat_reconnect_reuses_stage_after_stimulus_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the production route owns a real shared adapter and Stage manager.
    from src.web.websocket import endpoint

    agent = ReplyingAgent()
    adapter = WebSocketAdapter()
    stage_manager = StageManager(
        get_agent=lambda _: agent,
        adapter=adapter,
        get_context_factory=lambda _: ContextFactory(),
        config={"offline_timeout": 10, "stage": {"response_wait": 0.01}},
    )
    service = WebSocketService()
    runtime = SimpleNamespace(
        websocket_service=service,
        database_manager=object(),
        stage_manager=stage_manager,
        chat_adapter=adapter,
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        client_llm_executor=SimpleNamespace(clear_user=lambda *_: None),
    )
    monkeypatch.setattr(
        endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime)),
    )

    async def authenticate(connection, _service, _database) -> bool:
        connection.set_user("user", "用户")
        return True

    received: set[str] = set()

    async def receive(connection: WebSocketConnection) -> WSMessage:
        socket = connection.websocket
        if socket.client_msg_id not in received:
            received.add(socket.client_msg_id)
            return WSMessage(
                event_type="user_text",
                client_msg_id=socket.client_msg_id,
                payload={"text": "你好"},
            )
        await asyncio.wait_for(socket.output_finished.wait(), 2)
        await asyncio.sleep(0)
        raise WebSocketDisconnect

    monkeypatch.setattr(WebSocketConnection, "auth", authenticate)
    monkeypatch.setattr(service, "try_recv_client_msg", receive)

    # When: one authenticated connection chats, disconnects, then reconnects and chats again.
    first = Socket("first")
    second = Socket("second")
    await endpoint.chat_ws(first)
    await endpoint.chat_ws(second)

    # Then: both receive Agent output and both stimuli use the retained Stage interaction.
    for socket in (first, second):
        packets = [event["payload"] for event in socket.events if event.get("type") == "agent_message"]
        assert any(packet["text"] == "收到" for packet in packets)
        assert any(packet["is_final_package"] for packet in packets)
    assert len(agent.text_interaction_ids) == 2
    assert agent.text_interaction_ids[0] == agent.text_interaction_ids[1]
    await stage_manager.close()
