"""管理组件DTO是现有配置的投影，不引入新的持久节点。"""

from copy import deepcopy

from src.infrastructure.config.model_editor import apply_llm_config_draft, build_llm_config_view


def test_component_startup_view_defaults_to_full_capabilities_without_mutation():
    config = {}

    view = build_llm_config_view(config)

    assert view["component_startup"] == {"speaking_enabled": True, "vector_store_enabled": True}
    assert config == {}


def test_component_patch_maps_only_supplied_leaf_and_preserves_raw_configuration():
    config = {
        "llm_service": {"available_llms": {"main": {"api_key": "$UNCHANGED", "model": "existing"}}},
        "agent_runtime": {
            "skills": {"speaking": {"characters": {"luotianyi": {"reference_audio_dir": "retained"}}}},
            "vector_store": {"enabled": False, "embedding_model": {"api_key": "$EMBEDDING"}},
        },
        "world": {"citywalk": {"enabled": False}},
    }
    before = deepcopy(config)
    expected = deepcopy(config)
    expected["agent_runtime"]["skills"]["speaking"]["enabled"] = False

    result = apply_llm_config_draft(config, {"component_startup": {"speaking_enabled": False}})

    assert result == expected
    assert config == before
    assert "component_startup" not in result
    assert build_llm_config_view(result)["component_startup"] == {
        "speaking_enabled": False,
        "vector_store_enabled": False,
    }
    assert apply_llm_config_draft(result, {}) == result
    assert apply_llm_config_draft(result, {"component_startup": {}}) == result
    both = apply_llm_config_draft(
        result, {"component_startup": {"speaking_enabled": True, "vector_store_enabled": True}}
    )
    assert both["agent_runtime"]["vector_store"] == {
        "enabled": True,
        "embedding_model": {"api_key": "$EMBEDDING"},
    }
    assert both["agent_runtime"]["skills"]["speaking"]["enabled"] is True
