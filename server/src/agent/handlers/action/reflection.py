"""REFLECTION 行动：在一次交互回复后完成认知维护。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.agent.skills.invocation import execution_invocation
from src.agent.skills.reflection import ReflectionSkill
from src.utils.enum_type import ConversationSource


def _reflection_dialogue(prepared_inputs: tuple[d.PreprocessedInput, ...], snapshot) -> str:
    """把本次用户输入与近期 agent 回复拼成记忆提炼依据。"""
    lines = [f"user: {item.text}" for item in prepared_inputs if item.text and item.text.strip()]
    lines.extend(
        f"agent: {entry.content.text}" for entry in snapshot.entries if entry.source == ConversationSource.AGENT.value
    )
    return "\n".join(lines)


def _render_history(snapshot) -> str:
    """把总结和近期对话渲染成记忆技能的历史文本。"""
    lines = [snapshot.summary.text] if snapshot.summary.text else []
    lines.extend(f"{entry.source}: {entry.content.text}" for entry in snapshot.entries)
    return "\n".join(lines)


class ReflectionActionHandler:
    """把一次 InteractionDeadline 的认知维护作为最后一个行动执行。"""

    def __init__(self, character_id: str, reflection: ReflectionSkill, compaction: ConversationCompactionSkill) -> None:
        """绑定角色和共享的记忆、画像及上下文压缩技能。"""
        self._character_id = character_id
        self._reflection = reflection
        self._compaction = compaction

    async def realize(
        self,
        action: d.Action,
        execution_context: d.ExecutionContext,
        outputs: OutputEmitter,
    ) -> d.ActionResult:
        """按当前交互上下文执行记忆提取、压缩和画像更新，不产生用户可见输出。"""
        _ = outputs
        if not isinstance(action, d.Reflection):
            raise TypeError("ReflectionActionHandler 只处理 Reflection")
        context = execution_context.interaction_context
        if context is None or not all(
            hasattr(context, attribute) for attribute in ("identity", "conversation", "recalled_memory")
        ):
            return self._failed(action, d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)
        try:
            if context.identity.user_id is None:
                return self._result(action)

            snapshot = context.conversation.read()
            dialogue = _reflection_dialogue(action.prepared_inputs, snapshot)
            invocation = execution_invocation(self._character_id, execution_context, user_id=context.identity.user_id)
            if dialogue:
                await self._reflection.consolidate_memories(
                    invocation,
                    current_dialogue=dialogue,
                    conversation_history=_render_history(snapshot),
                )
            compaction = await self._compaction.compact(context.conversation)
            if compaction is not None:
                await context.conversation.compact(compaction)
            if snapshot.summary.text or snapshot.entries:
                await self._reflection.update_profile(
                    invocation,
                    summary=snapshot.summary.text,
                    recent_conversation=[f"{entry.source}: {entry.content.text}" for entry in snapshot.entries],
                )
            return self._result(action)
        finally:
            for prepared in action.prepared_inputs:
                context.recalled_memory.remove_by_stimulus_id(prepared.stimulus_id)

    @staticmethod
    def _result(action: d.Reflection) -> d.ActionResult:
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )

    @staticmethod
    def _failed(action: d.Reflection, code: d.ExecutionErrorCode) -> d.ActionResult:
        return d.ActionResult(
            action_id=action.action_id,
            status=(
                d.ActionExecutionStatus.CANCELLED
                if code is d.ExecutionErrorCode.CANCELLED
                else d.ActionExecutionStatus.FAILED
            ),
            error_code=code,
            irreversible_effect_committed=False,
            effect_ref=None,
        )
