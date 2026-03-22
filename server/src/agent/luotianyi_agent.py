"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""

from typing import AsyncGenerator, List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod
import time
from sqlalchemy.orm import Session
import redis
import asyncio
import json
from fastapi import UploadFile
import re
import base64
from typing import TYPE_CHECKING

from ..llm.prompt_manager import PromptManager
from .main_chat import MainChat, OneSentenceChat, SongSegmentChat
from .main_chat_v2 import MainChatV2, TopicReplyResult
from .planner import Planner
from .topic_extractor import TopicExtractor
from .conversation_manager import ConversationManager
from ..types.conversation_type import ConversationItem
from ..utils.logger import get_logger
from ..tts import TTSModule
from ..utils.enum_type import ContextType, ConversationSource
from ..memory.memory_manager import MemoryManager
from ..service.types import ChatResponse
from ..music.singing_manager import SingingManager
from ..music.knowledge_service import get_song_introduction, get_song_lyrics
from ..vision.vision_module import VisionModule
from ..vision.image_process import get_image_bytes_and_base64, get_postfix, save_image
from ..database.sql_database import get_sql_session
from ..database.sql_database import User

from ..pipeline.chat_events import ChatInputEvent, ChatInputEventType
from ..pipeline.global_speaking_worker import SpeakingJob
from ..database.vector_store import BaseDocument
if TYPE_CHECKING:
    from ..service.service_hub import ServiceHub
    from ..pipeline.modules.unread_store import UnreadMessageSnapshot, UnreadMessage
    from ..pipeline.topic_planner import ExtractedTopic
    from ..database.vector_store import VectorStore


def get_available_expression(config_path: str = "config/live2d_interface_config.json") -> List[str]:
    with open(config_path, "r", encoding="utf-8") as f:
        config: Dict = json.load(f)
    expressions: Dict = config.get("expression_projection", {})
    return list(expressions.keys())


