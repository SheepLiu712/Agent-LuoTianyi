import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import MainChat


def load_static_variables(path: Path) -> MainChat:
    main_chat = MainChat.__new__(MainChat)
    main_chat.character_profile = SimpleNamespace(
        character_id="test-character",
        static_variables_file=str(path),
    )
    main_chat._init_static_variables_sync()
    return main_chat


def test_character_static_variables_file_must_exist(tmp_path):
    missing_path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match="test-character"):
        load_static_variables(missing_path)


def test_character_static_variables_must_be_valid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="contains invalid JSON"):
        load_static_variables(path)


@pytest.mark.parametrize(
    "missing_field",
    ["character_name", "character_persona", "speaking_style"],
)
def test_character_static_variables_require_critical_fields(tmp_path, missing_field):
    static_variables = {
        "character_name": "Test Character",
        "character_persona": ["kind", "curious"],
        "speaking_style": ["brief", "friendly"],
    }
    del static_variables[missing_field]
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(static_variables), encoding="utf-8")

    with pytest.raises(ValueError, match=missing_field):
        load_static_variables(path)


def test_character_static_variables_are_loaded_before_runtime_use(tmp_path):
    path = tmp_path / "valid.json"
    path.write_text(
        json.dumps(
            {
                "character_name": " Test Character ",
                "character_persona": [" kind ", " curious "],
                "speaking_style": [" brief ", " friendly "],
            }
        ),
        encoding="utf-8",
    )

    main_chat = load_static_variables(path)

    assert main_chat.character_name == "Test Character"
    assert main_chat.character_persona == "kindcurious"
    assert main_chat.speaking_style == "brieffriendly"
