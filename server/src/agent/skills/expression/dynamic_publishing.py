"""按角色生成并发布外部动态，不产生聊天输出。"""

from __future__ import annotations

from dataclasses import dataclass

import src.domain.agent as d
from src.capabilities.dynamic.dynamic import DynamicCapability
from src.utils.logger import get_logger


@dataclass(frozen=True)
class DynamicPublishResult:
    """一次动态发布的结果；dynamic_id 为已落库动态的稳定身份。"""

    ok: bool
    message: str
    dynamic_id: str | None


class DynamicPublishingSkill:
    """包装动态能力：生成角色化文案，并按来源身份发布。"""

    def __init__(self, dynamics: DynamicCapability) -> None:
        self._dynamics = dynamics
        self._logger = get_logger(__name__)

    async def compose(self, *, dynamic_type: str, instruction: str, structured_context: str) -> str:
        """按角色上下文生成动态文案；模型不可用或生成失败时返回空字符串。"""
        for name, value in (
            ("dynamic_type", dynamic_type),
            ("instruction", instruction),
            ("structured_context", structured_context),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        return await self._dynamics.generate_world_dynamic_content(
            dynamic_type=dynamic_type,
            instruction=instruction,
            structured_context=structured_context,
        )

    async def publish(self, action: d.PublishDynamic, *, character_id: str) -> DynamicPublishResult:
        """按来源身份幂等发布动态；已存在同来源动态时返回其身份。"""
        if not isinstance(action, d.PublishDynamic):
            raise TypeError("action 必须是 PublishDynamic")
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("character_id 不能为空")
        image_refs = [ref.media_id for ref in action.media_refs] or None
        ok, message, item = self._dynamics.publish_agent_dynamic(
            character_id=character_id,
            content=action.body,
            source_type=action.source.source_type,
            source_id=action.source.source_id,
            visibility=action.visibility.value,
            owner_user_id=action.owner_user_id,
            allow_comment=action.allow_comment,
            image_refs=image_refs,
            idempotent_by_source=True,
        )
        dynamic_id = str(item.get("id") or "") or None if (ok and item) else None
        if not ok:
            self._logger.warning("动态发布失败 source=%s/%s: %s",
                                 action.source.source_type, action.source.source_id, message)
        return DynamicPublishResult(ok=bool(ok), message=str(message), dynamic_id=dynamic_id)
