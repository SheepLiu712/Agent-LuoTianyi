from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import src.system.database as database
from src.agent.activity_maker import ActivityMaker, init_activity_maker
from src.agent.luotianyi_agent import LuoTianyiAgent
from src.capabilities import CapabilityRegistry, SingingCapability, SpeechCapability
from src.capabilities.speech import TTSModule, init_tts_module
from src.plugins import DailyScheduler
from src.world.citywalk import CitywalkRuntimeService
from src.plugins.music import MusicManager
from src.plugins.schedule import ScheduleManager
from src.runtime.agent_runtime import AgentRuntime, get_default_agent, init_agent_runtime
from src.system.chat_session.global_chat_stream_manager import GlobalChatStreamManager, get_GCSM
from src.system.conversation import ConversationManager, ConversationService
from src.system.database.sql_database import get_sql_session
from src.system.user_interface import account
from src.system.user_interface.websocket_service import WebSocketService, get_websocket_service
from src.system.workers.global_speaking_worker import GlobalSpeakingWorker, get_global_speaking_worker
from src.world import CitywalkDiaryProvider, ScheduleWorldProvider


@dataclass
class SystemRuntime:
    """Application-level runtime container and lifecycle owner.

    SystemRuntime owns long-lived application services. Request handlers should
    use it as a dependency container, while startup/shutdown details remain
    inside this module.
    """

    websocket_service: WebSocketService
    gcsm: GlobalChatStreamManager
    global_speaking_worker: GlobalSpeakingWorker
    agent: LuoTianyiAgent
    agent_runtime: AgentRuntime
    capabilities: CapabilityRegistry
    conversation_service: ConversationService
    activity_maker: ActivityMaker
    schedule_manager: Optional[ScheduleManager] = None
    world_event_provider: Optional[ScheduleWorldProvider] = None
    public_diary_provider: Optional[CitywalkDiaryProvider] = None
    daily_scheduler: Optional[DailyScheduler] = None

    @classmethod
    async def initialize(cls, config: Dict) -> "SystemRuntime":
        database_config: Dict = config.get("database", {})
        database.init_all_databases(database_config)

        tts_config = config.get("tts", {})
        tts_module: TTSModule = init_tts_module(tts_config)

        music_manager = MusicManager(config=config["music"])
        capabilities = CapabilityRegistry(
            speech=SpeechCapability(tts_module),
            singing=SingingCapability(music_manager),
        )
        agent_runtime = init_agent_runtime(
            config,
            tts_module,
            redis_client=database.get_redis_buffer(),
            vector_store=database.get_vector_store(),
            sql_session_factory=get_sql_session,
            music_manager=music_manager,
            capabilities=capabilities,
        )
        agent = get_default_agent()

        conversation_service = ConversationService(
            conversation_manager=ConversationManager(
                config.get("conversation_manager", {}),
                agent.prompt_manager,
            ),
            sql_session_factory=get_sql_session,
            redis_client=database.get_redis_buffer(),
        )

        schedule_manager = ScheduleManager(
            sql_session_factory=get_sql_session,
            config=config.get("schedule", {}),
        )
        citywalk_report_dir = (
            config.get("citywalk", {})
            .get("report", {})
            .get("output_dir", "data/citywalk_reports")
        )

        runtime = cls(
            websocket_service=get_websocket_service(),
            gcsm=get_GCSM(),
            global_speaking_worker=get_global_speaking_worker(),
            agent=agent,
            agent_runtime=agent_runtime,
            capabilities=capabilities,
            conversation_service=conversation_service,
            activity_maker=init_activity_maker(config.get("activity_maker", {})),
            schedule_manager=schedule_manager,
            world_event_provider=ScheduleWorldProvider(schedule_manager),
            public_diary_provider=CitywalkDiaryProvider(citywalk_report_dir),
        )

        runtime._wire_dependencies()
        runtime._start_background_services(config)
        account.generate_keys()
        return runtime

    def _wire_dependencies(self) -> None:
        self.activity_maker.set_agent(self.agent)
        self.activity_maker.set_system_runtime(self)
        self.gcsm.register_activity_maker(self.activity_maker)
        self.global_speaking_worker.set_capabilities(self.capabilities)
        if self.schedule_manager is not None:
            self.schedule_manager.set_gcsm_ref(self.gcsm)

    def _start_background_services(self, config: Dict) -> None:
        self.gcsm.start_cleanup_task(expiration_seconds=360)
        self.global_speaking_worker.start_if_needed()
        if self.schedule_manager is not None:
            self.schedule_manager.start()

        self.daily_scheduler = DailyScheduler(
            song_knowledge_config=config["music"]["song_knowledge"],
            citywalk_service=CitywalkRuntimeService(
                config["citywalk"],
                vector_store=database.get_vector_store(),
            ),
            song_learner=self.agent.music_manager.auto_song_learner,
            schedule_manager=self.schedule_manager,
        )
        self.daily_scheduler.start()

    async def shutdown(self) -> None:
        if self.daily_scheduler is not None:
            self.daily_scheduler.stop()
            self.daily_scheduler = None
        if self.schedule_manager is not None:
            self.schedule_manager.stop()
        await self.gcsm.stop_cleanup_task()
        await self.global_speaking_worker.stop()


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
