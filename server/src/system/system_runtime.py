from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict

from src.agent_runtime import AgentRuntime
from src.agent_runtime.agent_runtime import clear_agent_runtime
from src.capabilities import CapabilityManager
from src.chat_session import ChatSessionManager
from src.chat_session import chat_stream_manager as chat_stream_manager_module
from src.system.database import DatabaseManager, set_default_database_manager
from src.system.observability import ObservabilityService, set_observability_service
from src.system.user_interface import UserInterface
from src.utils.llm_service import LLMService
from src.utils.llm.client_llm_executor import ClientLLMExecutor
from src.utils.logger import get_logger, install_observability_log_handler, uninstall_observability_log_handler
from src.world import WorldRuntime


logger = get_logger(__name__)


@dataclass
class SystemRuntime:
    """Application-level runtime container and lifecycle owner."""

    user_interface: UserInterface
    world: WorldRuntime
    database_manager: DatabaseManager
    agent_runtime: AgentRuntime
    capability_manager: CapabilityManager
    chat_session_manager: ChatSessionManager
    llm_service: LLMService
    client_llm_executor: ClientLLMExecutor
    observability: ObservabilityService
    owns_observability: bool = field(default=True)
    _shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _shutdown_complete: bool = field(default=False, init=False, repr=False)
    _shutdown_completed_stages: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    async def initialize(cls, config: Dict, observability: ObservabilityService | None = None) -> "SystemRuntime":
        owns_observability = observability is None
        database_manager: DatabaseManager | None = None
        capability_manager: CapabilityManager | None = None
        chat_session_manager: ChatSessionManager | None = None
        world: WorldRuntime | None = None
        agent_runtime: AgentRuntime | None = None
        runtime: SystemRuntime | None = None
        llm_service: LLMService | None = None

        try:
            # 1. 初始化观测服务，后续模块可统一写入指标和异常日志
            if observability is None:
                observability = ObservabilityService(config.get("observability", {}))
                set_observability_service(observability)
                install_observability_log_handler(observability)

            # 2. 初始化 LLM 服务
            client_llm_timeout = config.get("llm_service", {}).get("client_llm_timeout_seconds", 120.0)
            client_llm_executor = ClientLLMExecutor(timeout_seconds=client_llm_timeout)
            llm_service = LLMService(
                config.get("llm_service", {}),
                client_llm_executor=client_llm_executor,
            )

            # 3. 初始化数据库管理器
            database_manager = DatabaseManager(config.get("database", {}))
            set_default_database_manager(database_manager)

            # 4. 初始化能力管理器。SpeechCapability 会在这里启动 TTS worker。
            capability_manager = CapabilityManager(config.get("capabilities", {}), llm_service)

            # 5. 初始化聊天会话管理器
            chat_session_manager = ChatSessionManager(
                config.get("chat_session_manager", {}),
                llm_service,
                database_manager,
            )

            # 6. 初始化箱庭世界运行时
            world = WorldRuntime(config.get("world", {}))

            # 7. 初始化 Agent 运行时
            agent_runtime = AgentRuntime(
                config.get("agent_runtime", {}),
                llm_service,
                capability_manager,
                database_manager,
            )

            # 8. 组装系统运行时
            runtime = cls(
                user_interface=UserInterface(database_manager),
                world=world,
                database_manager=database_manager,
                agent_runtime=agent_runtime,
                capability_manager=capability_manager,
                chat_session_manager=chat_session_manager,
                llm_service=llm_service,
                client_llm_executor=client_llm_executor,
                observability=observability,
                owns_observability=owns_observability,
            )

            runtime._wire_dependencies()
            runtime._start_background_services()
            runtime.user_interface.generate_rsa_keys()
            return runtime
        except BaseException:
            logger.error("SystemRuntime initialization failed, starting rollback...")
            await cls._rollback_failed_initialization(
                runtime=runtime,
                world=world,
                database_manager=database_manager,
                capability_manager=capability_manager,
                chat_session_manager=chat_session_manager,
                agent_runtime=agent_runtime,
                observability=observability,
                owns_observability=owns_observability,
            )
            raise

    def _wire_dependencies(self) -> None:
        """把顶层模块依赖分发给各运行时模块。"""
        self.llm_service.ensure_dependencies()
        self.database_manager.wire_dependencies(llm_service=self.llm_service)
        self.capability_manager.wire_dependencies(
            database_manager=self.database_manager,
        )
        self.agent_runtime.wire_dependencies(
            llm_service=self.llm_service,
            capability_manager=self.capability_manager,
            database_manager=self.database_manager,
        )
        self.chat_session_manager.wire_dependencies(
            database_manager=self.database_manager,
            llm_service=self.llm_service,
            capability_manager=self.capability_manager,
        )
        self.client_llm_executor.bind(self.chat_session_manager.chat_stream_manager)
        self.world.wire_dependencies(system_runtime=self)
        self.user_interface.wire_dependencies(database_manager=self.database_manager)
        self.ensure_dependencies()

    def _start_background_services(self) -> None:
        """启动所有后台服务。"""
        self.ensure_dependencies()
        self.chat_session_manager.start_background_services()
        self.world.start_background_services()

    @classmethod
    async def _rollback_failed_initialization(
        cls,
        *,
        runtime: "SystemRuntime | None",
        world: "WorldRuntime | None",
        database_manager: "DatabaseManager | None",
        capability_manager: "CapabilityManager | None",
        chat_session_manager: "ChatSessionManager | None",
        agent_runtime: "AgentRuntime | None",
        observability: "ObservabilityService | None",
        owns_observability: bool,
    ) -> None:
        """在初始化失败的情况下，尝试回滚初始化失败的系统运行时，关闭已启动的后台服务和资源。"""
        errors: list[str] = []

        async def _clear_refs() -> None:
            cls._clear_global_references(
                runtime=runtime,
                database_manager=database_manager,
                chat_session_manager=chat_session_manager,
                agent_runtime=agent_runtime,
            )

        async def _close_obs() -> None:
            """关闭观测服务，finally 确保无论成功与否都清理全局状态。"""
            try:
                observability.close()  # type: ignore[union-attr]
            finally:
                set_observability_service(None)
                uninstall_observability_log_handler()

        shutdown_steps: tuple[tuple[str, callable | None], ...] = (
            ("world runtime", world.stop_background_services if world is not None else None),
            (
                "chat session manager",
                chat_session_manager.stop_background_services if chat_session_manager is not None else None,
            ),
            (
                "agent runtime",
                getattr(agent_runtime, "shutdown", None) if agent_runtime is not None else None,
            ),
            ("capability manager", capability_manager.stop if capability_manager is not None else None),
            ("database manager", database_manager.shutdown if database_manager is not None else None),
            ("global references", _clear_refs),
            ("observability", _close_obs if (owns_observability and observability is not None) else None),
        )
        for name, stop in shutdown_steps:
            if stop is None:
                continue
            try:
                await stop()
            except BaseException as error:
                errors.append(f"{name}: {type(error).__name__}: {error}")

        if errors:
            logger.error("SystemRuntime initialization rollback had errors: " + "; ".join(errors))
        else:
            logger.info("SystemRuntime initialization rollback completed successfully.")

    @staticmethod
    def _clear_global_references(
        *,
        runtime: "SystemRuntime | None",
        database_manager: "DatabaseManager | None",
        chat_session_manager: "ChatSessionManager | None",
        agent_runtime: "AgentRuntime | None",
    ) -> None:
        '''将已经连接的引用清理掉，避免在系统运行时关闭后仍然被引用。'''
        global _system_runtime
        if runtime is not None and _system_runtime is runtime:
            _system_runtime = None
        if agent_runtime is not None:
            clear_agent_runtime(agent_runtime)
        if database_manager is not None:
            # The runtime is the sole owner of the legacy database singleton.
            set_default_database_manager(None)
        if chat_session_manager is not None:
            manager = getattr(chat_session_manager, "chat_stream_manager", None)
            if chat_stream_manager_module.chat_stream_manager is manager:
                chat_stream_manager_module.chat_stream_manager = None

    ########## 关闭逻辑 ##########

    async def shutdown(self) -> None:
        """按依赖反向顺序关闭后台服务和资源。"""
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            errors: list[str] = []
            shutdown_steps = (
                ("world runtime", self.world.stop_background_services),
                ("chat sessions", self.chat_session_manager.stop_background_services),
                ("agent runtime", getattr(self.agent_runtime, "shutdown", None)),
                ("capability manager", self.capability_manager.stop),
                ("database manager", self.database_manager.shutdown),
                ("global references", self._shutdown_clear_global_references),
                ("observability", self._shutdown_observability),
            )
            all_stages = {name for name, _stop in shutdown_steps}

            for name, stop in shutdown_steps:
                if name in self._shutdown_completed_stages:
                    continue
                if stop is None:
                    self._shutdown_completed_stages.add(name)
                    continue
                try:
                    await stop()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    errors.append(f"{name}: {type(error).__name__}: {error}")
                    break
                else:
                    self._shutdown_completed_stages.add(name)

            self._shutdown_complete = all_stages.issubset(self._shutdown_completed_stages)
            if errors:
                raise RuntimeError("System runtime shutdown failed: " + "; ".join(errors))

    async def _shutdown_clear_global_references(self) -> None:
        """清理模块级全局引用，防止关闭后仍被其他代码引用。"""
        self._clear_global_references(
            runtime=self,
            database_manager=self.database_manager,
            chat_session_manager=self.chat_session_manager,
            agent_runtime=self.agent_runtime,
        )

    async def _shutdown_observability(self) -> None:
        """关闭观测服务并清理相关全局状态。"""
        if self.owns_observability:
            self.observability.close()
            set_observability_service(None)
            uninstall_observability_log_handler()

    def ensure_dependencies(self) -> None:
        """检查系统运行时所有顶层模块依赖已经完成派发。"""
        required = {
            "user_interface": self.user_interface,
            "world": self.world,
            "database_manager": self.database_manager,
            "agent_runtime": self.agent_runtime,
            "capability_manager": self.capability_manager,
            "chat_session_manager": self.chat_session_manager,
            "llm_service": self.llm_service,
            "observability": self.observability,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"SystemRuntime dependencies are missing: {', '.join(missing)}")
        self.llm_service.ensure_dependencies()
        self.database_manager.ensure_dependencies()
        self.capability_manager.ensure_dependencies()
        self.agent_runtime.ensure_dependencies()
        self.chat_session_manager.ensure_dependencies()
        self.world.ensure_dependencies()
        self.user_interface.ensure_dependencies()

    # Properties for convenient access to subsystems
    @property
    def agent(self):
        return self.agent_runtime.get_agent()

    @property
    def websocket_service(self):
        return self.user_interface.websocket_service

    @property
    def gcsm(self):
        return self.chat_session_manager.chat_stream_manager

    @property
    def chat_stream_manager(self):
        return self.chat_session_manager.chat_stream_manager

    @property
    def conversation_service(self):
        return self.chat_session_manager.conversation_service

    @property
    def activity_maker(self):
        return self.chat_session_manager.proactive_topic_maker

    @property
    def global_speaking_worker(self):
        return self.chat_session_manager.global_speaking_worker

    @property
    def capabilities(self):
        return self.capability_manager




_system_runtime: SystemRuntime | None = None


def set_system_runtime(runtime: SystemRuntime | None) -> None:
    global _system_runtime
    _system_runtime = runtime


async def init_system_runtime(config: Dict) -> SystemRuntime:
    global _system_runtime
    _system_runtime = await SystemRuntime.initialize(config)
    return _system_runtime


def get_system_runtime_optional() -> SystemRuntime | None:
    return _system_runtime


def get_system_runtime() -> SystemRuntime:
    if _system_runtime is None:
        raise RuntimeError("SystemRuntime has not been initialized.")
    return _system_runtime


async def shutdown_system_runtime() -> None:
    global _system_runtime
    if _system_runtime is None:
        return
    await _system_runtime.shutdown()
    _system_runtime = None
