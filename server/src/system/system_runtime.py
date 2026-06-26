from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from src.agent_runtime import AgentRuntime
from src.capabilities import CapabilityManager
from src.chat_session import ChatSessionManager
from src.system.database import DatabaseManager, set_default_database_manager
from src.system.user_interface import UserInterface
from src.utils.llm_service import LLMService
from src.world import WorldRuntime


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

    @classmethod
    async def initialize(cls, config: Dict) -> "SystemRuntime":
        # 1. 初始化 LLM 服务
        llm_service = LLMService(config.get("llm_service", {}))

        # 2. 初始化数据库管理器
        database_manager = DatabaseManager(config.get("database", {}))
        database_manager.create_llm_modules(llm_service)
        set_default_database_manager(database_manager)

        # 3. 初始化能力管理器
        capability_manager = CapabilityManager(config.get("capabilities", {}), llm_service)

        # 4. 初始化聊天会话管理器
        chat_session_manager = ChatSessionManager(
            config.get("chat_session_manager", {}),
            llm_service,
            database_manager,
        )
        
        # 5. 初始化箱庭世界运行时
        world = WorldRuntime(
            config.get("world", {}),
        )

        # 6. 初始化 Agent 运行时
        agent_runtime = AgentRuntime(
            config.get("agent_runtime", {}),
            llm_service,
            capability_manager,
            database_manager,
        )

        # 7. 组装系统运行时
        runtime = cls(
            user_interface=UserInterface(database_manager),
            world=world,
            database_manager=database_manager,
            agent_runtime=agent_runtime,
            capability_manager=capability_manager,
            chat_session_manager=chat_session_manager,
            llm_service=llm_service,
        )

        runtime._wire_dependencies()
        runtime._start_background_services()
        runtime.user_interface.generate_rsa_keys()
        return runtime

    def _wire_dependencies(self) -> None:
        self.world.set_system_runtime(self)
        self.world.initialize_modules()
        self.chat_session_manager.proactive_topic_maker.set_agent(self.agent)
        self.chat_session_manager.proactive_topic_maker.set_system_runtime(self)
        self.gcsm.register_activity_maker(self.chat_session_manager.proactive_topic_maker)
        self.global_speaking_worker.set_capabilities(self.capability_manager)

    def _start_background_services(self) -> None:
        self.chat_session_manager.start_background_services()
        self.world.start_background_services()

    async def shutdown(self) -> None:
        await self.world.stop_background_services()
        await self.chat_session_manager.stop_background_services()

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
