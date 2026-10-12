"""Test-only observation wrapper for real WebSocket disconnect evidence."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from support.call_network_success_server import main

import server_main
from src.server_runtime import CallTransportHub

EVIDENCE = Path(sys.argv[1]).resolve() / "disconnect-evidence.jsonl"


def _record(event: str, **fields: object) -> None:
    item = {"event": event, "monotonic_ns": time.monotonic_ns(), **fields}
    with EVIDENCE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, separators=(",", ":")) + "\n")


class DisconnectEvidenceMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))

        async def observed_receive():
            message = await receive()
            if message.get("type") == "websocket.disconnect":
                _record("websocket.disconnect", path=path, code=message.get("code"))
            return message

        await self.app(scope, observed_receive, send)


server_main.app.add_middleware(DisconnectEvidenceMiddleware)

_detach_after_disconnect = CallTransportHub.detach_after_disconnect


async def _observed_detach_after_disconnect(self, binding, disconnect_stage):
    call_id = binding.session.call_id
    stage_state = None

    async def observed_stage_disconnect():
        nonlocal stage_state
        result = await disconnect_stage()
        manager = getattr(binding.session.business_sink, "_stage", None)
        state = getattr(manager, "state", None)
        stage_state = getattr(state, "value", None)
        return result

    detached = await _detach_after_disconnect(self, binding, observed_stage_disconnect)
    entry = self._sessions.get(call_id)  # noqa: SLF001 - test-only observation
    _record(
        "hub.detach_after_disconnect",
        call_id=call_id,
        detached=detached,
        connection_present=entry is not None and entry.connection_id is not None,
        generation=None if entry is None else entry.generation,
        stage_state=stage_state,
    )
    return detached


CallTransportHub.detach_after_disconnect = _observed_detach_after_disconnect


if __name__ == "__main__":
    main()
