"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""

from typing import  List, Dict, Any, Optional, Callable, Tuple, AsyncGenerator
from dataclasses import dataclass
import time
from sqlalchemy.orm import Session
import asyncio
import json
import re
from typing import TYPE_CHECKING
from uuid import uuid4

from ..utils.llm.prompt_manager import PromptManager
from .main_chat import MainChat, OneResponseLine, OneSentenceChat, SongSegmentChat
from .activity_maker import ActivityType
from .topic_extractor import TopicExtractor
from .conversation_manager import ConversationManager
from ..types.conversation_type import ConversationItem
from ..utils.logger import get_logger
from ..tts import TTSModule
from ..utils.enum_type import ContextType, ConversationSource
from ..memory.memory_manager import MemoryManager
from ..plugins.music.singing_manager import SingingManager
from ..vision.vision_module import VisionModule
from ..database.sql_database import User
from ..database.memory_storage import MemoryStorage

from ..pipeline.chat_events import ChatInputEvent, ChatInputEventType
from ..database.vector_store import BaseDocument
if TYPE_CHECKING:
    from ..interface.service_hub import ServiceHub
    from ..pipeline.modules.unread_store import UnreadMessageSnapshot, UnreadMessage
    from ..pipeline.topic_planner import ExtractedTopic
    from ..database.vector_store import VectorStore
    from ..utils.llm.llm_module import LLMAPIInterface
    


def get_available_expression(config_path: str = "config/live2d_interface_config.json") -> List[str]:
    with open(config_path, "r", encoding="utf-8") as f:
        config: Dict = json.load(f)
    expressions: Dict = config.get("expression_projection", {})
    return list(expressions.keys())


@dataclass
class _AgentRuntimeHub:
    """仅供 LuoTianyiAgent 内部使用的运行时依赖。"""

    redis_client: MemoryStorage
    vector_store: "VectorStore"
    sql_session_factory: Callable[[], Session]
    song_session_factory: Callable[[], Session]

    def open_sql_session(self) -> Session:
        return self.sql_session_factory()

    def open_song_session(self) -> Session:
        return self.song_session_factory()


