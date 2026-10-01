"""判定用户消息是否包含明确的唱歌意图。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.domain.planner_type import PlanningStep, SingingAction
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.models.service import LLMService


_SINGING_CUES = ("唱", "听歌", "来首", "来一首", "点歌", "演唱")


class SingingIntentSkill:
    """用决策模型把歌词/歌名候选收口为经过确认的唱歌请求。"""

    def __init__(self, config: dict[str, Any], llm_service: LLMService) -> None:
        if not isinstance(config, dict):
            raise TypeError("topic_extractor 必须是字典")
        module_config = config.get("llm_module")
        self._llm = (
            llm_service.register_llm_module("singing_intent", module_config) if module_config is not None else None
        )
        self._logger = get_logger(__name__)

    async def decide(
        self,
        message: str,
        *,
        terms: tuple[str, ...] = (),
        conversation_history: str = "",
    ) -> tuple[str, ...]:
        """返回确认后的歌名、random_song 或空；模型及解析失败时保守返回空。"""
        if not isinstance(message, str):
            raise TypeError("message 必须是字符串")
        text = message.strip()
        candidates = tuple(term.strip() for term in terms if isinstance(term, str) and term.strip())
        if not text or (not candidates and not any(cue in text for cue in _SINGING_CUES)):
            return ()
        if self._llm is None:
            return ()
        try:
            response = await self._llm.generate_response(
                conversation_history=conversation_history,
                message_content=f"[0]: {text}",
                terms=", ".join(candidates) if candidates else "None",
                use_json=True,
            )
            decision = self._parse_decision(response)
        except Exception as error:  # noqa: BLE001 - intent gate must never break the reply chain
            self._logger.warning(f"唱歌意图判定失败，已按无唱歌意图处理: {error}")
            return ()
        if decision.singing_action is not SingingAction.TRY_SINGING:
            return ()
        song = (decision.singing_song or "").strip()
        return (song,) if song else ()

    @staticmethod
    def _parse_decision(response: Any) -> PlanningStep:
        if not isinstance(response, str) or not response.strip():
            return PlanningStep()
        text = response.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        data = json.loads(text)
        attempts = data.get("sing_attempts") if isinstance(data, dict) else None
        if not isinstance(attempts, list):
            return PlanningStep()
        songs = [str(item).strip() for item in attempts if item is not None and str(item).strip()]
        if not songs:
            return PlanningStep()
        return PlanningStep(singing_action=SingingAction.TRY_SINGING, singing_song=songs[0])
