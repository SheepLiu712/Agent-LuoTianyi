from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class RealizationPromptInput:
    character_name: str
    character_persona: str
    speaking_style: str
    user_persona: str
    preference_context: str
    conversation_history: str
    current_time: str
    reply_topic: str
    sing_requirement: str
    extra_knowledge: str


class RealizationPromptAssembler:
    """Builds prompt variables for the current MainChat realization backend."""

    def build(
        self,
        *,
        character_name: str,
        character_persona: str,
        speaking_style: str,
        reply_topic: str,
        user_nickname: str,
        user_description: str,
        preference_context: str = "",
        conversation_history: str = "",
        fact_hits: Optional[list[str]] = None,
        memory_hits: Optional[list[str]] = None,
        sing_plan: Optional[tuple[str, str]] = None,
    ) -> RealizationPromptInput:
        return RealizationPromptInput(
            character_name=character_name,
            character_persona=character_persona,
            speaking_style=speaking_style,
            user_persona=self.build_user_persona(user_nickname, user_description),
            preference_context=preference_context,
            conversation_history=conversation_history or "无",
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            reply_topic=reply_topic or "",
            sing_requirement=self.build_sing_requirement(sing_plan),
            extra_knowledge=self.build_extra_knowledge(fact_hits or [], memory_hits or []),
        )

    def build_user_persona(self, user_nickname: str, user_description: str) -> str:
        return (user_description or "").strip()

    def build_sing_requirement(self, sing_plan: Optional[tuple[str, str]]) -> str:
        if not sing_plan or not sing_plan[0]:
            return "在回复中你不需要为用户唱歌"
        if sing_plan[0] is not None and sing_plan[1] is None:
            return f"用户想要听《{sing_plan[0]}》，但是你还不会唱。"
        normalized_song = self.normalize_sing_song(sing_plan[0])
        if normalized_song:
            return f"你要为用户唱一段《{normalized_song}》。"
        return "在回复中你不需要为用户唱歌"

    def build_extra_knowledge(self, fact_hits: list[str], memory_hits: list[str]) -> str:
        merged: list[str] = []
        seen = set()
        for item in fact_hits + memory_hits:
            text = (item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
        if not merged:
            return "无"
        return "\n".join(merged)

    def normalize_sing_song(self, sing_song: Optional[str]) -> Optional[str]:
        if not sing_song:
            return None
        value = str(sing_song).strip()
        if not value:
            return None
        if "|" in value:
            value = value.split("|", 1)[0].strip()
        return value.strip("'\"")
