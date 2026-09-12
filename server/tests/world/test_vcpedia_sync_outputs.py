"""Offline output contracts through ingestion/sync with isolated SQL and files."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.world.get_new_songs import daily_new_song_fetcher as daily
from src.subconscious.music_knowledge import song_database as database
from src.world.get_new_songs.task import VCPediaNewSongTask


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(daily, "SONG_NAME_KEYWORDS_FILE", tmp_path / "names.txt")
    monkeypatch.setattr(daily, "SONG_LYRIC_KEYWORDS_FILE", tmp_path / "lyrics.txt")
    monkeypatch.setattr(database, "engine", None)
    monkeypatch.setattr(database, "SessionLocal", None)
    monkeypatch.setattr(daily.time, "sleep", lambda seconds: None)
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SimpleNamespace(db=db, path=tmp_path)
    engine.dispose()
    if database.engine is not None:
        database.engine.dispose()


def supplier(lyrics="这是第一句完整歌词", **fields):
    return SimpleNamespace(fetch_entity_description=lambda name: {
        "infobox": {"演唱": "洛天依", "UP主": "作者", "额外": "不入SQL"},
        "type": "Song", "summary": ["歌曲简介"], "lyrics": lyrics, "spaced_lyrics": lyrics, **fields})


@pytest.fixture
def sync_wire(outputs, monkeypatch):
    state = SimpleNamespace(names=["甲", "乙", "丙"], calls=[], bad=set())
    def get(url, **kwargs):
        title = kwargs.get("params", {}).get("page") or parse_qs(urlsplit(url).query).get("page", [""])[0]
        state.calls.append(title)
        source = " ".join(f"[[{name}页面|{name}]]" for name in state.names) if title.startswith("Template:") else "== 简介 ==\n歌曲简介\n== 歌词 ==\n<poem>这是第一句完整歌词</poem>"
        response = requests.Response()
        response.status_code = 500 if title in state.bad else 200
        response._content = json.dumps({"parse": {"title": title, "wikitext": {"*": source}}}).encode()
        return response
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: get(url, **kw))
    state.config = {"song_database": {"db_folder": str(outputs.path / "db"), "db_file": "songs.db"},
                    "crawler": {"activated": True, "use_llm": False, "data_dir": str(outputs.path / "cache")}}
    return state


def test_hidden_list_links_cannot_steal_display_identity(outputs, sync_wire, monkeypatch):
    original = requests.get
    def get(url, **kwargs):
        response = original(url, **kwargs)
        if "Template:" in sync_wire.calls[-1]:
            response._content = json.dumps({"parse": {"wikitext": {"*": '<includeonly>[[错误页|甲]]</includeonly>[[甲页面|甲]]'}}}).encode()
        return response
    monkeypatch.setattr(requests, "get", get)
    assert daily.sync_daily_new_songs(sync_wire.config)["added"] == ["甲"]
    assert sync_wire.calls[-1] == "甲页面"


def test_structural_normalization_list_keeps_link_identity(outputs, sync_wire, monkeypatch):
    original = requests.get
    def get(url, **kwargs):
        response = original(url, **kwargs)
        if "Template:" in sync_wire.calls[-1]:
            source = '{{隱藏|內容=[[夢與樂頁#歌詞|夢與樂]]}}'
        else:
            source = '{{VOCALOID Songbox|演唱=樂師|UP主=龍作者|簡介=繁體介紹|歌詞=夢裡聽見樂聲}}'
        response._content = json.dumps({"parse": {"title": sync_wire.calls[-1], "wikitext": {"*": source}}}).encode()
        return response
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: get(url, **kw))
    assert daily.fetch_song_list_from_template(daily.TEMPLATE_URL) == ["夢與樂"]
    assert daily.sync_daily_new_songs(sync_wire.config)["added"] == ["夢與樂"]
    assert sync_wire.calls[-1] == "夢與樂頁"
    with database.get_song_session() as db:
        row = db.query(database.Song).one()
        assert (row.name, row.singers, row.uploader, row.lyrics) == ("夢與樂", "乐师", "龙作者", "梦里听见乐声")


def test_list_content_slots_share_target_display(outputs, sync_wire, monkeypatch):
    original = requests.get
    def get(url, **kwargs):
        response = original(url, **kwargs)
        if "Template:" in sync_wire.calls[-1]:
            source = '{{Hide|标题=[[错误页|甲♡]]|内容=<includeonly>[[隐藏页|甲♡]]</includeonly>{{Tabs|label1=[[标签页]]|text1=[[甲页面#歌词|甲♡*]] [[另一页|甲♡]]}}}}'
            response._content = json.dumps({"parse": {"wikitext": {"*": source}}}).encode()
        return response
    monkeypatch.setattr(requests, "get", get)
    assert daily.fetch_song_list_from_template(daily.TEMPLATE_URL) == ["甲♡"]
    assert daily.sync_daily_new_songs(sync_wire.config)["added"] == ["甲♡"]
    assert sync_wire.calls[-1] == "甲页面"
