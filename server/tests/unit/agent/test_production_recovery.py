"""Regression cases from the November 14 production incident."""

import importlib.util
from importlib.metadata import distribution

import pytest

from src.agent.context._storage import _decode_entry
from src.agent.context.models import SongContent
from src.agent.skills.expression.speaking.gsv_languages import configure_chinese_language_labels


@pytest.mark.parametrize("text", ["（唱歌）：《纯蓝》\n歌词", "（唱了《纯蓝》）\n歌词"])
def test_legacy_song_history_retains_text_and_title(text):
    entry = _decode_entry(
        dict(uuid="old", timestamp="2026-11-14T12:00:00", source="agent", type="sing", content=text, meta_data=None)
    )
    assert entry.content == SongContent(text, "纯蓝")


def test_structured_song_title_takes_precedence_over_legacy_text():
    entry = _decode_entry(
        dict(
            uuid="new",
            timestamp="2026-11-14T12:00:00",
            source="agent",
            type="sing",
            content="（唱了《旧名》）\n歌词",
            meta_data={"song": "正式曲名", "segment": "副歌"},
        )
    )
    assert entry.content.song == "正式曲名"
    assert entry.content.segment == "副歌"


def test_unknown_song_format_is_not_silently_relabelled():
    with pytest.raises(ValueError, match="演唱历史缺少曲名"):
        _decode_entry(
            dict(
                uuid="bad",
                timestamp="2026-11-14T12:00:00",
                source="agent",
                type="sing",
                content="没有可恢复的曲名",
                meta_data=None,
            )
        )


@pytest.mark.parametrize(
    "label,expected",
    [("yue", "zh"), ("wuu", "zh"), ("zh", "zh"), ("ja", "ja"), ("ko", "ko"), ("en", "en"), (None, None)],
)
def test_chinese_labels_are_normalized_before_filtering(label, expected):
    class Segmenter:
        _lang_classify = staticmethod(lambda text: label)
        _lang_classify_full = staticmethod(lambda text: label)

    configure_chinese_language_labels(Segmenter)
    assert Segmenter._lang_classify("text") == expected
    assert Segmenter._lang_classify_full("text") == expected


@pytest.mark.parametrize(
    "text,language",
    [
        ("你能跑到哪去呀？", "zh"),
        ("埃博拉病毒听起来比霍乱还可怕呀！", "zh"),
        ("こんにちは、元気ですか？", "ja"),
        ("안녕하세요", "ko"),
        ("Hello world", "en"),
    ],
)
def test_real_gsv_segmentation_preserves_supported_speech(text, language):
    # Load the classifier alone: no GPU/model startup is needed for segmentation.
    source = distribution("gsv-tts-lite").locate_file("gsv_tts/LangSegment.py")
    spec = importlib.util.spec_from_file_location("incident_lang_segment", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    configure_chinese_language_labels(module.LangSegment)
    segments = module.LangSegment.getTexts(text)
    assert segments
    assert all(segment["lang"] == language for segment in segments)
    assert "".join(segment["text"] for segment in segments).strip() == text
