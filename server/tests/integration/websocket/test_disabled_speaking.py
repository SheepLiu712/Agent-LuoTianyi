"""真实 Agent/SAY 到公开聊天 Adapter 的文字包与终态；不冒充完整 HTTP/WS 启动验收。"""

import asyncio
import json
import wave
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.expression.speaking import SpeakingSkill


class ChatEndpoint:
    interaction_id = "interaction"
    user_id = "user"
    character_id = "luotianyi"
    connection_generation = 0

    async def start(self):
        pass

    async def connection_changed(self, available, generation):
        self.connection_generation = generation
        return True


class OutputSink:
    def __init__(self, adapter):
        self.adapter = adapter

    async def emit(self, value):
        await self.adapter.output_sink.submit_output(value)
        return d.OutputReceipt(
            execution_id=value.execution_id,
            sequence_no=value.sequence_no,
            status=d.OutputAcceptanceStatus.ACCEPTED,
        )


def prepared_catalog(tmp_path):
    audio_path = tmp_path / "prepared.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 24)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps([{"name": "greet", "audio_path": audio_path.name, "text": "欢迎", "expression": "happy"}]),
        encoding="utf-8",
    )
    return PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})


async def connected_adapter():
    stage = ChatEndpoint()

    async def get_stage(**kwargs):
        return stage

    async def disconnect(connection):
        return None

    adapter = WebSocketAdapter()
    adapter.initialize(SimpleNamespace(try_to_get_stage=get_stage, disconnect=disconnect))
    connection = await adapter.open(user_id="user", connection_id=object())
    ready = await adapter.next_output(connection)
    assert json.loads(ready.message)["type"] == "chat.ready"
    adapter.complete_output(connection, ready.delivery_id)
    return adapter, connection


def execution_inputs(*, text, index, prepared=False, ephemeral=False, call=False, text_only=False):
    plan = d.ActionPlan(
        plan_id=f"plan-{index}",
        origin_request_id=f"request-{index}",
        plan_ordinal=0,
        target_character_id="luotianyi",
        interaction_id="interaction",
        basis_interaction_revision=1,
        source_stimulus_ids=(f"stimulus-{index}",),
        actions=(
            d.Say(
                action_id=f"say-{index}",
                content=text,
                sound_content=None if prepared or text_only else text,
                prepared_audio_ref=d.MediaRef(media_id="greet") if prepared else None,
                tone=d.Tone(value="normal"),
                expression=d.ChangeExpression(expression_id="happy"),
                delivery=d.OutputDelivery.EPHEMERAL_REACTION if ephemeral else d.OutputDelivery.CONVERSATION,
                message_id=f"message-{index}",
                call_delivery=(
                    d.CallSpeechDelivery(
                        audio_route=d.CallAudioRoute.CALL,
                        display_in_chat=False,
                        is_ephemeral=True,
                        response_id=f"response-{index}",
                    )
                    if call
                    else d.CallSpeechDelivery()
                ),
            ),
        ),
    )
    context = d.ExecutionContext(
        execution_id=f"execution-{index}",
        interaction_id="interaction",
        current_interaction_revision=1,
        cancellation=d.CancellationToken(),
        call_output_permit=SimpleNamespace(allows=lambda response_id: True) if call else None,
    )
    return plan, context


async def realize_and_receive(agent, adapter, connection, **inputs):
    plan, context = execution_inputs(**inputs)
    execution = asyncio.create_task(agent.realize_action_plan(plan, context, OutputSink(adapter)))
    packets = []
    try:
        while True:
            delivery = await asyncio.wait_for(adapter.next_output(connection), 2)
            event = json.loads(delivery.message)
            adapter.complete_output(connection, delivery.delivery_id)
            assert event["type"] == "agent_message"
            packet = event["payload"]
            packets.append(packet)
            if packet["is_final_package"]:
                break
        report = await asyncio.wait_for(execution, 2)
        return report, packets
    finally:
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("text_only", [False, True])
async def test_disabled_say_delivers_two_text_messages_with_successful_terminal(tmp_path, text_only):
    speech = SpeakingSkill({"enabled": False})
    agent = Agent(
        character_id="luotianyi",
        action_router=ActionRouter(((d.ActionKind.SAY, SayHandler("luotianyi", speech, prepared_catalog(tmp_path))),)),
    )
    adapter, connection = await connected_adapter()
    try:
        for index, text in enumerate(("你好，412", "第二条")):
            report, packets = await realize_and_receive(
                agent, adapter, connection, text=text, index=index, text_only=text_only
            )
            assert report.status is d.ExecutionStatus.COMPLETED
            assert [packet["text"] for packet in packets if packet["text"]] == [text]
            assert all(packet["audio"] == "" for packet in packets)
            assert sum(packet["is_final_package"] for packet in packets) == 1
            assert packets[-1]["audio_error"] is False
            assert packets[-1]["error_code"] is None
            assert {packet["uuid"] for packet in packets} == {f"message-{index}"}
            assert [packet["packet_sequence"] for packet in packets] == list(range(len(packets)))
    finally:
        await adapter.close()
        await speech.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("ephemeral,text", [(False, "欢迎，412"), (True, "")])
