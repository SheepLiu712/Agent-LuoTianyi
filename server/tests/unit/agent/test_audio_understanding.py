"""音频理解结构校验、重试、降级及上下文不变量。"""

import asyncio
import json

import pytest

import src.domain.agent as d
from src.agent.context import AudioContent, AudioUnderstandingStatus, render_audio_context
from src.agent.context._storage import _decode_entry, _encode_entry
from src.agent.skills.cognitive import AudioUnderstandingSkill
from src.infrastructure.media import ResolvedMedia


class _Resolver:
    def __init__(self):
        self.calls = []

    def resolve(self, media_ref, *, owner_user_id, expected_kind=None):
        self.calls.append((media_ref, owner_user_id, expected_kind))
        return ResolvedMedia(data=b"audio", mime_type="audio/mp4")


class _Module:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_response(self, *, audio_base64):
        self.calls.append(audio_base64)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return await response()
        return {"content": json.dumps(response, ensure_ascii=False)}


def _skill(responses, **kwargs):
    resolver = _Resolver()
    module = _Module(responses)
    return AudioUnderstandingSkill({}, resolver, audio_module=module, retry_delay_seconds=0, **kwargs), resolver, module


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"transcript": "今晚吃饭吧。", "emotion": None, "sound_description": None}, "[音频]用户说：“今晚吃饭吧。”"),
        (
            {"transcript": "别这样。", "emotion": "生气", "sound_description": None},
            "[音频]用户带着生气的情绪说：“别这样。”",
        ),
        ({"transcript": None, "emotion": None, "sound_description": "一段猫叫声。"}, "[音频]一段猫叫声。"),
        (
            {"transcript": "成功啦。", "emotion": "开心", "sound_description": "随后响起掌声。"},
            "[音频]用户带着开心的情绪说：“成功啦。”；随后响起掌声。",
        ),
    ],
)
async def test_understands_supported_audio_shapes(payload, expected):
    skill, resolver, module = _skill([payload])
    media_ref = d.MediaRef(media_id="audio-id")
    media, status, result = await skill.understand(media_ref, owner_user_id="owner")
    assert media.mime_type == "audio/mp4"
    assert status is AudioUnderstandingStatus.UNDERSTOOD
    assert render_audio_context(status=status, **result.__dict__) == expected
    assert resolver.calls == [(media_ref, "owner", "audio")]
    assert module.calls == ["data:audio/mp4;base64,YXVkaW8="]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"transcript": "hello", "emotion": None},
        {"transcript": 1, "emotion": None, "sound_description": None},
        {"transcript": " ", "emotion": " ", "sound_description": " "},
        {"transcript": None, "emotion": "开心", "sound_description": "掌声"},
    ],
)
async def test_invalid_structure_retries_then_degrades(bad):
    skill, _, module = _skill([bad, bad])
    _, status, result = await skill.understand(d.MediaRef(media_id="audio-id"), owner_user_id="owner")
    assert status is AudioUnderstandingStatus.NOT_UNDERSTOOD
    assert result.transcript is result.emotion is result.sound_description is None
    assert len(module.calls) == 2


@pytest.mark.asyncio
async def test_timeout_retries_once_then_degrades():
    async def slow():
        await asyncio.sleep(0.05)

    skill, _, module = _skill([slow, slow], timeout_seconds=0.001)
    _, status, _ = await skill.understand(d.MediaRef(media_id="audio-id"), owner_user_id="owner")
    assert status is AudioUnderstandingStatus.NOT_UNDERSTOOD
    assert len(module.calls) == 2


@pytest.mark.asyncio
async def test_first_failure_then_success():
    valid = {"transcript": "重试成功", "emotion": None, "sound_description": None}
    skill, _, module = _skill([RuntimeError("provider unavailable"), valid])
    _, status, result = await skill.understand(d.MediaRef(media_id="audio-id"), owner_user_id="owner")
    assert status is AudioUnderstandingStatus.UNDERSTOOD
    assert result.transcript == "重试成功"
    assert len(module.calls) == 2


def test_audio_content_invariants_and_rendering():
    understood = AudioContent(
        media_id="audio-id",
        mime_type="audio/mp4",
        duration_ms=1000,
        understanding_status=AudioUnderstandingStatus.UNDERSTOOD,
        transcript="你好",
        emotion=None,
        sound_description="随后响起掌声。",
    )
    assert understood.text == "[音频]用户说：“你好”；随后响起掌声。"
    degraded = AudioContent(
        media_id="audio-id",
        mime_type="audio/mp4",
        duration_ms=1000,
        understanding_status=AudioUnderstandingStatus.NOT_UNDERSTOOD,
        transcript=None,
        emotion=None,
        sound_description=None,
    )
    assert degraded.text == "[音频]听不清"
    with pytest.raises(ValueError):
        AudioContent(
            media_id="audio-id",
            mime_type="audio/mp4",
            duration_ms=1000,
            understanding_status=AudioUnderstandingStatus.UNDERSTOOD,
            transcript=None,
            emotion="开心",
            sound_description="掌声",
        )


def test_audio_storage_round_trip_and_rejects_mismatched_rendered_text():
    from datetime import datetime

    from src.agent.context import ConversationEntry

    content = AudioContent(
        media_id="audio-id",
        mime_type="audio/mp4",
        duration_ms=1000,
        understanding_status=AudioUnderstandingStatus.UNDERSTOOD,
        transcript="你好",
        emotion=None,
        sound_description=None,
    )
    entry = ConversationEntry("entry", datetime(2026, 1, 1), "user", content)
    encoded = _encode_entry(entry)
    decoded = _decode_entry(
        {
            "uuid": encoded.uuid,
            "timestamp": encoded.timestamp,
            "source": encoded.source,
            "type": encoded.type,
            "content": encoded.content,
            "meta_data": encoded.data,
        }
    )
    assert decoded == entry
    with pytest.raises(ValueError, match="不一致"):
        _decode_entry(
            {
                "uuid": encoded.uuid,
                "timestamp": encoded.timestamp,
                "source": encoded.source,
                "type": encoded.type,
                "content": "[音频]被篡改",
                "meta_data": encoded.data,
            }
        )
    with pytest.raises(ValueError):
        AudioContent(
            media_id="audio-id",
            mime_type="audio/mp4",
            duration_ms=1000,
            understanding_status=AudioUnderstandingStatus.NOT_UNDERSTOOD,
            transcript="不应存在",
            emotion=None,
            sound_description=None,
        )
