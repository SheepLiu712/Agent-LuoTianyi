"""真实触摸 handler 经 ChatStage 按计划顺序投递瞬时输出。"""

import asyncio
import json
import wave

import pytest
from stage_support import cleanup, setup, stimulus

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.action.restore_expression import RestoreExpressionHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.handlers.stimulus.touch import TouchInteractionHandler
from src.agent.skills.expression.touch import TouchReactionSkill
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 2)


@pytest.mark.asyncio
async def test_touch_audio_end_precedes_restore_and_never_becomes_chat_record(tmp_path):
    audio = tmp_path / "touch.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 10)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "touch_voice",
                    "audio_path": "touch.wav",
                    "text": "",
                    "expression": "happy",
                }
            ]
        ),
        encoding="utf-8",
    )
    prepared = PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})
    touch = TouchInteractionHandler(
        TouchReactionSkill(
            {
                "luotianyi": {
                    "resource_names": ["touch_voice"],
                    "probability": 1.0,
                }
            },
            prepared,
        )
    )
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [
                (d.StimulusKind.TOUCH_INTERACTION, touch),
                (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
            ]
        ),
        action_router=ActionRouter(
            [
                (d.ActionKind.SAY, SayHandler("luotianyi", None, prepared)),
                (d.ActionKind.RESTORE_EXPRESSION, RestoreExpressionHandler()),
            ]
        ),
    )
    stage, _, adapter, _, socket = await setup(agent)
    try:
        accepted = stage.stimulus_input_sink.submit(
            stimulus(
                d.TouchInteraction,
                body_regions=(d.BodyRegion(value="head"),),
                click_frequency=None,
                ephemeral=True,
            )
        )
        assert accepted is True
        await until(lambda: len(socket.events) >= 5)
        packets = [event["payload"] for event in socket.events if event["type"] == "agent_message"]
        assert [packet["expression"] for packet in packets if packet["expression"]] == ["happy", "normal"]
        end_indices = [index for index, packet in enumerate(packets) if packet["is_final_package"]]
        restore_index = next(index for index, packet in enumerate(packets) if packet["expression"] == "normal")
        assert len(end_indices) == 2
        assert end_indices[0] < restore_index < end_indices[1]
        assert all(packet["text"] == "" for packet in packets)
        assert all(packet["is_ephemeral"] is True for packet in packets)
        assert all(packet["display_in_chat"] is False for packet in packets)
        assert stage._pending == {}
        await asyncio.sleep(0)
        assert packets[restore_index]["expression"] == "normal"
        assert packets[-1]["is_final_package"] is True
    finally:
        await cleanup(stage, adapter)
