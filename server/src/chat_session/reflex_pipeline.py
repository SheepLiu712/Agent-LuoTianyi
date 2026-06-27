from __future__ import annotations

from typing import Awaitable, Callable, TYPE_CHECKING

from src.chat_session.reflex import TouchReflexResponder
from src.domain.chat import ChatInputEvent, ChatInputEventType

if TYPE_CHECKING:
    from src.system.user_interface.types import ChatResponse


class ReflexPipeline:
    """Handles fast, ephemeral reactions before chat-topic planning."""

    def __init__(self, config: dict, touch_responder: TouchReflexResponder | None = None) -> None:
        self.config = config
        self.touch_responder = touch_responder or TouchReflexResponder(config.get("touch", {}))

    def ensure_dependencies(self) -> None:
        """检查反射管线依赖已经初始化。"""
        if self.touch_responder is None:
            raise RuntimeError("ReflexPipeline dependency is missing: touch_responder")

    async def try_handle(
        self,
        event: ChatInputEvent,
        send_reply_callback: Callable[["ChatResponse"], Awaitable[None]],
    ) -> bool:
        if event.event_type == ChatInputEventType.USER_TOUCH:
            return await self.touch_responder.try_reply(event, send_reply_callback)
        return False
