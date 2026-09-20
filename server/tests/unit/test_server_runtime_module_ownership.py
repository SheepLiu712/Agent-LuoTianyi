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


def test_server_main_delegates_all_web_binding_to_web_module() -> None:
    source = (SERVER_ROOT / "server_main.py").read_text(encoding="utf-8")

    assert source.count("bind_web_interfaces(app, current_dir)") == 1
    assert "@app." not in source
    assert "include_router" not in source
    assert "startup_event" not in source
    assert "FastAPI(lifespan=" not in source
    assert "uvicorn.run(" not in source
    assert "asyncio.run(run_server(host, port))" in source
