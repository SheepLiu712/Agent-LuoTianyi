"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""

from typing import  List, Dict, Any, Optional, Callable, Tuple, Generator
from dataclasses import dataclass
from sqlalchemy.orm import Session
import asyncio
import json
import re
from typing import TYPE_CHECKING
from uuid import uuid4

from src.utils.llm.prompt_manager import PromptManager
from src.agent.date_processor import DateDetector
from src.agent.main_chat import MainChat, OneResponseLine
from src.chat_session.proactive_topic_maker import ActivityType
from src.agent.topic_extractor import TopicExtractor
from src.system import ConversationManager
from src.utils.logger import get_logger
from src.capabilities.speech import TTSModule
from src.subconscious.memory import SongKnowledgeMemory, SubconsciousMemory
from src.subconscious.state import SubconsciousState
from src.agent.attention_planner import AttentionPlanner, TopicAttentionPlan
from src.agent.response_realizer import ResponseRealizer, UserExpressionContext
from src.domain import CharacterProfile

from src.utils.vision.vision_module import VisionModule

from src.system.database.vector_store import BaseDocument
if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.agent.chat.unread_store import UnreadMessageSnapshot, UnreadMessage
    from src.agent.chat.topic_planner import ExtractedTopic
    from src.system.database.vector_store import VectorStore
    from src.utils.llm.llm_module import LLMAPIInterface
    from src.subconscious.music_knowledge.music_manager import MusicManager
    from src.system.database.redis_buffer import RedisBuffer
    


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


@dataclass
class _AgentRuntimeHub:
    """仅供 LuoTianyiAgent 内部使用的运行时依赖。"""

    redis_client: "RedisBuffer"
    vector_store: "VectorStore"
    sql_session_factory: Callable[[], Session]
    database: Any
    music_manager: "MusicManager"
    capabilities: Any | None = None

    def open_sql_session(self) -> Session:
        return self.sql_session_factory()


