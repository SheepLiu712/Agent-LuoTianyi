from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..agent.luotianyi_agent import LuoTianyiAgent
    from ..agent.activity_maker import ActivityMaker
    from ..pipeline.global_chat_stream_manager import GlobalChatStreamManager
    from ..pipeline.global_speaking_worker import GlobalSpeakingWorker
    from .websocket_service import WebSocketService
    from ..plugins.schedule.schedule_manager import ScheduleManager


@dataclass
class ServiceHub:
    """WebSocket 运行时依赖容器。

    说明：
    - 长生命周期对象（单例）直接持有
    - 短生命周期对象（数据库 Session）用工厂按需创建
    """

    websocket_service: "WebSocketService"
    gcsm: "GlobalChatStreamManager"
    global_speaking_worker: "GlobalSpeakingWorker"
    agent: "LuoTianyiAgent"
    activity_maker: "ActivityMaker"
    schedule_manager: Optional["ScheduleManager"] = None
