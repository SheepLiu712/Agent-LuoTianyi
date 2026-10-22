"""Test-only observation wrapper for real WebSocket disconnect evidence."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from support.call_network_success_server import main

import server_main
from src.adapter.websocket.call_v1._session import Session

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

_detach = Session.detach


async def _observed_detach(self, binding):
    # Observe the current Session/Binding seam without replacing disconnect behavior.
    was_current = self._binding is binding
    result = await _detach(self, binding)
    _record(
        "session.detach",
        call_id=self.call_id,
        detached=was_current and self._binding is not binding,
        connection_present=self._binding is not None,
        stage_state=self._stage.state.value,
    )
    return result


Session.detach = _observed_detach


if __name__ == "__main__":
    main()
