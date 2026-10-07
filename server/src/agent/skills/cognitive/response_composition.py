"""批次回复的生成技能：召回证据并生成角色回复草稿。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from src.agent.context.models import UserContextSnapshot
from src.agent.skills.cognitive.topic_extraction import TopicExtractionSkill
from src.agent.skills.contracts import ComposedReply, ComposedResponse, ReplyDraft, SkillInvocation


class _Memory(Protocol):
    async def search_memory_context_for_topic(self, user_id: str, queries: list[str]): ...


class _Singing(Protocol):
    async def build_sing_plan(
        self,
        character_id: str,
        attempts: list[str],
        *,
        excluded_segments: set[tuple[str, str]] | None = None,
        emotion_context: str = "",
        confirmed_intent: bool = False,
    ): ...

    def get_segment_lyrics(self, character_id: str, song: str, segment: str) -> str: ...


class _ReplyGenerator(Protocol):
    async def generate(
        self,
        *,
        reply_topic: str,
        user_context: UserContextSnapshot,
        conversation_history: str,
        fact_hits: list[str],
        memory_hits: list[str],
        sing_plan: tuple[str, str] | None,
    ) -> tuple[ReplyDraft, ...]: ...


class ResponseCompositionSkill:
    """隐藏召回、选歌、角色化生成和歌词补全，只暴露回复草稿 interface。"""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        memories: Mapping[str, _Memory],
        singing: _Singing,
        generators: Mapping[str, _ReplyGenerator],
        topic_extraction: TopicExtractionSkill,
    ) -> None:
        if not isinstance(config, dict):
            raise TypeError("reply_composition 必须是字典")
        if not memories or set(memories) != set(generators):
            raise ValueError("回复编排要求每个角色同时具备记忆和回复生成器")
        slow = config.get("slow_recall", {})
        if not isinstance(slow, dict):
            raise TypeError("reply_composition.slow_recall 必须是字典")
        self._provisional_after = max(float(slow.get("provisional_after_seconds", 0) or 0), 0.0)
        self._provisional = ReplyDraft(
            content=str(slow.get("provisional_text", "") or "").strip(),
            sound_content=str(slow.get("provisional_sound_content", "") or "").strip(),
            tone=str(slow.get("provisional_tone", "") or "").strip(),
            expression=(str(slow.get("provisional_expression", "") or "").strip() or None),
        )
        self._topic_extraction = topic_extraction
        self._memories = dict(memories)
        self._singing = singing
        self._generators = dict(generators)

    async def compose(
        self,
        invocation: SkillInvocation,
        *,
        user_context: UserContextSnapshot,
        reply_topic: str,
        conversation_history: str,
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> tuple[ReplyDraft, ...]:
        """所有生成回复统一经过提取、召回/选歌、replier。"""
        staged = await self.compose_staged(
            invocation,
            user_context=user_context,
            reply_topic=reply_topic,
            conversation_history=conversation_history,
            excluded_segments=excluded_segments,
        )
        return (await staged.formal()).drafts

    async def compose_staged(
        self,
        invocation: SkillInvocation,
        *,
        user_context: UserContextSnapshot,
        reply_topic: str,
        conversation_history: str,
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> ComposedResponse:
        """召回超时则先给出配置的临时草稿，正式草稿留待调用方继续 await。"""
        user_id = invocation.require_user_id()
        if invocation.cancellation.is_cancelled:
            return ComposedResponse()
        decision = await self._topic_extraction.extract(reply_topic, conversation_history=conversation_history)
        if invocation.cancellation.is_cancelled:
            return ComposedResponse()
        memory_queries = decision.memory_queries
        recall = asyncio.ensure_future(self._recall(invocation.character_id, user_id, memory_queries))

        async def formal() -> ComposedReply:
            return await self._compose_reply(
                invocation=invocation,
                user_context=user_context,
                reply_topic=reply_topic,
                conversation_history=conversation_history,
                sing_attempts=decision.sing_attempts,
                excluded_segments=excluded_segments,
                recall=recall,
            )

        if self._waits_for_slow_recall(memory_queries):
            try:
                await asyncio.wait_for(asyncio.shield(recall), self._provisional_after)
            except asyncio.TimeoutError:
                return ComposedResponse(provisional=(self._provisional,), pending=formal)
        return ComposedResponse(provisional=None, pending=formal)

    def _waits_for_slow_recall(self, memory_queries: tuple[str, ...]) -> bool:
        return bool(memory_queries) and self._provisional_after > 0 and bool(self._provisional.content)

    async def _recall(self, character_id: str, user_id: str, memory_queries: tuple[str, ...]):
        if not memory_queries:
            return None
        return await self._memory_for(character_id).search_memory_context_for_topic(user_id, list(memory_queries))

    async def _compose_reply(
        self,
        *,
        invocation: SkillInvocation,
        user_context: UserContextSnapshot,
        reply_topic: str,
        conversation_history: str,
        sing_attempts: tuple[str, ...],
        excluded_segments: set[tuple[str, str]] | None,
        recall: Awaitable,
    ) -> ComposedReply:
        context = await recall
        if invocation.cancellation.is_cancelled:
            return ComposedReply()
        memory_hits = context.render_for_prompt() if context is not None else []
        hits = tuple(getattr(context, "hits", ()) or ()) if context is not None else ()
        sing_plan = None
        if sing_attempts:
            candidate = await self._singing.build_sing_plan(
                invocation.character_id,
                list(sing_attempts),
                excluded_segments=excluded_segments,
                confirmed_intent=True,
            )
            if candidate and candidate[0] and candidate[1]:
                sing_plan = candidate
        if invocation.cancellation.is_cancelled:
            return ComposedReply()
        drafts = await self._generator_for(invocation.character_id).generate(
            reply_topic=reply_topic,
            user_context=user_context,
            conversation_history=conversation_history,
            memory_hits=memory_hits,
            fact_hits=[],
            sing_plan=sing_plan,
        )
        enriched: list[ReplyDraft] = []
        for draft in drafts:
            if draft.sing is not None:
                if sing_plan is None or not draft.sing[1]:
                    continue
                song, segment = draft.sing
                lyrics = self._singing.get_segment_lyrics(invocation.character_id, song, segment)
                draft = replace(draft, lyrics=lyrics or "")
            enriched.append(draft)
        return ComposedReply(drafts=tuple(enriched), memory_hits=hits)

    def _memory_for(self, character_id: str) -> _Memory:
        try:
            return self._memories[character_id]
        except KeyError as error:
            raise KeyError(f"角色 {character_id} 未配置记忆") from error

    def _generator_for(self, character_id: str) -> _ReplyGenerator:
        try:
            return self._generators[character_id]
        except KeyError as error:
            raise KeyError(f"角色 {character_id} 未配置回复生成器") from error
