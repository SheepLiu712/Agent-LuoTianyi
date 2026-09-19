"""动态观察事实的角色决策：是否回复，以及独立提交记忆。"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.cognitive.dynamic_topic_memory import DynamicTopicMemorySkill
from src.agent.skills.expression.dynamic_reply import DynamicReplySkill
from src.agent.skills.invocation import handling_invocation
from src.utils.logger import get_logger

DYNAMIC_MEMORY_TRACE_PREFIX = "dynamic"


class DynamicObservedHandler:
    """读结构化线程决定回复或明确忽略，并独立写入记忆。

    记忆先于回复提交且失败隔离：回复失败不会让记忆批次失败；
    「已存在角色回复」与「模型判断不回复」都经处理结算明确表达，不产生计划。
    """

    def __init__(
        self,
        character_id: str,
        reply: DynamicReplySkill,
        memory: DynamicTopicMemorySkill,
    ) -> None:
        self._character_id = character_id
        self._reply = reply
        self._memory = memory
        self._logger = get_logger(__name__)

    async def handle(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
    ) -> d.HandlingReport:
        """处理一次动态观察；回复不可用或决定忽略时都不冒充已回复。"""
        stimulus = request.stimulus
        if not isinstance(stimulus, d.DynamicObserved):
            raise TypeError("DynamicObservedHandler 只处理 DynamicObserved")
        invocation = handling_invocation(request, plans.context)
        await self._write_memory(invocation, stimulus)
        if self._reply.already_replied(invocation, stimulus):
            self._logger.info(
                "线程中已存在角色回复，不再重复发布 dynamic=%s target=%s",
                stimulus.dynamic_id,
                stimulus.target_message_id,
            )
            return self._report(request, d.HandlingRequestStatus.COMPLETED, None, (stimulus.stimulus_id,))
        if not self._reply.available():
            self._logger.warning("动态回复模型不可用 dynamic=%s", stimulus.dynamic_id)
            return self._report(request, d.HandlingRequestStatus.FAILED, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE, ())
        item = self._reply.build_item(invocation, stimulus)
        is_post = stimulus.target_kind is d.DynamicTargetKind.POST
        body = await self._reply.compose_for_post(invocation, item) if is_post else ""
        if not is_post:
            should_reply, body = await self._reply.compose_for_comment(invocation, item)
        else:
            should_reply = bool(body.strip())
        if not should_reply or not body.strip():
            self._logger.info(
                "明确忽略本次动态互动 dynamic=%s target=%s",
                stimulus.dynamic_id,
                stimulus.target_message_id,
            )
            return self._report(request, d.HandlingRequestStatus.COMPLETED, None, (stimulus.stimulus_id,))
        action = d.ReplyDynamic(
            action_id=str(uuid4()),
            body=body,
            target=d.DynamicReplyTarget(
                dynamic_id=stimulus.dynamic_id,
                parent_comment_id=(
                    stimulus.target_message_id if stimulus.target_kind is d.DynamicTargetKind.COMMENT else None
                ),
            ),
            owner_user_id=self._reply.target_author_id(stimulus),
        )
        receipt = await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(action,),
            )
        )
        return self._report(
            request, d.HandlingRequestStatus.COMPLETED, None, (stimulus.stimulus_id,), plans=(receipt.plan_id,)
        )

    async def _write_memory(self, invocation, stimulus: d.DynamicObserved) -> None:
        """独立提交记忆；失败只记录，不影响回复方面。"""
        target = next(
            (message for message in stimulus.messages if message.message_id == stimulus.target_message_id),
            stimulus.messages[0],
        )
        post = stimulus.messages[0]
        history = "" if post.message_id == target.message_id else f"动态正文：{post.text}"
        source_context = f"{history}\n\n当前内容：\n{target.text}".strip()
        try:
            await self._memory.write(
                replace(invocation, user_id=target.author_ref.actor_id),
                current_dialogue=f"user: {target.text}",
                conversation_history=history,
                trace_id=f"{DYNAMIC_MEMORY_TRACE_PREFIX}:{target.message_id}",
                source_context=source_context,
                topic_id=target.message_id,
            )
        except Exception:
            self._logger.exception("动态记忆写入失败 target=%s", target.message_id)

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        status: d.HandlingRequestStatus,
        error_code: d.HandlingErrorCode | None,
        consumed: tuple[str, ...],
        *,
        plans: tuple[str, ...] = (),
    ) -> d.HandlingReport:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=plans,
            error_code=error_code,
            retryable=False,
        )
