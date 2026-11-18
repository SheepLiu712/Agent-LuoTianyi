"""开发者可见的配置错误、模型选择及角色隔离。"""

import asyncio
import json
from contextlib import aclosing
from types import SimpleNamespace

import pytest

from src.agent.context import UserContextSnapshot
from src.agent.skills.cognitive.reply import ReplySkill
from src.agent_runtime.agent_runtime import AgentRuntime
from src.domain.character import CharacterProfile
from src.infrastructure.config.model_editor import apply_llm_config_draft, build_llm_config_view
from src.infrastructure.config.skills import SkillsConfig


class ModelService:
    def register_llm_module(self, name, config, *, stream=False):
        assert stream is True

        async def generate_response(*, on_delta=None, **kwargs):
            await asyncio.sleep(0)
            text = f"[中性]{config['llm']['name']}：{kwargs['character_name']}，{kwargs['reply_topic']}。"
            if on_delta is not None:
                await on_delta(text)
            return text

        return SimpleNamespace(
            stream=stream,
            generate_response=generate_response,
            prompt_template=SimpleNamespace(get_variables=list),
        )


async def test_two_characters_use_their_own_model_and_persona(tmp_path):
    characters = {}
    tones = tmp_path / "tones.json"
    tones.write_text(json.dumps({"llm_tone_to_tts_tone": {"中性": "normal"}}), encoding="utf-8")
    for key in ("甲", "乙"):
        persona = tmp_path / f"{key}.json"
        persona.write_text(
            json.dumps({"character_name": key, "character_persona": f"{key}的人设", "speaking_style": "自然"}),
            encoding="utf-8",
        )
        characters[key] = CharacterProfile(
            character_id=key,
            display_name=key,
            memory_namespace=key,
            static_variables_file=str(persona),
            llm_tone_mapping_file=str(tones),
        )
    skill = ReplySkill(
        {"llm_module": {"llm": {"name": "模型甲"}}, "characters": {"乙": {"llm_module": {"llm": {"name": "模型乙"}}}}},
        llm_service=ModelService(),
        characters=characters,
    )

    async def collect(key):
        async with aclosing(skill.generate(key, reply_topic=key, user_context=UserContextSnapshot())) as stream:
            return "".join([draft.content async for draft in stream])

    assert await asyncio.gather(collect("甲"), collect("乙")) == ["模型甲：甲，甲。", "模型乙：乙，乙。"]


@pytest.mark.parametrize("old_node", ["agent", "prepared_speech", "reply_composition"])
def test_old_runtime_nodes_report_migration(old_node):
    with pytest.raises(ValueError, match=f"agent_runtime.{old_node}.*迁移"):
        SkillsConfig.from_runtime({old_node: {}})


def test_missing_reply_model_fails_before_serving_chat(runtime_dependencies):
    kwargs, store = runtime_dependencies
    kwargs["config"]["skills"]["reply"] = {}
    with pytest.raises(ValueError, match=r"agent_runtime.skills.reply.llm_module.llm.name"):
        AgentRuntime(**kwargs)
    assert store.close_calls == 1


def test_old_character_touch_policy_cannot_be_silently_ignored(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    kwargs["config"]["character_registry"]["characters"]["luotianyi"]["reflex"] = {
        "touch": {"fast_reply": {"resource_names": ["touch_1"]}}
    }
    with pytest.raises(ValueError, match=r"characters.luotianyi.reflex.touch.*迁移"):
        AgentRuntime(**kwargs)


def test_removed_call_decision_configuration_is_not_silently_ignored(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    kwargs["config"]["skills"]["call_recall"] = {}
    with pytest.raises(ValueError, match=r"skills.call_recall.*已删除"):
        AgentRuntime(**kwargs)


def test_admin_model_edit_preserves_other_skill_configuration():
    config = {
        "agent_runtime": {
            "skills": {
                "reply": {"llm_module": {"llm": {"name": "旧模型"}}},
                "memory_write": {"llm_module": {"llm": {"name": "记忆模型"}}, "dedup_threshold": 0.8},
            }
        }
    }
    view = build_llm_config_view(config)
    for binding in view["module_bindings"]:
        if binding["path"] == "agent_runtime.skills.reply.llm_module":
            binding["interface_name"] = "新模型"
    updated = apply_llm_config_draft(config, view)
    skills = updated["agent_runtime"]["skills"]
    assert skills["reply"]["llm_module"]["llm"]["name"] == "新模型"
    assert skills["memory_write"]["llm_module"]["llm"]["name"] == "记忆模型"
    assert skills["memory_write"]["dedup_threshold"] == 0.8


def test_old_terminology_configuration_reports_migration(runtime_dependencies):
    kwargs, _ = runtime_dependencies
    kwargs["config"]["skills"]["text_preprocessing"] = {}
    with pytest.raises(ValueError, match=r"skills.text_preprocessing.*jargon_recognition"):
        AgentRuntime(**kwargs)


@pytest.mark.parametrize(
    "obsolete", ["response_composition", "memory", "main_chat", "preprocessing", "diary_writing", "date_detector"]
)
def test_removed_skill_nodes_cannot_silently_start(runtime_dependencies, obsolete):
    kwargs, _ = runtime_dependencies
    kwargs["config"]["skills"][obsolete] = {}
    with pytest.raises(ValueError, match=rf"agent_runtime.skills.{obsolete}.*(删除|迁移)"):
        AgentRuntime(**kwargs)
