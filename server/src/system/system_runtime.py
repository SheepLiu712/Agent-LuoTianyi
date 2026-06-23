from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


from src.system.user_interface import UserInterface
from src.world import WorldRuntime
from src.system.database import DatabaseManager
from src.agent_runtime import AgentRuntime
from src.capabilities import CapabilityManager
from src.chat_session import ChatSessionManager
from src.utils.llm_service import LLMService


@dataclass
class SystemRuntime:
    """Application-level runtime container and lifecycle owner.

    SystemRuntime owns long-lived application services. Request handlers should
    use it as a dependency container, while startup/shutdown details remain
    inside this module.
    """
    user_interface: UserInterface
    world: WorldRuntime
    database_manager: DatabaseManager
    agent_runtime: AgentRuntime
    capability_manager: CapabilityManager
    chat_session_manager: ChatSessionManager
    llm_service: LLMService

    @classmethod
    async def initialize(cls, config: Dict) -> "SystemRuntime":
        # llm服务初始化
        llm_service = LLMService(config.get("llm_service", {}))

        # 数据库初始化
        database_manager = DatabaseManager(config.get("database", {}))
        database_manager.init_all_databases()

        # 能力模块初始化
        capability_manager = CapabilityManager(config.get("capabilities", {}), llm_service)

        # 会话管理器初始化
        chat_session_manager = ChatSessionManager(config.get("chat_sessions", {}), llm_service)

        # 箱庭世界初始化
        world = WorldRuntime(config.get("world", {}), llm_service)

        # Agent运行时初始化
        agent_runtime = AgentRuntime(config.get("agent_runtime", {}), llm_service, capability_manager, database_manager)

        runtime = cls(
            user_interface=UserInterface(database_manager),
            capability_manager = capability_manager,
            chat_session_manager = chat_session_manager,
            world=world,
            database_manager=database_manager,
            agent_runtime=agent_runtime,
            llm_service=llm_service,
        )

        # runtime._wire_dependencies()
        runtime._start_background_services()
        runtime.user_interface.generate_rsa_keys()
        return runtime

    def _wire_dependencies(self) -> None:
        self.activity_maker.set_agent(self.agent)
        self.activity_maker.set_system_runtime(self)
        self.gcsm.register_activity_maker(self.activity_maker)
        self.global_speaking_worker.set_capabilities(self.capabilities)
        if self.schedule_manager is not None:
            self.schedule_manager.set_gcsm_ref(self.gcsm)

    def _start_background_services(self) -> None:
        # 启动chat session相关的后台服务
        self.chat_session_manager.start_background_services()
        self.world.start_background_services()

    async def shutdown(self) -> None:
        await self.world.stop_background_services()
        await self.chat_session_manager.stop_background_services()

    # 各种属性访问器，方便外部使用
    @property
    def agent(self):
        return self.agent_runtime.get_agent()
    
    @property
    def websocket_service(self):
        return self.user_interface.websocket_service

    @property
    def gcsm(self):
        return self.chat_session_manager.global_chat_stream_manager


_system_runtime: SystemRuntime | None = None


async def init_system_runtime(config: Dict) -> SystemRuntime:
    global _system_runtime
    _system_runtime = await SystemRuntime.initialize(config)
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
