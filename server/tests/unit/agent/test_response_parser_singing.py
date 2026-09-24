import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parents[3])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.skills.cognitive._response_parser import StructuredResponseParser
from src.agent.skills.contracts import ReplyDraft


def build_parser() -> StructuredResponseParser:
    return StructuredResponseParser(
        default_draft=ReplyDraft(
            content="默认回复", sound_content="默认回复", tone="normal", expression="微笑脸"
        ),
        tone_mapper=lambda tone: ("微笑脸", "normal"),
    )


def test_sing_intent_is_kept_when_it_differs_from_plan():
    items = build_parser().parse("[sing] 《歌曲B》", ("歌曲A", "段落1"))

    assert len(items) == 1
    assert isinstance(items[0], ReplyDraft)
    assert items[0].sing == ("歌曲B", "")


def test_sing_intent_is_kept_without_a_plan():
    items = build_parser().parse("[sing] 《歌曲A》", None)

    assert len(items) == 1
    assert isinstance(items[0], ReplyDraft)
    assert items[0].sing == ("歌曲A", "")


def test_matching_sing_plan_keeps_its_preferred_segment():
    items = build_parser().parse("[sing] 《歌曲A》", ("歌曲A", "段落2"))

    assert len(items) == 1
    assert isinstance(items[0], ReplyDraft)
    assert items[0].sing == ("歌曲A", "段落2")
