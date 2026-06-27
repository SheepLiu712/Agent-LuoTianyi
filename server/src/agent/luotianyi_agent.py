"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""
from __future__ import annotations

from typing import  List, Dict, Any, Optional, Tuple, Generator
import json
import re
from typing import TYPE_CHECKING

from src.agent.main_chat import MainChat, OneResponseLine
from src.utils.logger import get_logger
from src.subconscious.attention import TopicAttentionPlan
from src.agent.response_realizer import ResponseRealizer, UserExpressionContext
from src.domain import CharacterProfile, CharacterName


if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.database import DatabaseManager
    from src.subconscious.character_mind import CharacterSubconscious
    from src.utils.llm.llm_module import LLMModule
    from src.domain.chat import UnreadMessageSnapshot, UnreadMessage, ExtractedTopic
    


_expression_cache: Dict[str, List[str]] = {}

def get_available_expression(config_path: str = "config/live2d_interface_config.json") -> List[str]:
    if config_path in _expression_cache:
        return _expression_cache[config_path]
    with open(config_path, "r", encoding="utf-8") as f:
        config: Dict = json.load(f)
    expressions: Dict = config.get("expression_projection", {})
    result = list(expressions.keys())
    _expression_cache[config_path] = result
    return result


class LuoTianyiAgent:
    """洛天依Agent类

    实现洛天依角色扮演对话Agent的核心逻辑
    """

    def __init__(
        self,
        config: Dict[str, Any],
        database_manager: "DatabaseManager",
        capability_manager: "CapabilityManager",
        main_chat_module: "LLMModule",
        character_profile: CharacterProfile | None = None,
        mind: "CharacterSubconscious | None" = None,
    ) -> None:
        """初始化洛天依Agent

        Args:
            config: 配置字典
        """
        self.config = config
        self.logger = get_logger("LuoTianyiAgent")
        self.database_manager = database_manager
        self.capabilities = capability_manager
        self.character_profile = character_profile
        self.character_id = character_profile.character_id if character_profile else CharacterName.LUOTIANYI.value
        if mind is None:
            raise ValueError("LuoTianyiAgent requires a CharacterSubconscious instance.")
        self.mind = mind

        self.main_chat = MainChat(self.config["main_chat"], main_chat_module, self.character_profile)
        self.response_realizer = ResponseRealizer(self.main_chat)

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        """供 TopicReplier (或其他组件) 查找歌曲信息的代理方法"""
        return await self.mind.search_song_facts_for_topic(constraints)

    async def plan_topic_turn_for_pipeline(
        self,
        user_id: str,
        topic: "ExtractedTopic",
        conversation_history: str,
        external_context: Optional[str] = None,
    ) -> TopicAttentionPlan:
        """Build a conscious attention plan for one legacy chat topic."""
        return await self.mind.plan_topic_turn(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            external_context=external_context,
        )

    async def search_memory_context_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
    ):
        return await self.mind.search_memory_context_for_topic(
            user_id=user_id,
            queries=queries,
            similarity_threshold=similarity_threshold,
            k=k,
        )

    async def realize_topic_plan_for_pipeline(
        self,
        user_id: str,
        plan: TopicAttentionPlan,
    ) -> List[OneResponseLine]:
        """Realize a conscious plan into legacy response line objects."""
        user_context = self._load_user_expression_context(user_id)
        return await self.response_realizer.realize_topic_plan(
            plan=plan,
            user_context=user_context,
        )

    async def _search_fact_constraints_for_topic(self, fact_constraints: List[str]) -> List[str]:
        return await self.mind.search_fact_constraints_for_topic(fact_constraints)

    async def _plan_sing_attempts_for_topic(
        self,
        sing_attempts: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        return self.build_sing_plan_for_topic(sing_attempts)

    def _load_user_expression_context(self, user_id: str) -> UserExpressionContext:
        description = self.database_manager.get_user_description(user_id) or ""
        preferences = self.database_manager.get_user_preferences(user_id) or {}
        return UserExpressionContext(
            nickname="你",
            description=description,
            preference_context=self._build_preference_context(preferences),
        )

    def _build_preference_context(self, preferences: Any) -> str:
        if not preferences:
            return ""
        try:
            prefs = json.loads(preferences) if isinstance(preferences, str) else preferences
            pref_parts = []
            if prefs.get("relationship"):
                pref_parts.append(f"用户希望你是他的：{prefs['relationship']}")
            if prefs.get("speaking_style"):
                pref_parts.append(f"用户希望你的表达风格偏向：{prefs['speaking_style']}")
            if prefs.get("personality_traits"):
                traits = "、".join(prefs["personality_traits"])
                pref_parts.append(f"用户希望你的性格特点：{traits}")
            if prefs.get("custom_context"):
                custom_context = prefs["custom_context"].replace("我", "用户")
                pref_parts.append(f"用户补充的上下文：{custom_context}")
            if pref_parts:
                return "用户偏好设置：" + "；".join(pref_parts)
        except Exception as e:
            self.logger.warning(f"Failed to parse preferences: {e}")
        return ""

    async def get_citywalk_diary_by_date(self, date_str: str) -> str | None:
        """按日期检索 citywalk 报告并返回 diary_text 字段。
        如果同一天有多条记录，返回 created_at 最最新的那一条的 diary_text。
        date_str 格式为 YYYY-MM-DD
        """
        try:
            from pathlib import Path
            import json

            reports_dir = Path("data/citywalk_reports")
            if not reports_dir.exists():
                return None

            best_dt = None
            best_diary = None
            for p in reports_dir.glob("citywalk_*.json"):
                try:
                    text = p.read_text(encoding="utf-8")
                    data = json.loads(text)
                    created = data.get("created_at") or data.get("overview", {}).get("created_at")
                    diary = data.get("diary_text") or data.get("diary") or ""
                    if not created:
                        continue
                    # ISO datetime
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(created)
                    except Exception:
                        # try fallback parse
                        dt = datetime.strptime(created.split("+")[0], "%Y-%m-%dT%H:%M:%S")
                    if dt.strftime("%Y-%m-%d") != date_str:
                        continue
                    if best_dt is None or dt > best_dt:
                        best_dt = dt
                        best_diary = diary
                except Exception:
                    continue

            return best_diary
        except Exception as e:
            self.logger.error(f"get_citywalk_diary_by_date failed: {e}")
            return None

    async def get_citywalk_overview_by_date(self, date_str: str) -> dict | None:
        """返回指定日期的 citywalk overview（包含 city 和 selected_destination）"""
        try:
            from pathlib import Path
            import json

            reports_dir = Path("data/citywalk_reports")
            if not reports_dir.exists():
                return None

            best_dt = None
            best_overview = None
            for p in reports_dir.glob("citywalk_*.json"):
                try:
                    text = p.read_text(encoding="utf-8")
                    data = json.loads(text)
                    created = data.get("created_at")
                    overview = data.get("overview") or {}
                    if not created:
                        continue
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(created)
                    except Exception:
                        dt = datetime.strptime(created.split("+")[0], "%Y-%m-%dT%H:%M:%S")
                    if dt.strftime("%Y-%m-%d") != date_str:
                        continue
                    if best_dt is None or dt > best_dt:
                        best_dt = dt
                        best_overview = overview
                except Exception:
                    continue

            return best_overview
        except Exception as e:
            self.logger.error(f"get_citywalk_overview_by_date failed: {e}")
            return None

    async def generate_topic_reply_for_pipeline(
        self,
        user_id: str,
        topic_content: str,
        memory_hits: Optional[List[str]] = None,
        fact_hits: Optional[List[str]] = None,
        sing_plan: Optional[Tuple[str, str]] = None,
        conversation_history: Optional[str] = None,  # cached context; reads from Redis if None
    ) -> List[OneResponseLine]:
        """供 TopicReplier 调用：按话题生成分段回复。"""
        if conversation_history is None:
            conversation_history = ""
        user_context = self._load_user_expression_context(user_id)

        return await self.main_chat.generate_response(
            reply_topic=topic_content,
            user_nickname=user_context.nickname,
            user_description=user_context.description,
            preference_context=user_context.preference_context,
            conversation_history=conversation_history,
            fact_hits=fact_hits or [],
            memory_hits=memory_hits or [],
            sing_plan=sing_plan,
        )

    async def write_topic_memories_for_pipeline(
        self,
        user_id: str,
        current_dialogue: str,
        related_memories: Optional[List[str]] = None,
        conversation_history: Optional[str] = None,  # cached context; reads from Redis if None
    ) -> None:
        """供 TopicReplier 调用：在单个 topic 回复完成后异步提取并写入记忆。"""
        await self.mind.write_topic_memories(
            user_id=user_id,
            current_dialogue=current_dialogue,
            related_memories=related_memories,
            conversation_history=conversation_history,
        )

    def build_sing_plan_for_topic(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """供 TopicReplier 调用的唱歌计划接口。返回 song|segment。"""
        return self.mind.build_sing_plan_for_topic(sing_attempts)
    
    def sing(self, song_name: str, segment: str) -> Optional[bytes]:
        """调用唱歌管理器生成歌曲片段的音频，并返回音频的Base64字符串"""
        return self.capabilities.singing.sing(self.character_id, song_name, segment)
    
    async def tts_say(self, text: str, tone: str) -> str:
        return await self.capabilities.speech.say(self.character_id, text, tone)
    
    def tts_say_stream(self, text: str, tone: str) -> Generator[str, None, None]:
        yield from self.capabilities.speech.say_stream(self.character_id, text, tone)

    def _extract_song_name(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return ""

        m = re.search(r"《([^》]+)》", content)
        if m:
            return m.group(1).strip()

        if "是一首歌" in content:
            return content.split("是一首歌", 1)[0].strip().strip("《》")

        return content.strip("\"'“”‘’《》")

    def _format_memory_hit(self, doc: Any) -> str:
        timestamp = ""
        if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
            timestamp = str(doc.metadata.get("timestamp") or "").strip()
        content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
        if not content:
            return ""
        if timestamp:
            return f"在{timestamp}, {content}"
        return content
