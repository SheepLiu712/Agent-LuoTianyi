"""触摸刺激生成两个独立计划，失败时直接丢弃。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from routing_support import Sink

import src.domain.agent as d
from src.agent.handlers.action.restore_expression import RestoreExpressionHandler
from src.agent.handlers.stimulus.touch import TouchInteractionHandler
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.expression.touch import TouchReaction, TouchReactionSkill
from src.agent_runtime.agent_runtime import AgentRuntime


def touch_request() -> d.HandleStimulusRequest:
    stimulus = d.TouchInteraction(
        stimulus_id="touch",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        body_regions=(d.BodyRegion(value="head"),),
        click_frequency=None,
    )
    interaction = d.ChatInteractionSnapshot(
        interaction_id="interaction",
        interaction_revision=3,
        user_id="user",
        pending_stimuli=(),
        now=datetime.now(timezone.utc),
        timezone=ZoneInfo("UTC"),
        supported_outputs=frozenset({
            d.AgentOutputKind.AUDIO_CHUNK,
            d.AgentOutputKind.MESSAGE_END,
            d.AgentOutputKind.EXPRESSION,
        }),
        response_deadline=None,
        connection_state=d.ConnectionState.CONNECTED,
    )
    return d.HandleStimulusRequest(
        request_id="request",
        stimulus=stimulus,
        interaction=interaction,
        cancellation=d.CancellationToken(),
    )


@dataclass(frozen=True, slots=True)
class ReactionSkill:
    reaction: TouchReaction | None

    def choose(self) -> TouchReaction | None:
        return self.reaction


@pytest.mark.asyncio
async def test_touch_handler_emits_ephemeral_say_then_independent_restore_plan():
    request = touch_request()
    sink = Sink()
    plans = PlanEmitter("luotianyi", request, sink)
    handler = TouchInteractionHandler(ReactionSkill(TouchReaction(
        audio_ref=d.MediaRef(media_id="touch_voice"),
        expression_id="happy",
    )))

    report = await handler.handle(request, plans)

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.considered_pending_stimulus_ids == ()
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == ()
    assert report.emitted_plan_ids == tuple(plans.accepted_ids)
    assert len(sink.values) == 2
    say = sink.values[0]
    restore = sink.values[1]
    assert say.plan_ordinal == 0 and restore.plan_ordinal == 1
    assert say.source_stimulus_ids == ("touch",)
    assert restore.source_stimulus_ids == ("touch",)
    assert say.actions == (d.Say(
        action_id=say.actions[0].action_id,
        content="",
        sound_content=None,
        prepared_audio_ref=d.MediaRef(media_id="touch_voice"),
        tone=d.Tone(value="normal"),
        expression=d.ChangeExpression(expression_id="happy"),
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
    ),)
    assert restore.actions == (d.RestoreExpression(
        action_id=restore.actions[0].action_id,
        expression_id="normal",
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
    ),)


@pytest.mark.asyncio
async def test_touch_handler_failure_logs_and_discards_without_plan(caplog):
    from src.utils.logger import get_logger

    request = touch_request()
    sink = Sink()
    plans = PlanEmitter("luotianyi", request, sink)
    handler = TouchInteractionHandler(ReactionSkill(None))
    logger = get_logger("src.agent.handlers.stimulus.touch")
    logger.addHandler(caplog.handler)
    try:
        report = await handler.handle(request, plans)
    finally:
        logger.removeHandler(caplog.handler)

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert report.retryable is False
    assert report.emitted_plan_ids == ()
    assert sink.values == []
    assert any("Touch reaction unavailable" in record.getMessage() for record in caplog.records)


def test_touch_skill_wraps_legacy_builder_selection_and_expression(tmp_path, monkeypatch):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    (tmp_path / "voice_to_expression.json").write_text(
        '{"voice": "happy"}',
        encoding="utf-8",
    )
    skill = TouchReactionSkill({"touch_voice_dir": str(tmp_path), "probability": 1.0})
    monkeypatch.setattr("src.agent.reflex.touch.random.choice", lambda files: next(iter(files)))

    reaction = skill.choose()

    assert reaction == TouchReaction(
        audio_ref=d.MediaRef(media_id="voice"),
        expression_id="happy",
    )


@pytest.mark.parametrize("mode", ["miss", "missing", "unreadable"])
def test_touch_skill_returns_none_when_fast_resource_cannot_be_used(tmp_path, monkeypatch, mode):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    skill = TouchReactionSkill({"touch_voice_dir": str(tmp_path), "probability": 1.0})
    if mode == "miss":
        monkeypatch.setattr(skill._builder, "should_use_fast_path", lambda: False)
    elif mode == "missing":
        audio.unlink()
    else:
        monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError("failed")))

    assert skill.choose() is None


@pytest.mark.asyncio
async def test_production_runtime_registers_touch_and_restore_without_chat_duplicate(
    runtime_dependencies,
    tmp_path,
):
    import json
    import wave

    kwargs, _ = runtime_dependencies
    audio = tmp_path / "touch.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 10)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{
        "name": "touch_voice",
        "audio_path": "touch.wav",
        "text": "",
        "expression": "happy",
    }]), encoding="utf-8")
    kwargs["config"]["prepared_speech"] = {"manifest": str(manifest)}
    kwargs["config"]["character_registry"]["characters"]["luotianyi"]["reflex"] = {
        "touch": {"fast_reply": {
            "manifest": str(manifest),
            "resource_names": ["touch_voice"],
            "probability": 1.0,
        }},
    }
    runtime = AgentRuntime(**kwargs)
    try:
        agent = runtime.get_agent("luotianyi")
        assert isinstance(
            agent._stimulus_router.resolve(d.StimulusKind.TOUCH_INTERACTION),
            TouchInteractionHandler,
        )
        assert isinstance(
            agent._action_router.resolve(d.ActionKind.RESTORE_EXPRESSION),
            RestoreExpressionHandler,
        )
    finally:
        await runtime.shutdown()
