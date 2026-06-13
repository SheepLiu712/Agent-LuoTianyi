from pathlib import Path

from src.plugins.schedule.official_feed_fetcher import (
    BILI_DYNAMIC_FEATURES,
    BILI_DYNAMIC_WEB_LOCATION,
    OfficialFeedFetcher,
)


def test_build_bili_space_url_uses_opus_features(tmp_path: Path) -> None:
    fetcher = OfficialFeedFetcher(config={}, data_file=str(tmp_path / "feed_cache.json"))
    url = fetcher._build_bili_space_url(uid="36081646", offset="abc")

    assert "host_mid=36081646" in url
    assert "type=all" in url
    assert "platform=web" in url
    assert f"features={BILI_DYNAMIC_FEATURES}" in url
    assert f"web_location={BILI_DYNAMIC_WEB_LOCATION}" in url
    assert "offset=abc" in url


def test_parse_bili_opus_item_reads_summary_text_and_images(tmp_path: Path) -> None:
    fetcher = OfficialFeedFetcher(config={}, data_file=str(tmp_path / "feed_cache.json"))

    raw_item = {
        "id_str": "1207789540018749465",
        "type": "DYNAMIC_TYPE_DRAW",
        "modules": {
            "module_author": {
                "name": "洛天依",
                "pub_ts": 1735660800,
            },
            "module_dynamic": {
                "desc": None,
                "major": {
                    "type": "MAJOR_TYPE_OPUS",
                    "opus": {
                        "summary": {
                            "text": "诞生于纯蓝之中的魔女，要将世界染成五光十色的……"
                        },
                        "pics": [
                            {"url": "https://i0.hdslb.com/example-1.png"},
                            {"url": "https://i0.hdslb.com/example-2.png"},
                        ],
                    },
                },
            },
        },
    }

    parsed = fetcher._parse_bili_item("36081646", raw_item)

    assert parsed is not None
    assert "诞生于纯蓝之中的魔女，要将世界染成五光十色的" in parsed.content
    assert parsed.pics == [
        "https://i0.hdslb.com/example-1.png",
        "https://i0.hdslb.com/example-2.png",
    ]
    assert parsed.source_url == "https://www.bilibili.com/opus/1207789540018749465"
