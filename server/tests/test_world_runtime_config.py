import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent_runtime.character_registry import CharacterRegistry


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
