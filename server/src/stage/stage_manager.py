"""管理聊天 Stage 的创建、重连保留和离线回收。"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.agent import InteractionEndingReason
from src.domain.stage import StageState
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned
from .chat_stage import ChatStage

if TYPE_CHECKING:
    from src.agent.facade import Agent
    from src.adapter.websocket import WebSocketAdapter
    from src.system.user_interface.websocket_service import WebSocketConnection


@dataclass(frozen=True)
class _ManagerConfig:
    offline_timeout: float

    @classmethod
    def from_dict(cls, config: dict) -> "_ManagerConfig":
        if not isinstance(config, dict):
            raise TypeError("stage manager config must be a dictionary")
        timeout = config.get("offline_timeout", 60.0)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("offline_timeout must be finite and nonnegative")
        return cls(offline_timeout=timeout)


class StageManager:
    """按用户与角色管理 Stage，持有共享 adapter 及离线回收任务。"""

    def __init__(self, *, get_agent: Callable[[str], Agent], adapter: WebSocketAdapter,
                 config: dict | None = None) -> None:
        """使用 get_agent 取得角色门面；config.offline_timeout 为离线保留秒数，stage 子配置直接下传。"""
        config = {} if config is None else config
        self._config = _ManagerConfig.from_dict(config)
        self._stage_config = config.get("stage", {})
        self._get_agent, self._adapter = get_agent, adapter
        self._stages: dict[tuple[str, str], ChatStage] = {}
        self._connections: dict[ChatStage, WebSocketConnection] = {}
        self._expiry: dict[ChatStage, asyncio.Task[None]] = {}
        self._retiring: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    async def connect(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        """取得或创建 connection 用户与 character_id 的 Stage，完成绑定后返回；保留期内复用原实例。"""
        return await complete_owned(self._connect(connection, character_id))

    async def disconnect(self, connection: WebSocketConnection) -> None:
        """处理 connection 断线，解除其仍有效的绑定并启动离线保留期；旧连接通知不影响重连。"""
        await complete_owned(self._disconnect(connection))

    async def close(self) -> None:
        """停止接入，终止全部 Stage 并解除绑定，等待正在执行的离线回收任务。"""
        if self._closing is None:
            self._closing = asyncio.create_task(self._close(), name="stage-manager-close")
        await asyncio.shield(self._closing)

    async def _connect(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        async with self._lock:
            if self._closed or connection.is_closed or not connection.user_uuid:
                raise ValueError("manager or connection is unavailable")
            key = (connection.user_uuid, character_id)
            stage = self._stages.get(key)
            if stage is None or stage.state in (StageState.TERMINATING, StageState.TERMINATED):
                stage = ChatStage(user_id=key[0], character_id=key[1], agent=self._get_agent(character_id),
                                  adapter=self._adapter, config=self._stage_config)
                self._stages[key] = stage
            timer = self._expiry.pop(stage, None)
            if timer is not None:
                timer.cancel()
            try:
                await self._adapter.bind(stage, connection)
            except BaseException:
                self._schedule_expiry(stage)
                raise
            self._connections[stage] = connection
            return stage

    async def _disconnect(self, connection: WebSocketConnection) -> None:
        async with self._lock:
            connection.mark_disconnected()
            for stage, current in list(self._connections.items()):
                if current is connection:
                    await self._adapter.disconnect(stage, connection)
                    self._connections.pop(stage, None)
                    self._schedule_expiry(stage)

    async def _close(self) -> None:
        async with self._lock:
            self._closed = True
            stages = tuple(self._stages.values())
            self._stages.clear()
            timers = tuple(self._expiry.values())
            self._expiry.clear()
            for timer in timers:
                timer.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
        for stage in stages:
            await self._retire(stage, InteractionEndingReason.SHUTDOWN)
        if self._retiring:
            await asyncio.gather(*tuple(self._retiring), return_exceptions=True)

    def _schedule_expiry(self, stage: ChatStage) -> None:
        old = self._expiry.pop(stage, None)
        if old is not None:
            old.cancel()
        self._expiry[stage] = asyncio.create_task(self._expire(stage), name="stage-offline-expiry")

    async def _expire(self, stage: ChatStage) -> None:
        await asyncio.sleep(self._config.offline_timeout)
        async with self._lock:
            if self._expiry.get(stage) is not asyncio.current_task():
                return
            self._expiry.pop(stage, None)
            key = (stage.user_id, stage.character_id)
            if self._stages.get(key) is stage:
                del self._stages[key]
            # 从可复用集合移除后才开始结束处理；重连可创建新的交互。
            task = asyncio.create_task(self._retire(stage, InteractionEndingReason.USER_LEFT), name="stage-retire")
            self._retiring.add(task)
            task.add_done_callback(self._retiring.discard)

    async def _retire(self, stage: ChatStage, reason: InteractionEndingReason) -> None:
        try:
            result = await stage.terminate(reason)
            if result.error is not None:
                get_logger(__name__).error("Stage retirement failed interaction=%s error=%s", stage.interaction_id, result.error)
        finally:
            await self._adapter.disconnect(stage)
            self._connections.pop(stage, None)
