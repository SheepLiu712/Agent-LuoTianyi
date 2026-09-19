from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Final

from src.adapter.websocket import WebSocketAdapter
from src.agent_runtime import AgentRuntime
from src.agent_runtime.agent_runtime import clear_agent_runtime
from src.domain.stage import StageState
from src.infrastructure.runtime import InfrastructureRuntime
from src.stage import StageManager, WorldStage
from src.system.database import DatabaseManager, set_default_database_manager
from src.system.due_event_provider import EventStoreDueEventProvider
from src.system.observability import ObservabilityService, set_observability_service
from src.system.user_interface import UserInterface
from src.utils.llm.client_llm_executor import ClientLLMExecutor
from src.utils.llm_service import LLMService
from src.utils.logger import (
    get_logger,
    install_observability_log_handler,
    uninstall_observability_log_handler,
)
from src.world import WorldRuntime

logger = get_logger(__name__)
DEFAULT_WORLD_ID: Final = "default"


@dataclass
class SystemRuntime:
    """Application-level runtime container and lifecycle owner."""

    user_interface: UserInterface
    world: WorldRuntime
    database_manager: DatabaseManager
    agent_runtime: AgentRuntime
    infrastructure: InfrastructureRuntime
    llm_service: LLMService
    client_llm_executor: ClientLLMExecutor
    observability: ObservabilityService
    owns_observability: bool = field(default=True)
    chat_adapter: WebSocketAdapter = field(default_factory=WebSocketAdapter)
    stage_manager: StageManager | None = None
    default_world_id: str = DEFAULT_WORLD_ID
    world_stage_config: dict = field(default_factory=dict, repr=False)
    _world_stages: dict[tuple[str, str], WorldStage] = field(default_factory=dict, init=False, repr=False)
    _world_stage_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _shutdown_complete: bool = field(default=False, init=False, repr=False)
    _shutdown_completed_stages: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    async def initialize(cls, config: dict, observability: ObservabilityService | None = None) -> SystemRuntime:
        owns_observability = observability is None
        database_manager: DatabaseManager | None = None
        infrastructure: InfrastructureRuntime | None = None
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

            # 4. 初始化共享基础设施。SpeechBackend 会在这里启动 TTS worker。
            infrastructure = InfrastructureRuntime(config.get("infrastructure", {}), llm_service)

            # 5. 初始化箱庭世界运行时
            world = WorldRuntime(config.get("world", {}))

            # 6. 初始化 Agent 运行时
            agent_config = dict(config.get("agent_runtime", {}))
            skills_config = dict(agent_config.get("skills", {}))
            skills_config.setdefault(
                "conversation_compaction",
                config.get("chat_session_manager", {}).get("conversation_service", {}),
            )
            agent_config["skills"] = skills_config
            agent_runtime = AgentRuntime(
                agent_config,
                llm_service,
                infrastructure,
                database_manager,
            )

            # 7. 组装系统运行时
            runtime = cls(
                user_interface=UserInterface(database_manager),
                world=world,
                database_manager=database_manager,
                agent_runtime=agent_runtime,
                infrastructure=infrastructure,
                llm_service=llm_service,
                client_llm_executor=client_llm_executor,
                observability=observability,
                owns_observability=owns_observability,
                chat_adapter=WebSocketAdapter(
                    {
                        **config.get("chat_adapter", {}),
                        "media_store": config.get("infrastructure", {}).get("media_resolution", {}),
                    },
                    default_character_id=agent_runtime.default_character_id,
                ),
                default_world_id=str(config.get("world", {}).get("world_id", DEFAULT_WORLD_ID)),
                world_stage_config=config.get("world_stage", {}),
            )

            event_store = database_manager.event_store
            if event_store is None:
                raise RuntimeError("EventStore is required for due-event dispatch")
            runtime.stage_manager = StageManager(
                get_agent=agent_runtime.get_agent,
                adapter=runtime.chat_adapter,
                get_context_factory=agent_runtime.context_factories.__getitem__,
                due_event_provider=EventStoreDueEventProvider(event_store),
                config=config.get("stage_manager", {}),
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
                infrastructure=infrastructure,
                agent_runtime=agent_runtime,
                observability=observability,
                owns_observability=owns_observability,
            )
            raise

    def _wire_dependencies(self) -> None:
        """把顶层模块依赖分发给各运行时模块。"""
        self.llm_service.ensure_dependencies()
        self.database_manager.wire_dependencies(llm_service=self.llm_service)
        self.infrastructure.wire_dependencies()
        self.agent_runtime.wire_dependencies(
            llm_service=self.llm_service,
            infrastructure=self.infrastructure,
            database_manager=self.database_manager,
        )
        self.world.wire_dependencies(system_runtime=self)
        self.user_interface.wire_dependencies(database_manager=self.database_manager)
        self.ensure_dependencies()

    def _start_background_services(self) -> None:
        """启动所有后台服务。"""
        self.ensure_dependencies()
        self.world.start_background_services()

    @classmethod
    async def _rollback_failed_initialization(
        cls,
        *,
        runtime: SystemRuntime | None,
        world: WorldRuntime | None,
        database_manager: DatabaseManager | None,
        infrastructure: InfrastructureRuntime | None,
        agent_runtime: AgentRuntime | None,
        observability: ObservabilityService | None,
        owns_observability: bool,
    ) -> None:
        """在初始化失败的情况下，尝试回滚初始化失败的系统运行时，关闭已启动的后台服务和资源。"""
        errors: list[str] = []

        async def _clear_refs() -> None:
            cls._clear_global_references(
                runtime=runtime,
                database_manager=database_manager,
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
            ("world stages", runtime.close_world_stages if runtime is not None else None),
            (
                "chat stages",
                runtime.stage_manager.close if runtime is not None and runtime.stage_manager is not None else None,
            ),
            ("world runtime", world.stop_background_services if world is not None else None),
            (
                "agent runtime",
                getattr(agent_runtime, "shutdown", None) if agent_runtime is not None else None,
            ),
            ("infrastructure", infrastructure.stop if infrastructure is not None else None),
            ("database manager", database_manager.shutdown if database_manager is not None else None),
            ("global references", _clear_refs),
            ("observability", _close_obs if (owns_observability and observability is not None) else None),
        )
        for name, stop in shutdown_steps:
            if stop is None:
                continue
            try:
                await stop()
            except BaseException as error:  # noqa: BLE001 - rollback must continue through all owned resources
                errors.append(f"{name}: {type(error).__name__}: {error}")

        if errors:
            logger.error("SystemRuntime initialization rollback had errors: " + "; ".join(errors))
        else:
            logger.info("SystemRuntime initialization rollback completed successfully.")

    @staticmethod
    def _clear_global_references(
        *,
        runtime: SystemRuntime | None,
        database_manager: DatabaseManager | None,
        agent_runtime: AgentRuntime | None,
    ) -> None:
        """将已经连接的引用清理掉，避免在系统运行时关闭后仍然被引用。"""
        global _system_runtime
        if runtime is not None and _system_runtime is runtime:
            _system_runtime = None
        if agent_runtime is not None:
            clear_agent_runtime(agent_runtime)
        if database_manager is not None:
            # The runtime is the sole owner of the legacy database singleton.
            set_default_database_manager(None)

    ########## 关闭逻辑 ##########

    async def shutdown(self) -> None:
        """按依赖反向顺序关闭后台服务和资源。"""
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            errors: list[str] = []
            shutdown_steps = (
                ("world runtime", self.world.stop_background_services),
                ("world stages", self.close_world_stages),
                ("chat stages", self.stage_manager.close if self.stage_manager is not None else None),
                ("agent runtime", getattr(self.agent_runtime, "shutdown", None)),
                ("infrastructure", self.infrastructure.stop),
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
                except Exception as error:  # noqa: BLE001 - lifecycle boundary aggregates dependency failures
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
            "infrastructure": self.infrastructure,
            "llm_service": self.llm_service,
            "observability": self.observability,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"SystemRuntime dependencies are missing: {', '.join(missing)}")
        self.llm_service.ensure_dependencies()
        self.database_manager.ensure_dependencies()
        self.infrastructure.ensure_dependencies()
        self.agent_runtime.ensure_dependencies()
        self.world.ensure_dependencies()
        self.user_interface.ensure_dependencies()

    def get_agent(self, character_id: str | None = None):
        """通过显式拥有的 AgentRuntime 返回角色门面。"""
        return self.agent_runtime.get_agent(character_id)

    async def get_world_stage(
        self,
        character_id: str | None = None,
        world_id: str | None = None,
    ) -> WorldStage:
        """取得或创建角色与世界作用域唯一的长期 WorldStage。"""
        selected_character = character_id or self.agent_runtime.default_character_id
        selected_world = world_id or self.default_world_id
        key = (selected_character, selected_world)
        async with self._world_stage_lock:
            stage = self._world_stages.get(key)
            if stage is None or stage.state is StageState.TERMINATED:
                settlements = getattr(getattr(self, "world", None), "settlements", None)
                stage = await WorldStage.create(
                    character_id=selected_character,
                    world_id=selected_world,
                    agent=self.get_agent(selected_character),
                    context_factory=self.agent_runtime.context_factories[selected_character],
                    config=self.world_stage_config,
                    on_handling_settled=(settlements.on_handling_settled if settlements is not None else None),
                    on_execution_finished=(settlements.on_execution_finished if settlements is not None else None),
                )
                self._world_stages[key] = stage
            return stage

    async def close_world_stages(self) -> None:
        """移出并关闭全部长期 WorldStage。"""
        async with self._world_stage_lock:
            stages = tuple(self._world_stages.values())
            self._world_stages.clear()
        if stages:
            await asyncio.gather(*(stage.close() for stage in stages))

    # Properties for convenient access to subsystems
    @property
    def websocket_service(self):
        return self.user_interface.websocket_service


_system_runtime: SystemRuntime | None = None


def set_system_runtime(runtime: SystemRuntime | None) -> None:
    global _system_runtime
    _system_runtime = runtime


async def init_system_runtime(config: dict) -> SystemRuntime:
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
