"""把动态正文与评论写入用户长期记忆。"""

from __future__ import annotations

from typing import Any

from src.agent.skills.adapters.memory import AgentMemory
from src.system.observability import get_observability_service
from src.utils.logger import get_logger


class DynamicTopicMemorySkill:
    """动态互动的记忆写入技能。

    记忆写入与回复可用性完全解耦：调用方在回复之前独立提交，失败只记录；
    写入结果（是否真的产生了记忆）只在这里判定，世界侧不再解读记忆返回值。
    """

    def __init__(self, memory: AgentMemory | None) -> None:
        self._memory = memory
        self._logger = get_logger(__name__)

    async def write(
        self,
        *,
        user_id: str,
        current_dialogue: str,
        conversation_history: str,
        trace_id: str,
        source_context: str,
        topic_id: str,
    ) -> bool:
        """写一轮话题记忆；真正写入至少一条记忆时返回 True。"""
        for name, value in (("user_id", user_id), ("current_dialogue", current_dialogue)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        if self._memory is None:
            raise RuntimeError("角色记忆不可用，无法写入动态记忆")
        result: dict[str, Any] = await self._memory.write_topic_memories(
            user_id=user_id,
            history=conversation_history or "",
            current_dialogue=current_dialogue,
            related_memories=[],
            commit=True,
        )
        self._record_trace_events(
            trace_id=trace_id,
            user_id=user_id,
            topic_id=topic_id,
            source_context=source_context,
            result=result or {},
        )
        return any(str(item.get("status") or "") == "written" for item in (result or {}).get("items") or [])

    def _record_trace_events(
        self,
        *,
        trace_id: str,
        user_id: str,
        topic_id: str,
        source_context: str,
        result: dict[str, Any],
    ) -> None:
        """记录记忆抽取与写入轨迹；观测服务不可用时静默跳过。"""
        observability = get_observability_service()
        if observability is None:
            return
        payload = result.get("payload") or {}
        observability.record_memory_trace_event(
            trace_id=trace_id,
            user_id=user_id,
            topic_id=topic_id,
            event_type="memory_write_extraction",
            item_type="memory_payload",
            content_text=self._short_json(payload),
            source_context=source_context,
            result=payload,
            duration_ms=0.0,
            annotation_required=False,
            metadata={"source": "dynamic"},
        )
        for item in result.get("items") or []:
            status = item.get("status") or ""
            observability.record_memory_trace_event(
                trace_id=trace_id,
                user_id=user_id,
                topic_id=topic_id,
                event_type="memory_write",
                item_type=str(item.get("memory_type") or "memory"),
                content_text=str(item.get("content") or ""),
                source_context=source_context,
                result=item,
                duration_ms=0.0,
                annotation_required=status == "written",
                metadata={"source": "dynamic"},
            )

    @staticmethod
    def _short_json(value: Any) -> str:
        import json

        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - 轨迹文本是尽力而为，不可因序列化失败中断记忆写入
            return str(value)
