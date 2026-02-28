import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import asdict
from sqlalchemy.orm import Session
from redis import Redis
import uuid

from ..utils.logger import get_logger
from ..llm.llm_module import LLMModule
from ..llm.prompt_manager import PromptManager
from ..utils.enum_type import ContextType, ConversationSource
from ..types import ConversationItem
from ..database import database_service
from ..database.sql_database import get_sql_session
from ..types.conversation_type import timestamp_to_elapsed_time

class ConversationManager:
    """
    无状态对话管理器
    负责管理对话历史，通过调用 database_service 实现数据持久化和读取
    """
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager) -> None:
        self.logger = get_logger(__name__)
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        
        # 配置参数
        self.raw_conversation_context_limit = self.config.get("raw_conversation_context_limit", 100)
        self.forget_conversation_days = self.config.get("forget_conversation_days", 10)
        self.not_zip_conversation_count = self.config.get("not_zip_conversation_count", 20)
        # Old config for compatibility
        self.recent_limit = self.config.get("recent_history_limit", 100)

    async def add_conversation(self, db: Session, redis: Redis, user_id: str, 
                             source: ConversationSource, content: str, type: ContextType = ContextType.TEXT, data: Any = None) -> str:
        """
        添加对话到数据库，并检查是否需要更新上下文摘要，返回添加的对话的uuid列表

        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item = ConversationItem(
            timestamp=timestamp,
            source=source.value,
            type=type.value,
            content=content,
            data=data,
            uuid=str(uuid.uuid4())
        )
        
        # 1. 写入数据库并更新 Redis Buffer
        # 使用 asyncio.to_thread 运行阻塞的数据库操作
        uuid_list = await asyncio.to_thread(
            database_service.add_conversations, db, redis, user_id, [item]
        )
        # 2. 检查是否需要更新上下文摘要
        await self.check_and_update_context(db, redis, user_id)
        return uuid_list[0] if uuid_list else "" # 总只有一条记录，所以取第一个返回  
    
    def add_conversation_wo_db(self, user_id: str, source: ConversationSource, content: str, type: ContextType = ContextType.TEXT, data: Any = None) -> ConversationItem:
        """
        直接创建 ConversationItem 对象，不写入数据库，在后处理时再写入数据库，防止占用过多数据库连接资源
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item = ConversationItem(
            timestamp=timestamp,
            source=source.value,
            type=type.value,
            content=content,
            data=data,
            uuid=str(uuid.uuid4())
        )
        return item
    
    async def add_conversation_list_to_db(self, db: Session, redis: Redis, user_id: str, conversation_list: List[ConversationItem], commit=True) -> List[str]:
        """
        将 ConversationItem 列表写入数据库，并检查是否需要更新上下文摘要，返回添加的对话的uuid列表

        """
        # 1. 写入数据库并更新 Redis Buffer
        uuid_list = await asyncio.to_thread(
            database_service.add_conversations, db, redis, user_id, conversation_list, commit=commit
        )
        await self.check_and_update_context(db, redis, user_id, commit=commit)
        return uuid_list

    async def get_total_conversation_count(self, db: Session, user_id: str) -> int:
        """
        获取用户的总对话数量
        """
        return await asyncio.to_thread(
            database_service.get_total_conversation_count, db, user_id
        )
    
    async def check_and_update_context(self, db: Session, redis: Redis, user_id: str, commit: bool = True):
        """
        检查是否需要更新上下文 (Context Summary)
        """
        # 获取当前未压缩的对话数量
        current_count = await asyncio.to_thread(database_service.get_context_count, db, user_id)
        if current_count > self.raw_conversation_context_limit:
             # 在后台任务中更新摘要，使用新的 DB 会话
             asyncio.create_task(self._update_context(db, redis, user_id, commit=commit))

    async def get_nearset_history(self, db: Session, redis: Redis, user_id: str, n: int) -> List[ConversationItem]:
        """
        获取最近的n条对话
        """
        total_count = await asyncio.to_thread(database_service.get_total_conversation_count, db, user_id)
        start = max(0, total_count - n)
        return await self.get_history(db, user_id, start, total_count)

    async def get_history(self, db: Session, user_id: str, start: int, end: int) -> List[ConversationItem]:
        """
        获取指定范围的历史对话
        """
        return await asyncio.to_thread(
            database_service.get_history_from_db, db, user_id, start, end
        )
    
    async def get_context(self, db: Session, redis: Redis, user_id: str) -> str:
        """
        获取上下文用于LLM提示词
        """
        try:
            context_data = await asyncio.to_thread(
                database_service.get_context_from_buffer, db, redis, user_id
            )
            
            if not context_data:
                return ""
                
            summary = context_data.get("summary", "")
            conversations = context_data.get("conversations", [])
            
            # 格式化上下文
            conv_list = []
            for c in conversations:
                ts = c.get("timestamp", "")
                ts = timestamp_to_elapsed_time(ts)
                src = c.get("source", "")
                cnt = c.get("content", "")
                conv_list.append(f"[{ts}]{src}: {cnt}")

            return "更早对话总结：" + summary + \
                "\n 最近对话：\n" + "\n".join(conv_list)
        except Exception as e:
            self.logger.error(f"Error in get_context: {e}")
            return ""

    async def _update_context(self, db: Session, redis: Redis, user_id: str, commit: bool = True):
        """
        后台任务：更新上下文摘要
        """
        self.logger.debug(f"Task: Updating context summary for user {user_id}...")
        
        try:
            # 1. 获取当前上下文内容
            context_data = await asyncio.to_thread(
                database_service.get_context_from_buffer, db, redis, user_id
            )
            
            if not context_data:
                return

            current_summary = context_data.get("summary", "")
            conversations = context_data.get("conversations", [])
            
            recent_conversation = "\n".join(
                [f"[{c['timestamp']}]{c['source']}: {c['content']}" for c in conversations]
            )
            
            # 2. 调用 LLM 生成新摘要
            new_summary = await self.llm.generate_response(
                forget_conversation_days=self.forget_conversation_days,
                current_summary=current_summary,
                recent_conversation=recent_conversation
                )

            
            self.logger.debug(f"New summary generated")

            # 3. 更新数据库和 Redis
            new_count = self.not_zip_conversation_count
            await asyncio.to_thread(
                database_service.update_context_summary,
                db, redis, user_id, new_summary.strip(), new_count, commit=commit
            )
            
        except Exception as e:
            self.logger.error(f"Error in _update_context: {e}")
        finally:
            pass
            # db.close()


