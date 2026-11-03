"""Call-only summary and maintenance skills over immutable final snapshots."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from src.agent.context import ConversationSnapshot
from src.agent.skills.contracts import SkillInvocation
from src.domain.call import CallFinalSnapshot, CallFinalTurn, CallReplyStatus


def render_call_turns(snapshot: CallFinalSnapshot, *, after_turn_seq: int = 0) -> tuple[str, ...]:
    """Keep every completed user fact; include only fully completed formal replies."""
    rendered = []
    for turn in snapshot.completed_turns:
        if turn.turn_seq <= after_turn_seq:
            continue
        text = f"用户：{turn.user_semantic}"
        confirmed = turn.confirmed_agent_text
        if confirmed is None and turn.reply_turn_seq is None and turn.reply_status is CallReplyStatus.COMPLETED:
            confirmed = turn.formal_agent_text
        if confirmed is not None:
            text += f"\n角色：{confirmed}"
        rendered.append(text)
    return tuple(rendered)


@dataclass(frozen=True)
class CallSummaryMaterial:
    """本次通话的只读材料；范围边界取结束维护前的压缩进度。"""

    working: ConversationSnapshot
    accepted_turns: tuple[CallFinalTurn, ...]
    summarized_turn_seq: int


class CallSummaryStatus(str, Enum):
    GENERATED = "generated"
    EMPTY = "empty"
    FAILED = "failed"


@dataclass(frozen=True)
class CallSummaryResult:
    status: CallSummaryStatus
    summary: str | None = None


def _summary_inputs(material: CallSummaryMaterial) -> tuple[str, ...]:
    lines = []
    if material.working.summary.text.strip():
        lines.append(f"本次通话已有摘要：{material.working.summary.text.strip()}")
    present = set()
    reply_anchors = set()
    for entry in material.working.entries:
        if entry.entry_id in present:
            continue
        present.add(entry.entry_id)
        lines.append(f"{entry.source}：{entry.content.text}")
        match = re.fullmatch(r"call-turn-(\d+)-agent-[\w-]+", entry.entry_id)
        if match:
            reply_anchors.add(int(match.group(1)))
    for turn in material.accepted_turns:
        if turn.turn_seq <= material.summarized_turn_seq:
            continue
        entry_id = f"call-turn-{turn.turn_seq}-user"
        if entry_id not in present:
            lines.append(f"用户：{turn.user_semantic}")
            present.add(entry_id)
        anchor = turn.reply_turn_seq or turn.turn_seq
        confirmed = turn.confirmed_agent_text
        if confirmed is None and turn.reply_turn_seq is None and turn.reply_status is CallReplyStatus.COMPLETED:
            confirmed = turn.formal_agent_text
        if confirmed is not None and anchor not in reply_anchors:
            lines.append(f"角色：{confirmed}")
            reply_anchors.add(anchor)
    return tuple(lines)


class CallSummarySkill:
    def __init__(self, config: dict, *, llm_service, characters) -> None:
        module = config.get("llm_module")
        self._models = (
            {
                character_id: llm_service.register_llm_module(f"skill.call_summary.generate.{character_id}", module)
                for character_id in characters
            }
            if module is not None
            else {}
        )

    def supports_character(self, character_id: str) -> bool:
        model = self._models.get(character_id)
        return model is not None and callable(getattr(model, "generate_response", None))

    async def generate(self, invocation: SkillInvocation, *, material: CallSummaryMaterial) -> CallSummaryResult:
        turns = _summary_inputs(material)
        if not turns:
            return CallSummaryResult(CallSummaryStatus.EMPTY)
        model = self._models.get(invocation.character_id)
        if model is None:
            return CallSummaryResult(CallSummaryStatus.FAILED)
        try:
            # 模型适配器拥有既有的有限重试和指数退避。
            response = await model.generate_response(completed_turns=turns)
            summary = response.strip() if isinstance(response, str) else ""
            if summary and len(summary) <= 200:
                return CallSummaryResult(CallSummaryStatus.GENERATED, summary)
        except Exception:
            logging.getLogger(__name__).warning("Call summary generation failed")
        return CallSummaryResult(CallSummaryStatus.FAILED)
