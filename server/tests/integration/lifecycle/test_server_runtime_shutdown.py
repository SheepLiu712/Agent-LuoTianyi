import asyncio
from types import SimpleNamespace

from src.server_runtime import ServerRuntime
from src.adapter.websocket.client_model_executor import ClientLLMExecutor


def test_server_runtime_shutdown_releases_agent_skills_before_database():
    calls: list[str] = []

    async def record_async(name: str) -> None:
        calls.append(name)

    runtime = ServerRuntime(
        user_interface=SimpleNamespace(),
        websocket_service=SimpleNamespace(),
        world=SimpleNamespace(
            stop_background_services=lambda: record_async("world"),
        ),
        database_manager=SimpleNamespace(
            shutdown=lambda: record_async("database"),
        ),
        agent_runtime=SimpleNamespace(shutdown=lambda: record_async("agent_skills")),
        media_resolver=SimpleNamespace(),
        llm_service=SimpleNamespace(),
        observability=SimpleNamespace(),
        client_llm_executor=ClientLLMExecutor(),
        owns_observability=False,
    )

    asyncio.run(runtime.shutdown())

    assert calls == ["world", "agent_skills", "database"]
