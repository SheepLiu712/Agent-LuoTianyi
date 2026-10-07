from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.application.admin import AdminShell, init_admin_shell, shutdown_admin_shell
from src.utils.logger import get_logger

InitializeAdminShell = Callable[..., Awaitable[AdminShell]]
ShutdownAdminShell = Callable[[], Awaitable[None]]


class ServerLifecycle:
    """Own the server application's lifecycle independently of any Web host."""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        config_path: str | Path = "config/config.json",
        initialize_admin_shell: InitializeAdminShell = init_admin_shell,
        shutdown_admin_shell: ShutdownAdminShell = shutdown_admin_shell,
    ) -> None:
        self._root_dir = Path(root_dir)
        self._config_path = config_path
        self._initialize_admin_shell = initialize_admin_shell
        self._shutdown_admin_shell = shutdown_admin_shell
        self._admin_shell: AdminShell | None = None
        self._lock = asyncio.Lock()
        self._logger = get_logger(self.__class__.__name__)

    @property
    def admin_shell(self) -> AdminShell | None:
        return self._admin_shell

    async def start(self) -> dict[str, Any]:
        """Initialize the administration shell and attempt to start ServerRuntime."""
        async with self._lock:
            if self._admin_shell is not None:
                return self._admin_shell.runtime_supervisor.status()

            admin_shell = await self._initialize_admin_shell(
                root_dir=self._root_dir,
                config_path=self._config_path,
            )
            self._admin_shell = admin_shell
            self._logger.info("AdminShell 初始化完成，正在校验配置并启动系统运行时")
            try:
                runtime_status = await admin_shell.runtime_supervisor.start()
            except BaseException:
                await self._shutdown_after_failed_start()
                raise

            if runtime_status.get("running"):
                self._logger.info("配置校验通过，ServerRuntime 已自动启动")
            else:
                self._logger.warning(
                    "ServerRuntime 未自动启动: state=%s, error=%s",
                    runtime_status.get("state"),
                    runtime_status.get("last_error"),
                )
            return runtime_status

    async def stop(self) -> None:
        """Stop ServerRuntime and close the administration shell."""
        async with self._lock:
            if self._admin_shell is None:
                return
            self._logger.info("正在关闭 AdminShell 和系统运行时")
            await self._shutdown_admin_shell()
            self._admin_shell = None
            self._logger.info("AdminShell 已关闭")

    async def _shutdown_after_failed_start(self) -> None:
        try:
            await self._shutdown_admin_shell()
        finally:
            self._admin_shell = None
