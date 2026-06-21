import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.main_chat import OneSentenceChat, SongSegmentChat
from src.agent.prompt_assembly import RealizationPromptAssembler
from src.agent.response_parser import StructuredResponseParser


def test_realization_prompt_assembler_builds_legacy_prompt_variables():
    assembler = RealizationPromptAssembler()

    prompt_input = assembler.build(
        character_name="Luo Tianyi",
        character_persona="persona",
        speaking_style="style",
        reply_topic="topic",
        user_nickname="user",
        user_description="desc",
        preference_context="prefs",
        conversation_history="history",
        fact_hits=["fact", "fact"],
        memory_hits=["memory"],
        sing_plan=("Song A|alias", "segment-1"),
    )

    assert prompt_input.character_name == "Luo Tianyi"
    assert prompt_input.user_persona == "desc"
    assert prompt_input.conversation_history == "history"
    assert prompt_input.reply_topic == "topic"
    assert prompt_input.extra_knowledge == "fact\nmemory"
    assert "Song A" in prompt_input.sing_requirement


def test_structured_response_parser_parses_tone_line():
    default = OneSentenceChat(content="")
    parser = StructuredResponseParser(
        sentence_cls=OneSentenceChat,
        song_cls=SongSegmentChat,
        default_response=default,
        tone_mapper=lambda tone: (f"expr-{tone}", f"tts-{tone}"),
    )

    parsed = parser.parse("[happy] hello", sing_plan=None)

    assert len(parsed) == 1
    assert isinstance(parsed[0], OneSentenceChat)
    assert parsed[0].content == "hello"
    assert parsed[0].expression == "expr-happy"
    assert parsed[0].tone == "tts-happy"


def test_structured_response_parser_parses_matching_sing_line():
    default = OneSentenceChat(content="")
    parser = StructuredResponseParser(
        sentence_cls=OneSentenceChat,
        song_cls=SongSegmentChat,
        default_response=default,
        tone_mapper=lambda tone: ("", ""),
    )

    parsed = parser.parse("[sing] Song A", sing_plan=("Song A", "segment-1"))

    assert len(parsed) == 1
    assert isinstance(parsed[0], SongSegmentChat)
    assert parsed[0].song == "Song A"
    assert parsed[0].segment == "segment-1"


def test_structured_response_parser_falls_back_on_unstructured_text():
    default = OneSentenceChat(content="fallback")
    parser = StructuredResponseParser(
        sentence_cls=OneSentenceChat,
        song_cls=SongSegmentChat,
        default_response=default,
        tone_mapper=lambda tone: ("", ""),
    )

    assert parser.parse("plain text", sing_plan=None) == [default]
