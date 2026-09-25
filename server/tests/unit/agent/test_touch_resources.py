"""触摸 manifest 资源的失败丢弃边界。"""

import json
import wave
from pathlib import Path

import pytest
from support.touch_support import touch_request

import src.domain.agent as d
from src.agent.skills.expression.touch import TouchReactionSkill
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from support.skill_support import invocation


def configured_skill(tmp_path: Path) -> tuple[TouchReactionSkill, Path]:
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
    return (
        TouchReactionSkill(
            {
                "luotianyi": {
                    "resource_names": ["touch_voice"],
                    "probability": 1.0,
                }
            },
            PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}}),
        ),
        audio,
    )


def stimulus() -> d.TouchInteraction:
    return touch_request().stimulus


def test_touch_resource_probability_miss_returns_none(tmp_path, monkeypatch):
    skill, _ = configured_skill(tmp_path)
    monkeypatch.setattr(skill._resources["luotianyi"][0], "should_use_fast_path", lambda: False)

    assert skill.choose(invocation(), stimulus()) is None


@pytest.mark.parametrize("failure", ["deleted", "unreadable"])
def test_touch_resource_read_failure_returns_none(tmp_path, monkeypatch, failure):
    skill, audio = configured_skill(tmp_path)
    monkeypatch.setattr("src.agent.skills.expression._touch_resources.random.choice", lambda files: next(iter(files)))
    if failure == "deleted":
        audio.unlink()
    else:
        monkeypatch.setattr(type(audio), "read_bytes", lambda self: (_ for _ in ()).throw(OSError("failed")))

    assert skill.choose(invocation(), stimulus()) is None
