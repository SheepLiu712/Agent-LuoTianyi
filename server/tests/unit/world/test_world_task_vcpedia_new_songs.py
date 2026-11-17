import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.domain.agent as d
import src.world.get_new_songs.daily_new_song_fetcher as fetcher_module
import src.world.get_new_songs.task as task_module
from src.infrastructure.persistence import (
    Song,
    get_song_session,
    init_song_db,
)
from src.world.get_new_songs.daily_new_song_fetcher import (
    NewSongCandidate,
    collect_new_song_candidates,
)
from src.world.get_new_songs.task import VCPediaNewSongTask


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


def server_runtime(accept=True, *, llm_service=None, character_id="luotianyi"):
    stage = SimpleNamespace(fact_sink=FakeFactSink(accept))
    asked = []

    async def get_world_stage(character_id=None, world_id=None):
        asked.append(character_id)
        return stage

    runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(default_character_id=character_id),
        get_world_stage=get_world_stage,
        llm_service=llm_service,
    )
    return runtime, stage, asked


class FakeLLMService:
    def __init__(self):
        self.calls = []

    def register_llm_module(self, name, config):
        self.calls.append((name, config))
        return name + "-module"


@pytest.mark.parametrize("switch", [{}, {"use_llm": True}])
def test_vcpedia_initialize_registers_separate_models_by_default_and_when_enabled(switch):
    crawler = {
        **switch, "llm_module": {"prompt_name": "summary"},
        "extraction_llm_module": {"prompt_name": "extract"},
    }
    service = FakeLLMService()
    task = VCPediaNewSongTask({"crawler": crawler})

    task.initialize(SimpleNamespace(llm_service=service))

    assert task.llm_module == "song_knowledge_crawler-module"
    assert task.extraction_llm_module == "song_knowledge_extractor-module"
    assert service.calls == [
        ("song_knowledge_crawler", crawler["llm_module"]),
        ("song_knowledge_extractor", crawler["extraction_llm_module"]),
    ]


def test_vcpedia_initialize_skips_invalid_models_when_llm_disabled():
    crawler = {
        "use_llm": False, "llm_module": {"llm": {"name": "invalid-provider"}},
        "extraction_llm_module": {"llm": {"name": "also-invalid"}},
    }
    task = VCPediaNewSongTask({"crawler": crawler})

    # 没有 register_llm_module 方法；关闭时不得尝试注册或验证配置。
    task.initialize(SimpleNamespace(llm_service=object()))

    assert task.llm_module is None
    assert task.extraction_llm_module is None


@pytest.mark.parametrize("config_key", ["llm_module", "extraction_llm_module"])
def test_enabled_invalid_model_error_names_exact_crawler_location(config_key):
    def register(name, config):
        raise ValueError("LLM接口未找到: invalid-provider")

    task = VCPediaNewSongTask({"crawler": {config_key: {"llm": {"name": "invalid-provider"}}}})
    with pytest.raises(ValueError) as caught:
        task.initialize(SimpleNamespace(llm_service=SimpleNamespace(register_llm_module=register)))

    assert f"world.song_knowledge.crawler.{config_key}" in str(caught.value)
    assert "invalid-provider" in str(caught.value)
    assert isinstance(caught.value.__cause__, ValueError)


def test_initialize_does_not_substitute_summary_module_for_missing_extractor():
    task = VCPediaNewSongTask({"crawler": {"llm_module": {"prompt_name": "summary"}}})
    service = FakeLLMService()

    task.initialize(SimpleNamespace(llm_service=service))

    assert task.llm_module == "song_knowledge_crawler-module"
    assert task.extraction_llm_module is None
    assert len(service.calls) == 1


def test_missing_llm_service_keeps_models_optional():
    task = VCPediaNewSongTask({"crawler": {
        "llm_module": {"prompt_name": "summary"}, "extraction_llm_module": {"prompt_name": "extract"},
    }})
    runtime, stage, _ = server_runtime(llm_service=None)

    task.initialize(runtime)
    task.ensure_dependencies()

    assert task.llm_module is None and task.extraction_llm_module is None
    assert asyncio.run(task._submit_candidates([candidate()])) == (1, 0)
    assert len(stage.fact_sink.facts) == 1


def test_reinitialize_with_llm_disabled_clears_both_previous_dependencies():
    task = VCPediaNewSongTask({"crawler": {
        "llm_module": {"prompt_name": "summary"}, "extraction_llm_module": {"prompt_name": "extract"},
    }})
    service = FakeLLMService()
    task.initialize(SimpleNamespace(llm_service=service))
    task.config["crawler"]["use_llm"] = False

    task.initialize(SimpleNamespace(llm_service=object()))

    assert len(service.calls) == 2
    assert task.llm_module is None and task.extraction_llm_module is None


