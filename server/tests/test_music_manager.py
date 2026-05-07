import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

from src.plugins.music.singing_manager import SingingManager


def test_get_songs_can_sing():
    music_manager = SingingManager(config={})
    songs = music_manager.get_songs_can_sing()
    assert isinstance(songs, dict)


def test_can_i_sing_song():
    music_manager = SingingManager(config={})
    name, segments = music_manager.can_i_sing_song("光与影的对白")
    assert isinstance(name, str)
    assert isinstance(segments, list)


def test_tool_names():
    music_manager = SingingManager(config={})
    tool_names = music_manager.get_tool_names()
    assert isinstance(tool_names, list)


def test_get_tools():
    music_manager = SingingManager(config={})
    tools = music_manager.get_tools()
    assert isinstance(tools, dict)
    assert len(tools) > 0

