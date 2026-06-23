from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.agent.prompt_assembly import RealizationPromptAssembler
from src.agent.response_parser import StructuredResponseParser
from src.utils.enum_type import ContextType
from src.utils.llm.llm_module import LLMModule
from src.utils.llm.llm_api_interface import LLMAPIFactory
from src.utils.llm.prompt_manager import PromptManager
from src.utils.logger import get_logger


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

    def get_content(self) -> str:
        return self.content


class MainChat:
    """Realization backend for styled character replies."""

    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.logger = get_logger(__name__)
        self.config = config

        llm_module_cfg = config.get("llm_module", {})
        llm_cfg = llm_module_cfg.get("llm", {})
        prompt_name = llm_module_cfg.get("prompt_name")
        if not prompt_name:
            raise ValueError("llm_module 配置中缺少 prompt_name")
        prompt_template = prompt_manager.get_template(prompt_name)
        if not prompt_template:
            raise ValueError(f"Prompt 模板未找到: {prompt_name}")
        llm_interface = LLMAPIFactory.create_interface(llm_cfg)

        self.llm = LLMModule(
            module_name="main_chat",
            module_config=llm_module_cfg,
            prompt_template=prompt_template,
            interface=llm_interface,
        )
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
        try:
            return await self.llm.generate_response(**kwargs)
        except Exception as e:
            import traceback

            self.logger.error(f"Error during topic reply generation: {e}\n{traceback.format_exc()}")
            return ""

    def _parse_response(self, response: str, sing_plan: Optional[Tuple[str, str]]) -> List[OneResponseLine]:
        return self.response_parser.parse(response, sing_plan)

    def _init_static_variables_sync(self) -> None:
        static_variables_file = self.config.get("static_variables_file")
        if not static_variables_file:
            self.logger.error("No static_variables_file configured for MainChat, skip loading static variables")
            return

        path = Path(static_variables_file)
        if not path.exists():
            self.logger.warning(f"MainChat static_variables_file not found: {static_variables_file}")
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                static_vars: Dict[str, Any] = json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load MainChat static variables: {e}")
            return

        character_name = static_vars.get("character_name", "").strip()
        if character_name:
            self.character_name = character_name

        persona = static_vars.get("character_persona", "")
        if isinstance(persona, list):
            persona = "".join(str(x) for x in persona if str(x).strip())
        if persona:
            self.character_persona = str(persona).strip()

        style = static_vars.get("speaking_style", "")
        if isinstance(style, list):
            style = "".join(str(x) for x in style if str(x).strip())
        if not style:
            requirements = static_vars.get("response_requirements", [])
            if isinstance(requirements, list):
                style = "".join(str(x).lstrip("- ").strip() for x in requirements[:3] if str(x).strip())
        if style:
            self.speaking_style = str(style).strip()

        assert hasattr(self, "character_name"), "character_name is required in static variables"
        assert hasattr(self, "character_persona"), "character_persona is required in static variables"
        assert hasattr(self, "speaking_style"), "speaking_style is required in static variables"

    def _init_llm_tone_mapping(self) -> None:
        self.llm_tone_mapping_file = self.config.get("llm_tone_mapping_file")
        self.llm_tone_to_tts_tone: Dict[str, str] = {}
        self.llm_tone_to_l2d_expression: Dict[str, str] = {}
        if not self.llm_tone_mapping_file:
            self.default_response = OneSentenceChat(content="")
            return

        path = Path(self.llm_tone_mapping_file)
        if not path.exists():
            self.logger.warning(f"LLM tone mapping file not found: {self.llm_tone_mapping_file}")
            self.default_response = OneSentenceChat(content="")
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
        except Exception as e:
            self.logger.warning(f"Failed to load LLM tone mapping: {e}")

        self.default_response = OneSentenceChat(
            expression=self.llm_tone_to_l2d_expression.get("中性", ""),
            tone=self.llm_tone_to_tts_tone.get("中性", ""),
            content="",
        )

    def _get_expressions_and_tts_tone(self, tone: str) -> Tuple[str, str]:
        normalized_tone = (tone or "").lower().strip()
        tts_tone = self.llm_tone_to_tts_tone.get(normalized_tone, "")
        expression = self.llm_tone_to_l2d_expression.get(normalized_tone, "")
        return expression, tts_tone
