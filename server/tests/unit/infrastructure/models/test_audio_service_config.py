"""Audio service configuration and Skill-owned prompt contract, without supplier calls."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent.context import AudioUnderstandingStatus
from src.agent.skills.cognitive.audio_understanding import AudioUnderstandingSkill
from src.domain.agent import MediaRef
from src.infrastructure.media import ResolvedMedia
from src.infrastructure.models.audio.interface import OpenAIAudioModelAPIInterface
from src.infrastructure.models.service import LLMService
from src.utils.helpers import load_config

SERVER_ROOT = Path(__file__).resolve().parents[4]
PROMPTS = SERVER_ROOT / "res/agent/prompts"


def config():
    return {
        "available_audio_models": {
            "custom": {
                "api_type": "openai",
                "model": "custom-audio",
                "base_url": "https://example.invalid/v1",
                "api_key": "test-only",
            }
        },
        "prompt_manager": {"template_dir": str(PROMPTS)},
    }


def module_config(prompt="audio_understanding_prompt"):
    return {"audio": {"name": "custom"}, "prompt_name": prompt, "use_json": True}


@pytest.mark.parametrize("settings", [{}, {"available_audio_models": {}}])
def test_absent_catalog_never_invents_a_provider(settings):
    service = LLMService(settings)
    assert service.get_audio_model_interface_info() == {}
    with pytest.raises(ValueError, match="音频模型接口未找到"):
        service.register_audio_model_module("audio", module_config())


@pytest.mark.parametrize("settings", [{}, {"audio": {}}, {"audio": {"name": "missing"}}])
def test_audio_module_requires_an_explicit_registered_model(settings):
    with pytest.raises(ValueError, match="音频模型接口未找到"):
        LLMService(config()).register_audio_model_module("audio", settings)


@pytest.mark.parametrize("prompt", [None, "", "missing"])
def test_audio_module_does_not_fall_back_when_prompt_is_missing(prompt):
    service = LLMService(config())
    with pytest.raises(ValueError, match="Prompt模板未找到"):
        service.register_audio_model_module("audio", module_config(prompt))
    assert service.audio_model_modules == {}


def test_audio_info_lists_configured_interfaces_without_credentials():
    info = LLMService(config()).get_audio_model_interface_info()
    assert info == {
        "custom": {
            "type": "OpenAIAudioModelAPIInterface",
            "model": "custom-audio",
            "base_url": "https://example.invalid/v1",
        }
    }
    assert "test-only" not in json.dumps(info)


@pytest.mark.parametrize("field", ["model", "base_url"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_provider_identity_must_be_explicit(field, value):
    settings = config()["available_audio_models"]["custom"]
    settings[field] = value
    with pytest.raises(ValueError, match=field):
        OpenAIAudioModelAPIInterface(settings)


def test_only_load_config_resolves_environment_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "environment-test-value")
    settings = config()
    settings["available_audio_models"]["custom"]["api_key"] = "$QWEN_API_KEY"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    loaded = load_config(str(path))
    monkeypatch.setenv("QWEN_API_KEY", "changed-after-load")
    service = LLMService(loaded)
    assert service.audio_model_interfaces["custom"].api_key == "environment-test-value"
    unresolved = LLMService(settings).audio_model_interfaces["custom"]
    assert unresolved.api_key == "$QWEN_API_KEY"
    with pytest.raises(RuntimeError, match="API Key"):
        unresolved._ensure_client()
    settings["available_audio_models"]["custom"].pop("api_key")
    missing = LLMService(settings).audio_model_interfaces["custom"]
    assert missing.api_key == ""
    with pytest.raises(RuntimeError, match="API Key"):
        missing._ensure_client()


@pytest.mark.asyncio
async def test_skill_registers_real_module_with_its_resource_and_parses_the_response():
    service = LLMService(config())
    model = service.audio_model_interfaces["custom"]
    model.generate_response = AsyncMock(
        return_value={
            "content": json.dumps({"transcript": "你好", "emotion": None, "sound_description": None}),
            "usage": {},
            "response_time_s": 0.1,
        }
    )
    resolver = SimpleNamespace(resolve=lambda *args, **kwargs: ResolvedMedia(b"audio", "audio/mp4"))
    skill = AudioUnderstandingSkill({"audio_model_module": module_config()}, resolver, service)
    _, status, result = await skill.understand(MediaRef(media_id="audio"), owner_user_id="owner")
    assert status is AudioUnderstandingStatus.UNDERSTOOD
    assert result.transcript == "你好"
    prompt = model.generate_response.call_args.args[0]
    for field in ("transcript", "emotion", "sound_description"):
        assert field in prompt
    assert "逐字转写" in prompt
    assert model.generate_response.call_args.kwargs["response_format"] == {"type": "json_object"}
    assert service.audio_model_modules["audio_understanding"].prompt_template.name == "audio_understanding_prompt"


@pytest.mark.asyncio
async def test_other_audio_tasks_can_use_unrelated_templates():
    service = LLMService(config())
    service.prompt_manager.add_template_from_str("music", "Classify music genre: {{ label }}")
    model = service.audio_model_interfaces["custom"]
    model.generate_response = AsyncMock(return_value={"content": "rock", "usage": {}})
    settings = module_config("music") | {"use_json": False}
    module = service.register_audio_model_module("music", settings)
    await module.generate_response("data:audio/mp4;base64,AA==", label="example")
    assert model.generate_response.call_args.args == ("Classify music genre: example",)
    assert "response_format" not in model.generate_response.call_args.kwargs


@pytest.mark.parametrize("filename", ["config.json", "config.json.template"])
def test_shipped_config_explicitly_selects_audio_model_and_prompt(filename):
    settings = json.loads((SERVER_ROOT / "config" / filename).read_text(encoding="utf-8"))
    catalog = settings["llm_service"]["available_audio_models"]
    module = settings["agent_runtime"]["skills"]["audio_understanding"]["audio_model_module"]
    assert module["audio"]["name"] in catalog
    assert catalog[module["audio"]["name"]]["model"] == "qwen3.8-omni-flash"
    assert module["prompt_name"] == "audio_understanding_prompt"
    assert module["use_json"] is True
