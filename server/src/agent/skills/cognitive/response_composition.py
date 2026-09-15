"""批次回复的生成技能：召回证据并生成角色回复草稿。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol

from src.agent.main_chat import SongSegmentChat
from src.agent.text_cleaning import build_sound_content


class _Mind(Protocol):
    async def search_memory_context_for_topic(self, user_id: str, queries: list[str]): ...
    async def build_sing_plan_for_topic(self, attempts: list[str], excluded_segments=None,
                                        emotion_context: str = ""): ...


class _Conscious(Protocol):
    async def generate_topic_reply_for_pipeline(self, user_id: str, topic_content: str,
                                                memory_hits=None, fact_hits=None, sing_plan=None,
                                                conversation_history=None): ...


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


class ResponseCompositionSkill:
    """包装角色潜意识的召回与意识的回复生成，输出与旧链路等价的回复草稿。"""

    def __init__(self, config: dict[str, Any],
                 runtime_provider: Callable[[str], _Runtime]) -> None:
        """校验本层 config 并绑定按角色解析潜意识/意识的提供者。"""
        if not isinstance(config, dict):
            raise TypeError("reply_composition 必须是字典")
        self._runtime_provider = runtime_provider

    async def compose(self, *, character_id: str, user_id: str, reply_topic: str,
                      conversation_history: str, memory_queries: tuple[str, ...] = (),
                      sing_attempts: tuple[str, ...] = (),
                      excluded_segments: set[tuple[str, str]] | None = None) -> tuple[ReplyDraft, ...]:
        """按话题召回记忆、按最近已唱排除选择演唱片段，并生成有序回复草稿。"""
        runtime = self._runtime_provider(character_id)
        memory_hits: list[str] = []
        if memory_queries:
            context = await runtime.mind.search_memory_context_for_topic(user_id, list(memory_queries))
            if context is not None:
                memory_hits = context.render_for_prompt()
        sing_plan = None
        if sing_attempts:
            candidate = await runtime.mind.build_sing_plan_for_topic(
                list(sing_attempts), excluded_segments=excluded_segments)
            if candidate and candidate[1]:
                sing_plan = candidate
        lines = await runtime.conscious.generate_topic_reply_for_pipeline(
            user_id=user_id, topic_content=reply_topic, memory_hits=memory_hits,
            fact_hits=None, sing_plan=sing_plan, conversation_history=conversation_history,
        )
        drafts = []
        for line in lines:
            draft = _draft(line)
            if draft.sing is not None:
                song, segment = draft.sing
                lyrics = runtime.capability_manager.singing.get_segment_lyrics(
                    character_id, song, segment)
                draft = replace(draft, lyrics=lyrics or "")
            drafts.append(draft)
        return tuple(drafts)


def _draft(line: Any) -> ReplyDraft:
    if isinstance(line, SongSegmentChat):
        return ReplyDraft(content=line.get_content(), sound_content="", tone="",
                          expression=None, sing=(line.song, line.segment))
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
