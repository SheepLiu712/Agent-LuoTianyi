from __future__ import annotations

import re
from typing import Callable, Optional, TYPE_CHECKING

from src.agent.text_cleaning import build_sound_content
from src.utils.helpers import get_unified_song_name

if TYPE_CHECKING:
    from src.agent.main_chat import OneResponseLine, OneSentenceChat, SongSegmentChat


ToneMapper = Callable[[str], tuple[str, str]]


class StructuredResponseParser:
    """Parses LLM response lines into legacy response objects."""

    tone_pattern = re.compile(r"^\[([^\]]+)\](.*)$", flags=re.IGNORECASE)
    sing_pattern = re.compile(r"^\[sing\]\s*(.+)$", flags=re.IGNORECASE)

    def __init__(
        self,
        *,
        sentence_cls: type["OneSentenceChat"],
        song_cls: type["SongSegmentChat"],
        default_response: "OneResponseLine",
        tone_mapper: ToneMapper,
        logger=None,
    ) -> None:
        self.sentence_cls = sentence_cls
        self.song_cls = song_cls
        self.default_response = default_response
        self.tone_mapper = tone_mapper
        self.logger = logger

    def parse(
        self,
        response: str,
        sing_plan: Optional[tuple[str, str]],
    ) -> list["OneResponseLine"]:
        if not response:
            return [self.default_response]

        text = self._strip_code_fence(response)
        results: list["OneResponseLine"] = []
        structured_found = False

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            sing_match = self.sing_pattern.match(line)
            if self.logger:
                self.logger.debug(f"Parsing line: '{line}'")
            if sing_match:
                if sing_plan:
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
                continue

        if structured_found:
            return results or [self.default_response]

        if self.logger:
            self.logger.warning("No structured format detected in LLM response, returning an empty text.")
        return [self.default_response]

    def _strip_code_fence(self, response: str) -> str:
        text = response.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2:
                return "\n".join(lines[1:-1]).strip()
        return text

    def _parse_sing_line(
        self,
        raw_song: str,
        sing_plan: tuple[str, str],
    ) -> Optional["SongSegmentChat"]:
        song = self._clean_song_token(raw_song)
        sing_plan_song = self._clean_song_token(sing_plan[0])
        if song and get_unified_song_name(song) == get_unified_song_name(sing_plan_song):
            return self.song_cls(song=sing_plan_song, segment=sing_plan[1], lyrics="")
        if self.logger:
            self.logger.warning(
                f"LLM requested to sing '{song}', but it does not match the sing plan song '{sing_plan_song}'. Ignoring this sing instruction."
            )
        return None

    def _clean_song_token(self, value: str) -> str:
        return (value or "").strip().strip("<>").strip().strip("'\"")

    def _parse_tone_line(
        self,
        tone: str,
        raw_content: str,
    ) -> Optional["OneSentenceChat"]:
        content = raw_content.strip()
        if not content:
            return None
        expression, tts_tone = self.tone_mapper(tone.lower().strip())
        return self.sentence_cls(
            expression=expression,
            tone=tts_tone,
            content=content,
            sound_content=build_sound_content(content),
        )
