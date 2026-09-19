"""将结构化模型文本解析为 Agent 内部回复草稿。"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from src.agent.skills.cognitive._text_cleaning import build_sound_content
from src.agent.skills.contracts import ReplyDraft
from src.utils.helpers import get_unified_song_name
from src.utils.logger import get_logger

ToneMapper = Callable[[str], tuple[str, str]]


class StructuredResponseParser:
    """解析模型的情绪行和演唱行，不暴露旧聊天回复对象。"""

    tone_pattern = re.compile(r"^\[([^\]]+)\](.*)$", flags=re.IGNORECASE)
    sing_pattern = re.compile(r"^\[sing\]\s*(.+)$", flags=re.IGNORECASE)

    def __init__(self, *, default_draft: ReplyDraft, tone_mapper: ToneMapper) -> None:
        self.default_draft = default_draft
        self.tone_mapper = tone_mapper
        self._logger: logging.Logger = get_logger(__name__)

    def parse(self, response: str, sing_plan: tuple[str, str] | None) -> tuple[ReplyDraft, ...]:
        if not response:
            return (self.default_draft,)
        text = self._strip_code_fence(response)
        results: list[ReplyDraft] = []
        structured_found = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            sing_match = self.sing_pattern.match(line)
            self._logger.debug("Parsing line: %r", line)
            if sing_match:
                item = self._parse_sing_line(sing_match.group(1), sing_plan)
                if item is not None:
                    results.append(item)
                    structured_found = True
                continue
            tone_match = self.tone_pattern.match(line)
            if tone_match:
                item = self._parse_tone_line(tone_match.group(1), tone_match.group(2))
                if item is not None:
                    results.append(item)
                    structured_found = True
        if structured_found:
            return tuple(results) or (self.default_draft,)
        self._logger.warning("No structured format detected in LLM response, returning an empty text.")
        return (self.default_draft,)

    @staticmethod
    def _strip_code_fence(response: str) -> str:
        text = response.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2:
                return "\n".join(lines[1:-1]).strip()
        return text

    def _parse_sing_line(self, raw_song: str, sing_plan: tuple[str, str] | None) -> ReplyDraft | None:
        song = self._clean_song_token(raw_song)
        if not song:
            return None
        segment = ""
        if sing_plan and sing_plan[0]:
            planned_song = self._clean_song_token(sing_plan[0])
            if get_unified_song_name(song) == get_unified_song_name(planned_song):
                segment = sing_plan[1] or ""
        return ReplyDraft(content=f"唱了《{song}》", sound_content="", tone="", expression=None, sing=(song, segment))

    @staticmethod
    def _clean_song_token(value: str) -> str:
        return (value or "").strip().strip("<>《》").strip().strip("'\"“”‘’")

    def _parse_tone_line(self, tone: str, raw_content: str) -> ReplyDraft | None:
        content = raw_content.strip()
        if not content:
            return None
        expression, tts_tone = self.tone_mapper(tone.lower().strip())
        return ReplyDraft(
            content=content,
            sound_content=build_sound_content(content),
            tone=tts_tone,
            expression=expression,
        )
