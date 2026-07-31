from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.prompt_assembly import RealizationPromptAssembler
from src.agent.response_parser import StructuredResponseParser
from src.agent.text_cleaning import build_sound_content
from src.domain import CharacterProfile
from src.utils.enum_type import ContextType
from src.utils.llm.llm_api_interface import LLMContentInspectionError
from src.utils.llm.llm_module import LLMModule
from src.utils.logger import get_logger


DEFAULT_LLM_TONE = "中性"
DEFAULT_TTS_TONE = "normal"
DEFAULT_EXPRESSION = "微笑脸"
DEFAULT_LLM_FAILURE_RESPONSE = "[中性]抱歉，我刚刚没能组织好回复，请再说一次吧"
DEFAULT_LLM_FAILURE_MAX_ATTEMPTS = 2
MAX_LLM_FAILURE_ATTEMPTS = 3
DEFAULT_LLM_FAILURE_RETRY_DELAY_SECONDS = 0.2
MAX_LLM_FAILURE_RETRY_DELAY_SECONDS = 2.0


@dataclass
class OneResponseLine(ABC):
    type: ContextType
    uuid: str = ""

    @abstractmethod
    def get_content(self) -> str:
        raise NotImplementedError("Subclasses of OneResponseLine must implement get_content()")


@dataclass
class SongSegmentChat(OneResponseLine):
    type: ContextType = ContextType.SING
    lyrics: str = ""
    song: str = ""
    segment: str = ""
    uuid: str = ""

    def get_content(self) -> str:
        return f"唱了《{self.song}》"


@dataclass
class OneSentenceChat(OneResponseLine):
    type: ContextType = ContextType.TEXT
    sound_content: str = ""
    expression: str = ""
    tone: str = ""
    content: str = ""
    uuid: str = ""

    def __post_init__(self) -> None:
        if not self.sound_content and self.content:
            self.sound_content = build_sound_content(self.content)

    def get_content(self) -> str:
        return self.content


