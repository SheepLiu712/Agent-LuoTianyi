"""批次回复的生成技能：召回证据并生成角色回复草稿。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import replace
from typing import Any, Protocol

from src.agent.context.models import UserContextSnapshot
from src.agent.skills.contracts import ComposedReply, ComposedResponse, ReplyDraft


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
        character_id: str,
        memory: _Memory,
        singing: _Singing,
        generator: _ReplyGenerator,
    ) -> None:
        if not isinstance(config, dict):
            raise TypeError("reply_composition 必须是字典")
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("character_id 不能为空")
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
        self._character_id = character_id
        self._memory = memory
        self._singing = singing
        self._generator = generator

    async def compose(
        self,
        *,
        user_id: str,
        user_context: UserContextSnapshot,
        reply_topic: str,
        conversation_history: str,
        memory_queries: tuple[str, ...] = (),
        sing_attempts: tuple[str, ...] = (),
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> tuple[ReplyDraft, ...]:
        """按话题召回记忆、选择演唱片段，并生成有序回复草稿。"""
        reply = await self._compose_reply(
            user_id=user_id,
            user_context=user_context,
            reply_topic=reply_topic,
            conversation_history=conversation_history,
            sing_attempts=sing_attempts,
            excluded_segments=excluded_segments,
            recall=self._recall(user_id, memory_queries),
        )
        return reply.drafts

    async def compose_staged(
        self,
        *,
        user_id: str,
        user_context: UserContextSnapshot,
        reply_topic: str,
        conversation_history: str,
        memory_queries: tuple[str, ...] = (),
        sing_attempts: tuple[str, ...] = (),
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> ComposedResponse:
        """召回超时则先给出配置的临时草稿，正式草稿留待调用方继续 await。"""
        recall = asyncio.ensure_future(self._recall(user_id, memory_queries))

        async def formal() -> ComposedReply:
            return await self._compose_reply(
                user_id=user_id,
                user_context=user_context,
                reply_topic=reply_topic,
                conversation_history=conversation_history,
                sing_attempts=sing_attempts,
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

    async def _recall(self, user_id: str, memory_queries: tuple[str, ...]):
        if not memory_queries:
            return None
        return await self._memory.search_memory_context_for_topic(user_id, list(memory_queries))

    async def _compose_reply(
        self,
        *,
        user_id: str,
        user_context: UserContextSnapshot,
        reply_topic: str,
        conversation_history: str,
        sing_attempts: tuple[str, ...],
        excluded_segments: set[tuple[str, str]] | None,
        recall: Awaitable,
    ) -> ComposedReply:
        context = await recall
        memory_hits = context.render_for_prompt() if context is not None else []
        hits = tuple(getattr(context, "hits", ()) or ()) if context is not None else ()
        sing_plan = None
        if sing_attempts:
            candidate = await self._singing.build_sing_plan(
                self._character_id,
                list(sing_attempts),
                excluded_segments=excluded_segments,
            )
            if candidate and candidate[1]:
                sing_plan = candidate
        drafts = await self._generator.generate(
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
                song, segment = draft.sing
                lyrics = self._singing.get_segment_lyrics(self._character_id, song, segment)
                draft = replace(draft, lyrics=lyrics or "")
            enriched.append(draft)
        return ComposedReply(drafts=tuple(enriched), memory_hits=hits)
