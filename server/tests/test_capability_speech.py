"""Speech capability integration tests."""

import base64
import os
import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.speech import SpeechCapability
from src.utils.helpers import load_config


@pytest.fixture(scope="module", autouse=True)
def server_cwd():
    old_cwd = os.getcwd()
    os.chdir(server_root)
    try:
        yield
    finally:
        os.chdir(old_cwd)


CHARACTER_ID = "luotianyi"
SAMPLE_TEXT = "你好，测试一下语音合成。"
SAMPLE_TONE = "normal"


@pytest.fixture(scope="module")
def capability_config():
    return load_config("config/config.json")["capabilities"]


@pytest.fixture(scope="module")
def speech_capability(capability_config):
    speech = SpeechCapability(capability_config["tts"])
    try:
        yield speech
    finally:
        for module in speech.tts_module.values():
            module.tts_server.stop(force=True)


def _assert_base64_audio(payload: str) -> bytes:
    assert isinstance(payload, str)
    assert payload.strip(), "audio payload should not be empty"
    audio = base64.b64decode(payload)
    assert len(audio) > 1024, "decoded audio should contain real waveform data"
    return audio


def test_tts_config_is_valid(capability_config):
    tts_cfg = capability_config.get("tts", {})
    assert CHARACTER_ID in tts_cfg

    character_cfg = tts_cfg[CHARACTER_ID]
    required_paths = [
        "reference_audio_dir",
        "reference_audio_lyrics",
        "server_config_path",
        "interface_config_path",
    ]
    for key in required_paths:
        value = character_cfg.get(key)
        assert value, f"capabilities.tts.{CHARACTER_ID}.{key} is required"
        assert Path(value).exists(), f"configured path does not exist: {value}"


@pytest.mark.asyncio
async def test_tts_say_returns_non_empty_audio(speech_capability):
    audio_b64 = await speech_capability.say(CHARACTER_ID, SAMPLE_TEXT, SAMPLE_TONE)
    audio = _assert_base64_audio(audio_b64)
    assert audio[:4] == b"RIFF", "non-streaming TTS should return WAV bytes"


def test_tts_say_stream_returns_non_empty_audio_chunks(speech_capability):
    chunks = list(speech_capability.say_stream(CHARACTER_ID, SAMPLE_TEXT, SAMPLE_TONE))
    assert chunks, "streaming TTS should yield at least one audio chunk"
    decoded_chunks = [_assert_base64_audio(chunk) for chunk in chunks]
    assert sum(len(chunk) for chunk in decoded_chunks) > 1024
