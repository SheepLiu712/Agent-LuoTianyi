import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server_main
from src.application.server_lifecycle import ServerLifecycle


def test_server_lifecycle_starts_and_stops_without_fastapi(tmp_path):
    runtime_supervisor = SimpleNamespace(
        start=AsyncMock(return_value={"running": True, "state": "running", "last_error": None}),
    )
    admin_shell = SimpleNamespace(runtime_supervisor=runtime_supervisor)
    init_admin_shell = AsyncMock(return_value=admin_shell)
    shutdown_admin_shell = AsyncMock()
    lifecycle = ServerLifecycle(
        root_dir=tmp_path,
        initialize_admin_shell=init_admin_shell,
        shutdown_admin_shell=shutdown_admin_shell,
    )

    async def run_lifecycle() -> None:
        status = await lifecycle.start()
        assert status["running"] is True
        await lifecycle.stop()

    asyncio.run(run_lifecycle())

    init_admin_shell.assert_awaited_once_with(root_dir=tmp_path, config_path="config/config.json")
    runtime_supervisor.start.assert_awaited_once_with()
    shutdown_admin_shell.assert_awaited_once_with()


def test_run_server_owns_lifecycle_around_uvicorn(monkeypatch):
    events = []
    event_loops = []

    class Lifecycle:
        async def start(self):
            events.append("start")
            event_loops.append(asyncio.get_running_loop())

        async def stop(self):
            events.append("stop")
            event_loops.append(asyncio.get_running_loop())

    class WebServer:
        def __init__(self, config):
            assert config.app is server_main.app
            assert config.host == "127.0.0.1"
            assert config.port == 60030
            assert config.lifespan == "off"

        async def serve(self):
            events.append("serve")
            event_loops.append(asyncio.get_running_loop())
            raise RuntimeError("server stopped unexpectedly")

    monkeypatch.setattr(server_main.uvicorn, "Server", WebServer)
    monkeypatch.setattr(server_main, "install_access_log_filter", lambda: events.append("filter"))

    with pytest.raises(RuntimeError, match="server stopped unexpectedly"):
        asyncio.run(server_main.run_server("127.0.0.1", 60030, Lifecycle()))

    assert events == ["filter", "start", "serve", "stop"]
    assert all(event_loop is event_loops[0] for event_loop in event_loops)


def test_project_plan_is_exposed_by_public_get_routes():
    matching_routes = {
        route.path: route
        for route in server_main.app.routes
        if getattr(route, "path", None) in {"/project-plan", "/project-plan/"}
    }

    assert set(matching_routes) == {"/project-plan", "/project-plan/"}
    assert all("GET" in route.methods for route in matching_routes.values())


def test_project_plan_get_returns_page_content():
    client = TestClient(server_main.app)

    response = client.get("/project-plan")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "AgentLuo项目计划书" in response.text
    assert "最终她会于光影中降临" in response.text
