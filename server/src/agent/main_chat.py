from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from ..utils.llm.llm_module import LLMModule
from ..utils.llm.prompt_manager import PromptManager
from ..utils.logger import get_logger
from ..utils.enum_type import ContextType
import dataclasses
from abc import ABC, abstractmethod


@dataclasses.dataclass
class OneResponseLine(ABC):
    type: ContextType  # 'say' 或 'sing'
    uuid: str = ""  # 可选的唯一标识符，供前端关联 TTS 音频和文本使用
    @abstractmethod
    def get_content(self) -> str:
        raise NotImplementedError("Subclasses of OneResponseLine must implement get_content()")


@dataclasses.dataclass
class SongSegmentChat(OneResponseLine):
    type: ContextType = ContextType.SING
    lyrics: str = ""
    song: str = ""
    segment: str = ""
    uuid: str = ""

    def get_content(self) -> str:
        return f"唱了《{self.song}》"


@dataclasses.dataclass
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
    """按话题生成回复文本的轻量聊天模块。"""

    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.logger = get_logger(__name__)
        self.config = config

        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.variables: List[str] = self.llm.prompt_template.get_variables()
        self._init_static_variables_sync()
        self._init_llm_tone_mapping()

    async def generate_response(
        self,
        reply_topic: str,
        user_nickname: str,
        user_description: str,
        conversation_history: str = "",
        fact_hits: Optional[List[str]] = None,
        memory_hits: Optional[List[str]] = None,
        sing_plan: Optional[Tuple[str, str]] = None,
    ) -> List[OneResponseLine]:
        """根据 topic_reply_prompt 生成自然语言回复。"""
        user_persona = self._build_user_persona(user_nickname, user_description)
        sing_requirement = self._build_sing_requirement(sing_plan)
        extra_knowledge = self._build_extra_knowledge(fact_hits or [], memory_hits or [])
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        response = await self._call_llm(
            character_name=self.character_name,
            character_persona=self.character_persona,
            speaking_style=self.speaking_style,
            user_persona=user_persona,
            conversation_history=conversation_history or "无",
            current_time=current_time,
            reply_topic=reply_topic or "",
            sing_requirement=sing_requirement,
            extra_knowledge=extra_knowledge,
        )
        return self._parse_response(response, sing_plan)

    async def _call_llm(self, **kwargs) -> str:
        try:
            return await self.llm.generate_response(**kwargs)
        except Exception as e:
            import traceback

            self.logger.error(f"Error during topic reply generation: {e}\n{traceback.format_exc()}")
            return ""

    def _parse_response(self, response: str, sing_plan: Optional[Tuple[str, str]]) -> List[OneResponseLine]:
        if not response:
            return [self.default_response]

        text = response.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2:
                text = "\n".join(lines[1:-1]).strip()

        tone_pattern = re.compile(r"^\[(中性|欣喜|温柔|伤心|生气|惊讶|害怕)\](.*)$", flags=re.IGNORECASE)
        sing_pattern = re.compile(r"^\[sing\]\s*(.+)$", flags=re.IGNORECASE)

        results: List[OneResponseLine] = []
        structured_found = False

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            # 先尝试匹配唱歌指令
            sing_match = sing_pattern.match(line)
            if sing_match and sing_plan:
                song = sing_match.group(1).strip().strip("<>").strip().strip("'\"“”《》")
                sing_plan_song = sing_plan[0].strip().strip("<>").strip().strip("'\"“”《》")
                if song and song == sing_plan_song:
                    results.append(SongSegmentChat(song=sing_plan_song, segment=sing_plan[1], lyrics=""))
                    structured_found = True
                continue

            # 再尝试匹配语气标记
            tone_match = tone_pattern.match(line)
            if tone_match:
                tone = tone_match.group(1).lower().strip()
                content = tone_match.group(2).strip()
                if content:
                    content = content.strip()
                    expression, tts_tone = self._get_expressions_and_tts_tone(tone)
                    results.append(OneSentenceChat(expression=expression, tone=tts_tone, content=content))
                    # sentences = self._split_text_to_short_sentences(content)
                    # if not sentences:
                    #     sentences = [content]
                    # for sentence in sentences:
                    #     normalized = sentence.strip()
                    #     if not normalized:
                    #         continue
                    #     expression, tts_tone = self._get_expressions_and_tts_tone(tone)
                    #     results.append(OneSentenceChat(expression=expression, tone=tts_tone, content=normalized))
                    structured_found = True
                continue

        if structured_found:
            return results or [self.default_response]

        self.logger.warning("No structured format detected in LLM response, returning an empty text.")

        return [self.default_response]

    def _split_text_to_short_sentences(self, text: str) -> List[str]:
        """复用 _split_responses 的拆句策略：按标点切分并聚合为短句。"""
        raw = (text or "").strip()
        if not raw:
            return []

        punct_pattern = re.compile(r"^(?:\.{3}|[。，！？~,])+$")
        parts = re.split(r"((?:\.{3}|[。，！？~,]))", raw)

        sentences_with_punct: List[str] = []
        for s in parts:
            if not s:
                continue
            if punct_pattern.match(s) and sentences_with_punct:
                sentences_with_punct[-1] += s
            else:
                sentences_with_punct.append(s)

        sentence_buffer = ""
        split_sentences: List[str] = []

        for i, sentence in enumerate(sentences_with_punct):
            match = re.match(r"^(\（.*?\）|\(.*?\))", sentence)
            paren_content = None
            if match:
                paren_content = match.group(1)
                sentence = sentence[len(paren_content) :]

            if paren_content:
                if sentence_buffer.strip():
                    sentence_buffer += paren_content
                elif split_sentences:
                    split_sentences[-1] += paren_content
                else:
                    sentence = paren_content + sentence

            sentence_buffer += sentence

            if len(sentence_buffer) >= 6 or i == len(sentences_with_punct) - 1:
                final_content = sentence_buffer.strip()
                if final_content:
                    split_sentences.append(final_content)
                sentence_buffer = ""

        return split_sentences

    def _build_user_persona(self, user_nickname: str, user_description: str) -> str:
        return user_description.strip()
        # nickname = (user_nickname or "你").strip() or "你"
        # description = (user_description or "").strip()
        # if description:
        #     return f"昵称：{nickname}。描述：{description}"
        # return f"昵称：{nickname}。"

    def _build_sing_requirement(self, sing_plan: Optional[Tuple[str, str]]) -> str:
        if not sing_plan or not sing_plan[0]:
            return "在回复中你不需要为用户唱歌"
        if sing_plan[0] is not None and sing_plan[1] is None:
            return f"用户想要听《{sing_plan[0]}》，但是你还不会唱。"
        sing_song = sing_plan[0]
        normalized_song = self._normalize_sing_song(sing_song)
        if normalized_song:
            return f"你要为用户唱一段《{normalized_song}》"
        return "在回复中你不需要为用户唱歌"

    def _build_extra_knowledge(self, fact_hits: List[str], memory_hits: List[str]) -> str:
        merged: List[str] = []
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

    def _normalize_sing_song(self, sing_song: Optional[str]) -> Optional[str]:
        if not sing_song:
            return None
        value = str(sing_song).strip()
        if not value:
            return None
        if "|" in value:
            value = value.split("|", 1)[0].strip()
        return value.strip("'\"“”《》")

    def _init_static_variables_sync(self) -> None:

        static_variables_file = self.config.get("static_variables_file", None)
        if not static_variables_file:
            self.logger.error("No static_variables_file configured for MainChatV2, skip loading static variables")
            return

        path = Path(static_variables_file)
        if not path.exists():
            self.logger.warning(f"MainChatV2 static_variables_file not found: {static_variables_file}")
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                static_vars: Dict[str, Any] = json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load MainChatV2 static variables: {e}")
            return
        
        character_name = static_vars.get("character_name", "").strip()
        if character_name:
            self.character_name = character_name

        persona = static_vars.get("character_persona", "")
        if isinstance(persona, list):
            persona = "\n".join(str(x) for x in persona if str(x).strip())
        if persona:
            self.character_persona = str(persona).strip()

        style = static_vars.get("speaking_style", "")
        if isinstance(style, list):
            style = "；".join(str(x) for x in style if str(x).strip())
        if not style:
            requirements = static_vars.get("response_requirements", [])
            if isinstance(requirements, list):
                style = "；".join(str(x).lstrip("- ").strip() for x in requirements[:3] if str(x).strip())
        if style:
            self.speaking_style = str(style).strip()

        assert hasattr(self, "character_name"), "character_name is required in static variables"
        assert hasattr(self, "character_persona"), "character_persona is required in static variables"
        assert hasattr(self, "speaking_style"), "speaking_style is required in static variables"

    def _init_llm_tone_mapping(self) -> None:
        self.llm_tone_mapping_file = self.config.get("llm_tone_mapping_file", None)
        self.llm_tone_to_tts_tone: Dict[str, str] = {}
        self.llm_tone_to_l2d_expression: Dict[str, str] = {}
        if not self.llm_tone_mapping_file:
            return
        path = Path(self.llm_tone_mapping_file)
        if not path.exists():
            self.logger.warning(f"LLM tone mapping file not found: {self.llm_tone_mapping_file}")
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                mapping = json.load(f)
                if isinstance(mapping, dict):
                    self.llm_tone_to_tts_tone = {
                        str(k).strip().lower(): str(v).strip() for k, v in mapping.get("llm_tone_to_tts_tone", {}).items()
                    }
                    self.llm_tone_to_l2d_expression = {
                        str(k).strip().lower(): str(v).strip() for k, v in mapping.get("llm_tone_to_l2d_expression", {}).items()
                    }
        except Exception as e:
            self.logger.warning(f"Failed to load LLM tone mapping: {e}")

        self.default_response = OneSentenceChat(
                expression=self.llm_tone_to_l2d_expression.get("中性", ""),
                tone=self.llm_tone_to_tts_tone.get("中性", ""),
                content="",
        )

    def _get_expressions_and_tts_tone(self, tone: str) -> Tuple[str, str]:
        normalized_tone = tone.lower().strip()
        tts_tone = self.llm_tone_to_tts_tone.get(normalized_tone, "")
        expression = self.llm_tone_to_l2d_expression.get(normalized_tone, "")
        return expression, tts_tone