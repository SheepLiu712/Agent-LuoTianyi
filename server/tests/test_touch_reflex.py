import asyncio
import json
import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.chat.chat_events import ChatInputEvent, ChatInputEventType
from src.agent.reflex import TouchFastReplyBuilder, TouchReflexResponder


def test_touch_fast_reply_builder_creates_ephemeral_audio_response(tmp_path):
    audio_path = tmp_path / "tap.wav"
    audio_path.write_bytes(b"audio-bytes")
    (tmp_path / "voice_to_expression.json").write_text(
        json.dumps({"tap": "surprised"}),
        encoding="utf-8",
    )

    response = TouchFastReplyBuilder(touch_voice_dir=tmp_path, probability=1.0).build_response()

    assert isinstance(response, list)
    assert response[0].audio
    assert response[0].expression == "surprised"
    assert response[0].display_in_chat is False
    assert response[0].is_ephemeral is True
    assert response[1].expression == "normal"


def test_touch_reflex_responder_handles_touch_before_topic_pipeline(tmp_path):
    audio_path = tmp_path / "tap.wav"
    audio_path.write_bytes(b"audio-bytes")
    builder = TouchFastReplyBuilder(touch_voice_dir=tmp_path, probability=1.0)
    responder = TouchReflexResponder(builder)
    sent = []

    async def send(response):
        sent.append(response)

    event = ChatInputEvent(event_type=ChatInputEventType.USER_TOUCH, text="tap", payload={})

    assert asyncio.run(responder.try_reply(event, send)) is True
    assert len(sent) == 1
    assert sent[0].is_ephemeral is True
    assert sent[0].display_in_chat is False


def test_touch_reflex_responder_falls_back_when_unavailable(tmp_path):
    builder = TouchFastReplyBuilder(touch_voice_dir=tmp_path, probability=1.0)
    responder = TouchReflexResponder(builder)
    sent = []

    async def send(response):
        sent.append(response)

    event = ChatInputEvent(event_type=ChatInputEventType.USER_TOUCH, text="tap", payload={})

    assert asyncio.run(responder.try_reply(event, send)) is False
    assert sent == []


def test_touch_reflex_responder_ignores_non_touch(tmp_path):
    builder = TouchFastReplyBuilder(touch_voice_dir=tmp_path, probability=1.0)
    responder = TouchReflexResponder(builder)

    async def send(response):
        raise AssertionError("non-touch event should not send a reflex response")

    event = ChatInputEvent(event_type=ChatInputEventType.USER_TEXT, text="hello", payload={})

    assert asyncio.run(responder.try_reply(event, send)) is False
