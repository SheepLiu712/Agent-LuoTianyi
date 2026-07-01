from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional

from src.agent.main_chat import OneResponseLine
from src.system.observability import get_observability_service
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.domain.chat import ExtractedTopic
    from src.system.system_runtime import SystemRuntime


@dataclass
class CompletedTurn:
    user_id: str
    character_id: str
    topic: "ExtractedTopic"
    reply_items: List[OneResponseLine]
    attention_plan: Any
    conversation_history: str


class ReflectionWorker:
    """Serial post-turn reflection worker for one user-character chat stream."""

    def __init__(
        self,
        config: dict,
        username: str,
        user_id: str,
        character_id: str = "luotianyi",
        reply_topic_callback: Optional[Callable[["ExtractedTopic"], Awaitable[None]]] = None,
    ) -> None:
        self.config = config
        self.username = username
        self.user_id = user_id
        self.character_id = character_id or "luotianyi"
        self.reply_topic_callback = reply_topic_callback
        self.system_runtime: "SystemRuntime | None" = None
        self.logger = get_logger(f"{username}ReflectionWorker")
        self.reflection_queue: asyncio.Queue[CompletedTurn] = asyncio.Queue()
        self.processor_task: asyncio.Task | None = None

    def set_system_runtime(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime

    def set_reply_topic_callback(
        self,
        callback: Callable[["ExtractedTopic"], Awaitable[None]],
    ) -> None:
        self.reply_topic_callback = callback

    def ensure_dependencies(self) -> None:
        """检查反思 worker 依赖已经初始化。"""
        required = {
            "system_runtime": self.system_runtime,
            "reply_topic_callback": self.reply_topic_callback,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ReflectionWorker dependencies are missing: {', '.join(missing)}")

    def start_processing(self) -> None:
        if self.processor_task is None or self.processor_task.done():
            self.processor_task = asyncio.create_task(self._reflection_processor())
            self.logger.info("Reflection worker processor task started")

    async def submit_completed_turn(self, turn: CompletedTurn) -> None:
        await self.reflection_queue.put(turn)

    async def _reflection_processor(self) -> None:
        while True:
            turn: CompletedTurn | None = None
            try:
                turn = await self.reflection_queue.get()
                await self._reflect_completed_turn(turn)
            except asyncio.CancelledError:
                self.logger.info("Reflection worker task cancelled")
                break
            except Exception as e:
                self.logger.exception(f"Reflection worker error: {e}")
                await asyncio.sleep(0.1)
            finally:
                if turn is not None:
                    self.reflection_queue.task_done()

    async def _reflect_completed_turn(self, turn: CompletedTurn) -> None:
        await self._process_date_detection(turn)
        await self._write_topic_memories(turn)
        await self._compress_context_and_update_profile(turn)

    async def _process_date_detection(self, turn: CompletedTurn) -> None:
        if self.system_runtime is None:
            return

        result = await self.system_runtime.agent_runtime.detect_dates_for_topic(
            character_id=turn.character_id,
            user_id=turn.user_id,
            topic=turn.topic,
            conversation_history=turn.conversation_history,
            reply_topic_callback=lambda t: self._safe_reply_topic(t),
        )

        if result is True:
            self.logger.info(f"Date auto-saved from topic {turn.topic.topic_id}")
        elif result is False:
            self.logger.debug(f"Date discarded from topic {turn.topic.topic_id}")
        else:
            self.logger.info(f"Date confirmation topic created from topic {turn.topic.topic_id}")

    def _safe_reply_topic(self, topic: "ExtractedTopic") -> None:
        if self.reply_topic_callback is None:
            self.logger.warning("No reply topic callback set, cannot enqueue reflection topic")
            return
        try:
            asyncio.create_task(self.reply_topic_callback(topic))
        except Exception as e:
            self.logger.warning(f"Failed to add reflection topic: {e}")

    async def _write_topic_memories(self, turn: CompletedTurn) -> None:
        if self.system_runtime is None:
            return
        if len(getattr(turn.topic, "source_messages", []) or []) == 0:
            self.logger.info("No source messages for topic, skip scheduling memory write")
            return

        current_dialogue = self._build_current_dialogue(turn.topic, turn.reply_items)
        memory_hits = getattr(turn.attention_plan, "memory_hits", []) or []

        try:
            start = time.perf_counter()
            write_result = await self.system_runtime.agent_runtime.write_topic_memories(
                character_id=turn.character_id,
                user_id=turn.user_id,
                current_dialogue=current_dialogue,
                related_memories=memory_hits,
                conversation_history=turn.conversation_history,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            self._record_memory_write_events(turn, current_dialogue, write_result or {}, duration_ms)
        except Exception as e:
            self.logger.warning(f"Topic memory write task failed: {e}")

    async def _compress_context_and_update_profile(self, turn: CompletedTurn) -> None:
        if self.system_runtime is None:
            return

        try:
            pre_compression_snapshot = await self.system_runtime.conversation_service.get_context_snapshot(
                turn.user_id,
                character_id=turn.character_id,
                ts_type="date",
            )
            compressed_snapshot = await self.system_runtime.conversation_service.compress_context_if_needed(
                turn.user_id,
                character_id=turn.character_id,
                snapshot=pre_compression_snapshot,
            )
            if compressed_snapshot is None:
                return
            current_profile = ""
            try:
                current_profile = self.system_runtime.database_manager.get_user_description(turn.user_id) or ""
            except Exception:
                current_profile = ""
            start = time.perf_counter()
            new_profile = await self.system_runtime.agent_runtime.update_user_profile_by_context(
                character_id=turn.character_id,
                user_id=turn.user_id,
                context=pre_compression_snapshot.as_prompt_payload(),
            )
            duration_ms = (time.perf_counter() - start) * 1000
            self._record_user_profile_update_event(
                turn,
                pre_compression_snapshot.as_prompt_payload(),
                current_profile,
                new_profile,
                duration_ms,
            )
        except Exception as e:
            self.logger.warning(f"Context compression/profile update task failed: {e}")

    @staticmethod
    def _build_current_dialogue(topic: "ExtractedTopic", reply_items: List[OneResponseLine]) -> str:
        lines: List[str] = []

        for msg in getattr(topic, "source_messages", []) or []:
            content = (getattr(msg, "content", "") or "").strip()
            if content:
                lines.append(f"user: {content}")

        for item in reply_items:
            lines.append(f"agent: {item.get_content()}")

        return "\n".join(lines)

    def _record_memory_write_events(
        self,
        turn: CompletedTurn,
        current_dialogue: str,
        write_result: dict[str, Any],
        duration_ms: float,
    ) -> None:
        observability = get_observability_service()
        if observability is None:
            return
        trace_id = getattr(turn.topic, "trace_id", None)
        source_context = self._build_write_source_context(turn.conversation_history, current_dialogue)
        payload = write_result.get("payload") or {}
        observability.record_memory_trace_event(
            trace_id=trace_id,
            user_id=turn.user_id,
            topic_id=turn.topic.topic_id,
            event_type="memory_write_extraction",
            item_type="memory_payload",
            content_text=self._short_json(payload),
            source_context=source_context,
            result=payload,
            duration_ms=duration_ms,
            annotation_required=False,
        )
        for item in write_result.get("items") or []:
            status = item.get("status") or ""
            observability.record_memory_trace_event(
                trace_id=trace_id,
                user_id=turn.user_id,
                topic_id=turn.topic.topic_id,
                event_type="memory_write",
                item_type=str(item.get("memory_type") or "memory"),
                content_text=str(item.get("content") or ""),
                source_context=source_context,
                result=item,
                duration_ms=duration_ms,
                annotation_required=status == "written",
            )

    def _record_user_profile_update_event(
        self,
        turn: CompletedTurn,
        context: dict[str, Any],
        current_profile: str,
        new_profile: str | None,
        duration_ms: float,
    ) -> None:
        observability = get_observability_service()
        if observability is None:
            return
        trace_id = getattr(turn.topic, "trace_id", None)
        observability.record_memory_trace_event(
            trace_id=trace_id,
            user_id=turn.user_id,
            topic_id=turn.topic.topic_id,
            event_type="user_profile_update",
            item_type="user_profile",
            content_text=new_profile or "",
            source_context=self._short_json(context),
            result={
                "old_profile": current_profile,
                "new_profile": new_profile or "",
                "status": "updated" if new_profile else "no_update",
            },
            duration_ms=duration_ms,
            annotation_required=bool(new_profile),
        )

    @staticmethod
    def _build_write_source_context(conversation_history: str, current_dialogue: str) -> str:
        parts = []
        if current_dialogue:
            parts.append("当前对话：\n" + current_dialogue)
        if conversation_history:
            parts.append("会话上下文：\n" + conversation_history)
        return "\n\n".join(parts)

    @staticmethod
    def _short_json(value: Any) -> str:
        try:
            import json

            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