class MainChat:
    """Realization backend for styled character replies."""

    def __init__(self, config: Dict[str, Any], llm_module: LLMModule, character_profile: CharacterProfile):
        self.logger = get_logger(__name__)
        self.config = config
        self.character_profile = character_profile
        self.llm = llm_module
        self.llm_failure_max_attempts = self._bounded_int(
            config.get("llm_failure_max_attempts"),
            default=DEFAULT_LLM_FAILURE_MAX_ATTEMPTS,
            minimum=1,
            maximum=MAX_LLM_FAILURE_ATTEMPTS,
        )
        self.llm_failure_retry_delay_seconds = self._bounded_float(
            config.get("llm_failure_retry_delay_seconds"),
            default=DEFAULT_LLM_FAILURE_RETRY_DELAY_SECONDS,
            minimum=0.0,
            maximum=MAX_LLM_FAILURE_RETRY_DELAY_SECONDS,
        )
        configured_fallback = str(config.get("llm_failure_response") or "").strip()
        self.llm_failure_response = self._structured_failure_response(configured_fallback)
        self.variables: List[str] = self.llm.prompt_template.get_variables()
        self._init_static_variables_sync()
        self._init_llm_tone_mapping()
        self.prompt_assembler = RealizationPromptAssembler()
        self.response_parser = StructuredResponseParser(
            sentence_cls=OneSentenceChat,
            song_cls=SongSegmentChat,
            default_response=self.default_response,
            tone_mapper=self._get_expressions_and_tts_tone,
            logger=self.logger,
        )

    async def generate_response(
        self,
        reply_topic: str,
        user_nickname: str,
        user_description: str,
        preference_context: str = "",
        conversation_history: str = "",
        fact_hits: Optional[List[str]] = None,
        memory_hits: Optional[List[str]] = None,
        sing_plan: Optional[Tuple[str, str]] = None,
    ) -> List[OneResponseLine]:
        prompt_input = self.prompt_assembler.build(
            character_name=self.character_name,
            character_persona=self.character_persona,
            speaking_style=self.speaking_style,
            reply_topic=reply_topic,
            user_nickname=user_nickname,
            user_description=user_description,
            preference_context=preference_context,
            conversation_history=conversation_history,
            fact_hits=fact_hits,
            memory_hits=memory_hits,
            sing_plan=sing_plan,
        )
        response = await self._call_llm(**asdict(prompt_input))
        return self._parse_response(response, sing_plan)

    async def _call_llm(self, **kwargs) -> str:
        max_attempts = getattr(
            self,
            "llm_failure_max_attempts",
            DEFAULT_LLM_FAILURE_MAX_ATTEMPTS,
        )
        retry_delay = getattr(
            self,
            "llm_failure_retry_delay_seconds",
            DEFAULT_LLM_FAILURE_RETRY_DELAY_SECONDS,
        )
        failure_response = getattr(
            self,
            "llm_failure_response",
            DEFAULT_LLM_FAILURE_RESPONSE,
        )

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.llm.generate_response(**kwargs)
                if isinstance(response, str) and response.strip():
                    return response
                raise RuntimeError("LLM returned an empty response")
            except LLMContentInspectionError as e:
                self.logger.warning(f"MainChat LLM 内容审查失败，返回话题切换回复: {e}")
                return "[中性]这个话题不太合适，我们聊点别的吧"
            except Exception as e:
                if attempt >= max_attempts:
                    self.logger.error(
                        "MainChat LLM failed after "
                        f"{attempt} attempts ({type(e).__name__}): {e}"
                    )
                    break
                self.logger.warning(
                    "MainChat LLM request failed "
                    f"({attempt}/{max_attempts}), retrying: "
                    f"{type(e).__name__}: {e}"
                )
                if retry_delay > 0:
                    await asyncio.sleep(retry_delay)

        return failure_response

    def _parse_response(self, response: str, sing_plan: Optional[Tuple[str, str]]) -> List[OneResponseLine]:
        return self.response_parser.parse(response, sing_plan)

    @staticmethod
    def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _structured_failure_response(value: str) -> str:
        if not value:
            return DEFAULT_LLM_FAILURE_RESPONSE
        if value.startswith("[") and "]" in value:
            _tone, content = value.split("]", 1)
            if content.strip():
                return value
            return DEFAULT_LLM_FAILURE_RESPONSE
        return f"[{DEFAULT_LLM_TONE}]{value}"

    def _init_static_variables_sync(self) -> None:
        static_variables_file = self.character_profile.static_variables_file
        character_id = self.character_profile.character_id
        if not static_variables_file:
            raise ValueError(f"No static_variables_file configured for character '{character_id}'.")

        path = Path(static_variables_file)
        if not path.is_file():
            raise FileNotFoundError(
                f"Static variables file for character '{character_id}' was not found: {path}"
            )

        try:
            with path.open("r", encoding="utf-8") as f:
                static_vars: Dict[str, Any] = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Static variables file for character '{character_id}' contains invalid JSON: {path}"
            ) from exc
        except OSError as exc:
            raise OSError(
                f"Failed to read static variables file for character '{character_id}': {path}"
            ) from exc

        if not isinstance(static_vars, dict):
            raise ValueError(
                f"Static variables file for character '{character_id}' must contain a JSON object: {path}"
            )

        character_name = self._required_static_text(
            static_vars,
            "character_name",
            character_id=character_id,
            path=path,
            allow_list=False,
        )
        character_persona = self._required_static_text(
            static_vars,
            "character_persona",
            character_id=character_id,
            path=path,
        )
        speaking_style = self._required_static_text(
            static_vars,
            "speaking_style",
            character_id=character_id,
            path=path,
        )

        self.character_name = character_name
        self.character_persona = character_persona
        self.speaking_style = speaking_style

    @staticmethod
    def _required_static_text(
        static_vars: Dict[str, Any],
        field_name: str,
        *,
        character_id: str,
        path: Path,
        allow_list: bool = True,
    ) -> str:
        value = static_vars.get(field_name)
        if isinstance(value, str):
            normalized = value.strip()
        elif allow_list and isinstance(value, list) and all(isinstance(item, str) for item in value):
            normalized = "".join(item.strip() for item in value if item.strip())
        else:
            normalized = ""

        if not normalized:
            raise ValueError(
                f"Static variables file for character '{character_id}' has an invalid or missing "
                f"'{field_name}' field: {path}"
            )
        return normalized

    def _init_llm_tone_mapping(self) -> None:
        self.llm_tone_mapping_file = self.character_profile.llm_tone_mapping_file
        self.llm_tone_to_tts_tone: Dict[str, str] = {}
        self.llm_tone_to_l2d_expression: Dict[str, str] = {}
        self.llm_tone_aliases: Dict[str, str] = {}
        if not self.llm_tone_mapping_file:
            raise ValueError(f"No llm_tone_mapping_file configured for character {self.character_profile.character_id}")

        path = Path(self.llm_tone_mapping_file)
        if not path.exists():
            self.logger.warning(f"LLM tone mapping file not found: {self.llm_tone_mapping_file}")
            self.default_response = OneSentenceChat(expression=DEFAULT_EXPRESSION, tone=DEFAULT_TTS_TONE, content="")
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                mapping = json.load(f)
            if isinstance(mapping, dict):
                self.llm_tone_to_tts_tone = {
                    str(k).strip().lower(): str(v).strip()
                    for k, v in mapping.get("llm_tone_to_tts_tone", {}).items()
                }
                self.llm_tone_to_l2d_expression = {
                    str(k).strip().lower(): str(v).strip()
                    for k, v in mapping.get("llm_tone_to_l2d_expression", {}).items()
                }
                self.llm_tone_aliases = {
                    str(k).strip().lower(): str(v).strip().lower()
                    for k, v in mapping.get("tone_aliases", {}).items()
                }
        except Exception as e:
            self.logger.warning(f"Failed to load LLM tone mapping: {e}")

        default_key = DEFAULT_LLM_TONE.lower()
        self.default_response = OneSentenceChat(
            expression=self.llm_tone_to_l2d_expression.get(default_key, DEFAULT_EXPRESSION),
            tone=self.llm_tone_to_tts_tone.get(default_key, DEFAULT_TTS_TONE),
            content="",
        )

    def _get_expressions_and_tts_tone(self, tone: str) -> Tuple[str, str]:
        normalized_tone = self._normalize_tone_label(tone)
        default_key = DEFAULT_LLM_TONE.lower()
        if not normalized_tone:
            self.logger.warning(f"LLM tone is empty, falling back to {DEFAULT_LLM_TONE}.")
            normalized_tone = default_key
        resolved_tone = self._resolve_tone_label(normalized_tone)
        if resolved_tone is None:
            self.logger.warning(f"LLM tone '{tone}' not found, falling back to {DEFAULT_LLM_TONE}.")
            resolved_tone = default_key
        tts_tone = self.llm_tone_to_tts_tone.get(
            resolved_tone,
            self.llm_tone_to_tts_tone.get(default_key, DEFAULT_TTS_TONE),
        )
        expression = self.llm_tone_to_l2d_expression.get(
            resolved_tone,
            self.llm_tone_to_l2d_expression.get(default_key, DEFAULT_EXPRESSION),
        )
        return expression, tts_tone

    @staticmethod
    def _normalize_tone_label(tone: str) -> str:
        """容错归一化情绪标签：去引号/括号/标点、多余空白并统一小写。"""
        if not tone:
            return ""
        text = str(tone).strip().lower()
        text = text.strip("[]()（）【】{}'\"“”‘’")
        text = text.strip(" \t\r\n。，、；：！？!?.;:…·~～")
        return "".join(text.split())

    def _resolve_tone_label(self, normalized_tone: str) -> Optional[str]:
        """将归一化后的情绪标签解析为映射表中的正式情绪。

        解析顺序：精确命中正式情绪 -> 别名表 -> 包含匹配（处理“有点伤心”“开心地”等带修饰的标签）。
        """
        if not normalized_tone:
            return DEFAULT_LLM_TONE.lower()
        if normalized_tone in self.llm_tone_to_tts_tone:
            return normalized_tone
        aliases = getattr(self, "llm_tone_aliases", {})
        if normalized_tone in aliases:
            return aliases[normalized_tone]
        for key in sorted(self.llm_tone_to_tts_tone, key=len, reverse=True):
            if key and (key in normalized_tone or normalized_tone in key):
                return key
        return None
