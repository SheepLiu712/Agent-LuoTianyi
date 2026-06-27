from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import uuid4

from src.agent.main_chat import ContextType as ResponseLineType
from src.agent.main_chat import OneResponseLine, OneSentenceChat, SongSegmentChat
from src.domain.chat import ChatInputEvent, ChatInputEventType
from src.domain.conversation_type import ConversationItem, timestamp_to_date, timestamp_to_elapsed_time
from src.utils.enum_type import ContextType, ConversationSource
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database.database_service import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.utils.llm.llm_module import LLMModule


@dataclass
class ConversationContextSnapshot:
    """A formatted, disposable context view owned by a ChatStream."""

    user_id: str
    character_id: str = "luotianyi"
    summary: str = ""
    conversations: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    recent_conversation: list[str] = field(default_factory=list)
    context_count: int = 0
    version: str | None = None

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "recent_conversation": self.recent_conversation,
        }


class ConversationService:
    """Stateless runtime service for conversation persistence and context."""

    def __init__(
        self,
        config: dict[str, Any],
        database: "DatabaseManager",
        llm_service: "LLMService" = None,
    ) -> None:
        self.config = config
        self.database = database
        self.llm_service = llm_service
        self.logger = get_logger("ConversationService")

        self.raw_conversation_context_limit = self.config.get("raw_conversation_context_limit", 60)
        self.forget_conversation_days = self.config.get("forget_conversation_days", 10)
        self.not_zip_conversation_count = self.config.get("not_zip_conversation_count", 30)
        self.context_stale_after_days = self.config.get("context_stale_after_days", 5)
        self.summary_llm = self._create_summary_llm()

    def wire_dependencies(
        self,
        *,
        database: "DatabaseManager",
        llm_service: "LLMService",
    ) -> None:
        """更新会话服务依赖，并按需注册摘要 LLM。"""
        self.database = database
        self.llm_service = llm_service
        if self.summary_llm is None:
            self.summary_llm = self._create_summary_llm()
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查会话服务依赖已经初始化。"""
        if self.database is None:
            raise RuntimeError("ConversationService dependency is missing: database")

    def _create_summary_llm(self) -> "LLMModule" | None:
        module_config = self.config.get("llm_module")
        if not module_config or self.llm_service is None:
            return None
        try:
            return self.llm_service.register_llm_module("conversation_context_summary", module_config)
        except Exception as e:
            self.logger.warning(f"Failed to register conversation summary LLM module: {e}")
            return None

    async def persist_user_event(
        self,
        user_id: Optional[str],
        event: ChatInputEvent,
        character_id: str = "luotianyi",
    ) -> Optional[str]:
        if user_id is None:
            self.logger.warning("user_id is None in persist_user_event, skipping")
            return None
        if event.event_type not in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE}:
            self.logger.warning(f"Unsupported event type {event.event_type} in persist_user_event, skipping")
            return None

        if event.payload and event.payload.get("is_proactive"):
            self.logger.info(f"Skipping DB save for proactive message: {event.text[:50]}...")
            return None

        payload = event.payload or {}
        content = event.text
        if event.event_type == ChatInputEventType.USER_IMAGE:
            conversation_type = ContextType.IMAGE.value
            data = {
                "image_client_path": payload.get("image_client_path"),
                "image_server_path": payload.get("image_server_path"),
                "mime_type": payload.get("mime_type"),
                "terms": payload.get("terms", []),
            }
        else:
            conversation_type = ContextType.TEXT.value
            data = {"terms": payload.get("terms", [])}

        item = ConversationItem(
            uuid=str(uuid4()),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            source=ConversationSource.USER.value,
            type=conversation_type,
            content=content,
            data=data,
        )
        uuid_list = await asyncio.to_thread(self.database.add_conversations, user_id, [item], True, character_id)
        return uuid_list[0] if uuid_list else None

    async def initialize_context_snapshot(
        self,
        user_id: str,
        *,
        character_id: str = "luotianyi",
        ts_type: str = "elapsed",
    ) -> ConversationContextSnapshot:
        '''
        在创建chat stream时调用
        如果上一次对话已经过期，则清空对话上下文状态
        然后，根据上下文状态拿具体的对话，组装并返回ConversationContextSnapshot

        :param user_id: 用户ID
        :param character_id: 角色ID
        :param ts_type: 时间戳类型，'elapsed'表示相对时间，'date'表示绝对时间
        :return: ConversationContextSnapshot对象
        '''
        await asyncio.to_thread(
            self.database.reset_conversation_context_if_stale,
            user_id,
            character_id,
            self.context_stale_after_days,
        )
        return await self.get_context_snapshot(user_id, character_id=character_id, ts_type=ts_type)

    async def persist_agent_replies(
        self,
        user_id: str,
        reply_items: List[OneResponseLine],
        character_id: str = "luotianyi",
    ) -> List[Optional[str]]:
        if not user_id:
            return []

        conversation_items: list[ConversationItem] = []
        persisted_indices: list[int] = []
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        for index, item in enumerate(reply_items):
            if isinstance(item, OneSentenceChat):
                text = item.get_content()
                if not text:
                    continue
                conversation_items.append(
                    ConversationItem(
                        uuid=str(uuid4()),
                        timestamp=now,
                        source=ConversationSource.AGENT.value,
                        type=ContextType.TEXT.value,
                        content=text,
                        data=None,
                    )
                )
                persisted_indices.append(index)
            elif isinstance(item, SongSegmentChat):
                song_name = item.song or None
                if not song_name:
                    continue
                lyrics = item.lyrics
                conversation_items.append(
                    ConversationItem(
                        uuid=str(uuid4()),
                        timestamp=now,
                        source=ConversationSource.AGENT.value,
                        type=ContextType.SING.value,
                        content=f"（唱了《{song_name}》）\n{lyrics}",
                        data={"song": song_name, "segment": item.segment},
                    )
                )
                persisted_indices.append(index)
            elif getattr(item, "type", None) not in {ResponseLineType.TEXT, ResponseLineType.SING}:
                self.logger.warning(f"Unsupported agent reply line type for persistence: {getattr(item, 'type', None)}")

        if not conversation_items:
            return [None] * len(reply_items)

        uuid_list = await asyncio.to_thread(self.database.add_conversations, user_id, conversation_items, True, character_id)
        result: list[Optional[str]] = [None] * len(reply_items)
        for index, uuid in zip(persisted_indices, uuid_list):
            result[index] = uuid
        return result

    async def get_context_snapshot(
        self,
        user_id: str,
        *,
        character_id: str = "luotianyi",
        ts_type: str = "elapsed",
    ) -> ConversationContextSnapshot:
        '''
        获取快照形式的对话上下文状态，包含summary、conversations、context_count等信息
        '''
        context_data = await asyncio.to_thread(self.database.get_conversation_context_state, user_id, character_id)
        return self._build_snapshot(user_id, character_id, context_data, ts_type=ts_type)

    async def get_context(
        self,
        user_id: str,
        character_id: str = "luotianyi",
        ret_type: str = "str",
        ts_type: str = "elapsed",
    ) -> str | dict[str, Any]:
        '''
        获取对话上下文的文本或结构化数据，返回值类型由ret_type参数决定。选择str时适合直接作为prompt使用，选择dict时适合进一步处理。

        :param user_id: 用户ID
        :param character_id: 角色ID
        :param ret_type: 返回类型，'str'表示返回文本，'dict'表示返回结构化数据
        :param ts_type: 时间戳类型，'elapsed'表示相对时间，'date'表示绝对时间
        :return: 对话上下文的文本或结构化数据，根据ret_type参数决定
        '''
        snapshot = await self.get_context_snapshot(user_id, character_id=character_id, ts_type=ts_type)
        if ret_type == "str":
            return snapshot.text
        return snapshot.as_prompt_payload()

    async def compress_context_if_needed(
        self,
        user_id: str,
        character_id: str = "luotianyi",
        snapshot: ConversationContextSnapshot | None = None,
    ) -> ConversationContextSnapshot | None:
        '''
        根据需要压缩对话上下文
        '''
        context_count = await asyncio.to_thread(self.database.get_context_count, user_id, character_id)
        if context_count <= self.raw_conversation_context_limit:
            return None

        snapshot = snapshot or await self.get_context_snapshot(user_id, character_id=character_id, ts_type="date")
        if self.summary_llm is None:
            self.logger.warning("Conversation context is too long, but summary LLM is unavailable")
            return None

        recent_conversation = snapshot.recent_conversation
        if not recent_conversation:
            recent_conversation = self._format_conversations(snapshot.conversations, ts_type="date")

        new_summary = await self.summary_llm.generate_response(
            forget_conversation_days=self.forget_conversation_days,
            current_date=datetime.now().strftime("%Y-%m-%d"),
            current_summary=snapshot.summary,
            recent_conversation="\n".join(recent_conversation),
        )

        updated = await asyncio.to_thread(
            self.database.compact_conversation_context,
            user_id,
            new_summary.strip(),
            self.not_zip_conversation_count,
            context_count,
            character_id,
        )
        if not updated:
            self.logger.info(f"Skipped context compaction for {user_id}; context state changed concurrently")
            return None
        return await self.get_context_snapshot(user_id, character_id=character_id, ts_type="date")


    def _build_snapshot(
        self,
        user_id: str,
        character_id: str,
        context_data: Any,
        *,
        ts_type: str,
    ) -> ConversationContextSnapshot:
        if not context_data:
            return ConversationContextSnapshot(user_id=user_id, character_id=character_id)

        summary = context_data.get("summary", "") or ""
        conversations = context_data.get("conversations", []) or []
        context_count = int(context_data.get("context_count", len(conversations)) or 0)
        version = context_data.get("version")
        recent_conversation = self._format_conversations(conversations, ts_type=ts_type)
        text = "更早对话总结：" + summary + "\n 最近对话：\n" + "\n".join(recent_conversation)
        return ConversationContextSnapshot(
            user_id=user_id,
            character_id=character_id,
            summary=summary,
            conversations=conversations,
            text=text,
            recent_conversation=recent_conversation,
            context_count=context_count,
            version=version,
        )

    @staticmethod
    def _format_conversations(conversations: list[dict[str, Any]], *, ts_type: str) -> list[str]:
        conv_list: list[str] = []
        for c in conversations:
            ts = c.get("timestamp", "")
            if ts_type == "elapsed":
                ts = timestamp_to_elapsed_time(ts)
            else:
                ts = timestamp_to_date(ts)
            src = c.get("source", "")
            cnt = c.get("content", "")
            conv_list.append(f"[{ts}]{src}: {cnt}")
        return conv_list
