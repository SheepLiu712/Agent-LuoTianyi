from __future__ import annotations

from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from src.subconscious.attention import AttentionPlanner, TopicAttentionPlan
from src.domain import CharacterProfile

from src.subconscious.date_processor import DateDetector, process_detected_date
from src.subconscious.memory import SongKnowledgeMemory, SubconsciousMemory
from src.subconscious.state import SubconsciousState
from src.subconscious.topic_extractor import TopicExtractor
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.domain.chat import UnreadMessageSnapshot, ExtractedTopic, UnreadMessage
    from src.domain import MemoryContext


class CharacterSubconscious:
    """Per-character subconscious services.

    This owns recall, topic extraction, attention material, state, date
    detection, and memory/profile writes for one character. The conscious agent
    consumes the plans and context produced here.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        database_manager: "DatabaseManager",
        capability_manager: "CapabilityManager",
        memory: SubconsciousMemory,
        llm_modules: dict[str, "LLMService"],
        character_profile: CharacterProfile,
    ) -> None:
        self.config = config
        self.database_manager = database_manager
        self.capability_manager = capability_manager
        self.character_profile = character_profile
        self.character_id = character_profile.character_id
        self.logger = get_logger(f"{self.character_id}Subconscious")

        self.memory = memory
        self.state = SubconsciousState(owner_character_id=self.character_id)
        self.song_knowledge = SongKnowledgeMemory(
            config.get("song_knowledge", {}),
        )
        self.topic_extractor = TopicExtractor(
            config["topic_extractor"],
            character_id=self.character_id,
            llm_module=llm_modules["topic_extractor"]
        )
        self.attention_planner = AttentionPlanner(
            config.get("attention_planner", {}),
            target_character_id=self.character_id,
        )
        self.date_detector = DateDetector(
            config.get("date_detector", {}),
            character_id=self.character_id,
            llm_module=llm_modules["date_detector"]
            )

    def get_state(self):
        return self.state.get_snapshot()

    def ensure_dependencies(self) -> None:
        """检查角色潜意识依赖已经初始化。"""
        required = {
            "database_manager": self.database_manager,
            "capability_manager": self.capability_manager,
            "character_profile": self.character_profile,
            "memory": self.memory,
            "state": self.state,
            "song_knowledge": self.song_knowledge,
            "topic_extractor": self.topic_extractor,
            "attention_planner": self.attention_planner,
            "date_detector": self.date_detector,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CharacterSubconscious dependencies are missing: {', '.join(missing)}")
        self.memory.ensure_dependencies()

    async def extract_topics(
        self,
        user_id: str,
        unread_snapshot: "UnreadMessageSnapshot",
        force_complete: bool = False,
        conversation_history: str | None = None,
    ) -> Tuple[Optional["ExtractedTopic"], List[UnreadMessage]]:
        '''从用户发来的消息中尝试构造话题，生成记忆检索和事实检索的线索。返回话题对象和未读消息列表。'''
        if unread_snapshot is None or not unread_snapshot.messages:
            return None, []

        if conversation_history is None:
            conversation_history = ""

        return await self.topic_extractor.extract_topics(
            unread_snapshot=unread_snapshot,
            conversation_history=conversation_history,
            force_complete=force_complete,
        )
    
    async def search_fact_constraints_for_topic(self, fact_constraints: List[str]) -> List[str]:
        '''搜索与话题相关的事实约束，返回匹配的事实列表。例如歌曲的事实，歌曲作者的事实等。'''
        if not fact_constraints:
            return []

        special_hits: List[str] = []
        regular_constraints: List[str] = []
        for constraint in fact_constraints:
            if constraint == "/SongsCanSing":
                try:
                    songs_json = await self.capability_manager.singing.get_songs_can_sing_llm(
                        self.character_id,
                        max_song_num=15,
                    )
                    special_hits.append(f"可演唱歌曲推荐：{songs_json}")
                except Exception as e:
                    self.logger.error(f"Failed to get songs can sing: {e}")
                continue

            if constraint.startswith("/CanISing"):
                song_name = constraint[len("/CanISing"):].strip()
                if not song_name:
                    continue
                try:
                    special_hits.append(
                        await self.capability_manager.singing.can_i_sing_song_llm(
                            self.character_id,
                            song_name,
                        )
                    )
                except Exception as e:
                    self.logger.error(f"Failed to get can I sing for {song_name}: {e}")
                continue

            regular_constraints.append(constraint)

        regular_hits = await self.song_knowledge.search_song_facts_for_topic(regular_constraints) if regular_constraints else []
        return special_hits + regular_hits

    async def search_memory_context_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
    ) -> "MemoryContext":
        '''搜索与话题相关的记忆，返回 MemoryContext 对象，包含匹配的记忆和相关信息。'''
        if not queries:
            from src.domain import MemoryContext

            return MemoryContext()

        return await self.memory.search_memory_context_for_topic(
            user_id=user_id,
            queries=queries,
            similarity_threshold=similarity_threshold,
            k=k,
        )

    async def plan_topic_turn(
        self,
        user_id: str,
        topic: "ExtractedTopic",
        conversation_history: str,
        external_context: Optional[str] = None,
    ) -> TopicAttentionPlan:
        return await self.attention_planner.plan_topic_turn(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            memory_search=lambda queries: self.search_memory_context_for_topic(
                user_id=user_id,
                queries=queries,
                similarity_threshold=0.8,
            ),
            fact_search=self.search_fact_constraints_for_topic,
            sing_planner=self._plan_sing_attempts_for_topic,
            external_context=external_context,
            agent_state=self.state.get_snapshot(),
        )

    async def write_topic_memories(
        self,
        user_id: str,
        current_dialogue: str,
        related_memories: Optional[List[str]] = None,
        conversation_history: Optional[str] = None,
    ) -> dict[str, Any]:
        return await self.memory.write_topic_memories(
            user_id=user_id,
            history=conversation_history or "",
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
            commit=True,
        )

    async def detect_dates_for_topic(
        self,
        *,
        user_id: str,
        topic: Any,
        conversation_history: str | None,
        reply_topic_callback,
    ) -> bool:
        if self.date_detector is None:
            return None

        user_texts = []
        for msg in getattr(topic, "source_messages", []) or []:
            content = getattr(msg, "content", "") or ""
            if content.strip():
                user_texts.append(content.strip())
        if not user_texts:
            return None

        date_info = await self.date_detector.detect(
            "\n".join(user_texts),
            conversation_history=conversation_history or "",
        )
        if date_info is None:
            return None

        self.logger.debug(f"DateDetector: {date_info}")
        return await process_detected_date(
            date_info=date_info,
            user_id=user_id,
            open_sql_session=self.database_manager.open_sql_session,
            reply_topic_callback=reply_topic_callback,
        )

    async def update_user_profile_by_context(self, user_id: str, context: dict[str, Any]) -> str | None:
        return await self.memory.update_user_profile_by_context(
            user_id=user_id,
            context=context,
        )

    async def _plan_sing_attempts_for_topic(
        self,
        sing_attempts: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        return self.build_sing_plan_for_topic(sing_attempts)

    def build_sing_plan_for_topic(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        return self.capability_manager.singing.build_sing_plan(self.character_id, sing_attempts)