def test_vcpedia_run_once_submits_candidates_as_world_facts(monkeypatch):
    calls = {}

    def collect(config, llm_module=None, *, extraction_llm_module=None):
        calls["config"] = config
        calls["llm_module"] = llm_module
        calls["extraction_llm_module"] = extraction_llm_module
        return {"discovered": [candidate("A"), candidate("B")], "skipped_existing": ["C"], "fetch_failed": ["D"]}

    monkeypatch.setattr(task_module, "collect_new_song_candidates", collect)
    runtime, stage, asked = server_runtime(llm_service=FakeLLMService())
    task = VCPediaNewSongTask({"crawler": {
        "llm_module": {"prompt_name": "summary"}, "extraction_llm_module": {"prompt_name": "extract"},
    }})
    task.initialize(runtime)
    task.ensure_dependencies()

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["discovered_count"] == 2
    assert result.data["submitted_count"] == 2
    assert result.data["rejected_count"] == 0
    assert result.data["skipped_existing_count"] == 1
    assert result.data["fetch_failed_count"] == 1
    assert calls["llm_module"] == "song_knowledge_crawler-module"
    assert calls["extraction_llm_module"] == "song_knowledge_extractor-module"
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
        lambda config, llm_module=None, *, extraction_llm_module=None: {
            "discovered": [candidate("A")], "skipped_existing": [], "fetch_failed": []
        },
    )
    runtime, stage, _ = server_runtime(accept=False)
    task = VCPediaNewSongTask({"crawler": {}})
    task.initialize(runtime)

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["submitted_count"] == 0
    assert result.data["rejected_count"] == 1
    assert len(stage.fact_sink.facts) == 1


def test_vcpedia_run_once_returns_failure_on_exception(monkeypatch):
    def collect(config, llm_module=None, *, extraction_llm_module=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_module, "collect_new_song_candidates", collect)
    task = VCPediaNewSongTask({})
    task.initialize(server_runtime()[0])

    result = asyncio.run(task.run_once())

    assert result.ok is False
    assert "boom" in result.message


def test_initialize_captures_required_interfaces_without_runtime_attribute():
    """只验证不直接保存 runtime 属性；绑定入口仍可能间接持有 runtime。"""
    runtime, stage, asked = server_runtime(character_id="other-character")
    task = VCPediaNewSongTask({"crawler": {"use_llm": False}})
    with pytest.raises(RuntimeError, match="initialize"):
        task.ensure_dependencies()
    task.initialize(runtime)

    assert "server_runtime" not in vars(task)
    assert "_llm_service" not in vars(task)
    assert all(value is not runtime for value in vars(task).values())
    del runtime.agent_runtime
    del runtime.get_world_stage
    del runtime.llm_service
    task.ensure_dependencies()

    submitted, rejected = asyncio.run(task._submit_candidates([candidate()]))

    assert (submitted, rejected) == (1, 0)
    assert asked == ["other-character"]
    assert stage.fact_sink.facts[0].target_character_ids == ("other-character",)


def test_initialized_task_without_stage_counts_unsubmitted_candidates(monkeypatch):
    monkeypatch.setattr(task_module, "collect_new_song_candidates", lambda *a, **k: {
        "discovered": [candidate()], "skipped_existing": [], "fetch_failed": [],
    })
    task = VCPediaNewSongTask({"crawler": {"use_llm": False}})
    task.initialize(SimpleNamespace())
    task.ensure_dependencies()

    result = asyncio.run(task.run_once())

    assert result.ok is True
    assert result.data["submitted_count"] == 0
    assert result.data["rejected_count"] == 1


def test_template_declares_enabled_stages_and_a_resolvable_extractor(monkeypatch):
    from src.infrastructure.models.service import LLMService

    server_root = Path(__file__).resolve().parents[3]
    config = json.loads((server_root / "config/config.json.template").read_text(encoding="utf-8"))
    crawler = config["world"]["song_knowledge"]["crawler"]
    provider = config["llm_service"]["available_llms"]["dsv4-flash"]
    assert crawler["merge_rendered_fragments"] is True and crawler["use_llm"] is True
    assert provider["model"] == "deepseek-v4-flash-0731"
    assert provider["api_type"] == "openai"
    assert provider["api_key"] == "$QWEN_API_KEY"
    assert provider["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert provider["can_enable_thinking"] is True and provider["can_use_json"] is True
    assert crawler["extraction_llm_module"]["llm"] == {
        "name": "dsv4-flash", "enable_thinking": False, "use_json": True,
    }
    # 真实服务注册、离线接口与仓库提示词，不读取真实配置/Key，不调用供应商。
    monkeypatch.setattr(LLMService, "_create_llm_interfaces", lambda self: {
        name: SimpleNamespace(default_parameters={}) for name in self.llms_config
    })
    monkeypatch.setattr(LLMService, "_create_vlm_interfaces", lambda self: {})
    service_config = config["llm_service"]
    service_config["prompt_manager"]["template_dir"] = str(server_root / "res/agent/prompts")
    task = VCPediaNewSongTask(config["world"]["song_knowledge"])

    task.initialize(SimpleNamespace(llm_service=LLMService(service_config)))

    assert task.llm_module.name == "song_knowledge_crawler"
    assert task.extraction_llm_module.name == "song_knowledge_extractor"
    assert task.extraction_llm_module.use_json is True
    assert task.extraction_llm_module.enable_thinking is False


@pytest.mark.parametrize(
    "config,location",
    [({}, "song_database"), ({"song_database": {"db_file": "unused"}}, "crawler")],
)
def test_missing_collection_config_names_current_world_location(config, location):
    with pytest.raises(ValueError, match="world.song_knowledge." + location):
        collect_new_song_candidates(config)


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
        def __init__(self, config, llm_module=None, *, extraction_llm_module=None):
            pass

        def fetch_entity_description(self, song_name):
            if song_name == "新歌":
                return {"infobox": {"UP主": "UP主", "演唱": "歌手A、歌手B"}, "short_summary": "介绍",
                        "lyrics": "歌词正文", "spaced_lyrics": "今天天气真不错 明天也要努力呀"}
            return None

    monkeypatch.setattr(
        fetcher_module, "fetch_song_list_from_template",
        lambda url, timeout=20: ["新歌", "旧歌", "坏歌"])
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
