from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, List, Optional, TYPE_CHECKING


from src.utils.logger import get_logger
from src.utils.asyncio_helpers import (
    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
    cancel_task_once,
    wait_for_owned_tasks,
)
from src.domain.chat import ChatInputEvent, ChatInputEventType
from src.system.user_interface.types import WSEventType

from src.chat_session.chat_pipeline.topic_planner import TopicPlanner
from src.chat_session.chat_pipeline.topic_replier import TopicReplier
from src.chat_session.chat_pipeline.ingress_helper import IngressHelper
from src.chat_session.chat_pipeline.reflection_worker import ReflectionWorker

if TYPE_CHECKING:
    from src.chat_session.dependency.conversation_service import ConversationContextSnapshot
    from src.system.system_runtime import SystemRuntime
    from src.system.user_interface.types import ChatResponse
    from src.system.user_interface.websocket_service import WebSocketConnection


class ChatStream:
    STATE_WAITING = "waiting"
    STATE_REFLECTION = "reflection"
    STATE_LISTENING = "listening"
    STATE_THINKING = "thinking"

    def __init__(self, config: dict, ws_connection: "WebSocketConnection", character_id: str = "luotianyi"):
        self.config = config
        self.ws_connection = ws_connection
        self.user_name: str = ws_connection.user_name
        self.user_uuid: str = ws_connection.user_uuid
        self.character_id: str = character_id or "luotianyi"
        self.recent_sung_segments: deque[tuple[str, str]] = deque(maxlen=10)
        self.logger = get_logger(f"{self.user_name}ChatStream")

        self.system_runtime: Optional["SystemRuntime"] = None
        self.connection_lost_time = None
        self.ingress_helper = IngressHelper(
            config.get("ingress_helper", {}),
            username=self.user_name,
            user_id=self.user_uuid,
            character_id=self.character_id,
            send_reply_callback=self.feed_response
        )
        self.topic_planner = TopicPlanner(
            config.get("topic_planner", {}),
            username=self.user_name,
            user_id=self.user_uuid,
            character_id=self.character_id,
            context_provider=self.get_conversation_context
        )
        self.reflection_worker = ReflectionWorker(
            config.get("reflection_worker", {}),
            username=self.user_name,
            user_id=self.user_uuid,
            character_id=self.character_id,
        )
        self.topic_replier = TopicReplier(
            config.get("topic_replier", {}),
            username=self.user_name,
            user_id=self.user_uuid,
            character_id=self.character_id,
            context_provider=self.get_conversation_context,
            reflection_submitter=self.reflection_worker.submit_completed_turn,
            recent_sung_segments=self.recent_sung_segments,
        )
        self.reflection_worker.set_reply_topic_callback(self.topic_replier.add_topic)
        self.ingress_helper.set_msg_consumer(self.topic_planner.feed_unread_message)
        self.topic_planner.set_topic_consumer(self.topic_replier.add_topic)
        self.topic_replier.set_change_state_callback(self.change_state)
        self.topic_replier.set_send_reply_callback(self.feed_response)

        self.response_queue_maxsize = max(
            1,
            int(config.get("response_queue_maxsize", 256)),
        )
        self.response_queue: asyncio.Queue[ChatResponse] = asyncio.Queue(
            maxsize=self.response_queue_maxsize,
        )
        self.response_sender_task: asyncio.Task | None = None
        self.context_snapshot: "ConversationContextSnapshot | None" = None
        self.context_snapshot_ts_type: str = "elapsed"
        self.context_initialized: bool = False

        self.state = self.STATE_WAITING
        self.state_lock = asyncio.Lock()
        self.last_response_active_ts: float | None = None
        self._stop_lock = asyncio.Lock()
        self._closing = False
        self._stopped = False
        self.shutdown_timeout_seconds = max(
            0.001,
            float(
                config.get(
                    "shutdown_timeout_seconds",
                    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
                )
            ),
        )

    def record_sung_segment(self, song_name: str, segment: str) -> None:
        self.recent_sung_segments.append((song_name, segment))

    async def get_recent_conversation_context(self) -> str:
        payload = await self.get_conversation_context(force_refresh=False, ret_type="dict")
        if not isinstance(payload, dict):
            return ""
        recent = payload.get("recent_conversation") or []
        return "\n".join(str(item) for item in recent if str(item).strip())

    def set_system_runtime(self, system_runtime: "SystemRuntime"):
        if system_runtime is None:
            self.logger.warning("Setting system runtime to None, chat stream cannot function properly")
            return
        if self.system_runtime is not None and self.system_runtime != system_runtime:
            self.logger.warning("System runtime is already set, overwriting with new value")
        self.system_runtime = system_runtime
        self.ingress_helper.set_system_runtime(system_runtime)
        self.topic_planner.set_system_runtime(system_runtime)
        self.topic_replier.set_system_runtime(system_runtime)
        self.reflection_worker.set_system_runtime(system_runtime)

    def ensure_dependencies(self) -> None:
        """检查 ChatStream 和内部 pipeline worker 依赖已经初始化。"""
        required = {
            "ws_connection": self.ws_connection,
            "user_uuid": self.user_uuid,
            "system_runtime": self.system_runtime,
            "ingress_helper": self.ingress_helper,
            "topic_planner": self.topic_planner,
            "topic_replier": self.topic_replier,
            "reflection_worker": self.reflection_worker,
            "response_queue": self.response_queue,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ChatStream dependencies are missing: {', '.join(missing)}")
        self.ingress_helper.ensure_dependencies()
        self.topic_planner.ensure_dependencies()
        self.topic_replier.ensure_dependencies()
        self.reflection_worker.ensure_dependencies()

    async def start_if_needed(self):
        """启动常驻消息处理协程（仅启动一次）。"""
        if self._closing:
            raise RuntimeError("Chat stream is stopping and cannot be started")
        self.ensure_dependencies()
        await self.initialize_context()
        self.ingress_helper.start_processing()
        self.topic_planner.start_processing()
        self.reflection_worker.start_processing()
        self.topic_replier.start_processing()
        self._start_response_sender()

    async def feed_event(self, event: ChatInputEvent):
        """接收 service 层转换后的聊天事件，并交给 ingress worker。"""
        if self._closing:
            raise RuntimeError("Chat stream is stopping and cannot accept events")
        await self.ingress_helper.put(event)

    def try_feed_event(self, event: ChatInputEvent) -> bool:
        """Try to accept a WebSocket event without waiting for queue capacity."""
        if self._closing:
            return False
        return self.ingress_helper.put_nowait(event)
    
    async def feed_response(self, response: ChatResponse):
        """接收 topic replier 生成的回复，并发送给用户。"""
        if self._closing:
            raise RuntimeError("Chat stream is stopping and cannot accept responses")
        await self.response_queue.put(response)

    async def get_conversation_context(
        self,
        *,
        force_refresh: bool = True,
        ret_type: str = "str",
        ts_type: str = "elapsed",
    ) -> str | dict[str, Any]:
        if self.system_runtime is None:
            self.logger.warning("System runtime is not available, cannot load conversation context")
            return "" if ret_type == "str" else {}

        if force_refresh or self.context_snapshot is None or self.context_snapshot_ts_type != ts_type:
            self.context_snapshot = await self.system_runtime.conversation_service.get_context_snapshot(
                self.user_uuid,
                character_id=self.character_id,
                ts_type=ts_type,
            )
            self.context_snapshot_ts_type = ts_type

        if ret_type == "str":
            return self.context_snapshot.text
        return self.context_snapshot.as_prompt_payload()

    async def initialize_context(self, *, force: bool = False) -> None:
        if self.context_initialized and not force:
            return
        if self.system_runtime is None:
            self.logger.warning("System runtime is not available, cannot initialize conversation context")
            return
        self.context_snapshot = await self.system_runtime.conversation_service.initialize_context_snapshot(
            self.user_uuid,
            character_id=self.character_id,
            ts_type="elapsed",
        )
        self.context_snapshot_ts_type = "elapsed"
        self.context_initialized = True

    async def response_sender_loop(self):
        while True:
            response = None
            try:
                response = await self.response_queue.get()
                while True:
                    sent = await self._send_response(response)
                    if sent:
                        break
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.logger.info("Response sender task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in response sender loop: {e}")
                await asyncio.sleep(1)
            finally:
                if response is not None:
                    self.response_queue.task_done()

    async def change_state(self, thinking: Optional[bool] = None, speaking: Optional[bool] = None):
        async with self.state_lock:
            if thinking == True:  # 由replier调用，进入思考状态时必然更新状态
                self.state = self.STATE_THINKING
                await self._send_agent_state(self.STATE_THINKING)
                return
            if speaking == True:  # 由chat_stream的_send_response调用，此时如果不在思考，则认为进入WAITING状态
                if not self.topic_replier.is_processing and self.state != self.STATE_WAITING:
                    self.state = self.STATE_WAITING
                    await self._send_agent_state(self.STATE_WAITING)
                return
            if thinking == False:
                if self.state != self.STATE_WAITING:
                    self.state = self.STATE_WAITING
                    await self._send_agent_state(self.STATE_WAITING)
                return

    async def _send_response(self, response: ChatResponse) -> bool:
        self.last_response_active_ts = time.monotonic()
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return False
        ws_service = self.system_runtime.websocket_service if self.system_runtime else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send response")
            return False
        try:
            await self.change_state(speaking=True)  # 发送回复前更新状态
            event = ws_service._make_event(
                WSEventType.AGENT_MESSAGE,
                response.model_dump() if hasattr(response, "model_dump") else response.dict(),
            )
            await self.ws_connection.websocket.send_json(event)
            return True
        except Exception as e:
            self.logger.warning(f"Send response failed, will retry: {e}")
            return False

    def seconds_since_last_response(self) -> float:
        """返回距离上次调用 _send_response 过去的秒数；从未发送过则视为空闲。"""
        if self.last_response_active_ts is None:
            return float("inf")
        return time.monotonic() - self.last_response_active_ts

    def seconds_until_proactive_idle(self, min_idle_seconds: float) -> float:
        """返回距离允许主动发言还需要等待的秒数。"""
        if self.last_response_active_ts is None:
            return 0.0
        return max(0.0, float(min_idle_seconds) - self.seconds_since_last_response())

    def can_dispatch_proactive(self, min_idle_seconds: float) -> bool:
        """聊天流足够空闲时才允许派发主动话题。"""
        return self.seconds_until_proactive_idle(min_idle_seconds) <= 0

    async def _send_agent_state(self, state: str) -> bool:
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return False
        ws_service = self.system_runtime.websocket_service if self.system_runtime else None
        if ws_service is None:
            self.logger.warning("WebSocket service is not available, cannot send agent state")
            return False
        try:
            self.logger.info(f"Sending agent state change event: {state}")
            event = ws_service._make_event(
                WSEventType.AGENT_STATE_CHANGED,
                {"state": state},
            )
            await self.ws_connection.websocket.send_json(event)
            return True
        except Exception as e:
            self.logger.warning(f"Send agent state failed, will retry: {e}")
            return False

    def _start_response_sender(self):
        if self.response_sender_task is None or self.response_sender_task.done():
            self.response_sender_task = asyncio.create_task(self.response_sender_loop())
            self.logger.info("Started response sender task")


    ####### 下方为连接管理相关方法 #######

    def owns_connection(self, ws_connection: "WebSocketConnection") -> bool:
        """Return whether ``ws_connection`` is still the stream's active connection."""
        return self.ws_connection is ws_connection

    def lost_connection(self, ws_connection: "WebSocketConnection | None" = None) -> bool:
        """Mark the stream offline only when the active connection was lost."""
        if ws_connection is not None and not self.owns_connection(ws_connection):
            return False
        if self.ws_connection is None:
            return False
        self.ws_connection = None
        self.connection_lost_time = time.time()
        return True

    def is_connection_lost(self):
        """检查连接是否丢失"""
        return self.ws_connection is None

    async def reconnect(self, new_ws_connection: "WebSocketConnection"):
        """用户重连时调用，更新 WebSocket 连接"""
        if self._closing:
            raise RuntimeError("Chat stream is stopping and cannot reconnect")
        self.logger.info(f"User {self.user_name} reconnected")
        self.ws_connection = new_ws_connection
        self.user_name = new_ws_connection.user_name if new_ws_connection else self.user_name
        self.connection_lost_time = None
        self.state = self.STATE_WAITING
        await self.start_if_needed()

    def _worker_task_bindings(self):
        return (
            (self.ingress_helper, "ingress_worker_task"),
            (self.topic_planner, "processor_task"),
            (self.topic_replier, "processor_task"),
            (self.reflection_worker, "processor_task"),
            (self, "response_sender_task"),
        )

    def clean_up(self):
        """Request cancellation of all stream workers without waiting for completion."""
        for owner, attribute in self._worker_task_bindings():
            task = getattr(owner, attribute, None)
            if task is not None and not task.done():
                task.cancel()

    async def stop(self, *, close_connection: bool = True) -> None:
        """Stop the stream completely; failed steps remain retryable."""
        async with self._stop_lock:
            if self._stopped:
                return

            self._closing = True
            errors: list[str] = []
            connection = self.ws_connection
            if close_connection and connection is not None and connection.websocket is not None:
                try:
                    await connection.websocket.close()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    errors.append(f"websocket close failed: {error}")
                else:
                    self.lost_connection(connection)

            bindings = self._worker_task_bindings()
            tasks = []
            for owner, attribute in bindings:
                task = getattr(owner, attribute, None)
                if task is not None:
                    cancel_task_once(task)
                    tasks.append(task)

            if tasks:
                done, pending = await wait_for_owned_tasks(
                    tasks,
                    timeout_seconds=self.shutdown_timeout_seconds,
                )
                for task in done:
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception as error:
                        errors.append(f"worker stop failed: {error}")
                if pending:
                    errors.append(f"{len(pending)} worker task(s) still stopping")

            for owner, attribute in bindings:
                task = getattr(owner, attribute, None)
                if task is not None and task.done():
                    setattr(owner, attribute, None)

            if errors:
                raise RuntimeError("; ".join(errors))

            if connection is not None and self.ws_connection is connection:
                self.lost_connection(connection)
            self._stopped = True