async def test_disabled_prepared_say_never_reads_audio_and_finishes(tmp_path, monkeypatch, ephemeral, text):
    speech = SpeakingSkill({"enabled": False})
    catalog = prepared_catalog(tmp_path)

    async def forbidden_read(*args, **kwargs):
        pytest.fail("disabled SAY must not read prepared audio")

    monkeypatch.setattr(catalog, "read_audio", forbidden_read)
    monkeypatch.setattr(catalog, "read_call_pcm", forbidden_read)
    agent = Agent(
        character_id="luotianyi",
        action_router=ActionRouter(((d.ActionKind.SAY, SayHandler("luotianyi", speech, catalog)),)),
    )
    adapter, connection = await connected_adapter()
    try:
        report, packets = await realize_and_receive(
            agent, adapter, connection, text=text, index=0, prepared=True, ephemeral=ephemeral
        )
        assert report.status is d.ExecutionStatus.COMPLETED
        assert [packet["text"] for packet in packets if packet["text"]] == ([] if ephemeral else [text])
        assert all(packet["audio"] == "" for packet in packets)
        assert all(packet["display_in_chat"] is not ephemeral for packet in packets)
        assert all(packet["is_ephemeral"] is ephemeral for packet in packets)
        assert [packet["expression"] for packet in packets if packet["expression"]] == ["happy"]
        assert sum(packet["is_final_package"] for packet in packets) == 1
        assert packets[-1]["audio_error"] is False
    finally:
        await adapter.close()
        await speech.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared", [False, True])
async def test_disabled_call_say_is_rejected_without_a_text_only_fallback(tmp_path, prepared):
    speech = SpeakingSkill({"enabled": False})
    agent = Agent(
        character_id="luotianyi",
        action_router=ActionRouter(((d.ActionKind.SAY, SayHandler("luotianyi", speech, prepared_catalog(tmp_path))),)),
    )
    values = []

    async def reject_output(output):
        values.append(output)
        raise AssertionError("disabled CALL must not output text, prepared audio or a success end")

    plan, context = execution_inputs(text="通话不能回退文字", index=0, prepared=prepared, ephemeral=True, call=True)
    try:
        report = await agent.realize_action_plan(plan, context, SimpleNamespace(emit=reject_output))

        assert report.status is d.ExecutionStatus.FAILED
        assert report.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        assert values == []
    finally:
        await speech.stop()


@pytest.mark.asyncio
async def test_disabled_text_say_preserves_sink_failures_instead_of_success(tmp_path):
    speech = SpeakingSkill({"enabled": False})
    agent = Agent(
        character_id="luotianyi",
        action_router=ActionRouter(((d.ActionKind.SAY, SayHandler("luotianyi", speech, prepared_catalog(tmp_path))),)),
    )
    attempted = []

    async def fail_delivery(output):
        attempted.append(output)
        raise RuntimeError("connection failed")

    plan, context = execution_inputs(text="不会伪报送达", index=0)
    try:
        report = await agent.realize_action_plan(plan, context, SimpleNamespace(emit=fail_delivery))

        assert report.status is d.ExecutionStatus.FAILED
        assert [output.kind for output in attempted] == [d.AgentOutputKind.TEXT_FINAL]
        assert not any(isinstance(output, d.MessageEndOutput) for output in attempted)
    finally:
        await speech.stop()
