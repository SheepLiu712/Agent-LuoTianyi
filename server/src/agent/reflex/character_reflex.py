from __future__ import annotations

from typing import Awaitable, Callable, TYPE_CHECKING

from src.agent.reflex.touch import TouchReflexResponder
from src.domain.chat import ChatInputEvent, ChatInputEventType

if TYPE_CHECKING:
    from src.domain import CharacterProfile
    from src.system.user_interface.types import ChatResponse


class CharacterReflex:
    """角色级反射处理入口。"""

    def __init__(self, character_profile: "CharacterProfile") -> None:
        self.character_profile = character_profile
        self.character_id = character_profile.character_id
        self.config = dict(character_profile.reflex or {})
        touch_config = self.config.get("touch")
        self.touch_responder = TouchReflexResponder(touch_config) if touch_config else None

    def ensure_dependencies(self) -> None:
        """检查角色反射处理依赖已经初始化。"""
        required = {
            "character_profile": self.character_profile,
            "config": self.config,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CharacterReflex dependencies are missing: {', '.join(missing)}")
        if self.touch_responder is not None:
            self.touch_responder.ensure_dependencies()

    async def try_handle(
        self,
        event: ChatInputEvent,
        send_reply_callback: Callable[["ChatResponse"], Awaitable[None]],
    ) -> bool:
        """尝试处理低延迟反射事件，成功时返回 True。"""
        if event.event_type == ChatInputEventType.USER_TOUCH:
            if self.touch_responder is None:
                return False
            return await self.touch_responder.try_reply(event, send_reply_callback)
        return False
