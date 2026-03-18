from dataclasses import dataclass
from typing import Callable
from typing import TYPE_CHECKING

import redis
from sqlalchemy.orm import Session

from ..database import VectorStore

if TYPE_CHECKING:
    from ..agent.luotianyi_agent import LuoTianyiAgent
    from ..agent.global_chat_stream_manager import GlobalChatStreamManager
    from ..agent.global_speaking_worker import GlobalSpeakingWorker
    from .websocket_service import WebSocketService


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
    redis_client: redis.Redis
    vector_store: VectorStore
    sql_session_factory: Callable[[], Session]
    song_session_factory: Callable[[], Session]

    def open_sql_session(self) -> Session:
        return self.sql_session_factory()

    def open_song_session(self) -> Session:
        return self.song_session_factory()
    