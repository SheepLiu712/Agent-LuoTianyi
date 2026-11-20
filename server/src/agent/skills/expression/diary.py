"""日记材料与私密发布；模型生成复用统一动态能力。"""

from dataclasses import dataclass
from datetime import date

import src.domain.agent as d
from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.expression._diary_materials import DiaryMaterials
from src.agent.skills.expression.dynamic import (
    DiaryGenerationMaterial,
    DynamicDraft,
    DynamicPublication,
    DynamicWritingRequest,
)


@dataclass(frozen=True)
class DiaryDraft:
    body: str
    local_date: date
    owner_user_id: str


class DiarySkill:
    def __init__(self, config: dict, *, dynamic, database) -> None:
        self._dynamic = dynamic
        self._materials = DiaryMaterials(config, database=database)

    async def generate(self, invocation: SkillInvocation, *, local_date: date) -> DiaryDraft:
        if type(local_date) is not date:
            raise TypeError("日记日期必须是本地日期")
        user_id = invocation.require_user_id()
        materials = await self._materials._collect_materials(user_id, invocation.character_id, local_date.isoformat())
        if materials == "今天没有特别的互动记录。":
            return DiaryDraft("", local_date, user_id)
        draft = await self._dynamic.generate(
            invocation,
            request=DynamicWritingRequest(
                kind="diary",
                instruction="根据指定日期的授权材料写日记",
                materials=materials,
                diary=DiaryGenerationMaterial(
                    local_date.isoformat(),
                    self._materials._get_user_name(user_id),
                    self._materials._get_user_description(user_id),
                    self._materials._get_user_preferences(user_id),
                ),
            ),
        )
        body = self._materials._parse_diary_result(draft.body, local_date.isoformat())
        if not body:
            raise ValueError("日记生成没有有效正文")
        return DiaryDraft(body, local_date, user_id)

    async def publish(self, invocation: SkillInvocation, *, draft: DiaryDraft):
        if draft.owner_user_id != invocation.require_user_id():
            raise PermissionError("日记只能发布到调用用户的私密范围")
        source_id = f"diary:{invocation.character_id}:{draft.owner_user_id}:{draft.local_date.isoformat()}"
        return await self._dynamic.publish(
            invocation,
            draft=DynamicDraft(draft.body),
            publication=DynamicPublication(
                source=d.DynamicSource(source_type="diary", source_id=source_id),
                visibility=d.Visibility.PRIVATE,
                owner_user_id=draft.owner_user_id,
                allow_comment=False,
            ),
        )
