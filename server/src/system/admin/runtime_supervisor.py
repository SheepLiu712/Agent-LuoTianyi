from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime
from typing import Any, Coroutine

from src.system.admin.config_store import ConfigStore
from src.system.admin.config_validator import RuntimeConfigValidator
from src.system.admin.secret_store import SecretStore
from src.system.observability import ObservabilityService


class RuntimeSupervisor:
    """Owns the business SystemRuntime lifecycle behind the admin shell."""

    def __init__(
        self,
        *,
        config_store: ConfigStore,
        secret_store: SecretStore,
        validator: RuntimeConfigValidator,
        observability: ObservabilityService,
    ) -> None:
        self.config_store = config_store
        self.secret_store = secret_store
        self.validator = validator
        self.observability = observability
        self._runtime: Any | None = None
        self._lock = asyncio.Lock()
        self.state = "stopped"
        self.last_error: str | None = None
        self.last_started_at: str | None = None
        self.last_stopped_at: str | None = None
        self.last_validation: dict[str, Any] | None = None
        self._transition_task: asyncio.Task[dict[str, Any]] | None = None

    @property
    def runtime(self) -> Any | None:
        return self._runtime

    def is_running(self) -> bool:
        return self._runtime is not None and self.state == "running"

    def _has_active_transition(self) -> bool:
        return self._transition_task is not None and not self._transition_task.done()

    def _schedule_transition(self, coro: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
        task = asyncio.create_task(coro)
        self._transition_task = task
        task.add_done_callback(self._clear_transition_task)
        return self.status()

    def _clear_transition_task(self, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._transition_task is task:
            self._transition_task = None

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "running": self.is_running(),
            "busy": self.state in {"starting", "stopping"} or self._has_active_transition(),
            "last_error": self.last_error,
            "last_started_at": self.last_started_at,
            "last_stopped_at": self.last_stopped_at,
            "validation": self.last_validation,
        }

    def request_start(self) -> dict[str, Any]:
        if self.is_running() or self._has_active_transition():
            return self.status()
        self.state = "starting"
        self.last_error = None
        return self._schedule_transition(self.start())

    def request_stop(self) -> dict[str, Any]:
        if self._has_active_transition():
            return self.status()
        if self._runtime is None:
            self.state = "stopped"
            return self.status()
        self.state = "stopping"
        return self._schedule_transition(self.stop())

    def request_restart(self) -> dict[str, Any]:
        if self._has_active_transition():
            return self.status()
        self.state = "stopping" if self._runtime is not None else "starting"
        self.last_error = None
        return self._schedule_transition(self.restart())

    def validate_current_config(self) -> dict[str, Any]:
        self.secret_store.load_into_environment()
        try:
            config = self.config_store.read_resolved()
            self.last_validation = self.validator.validate(config)
        except (json.JSONDecodeError, OSError) as exc:
            self.last_validation = self._config_read_error_validation(exc)
        return self.last_validation

    def _config_read_error_validation(self, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, json.JSONDecodeError):
            message = f"config.json 不是合法 JSON: line {exc.lineno} column {exc.colno}: {exc.msg}"
        else:
            message = f"config.json 读取失败: {exc}"
        return {
            "ok": False,
            "core_ok": False,
            "items": [
                {
                    "scope": "core",
                    "name": "config.json",
                    "status": "error",
                    "severity": "error",
                    "message": message,
                }
            ],
            "world_disabled": [],
        }

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self.is_running():
                return self.status()
            self.state = "starting"
            self.last_error = None
            try:
                self.secret_store.load_into_environment()
                try:
                    config = self.config_store.read_resolved()
                except (json.JSONDecodeError, OSError) as exc:
                    self.last_validation = self._config_read_error_validation(exc)
                    self.state = "blocked"
                    self.last_error = self.last_validation["items"][0]["message"]
                    return self.status()
                validation = self.validator.validate(config)
                self.last_validation = validation
                if not validation.get("core_ok"):
                    self.state = "blocked"
                    self.last_error = "Runtime config validation failed"
                    return self.status()
                config = self.validator.apply_world_disablements(config, validation)

                from src.system.system_runtime import SystemRuntime, set_system_runtime

                runtime = await SystemRuntime.initialize(config, observability=self.observability)
                set_system_runtime(runtime)
                self._runtime = runtime
                self.state = "running"
                self.last_started_at = datetime.now().isoformat(timespec="seconds")
                return self.status()
            except Exception as exc:
                self.state = "failed"
                self.last_error = f"{exc}\n{traceback.format_exc()}"
                return self.status()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if self._runtime is None:
                self.state = "stopped"
                return self.status()
            self.state = "stopping"
            runtime = self._runtime
            self._runtime = None
            try:
                from src.system.system_runtime import set_system_runtime

                set_system_runtime(None)
                await runtime.shutdown()
                self.state = "stopped"
                self.last_stopped_at = datetime.now().isoformat(timespec="seconds")
                return self.status()
            except Exception as exc:
                self.state = "failed"
                self.last_error = f"{exc}\n{traceback.format_exc()}"
                return self.status()

    async def restart(self) -> dict[str, Any]:
        await self.stop()
        return await self.start()
