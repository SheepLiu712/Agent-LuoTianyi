"""Frozen real browser captures: regression replay, not a new random acceptance."""
import json
from pathlib import Path
import sys

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.world.get_new_songs import daily_new_song_fetcher as daily
from src.subconscious.music_knowledge.song_database import Song
from src.subconscious.music_knowledge.jargon import SongEntityLinker

import html_surface

RECORDS = json.loads((Path(__file__).parent / "fixtures/vcpedia_fixed_acceptance.json").read_text(encoding="utf-8"))


CONSECUTIVE = json.loads((Path(__file__).parent / "fixtures/vcpedia_frozen_consecutive.json").read_text(encoding="utf-8"))


@pytest.fixture(params=range(3), ids=["qin", "dao", "paper"])
def replay(request, monkeypatch, tmp_path):
    record = RECORDS[request.param]
    page = record["response"]["parse"]
    calls = []
    def get(self, url, **kwargs):
        from urllib.parse import parse_qs, urlsplit
        params = kwargs.get("params") or {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        calls.append(params)
        assert params["page"] == page["title"]
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(record["response"], ensure_ascii=False).encode()
        return response
    monkeypatch.setattr(requests.Session, "get", get)
    crawler = VCPediaFetcher({"activated": True, "use_llm": False, "data_dir": str(tmp_path / "cache")})
    try:
        yield crawler, page, calls
    finally:
        crawler.session.close()


def surface_lines(page):
    return html_surface.surface_lines(page["text"]["*"])


@pytest.mark.parametrize("index", [0, 1, 2], ids=["goodbye", "estrus", "weekly-nonsong"])
def test_frozen_consecutive_source_full_fields_and_consumer(index, monkeypatch, tmp_path):
    record = CONSECUTIVE[index]
    page = record["response"]["parse"]
    def get(self, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(record["response"], ensure_ascii=False).encode()
        return response
    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(daily, "SONG_NAME_KEYWORDS_FILE", tmp_path / "names.txt")
    monkeypatch.setattr(daily, "SONG_LYRIC_KEYWORDS_FILE", tmp_path / "lyrics.txt")
    crawler = VCPediaFetcher({"activated": True, "use_llm": False, "data_dir": str(tmp_path / "cache")})
    engine = create_engine("sqlite:///:memory:")
    Song.metadata.create_all(engine)
    try:
        data = crawler.fetch_entity_description(page["title"])
        if index == 2:
            assert data["type"] == "Person" and not data["lyrics"]
            with Session(engine) as db:
                assert not daily.do_one_song(db, crawler, page["title"])
                assert db.query(Song).count() == 0
            assert not (tmp_path / "names.txt").exists()
            return
        expected = surface_lines(page)
        assert ["".join(line.split()) for line in data["lyrics"].splitlines() if line.strip()] == ["".join(line.split()) for line in expected]
        if index == 1:
            assert data["infobox"] == {"歌曲名称": "Estrus❤Cycle,发情期", "演唱": "心华", "UP主": "野良犬P", "投稿时间": "2016年6月10日", "再生": "5804（最终记录）"}
            assert "本曲旋律动感且毒性强" in "".join(data["summary"])
            assert "我希望你看着我" not in data["lyrics"]
        assert crawler.fetch_entity_description(page["title"]) == data
        with Session(engine) as db:
            assert daily.do_one_song(db, crawler, page["title"])
            assert db.query(Song).one().lyrics == data["lyrics"]
        linker = SongEntityLinker({}, str(tmp_path / "names.txt"), str(tmp_path / "lyrics.txt"))
        # Short standalone fragments cannot satisfy the six-character keyword contract.
        eligible = [line for line in expected if len("".join(line.split())) >= 6]
        assert any(linker.extract_and_verify(line) for line in eligible)
    finally:
        crawler.session.close()
        engine.dispose()


def test_fixed_main_roles_and_display_identity(replay):
    crawler, page, calls = replay
    display = {"刀马旦(虚拟歌手)": "刀马旦", "纸飞机(GhostFinal)": "纸飞机"}.get(page["title"], page["title"])
    data = crawler.fetch_entity_description(display, source_title=page["title"])
    expected = {"秦宣四方": ("沨漪", "忘川风华录"), "刀马旦": ("言和、乐正龙牙", "纳兰寻风"), "纸飞机": ("洛天依", "GhostFinal")}[display]
    assert (data["infobox"].get("演唱"), data["infobox"].get("UP主")) == expected
    assert data["name"] == display
    assert crawler.fetch_entity_description(display, source_title=page["title"]) == data
    assert len(calls) == 2


def test_fixed_full_lyrics_match_same_response_surface_html(replay):
    crawler, page, _ = replay
    data = crawler.fetch_entity_description(page["title"])
    actual = [line.strip() for line in data["lyrics"].splitlines() if line.strip()]
    expected = surface_lines(page)
    assert ["".join(x.split()) for x in actual] == ["".join(x.split()) for x in expected]


def test_fixed_infobox_never_leaks_dynamic_counts(replay):
    crawler, page, _ = replay
    data = crawler.fetch_entity_description(page["title"])
    assert "再生数为" not in str(data["infobox"])