class LuoTianyiAgent:
    """洛天依Agent类

    实现洛天依角色扮演对话Agent的核心逻辑
    """

    def __init__(
        self,
        config: Dict[str, Any],
        tts_module: TTSModule,
        runtime_hub: "_AgentRuntimeHub",
        character_profile: CharacterProfile | None = None,
    ) -> None:
        """初始化洛天依Agent

        Args:
            config: 配置字典
        """
        self.config = config
        self.logger = get_logger("LuoTianyiAgent")
        self._runtime_hub = runtime_hub
        self.character_profile = character_profile
        self.character_id = character_profile.character_id if character_profile else "luotianyi"
        self.music_manager = runtime_hub.music_manager
        self.capabilities = runtime_hub.capabilities
        self.prompt_manager = PromptManager(self.config.get("prompt_manager", {}))  # 提示管理器

        # 各种模块初始化
        self.conversation_manager = ConversationManager(
            self.config.get("conversation_manager", {}), self.prompt_manager, db_manager=runtime_hub.database
        )  # 对话管理器
        self.subconscious_memory = SubconsciousMemory(
            self.config["memory_manager"],
            self.prompt_manager,
            owner_character_id=self.character_id,
        )
        self.subconscious_state = SubconsciousState(owner_character_id=self.character_id)
        self.song_knowledge_memory = SongKnowledgeMemory(runtime_hub.music_manager)
        self.memory_updates = self.subconscious_memory.updates
        # Compatibility alias for legacy callers while dependencies migrate.
        self.memory_manager = self.subconscious_memory

        self.tts_engine = tts_module  # TTS模块
        self.main_chat = MainChat(self.config["main_chat"], self.prompt_manager)
        self.attention_planner = AttentionPlanner(target_character_id=self.character_id)
        self.response_realizer = ResponseRealizer(self.main_chat)
        self.topic_extractor = TopicExtractor(self.config["topic_extractor"],self.prompt_manager,)
        self.vision_module = VisionModule(self.config["vision_module"], self.prompt_manager)

        self.date_detector = DateDetector(self.config["date_detector"]["llm_module"], self.prompt_manager)
        

    def save_preferences(self, user_uuid: str, preferences: dict) -> bool:
        """保存用户偏好设置到数据库。"""
        saved = self._runtime_hub.database.save_user_preferences(user_uuid, preferences)
        if saved:
            self.logger.info(f"Saved preferences for user {user_uuid}: {preferences}")
        else:
            self.logger.warning(f"User {user_uuid} not found")
        return saved

    async def extract_topics_for_pipeline(
        self,
        user_id: str,
        unread_snapshot: "UnreadMessageSnapshot",
        force_complete: bool = False,
        conversation_history: str | None = None,
    ) -> tuple[Optional["ExtractedTopic"], List["UnreadMessage"]]:
        """Pipeline topic extraction entry.

        The system layer should provide conversation_history. The fallback read
        remains only for legacy callers.
        """
        if unread_snapshot is None or not unread_snapshot.messages:
            return None, []

        if conversation_history is None:
            try:
                conversation_history = await self.conversation_manager.get_context(
                    db=None,
                    redis=None,
                    user_id=user_id,
                )
            except Exception as e:
                self.logger.warning(f"Failed to get conversation_history for topic extraction: {e}")
                conversation_history = ""

        topic, remaining = await self.topic_extractor.extract_topics(
            unread_snapshot=unread_snapshot,
            conversation_history=conversation_history,
            force_complete=force_complete,
        )
        return topic, remaining
    
    async def generate_topic_from_activity(self, activity_type: ActivityType, user_uuid: str, llm_client: "LLMAPIInterface", **kwargs) -> "ExtractedTopic":
        """根据用户活动生成话题，供 ProactiveTopicMaker 调用"""
        from src.agent.chat.topic_planner import ExtractedTopic
        from src.agent.chat.unread_store import UnreadMessage
        prompt = self.prompt_manager.get_template(activity_type.value)
        if not prompt:
            self.logger.error(f"No prompt template found for activity type {activity_type}")
            raise ValueError(f"No prompt template found for activity type {activity_type}")
        prompt = prompt.render(**kwargs)

        content = await llm_client.generate_response(prompt, use_json=False)
        content = (content or {}).get("content", "") if isinstance(content, dict) else str(content)
        return ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=[],
            topic_content=content or prompt,
            summary="",
            is_activity=True,
        )


    async def describe_image(self, image_base64: str) -> str:
        """调用视觉模块对图片进行描述

        Args:
            image_base64: 图片的Base64字符串

        Returns:
            图片描述文本
        """
        return await self.vision_module.describe_image(image_base64)

    async def search_memories_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.60,
        k: int = 3,
    ) -> List[str]:
        """供 TopicReplier 调用的记忆检索接口。"""
        if not queries:
            return []
        return await self.subconscious_memory.search_memories_for_topic(
            vector_store=self._runtime_hub.vector_store,
            user_id=user_id,
            queries=queries,
            similarity_threshold=similarity_threshold,
            k=k,
        )

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        """供 TopicReplier (或其他组件) 查找歌曲信息的代理方法"""
        return await self.song_knowledge_memory.search_song_facts_for_topic(constraints)

    async def plan_topic_turn_for_pipeline(
        self,
        user_id: str,
        topic: "ExtractedTopic",
        conversation_history: str,
        external_context: Optional[str] = None,
    ) -> TopicAttentionPlan:
        """Build a conscious attention plan for one legacy chat topic."""
        return await self.attention_planner.plan_topic_turn(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            memory_search=lambda queries: self.search_memory_context_for_topic(
                user_id=user_id,
                queries=queries,
                similarity_threshold=0.8,
            ),
            fact_search=self._search_fact_constraints_for_topic,
            sing_planner=self._plan_sing_attempts_for_topic,
            external_context=external_context,
            agent_state=self.subconscious_state.get_snapshot(),
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

        db = self._runtime_hub.open_sql_session()
        try:
            return await self.subconscious_memory.search_memory_context_for_topic(
                db=db,
                vector_store=self._runtime_hub.vector_store,
                user_id=user_id,
                queries=queries,
                similarity_threshold=similarity_threshold,
                k=k,
            )
        finally:
            db.close()

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
        if not fact_constraints:
            return []

        special_hits: List[str] = []
        regular_constraints: List[str] = []
        for constraint in fact_constraints:
            if constraint == "/SongsCanSing":
                try:
                    songs_json = await self.music_manager.get_songs_can_sing_llm(max_song_num=15)
                    special_hits.append(f"可演唱歌曲推荐：{songs_json}")
                except Exception as e:
                    self.logger.error(f"Failed to get songs can sing: {e}")
                continue

            if constraint.startswith("/CanISing"):
                song_name = constraint[len("/CanISing"):].strip()
                if not song_name:
                    continue
                try:
                    special_hits.append(await self.music_manager.can_i_sing_song_llm(song_name))
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

    def _load_user_expression_context(self, user_id: str) -> UserExpressionContext:
        data = self._runtime_hub.database.get_user_expression_context_data(user_id)
        return UserExpressionContext(
            nickname=data["nickname"],
            description=data["description"],
            preference_context=self._build_preference_context(data["preferences"]),
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
            conversation_history = await self.conversation_manager.get_context(None, None, user_id)
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
        db = self._runtime_hub.open_sql_session()
        redis_client = self._runtime_hub.redis_client
        vector_store = self._runtime_hub.vector_store
        try:
            history = conversation_history or await self.conversation_manager.get_context(db, redis_client, user_id)
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

    def build_sing_plan_for_topic(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """供 TopicReplier 调用的唱歌计划接口。返回 song|segment。"""
        if self.capabilities is not None:
            return self.capabilities.singing.build_sing_plan(sing_attempts)
        if not sing_attempts:
            return None, None

        song_name = None
        for attempt in sing_attempts:
            candidate = (attempt or "").strip()
            if not candidate:
                continue
            if candidate == "random_song":
                pair = self.music_manager.pick_random_song_and_segment()
                return pair if pair else (None, None)

            song_name = self._extract_song_name(candidate)
            if not song_name:
                continue

            correct_song_name, segment = self.music_manager.pick_segment_for_song(song_name)
            if segment:
                return correct_song_name, segment
        if song_name:
            self.music_manager.add_wished_song(song_name)
        return song_name, None # 如果有明确歌名但无法满足唱歌需求，返回歌名和None表示用户想听这首歌但还不会唱
    
    def sing(self, song_name: str, segment: str) -> Optional[bytes]:
        """调用唱歌管理器生成歌曲片段的音频，并返回音频的Base64字符串"""
        if self.capabilities is not None:
            return self.capabilities.singing.sing(song_name, segment)
        if not song_name or not segment:
            return None
        _, audio_bytes = self.music_manager.get_song_segment(song_name, segment) # 已经是base64字符串了
        return audio_bytes
    
    async def tts_say(self, text: str, tone: str) -> str:
        if self.capabilities is not None:
            return await self.capabilities.speech.say(text, tone)
        audio_bytes = await self.tts_engine.synthesize_speech_with_tone(text, tone)
        return self.tts_engine.encode_audio_to_base64(audio_bytes)
    
    def tts_say_stream(self, text: str, tone: str) -> Generator[str, None, None]:
        if self.capabilities is not None:
            yield from self.capabilities.speech.say_stream(text, tone)
            return
        for chunk in self.tts_engine.stream_synthesize_speech_with_tone(text, tone):
            yield self.tts_engine.encode_audio_to_base64(chunk)

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

    def _format_memory_hit(self, doc: BaseDocument) -> str:
        timestamp = ""
        if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
            timestamp = str(doc.metadata.get("timestamp") or "").strip()
        content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
        if not content:
            return ""
        if timestamp:
            return f"在{timestamp}, {content}"
        return content
