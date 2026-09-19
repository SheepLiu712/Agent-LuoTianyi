"""复用日记能力收集材料、生成正文并按旧来源身份发布。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import src.domain.agent as d
from src.agent.skills.contracts import CharacterNarrative, SkillInvocation
from src.agent.skills.expression._diary_operations import DiaryOperations
from src.agent.skills.expression._dynamic_operations import DynamicOperations
from src.utils.logger import get_logger


@dataclass(frozen=True, slots=True)
class DiaryPublishResult:
    ok: bool
    message: str
    dynamic_id: str | None


class DiaryWritingSkill:
    """包装既有日记提示词与动态落库，不承担调度或用户筛选。"""

    def __init__(
        self,
        diary: DiaryOperations | None,
        dynamics: DynamicOperations,
        narratives: Mapping[str, CharacterNarrative],
    ) -> None:
        self._diary = diary
        self._dynamics = dynamics
        self._narratives = dict(narratives)
        self._logger = get_logger(__name__)

    def available(self) -> bool:
        return self._diary is not None and self._diary.ensure_llm()

    async def compose(self, invocation: SkillInvocation, local_date: date) -> str:
        """生成指定用户和日期的正文；材料或模型不可用时返回空字符串。"""
        if self._diary is None:
            return ""
        owner_user_id = invocation.require_user_id()
        narrative = self._narrative_for(invocation.character_id)
        return await self._diary.generate_diary_body(
            user_id=owner_user_id,
            character_id=invocation.character_id,
            character_name=narrative.name,
            character_persona=narrative.persona,
            speaking_style=narrative.speaking_style,
            target_date=local_date.isoformat(),
        )

    def publish(self, invocation: SkillInvocation, action: d.WriteDiary) -> DiaryPublishResult:
        """按旧链来源身份幂等发布私密、不可评论的日记动态。"""
        source_id = DiaryOperations._diary_source_id(
            invocation.character_id,
            action.owner_user_id,
            action.local_date.isoformat(),
        )
        ok, message, item = self._dynamics.publish_agent_dynamic(
            character_id=invocation.character_id,
            content=action.body,
            source_type="diary",
            source_id=source_id,
            visibility=d.Visibility.PRIVATE.value,
            owner_user_id=action.owner_user_id,
            allow_comment=False,
            idempotent_by_source=True,
        )
        dynamic_id = str(item.get("id") or "") or None if ok and item else None
        if not ok:
            self._logger.warning("日记动态发布失败 source=%s: %s", source_id, message)
        return DiaryPublishResult(bool(ok), str(message), dynamic_id)

    def _narrative_for(self, character_id: str) -> CharacterNarrative:
        try:
            return self._narratives[character_id]
        except KeyError as error:
            raise KeyError(f"角色 {character_id} 未配置叙事资料") from error
