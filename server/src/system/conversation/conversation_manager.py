import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import asdict
import uuid
from sqlalchemy.orm import Session
from redis import Redis

from src.utils.logger import get_logger
from src.utils.llm.llm_module import LLMModule
from src.utils.llm.llm_api_interface import LLMAPIFactory
from src.utils.llm.prompt_manager import PromptManager
from src.utils.enum_type import ContextType, ConversationSource
from src.domain import ConversationItem
from src.system.database import database_service
from src.domain.conversation_type import timestamp_to_elapsed_time, timestamp_to_date

class ConversationManager:
    """
    无状态对话管理器
    负责管理对话历史，通过调用 database_service 实现数据持久化和读取
    """
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager, db_manager: Optional[Any] = None) -> None:
        self.logger = get_logger(__name__)
        self.config = config

        llm_module_cfg = config.get("llm_module", {})
        llm_cfg = llm_module_cfg.get("llm", {})
        prompt_name = llm_module_cfg.get("prompt_name")
        if not prompt_name:
            raise ValueError("llm_module 配置中缺少 prompt_name")
        prompt_template = prompt_manager.get_template(prompt_name)
        if not prompt_template:
            raise ValueError(f"Prompt 模板未找到: {prompt_name}")
        llm_interface = LLMAPIFactory.create_interface(llm_cfg)

        self.llm = LLMModule(
            module_name="conversation_manager",
            module_config=llm_module_cfg,
            prompt_template=prompt_template,
            interface=llm_interface,
        )
        self.db = db_manager  # 可选的 DatabaseManager 引用，用于新式 API 调用

        # 配置参数
        self.raw_conversation_context_limit = self.config.get("raw_conversation_context_limit", 60)
        self.forget_conversation_days = self.config.get("forget_conversation_days", 10)
        self.not_zip_conversation_count = self.config.get("not_zip_conversation_count", 30)
        self.recent_limit = self.config.get("recent_history_limit", 50)

    async def add_conversation(self, db: Session | None, redis: Redis | None, user_id: str,
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
        
        if self.db is not None:
            uuid_list = await asyncio.to_thread(self.db.add_conversations, user_id, [item])
        else:
            uuid_list = await asyncio.to_thread(
                database_service.add_conversations, db, redis, user_id, [item]
            )
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
    
    async def add_conversation_list_to_db(self, db: Session | None, redis: Redis | None, user_id: str, conversation_list: List[ConversationItem], commit=True) -> List[str]:
        """
        将 ConversationItem 列表写入数据库，并检查是否需要更新上下文摘要，返回添加的对话的uuid列表

        """
        # 1. 写入数据库并更新 Redis Buffer
        if self.db is not None:
            uuid_list = await asyncio.to_thread(
                self.db.add_conversations, user_id, conversation_list, commit
            )
        else:
            uuid_list = await asyncio.to_thread(
                database_service.add_conversations, db, redis, user_id, conversation_list, commit=commit
            )
        return uuid_list

    async def get_total_conversation_count(self, db: Session | None, user_id: str) -> int:
        """
        获取用户的总对话数量
        """
        if self.db is not None:
            return await asyncio.to_thread(self.db.get_total_conversation_count, user_id)
        return await asyncio.to_thread(database_service.get_total_conversation_count, db, user_id)
    
    async def check_and_update_context(self, db: Session | None, redis: Redis | None, user_id: str, commit: bool = True):
        """
        检查是否需要更新上下文 (Context Summary)
        """
        # 获取当前未压缩的对话数量
        if self.db is not None:
            current_count = await asyncio.to_thread(self.db.get_context_count, user_id)
        else:
            current_count = await asyncio.to_thread(database_service.get_context_count, db, user_id)
        if current_count > self.raw_conversation_context_limit:
             # 在后台任务中更新摘要，使用新的 DB 会话
             asyncio.create_task(self._update_context(db, redis, user_id, commit=commit))

    async def is_conversation_too_long(self, db: Session | None, user_id: str) -> bool:
        if self.db is not None:
            current_count = await asyncio.to_thread(self.db.get_context_count, user_id)
        else:
            current_count = await asyncio.to_thread(database_service.get_context_count, db, user_id)
        if current_count > self.raw_conversation_context_limit:
            return True
        return False

    async def get_nearset_history(self, db: Session | None, redis: Redis | None, user_id: str, n: int) -> List[ConversationItem]:
        """
        获取最近的n条对话
        """
        total_count = await self.get_total_conversation_count(db, user_id)
        start = max(0, total_count - n)
        return await self.get_history(db, user_id, start, total_count)

    async def get_history(self, db: Session | None, user_id: str, start: int, end: int) -> List[ConversationItem]:
        """
        获取指定范围的历史对话
        """
        if self.db is not None:
            return await asyncio.to_thread(self.db.get_history_from_db, user_id, start, end)
        return await asyncio.to_thread(database_service.get_history_from_db, db, user_id, start, end)
    
    async def get_context(self, db: Session | None, redis: Redis | None, user_id: str, ret_type: str = "str", ts_type: str = "elapsed") -> str | Dict[str, Any]:
        """
        获取上下文用于LLM提示词
        """
        try:
            if self.db is not None:
                context_data = await asyncio.to_thread(self.db.get_context_from_buffer, user_id)
            else:
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
                if ts_type == "elapsed":
                    ts = timestamp_to_elapsed_time(ts)
                else:
                    ts = timestamp_to_date(ts)
                src = c.get("source", "")
                cnt = c.get("content", "")
                conv_list.append(f"[{ts}]{src}: {cnt}")

            if ret_type == "str":
                return "更早对话总结：" + summary + \
                    "\n 最近对话：\n" + "\n".join(conv_list)
            else:
                return {
                    "summary": summary,
                    "recent_conversation": conv_list
                }
        except Exception as e:
            self.logger.error(f"Error in get_context: {e}")
            return ""
        


    async def _update_context(self, db: Session | None, redis: Redis | None, user_id: str, context_data: Optional[Dict[str, Any]] = None, commit: bool = True):
        """
        后台任务：更新上下文摘要
        """
        self.logger.debug(f"Task: Updating context summary for user {user_id}...")
        
        try:
            # 1. 获取当前上下文内容
            if context_data is None:
                if self.db is not None:
                    context_data = await asyncio.to_thread(self.db.get_context_from_buffer, user_id)
                else:
                    context_data = await asyncio.to_thread(
                        database_service.get_context_from_buffer, db, redis, user_id
                    )
                conversations = context_data.get("conversations", [])
            
                context_data["recent_conversation"]= [f"[{c['timestamp']}]{c['source']}: {c['content']}" for c in conversations]
    

            if not context_data:
                return

            current_summary:str = context_data["summary"]
            recent_conversation: List[str] = context_data["recent_conversation"]
            recent_conversation_str = "\n".join(recent_conversation)
            
            
            # 2. 调用 LLM 生成新摘要
            new_summary = await self.llm.generate_response(
                forget_conversation_days=self.forget_conversation_days,
                current_date = datetime.now().strftime("%Y-%m-%d"),
                current_summary=current_summary,
                recent_conversation=recent_conversation_str
                )

            
            self.logger.debug(f"New summary generated")

            # 3. 更新数据库和 Redis
            new_count = self.not_zip_conversation_count
            if self.db is not None:
                await asyncio.to_thread(
                    self.db.update_context_summary,
                    user_id, new_summary.strip(), new_count, commit=commit,
                )
            else:
                await asyncio.to_thread(
                    database_service.update_context_summary,
                    db, redis, user_id, new_summary.strip(), new_count, commit=commit,
                )
            
        except Exception as e:
            self.logger.error(f"Error in _update_context: {e}")
        finally:
            pass


