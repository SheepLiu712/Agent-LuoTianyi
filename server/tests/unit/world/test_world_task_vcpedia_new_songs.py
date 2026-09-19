import asyncio
from types import SimpleNamespace

import src.domain.agent as d
import src.world.get_new_songs.daily_new_song_fetcher as fetcher_module
import src.world.get_new_songs.task as task_module
from src.world.get_new_songs.daily_new_song_fetcher import (
    NewSongCandidate,
    collect_new_song_candidates,
)
from src.world.get_new_songs.task import VCPediaNewSongTask
from src.infrastructure.song_knowledge.database import (
    Song,
    get_song_session,
    init_song_db,
)


def candidate(song_name="新歌", introduction="一首歌的介绍"):
    return NewSongCandidate(
        song_name=song_name, safe_name=song_name, uploader="UP主", singers=("歌手A", "歌手B"),
        introduction=introduction, lyrics="歌词正文", lyric_keywords=("一句歌词",),
    )


class FakeFactSink:
    def __init__(self, accept=True):
        self.facts = []
        self.accept = accept

    async def submit(self, fact):
        self.facts.append(fact)
        return self.accept


def system_runtime(accept=True):
    stage = SimpleNamespace(fact_sink=FakeFactSink(accept))
    asked = []

    async def get_world_stage(character_id=None, world_id=None):
        asked.append(character_id)
        return stage

    runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        get_world_stage=get_world_stage,
    )
    return runtime, stage, asked


def test_vcpedia_initialize_registers_llm_when_enabled():
    class FakeLLMService:
        def __init__(self):
            self.calls = []

        def register_llm_module(self, name, config):
            self.calls.append((name, config))
            return "llm-module"

    cfg = {"crawler": {"use_llm": True, "llm_module": {"prompt_name": "p"}}}
    service = FakeLLMService()
    task = VCPediaNewSongTask(cfg)

    task.initialize(SimpleNamespace(llm_service=service))

    assert task.llm_module == "llm-module"
    assert service.calls == [("song_knowledge_crawler", {"prompt_name": "p"})]


def test_vcpedia_initialize_skips_when_llm_disabled():
    task = VCPediaNewSongTask({"crawler": {"use_llm": False}})

    task.initialize(SimpleNamespace(llm_service=object()))

    assert task.llm_module is None


def test_vcpedia_run_once_submits_candidates_as_world_facts(monkeypatch):
    calls = {}

    def collect(config, llm_module=None):
        calls["config"] = config
        calls["llm_module"] = llm_module
        return {"discovered": [candidate("A"), candidate("B")], "skipped_existing": ["C"], "fetch_failed": ["D"]}

    monkeypatch.setattr(task_module, "collect_new_song_candidates", collect)
    runtime, stage, asked = system_runtime()
    task = VCPediaNewSongTask({"crawler": {}})
    task.system_runtime = runtime
    task.llm_module = "llm"

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["discovered_count"] == 2
    assert result.data["submitted_count"] == 2
    assert result.data["rejected_count"] == 0
    assert result.data["skipped_existing_count"] == 1
    assert result.data["fetch_failed_count"] == 1
    assert calls["llm_module"] == "llm"
    assert asked == ["luotianyi"]
    first = stage.fact_sink.facts[0]
    assert isinstance(first, d.SongKnowledgeDiscovered)
    assert first.source is d.StimulusSource.WORLD
    assert first.user_id is None and first.target_character_ids == ("luotianyi",)
    assert first.source_ref == d.SourceRef(source_id="vcpedia")
    assert first.external_song_id == "A"
    assert first.candidate.song_name == "A"
    assert first.candidate.singers == ("歌手A", "歌手B")
    assert isinstance(first.revision, int) and first.revision >= 0
    assert stage.fact_sink.facts[1].external_song_id == "B"


def test_vcpedia_run_once_counts_rejected_candidates(monkeypatch):
    monkeypatch.setattr(
        task_module, "collect_new_song_candidates",
        lambda config, llm_module=None: {"discovered": [candidate("A")], "skipped_existing": [], "fetch_failed": []},
    )
    runtime, stage, _ = system_runtime(accept=False)
    task = VCPediaNewSongTask({"crawler": {}})
    task.system_runtime = runtime

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["submitted_count"] == 0
    assert result.data["rejected_count"] == 1
    assert len(stage.fact_sink.facts) == 1


def test_vcpedia_run_once_returns_failure_on_exception(monkeypatch):
    def collect(config, llm_module=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_module, "collect_new_song_candidates", collect)
    task = VCPediaNewSongTask({})

    result = asyncio.run(task.run_once())

    assert result.ok is False
    assert "boom" in result.message


def _seed_existing_song(db_folder: str, song_name: str) -> None:
    init_song_db({"db_folder": db_folder, "db_file": "knowledge_db.db"})
    session = get_song_session()
    try:
        session.add(Song(name=song_name, safe_name=song_name, uploader="旧", singers="旧",
                         introduction="旧介绍", lyrics="旧歌词"))
        session.commit()
    finally:
        session.close()


def test_collect_new_song_candidates_skips_existing_and_writes_no_knowledge(monkeypatch, tmp_path):
    db_folder = tmp_path / "knowledge"
    _seed_existing_song(str(db_folder), "旧歌")

    class FakeFetcher:
        def __init__(self, config, llm_module=None):
            pass

        def fetch_entity_description(self, song_name):
            if song_name == "新歌":
                return {"infobox": {"UP主": "UP主", "演唱": "歌手A、歌手B"}, "short_summary": "介绍",
                        "lyrics": "歌词正文", "spaced_lyrics": "今天天气真不错 明天也要努力呀"}
            return None

    monkeypatch.setattr(fetcher_module, "fetch_song_list_from_template", lambda url, timeout=20: ["新歌", "旧歌", "坏歌"])
    monkeypatch.setattr(fetcher_module, "VCPediaFetcher", FakeFetcher)
    monkeypatch.setattr(fetcher_module.time, "sleep", lambda _: None)

    outcome = collect_new_song_candidates(
        {"song_database": {"db_folder": str(db_folder), "db_file": "knowledge_db.db"}, "crawler": {"activated": True}}
    )

    assert [item.song_name for item in outcome["discovered"]] == ["新歌"]
    assert outcome["skipped_existing"] == ["旧歌"]
    assert outcome["fetch_failed"] == ["坏歌"]
    assert outcome["discovered"][0].singers == ("歌手A", "歌手B")
    assert outcome["discovered"][0].lyric_keywords == ("今天天气真不错", "明天也要努力呀")

    session = get_song_session()
    try:
        assert session.query(Song).filter(Song.name == "新歌").first() is None
        assert session.query(Song).filter(Song.name == "旧歌").first() is not None
    finally:
        session.close()
    assert not (db_folder / "song_name_keywords.txt").exists()
    assert not (db_folder / "song_lyric_keywords.txt").exists()
