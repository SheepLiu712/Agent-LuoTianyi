import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import MainChat, OneSentenceChat


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


def build_main_chat_with_mapping() -> MainChat:
    main_chat = MainChat.__new__(MainChat)
    main_chat.logger = FakeLogger()
    main_chat.llm_tone_to_tts_tone = {
        "中性": "happy",
        "温柔": "tender",
    }
    main_chat.llm_tone_to_l2d_expression = {
        "中性": "微笑脸",
        "温柔": "温柔脸",
    }
    return main_chat


def test_main_chat_tone_mapping_strips_outer_quotes():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("'温柔'")

    assert expression == "温柔脸"
    assert tts_tone == "tender"


def test_main_chat_tone_mapping_falls_back_for_empty_tone():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("")

    assert expression == "微笑脸"
    assert tts_tone == "happy"


def test_main_chat_tone_mapping_falls_back_when_mapping_is_missing():
    main_chat = MainChat.__new__(MainChat)
    main_chat.logger = FakeLogger()
    main_chat.llm_tone_to_tts_tone = {}
    main_chat.llm_tone_to_l2d_expression = {}

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("未知")

    assert expression == "微笑脸"
    assert tts_tone == "normal"


def test_one_sentence_chat_allows_default_tts_tone():
    response = OneSentenceChat(content="你好", tone="normal", expression="微笑脸")

    assert response.sound_content == "你好"
    assert response.tone == "normal"
