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
        """把顶层模块依赖分发给各运行时模块。"""
        self.llm_service.ensure_dependencies()
        self.database_manager.wire_dependencies(llm_service=self.llm_service)
        self.capability_manager.wire_dependencies(llm_service=self.llm_service)
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
        self.world.wire_dependencies(system_runtime=self)
        self.user_interface.wire_dependencies(database_manager=self.database_manager)
        self.ensure_dependencies()

    def _start_background_services(self) -> None:
        """启动所有后台服务。"""
        self.ensure_dependencies()
        self.chat_session_manager.start_background_services()
        self.world.start_background_services()

    async def shutdown(self) -> None:
        """按依赖反向顺序关闭后台服务和资源。"""
        await self.world.stop_background_services()
        await self.chat_session_manager.stop_background_services()
        await self.database_manager.shutdown()

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
