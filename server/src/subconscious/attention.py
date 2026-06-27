from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Protocol

from src.domain import ActionPlan, ActionType, AgentState, MemoryContext, PlannedAction


class TopicLike(Protocol):
    topic_id: str
    topic_content: str
    memory_attempts: list[str]
    fact_constraints: list[str]
    sing_attempts: list[str]


MemorySearch = Callable[[list[str]], Awaitable[MemoryContext]]
FactSearch = Callable[[list[str]], Awaitable[list[str]]]
SingPlanner = Callable[[list[str]], Awaitable[tuple[Optional[str], Optional[str]]]]


@dataclass(frozen=True)
class TopicAttentionPlan:
    """Conscious-layer plan for one legacy chat topic.

    This object is intentionally richer than today's MainChat prompt, so future
    channels can reuse attention decisions without going through WebSocket chat.
    """

    user_id: str
    topic_id: str
    target_character_id: str
    topic_content: str
    conversation_history: str
    memory_context: MemoryContext = field(default_factory=MemoryContext)
    agent_state: AgentState | None = None
    memory_hits: list[str] = field(default_factory=list)
    fact_hits: list[str] = field(default_factory=list)
    sing_plan: tuple[Optional[str], Optional[str]] = (None, None)
    attention_notes: tuple[str, ...] = ()
    action_plan: ActionPlan | None = None


class AttentionPlanner:
    """Selects attention material and coarse actions before style realization."""

    def __init__(self, config: dict, target_character_id: str = "luotianyi") -> None:
        self.config = config
        self.target_character_id = target_character_id

    async def plan_topic_turn(
        self,
        *,
        user_id: str,
        topic: TopicLike,
        conversation_history: str,
        memory_search: MemorySearch,
        fact_search: FactSearch,
        sing_planner: SingPlanner,
        external_context: str | None = None,
        agent_state: AgentState | None = None,
    ) -> TopicAttentionPlan:
        topic_content, attention_notes = self._merge_external_context(
            topic.topic_content,
            external_context,
        )

        memory_task = asyncio.create_task(memory_search(topic.memory_attempts or []))
        fact_task = asyncio.create_task(fact_search(topic.fact_constraints or []))
        sing_task = asyncio.create_task(sing_planner(topic.sing_attempts or []))
        memory_context, fact_hits, sing_plan = await asyncio.gather(memory_task, fact_task, sing_task)
        memory_hits = memory_context.render_for_prompt() # MemoryContext

        actions = [PlannedAction(ActionType.SAY, {"topic_id": topic.topic_id})]
        if sing_plan and sing_plan[0] and sing_plan[1]:
            actions.append(
                PlannedAction(
                    ActionType.SING,
                    {
                        "song": sing_plan[0],
                        "segment": sing_plan[1],
                        "topic_id": topic.topic_id,
                    },
                )
            )

        action_plan = ActionPlan(
            target_character_id=self.target_character_id,
            actions=tuple(actions),
            attention_notes=tuple(attention_notes),
        )
        return TopicAttentionPlan(
            user_id=user_id,
            topic_id=topic.topic_id,
            target_character_id=self.target_character_id,
            topic_content=topic_content,
            conversation_history=conversation_history,
            memory_context=memory_context,
            agent_state=agent_state,
            memory_hits=memory_hits,
            fact_hits=fact_hits,
            sing_plan=sing_plan,
            attention_notes=tuple(attention_notes),
            action_plan=action_plan,
        )

    def _merge_external_context(self, topic_content: str, external_context: str | None) -> tuple[str, list[str]]:
        context = (external_context or "").strip()
        if not context:
            return topic_content, []
        merged = f"{topic_content}\n\n{context}" if topic_content else context
        return merged, ["external_context"]
