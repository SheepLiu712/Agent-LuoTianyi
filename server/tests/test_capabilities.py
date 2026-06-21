import asyncio
import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.capabilities import CapabilityRegistry, SingingCapability, SpeechCapability


class FakeTTSModule:
    async def synthesize_speech_with_tone(self, text, tone):
        return f"{tone}:{text}".encode("utf-8")

    def stream_synthesize_speech_with_tone(self, text, tone):
        yield f"{tone}:{text}:1".encode("utf-8")
        yield f"{tone}:{text}:2".encode("utf-8")

    def encode_audio_to_base64(self, audio_bytes):
        return audio_bytes.decode("utf-8")


class FakeMusicManager:
    def __init__(self):
        self.wished = []

    def pick_random_song_and_segment(self):
        return "随机歌", "副歌"

    def pick_segment_for_song(self, song_name):
        if song_name == "会唱的歌":
            return song_name, "主歌"
        return "", ""

    def add_wished_song(self, song_name):
        self.wished.append(song_name)
        return True

    def get_song_segment(self, song_name, segment):
        return [], b"audio"

    def get_segment_lyrics(self, song_name, segment):
        return "lyrics"


def test_speech_capability_wraps_tts_module():
    capability = SpeechCapability(FakeTTSModule())

    assert asyncio.run(capability.say("你好", "happy")) == "happy:你好"
    assert list(capability.say_stream("你好", "happy")) == ["happy:你好:1", "happy:你好:2"]


def test_singing_capability_builds_plan_and_sings():
    music = FakeMusicManager()
    capability = SingingCapability(music)

    assert capability.build_sing_plan(["random_song"]) == ("随机歌", "副歌")
    assert capability.build_sing_plan(["《会唱的歌》是一首歌"]) == ("会唱的歌", "主歌")
    assert capability.build_sing_plan(["《不会唱的歌》是一首歌"]) == ("不会唱的歌", None)
    assert music.wished == ["不会唱的歌"]
    assert capability.sing("会唱的歌", "主歌") == b"audio"
    assert capability.get_segment_lyrics("会唱的歌", "主歌") == "lyrics"


def test_capability_registry_groups_agent_actions():
    registry = CapabilityRegistry(
        speech=SpeechCapability(FakeTTSModule()),
        singing=SingingCapability(FakeMusicManager()),
    )

    assert registry.singing.build_sing_plan(["random_song"]) == ("随机歌", "副歌")
