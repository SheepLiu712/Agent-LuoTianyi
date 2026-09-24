"""Singing implementation belongs to the shared Agent skill boundary."""

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_singing_implementation_is_owned_by_agent_skills() -> None:
    singing = SERVER_ROOT / "src" / "agent" / "skills" / "expression" / "singing"

    assert (singing / "skill.py").is_file()
    assert (singing / "backend.py").is_file()
    assert (singing / "manager.py").is_file()
    assert (singing / "emotion.py").is_file()
    assert (singing / "wishlist.py").is_file()
    assert not (SERVER_ROOT / "src" / "infrastructure" / "singing").exists()


def test_singing_config_is_not_owned_by_infrastructure() -> None:
    import json

    config = json.loads((SERVER_ROOT / "config" / "config.json.template").read_text(encoding="utf-8"))

    assert "sing" not in config.get("infrastructure", {})
    assert "singing" in config["agent_runtime"]["skills"]
