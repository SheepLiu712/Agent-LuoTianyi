"""Song knowledge semantics and persistence have distinct owners."""

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_song_knowledge_storage_is_a_persistence_adapter() -> None:
    assert (SERVER_ROOT / "src" / "infrastructure" / "persistence" / "song_knowledge.py").is_file()


def test_song_entity_linking_is_an_agent_cognitive_skill() -> None:
    assert (SERVER_ROOT / "src" / "agent" / "skills" / "cognitive" / "song_entity_linker.py").is_file()
    assert not (SERVER_ROOT / "src" / "infrastructure" / "song_knowledge").exists()