@dataclass
class _AgentRuntimeHub:
    """仅供 LuoTianyiAgent 内部使用的运行时依赖。"""

    redis_client: redis.Redis
    vector_store: VectorStore
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
        self.memory_manager.memory_searcher.register_tools(self.singing_manager.get_tools())  # 注册唱歌工具

        self.tts_engine = tts_module  # TTS模块

        self.main_chat = MainChat(
            self.config["main_chat"],
            self.prompt_manager,
            available_tone=tts_module.get_available_tones(),
            available_expression=get_available_expression(),
        )
        main_chat_v2_config = self.config.get("main_chat_v2")
        if main_chat_v2_config is None:
            main_chat_v2_config = {
                **self.config.get("main_chat", {}),
                "llm_module": {
                    **self.config.get("main_chat", {}).get("llm_module", {}),
                    "prompt_name": "topic_reply_prompt",
                },
            }
        self.main_chat_v2 = MainChatV2(main_chat_v2_config, self.prompt_manager)
        self.topic_extractor = TopicExtractor(
            self.config.get("topic_extractor", {}),
            self.prompt_manager,
        )
        self.planner = Planner(config["planner"], self.prompt_manager, self.singing_manager)
        self.vision_module = VisionModule(config["vision_module"], self.prompt_manager)

    async def extract_topics_for_pipeline(
        self,
        service_hub: "ServiceHub",
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
        similarity_threshold: float = 0.8,
        k: int = 3,
    ) -> List[str]:
        """供 TopicReplier 调用的记忆检索接口。"""
        vector_store = self._runtime_hub.vector_store
        if vector_store is None or not queries:
            return []

        async def _search_one(query: str) -> List[str]:
            q = (query or "").strip()
            if not q:
                return []

            results = await vector_store.search(user_id, q, k=max(1, k))
            texts: List[str] = []
            for doc, score in results:
                if score < similarity_threshold:
                    continue
                content = self._format_memory_hit(doc)
                if content:
                    texts.append(content)
            return texts

        batches = await asyncio.gather(*[_search_one(q) for q in queries], return_exceptions=True)
        dedup: List[str] = []
        seen = set()
        for item in batches:
            if isinstance(item, Exception):
                self.logger.warning(f"Topic memory search failed: {item}")
                continue
            for text in item:
                if text not in seen:
                    seen.add(text)
                    dedup.append(text)
        return dedup

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        """供 TopicReplier 调用的歌曲事实检索接口。"""
        if not constraints:
            return []

        db = self._runtime_hub.open_song_session()
        try:
            dedup: List[str] = []
            seen = set()
            for raw in constraints:
                song_name = self._extract_song_name(raw)
                if not song_name:
                    continue
                intro = await asyncio.to_thread(get_song_introduction, db, song_name)
                lyrics = await asyncio.to_thread(get_song_lyrics, db, song_name)
                if intro:
                    text = f"《{song_name}》的介绍:\n{intro}"
                    if text not in seen:
                        seen.add(text)
                        dedup.append(text)
                if lyrics:
                    text = f"《{song_name}》的歌词:\n{lyrics}"
                    if text not in seen:
                        seen.add(text)
                        dedup.append(text)
            return dedup
        finally:
            db.close()

    async def generate_topic_reply_for_pipeline(
        self,
        user_id: str,
        topic_content: str,
        memory_hits: Optional[List[str]] = None,
        fact_hits: Optional[List[str]] = None,
        sing_song: Optional[str] = None,
    ) -> List[TopicReplyResult]:
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

        return await self.main_chat_v2.generate_response(
            reply_topic=topic_content,
            user_nickname=user_nickname,
            user_description=user_description,
            conversation_history=conversation_history,
            fact_hits=fact_hits or [],
            memory_hits=memory_hits or [],
            sing_song=sing_song,
        )

    def build_sing_plan_for_topic(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """供 TopicReplier 调用的唱歌计划接口。返回 song|segment。"""
        if not sing_attempts:
            return None, None

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

        return None, None

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
        
        content = event.text
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

        await self.conversation_manager.add_conversation(
            db=self._runtime_hub.open_sql_session(), 
            redis=self._runtime_hub.redis_client, 
            user_id=user_uuid,
            source=ConversationSource.USER,
            content=content,
            type=conversation_type, 
            data=payload,  
        )
        
        
    ############下方为旧的接口############

    async def mock_handle_user_input(
        self, 
        user_id: str, 
        text: str, 
        db: Session, 
        redis: redis.Redis, 
        vector_store: Any = None, 
        knowledge_db: Session = None
    ) -> AsyncGenerator[ChatResponse, None]:
        import os
        from datetime import datetime
        cwd = os.getcwd()
        wav_path = os.path.join(cwd, "example_audio.wav")
        with open(wav_path, "rb") as audio_file:
            original_audio_data = audio_file.read()
            base64_audio = base64.b64encode(original_audio_data).decode('utf-8')
        
        new_conversation_list: List[ConversationItem] = [
            ConversationItem(uuid="mock_conv_1", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source="agent", content="Mock response for user input", type="text", data={"expression": "微笑脸", "tone": "normal"}),
            ConversationItem(uuid="mock_conv_2", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source="agent", content="Mock response for user input", type="sing", data={"song": "上山岗", "segment": "段落1"}),
            ConversationItem(uuid="mock_conv_3", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source="agent", content="Mock response for user input", type="text", data={"expression": "微笑脸", "tone": "normal"}),
            ]
        await asyncio.sleep(5)  # 模拟处理延迟
        for conv in new_conversation_list:
            if conv.type == "text":
                # 从 conv.data 中提取 expression 和 tone
                expression = conv.data.get("expression", "normal")
                tone = conv.data.get("tone", "normal")
                audio_data_base64 = base64_audio
                response = ChatResponse(
                    uuid=conv.uuid, text=conv.content, expression=expression, audio=audio_data_base64, is_final_package=True
                )
                yield response
            elif conv.type == "sing":
                song = conv.data.get("song", "unknown")
                segment = conv.data.get("segment", "unknown")
                _, sing_audio_base64_str = self.singing_manager.get_song_segment(song, segment)
                sent_text = conv.content
                total_length = len(sing_audio_base64_str) if sing_audio_base64_str else 0
                chunk_size = 640 * 1024  # 640KB per chunk
                if total_length == 0:
                    self.logger.warning(f"No audio data for singing segment: {song} - {segment}")
                    yield ChatResponse(text=sent_text, expression="唱歌", audio="")
                else:
                    for i in range(0, total_length, chunk_size):
                        chunk = sing_audio_base64_str[i : i + chunk_size]
                        yield ChatResponse(
                            uuid=conv.uuid,
                            text=sent_text if i == 0 else "",  # 只有第一帧发送文本
                            expression="唱歌" if i == 0 else None,  # 只有第一帧发送表情
                            audio=chunk,
                            is_final_package=(i + chunk_size >= total_length),
                        )
                        await asyncio.sleep(0)  # 让出控制权，确保数据能及时通过网络栈发送出去


    async def handle_user_text_input(
        self,
        user_id: str,
        text: str,
        db: Session,
        redis: redis.Redis,
        vector_store: Any = None,
        knowledge_db: Session = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        """处理用户文本输入，生成回复（流式）。"""
        self.logger.info(f"Agent handling text input for {user_id}: {text}")
        await self.conversation_manager.add_conversation(
            db, redis, user_id, ConversationSource.USER, text, type=ContextType.TEXT, data=None
        )
        async for response in self.shared_process_pipeline(user_id, text, db, redis, vector_store, knowledge_db):
            yield response

    async def handle_user_pic_input(
        self,
        user_id: str,
        image: UploadFile,
        image_client_path: str,
        db: Session,
        redis: redis.Redis,
        vector_store: Any,
        knowledge_db: Session,
    ) -> AsyncGenerator[ChatResponse, None]:
        """处理用户图片输入，生成回复（流式）。"""
        self.logger.info(f"Agent handling image input for {user_id}")

        # 1. 获取图片字节和Base64字符串，并保存图片到服务器
        image_bytes, image_base64 = await get_image_bytes_and_base64(image)
        postfix = get_postfix(image.filename)
        image_server_path = save_image(user_id, image_bytes, postfix)

        # 将图片通过vlm模块转换为描述文本，并添加到对话中
        image_description = await self.describe_image(image_base64)
        image_description = f"（用户发送了一张图片）：{image_description}"
        await self.conversation_manager.add_conversation(
            db,
            redis,
            user_id,
            ConversationSource.USER,
            content=image_description,
            type=ContextType.IMAGE,
            data={"image_client_path": image_client_path, "image_server_path": image_server_path},
        )
        async for response in self.shared_process_pipeline(user_id, image_description, db, redis, vector_store, knowledge_db):
            yield response

    async def shared_process_pipeline(
        self,
        user_id: str,
        text: str,
        db: Session,
        redis: redis.Redis,
        vector_store: Any = None,
        knowledge_db: Session = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        """
        处理用户输入，生成回复（流式）。
        逻辑对应原 luotianyi_agent.py 中的 handle_user_input，但改为无状态和异步。

        Args:
            user_id: 用户ID，用于区分不同用户的上下文
            text: 用户输入的文本
            db: SQL数据库会话，用于持久化存储
            redis: Redis客户端，用于快速存取短期记忆/上下文
            vector_store: 向量数据库接口
            knowledge_db: Session = None,

        Yields:
            ChatResponse: 包含文本、表情、语音等信息的响应片段
        """
        # 1. 获取上下文 (Cache Aside 模式：优先查Redis，未命中则查DB并回写)
        context_data = await self.conversation_manager.get_context(db, redis, user_id)

        # 2. 记忆与知识检索 (并发执行，避免阻塞)
        username_task = asyncio.create_task(self.memory_manager.get_username(db, redis, user_id))
        knowledge_task = asyncio.create_task(
            self.memory_manager.get_knowledge(db, redis, vector_store, knowledge_db, user_id, text, context_data)
        )
        user_nickname, retrieved_knowledge = await asyncio.gather(username_task, knowledge_task)

        # 3. 调用LLM生成文本 (异步流式或分段)
        # 3a. 调用规划器生成行动计划
        planning_step = await self.planner.generate_response(
            user_input=text, conversation_history=context_data, retrieved_knowledge=retrieved_knowledge
        )
        # 3b. 根据行动计划调用主聊天模块生成回复
        llm_responses = await self.main_chat.generate_response(
            user_input=text,
            conversation_history=context_data,
            retrieved_knowledge=retrieved_knowledge,
            username=user_nickname,
            planning_step=planning_step,
        )

        # 4. 准备生成的回复内容列表，供后续处理使用
        agent_response_contents = [resp.get_content() for resp in llm_responses]

        # 5. 处理生成的回复片段
        new_conversation_list: List[ConversationItem] = []
        # 5a. 拆分回复，创建所有的对话对象
        for resp in llm_responses:
            if resp.type == ContextType.SING:
                parameter: SongSegmentChat = resp.parameters
                lrc_lines, _ = self.singing_manager.get_song_segment(parameter.song, parameter.segment, require_audio=False)
                lrc = [line.content for line in lrc_lines]
                sent_text = "（唱歌）：《" + parameter.song + "》\n" + "\n".join(lrc)
                conv = self.conversation_manager.add_conversation_wo_db(
                    user_id,
                    ConversationSource.AGENT,
                    sent_text,
                    type=ContextType.SING,
                    data={"song": parameter.song, "segment": parameter.segment},
                )
                new_conversation_list.append(conv)
            elif resp.type == ContextType.TEXT:
                resp: OneSentenceChat = resp.parameters
                resp_split = self._split_responses([resp])
                for split_resp in resp_split:
                    sent_content = split_resp.content
                    expression = split_resp.expression
                    tone = split_resp.tone if split_resp.tone else "normal"
                    conv = self.conversation_manager.add_conversation_wo_db(
                        user_id,
                        ConversationSource.AGENT,
                        sent_content,
                        type=ContextType.TEXT,
                        data={"expression": expression, "tone": tone},
                    )
                    new_conversation_list.append(conv)

        # 5b. 创建统一的记忆写入任务，异步执行，避免阻塞
        async def unified_background_write():
            # 使用独立的 Session，不使用 FastAPI 注入的 db
            async_db = get_sql_session()
            try:
                # 1. 批量写入对话记录
                await self.conversation_manager.add_conversation_list_to_db(
                    async_db, redis, user_id, new_conversation_list, commit=False  # 统一提交，等全部操作完成后再提交
                )

                # 2. 记忆后期处理（包含向量库写入和 Summary 更新）
                await self.memory_manager.post_process_interaction(
                    db=async_db,
                    redis=redis,
                    vector_store=vector_store,
                    user_id=user_id,
                    user_input=text,
                    agent_response_content=agent_response_contents,
                    history=context_data,
                    commit=False,  # 记忆写入时不立即提交，等全部操作完成后再统一提交
                )

                # 3. 最后一并提交
                async_db.commit()
            except Exception as e:
                async_db.rollback()
                self.logger.error(f"Background write failed for {user_id}: {e}")
            finally:
                async_db.close()  # 必须手动关闭

        write_task = asyncio.create_task(unified_background_write())

        # 5c. 生成语音并流式发送响应
        for conv in new_conversation_list:
            if conv.type == "text":
                # 从 conv.data 中提取 expression 和 tone
                expression = conv.data.get("expression", "normal")
                tone = conv.data.get("tone", "normal")
                audio_wav_bytes = await self.tts_engine.synthesize_speech_with_tone(conv.content, tone)
                audio_data_base64 = self.tts_engine.encode_audio_to_base64(audio_wav_bytes)
                response = ChatResponse(
                    uuid=conv.uuid, text=conv.content, expression=expression, audio=audio_data_base64, is_final_package=True
                )
                yield response
            elif conv.type == "sing":
                song = conv.data.get("song", "unknown")
                segment = conv.data.get("segment", "unknown")
                _, sing_audio_base64_str = self.singing_manager.get_song_segment(song, segment)
                sent_text = conv.content
                total_length = len(sing_audio_base64_str) if sing_audio_base64_str else 0
                chunk_size = 640 * 1024  # 640KB per chunk
                if total_length == 0:
                    self.logger.warning(f"No audio data for singing segment: {song} - {segment}")
                    yield ChatResponse(text=sent_text, expression="唱歌", audio="")
                else:
                    for i in range(0, total_length, chunk_size):
                        chunk = sing_audio_base64_str[i : i + chunk_size]
                        yield ChatResponse(
                            uuid=conv.uuid,
                            text=sent_text if i == 0 else "",  # 只有第一帧发送文本
                            expression="唱歌" if i == 0 else None,  # 只有第一帧发送表情
                            audio=chunk,
                            is_final_package=(i + chunk_size >= total_length),
                        )
                        await asyncio.sleep(0)  # 让出控制权，确保数据能及时通过网络栈发送出去

        # 6. 等待记忆写入和数据库写入完成，确保数据一致性
        await write_task
        self.logger.info(f"Finished handling input for {user_id}")

    def _split_responses(self, responses: List[OneSentenceChat]) -> List[OneSentenceChat]:
        """将长文本拆分为多个响应片段

        Args:
            responses: 原始响应列表

        Returns:
            拆分后的响应列表
        """

        def clean_sound_content(text: str) -> str:
            # Remove content within parentheses (Chinese and English)
            return re.sub(r"（.*?）|\(.*?\)", "", text)

        punct_pattern = re.compile(r"^(?:\.{3}|[。，！？~,])+$")

        split_responses: List[OneSentenceChat] = []
        for resp in responses:
            # 使用捕获组 () 保留分隔符
            parts = re.split(r"((?:\.{3}|[。，！？~,]))", resp.content)

            # 获取带标点符号的各个句子
            sentences_with_punct = []
            for s in parts:
                if not s:
                    continue
                if punct_pattern.match(s) and sentences_with_punct:
                    sentences_with_punct[-1] += s
                else:
                    sentences_with_punct.append(s)

            # 只要一句话超过了5个字，就拆分。否则分给下一句一起拆分
            sentence_buffer: str = ""

            for i, sentence in enumerate(sentences_with_punct):
                # check if sentence starts with parenthesis (action/mood)
                match = re.match(r"^(\（.*?\）|\(.*?\))", sentence)
                paren_content = None
                if match:
                    paren_content = match.group(1)
                    sentence = sentence[len(paren_content) :]  # remove from current sentence

                if paren_content:
                    # assign to previous sentence
                    if sentence_buffer.strip():
                        # append to current buffer
                        sentence_buffer += paren_content
                    elif split_responses:
                        # append to last existing response content
                        # No need to update sound_content as it strips parentheses anyway
                        split_responses[-1].content += paren_content
                    else:
                        # no previous sentence, keep it at start
                        sentence = paren_content + sentence

                sentence_buffer += sentence

                # Standard flush condition
                if len(sentence_buffer) >= 6 or i == len(sentences_with_punct) - 1:
                    if sentence_buffer.strip():
                        final_content = sentence_buffer.strip()
                        split_responses.append(
                            OneSentenceChat(
                                content=final_content,
                                expression=resp.expression,
                                tone=resp.tone,
                                sound_content=clean_sound_content(final_content),
                            )
                        )
                        sentence_buffer = ""
        return split_responses

    async def handle_history_request(self, user_id: str, count: int, end_index: int, db: Session) -> Dict[str, Any]:
        """处理历史记录请求

        Args:
            count: 请求的数量
            end_index: 结束索引（不包含），-1表示从最新开始

        Returns:
            (history_list, start_index)
        """

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


agent = None


def init_luotianyi_agent(
    config: Dict[str, Any],
    tts_module: TTSModule,
    redis_client: redis.Redis,
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
