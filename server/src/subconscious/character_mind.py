from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from src.subconscious.attention import AttentionPlanner, TopicAttentionPlan
from src.domain import CharacterProfile
from src.subconscious.date_processor import DateDetector, process_detected_date
from src.subconscious.memory import SongKnowledgeMemory, SubconsciousMemory
from src.subconscious.state import SubconsciousState
from src.subconscious.topic_extractor import TopicExtractor
from src.utils.llm.prompt_manager import PromptManager
from src.utils.logger import get_logger


class CharacterSubconscious:
    """Per-character subconscious services.

    This owns recall, topic extraction, attention material, state, date
    detection, and memory/profile writes for one character. The conscious agent
    consumes the plans and context produced here.
    """

    def __init__(
        self,
        config: dict[str, Any],
        runtime_hub: Any,
        character_profile: CharacterProfile,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self.config = config
        self.runtime_hub = runtime_hub
        self.character_profile = character_profile
        self.character_id = character_profile.character_id
        self.logger = get_logger(f"{self.character_id}Subconscious")
        self.prompt_manager = prompt_manager or PromptManager(config.get("prompt_manager", {}))

        self.memory = SubconsciousMemory(
            config["memory_manager"],
            self.prompt_manager,
            owner_character_id=self.character_id,
        )
        self.state = SubconsciousState(owner_character_id=self.character_id)
        self.song_knowledge = SongKnowledgeMemory(
            config.get("song_knowledge", {}),
            runtime_hub.music_manager,
        )
        self.memory_updates = self.memory.updates
        self.topic_extractor = TopicExtractor(config["topic_extractor"], self.prompt_manager)
        self.attention_planner = AttentionPlanner(
            config.get("attention_planner", {}),
            target_character_id=self.character_id,
        )
        date_cfg = config.get("date_detector", {})
        self.date_detector = DateDetector(date_cfg, self.prompt_manager) if date_cfg else None

    def get_state(self):
        return self.state.get_snapshot()

    async def extract_topics(
        self,
        user_id: str,
        unread_snapshot: Any,
        force_complete: bool = False,
        conversation_history: str | None = None,
    ):
        if unread_snapshot is None or not unread_snapshot.messages:
            return None, []

        if conversation_history is None:
            conversation_history = ""

        return await self.topic_extractor.extract_topics(
            unread_snapshot=unread_snapshot,
            conversation_history=conversation_history,
            force_complete=force_complete,
        )

    async def search_memories_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.60,
        k: int = 3,
    ) -> List[str]:
        if not queries:
            return []
        return await self.memory.search_memories_for_topic(
            vector_store=self.runtime_hub.vector_store,
            user_id=user_id,
            queries=queries,
            similarity_threshold=similarity_threshold,
            k=k,
        )

    async def search_memory_context_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
    ):
        if not queries:
            from src.domain import MemoryContext

            return MemoryContext()

        db = self.runtime_hub.open_sql_session()
        try:
            return await self.memory.search_memory_context_for_topic(
                db=db,
                vector_store=self.runtime_hub.vector_store,
                user_id=user_id,
                queries=queries,
                similarity_threshold=similarity_threshold,
                k=k,
            )
        finally:
            db.close()

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        return await self.song_knowledge.search_song_facts_for_topic(constraints)

    async def plan_topic_turn(
        self,
        user_id: str,
        topic: Any,
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
    ) -> None:
        db = self.runtime_hub.open_sql_session()
        redis_client = self.runtime_hub.redis_client
        vector_store = self.runtime_hub.vector_store
        try:
            history = conversation_history or ""
            await self.memory_updates.post_process_interaction(
                db=db,
                redis=redis_client,
                vector_store=vector_store,
                user_id=user_id,
                history=history,
                current_dialogue=current_dialogue,
                related_memories=related_memories or [],
                commit=True,
            )
        finally:
            db.close()

    async def detect_dates_for_topic(
        self,
        *,
        user_id: str,
        topic: Any,
        conversation_history: str | None,
        reply_topic_callback,
    ):
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
            open_sql_session=self.runtime_hub.open_sql_session,
            reply_topic_callback=reply_topic_callback,
        )

    async def update_user_profile_by_context(self, user_id: str, context: dict[str, Any]) -> str | None:
        db = self.runtime_hub.open_sql_session()
        try:
            return await self.memory_updates.update_user_profile_by_context(
                db,
                self.runtime_hub.redis_client,
                user_id,
                context,
            )
        finally:
            db.close()

    async def search_fact_constraints_for_topic(self, fact_constraints: List[str]) -> List[str]:
        if not fact_constraints:
            return []

        special_hits: List[str] = []
        regular_constraints: List[str] = []
        for constraint in fact_constraints:
            if constraint == "/SongsCanSing":
                try:
                    songs_json = await self.runtime_hub.music_manager.get_songs_can_sing_llm(max_song_num=15)
                    special_hits.append(f"可演唱歌曲推荐：{songs_json}")
                except Exception as e:
                    self.logger.error(f"Failed to get songs can sing: {e}")
                continue

            if constraint.startswith("/CanISing"):
                song_name = constraint[len("/CanISing"):].strip()
                if not song_name:
                    continue
                try:
                    special_hits.append(await self.runtime_hub.music_manager.can_i_sing_song_llm(song_name))
                except Exception as e:
                    self.logger.error(f"Failed to get can I sing for {song_name}: {e}")
                continue

            regular_constraints.append(constraint)

        regular_hits = await self.search_song_facts_for_topic(regular_constraints) if regular_constraints else []
        return special_hits + regular_hits

    async def _plan_sing_attempts_for_topic(
        self,
        sing_attempts: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        return self.build_sing_plan_for_topic(sing_attempts)

    def build_sing_plan_for_topic(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        capabilities = self.runtime_hub.capabilities
        if capabilities is not None:
            return capabilities.singing.build_sing_plan(self.character_id, sing_attempts)
        if not sing_attempts:
            return None, None

        song_name = None
        manager = self.runtime_hub.music_manager
        for attempt in sing_attempts:
            candidate = (attempt or "").strip()
            if not candidate:
                continue
            if candidate == "random_song":
                pair = manager.pick_random_song_and_segment()
                return pair if pair else (None, None)

            song_name = self._extract_song_name(candidate)
            if not song_name:
                continue

            correct_song_name, segment = manager.pick_segment_for_song(song_name)
            if segment:
                return correct_song_name, segment
        if song_name:
            manager.add_wished_song(song_name)
        return song_name, None

    def _extract_song_name(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return ""

        match = re.search(r"《([^》]+)》", content)
        if match:
            return match.group(1).strip()

        if "是一首歌" in content:
            return content.split("是一首歌", 1)[0].strip().strip("《》")

        return content.strip("\"'“”‘’《》")
