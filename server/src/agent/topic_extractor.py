from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple
from ..utils.llm.llm_module import LLMModule
from ..utils.llm.prompt_manager import PromptManager
from ..utils.logger import get_logger
import json
from uuid import uuid4

from ..pipeline.topic_planner import ExtractedTopic

if TYPE_CHECKING:
    from ..pipeline.modules.unread_store import UnreadMessageSnapshot, UnreadMessage


'''
我们考虑一个话题应该包括哪些内容。
1. topic_id: 每个话题一个唯一的ID，方便后续引用和跟踪。这个不用LLM生成。
2. topic_msgs: 这个话题是对哪些消息的总结和抽象。它的编号可以是在一个snapshot中的消息索引，这样可以从0编号，减小大模型处理的复杂度。比如说一个话题是对snapshot中第0、3、5条消息的总结，那么topic_msgs就是[0,3,5]。
3. topic_content: 这个话题的内容，通常是一个简短的文本总结。
LLM在这一步的另一个任务是给记忆搜索提供线索。那么至少有：
5. memory_attempts： 大模型尝试命中记忆，记忆包括：①用户的相关画像（爱好等）；②相关历史对话；
6. fact_constraints：如果话题涉及洛天依唱过的歌，需要从知识库中检索到相关的事实来约束大模型的输出，避免它编造一些洛天依没有唱过的歌。
7. sing_attempts：如果用户要求唱歌，需要给出用户要求的歌名。如果用户没有给出歌名，返回"random"，如果用户不要求唱歌，返回null
'''

class TopicExtractor:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.logger = get_logger(__name__)
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.variables: List[str] = self.llm.prompt_template.get_variables()


    async def extract_topics(self, 
                                unread_snapshot: Optional["UnreadMessageSnapshot"],
                                conversation_history: str = "", 
                                force_complete: bool = False,
                                ) -> Tuple[List["ExtractedTopic"], List["UnreadMessage"]]:
        if unread_snapshot is None or not unread_snapshot.messages:
            return [], []

        message_lines = []
        for idx, msg in enumerate(unread_snapshot.messages):
            message_lines.append(f"{[idx]}: {msg.content}")
        message_content = "\n".join(message_lines)

        terms = []
        for msg in unread_snapshot.messages:
            terms.extend(msg.terms or [])
        
        terms_str = ", ".join(terms) if terms else "None"


        response = await self._call_llm(
            conversation_history=conversation_history,
            message_content=message_content,
            terms=terms_str
        )
        if not response:
            return [], unread_snapshot.messages

        payload = self._parse_response_to_list(response)
        if payload is None:
            return [], unread_snapshot.messages

        topics: List[ExtractedTopic] = []
        remaining: List[UnreadMessage] = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            source_indexes = self._resolve_source_indexes(item.get("source_message_ids", []), unread_snapshot.messages)
            if not source_indexes:
                continue

            selected_messages = [unread_snapshot.messages[i] for i in source_indexes]
            topic_type = str(item.get("topic_types") or item.get("topic_type") or "chat").lower()

            if topic_type == "incomplete" and (not force_complete or len(topics) >= 1): # 如果已经有完整话题了，对于不完整话题就再等一等，放入剩余未读里，等待补全；如果没有完整话题了，不管怎样都放入话题里，强制完成这个不完整话题
                remaining.extend(selected_messages)
                continue

            topic_content = str(item.get("topic_content") or "").strip()
            if not topic_content:
                topic_content = "\n".join(msg.content for msg in selected_messages if msg.content)

            topics.append(
                ExtractedTopic(
                    topic_id=str(uuid4()),
                    source_messages=selected_messages,
                    topic_content=topic_content,
                    memory_attempts=self._normalize_str_list(item.get("memory_attempts")),
                    fact_constraints=self._normalize_str_list(item.get("fact_constraints")),
                    sing_attempts=self._normalize_str_list(item.get("sing_attempts")),
                    is_forced_from_incomplete=(topic_type == "incomplete" and force_complete),
                )
            )

        if not topics: # 没有成功提取出话题，全部保留为剩余未读，等待补全
            remaining = unread_snapshot.messages

        return topics, remaining

    async def _call_llm(self, **kwargs) -> Optional[str]:
        try:
            response = await self.llm.generate_response(
                **kwargs,
                use_json = True
            )
        except Exception as e:
            import traceback
            self.logger.error(f"Error during LLM response generation: {e} \n{traceback.format_exc()}")
            response = None
        return response

    def _parse_response_to_list(self, response: str) -> Optional[List[Dict[str, Any]]]:
        if not response:
            return None
        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse topic extractor response as JSON: {e}")
            self.logger.debug(f"Raw response: {response}")
            return None

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            topics = data.get("topics")
            if isinstance(topics, list):
                return topics
        return None

    def _resolve_source_indexes(self, source_ids: Any, messages: List["UnreadMessage"]) -> List[int]:
        if not isinstance(source_ids, list):
            return []

        indexes: List[int] = []
        for sid in source_ids:
            idx: Optional[int] = None

            if isinstance(sid, int):
                idx = sid
            elif isinstance(sid, str):
                if sid.isdigit():
                    idx = int(sid)
                else:
                    # 兼容少数模型返回消息ID字符串而非序号
                    for i, msg in enumerate(messages):
                        if msg.message_id == sid:
                            idx = i
                            break

            if idx is None:
                continue
            if idx < 0 or idx >= len(messages):
                continue
            if idx not in indexes:
                indexes.append(idx)

        return indexes

    def _normalize_str_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            normalized = []
            for item in value:
                if item is None:
                    continue
                s = str(item).strip()
                if s:
                    normalized.append(s)
            return normalized
        s = str(value).strip()
        return [s] if s else []
        