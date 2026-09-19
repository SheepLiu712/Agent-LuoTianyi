import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import server_main


def test_server_startup_attempts_to_start_runtime(monkeypatch):
    runtime_supervisor = SimpleNamespace(
        start=AsyncMock(return_value={"running": True, "state": "running", "last_error": None}),
    )
    admin_shell = SimpleNamespace(runtime_supervisor=runtime_supervisor)
    init_admin_shell = AsyncMock(return_value=admin_shell)
    shutdown_admin_shell = AsyncMock()
    monkeypatch.setattr(server_main, "init_admin_shell", init_admin_shell)
    monkeypatch.setattr(server_main, "shutdown_admin_shell", shutdown_admin_shell)

    async def run_lifespan() -> None:
        async with server_main.startup_event(server_main.app):
            runtime_supervisor.start.assert_awaited_once_with()

    asyncio.run(run_lifespan())

    init_admin_shell.assert_awaited_once_with(root_dir=server_main.current_dir)
    shutdown_admin_shell.assert_awaited_once_with()


def test_project_plan_is_exposed_by_public_get_routes():
    matching_routes = {
        route.path: route
        for route in server_main.app.routes
        if route.path in {"/project-plan", "/project-plan/"}
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
