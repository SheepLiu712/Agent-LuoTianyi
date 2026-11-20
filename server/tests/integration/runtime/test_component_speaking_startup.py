"""通过公开配置与真实共享技能装配验证语音开关，不替换技能选择接缝。"""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.skills import SharedSkills
from src.agent.skills.resources import SkillResources
from src.domain.character import CharacterProfile
from src.infrastructure.config.skills import SkillsConfig
from src.infrastructure.persistence.database.services.memory_store import MemoryStore


def runtime_config(tmp_path):
    persona = tmp_path / "persona.json"
    persona.write_text(
        json.dumps({"character_name": "测试角色", "character_persona": "测试人格", "speaking_style": "自然"}),
        encoding="utf-8",
    )
    tones = tmp_path / "tones.json"
    tones.write_text("{}", encoding="utf-8")
    module = {"llm_module": {"llm": {"name": "test"}}}
    return {
        "skills": {
            "reply": module,
            "memory_write": module,
            "cognitive_maintenance": {"user_profile": module},
            "speaking": {"enabled": False},
            "singing": {"characters": {"luotianyi": {"resource_path": str(tmp_path / "songs")}}},
            "jargon_recognition": {
                "song_entity_linker": {
                    "songname_file": str(tmp_path / "song_names.txt"),
                    "lyric_file": str(tmp_path / "lyrics.txt"),
                }
            },
        }
    }, CharacterProfile(
        character_id="luotianyi",
        display_name="测试角色",
        memory_namespace="luotianyi",
        static_variables_file=str(persona),
        llm_tone_mapping_file=str(tones),
    )


@pytest.mark.parametrize("value", [0, 1, None, "false", [], {}])
def test_runtime_skill_config_rejects_non_boolean_speaking_enabled(tmp_path, value):
    config, _ = runtime_config(tmp_path)
    config["skills"]["speaking"]["enabled"] = value

    with pytest.raises(TypeError, match=r"agent_runtime.skills.speaking.enabled"):
        SkillsConfig.from_runtime(config)


@pytest.mark.asyncio
async def test_shared_skills_disabled_speaking_never_constructs_tts_resources(tmp_path, monkeypatch):
    from src.agent.skills.expression.speaking import skill as speaking_module

    def forbidden(*args, **kwargs):
        pytest.fail("disabled shared speaking must not construct a TTS backend or stream")

    monkeypatch.setattr(speaking_module, "SpeechBackend", forbidden)
    monkeypatch.setattr(speaking_module, "AsyncTTS", forbidden)
    config, profile = runtime_config(tmp_path)
    assert config["skills"]["speaking"] == {"enabled": False}
    assert not (tmp_path / "tts").exists()
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.sqlite'}")
    sessions = sessionmaker(bind=engine)
    database = SimpleNamespace(memory_store=MemoryStore({}, sessions, redis_buffer=None))
    # 模型端口仅注册测试模型；没有替换 SharedSkills、AgentMemory 或 SpeakingSkill。
    models = SimpleNamespace(
        register_llm_module=lambda *args, **kwargs: SimpleNamespace(
            prompt_template=SimpleNamespace(get_variables=list),
        )
    )
    skills = None
    try:
        skills = SharedSkills(
            SkillsConfig.from_runtime(config),
            resources=SkillResources(
                llm_service=models,
                database=database,
                vector_store=object(),
                media_resolver=None,
                characters={"luotianyi": profile},
            ),
        )
        skills.ensure_dependencies()
        assert skills.speaking.enabled is False
        assert not skills.speaking.supports_call_audio("luotianyi")
        await skills.stop()
        await skills.stop()
        skills.abort_initialization()
    finally:
        if skills is not None:
            await skills.stop()
        engine.dispose()
