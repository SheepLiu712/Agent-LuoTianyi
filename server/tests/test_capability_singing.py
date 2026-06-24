"""Singing capability tests."""

import os
import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.singing import SingingCapability
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
KNOWN_SONG = "66CCFF"
UNKNOWN_SONG = "这首不存在的测试歌"


@pytest.fixture(scope="module")
def capability_config():
    return load_config("config/config.json")["capabilities"]


@pytest.fixture(scope="module")
def singing_capability(capability_config):
    return SingingCapability(capability_config["sing"])


def test_singing_config_is_valid(capability_config):
    sing_cfg = capability_config.get("sing", {})
    assert CHARACTER_ID in sing_cfg

    character_cfg = sing_cfg[CHARACTER_ID]
    resource_path = character_cfg.get("resource_path")
    assert resource_path
    assert Path(resource_path).exists()
    assert (Path(resource_path) / "songs").exists()
    assert (Path(resource_path) / "metadata.json").exists()


def test_singing_known_song_interfaces_return_usable_results(singing_capability: "SingingCapability"):
    songs = singing_capability.get_songs_can_sing(CHARACTER_ID)
    assert isinstance(songs, dict)
    assert songs, "singing capability should load at least one singable song"

    correct_song, segments = singing_capability.can_i_sing_song(CHARACTER_ID, KNOWN_SONG)
    assert correct_song == KNOWN_SONG
    assert segments

    planned_song, planned_segment = singing_capability.build_sing_plan(CHARACTER_ID, [KNOWN_SONG])
    assert planned_song == KNOWN_SONG
    assert planned_segment in segments

    lyrics = singing_capability.get_segment_lyrics(CHARACTER_ID, correct_song, segments[0])
    assert isinstance(lyrics, str)
    assert lyrics.strip()

    audio = singing_capability.sing(CHARACTER_ID, correct_song, segments[0])
    assert isinstance(audio, bytes)
    assert len(audio) > 1024
    assert audio[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_singing_unknown_song_interfaces_return_empty_results_without_error(
    singing_capability: "SingingCapability",
    monkeypatch,
):
    manager = singing_capability.singing_manager[CHARACTER_ID]
    monkeypatch.setattr(manager, "add_wished_song", lambda song_name: True)

    correct_song, segments = singing_capability.can_i_sing_song(CHARACTER_ID, UNKNOWN_SONG)
    assert correct_song == ""
    assert segments == []

    planned_song, planned_segment = singing_capability.build_sing_plan(CHARACTER_ID, [UNKNOWN_SONG])
    assert planned_song == UNKNOWN_SONG
    assert planned_segment is None

    assert singing_capability.sing(CHARACTER_ID, UNKNOWN_SONG, "不存在的段落") is None
    assert singing_capability.get_segment_lyrics(CHARACTER_ID, UNKNOWN_SONG, "不存在的段落") == ""

    llm_text = await singing_capability.can_i_sing_song_llm(CHARACTER_ID, UNKNOWN_SONG)
    assert UNKNOWN_SONG in llm_text
    assert "无法演唱" in llm_text
