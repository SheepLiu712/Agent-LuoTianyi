"""动态回复的角色化生成与发布，不产生聊天输出。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import src.domain.agent as d
from src.agent.skills.contracts import CharacterNarrative, SkillInvocation
from src.agent.skills.expression._dynamic_operations import DynamicOperations
from src.utils.logger import get_logger


@dataclass(frozen=True)
class DynamicReplyResult:
    """一次评论发布的结果；comment_id 为已落库评论的稳定身份。"""

    ok: bool
    message: str
    comment_id: str | None


class DynamicReplySkill:
    """包装动态能力：按结构化线程生成回复，并按目标身份发布评论。

    线程是唯一输入：事实里的 `messages` 已按「原帖在前、评论随后」排好序，
    因此技能不需要读取 world 的待处理队列，也不需要用户偏好等世界侧上下文。
    """

    def __init__(
        self,
        dynamics: DynamicOperations,
        narratives: Mapping[str, CharacterNarrative],
    ) -> None:
        self._dynamics = dynamics
        self._narratives = dict(narratives)
        self._logger = get_logger(__name__)

    def available(self) -> bool:
        """回复模型是否可用；不可用时回复方面明确失败，记忆方面不受影响。"""
        return bool(self._dynamics.replier.ensure_llm())

    def build_item(self, invocation: SkillInvocation, observation: d.DynamicObserved) -> dict[str, Any]:
        """把一次动态观察还原为回复生成所需的条目视图。"""
        messages = observation.messages
        post = messages[0]
        comments = [self._as_item(invocation, message) for message in messages[1:]]
        target = next(
            (message for message in messages if message.message_id == observation.target_message_id),
            post,
        )
        item = self._as_item(invocation, target)
        item["username"] = item["author_name"]
        item["user_description"] = ""
        item["preferences"] = {}
        item["thread_comments"] = comments
        item["dynamic"] = self._as_item(invocation, post)
        return item

    def target_author_id(self, observation: d.DynamicObserved) -> str:
        """本次判断目标的作者身份，用作回复评论的归属用户。"""
        for message in observation.messages:
            if message.message_id == observation.target_message_id:
                return message.author_ref.actor_id
        return observation.messages[0].author_ref.actor_id

    def already_replied(self, invocation: SkillInvocation, observation: d.DynamicObserved) -> bool:
        """线程里是否已存在角色针对该目标的回复；存在时不得再次发布。"""
        return any(
            message.author_ref.actor_id == invocation.character_id
            and message.parent_message_id == observation.target_message_id
            for message in observation.messages
        )

    async def compose_for_post(self, invocation: SkillInvocation, item: dict[str, Any]) -> str:
        """为动态原帖生成回复正文。"""
        return await self._dynamics.replier.generate_reply_for_post(
            item,
            character_name=self._narrative_for(invocation.character_id).name,
        )

    async def compose_for_comment(self, invocation: SkillInvocation, item: dict[str, Any]) -> tuple[bool, str]:
        """为动态评论生成是否回复的判断与正文。"""
        decision = await self._dynamics.replier.generate_reply_for_comment(
            item,
            character_name=self._narrative_for(invocation.character_id).name,
        )
        should_reply = bool(decision.get("should_reply"))
        body = str(decision.get("reply") or "").strip()
        return should_reply and bool(body), body

    def publish(self, invocation: SkillInvocation, action: d.ReplyDynamic) -> DynamicReplyResult:
        """按目标身份发布评论；已提交时返回评论身份。"""
        if not isinstance(action, d.ReplyDynamic):
            raise TypeError("action 必须是 ReplyDynamic")
        ok, message, item = self._dynamics.publish_agent_comment(
            dynamic_id=action.target.dynamic_id,
            owner_user_id=action.owner_user_id,
            content=action.body,
            character_id=invocation.character_id,
            parent_comment_id=action.target.parent_comment_id,
        )
        comment_id = str((item or {}).get("id") or "") or None if ok else None
        if not ok:
            self._logger.warning(
                "动态回复发布失败 dynamic=%s parent=%s: %s",
                action.target.dynamic_id,
                action.target.parent_comment_id,
                message,
            )
        return DynamicReplyResult(ok=bool(ok), message=str(message), comment_id=comment_id)

    def _as_item(self, invocation: SkillInvocation, message: d.DynamicMessage) -> dict[str, Any]:
        """把领域消息转换为能力层的条目视图，并标注角色自己的消息。"""
        actor_id = message.author_ref.actor_id
        return {
            "id": message.message_id,
            "content": message.text,
            "author_type": "agent" if actor_id == invocation.character_id else "user",
            "author_id": actor_id,
            "author_name": message.author_ref.display_name or actor_id,
        }

    def _narrative_for(self, character_id: str) -> CharacterNarrative:
        try:
            return self._narratives[character_id]
        except KeyError as error:
            raise KeyError(f"角色 {character_id} 未配置叙事资料") from error
