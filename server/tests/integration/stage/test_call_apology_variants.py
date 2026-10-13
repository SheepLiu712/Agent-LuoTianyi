import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from support.call_apology import Recall, Replies, _Plans, _request, _stimulus, catalog

import src.domain.agent as d
from src.agent.handlers.stimulus import call as call_handlers
from src.agent.handlers.stimulus.call import CallSilenceElapsedHandler, CallStartedHandler, CallTurnCompletedHandler
from src.agent.skills.cognitive.call_recall import SilenceDecision
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.domain.call import CallAudioSemantic
from src.utils.logger import get_logger


def variants(tmp_path):
    catalog(tmp_path)
    entries = [
        dict(name=f"call_apology_{scene}_{suffix}", audio_path="apology.wav", text="sorry", expression="normal")
        for scene in ("opening", "turn", "silence")
        for suffix in ("1", "7", "gentle")
    ]
    # Unrelated entries and empty suffixes cannot leak into a scene's candidates.
    entries += [
        dict(name=name, audio_path="apology.wav", text="", expression="normal")
        for name in ("first_greet_1", "call_apology", "call_apology_turn_")
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(entries), encoding="utf8")
    return PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})


@pytest.mark.asyncio
@pytest.mark.parametrize("scene", ["opening", "turn", "silence"])
async def test_failed_handler_randomly_selects_only_its_scene(tmp_path, monkeypatch, scene):
    resources = variants(tmp_path)
    replies, recall = Replies(failing=True), Recall()

    async def speak(*args, **kwargs):
        return SilenceDecision.SPEAK

    recall.decide_silence = speak
    now, call_id = datetime.now(timezone.utc), uuid4()
    handlers = {
        "opening": (
            CallStartedHandler(replies, resources),
            _stimulus(d.CallStarted, call_id=call_id, connected_at=now),
        ),
        "turn": (
            CallTurnCompletedHandler(recall, replies, resources),
            _stimulus(
                d.CallTurnCompleted, call_id=call_id, turn_seq=1, audio_content=CallAudioSemantic(transcript="hello")
            ),
        ),
        "silence": (
            CallSilenceElapsedHandler(recall, replies, resources),
            _stimulus(d.CallSilenceElapsed, call_id=call_id, silence_ms=5000),
        ),
    }
    handler, stimulus = handlers[scene]
    chosen = []
    for index in range(3):

        def choice(entries):
            assert {item.name for item in entries} == {
                f"call_apology_{scene}_{suffix}" for suffix in ("1", "7", "gentle")
            }
            return entries[index]

        monkeypatch.setattr("src.agent.skills.expression.prepared_speech.random.choice", choice)
        plans = _Plans()
        report = await handler.handle(_request(stimulus), plans)
        assert report.request_status is d.HandlingRequestStatus.FAILED
        action = plans.drafts[0].actions[0]
        chosen.append(action.prepared_audio_ref.media_id)
        assert action.call_delivery.provisional
        assert action.content == ""
        assert not any(entry.source == "agent" for entry in plans.context.conversation.entries)
    assert len(set(chosen)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("scene", ["opening", "turn", "silence"])
async def test_reply_failure_logs_only_stable_metadata(tmp_path, monkeypatch, scene):
    class CapturingHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            record.getMessage()
            self.records.append(record)

    resources = variants(tmp_path)
    replies, recall = Replies(failing=True), Recall()

    async def speak(*args, **kwargs):
        return SilenceDecision.SPEAK

    recall.decide_silence = speak
    now, call_id = datetime.now(timezone.utc), uuid4()
    handlers = {
        "opening": (
            CallStartedHandler(replies, resources),
            _stimulus(d.CallStarted, call_id=call_id, connected_at=now),
        ),
        "turn": (
            CallTurnCompletedHandler(recall, replies, resources),
            _stimulus(
                d.CallTurnCompleted, call_id=call_id, turn_seq=1, audio_content=CallAudioSemantic(transcript="hello")
            ),
        ),
        "silence": (
            CallSilenceElapsedHandler(recall, replies, resources),
            _stimulus(d.CallSilenceElapsed, call_id=call_id, silence_ms=5000),
        ),
    }
    logger = get_logger(call_handlers.__name__)
    capture = CapturingHandler()
    monkeypatch.setattr(logger, "handlers", [capture])

    handler, stimulus = handlers[scene]
    report = await handler.handle(_request(stimulus), _Plans())

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.getMessage() == "Call reply generation failed request_id=request error_type=RuntimeError"
    assert "private reply should not be logged" not in record.getMessage()


@pytest.mark.parametrize("missing", ["opening", "turn", "silence"])
def test_each_scene_is_required_for_readiness(tmp_path, missing):
    resources = variants(tmp_path)
    assert resources.supports_call_apology("luotianyi")
    manifest = tmp_path / "manifest.json"
    entries = json.loads(manifest.read_text(encoding="utf8"))
    entries = [entry for entry in entries if not entry["name"].startswith(f"call_apology_{missing}_")]
    manifest.write_text(json.dumps(entries), encoding="utf8")
    assert not PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}}).supports_call_apology("luotianyi")


def test_every_selectable_variant_must_be_valid(tmp_path):
    variants(tmp_path)
    (tmp_path / "broken.wav").write_bytes(b"not a wave file")
    manifest = tmp_path / "manifest.json"
    entries = json.loads(manifest.read_text(encoding="utf8"))
    entries.append(dict(name="call_apology_turn_broken", audio_path="broken.wav", text="", expression="normal"))
    manifest.write_text(json.dumps(entries), encoding="utf8")
    assert not PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}}).supports_call_apology("luotianyi")
