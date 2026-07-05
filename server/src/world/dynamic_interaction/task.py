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
    from src.capabilities.dynamic.dynamic import DynamicCapability


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
        self.dynamic_capability: "DynamicCapability" | None = None
        self.agent_runtime: Any | None = None
        self.reply_llm: Any | None = None
        self.character_id = str(self.config.get("character_id", "luotianyi"))
        self.character_name = str(self.config.get("character_name", "洛天依"))

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        self.database_manager = getattr(system_runtime, "database_manager", None)
        self.dynamic_capability = getattr(getattr(system_runtime, "capability_manager", None), "dynamics", None)
        self.agent_runtime = getattr(system_runtime, "agent_runtime", None)
        self.reply_llm = self._build_reply_llm()
        try:
            runtime = self.agent_runtime.get_character_runtime(self.character_id) if self.agent_runtime is not None else None
            if runtime is not None:
                self.character_name = getattr(getattr(runtime, "profile", None), "display_name", self.character_name) or self.character_name
        except Exception:
            pass

    def ensure_dependencies(self) -> None:
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "database_manager": self.database_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"DynamicInteractionTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        self.ensure_dependencies()
        if self.dynamic_capability is None or self.agent_runtime is None:
            return WorldTaskResult.skipped_result(self.task_name, "dynamic interaction dependencies are unavailable")
        if self.reply_llm is None:
            reply_stats = {
                "reply_processed": 0,
                "reply_replied": 0,
                "reply_ignored": 0,
                "reply_failed": 0,
            }
        else:
            reply_stats = await self._process_replies()
        memory_stats = await self._process_memories()
        return WorldTaskResult.success(
            self.task_name,
            "dynamic interaction pass completed" if self.reply_llm is not None else "dynamic memory pass completed",
            **reply_stats,
            **memory_stats,
        )

    def _build_reply_llm(self):
        llm_service = getattr(self.system_runtime, "llm_service", None)
        if llm_service is None:
            return None
        llm_cfg = self.config.get("llm_module")
        if not llm_cfg:
            llm_interfaces = getattr(llm_service, "llm_interfaces", None) or {}
            interface_names = list(llm_interfaces.keys())
            if not interface_names:
                return None
            llm_cfg = {
                "llm": {
                    "name": interface_names[0],
                    "enable_thinking": False,
                    "use_json": True,
                },
                "prompt_name": "dynamic_reply_prompt",
            }
        try:
            return llm_service.register_llm_module("dynamic_reply", llm_cfg)
        except Exception as exc:
            self.logger.warning(f"Dynamic reply module unavailable: {exc}")
            return None

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
                reply_text = await self._generate_reply_for_post(item)
                ok, message, created = self.dynamic_capability.publish_agent_comment(
                    dynamic_id=item["id"],
                    owner_user_id=item["owner_user_id"],
                    content=reply_text,
                    character_id=self.character_id,
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
                decision = await self._generate_reply_for_comment(item)
                if not decision["should_reply"]:
                    self.database_manager.dynamic_store.update_dynamic_comment_reply_state(item["id"], status="ignored", error=None)
                    ignored += 1
                    continue
                ok, message, created = self.dynamic_capability.publish_agent_comment(
                    dynamic_id=item["dynamic_id"],
                    owner_user_id=item["owner_user_id"],
                    content=decision["reply"],
                    character_id=self.character_id,
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

    async def _generate_reply_for_post(self, item: dict[str, Any]) -> str:
        decision = await self._ask_reply_llm(
            item_type="dynamic_post",
            must_reply=True,
            user_name=item.get("username") or "用户",
            user_description=item.get("user_description") or "",
            preference_context=self._build_preference_context(item.get("preferences") or {}),
            dynamic_content=item.get("content") or "",
            comment_content="",
        )
        reply = str(decision.get("reply") or "").strip()
        if reply:
            return reply
        return "我认真看完啦。谢谢你愿意和我分享这些，之后如果你还想继续说，我会认真听着。"

    async def _generate_reply_for_comment(self, item: dict[str, Any]) -> dict[str, Any]:
        dynamic = item.get("dynamic") or {}
        decision = await self._ask_reply_llm(
            item_type="dynamic_comment",
            must_reply=False,
            user_name=item.get("username") or "用户",
            user_description=item.get("user_description") or "",
            preference_context=self._build_preference_context(item.get("preferences") or {}),
            dynamic_content=dynamic.get("content") or "",
            comment_content=item.get("content") or "",
        )
        reply = str(decision.get("reply") or "").strip()
        should_reply = bool(decision.get("should_reply"))
        if should_reply and not reply:
            reply = "我看到你的补充啦，这件事我会记在心里。"
        return {"should_reply": should_reply and bool(reply), "reply": reply}

    async def _ask_reply_llm(
        self,
        *,
        item_type: str,
        must_reply: bool,
        user_name: str,
        user_description: str,
        preference_context: str,
        dynamic_content: str,
        comment_content: str,
    ) -> dict[str, Any]:
        response = await self.reply_llm.generate_response(
            character_name=self.character_name,
            user_name=user_name,
            user_description=user_description,
            preference_context=preference_context,
            item_type=item_type,
            must_reply="true" if must_reply else "false",
            dynamic_content=dynamic_content,
            comment_content=comment_content,
        )
        return self._parse_reply_json(response, must_reply=must_reply)

    @staticmethod
    def _parse_reply_json(response: str, *, must_reply: bool) -> dict[str, Any]:
        raw = (response or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("dynamic reply payload must be a JSON object")
        should_reply = bool(data.get("should_reply"))
        reply = str(data.get("reply") or "").strip()
        if must_reply:
            should_reply = True
        return {"should_reply": should_reply, "reply": reply}

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
    def _build_preference_context(preferences: dict[str, Any]) -> str:
        if not isinstance(preferences, dict) or not preferences:
            return ""
        parts = []
        if preferences.get("relationship"):
            parts.append(f"用户希望你是他的：{preferences['relationship']}")
        if preferences.get("speaking_style"):
            parts.append(f"用户希望你的表达风格偏向：{preferences['speaking_style']}")
        if preferences.get("personality_traits"):
            traits = preferences["personality_traits"]
            if isinstance(traits, list):
                parts.append(f"用户希望你的性格特点：{'、'.join(str(t) for t in traits if str(t).strip())}")
        if preferences.get("custom_context"):
            parts.append(f"用户补充的上下文：{str(preferences['custom_context']).replace('我', '用户')}")
        return "；".join(parts)

    @staticmethod
    def _short_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
