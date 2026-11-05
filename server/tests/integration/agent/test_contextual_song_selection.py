"""情绪选歌经过真实处理器、歌曲资源和标签模型接口后形成演唱行动。"""

import json
import wave
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.handlers.reply_skills import ReplySkills
from src.agent.skills.expression.singing import SingingSkill
from src.world.learn_sing_songs.task import LearnSingSongsTask
from tests.integration.agent.test_topic_reply_pipeline import pipeline, run_handler


class EmotionModels:
    def __init__(self):
        self.calls = []

    def register_llm_module(self, name, config):
        assert name == "song_emotion_tagger"
        return self

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return '{"emotion_tags":["积极"]}'


def write_song(root, name, tags):
    folder = root / "songs" / name
    folder.mkdir(parents=True)
    # 使用真实 WAV 内容验证可播放时长；资源加载器沿用既有 mp3 文件命名约定。
    with wave.open(str(folder / f"{name}.mp3"), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 16000)
    (folder / f"{name}.lrc").write_text("[00:00.00]测试歌词", encoding="utf-8")
    config = folder / f"{name}.json"
    config.write_text(
        json.dumps(
            {
                "title": name,
                "emotion_tags": tags,
                "segments": [{"description": "副歌", "start_time": 0, "end_time": 1, "lyrics": []}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return config


def singing(root, models):
    return SingingSkill(
        {
            "characters": {"luotianyi": {"resource_path": str(root)}},
            "song_emotion_tagger": {"llm": {"name": "emotion"}},
        },
        llm_service=models,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "memory", "proactive"])
async def test_context_emotion_limits_the_song_chosen_by_the_reply_handler(tmp_path, monkeypatch, mode):
    write_song(tmp_path, "冷清歌", ["伤感"])
    write_song(tmp_path, "庆祝歌", ["积极"])
    models = EmotionModels()
    songs = singing(tmp_path, models)
    # 没有情绪筛选时固定先选伤感歌曲，防止纯随机碰巧选对而掩盖断链。
    monkeypatch.setattr(
        "src.agent.skills.expression.singing.manager.random.shuffle",
        lambda names: names.sort(key=lambda name: name != "冷清歌"),
    )
    skills, _, calls = pipeline(attempts=("random_song",), song_id="庆祝歌")
    skills = ReplySkills(skills.topic_extraction, skills.retrieval, songs, skills.reply)

    report, actions, _ = await run_handler(skills, mode)

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    selected = [(action.song_id, action.segment_id) for action in actions if isinstance(action, d.Sing)]
    assert selected == [("庆祝歌", "副歌")]
    assert len(models.calls) == 1
    assert models.calls[0]["mode"] == "infer_target"
    assert "以前讨论过歌曲" in models.calls[0]["content"]
    assert f"当前话题：{calls['extract']['message_content']}" in models.calls[0]["content"]


@pytest.mark.asyncio
async def test_explicit_song_keeps_user_choice_without_emotion_inference(tmp_path):
    write_song(tmp_path, "冷清歌", ["伤感"])
    models = EmotionModels()
    skills, _, _ = pipeline(attempts=("冷清歌",), song_id="冷清歌")
    skills = ReplySkills(skills.topic_extraction, skills.retrieval, singing(tmp_path, models), skills.reply)

    report, actions, _ = await run_handler(skills)

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert [action.song_id for action in actions if isinstance(action, d.Sing)] == ["冷清歌"]
    assert models.calls == []


@pytest.mark.asyncio
async def test_each_learned_song_is_tagged_before_its_fact_and_tags_survive_reload(tmp_path):
    configs = {name: write_song(tmp_path, name, []) for name in ("新歌甲", "新歌乙")}
    models = EmotionModels()
    songs = singing(tmp_path, models)
    world_resources = songs.learning_tasks().world_resources
    facts = []

    async def submit(fact):
        assert json.loads(configs[fact.song_id].read_text(encoding="utf-8"))["emotion_tags"] == ["积极"]
        facts.append(fact)
        return True

    async def get_world_stage(character_id):
        assert character_id == "luotianyi"
        return SimpleNamespace(fact_sink=SimpleNamespace(submit=submit))

    task = LearnSingSongsTask({}, character_id="luotianyi", singing_backend=world_resources)
    task.auto_song_learner = SimpleNamespace(
        check_qq_credential=lambda: True,
        try_learn_pending=lambda: SimpleNamespace(learned=list(configs), abandoned=[], awaiting=[]),
    )
    task.server_runtime = SimpleNamespace(
        get_world_stage=get_world_stage, agent_runtime=SimpleNamespace(default_character_id="luotianyi")
    )

    result = await task.run_once()

    assert result.ok and result.data["submitted_count"] == 2
    assert [fact.song_id for fact in facts] == list(configs)
    assert [call["mode"] for call in models.calls] == ["tag_song", "tag_song"]
    world_resources.reload_songs("luotianyi")
    for name in configs:
        metadata = world_resources.singing_manager["luotianyi"].get_song_metadata(name)
        assert metadata.emotion_tags == ["积极"]
