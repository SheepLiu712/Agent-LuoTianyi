"""触摸 manifest 资源的失败丢弃边界。"""

import json
import wave
from pathlib import Path

import pytest
from support.skill_support import invocation
from support.touch_support import touch_request

import src.domain.agent as d
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.expression.touch import TouchReactionSkill


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


@pytest.mark.asyncio
async def test_character_touch_catalogs_and_missing_audio_do_not_cross_roles(tmp_path):
    configs, catalogs, audio_files = {}, {}, {}
    for character in ("甲", "乙"):
        folder = tmp_path / character
        folder.mkdir()
        audio = folder / "touch.wav"
        with wave.open(str(audio), "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes((b"\x01\x00" if character == "甲" else b"\x02\x00") * 10)
        manifest = folder / "manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "name": "touch_voice",
                        "audio_path": "touch.wav",
                        "text": "",
                        "expression": character,
                    }
                ]
            ),
            encoding="utf-8",
        )
        configs[character] = {"resource_names": ["touch_voice"], "probability": 1.0}
        catalogs[character] = {"manifest": str(manifest)}
        audio_files[character] = audio
    catalog = PreparedSpeechCatalog(catalogs)
    skill = TouchReactionSkill(configs, catalog)
    for character in ("甲", "乙"):
        reaction = skill.choose(invocation(character_id=character), stimulus())
        assert reaction.expression_id == character
        assert (await catalog.read_audio(character, reaction.audio_ref.media_id)).data == audio_files[
            character
        ].read_bytes()
    audio_files["乙"].unlink()
    assert skill.choose(invocation(character_id="乙"), stimulus()) is None
    assert skill.choose(invocation(character_id="甲"), stimulus()).expression_id == "甲"
