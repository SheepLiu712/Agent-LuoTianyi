import json
from pathlib import Path

import pytest

from src.agent_runtime.character_registry import CharacterRegistry
from src.world.dynamic_interaction.task import DynamicInteractionTask


def test_dynamic_reply_polling_interval_allows_five_minute_reply_target():
    server_root = Path(__file__).resolve().parents[3]
    shipped_config = json.loads((server_root / "config" / "config.json").read_text(encoding="utf-8"))
    configured = shipped_config["world"]["dynamic_interaction"]["clock_config"]["params"]["interval_seconds"]
    default = DynamicInteractionTask().config["clock_config"]["params"]["interval_seconds"]
    assert 0 < configured <= 240
    assert 0 < default <= 240


def test_character_registry_rejects_missing_default_character():
    with pytest.raises(ValueError, match="Default character 'luotianyi' is not configured"):
        CharacterRegistry(
            {
                "characters": {
                    "miku": {
                        "display_name": "Hatsune Miku",
                        "enabled": True,
                    }
                }
            }
        )


def test_character_registry_rejects_disabled_default_character():
    with pytest.raises(ValueError, match="Default character 'luotianyi' must be enabled"):
        CharacterRegistry(
            {
                "characters": {
                    "luotianyi": {
                        "display_name": "Luo Tianyi",
                        "enabled": False,
                    },
                    "miku": {
                        "display_name": "Hatsune Miku",
                        "enabled": True,
                    },
                }
            }
        )


def test_character_registry_rejects_multiple_default_characters():
    with pytest.raises(ValueError, match="Multiple default characters"):
        CharacterRegistry(
            {
                "characters": {
                    "luotianyi": {"enabled": True, "default_target": True},
                    "miku": {"enabled": True, "default_target": True},
                }
            }
        )
