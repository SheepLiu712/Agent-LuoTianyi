"""批次回复的生成技能：召回证据并生成角色回复草稿。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from src.agent.main_chat import SongSegmentChat
from src.agent.text_cleaning import build_sound_content
from src.domain.memory_context import MemoryHit


class _Mind(Protocol):
    async def search_memory_context_for_topic(self, user_id: str, queries: list[str]): ...
    async def build_sing_plan_for_topic(
        self, attempts: list[str], excluded_segments=None, emotion_context: str = ""
    ): ...


class _Conscious(Protocol):
    async def generate_topic_reply_for_pipeline(
        self,
        user_id: str,
        topic_content: str,
        memory_hits=None,
        fact_hits=None,
        sing_plan=None,
        conversation_history=None,
    ): ...


class _Runtime(Protocol):
    mind: _Mind
    conscious: _Conscious
    capability_manager: Any


@dataclass(frozen=True)
class ReplyDraft:
    """一条已生成的回复草稿；sing 非空表示演唱，否则为说话。"""

    content: str
    sound_content: str
    tone: str
    expression: str | None
    sing: tuple[str, str] | None = None
    lyrics: str = ""


@dataclass(frozen=True)
class ComposedReply:
    """一次生成的完整回复草稿及其所依据的召回命中。"""

    drafts: tuple[ReplyDraft, ...] = ()
    memory_hits: tuple[MemoryHit, ...] = ()


@dataclass
class ComposedResponse:
    """两阶段生成的内部结果：可选临时草稿，以及是否仍需等待正式结果。

    provisional 为 None 表示本次无需先行回复；awaits_formal 为 True 时调用方
    必须再 await formal() 取得正式草稿。该类型不出现在任何公开接口上。
    """

    provisional: tuple[ReplyDraft, ...] | None = None
    pending: Callable[[], Awaitable[ComposedReply]] | None = None
    _settled: ComposedReply | None = field(default=None, init=False, repr=False)

    @property
    def awaits_formal(self) -> bool:
        """返回是否还有尚未取得的正式结果。"""
        return self.pending is not None

    async def formal(self) -> ComposedReply:
        """取得正式结果；已取得时返回同一结果，不重复生成。"""
        if self._settled is None:
            if self.pending is None:
                self._settled = ComposedReply()
            else:
                pending, self.pending = self.pending, None
                self._settled = await pending()
        return self._settled


class ResponseCompositionSkill:
    """包装角色潜意识的召回与意识的回复生成，输出与旧链路等价的回复草稿。"""

    def __init__(self, config: dict[str, Any], runtime_provider: Callable[[str], _Runtime]) -> None:
        """校验本层 config 并绑定按角色解析潜意识/意识的提供者。"""
        if not isinstance(config, dict):
            raise TypeError("reply_composition 必须是字典")
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
        self._runtime_provider = runtime_provider

    async def compose(
        self,
        *,
        character_id: str,
        user_id: str,
        reply_topic: str,
        conversation_history: str,
        memory_queries: tuple[str, ...] = (),
        sing_attempts: tuple[str, ...] = (),
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> tuple[ReplyDraft, ...]:
        """按话题召回记忆、按最近已唱排除选择演唱片段，并生成有序回复草稿。"""
        reply = await self._compose_reply(
            character_id=character_id,
            user_id=user_id,
            reply_topic=reply_topic,
            conversation_history=conversation_history,
            sing_attempts=sing_attempts,
            excluded_segments=excluded_segments,
            recall=self._recall(character_id, user_id, memory_queries),
        )
        return reply.drafts

    async def compose_staged(
        self,
        *,
        character_id: str,
        user_id: str,
        reply_topic: str,
        conversation_history: str,
        memory_queries: tuple[str, ...] = (),
        sing_attempts: tuple[str, ...] = (),
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> ComposedResponse:
        """召回超时则先给出配置的临时草稿，正式草稿留待调用方继续 await。

        仅供处理器内部分阶段使用；不改变 compose 的既有语义。
        """
        recall = asyncio.ensure_future(self._recall(character_id, user_id, memory_queries))

        async def formal() -> ComposedReply:
            return await self._compose_reply(
                character_id=character_id,
                user_id=user_id,
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
        """只有配置了非空临时文案和正数等待时长的召回才分阶段。"""
        return bool(memory_queries) and self._provisional_after > 0 and bool(self._provisional.content)

    async def _recall(self, character_id: str, user_id: str, memory_queries: tuple[str, ...]):
        if not memory_queries:
            return None
        runtime = self._runtime_provider(character_id)
        return await runtime.mind.search_memory_context_for_topic(user_id, list(memory_queries))

    async def _compose_reply(
        self,
        *,
        character_id: str,
        user_id: str,
        reply_topic: str,
        conversation_history: str,
        sing_attempts: tuple[str, ...],
        excluded_segments: set[tuple[str, str]] | None,
        recall,
    ) -> ComposedReply:
        runtime = self._runtime_provider(character_id)
        context = await recall
        memory_hits = context.render_for_prompt() if context is not None else []
        hits = tuple(getattr(context, "hits", ()) or ()) if context is not None else ()
        sing_plan = None
        if sing_attempts:
            candidate = await runtime.mind.build_sing_plan_for_topic(
                list(sing_attempts), excluded_segments=excluded_segments
            )
            if candidate and candidate[1]:
                sing_plan = candidate
        lines = await runtime.conscious.generate_topic_reply_for_pipeline(
            user_id=user_id,
            topic_content=reply_topic,
            memory_hits=memory_hits,
            fact_hits=None,
            sing_plan=sing_plan,
            conversation_history=conversation_history,
        )
        drafts = []
        for line in lines:
            draft = _draft(line)
            if draft.sing is not None:
                song, segment = draft.sing
                lyrics = runtime.capability_manager.singing.get_segment_lyrics(character_id, song, segment)
                draft = replace(draft, lyrics=lyrics or "")
            drafts.append(draft)
        return ComposedReply(drafts=tuple(drafts), memory_hits=hits)


def _draft(line: Any) -> ReplyDraft:
    if isinstance(line, SongSegmentChat):
        return ReplyDraft(
            content=line.get_content(), sound_content="", tone="", expression=None, sing=(line.song, line.segment)
        )
    content = getattr(line, "content", "") or ""
    sound = getattr(line, "sound_content", "") or ""
    if content and not sound:
        sound = build_sound_content(content)
    return ReplyDraft(
        content=content,
        sound_content=sound,
        tone=getattr(line, "tone", "") or "",
        expression=(getattr(line, "expression", "") or None),
        sing=None,
    )
