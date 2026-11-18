"""Immutable evidence about the process hosting the application."""

from __future__ import annotations

from dataclasses import dataclass

_SERVER_MAIN_ATTESTATION = object()


@dataclass(frozen=True, slots=True)
class ServerHostContext:
    """Facts supplied by the launcher; unknown hosts deliberately grant no call capability."""

    launcher: str = "unknown"
    worker_count: int | None = None
    reload_enabled: bool | None = None
    _attestation: object | None = None

    @classmethod
    def _single_worker_launcher(cls) -> "ServerHostContext":
        """Evidence emitted only by the supported in-process Uvicorn launcher."""
        return cls(
            launcher="server_main.run_server",
            worker_count=1,
            reload_enabled=False,
            _attestation=_SERVER_MAIN_ATTESTATION,
        )

    @property
    def supports_single_process_calls(self) -> bool:
        return (
            self._attestation is _SERVER_MAIN_ATTESTATION
            and self.launcher == "server_main.run_server"
            and self.worker_count == 1
            and self.reload_enabled is False
        )
