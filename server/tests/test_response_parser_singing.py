import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import OneSentenceChat, SongSegmentChat
from src.agent.response_parser import StructuredResponseParser


def build_parser() -> StructuredResponseParser:
    return StructuredResponseParser(
        sentence_cls=OneSentenceChat,
        song_cls=SongSegmentChat,
        default_response=OneSentenceChat(content="默认回复", tone="normal", expression="微笑脸"),
        tone_mapper=lambda tone: ("微笑脸", "normal"),
    )


def test_sing_intent_is_kept_when_it_differs_from_plan():
    items = build_parser().parse("[sing] 《歌曲B》", ("歌曲A", "段落1"))

    assert len(items) == 1
    assert isinstance(items[0], SongSegmentChat)
    assert items[0].song == "歌曲B"
    assert items[0].segment == ""


def test_sing_intent_is_kept_without_a_plan():
    items = build_parser().parse("[sing] 《歌曲A》", None)

    assert len(items) == 1
    assert isinstance(items[0], SongSegmentChat)
    assert items[0].song == "歌曲A"
    assert items[0].segment == ""


def test_matching_sing_plan_keeps_its_preferred_segment():
    items = build_parser().parse("[sing] 《歌曲A》", ("歌曲A", "段落2"))

    assert len(items) == 1
    assert isinstance(items[0], SongSegmentChat)
    assert items[0].segment == "段落2"
