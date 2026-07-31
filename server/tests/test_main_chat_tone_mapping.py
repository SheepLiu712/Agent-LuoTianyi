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
        "开心": "happy",
        "喜欢": "happy",
        "温柔": "tender",
        "伤心": "sad",
        "生气": "angry",
        "狂喜": "happy",
        "暴怒": "angry",
        "悲痛": "sad",
        "惊恐": "sad",
    }
    main_chat.llm_tone_to_l2d_expression = {
        "中性": "微笑脸",
        "开心": "微笑脸",
        "喜欢": "喜欢脸",
        "温柔": "温柔脸",
        "伤心": "难过脸",
        "生气": "生气脸",
        "狂喜": "卖萌",
        "暴怒": "生气脸",
        "悲痛": "难过脸",
        "惊恐": "害怕脸",
    }
    main_chat.llm_tone_aliases = {
        "高兴": "开心",
        "快乐": "开心",
        "难过": "伤心",
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


def test_main_chat_tone_mapping_resolves_alias_to_canonical():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("高兴")

    assert expression == "微笑脸"
    assert tts_tone == "happy"


def test_main_chat_tone_mapping_resolves_canonical_expression():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("喜欢")

    assert expression == "喜欢脸"
    assert tts_tone == "happy"


def test_main_chat_tone_mapping_normalizes_brackets_and_punctuation():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("[开心。]")

    assert expression == "微笑脸"
    assert tts_tone == "happy"


def test_main_chat_tone_mapping_fuzzy_matches_decorated_tone():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("有点伤心")

    assert expression == "难过脸"
    assert tts_tone == "sad"


def test_main_chat_tone_mapping_maps_extreme_joy():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("狂喜")

    assert expression == "卖萌"
    assert tts_tone == "happy"


def test_main_chat_tone_mapping_maps_extreme_anger():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("暴怒")

    assert expression == "生气脸"
    assert tts_tone == "angry"


def test_main_chat_tone_mapping_maps_extreme_sadness():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("悲痛")

    assert expression == "难过脸"
    assert tts_tone == "sad"


def test_main_chat_tone_mapping_fuzzy_matches_suffix_tone():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("温柔地")

    assert expression == "温柔脸"
    assert tts_tone == "tender"


def test_main_chat_tone_mapping_unknown_tone_falls_back_to_default():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("量子态")

    assert expression == "微笑脸"
    assert tts_tone == "happy"
    assert main_chat.logger.warnings, "expected a warning for unknown tone"


def test_main_chat_tone_mapping_maps_extreme_fear():
    main_chat = build_main_chat_with_mapping()

    expression, tts_tone = main_chat._get_expressions_and_tts_tone("惊恐")

    assert expression == "害怕脸"
    assert tts_tone == "sad"


def test_one_sentence_chat_allows_default_tts_tone():
    response = OneSentenceChat(content="你好", tone="normal", expression="微笑脸")

    assert response.sound_content == "你好"
    assert response.tone == "normal"
