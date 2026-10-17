"""Loopback server proving call capability gating does not break chat authentication.

This harness deliberately uses the production ``ServerRuntime`` container,
``AgentRuntime``, SQL database, credential service, HTTP routes, and WebSocket
endpoints.  Provider-facing dependencies are deterministic offline ports.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI

import src.agent.skills.expression.speaking.backend as speaking_backend
from src.adapter.websocket import WebSocketAdapter
from src.adapter.websocket.call_v1 import CallWebSocketAdapter
from src.adapter.websocket.client_model_executor import ClientLLMExecutor
from src.agent_runtime import agent_runtime as agent_runtime_module
from src.application.host_context import ServerHostContext
from src.infrastructure.observability import CallMetrics, ObservabilityService
from src.infrastructure.persistence.database import DatabaseManager, InviteCode
from src.server_runtime import ServerRuntime
from src.web.http import routes
from src.web.http.user_interface import UserInterface
from src.web.websocket import call_endpoint, endpoint
from src.web.websocket.service import WebSocketService
from src.world import WorldRuntime
from support.call_coherent_runtime import (
    DeterministicCallTTSModule,
    DeterministicLLMService,
    DeterministicVectorStore,
    NoopMediaResolver,
    runtime_config,
)
from support.stage_manager import make_stage_manager


def make_runtime(root: Path, *, host_context: ServerHostContext) -> ServerRuntime:
    os.environ["JWT_SECRET"] = "call-network-e2e-isolated-secret"
    vector = DeterministicVectorStore()
    agent_runtime_module.get_vector_store = lambda: vector
    agent_runtime_module.clear_vector_store = lambda expected: expected is vector
    speaking_backend.init_tts_module = lambda _config: DeterministicCallTTSModule()

    database = DatabaseManager({"sql_db_folder": str(root / "db"), "sql_db_file": "calls.sqlite"})
    with database.open_sql_session() as session:
        session.add(InviteCode(code="invite", is_used=False))
        session.commit()
    registered, message = database.credential_service.register_user("alice", "offline-password", "invite")
    assert registered, message
    assert database.credential_service.authenticate_password_login("alice", "offline-password") is not None
    llm = DeterministicLLMService()
    agents = agent_runtime_module.AgentRuntime(runtime_config(root), llm, database, media_resolver=NoopMediaResolver())
    adapter = WebSocketAdapter(default_character_id=agents.default_character_id)
    manager = make_stage_manager(
        get_agent=agents.get_agent,
        adapter=adapter,
        get_context_factory=agents.context_factories.__getitem__,
        call_sessions=database.call_sessions,
    )
    call_adapter = CallWebSocketAdapter(
        manager=manager,
        enabled=True,
        trusted_host=host_context.supports_single_process_calls,
        provider_ready=False,
        call_tts_character_ids=lambda: agents.call_tts_character_ids,
        call_summary_character_ids=lambda: agents.call_summary_character_ids,
    )
    resolver = NoopMediaResolver()
    interface = UserInterface(database, resolver)
    interface.generate_rsa_keys()
    return ServerRuntime(
        user_interface=interface,
        websocket_service=WebSocketService(),
        world=WorldRuntime({}),
        database_manager=database,
        agent_runtime=agents,
        media_resolver=resolver,
        llm_service=llm,
        client_llm_executor=ClientLLMExecutor(),
        observability=ObservabilityService({}),
        chat_adapter=adapter,
        stage_manager=manager,
        call_adapter=call_adapter,
        call_metrics=CallMetrics(None),
        _call_transport_requested=True,
        _host_context=host_context,
    )


async def close_runtime(runtime: ServerRuntime) -> None:
    await runtime.stage_manager.close()  # type: ignore[union-attr]
    await runtime.call_adapter.close()  # type: ignore[union-attr]
    await runtime.agent_runtime.shutdown()
    await runtime.database_manager.shutdown()
    runtime.observability.close()


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    host_kind = sys.argv[2]
    root.mkdir(parents=True, exist_ok=True)
    host_context = (
        ServerHostContext(launcher="uvicorn", worker_count=2, reload_enabled=False)
        if host_kind == "multiworker"
        else ServerHostContext()
    )
    runtime = make_runtime(root, host_context=host_context)
    shell = SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime))
    endpoint.get_admin_shell = lambda: shell
    call_endpoint.get_admin_shell = lambda: shell

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await close_runtime(runtime)

    app = FastAPI(lifespan=lifespan)
    app.include_router(routes.router)
    app.include_router(endpoint.router)
    app.include_router(call_endpoint.router)

    @app.get("/test/evidence")
    async def evidence():
        token = runtime.database_manager.credential_service.generate_message_token("alice")
        return {
            "message_token": token,
            "call_transport_available": runtime.call_transport_available,
            "call_capability": asdict(runtime.call_capability_status),
        }

    @app.post("/test/stop")
    async def stop():
        server.should_exit = True
        return {"ok": True}

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        (root / "address.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{listener.getsockname()[1]}"}), encoding="utf-8"
        )
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws="websockets"))
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
