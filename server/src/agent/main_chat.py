from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.llm.llm_module import LLMModule
from ..utils.llm.prompt_manager import PromptManager
from ..utils.logger import get_logger
from ..utils.enum_type import ContextType
import dataclasses


@dataclasses.dataclass
class OneResponseLine:
    type: ContextType  # 'say' 或 'sing'
    parameters: Any # SongSegment 或 OneSentenceChat
    def get_content(self) -> str:
        if self.type == ContextType.TEXT:
            return self.parameters.content
        else:
            return f"唱了{self.parameters.song}的选段{self.parameters.segment}"

@dataclasses.dataclass
class SongSegmentChat:
    song: str
    segment: str
    lyrics: str = ""

@dataclasses.dataclass
class OneSentenceChat:
    expression: str
    tone: str
    content: str
    sound_content: str = ""

@dataclass
class TopicReplyResult:
    reply_type: str  # "text" or "sing"
    reply_text: str  # 当reply_type为"text"时是回复文本；为"sing"时是歌曲名


class MainChat:
    """按话题生成回复文本的轻量聊天模块。"""

    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.logger = get_logger(__name__)
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.variables: List[str] = self.llm.prompt_template.get_variables()
        self._init_static_variables_sync()

    async def generate_response(
        self,
        reply_topic: str,
        user_nickname: str,
        user_description: str,
        conversation_history: str = "",
        fact_hits: Optional[List[str]] = None,
        memory_hits: Optional[List[str]] = None,
        sing_song: Optional[str] = None,
    ) -> List[TopicReplyResult]:
        """根据 topic_reply_prompt 生成自然语言回复。"""
        user_persona = self._build_user_persona(user_nickname, user_description)
        sing_requirement = self._build_sing_requirement(sing_song)
        extra_knowledge = self._build_extra_knowledge(fact_hits or [], memory_hits or [])

        response = await self._call_llm(
            character_name=self.character_name,
            character_persona=self.character_persona,
            speaking_style=self.speaking_style,
            user_persona=user_persona,
            conversation_history=conversation_history or "无",
            reply_topic=reply_topic or "",
            sing_requirement=sing_requirement,
            extra_knowledge=extra_knowledge,
        )
        return self._parse_response(response)

    async def _call_llm(self, **kwargs) -> str:
        try:
            return await self.llm.generate_response(**kwargs)
        except Exception as e:
            import traceback

            self.logger.error(f"Error during topic reply generation: {e}\n{traceback.format_exc()}")
            return ""

    def _parse_response(self, response: str) -> List[TopicReplyResult]:
        if not response:
            return [TopicReplyResult(reply_type="text", reply_text="")]

        text = response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("text"):
                text = text[4:]
            text = text.strip()

        pattern = re.compile(r"\[sing\s+([^\]]+)\]", flags=re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            sentences = self._split_text_to_short_sentences(text.strip())
            if not sentences:
                return [TopicReplyResult(reply_type="text", reply_text="")]
            return [TopicReplyResult(reply_type="text", reply_text=s) for s in sentences]

        before = text[:match.start()].strip()
        song = match.group(1).strip().strip("'\"“”《》")
        after = text[match.end():].strip()

        results: List[TopicReplyResult] = []
        before_sentences = self._split_text_to_short_sentences(before)
        if before_sentences:
            results.extend([TopicReplyResult(reply_type="text", reply_text=s) for s in before_sentences])
        else:
            results.append(TopicReplyResult(reply_type="text", reply_text=""))

        results.append(TopicReplyResult(reply_type="sing", reply_text=song))

        after_sentences = self._split_text_to_short_sentences(after)
        if after_sentences:
            results.extend([TopicReplyResult(reply_type="text", reply_text=s) for s in after_sentences])
        else:
            results.append(TopicReplyResult(reply_type="text", reply_text=""))

        return results

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
                sentence = sentence[len(paren_content):]

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
        nickname = (user_nickname or "你").strip() or "你"
        description = (user_description or "").strip()
        if description:
            return f"昵称：{nickname}。描述：{description}"
        return f"昵称：{nickname}。"

    def _build_sing_requirement(self, sing_song: Optional[str]) -> str:
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
        self.character_name = str(self.config.get("character_name", "洛天依")).strip() or "洛天依"
        self.character_persona = str(self.config.get("character_persona", "")).strip()
        self.speaking_style = str(self.config.get("speaking_style", "亲切、自然、口语化")).strip() or "亲切、自然、口语化"

        static_variables_file = self.config.get("static_variables_file", None)
        if not static_variables_file:
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

        persona = static_vars.get("persona", "")
        if isinstance(persona, list):
            persona = "\n".join(str(x) for x in persona if str(x).strip())
        if persona and not self.character_persona:
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