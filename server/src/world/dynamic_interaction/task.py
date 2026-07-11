from __future__ import annotations

import json
import time
from typing import Any, Dict, TYPE_CHECKING

from src.system.observability import get_observability_service
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.system.system_runtime import SystemRuntime
    from src.agent_runtime.character_runtime import CharacterRuntime


class DynamicInteractionTask(WorldTask):
    task_name = "dynamic_interaction"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        merged_config = dict(config or {})
        merged_config.setdefault(
            "clock_config",
            {"type": "interval", "params": {"interval_seconds": 1800, "run_immediately": False}},
        )
        super().__init__(self.task_name, merged_config)
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.database_manager: "DatabaseManager" | None = None
        self.agent_runtime: Any | None = None
        self.character_runtime: "CharacterRuntime" | None = None
        self.character_id = str(self.config.get("character_id", "luotianyi"))
        self.character_name = str(self.config.get("character_name", "洛天依"))

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        self.database_manager = getattr(system_runtime, "database_manager", None)
        self.agent_runtime = getattr(system_runtime, "agent_runtime", None)
        try:
            runtime = self.agent_runtime.get_character_runtime(self.character_id) if self.agent_runtime is not None else None
            if runtime is not None:
                self.character_runtime = runtime
                self.character_name = getattr(getattr(runtime, "profile", None), "display_name", self.character_name) or self.character_name
        except Exception:
            pass

    def ensure_dependencies(self) -> None:
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "database_manager": self.database_manager,
            "agent_runtime": self.agent_runtime,
            "character_runtime": self.character_runtime,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"DynamicInteractionTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        self.ensure_dependencies()
        if self.character_runtime is None or self.agent_runtime is None:
            return WorldTaskResult.skipped_result(self.task_name, "dynamic interaction dependencies are unavailable")
        replier_available = self.character_runtime.capability_manager.dynamics.replier.ensure_llm()
        if replier_available:
            reply_stats = await self._process_replies()
        else:
            reply_stats = {
                "reply_processed": 0,
                "reply_replied": 0,
                "reply_ignored": 0,
                "reply_failed": 0,
            }
        memory_stats = await self._process_memories()
        return WorldTaskResult.success(
            self.task_name,
            "dynamic interaction pass completed" if replier_available else "dynamic memory pass completed",
            **reply_stats,
            **memory_stats,
        )

    async def _process_replies(self) -> dict[str, Any]:
        processed = 0
        replied = 0
        ignored = 0
        failed = 0
        post_limit = int(self.config.get("reply_post_limit", 10))
        comment_limit = int(self.config.get("reply_comment_limit", 20))

        for item in self.database_manager.dynamic_store.list_pending_dynamic_posts_for_reply(limit=post_limit):
            processed += 1
            try:
                reply_text = await self.character_runtime.generate_dynamic_reply_for_post(item)
                ok, message, created = self.character_runtime.publish_dynamic_comment(
                    dynamic_id=item["id"],
                    owner_user_id=item["owner_user_id"],
                    content=reply_text,
                )
                if ok and created is not None:
                    self.database_manager.dynamic_store.update_dynamic_post_reply_state(item["id"], status="replied", error=None)
                    replied += 1
                else:
                    self.database_manager.dynamic_store.update_dynamic_post_reply_state(item["id"], status="failed", error=message)
                    failed += 1
            except Exception as exc:
                self.database_manager.dynamic_store.update_dynamic_post_reply_state(item["id"], status="failed", error=str(exc))
                failed += 1

        for item in self.database_manager.dynamic_store.list_pending_dynamic_comments_for_reply(limit=comment_limit):
            processed += 1
            try:
                decision = await self.character_runtime.generate_dynamic_reply_for_comment(item)
                if not decision["should_reply"]:
                    self.database_manager.dynamic_store.update_dynamic_comment_reply_state(item["id"], status="ignored", error=None)
                    ignored += 1
                    continue
                ok, message, created = self.character_runtime.publish_dynamic_comment(
                    dynamic_id=item["dynamic_id"],
                    owner_user_id=item["owner_user_id"],
                    content=decision["reply"],
                    parent_comment_id=item["id"],
                )
                if ok and created is not None:
                    self.database_manager.dynamic_store.update_dynamic_comment_reply_state(item["id"], status="replied", error=None)
                    replied += 1
                else:
                    self.database_manager.dynamic_store.update_dynamic_comment_reply_state(item["id"], status="failed", error=message)
                    failed += 1
            except Exception as exc:
                self.database_manager.dynamic_store.update_dynamic_comment_reply_state(item["id"], status="failed", error=str(exc))
                failed += 1

        return {
            "reply_processed": processed,
            "reply_replied": replied,
            "reply_ignored": ignored,
            "reply_failed": failed,
        }

    async def _process_memories(self) -> dict[str, Any]:
        processed = 0
        written = 0
        ignored = 0
        failed = 0
        post_limit = int(self.config.get("memory_post_limit", 10))
        comment_limit = int(self.config.get("memory_comment_limit", 20))

        for item in self.database_manager.dynamic_store.list_pending_dynamic_posts_for_memory(limit=post_limit):
            processed += 1
            try:
                write_result = await self.agent_runtime.write_topic_memories(
                    character_id=self.character_id,
                    user_id=item["owner_user_id"],
                    current_dialogue=f"user: {item['content']}",
                    related_memories=[],
                    conversation_history="",
                )
                status = self._memory_status_from_result(write_result)
                self.database_manager.dynamic_store.update_dynamic_post_memory_state(item["id"], status=status, error=None)
                self._record_memory_write_events(
                    trace_id=f"dynamic:{item['id']}",
                    user_id=item["owner_user_id"],
                    topic_id=item["id"],
                    source_context=f"动态正文：\n{item['content']}",
                    write_result=write_result or {},
                )
                if status == "written":
                    written += 1
                else:
                    ignored += 1
            except Exception as exc:
                self.database_manager.dynamic_store.update_dynamic_post_memory_state(item["id"], status="failed", error=str(exc))
                failed += 1

        for item in self.database_manager.dynamic_store.list_pending_dynamic_comments_for_memory(limit=comment_limit):
            processed += 1
            try:
                history = ""
                dynamic = item.get("dynamic") or {}
                if dynamic.get("content"):
                    history = f"动态正文：{dynamic['content']}"
                write_result = await self.agent_runtime.write_topic_memories(
                    character_id=self.character_id,
                    user_id=item["owner_user_id"],
                    current_dialogue=f"user: {item['content']}",
                    related_memories=[],
                    conversation_history=history,
                )
                status = self._memory_status_from_result(write_result)
                self.database_manager.dynamic_store.update_dynamic_comment_memory_state(item["id"], status=status, error=None)
                self._record_memory_write_events(
                    trace_id=f"dynamic_comment:{item['id']}",
                    user_id=item["owner_user_id"],
                    topic_id=item["id"],
                    source_context=f"{history}\n\n当前评论：\n{item['content']}".strip(),
                    write_result=write_result or {},
                )
                if status == "written":
                    written += 1
                else:
                    ignored += 1
            except Exception as exc:
                self.database_manager.dynamic_store.update_dynamic_comment_memory_state(item["id"], status="failed", error=str(exc))
                failed += 1

        return {
            "memory_processed": processed,
            "memory_written": written,
            "memory_ignored": ignored,
            "memory_failed": failed,
        }

    @staticmethod
    def _memory_status_from_result(write_result: dict[str, Any] | None) -> str:
        items = (write_result or {}).get("items") or []
        if any(str(item.get("status") or "") == "written" for item in items):
            return "written"
        return "ignored"

    def _record_memory_write_events(
        self,
        *,
        trace_id: str,
        user_id: str,
        topic_id: str,
        source_context: str,
        write_result: dict[str, Any],
    ) -> None:
        observability = get_observability_service()
        if observability is None:
            return
        payload = write_result.get("payload") or {}
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
        for item in write_result.get("items") or []:
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
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
