"""一次模型调用提取本轮回复的记忆检索 key 与唱歌意图。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.agent.skills.contracts import TopicExtraction
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.agent.skills.cognitive.text_preprocessing import TextPreprocessingSkill
    from src.infrastructure.models.service import LLMService


class TopicExtractionSkill:
    """术语只作为模型线索，检索 key 和演唱 attempt 均由同一次决策产生。"""

    def __init__(
        self, config: dict[str, Any], llm_service: LLMService, *, understanding: TextPreprocessingSkill
    ) -> None:
        if not isinstance(config, dict):
            raise TypeError("topic_extractor 必须是字典")
        module_config = config.get("llm_module")
        self._llm = (
            llm_service.register_llm_module("topic_extract", module_config) if module_config is not None else None
        )
        self._understanding = understanding
        self._logger = get_logger(__name__)
        if self._llm is None:
            self._logger.warning("topic_extractor 未配置，回复将不检索记忆或尝试唱歌")

    async def extract(self, message: str, *, conversation_history: str = "") -> TopicExtraction:
        """每轮统一提取；失败不重试，不把原文或术语升级为检索/演唱决策。"""
        if not isinstance(message, str):
            raise TypeError("message 必须是字符串")
        if self._llm is None:
            return TopicExtraction()
        try:
            terms = self._understanding.extract_terms(message)
            response = await self._llm.generate_response(
                conversation_history=conversation_history,
                message_content=message,
                terms=", ".join(terms) if terms else "None",
                use_json=True,
            )
            return self._parse_response(response)
        except Exception as error:
            self._logger.warning("话题提取失败，按空检索和无唱歌意图继续回复: %s", error)
            return TopicExtraction()

    @staticmethod
    def _parse_response(response: Any) -> TopicExtraction:
        if not isinstance(response, str) or not response.strip():
            raise ValueError("topic_extract 返回空结果")
        text = response.strip()
        if text.startswith("```") and text.endswith("```"):
            text = "\n".join(text.splitlines()[1:-1]).strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("topic_extract 必须返回 JSON 对象")
        return TopicExtraction(
            memory_queries=_string_items(data.get("memory_attempts", [])),
            sing_attempts=_string_items(data.get("sing_attempts", [])),
        )


def _string_items(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("topic_extract 字段必须是字符串列表")
    return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
