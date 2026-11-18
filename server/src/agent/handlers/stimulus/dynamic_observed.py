"""动态观察事实的角色决策：是否回复，以及独立提交记忆。"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.expression.dynamic import DynamicGenerationError, DynamicSkill, DynamicThread
from src.agent.skills.invocation import handling_invocation
from src.agent.skills.memory_write import MemoryEvent, MemoryScope, MemoryWriteSkill
from src.utils.logger import get_logger


class DynamicObservedHandler:
    """读结构化线程决定回复或明确忽略，并独立写入记忆。

    记忆先于回复提交且失败隔离：回复失败不会让记忆批次失败；
    「已存在角色回复」与「模型判断不回复」都经处理结算明确表达，不产生计划。
    """

    def __init__(
        self,
        character_id: str,
        reply: DynamicSkill,
        memory: MemoryWriteSkill,
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
        try:
            decision = await self._reply.generate_reply(
                invocation,
                thread=DynamicThread(stimulus.dynamic_id, stimulus.messages),
                target_id=stimulus.target_message_id,
            )
        except DynamicGenerationError:
            return self._report(request, d.HandlingRequestStatus.FAILED, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE, ())
        if decision.draft is None:
            self._logger.info("明确忽略动态互动 target=%s reason=%s", stimulus.target_message_id, decision.reason)
            return self._report(request, d.HandlingRequestStatus.COMPLETED, None, (stimulus.stimulus_id,))
        draft = decision.draft
        action = d.ReplyDynamic(
            action_id=str(uuid4()),
            body=draft.body,
            target=d.DynamicReplyTarget(dynamic_id=draft.dynamic_id, parent_comment_id=draft.parent_comment_id),
            owner_user_id=draft.owner_user_id,
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
        try:
            await self._memory.remember_event(
                replace(invocation, user_id=target.author_ref.actor_id),
                event=MemoryEvent(
                    source="dynamic",
                    source_id=f"{stimulus.dynamic_id}:{target.message_id}",
                    occurred_at=stimulus.occurred_at,
                    body=target.text,
                    background=history,
                    scope=MemoryScope.USER,
                ),
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
