from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.system.admin.auth import AdminAuthService
from src.system.admin.config_store import ConfigStore
from src.system.admin.config_validator import RuntimeConfigValidator
from src.system.admin.runtime_supervisor import RuntimeSupervisor
from src.system.admin.secret_store import SecretStore
from src.system.observability import ObservabilityService, set_observability_service
from src.utils.logger import install_observability_log_handler, uninstall_observability_log_handler


@dataclass
class AdminShell:
    root_dir: Path
    config_store: ConfigStore
    secret_store: SecretStore
    auth: AdminAuthService
    validator: RuntimeConfigValidator
    runtime_supervisor: RuntimeSupervisor
    observability: ObservabilityService

    @classmethod
    async def initialize(cls, *, root_dir: str | Path, config_path: str | Path = "config/config.json") -> "AdminShell":
        root = Path(root_dir)
        config_store = ConfigStore(root / config_path, root_dir=root)
        secret_store = SecretStore(root / "config" / "secrets.local.env")
        secret_store.load_into_environment()
        try:
            raw_config = config_store.read_raw()
        except (json.JSONDecodeError, OSError):
            raw_config = {}
        observability = ObservabilityService(raw_config.get("observability", {}))
        set_observability_service(observability)
        install_observability_log_handler(observability)
        auth = AdminAuthService(root / "config" / "admin_auth.json", root / "config" / "admin_setup_token.txt")
        validator = RuntimeConfigValidator(root_dir=root, secret_store=secret_store)
        runtime_supervisor = RuntimeSupervisor(
            config_store=config_store,
            secret_store=secret_store,
            validator=validator,
            observability=observability,
        )
        return cls(
            root_dir=root,
            config_store=config_store,
            secret_store=secret_store,
            auth=auth,
            validator=validator,
            runtime_supervisor=runtime_supervisor,
            observability=observability,
        )

    async def shutdown(self) -> None:
        await self.runtime_supervisor.stop()
        self.observability.close()
        set_observability_service(None)
        uninstall_observability_log_handler()


_admin_shell: AdminShell | None = None


async def init_admin_shell(*, root_dir: str | Path, config_path: str | Path = "config/config.json") -> AdminShell:
    global _admin_shell
    _admin_shell = await AdminShell.initialize(root_dir=root_dir, config_path=config_path)
    return _admin_shell


def get_admin_shell() -> AdminShell:
    if _admin_shell is None:
        raise RuntimeError("AdminShell has not been initialized.")
    return _admin_shell


async def shutdown_admin_shell() -> None:
    global _admin_shell
    if _admin_shell is None:
        return
    await _admin_shell.shutdown()
    _admin_shell = None
