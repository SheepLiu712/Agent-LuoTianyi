import json
import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.reflex import CharacterReflex
from src.domain import CharacterProfile
from src.domain.chat import ChatInputEvent, ChatInputEventType


@pytest.mark.asyncio
async def test_character_reflex_uses_touch_resources_from_profile(tmp_path):
    touch_dir = tmp_path / "touch_voice"
    touch_dir.mkdir()
    (touch_dir / "touch_voice1.wav").write_bytes(b"fake-audio")
    (touch_dir / "voice_to_expression.json").write_text(
        json.dumps({"touch_voice1": "moemoe"}),
        encoding="utf-8",
    )

    profile = CharacterProfile(
        character_id="test_character",
        display_name="Test Character",
        memory_namespace="test_character",
        reflex={
            "touch": {
                "fast_reply": {
                    "touch_voice_dir": str(touch_dir),
                    "probability": 1.0,
                }
            }
        },
    )
    reflex = CharacterReflex(profile)
    responses = []

    async def collect(response):
        responses.append(response)

    handled = await reflex.try_handle(
        ChatInputEvent(event_type=ChatInputEventType.USER_TOUCH, text="touch"),
        collect,
    )

    assert handled is True
    assert responses[0].audio
    assert responses[0].expression == "moemoe"
    assert responses[0].display_in_chat is False
    assert responses[0].is_ephemeral is True
