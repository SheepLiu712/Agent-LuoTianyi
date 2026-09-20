"""The application has one explicit composition root."""

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]


def test_server_runtime_is_the_only_composition_root() -> None:
    assert (SERVER_ROOT / "src" / "server_runtime.py").is_file()
    assert not (SERVER_ROOT / "src" / "system").exists()
    assert not (SERVER_ROOT / "src" / "infrastructure" / "runtime.py").exists()


def test_agent_runtime_does_not_depend_on_an_infrastructure_container() -> None:
    source = (SERVER_ROOT / "src" / "agent_runtime" / "agent_runtime.py").read_text(encoding="utf-8")

    assert "InfrastructureRuntime" not in source
    assert "self.infrastructure" not in source
