import asyncio
import time
from typing import Dict, Iterator, Optional, TYPE_CHECKING, Any, Tuple

from src.system.user_interface.websocket_service import WebSocketConnection
from src.chat_session.chat_pipeline.chat_stream import ChatStream
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.chat_session.dependency.conversation_service import ConversationService
    from src.chat_session.dependency.global_speaking_worker import GlobalSpeakingWorker
    from src.chat_session.dependency.activity_context_provider import ActivityContextProvider
    from src.chat_session.dependency.proactive_topic_maker import ProactiveTopicMaker


class ChatStreamManager:
    """
    管理所有聊天流的单例类。
    负责维护用户与聊天流之间的映射关系，以及提供全局访问接口。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        conversation_service: "ConversationService",
        global_speaking_worker: "GlobalSpeakingWorker",
        proactive_topic_maker: "ProactiveTopicMaker",
        activity_context_provider: "ActivityContextProvider"
    ):
        self.config = config
        self.logger = get_logger(__name__)

        self.conversation_service: "ConversationService" | None = conversation_service
        self.global_speaking_worker: "GlobalSpeakingWorker" | None = global_speaking_worker
        self.proactive_topic_maker: "ProactiveTopicMaker" | None = proactive_topic_maker
        self.activity_context_provider: "ActivityContextProvider" | None = activity_context_provider


        self.user_streams: Dict[Tuple[str, str], ChatStream] = {}
        self.cleanup_task: asyncio.Task | None = None
        lock_stripes = max(1, int(config.get("stream_lock_stripes", 64)))
        self._stream_locks = tuple(asyncio.Lock() for _ in range(lock_stripes))
        self._background_tasks: set[asyncio.Task] = set()
        self._closing = False
        self.default_expiration_seconds = config.get("default_expiration_seconds", 3600)
        self.heartbeat_timeout_seconds = config.get("heartbeat_timeout_seconds", 60)

    def wire_dependencies(
        self,
        *,
        conversation_service: "ConversationService",
        global_speaking_worker: "GlobalSpeakingWorker",
        proactive_topic_maker: "ProactiveTopicMaker",
        activity_context_provider: "ActivityContextProvider",
    ) -> None:
        """注入聊天流管理器创建 ChatStream 所需的依赖。"""
        self.conversation_service = conversation_service
        self.global_speaking_worker = global_speaking_worker
        self.proactive_topic_maker = proactive_topic_maker
        self.activity_context_provider = activity_context_provider
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查聊天流管理器依赖已经初始化。"""
        required = {
            "conversation_service": self.conversation_service,
            "global_speaking_worker": self.global_speaking_worker,
            "proactive_topic_maker": self.proactive_topic_maker,
            "activity_context_provider": self.activity_context_provider,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ChatStreamManager dependencies are missing: {', '.join(missing)}")

    def _stream_lock_for(self, stream_key: Tuple[str, str]) -> asyncio.Lock:
        """Return a bounded lock stripe that serializes mutations for one stream key."""
        return self._stream_locks[hash(stream_key) % len(self._stream_locks)]

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_task_done)

    def _on_background_task_done(self, task: asyncio.Task) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            self.logger.error(f"Chat stream background task failed: {error}")

    async def get_or_register_chat_stream(
        self,
        ws_connection: WebSocketConnection,
        character: Optional[str] = None,
        system_runtime: Optional["SystemRuntime"] = None,
    ) -> ChatStream:
        """
        根据 WebSocket 连接获取对应的聊天流实例。
        如果不存在，则创建一个新的聊天流实例并注册。
        """
        user_uuid = ws_connection.user_uuid
        if user_uuid is None:
            raise ValueError("WebSocketConnection must have a user_uuid for chat stream management.")
        if self._closing:
            raise RuntimeError("Chat stream manager is stopping and cannot accept connections")

        character_id = self._resolve_character_id(character, system_runtime)
        stream_key = (user_uuid, character_id)
        async with self._stream_lock_for(stream_key):
            if self._closing:
                raise RuntimeError("Chat stream manager is stopping and cannot accept connections")
            chat_stream = self.user_streams.get(stream_key)
            if chat_stream is None:
                candidate = ChatStream(
                    self.config.get("chat_stream", {}),
                    ws_connection,
                    character_id=character_id,
                )
                candidate.set_system_runtime(system_runtime)
                try:
                    await candidate.start_if_needed()
                except BaseException:
                    try:
                        await self._stop_stream(candidate, close_connection=False)
                    except Exception as cleanup_error:
                        self.logger.error(
                            f"Failed to clean up partially started chat stream "
                            f"for user_uuid={user_uuid}, character={character_id}: {cleanup_error}"
                        )
                    raise
                self.user_streams[stream_key] = candidate
                chat_stream = candidate
            else:
                chat_stream.set_system_runtime(system_runtime)
                await chat_stream.reconnect(ws_connection)
        if self.proactive_topic_maker is not None and not self._closing:
            login_task = asyncio.create_task(
                self.proactive_topic_maker.on_user_login(user_uuid, chat_stream=chat_stream),
                name=f"chat-stream-login:{user_uuid}:{character_id}",
            )
            self._track_background_task(login_task)
        return chat_stream

    @staticmethod
    def _resolve_character_id(
        character: str | None,
        system_runtime: Optional["SystemRuntime"],
    ) -> str:
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        registry = getattr(agent_runtime, "character_registry", None)
        default_character_id = (
            getattr(agent_runtime, "default_character_id", None)
            or getattr(registry, "default_character_id", None)
            or "luotianyi"
        )
        resolved = character or default_character_id
        if registry is not None:
            registry.resolve_targets((resolved,))
        return resolved

    def get_stream_by_user_uuid(self, user_uuid: str, character: str = "luotianyi") -> ChatStream | None:
        return self.user_streams.get((user_uuid, character))

    def iter_active_streams(self, character_id: str | None = None) -> Iterator[tuple[str, str, ChatStream]]:
        """遍历当前仍在线的聊天流。"""
        for (user_uuid, stream_character_id), chat_stream in list(self.user_streams.items()):
            if character_id is not None and stream_character_id != character_id:
                continue
            if chat_stream is None or chat_stream.is_connection_lost():
                continue
            yield user_uuid, stream_character_id, chat_stream


    def ws_lost_connection(self, ws_connection: WebSocketConnection):
        """
        当 WebSocket 连接丢失时，调用此方法进行清理。
        """
        user_uuid = ws_connection.user_uuid
        if not user_uuid:
            return
        for (stream_user_uuid, _character), chat_stream in list(self.user_streams.items()):
            if stream_user_uuid == user_uuid:
                chat_stream.lost_connection(ws_connection)

    async def _cleanup_once(self, expiration_seconds: int, current_time: float | None = None) -> None:
        """Run one cleanup pass while isolating failures to the affected stream."""
        if current_time is None:
            current_time = time.time()
        current_time_ms = int(current_time * 1000)

        for stream_key, stream in list(self.user_streams.items()):
            try:
                ws_connection = stream.ws_connection
                if (
                    ws_connection
                    and ws_connection.last_ping_time
                    and (current_time_ms - ws_connection.last_ping_time > self.heartbeat_timeout_seconds * 1000)
                ):
                    try:
                        await ws_connection.websocket.close()
                    finally:
                        stream.lost_connection(ws_connection)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.logger.error(f"Failed to close stale chat stream {stream_key}: {error}")

        for stream_key, snapshot_stream in list(self.user_streams.items()):
            try:
                async with self._stream_lock_for(stream_key):
                    chat_stream = self.user_streams.get(stream_key)
                    if chat_stream is not snapshot_stream:
                        continue
                    lost_at = chat_stream.connection_lost_time
                    if lost_at is None or current_time - lost_at <= expiration_seconds:
                        continue
                    await self._stop_stream(chat_stream, close_connection=False)
                    if self.user_streams.get(stream_key) is chat_stream:
                        del self.user_streams[stream_key]
                    user_uuid, character_id = stream_key
                    self.logger.info(
                        f"Cleaned up expired chat stream for user_uuid={user_uuid}, "
                        f"character={character_id}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.logger.error(f"Failed to clean up expired chat stream {stream_key}: {error}")

    async def cleanup_expired_streams(self, expiration_seconds: int = 3600):
        """
        定期清理过期的聊天流实例。
        """
        while True:
            try:
                await self._cleanup_once(expiration_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.logger.error(f"Unexpected chat stream cleanup failure: {error}")
            await asyncio.sleep(60)

    def start_cleanup_task(self, expiration_seconds: Optional[int] = None):
        self.ensure_dependencies()
        if self._closing:
            raise RuntimeError("Chat stream manager is stopping and cannot start cleanup")
        if self.cleanup_task is not None and not self.cleanup_task.done():
            return
        if expiration_seconds is None:
            expiration_seconds = self.default_expiration_seconds
        self.cleanup_task = asyncio.create_task(
            self.cleanup_expired_streams(expiration_seconds),
            name="chat-stream-cleanup",
        )
        self.cleanup_task.add_done_callback(self._on_cleanup_task_done)

    def _on_cleanup_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            self.logger.error(f"Chat stream cleanup task stopped unexpectedly: {error}")

    async def stop_cleanup_task(self):
        task = self.cleanup_task
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                self.logger.info("ChatStreamManager cleanup task cancelled")
            finally:
                if self.cleanup_task is task:
                    self.cleanup_task = None

    async def _stop_stream(self, chat_stream: ChatStream, *, close_connection: bool) -> None:
        stop = getattr(chat_stream, "stop", None)
        if stop is not None:
            await stop(close_connection=close_connection)
            return
        chat_stream.clean_up()

    async def stop_all_streams(self) -> None:
        """Reject new streams and fully stop every registered stream."""
        self._closing = True
        errors: list[str] = []

        try:
            await self.stop_cleanup_task()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            errors.append(f"cleanup task: {error}")

        background_tasks = list(self._background_tasks)
        for task in background_tasks:
            if not task.done():
                task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
            self._background_tasks.difference_update(background_tasks)

        acquired_locks: list[asyncio.Lock] = []
        try:
            for lock in self._stream_locks:
                await lock.acquire()
                acquired_locks.append(lock)

            for stream_key, chat_stream in list(self.user_streams.items()):
                try:
                    await self._stop_stream(chat_stream, close_connection=True)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    errors.append(f"stream {stream_key}: {error}")
                    continue
                if self.user_streams.get(stream_key) is chat_stream:
                    del self.user_streams[stream_key]
        finally:
            for lock in reversed(acquired_locks):
                lock.release()

        if errors:
            raise RuntimeError("Chat stream shutdown failed: " + "; ".join(errors))


chat_stream_manager: ChatStreamManager | None = None


def get_GCSM() -> ChatStreamManager:
    global chat_stream_manager
    if chat_stream_manager is None:
        raise RuntimeError("ChatStreamManager has not been initialized.")
    return chat_stream_manager
