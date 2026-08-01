import os
import sys
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.speech import speech as speech_module
from src.capabilities.speech.speech import SpeechCapability
from src.capabilities.speech.tts_module import get_tts_server_key


class FakeModule:
    def __init__(self, server):
        self.tts_server = server
        self.say_calls = []
        self.stream_calls = []

    async def synthesize_speech_with_tone(self, text, tone, *, speaker=None):
        self.say_calls.append((text, tone, speaker))
        return b"audio"

    def stream_synthesize_speech_with_tone(self, text, tone, *, speaker=None):
        self.stream_calls.append((text, tone, speaker))
        yield b"chunk"

    @staticmethod
    def encode_audio_to_base64(audio):
        return audio.decode("ascii")


class FakeServer:
    def __init__(self):
        self.stop_calls = 0

    def request_stop(self):
        pass

    def stop(self):
        self.stop_calls += 1


def install_fake_factory(monkeypatch):
    created_servers = []

    def init_module(_config, *, tts_server=None):
        if tts_server is None:
            tts_server = FakeServer()
            created_servers.append(tts_server)
        return FakeModule(tts_server)

    monkeypatch.setattr(speech_module, "init_tts_module", init_module)
    return created_servers


def test_server_key_normalizes_equivalent_paths(tmp_path):
    config_path = tmp_path / "tts.yaml"
    equivalent_path = tmp_path / "nested" / ".." / "tts.yaml"

    first = get_tts_server_key({"server_config_path": str(config_path)})
    second = get_tts_server_key({"server_config_path": str(equivalent_path)})

    assert first == second
    assert first[1] == os.path.normcase(os.path.realpath(config_path))


def test_characters_share_worker_by_backend_config_and_flags(monkeypatch, tmp_path):
    created_servers = install_fake_factory(monkeypatch)
    config_path = tmp_path / "tts.yaml"
    speech = SpeechCapability(
        {
            "luotianyi": {
                "server_config_path": str(config_path),
                "speaker": "lty",
            },
            "yanhe": {
                "server_config_path": str(tmp_path / "nested" / ".." / "tts.yaml"),
                "speaker": "yanhe",
            },
        }
    )

    assert len(created_servers) == 1
    assert speech.tts_module["luotianyi"].tts_server is created_servers[0]
    assert speech.tts_module["yanhe"].tts_server is created_servers[0]


def test_worker_flags_are_part_of_server_ownership_key(monkeypatch, tmp_path):
    created_servers = install_fake_factory(monkeypatch)
    config_path = str(tmp_path / "tts.yaml")

    SpeechCapability(
        {
            "quiet": {
                "server_config_path": config_path,
                "suppress_worker_output": True,
            },
            "verbose": {
                "server_config_path": config_path,
                "suppress_worker_output": False,
            },
        }
    )

    assert len(created_servers) == 2


@pytest.mark.asyncio
async def test_character_speaker_mapping_reaches_say_and_stream(monkeypatch, tmp_path):
    install_fake_factory(monkeypatch)
    speech = SpeechCapability(
        {
            "luotianyi": {
                "server_config_path": str(tmp_path / "tts.yaml"),
                "speaker": "speaker-lty",
            }
        }
    )
    module = speech.tts_module["luotianyi"]

    assert await speech.say("luotianyi", "hello", "normal") == "audio"
    assert list(speech.say_stream("luotianyi", "hello", "normal")) == ["chunk"]
    assert module.say_calls == [("hello", "normal", "speaker-lty")]
    assert module.stream_calls == [("hello", "normal", "speaker-lty")]


@pytest.mark.asyncio
async def test_shared_worker_stops_once_and_stop_is_idempotent(monkeypatch, tmp_path):
    created_servers = install_fake_factory(monkeypatch)
    config_path = str(tmp_path / "tts.yaml")
    speech = SpeechCapability(
        {
            "first": {"server_config_path": config_path},
            "second": {"server_config_path": config_path},
        }
    )

    await speech.stop()
    await speech.stop()

    assert len(created_servers) == 1
    assert created_servers[0].stop_calls == 1


def test_partial_shared_module_failure_rolls_back_worker_once(monkeypatch, tmp_path):
    server = FakeServer()
    calls = 0

    def init_module(_config, *, tts_server=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("module failed")
        return FakeModule(tts_server or server)

    monkeypatch.setattr(speech_module, "init_tts_module", init_module)
    config_path = str(tmp_path / "tts.yaml")

    with pytest.raises(RuntimeError, match="module failed"):
        SpeechCapability(
            {
                "first": {"server_config_path": config_path},
                "second": {"server_config_path": config_path},
            }
        )

    assert server.stop_calls == 1


def test_invalid_speaker_mapping_fails_before_start(monkeypatch, tmp_path):
    created_servers = install_fake_factory(monkeypatch)

    with pytest.raises(ValueError, match="non-empty string"):
        SpeechCapability(
            {
                "luotianyi": {
                    "server_config_path": str(tmp_path / "tts.yaml"),
                    "speaker": "",
                }
            }
        )

    assert created_servers == []
