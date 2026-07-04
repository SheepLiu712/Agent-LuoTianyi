from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Awaitable, Callable, Optional, Protocol

from src.domain import ActionPlan, ActionType, AgentState, MemoryContext, PlannedAction
from src.system.observability import get_observability_service, get_trace_context


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

        memory_attempts = topic.memory_attempts or []
        fact_constraints = topic.fact_constraints or []
        sing_attempts = topic.sing_attempts or []

        memory_task = asyncio.create_task(self._timed_memory_search(memory_search, memory_attempts))
        fact_task = asyncio.create_task(self._timed_fact_search(fact_search, fact_constraints))
        sing_task = asyncio.create_task(self._timed_sing_plan(sing_planner, sing_attempts))
        (memory_context, memory_duration_ms), (fact_hits, fact_duration_ms), (sing_plan, sing_duration_ms) = await asyncio.gather(
            memory_task,
            fact_task,
            sing_task,
        )
        memory_hits = memory_context.render_for_prompt() # MemoryContext
        self._record_attention_events(
            user_id=user_id,
            topic=topic,
            topic_content=topic_content,
            memory_context=memory_context,
            memory_duration_ms=memory_duration_ms,
            fact_hits=fact_hits,
            fact_duration_ms=fact_duration_ms,
            sing_plan=sing_plan,
            sing_duration_ms=sing_duration_ms,
        )

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

    async def _timed_memory_search(
        self,
        memory_search: MemorySearch,
        memory_attempts: list[str],
    ) -> tuple[MemoryContext, float]:
        start = time.perf_counter()
        result = await memory_search(memory_attempts)
        return result, (time.perf_counter() - start) * 1000

    async def _timed_fact_search(
        self,
        fact_search: FactSearch,
        fact_constraints: list[str],
    ) -> tuple[list[str], float]:
        start = time.perf_counter()
        result = await fact_search(fact_constraints)
        return result, (time.perf_counter() - start) * 1000

    async def _timed_sing_plan(
        self,
        sing_planner: SingPlanner,
        sing_attempts: list[str],
    ) -> tuple[tuple[Optional[str], Optional[str]], float]:
        start = time.perf_counter()
        result = await sing_planner(sing_attempts)
        return result, (time.perf_counter() - start) * 1000

    def _record_attention_events(
        self,
        *,
        user_id: str,
        topic: TopicLike,
        topic_content: str,
        memory_context: MemoryContext,
        memory_duration_ms: float,
        fact_hits: list[str],
        fact_duration_ms: float,
        sing_plan: tuple[Optional[str], Optional[str]],
        sing_duration_ms: float,
    ) -> None:
        observability = get_observability_service()
        if observability is None:
            return
        trace_context = get_trace_context()
        trace_id = trace_context.get("trace_id")
        topic_id = getattr(topic, "topic_id", None)
        hit_queries = set()
        for hit in memory_context.hits:
            hit_queries.add(hit.query)
            observability.record_memory_trace_event(
                trace_id=trace_id,
                user_id=user_id,
                topic_id=topic_id,
                event_type="memory_recall",
                item_type=str(hit.memory_type or hit.source or "memory"),
                command_text=hit.query,
                content_text=hit.rendered_text,
                source_context=topic_content,
                result={
                    "score": hit.score,
                    "source": hit.source,
                    "memory_record_id": hit.memory_record_id,
                    "vector_id": hit.vector_id,
                },
                duration_ms=memory_duration_ms,
                annotation_required=True,
            )
        for query in topic.memory_attempts or []:
            if query in hit_queries:
                continue
            observability.record_memory_trace_event(
                trace_id=trace_id,
                user_id=user_id,
                topic_id=topic_id,
                event_type="memory_recall",
                item_type="no_hit",
                command_text=query,
                content_text="",
                source_context=topic_content,
                result={"hit_count": 0},
                duration_ms=memory_duration_ms,
                annotation_required=True,
            )
        if fact_hits:
            for fact in fact_hits:
                observability.record_memory_trace_event(
                    trace_id=trace_id,
                    user_id=user_id,
                    topic_id=topic_id,
                    event_type="fact_result",
                    item_type="song_fact",
                    command_text="\n".join(topic.fact_constraints or []),
                    content_text=fact,
                    source_context=topic_content,
                    result={"fact_count": len(fact_hits)},
                    duration_ms=fact_duration_ms,
                    annotation_required=False,
                )
        if sing_plan and (sing_plan[0] or sing_plan[1]):
            observability.record_memory_trace_event(
                trace_id=trace_id,
                user_id=user_id,
                topic_id=topic_id,
                event_type="sing_result",
                item_type="sing_plan",
                command_text="\n".join(topic.sing_attempts or []),
                content_text=" / ".join(part for part in sing_plan if part),
                source_context=topic_content,
                result={"song": sing_plan[0], "segment": sing_plan[1]},
                duration_ms=sing_duration_ms,
                annotation_required=False,
            )

    def _merge_external_context(self, topic_content: str, external_context: str | None) -> tuple[str, list[str]]:
        context = (external_context or "").strip()
        if not context:
            return topic_content, []
        merged = f"{topic_content}\n\n{context}" if topic_content else context
        return merged, ["external_context"]
