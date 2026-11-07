import pytest

from src.infrastructure.config.model_editor import apply_llm_config_draft, build_llm_config_view
from src.infrastructure.config.secrets import SecretStore
from src.infrastructure.config.store import ConfigStore
from src.infrastructure.config.validation import RuntimeConfigValidator


def test_audio_configuration_save_and_reload(tmp_path):
    config = {
        "llm_service": {
            "available_audio_models": {
                "audio": {
                    "api_type": "openai",
                    "model": "audio",
                    "api_key": "$AUDIO_KEY",
                    "base_url": "https://a.invalid",
                }
            },
            "client_model_types": [],
        },
        "agent_runtime": {
            "skills": {
                "audio_understanding": {
                    "audio_model_module": {"audio": {"name": "audio"}, "prompt_name": "audio_prompt"}
                }
            }
        },
        "call_transport": {"enabled": False, "other_setting": "preserved"},
    }
    draft = build_llm_config_view(config)
    draft["available_audio_models"]["audio"]["model"] = "new-audio"
    draft["client_model_types"].append(
        {
            "id": "audio_proxy",
            "name": "音频代理",
            "description": "",
            "model_kind": "audio",
            "requires_json": True,
            "requires_thinking": False,
        }
    )
    binding = draft["module_bindings"][0]
    assert binding["kind"] == "audio"
    assert binding["use_json"] is True
    binding.update(client_model_type="audio_proxy", params={"temperature": 0.2})
    draft["call_transport"].update(
        enabled=True,
        realtime_speech={
            "enabled": True,
            "model": "realtime",
            "api_key": "$REALTIME_KEY",
            "endpoint": "wss://realtime.invalid/ws",
            "write_queue_size": 16,
        },
    )
    updated = apply_llm_config_draft(config, draft)
    store = ConfigStore(tmp_path / "config.json", root_dir=tmp_path)
    store.write_raw(updated)
    assert build_llm_config_view(store.read_raw()) == draft
    module = updated["agent_runtime"]["skills"]["audio_understanding"]["audio_model_module"]
    assert module["audio"]["client_model_type"] == "audio_proxy"
    assert module["params"] == {"temperature": 0.2}
    assert module["use_json"] is True
    assert updated["call_transport"]["other_setting"] == "preserved"


@pytest.mark.parametrize(
    "patch",
    [
        {"endpoint": "https://invalid.example"},
        {"write_queue_size": 0},
        {"session_timeout_seconds": -1},
        {"api_key": "$UNRESOLVED_KEY"},
        {"enabled": "true"},
    ],
)
def test_realtime_invalid_configuration_blocks_save(tmp_path, patch):
    config = {
        "call_transport": {
            "enabled": True,
            "realtime_speech": {
                "enabled": True,
                "api_key": "test-key",
                "model": "realtime",
                "endpoint": "wss://realtime.invalid/ws",
                **patch,
            },
        }
    }
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=SecretStore(tmp_path / "secrets.json"))
    result = validator.validate(config)
    assert not result["core_ok"]
    assert any(
        item["name"] == "call_transport.realtime_speech" and item["status"] == "error" for item in result["items"]
    )


def test_realtime_valid_configuration_has_no_provider_error(tmp_path):
    config = {
        "call_transport": {
            "enabled": True,
            "realtime_speech": {
                "enabled": True,
                "api_key": "test-key",
                "model": "realtime",
                "workspace_id": "workspace",
            },
        }
    }
    validator = RuntimeConfigValidator(root_dir=tmp_path, secret_store=SecretStore(tmp_path / "secrets.json"))
    assert not any(item["name"] == "call_transport.realtime_speech" for item in validator.validate(config)["items"])