class LuoTianyiAgent:
    """洛天依Agent类

    实现洛天依角色扮演对话Agent的核心逻辑
    """

    def __init__(self, config: Dict[str, Any], tts_module: TTSModule, runtime_hub: "_AgentRuntimeHub") -> None:
        """初始化洛天依Agent

        Args:
            config: 配置字典
        """
        self.config = config
        self.logger = get_logger("LuoTianyiAgent")
        self._runtime_hub = runtime_hub
        self.prompt_manager = PromptManager(self.config.get("prompt_manager", {}))  # 提示管理器

        # 各种模块初始化
        self.conversation_manager = ConversationManager(
            self.config.get("conversation_manager", {}), self.prompt_manager
        )  # 对话管理器
        self.singing_manager = SingingManager(config={})  # 唱歌管理器
        memory_config = self.config.get("memory_manager", {})
        self.memory_manager = MemoryManager(memory_config, self.prompt_manager, self.singing_manager)  # 记忆管理器

        self.tts_engine = tts_module  # TTS模块
        self.main_chat = MainChat(self.config["main_chat"], self.prompt_manager)
        self.topic_extractor = TopicExtractor(
            self.config.get("topic_extractor", {}),
            self.prompt_manager,
        )
        self.vision_module = VisionModule(self.config["vision_module"], self.prompt_manager)

    async def extract_topics_for_pipeline(
        self,
        user_id: str,
        unread_snapshot: "UnreadMessageSnapshot",
        force_complete: bool = False,
    ) -> tuple[List["ExtractedTopic"], List["UnreadMessage"]]:
        """Pipeline 话题提取入口：内部负责获取 conversation_history。"""
        if unread_snapshot is None or not unread_snapshot.messages:
            return [], []

        db = self._runtime_hub.open_sql_session()
        try:
            conversation_history = await self.conversation_manager.get_context(
                db=db,
                redis=self._runtime_hub.redis_client,
                user_id=user_id,
            )
        except Exception as e:
            self.logger.warning(f"Failed to get conversation_history for topic extraction: {e}")
            conversation_history = ""
        finally:
            db.close()

        topics, remaining = await self.topic_extractor.extract_topics(
            unread_snapshot=unread_snapshot,
            conversation_history=conversation_history,
            force_complete=force_complete,
        )
        return topics, remaining
    
    async def generate_topic_from_activity(self, activity_type: ActivityType, user_uuid: str, llm_client: "LLMAPIInterface", **kwargs) -> "ExtractedTopic":
        """根据用户活动生成话题，供 ActivityMaker 调用"""
        prompt = self.prompt_manager.get_template(activity_type.value)
        if not prompt:
            self.logger.error(f"No prompt template found for activity type {activity_type}")
            raise ValueError(f"No prompt template found for activity type {activity_type}")
        prompt = prompt.render(**kwargs)


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
        similarity_threshold: float = 0.62,
        k: int = 3,
    ) -> List[str]:
        """供 TopicReplier 调用的记忆检索接口。"""
        if not queries:
            return []
        return await self.memory_manager.search_memories_for_topic(
            vector_store=self._runtime_hub.vector_store,
            user_id=user_id,
            queries=queries,
            similarity_threshold=similarity_threshold,
            k=k,
        )

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        """供 TopicReplier 调用的歌曲事实检索接口。"""
        if not constraints:
            return []

        db = self._runtime_hub.open_song_session()
        try:
            return await self.memory_manager.search_song_facts_for_topic(
                knowledge_db=db,
                constraints=constraints,
            )
        finally:
            db.close()

    async def get_citywalk_diary_by_date(self, date_str: str) -> str | None:
        """按日期检索 citywalk 报告并返回 diary_text 字段。
        如果同一天有多条记录，返回 created_at 最新的那一条的 diary_text。
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
    ) -> List[OneResponseLine]:
        """供 TopicReplier 调用：按话题生成分段回复。"""
        db = self._runtime_hub.open_sql_session()
        redis_client = self._runtime_hub.redis_client
        try:
            conversation_history = await self.conversation_manager.get_context(db, redis_client, user_id)
            user = db.query(User).filter(User.uuid == user_id).first()
            user_nickname = user.nickname if user and user.nickname else "你"
            user_description = user.description if user and user.description else ""
        finally:
            db.close()

        return await self.main_chat.generate_response(
            reply_topic=topic_content,
            user_nickname=user_nickname,
            user_description=user_description,
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
    ) -> None:
        """供 TopicReplier 调用：在单个 topic 回复完成后异步提取并写入记忆。"""
        db = self._runtime_hub.open_sql_session()
        redis_client = self._runtime_hub.redis_client
        vector_store = self._runtime_hub.vector_store
        try:
            history = await self.conversation_manager.get_context(db, redis_client, user_id)
            await self.memory_manager.post_process_interaction(
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

    async def persist_topic_replies_for_pipeline(
        self,
        user_id: str,
        reply_items: List[OneResponseLine],
    ) -> List[str]:
        """将 topic 回复落库，并触发上下文压缩检查。"""
        if not user_id:
            return []

        conversation_items: List[ConversationItem] = []
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        for item in reply_items:
            if isinstance(item, OneSentenceChat):
                text = item.get_content()
                if not text:
                    continue
                conversation_items.append(
                    ConversationItem(
                        uuid="",
                        timestamp=now,
                        source=ConversationSource.AGENT.value,
                        type=ContextType.TEXT.value,
                        content=text,
                        data=None,
                    )
                )
            elif isinstance(item, SongSegmentChat):
                song_name = item.song or None
                if not song_name:
                    continue
                lyrics = item.lyrics
                content = f"（唱了《{song_name}》）\n{lyrics}"
                conversation_items.append(
                    ConversationItem(
                        uuid="",
                        timestamp=now,
                        source=ConversationSource.AGENT.value,
                        type=ContextType.SING.value,
                        content=content,
                        data={"song": song_name, "segment": item.segment},
                    )
                )

        if not conversation_items:
            return []

        db = self._runtime_hub.open_sql_session()
        redis_client = self._runtime_hub.redis_client
        try:
            uuid_list = await self.conversation_manager.add_conversation_list_to_db(
                db=db,
                redis=redis_client,
                user_id=user_id,
                conversation_list=conversation_items,
                commit=True,
            )
        finally:
            db.close()
        return uuid_list

    async def update_profile_context_for_pipeline(self, user_id: str) -> None:
        """供 TopicReplier 调用：触发用户画像的上下文更新检查。"""
        db = self._runtime_hub.open_sql_session()
        is_conversation_too_long = await self.conversation_manager.is_conversation_too_long(db, user_id)
        if not is_conversation_too_long:
            db.close()
            return
        
        # 需要进行更新，包括两部分，①更新用户画像，②更新上下文摘要
        try:
            context: Dict[str, Any] = await self.conversation_manager.get_context(db, self._runtime_hub.redis_client, user_id, ret_type="json", ts_type="date")
            print(context)
            update_context_task = asyncio.create_task(self.conversation_manager._update_context(db, self._runtime_hub.redis_client, user_id, context, commit=True))
            update_profile_task = asyncio.create_task(self.memory_manager.update_user_profile_by_context(db, self._runtime_hub.redis_client, user_id, context))
            await asyncio.gather(update_context_task, update_profile_task)
        except Exception as e:
            self.logger.error(f"Error in update_profile_context_for_pipeline: {e}")
        finally:
            db.close()
        

    def build_sing_plan_for_topic(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """供 TopicReplier 调用的唱歌计划接口。返回 song|segment。"""
        if not sing_attempts:
            return None, None

        song_name = None
        for attempt in sing_attempts:
            candidate = (attempt or "").strip()
            if not candidate:
                continue
            if candidate == "random_song":
                pair = self.singing_manager.pick_random_song_and_segment()
                return pair if pair else (None, None)

            song_name = self._extract_song_name(candidate)
            if not song_name:
                continue

            segment = self.singing_manager.pick_segment_for_song(song_name)
            if segment:
                return song_name, segment

        return song_name, None # 如果有明确歌名但无法满足唱歌需求，返回歌名和None表示用户想听这首歌但还不会唱
    
    def sing(self, song_name: str, segment: str) -> Optional[str]:
        """调用唱歌管理器生成歌曲片段的音频，并返回音频的Base64字符串"""
        if not song_name or not segment:
            return None
        _, audio_bytes = self.singing_manager.get_song_segment(song_name, segment) # 已经是base64字符串了
        return audio_bytes
    
    async def tts_say(self, text: str, tone: str) -> str:
        audio_bytes = await self.tts_engine.synthesize_speech_with_tone(text, tone)
        return self.tts_engine.encode_audio_to_base64(audio_bytes)
    
    async def tts_say_stream(self, text: str, tone: str) -> AsyncGenerator[str, None]:
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
    
    async def add_conversation(self, service_hub: "ServiceHub", user_uuid: Optional[str], event: ChatInputEvent):
        """将事件转换为对话记录，并添加到数据库中

        Args:
            service_hub: ServiceHub实例，用于调用Agent的处理方法
            user_uuid: 用户UUID，用于区分不同用户的上下文
            event: ChatInputEvent事件对象，包含用户输入的文本和其他相关信息
        """
        if user_uuid is None:
            self.logger.warning("user_uuid is None in add_conversation, skipping")
            return
        if event.event_type not in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE}:
            self.logger.warning(f"Unsupported event type {event.event_type} in add_conversation, skipping")
            return
        
        content = event.text # 对文字信息，它是文本内容；对图片信息，它是图片描述（由视觉模块生成）
        if event.event_type == ChatInputEventType.USER_IMAGE:
            conversation_type = ContextType.IMAGE
            payload = {
                "image_client_path": event.payload.get("image_client_path"),
                "image_server_path": event.payload.get("image_server_path"),
                "mime_type": event.payload.get("mime_type"),
                "terms": event.payload.get("terms", []),
            }
        elif event.event_type == ChatInputEventType.USER_TEXT:
            conversation_type = ContextType.TEXT
            payload = {
                "terms": event.payload.get("terms", []),
                }

        await self.conversation_manager.add_conversation( # 等待入库
            db=self._runtime_hub.open_sql_session(), 
            redis=self._runtime_hub.redis_client, 
            user_id=user_uuid,
            source=ConversationSource.USER,
            content=content,
            type=conversation_type, 
            data=payload,  
        )

    async def handle_history_request(self, user_id: str, count: int, end_index: int) -> Dict[str, Any]:
        """处理历史记录请求

        Args:
            count: 请求的数量
            end_index: 结束索引（不包含），-1表示从最新开始

        Returns:
            (history_list, start_index)
        """
        db = self._runtime_hub.open_sql_session()
        try:
            total_count = await self.conversation_manager.get_total_conversation_count(db, user_id)

            if end_index == -1 or end_index > total_count:
                end_index = total_count

            start_index = max(0, end_index - count)

            # 如果请求范围无效（例如已经到了最开始），返回空列表
            if start_index >= end_index:
                return {"history": [], "start_index": 0}

            history_items = await self.conversation_manager.get_history(db, user_id, start_index, end_index)

            # 转换为UI需要的格式
            ret = {"history": [], "start_index": start_index}

            for item in history_items:
                if item.type == ContextType.IMAGE.value and item.data:
                    # 图片消息，返回图片路径
                    image_client_path = item.data.get("image_client_path")
                    content = image_client_path
                else:
                    content = item.content
                ret["history"].append(
                    {"uuid": item.uuid, "content": content, "source": item.source, "timestamp": item.timestamp, "type": item.type}
                )

            return ret
        finally:            
            db.close()


agent = None


def init_luotianyi_agent(
    config: Dict[str, Any],
    tts_module: TTSModule,
    redis_client: MemoryStorage,
    vector_store: Any,
    sql_session_factory: Callable[[], Session],
    song_session_factory: Callable[[], Session],
):
    """初始化洛天依Agent实例

    Args:
        config: 配置字典
    Returns:
        LuoTianyiAgent实例
    """
    global agent
    runtime_hub = _AgentRuntimeHub(
        redis_client=redis_client,
        vector_store=vector_store,
        sql_session_factory=sql_session_factory,
        song_session_factory=song_session_factory,
    )
    agent = LuoTianyiAgent(config, tts_module, runtime_hub)


def get_luotianyi_agent() -> LuoTianyiAgent:
    """获取洛天依Agent实例

    Returns:
        LuoTianyiAgent实例
    """
    if agent is None:
        raise ValueError("LuoTianyiAgent has not been initialized.")
    return agent
