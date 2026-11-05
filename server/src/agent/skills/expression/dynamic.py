"""动态线程、内容生成与持久发布的统一能力。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import src.domain.agent as d
from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.expression._dynamic_operations import DynamicOperations
from src.utils.asyncio_helpers import run_sync_owned
from src.utils.logger import get_logger


class DynamicGenerationError(RuntimeError):
    """动态生成未完成，不能解释成明确忽略。"""


class DynamicPublicationError(RuntimeError):
    """存储未确认动态或评论提交。"""


@dataclass(frozen=True)
class DynamicTarget:
    dynamic_id: str


@dataclass(frozen=True)
class DynamicThread:
    dynamic_id: str
    messages: tuple[d.DynamicMessage, ...]


@dataclass(frozen=True)
class DiaryGenerationMaterial:
    local_date: str
    user_name: str
    user_description: str
    user_preferences: str


@dataclass(frozen=True)
class DynamicWritingRequest:
    kind: str
    instruction: str
    materials: str
    diary: DiaryGenerationMaterial | None = None

    def __post_init__(self):
        if any(
            not isinstance(value, str) or not value.strip() for value in (self.kind, self.instruction, self.materials)
        ):
            raise ValueError("动态写作类型、要求和材料不能为空")


@dataclass(frozen=True)
class DynamicDraft:
    body: str


@dataclass(frozen=True)
class DynamicPublication:
    source: d.DynamicSource
    visibility: d.Visibility
    owner_user_id: str | None
    allow_comment: bool = True
    media_refs: tuple[d.MediaRef, ...] = ()


@dataclass(frozen=True)
class DynamicReplyDraft:
    body: str
    dynamic_id: str
    parent_comment_id: str | None
    owner_user_id: str


@dataclass(frozen=True)
class DynamicReplyDecision:
    draft: DynamicReplyDraft | None
    reason: str


@dataclass(frozen=True)
class ReplyPublication:
    source_id: str


@dataclass(frozen=True)
class PublishReceipt:
    identifier: str
    created: bool


class DynamicSkill:
    def __init__(self, config: dict, *, llm_service, database, narratives) -> None:
        self._database = database
        self._narratives = dict(narratives)
        self._operations = DynamicOperations(config)
        self._operations.create_llm_module(llm_service)
        self._operations.wire_dependencies(database_manager=database)
        module = config.get("diary_composer", {}).get("llm_module")
        self._diary_model = llm_service.register_llm_module("skill.dynamic.diary", module) if module else None

    async def read_thread(self, invocation: SkillInvocation, *, target: DynamicTarget) -> DynamicThread:
        post, comments = await run_sync_owned(
            self._database.dynamic_store.read_thread, invocation.user_id, invocation.character_id, target.dynamic_id
        )
        messages = tuple(
            d.DynamicMessage(
                message_id=row["id"],
                parent_message_id=None if row is post else row.get("parent_comment_id") or post["id"],
                author_ref=d.ActorRef(
                    actor_id=row["author_id"], display_name=row.get("author_name") or row["author_id"]
                ),
                text=row["content"],
                media_refs=tuple(d.MediaRef(media_id=value) for value in row.get("image_refs", ())),
            )
            for row in (post, *comments)
        )
        return DynamicThread(target.dynamic_id, messages)

    async def generate(self, invocation: SkillInvocation, *, request: DynamicWritingRequest) -> DynamicDraft:
        try:
            return await self._generate(invocation, request=request)
        except Exception as error:
            get_logger(__name__).exception("动态生成失败 kind=%s", request.kind)
            raise DynamicGenerationError("动态生成失败") from error

    async def _generate(self, invocation, *, request):
        narrative = self._narratives[invocation.character_id]
        if request.diary is not None:
            if self._diary_model is None:
                raise RuntimeError("agent_runtime.skills.dynamic.diary_composer 未配置")
            material = request.diary
            text = await self._diary_model.generate_response(
                character_name=narrative.name,
                character_persona=narrative.persona,
                speaking_style=narrative.speaking_style,
                user_name=material.user_name,
                diary_date=material.local_date,
                user_description=material.user_description,
                user_preferences=material.user_preferences,
                conversation_materials=request.materials,
            )
        else:
            text = await self._operations.generate_world_dynamic_content(
                character_name=narrative.name,
                character_persona=narrative.persona,
                speaking_style=narrative.speaking_style,
                dynamic_type=request.kind,
                instruction=request.instruction,
                structured_context=request.materials,
            )
        if not isinstance(text, str) or not text.strip():
            raise ValueError("动态生成未返回非空正文")
        return DynamicDraft(text.strip())

    async def generate_reply(self, invocation: SkillInvocation, *, thread: DynamicThread, target_id: str):
        try:
            return await self._generate_reply(invocation, thread=thread, target_id=target_id)
        except Exception as error:
            get_logger(__name__).exception("动态回复生成失败 dynamic_id=%s target=%s", thread.dynamic_id, target_id)
            raise DynamicGenerationError("动态回复生成失败") from error

    async def _generate_reply(self, invocation, *, thread, target_id):
        target = next(message for message in thread.messages if message.message_id == target_id)
        if any(
            message.author_ref.actor_id == invocation.character_id and message.parent_message_id == target_id
            for message in thread.messages
        ):
            return DynamicReplyDecision(None, "already_replied")
        if not self._operations.replier.ensure_llm():
            raise RuntimeError("agent_runtime.skills.dynamic.dynamic_replier 未配置")
        post = thread.messages[0]
        item = self._item(invocation, target)
        item.update(
            username=item["author_name"],
            user_description="",
            preferences={},
            thread_comments=[self._item(invocation, value) for value in thread.messages[1:]],
            dynamic=self._item(invocation, post),
        )
        name = self._narratives[invocation.character_id].name
        if target_id == post.message_id:
            body = await self._operations.replier.generate_reply_for_post(item, character_name=name)
            should_reply = True
        else:
            decision = await self._operations.replier.generate_reply_for_comment(item, character_name=name)
            should_reply, body = decision["should_reply"], decision["reply"]
        if not should_reply:
            return DynamicReplyDecision(None, "no_reply_intent")
        if not isinstance(body, str) or not body.strip():
            raise ValueError("动态回复模型决定回复，但未返回正文")
        owner_user_id = invocation.user_id or target.author_ref.actor_id
        if invocation.user_id is None and owner_user_id in self._narratives:
            raise ValueError("针对角色动态生成回复需要明确用户身份")
        return DynamicReplyDecision(
            DynamicReplyDraft(
                body.strip(),
                thread.dynamic_id,
                None if target_id == post.message_id else target_id,
                owner_user_id,
            ),
            "reply",
        )

    async def publish(
        self, invocation: SkillInvocation, *, draft: DynamicDraft, publication: DynamicPublication
    ) -> PublishReceipt:
        if not publication.source.source_id:
            raise ValueError("动态发布必须声明稳定来源标识")
        if publication.owner_user_id != invocation.user_id:
            raise PermissionError("动态发布归属必须与调用身份一致")
        ok, message, item = await run_sync_owned(
            self._operations.publish_agent_dynamic,
            character_id=invocation.character_id,
            content=draft.body,
            source_type=publication.source.source_type,
            source_id=publication.source.source_id,
            visibility=publication.visibility.value,
            owner_user_id=publication.owner_user_id,
            allow_comment=publication.allow_comment,
            image_refs=[value.media_id for value in publication.media_refs] or None,
            idempotent_by_source=True,
        )
        if not ok or not item or not item.get("id"):
            raise DynamicPublicationError(f"动态发布失败：{message}")
        return PublishReceipt(item["id"], message != "dynamic already exists")

    async def publish_reply(
        self, invocation: SkillInvocation, *, draft: DynamicReplyDraft, publication: ReplyPublication
    ) -> PublishReceipt:
        if not publication.source_id.strip():
            raise ValueError("评论发布必须声明稳定来源标识")
        if draft.owner_user_id != invocation.require_user_id():
            raise PermissionError("评论发布归属必须与调用身份一致")
        identity = str(
            uuid5(
                NAMESPACE_URL,
                repr(
                    (
                        invocation.character_id,
                        draft.owner_user_id,
                        draft.dynamic_id,
                        draft.parent_comment_id,
                        publication.source_id,
                    )
                ),
            )
        )
        try:
            identifier, created = await run_sync_owned(
                self._database.dynamic_store.create_agent_reply,
                identity=identity,
                character_id=invocation.character_id,
                dynamic_id=draft.dynamic_id,
                owner_user_id=draft.owner_user_id,
                parent_comment_id=draft.parent_comment_id,
                content=draft.body,
            )
        except Exception as error:
            get_logger(__name__).exception("动态回复提交失败 dynamic_id=%s", draft.dynamic_id)
            raise DynamicPublicationError("动态回复提交失败") from error
        return PublishReceipt(identifier, created)

    @staticmethod
    def _item(invocation, message):
        actor = message.author_ref
        return {
            "id": message.message_id,
            "content": message.text,
            "author_id": actor.actor_id,
            "author_name": actor.display_name or actor.actor_id,
            "author_type": "agent" if actor.actor_id == invocation.character_id else "user",
        }
