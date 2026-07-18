from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from src.chat_session.call_models import CallExitCode
from src.utils.logger import get_logger


class CallSettlementCoordinator:
    """电话结束后的摘要、记忆和画像处理器。

    每个 CallStream 持有一个实例，因此增量 memory_write 的批次边界天然按电话隔离；
    数据库状态更新仍以 call_id 为幂等键。
    """

    def __init__(self, *, config: dict[str, Any], llm_service, call_store, agent_runtime, character_id: str, observability=None):
        self.config = config or {}
        self.call_store = call_store
        self.agent_runtime = agent_runtime
        self.character_id = character_id
        self.observability = observability
        self.logger = get_logger("CallSettlementCoordinator")
        self.summary_llm = None
        module_config = (self.config.get("summary") or {}).get("llm_module")
        if module_config and llm_service is not None:
            try:
                self.summary_llm = llm_service.register_llm_module(
                    "call_summary", module_config
                )
            except Exception:
                self.logger.exception("register call summary llm failed")
        self._memory_lock = asyncio.Lock()
        self._memory_batch_index = 0
        self._memory_error: str | None = None

    @property
    def memory_error(self) -> str | None:
        return self._memory_error

    async def write_memory_incremental(
        self,
        *,
        call_id: str,
        user_id: str,
        turns: list[dict[str, Any]],
        final: bool = False,
    ) -> None:
        """每十行写一次；结束时不足十行也执行一次。"""
        async with self._memory_lock:
            target_count = len(turns) if final else (len(turns) // 10) * 10
            while self._memory_batch_index < target_count:
                end = min(self._memory_batch_index + 10, target_count)
                batch = turns[self._memory_batch_index:end]
                self._memory_batch_index = end
                if not batch:
                    continue
                dialogue = "\n".join(f"[{item['speaker']}] {item['text']}" for item in batch)
                try:
                    runtime = self.agent_runtime.get_character_runtime(self.character_id)
                    await runtime.mind.write_topic_memories(
                        user_id=user_id,
                        current_dialogue=dialogue,
                        related_memories=[],
                        conversation_history="",
                    )
                except Exception as exc:
                    self._memory_error = str(exc)[:500]
                    self.logger.exception("call memory_write failed: call_id=%s", call_id)

    async def process_after_end(
        self,
        *,
        call_id: str,
        user_id: str,
        exit_code: int,
        duration_seconds: int,
        turns: list[dict[str, Any]],
    ) -> None:
        """独立更新摘要、记忆和画像状态；任一项失败不阻塞其他项。"""
        self._active_call_id = call_id
        self._active_user_id = user_id
        state = await asyncio.to_thread(self.call_store.get_postprocess_state, call_id)
        if state and state.get("memory_status") != "success":
            await self.write_memory_incremental(call_id=call_id, user_id=user_id, turns=turns, final=True)
        memory_ok = self._memory_error is None
        if exit_code == int(CallExitCode.NORMAL) and not (state and state.get("memory_status") == "success"):
            try:
                runtime = self.agent_runtime.get_character_runtime(self.character_id)
                await runtime.mind.memory.write_event_memory(
                    user_id=user_id,
                    content=f"今天和用户进行了{duration_seconds}秒语音通话",
                    commit=True,
                )
            except Exception as exc:
                memory_ok = False
                self._memory_error = str(exc)[:500]
                self.logger.exception("call event memory failed: call_id=%s", call_id)
        await asyncio.to_thread(
            self.call_store.update_postprocess_status,
            call_id,
            "memory",
            "success" if memory_ok else "failed",
            self._memory_error,
        )
        self._record_event(
            "call.memory_write_completed" if memory_ok else "call.memory_write_failed",
            error=(None if memory_ok else {"message": self._memory_error or "memory_write_failed"}),
            metadata={"exit_code": exit_code, "turn_count": len(turns)},
        )

        summary = ""
        summary_error = None
        if not state or state.get("summary_status") != "success":
            try:
                summary = await self._generate_summary(turns, duration_seconds)
                await asyncio.to_thread(self.call_store.update_summary, call_id, summary, "success", None)
                self._record_event("call.summary_completed", metadata={"summary_length": len(summary)})
            except Exception as exc:
                summary_error = str(exc)[:500]
                self.logger.exception("call summary failed: call_id=%s", call_id)
                await asyncio.to_thread(self.call_store.update_summary, call_id, "", "failed", summary_error)
                self._record_event("call.summary_failed", error={"message": summary_error or "summary_failed"})
        else:
            summary = str(state.get("summary") or "")

        profile_ok = True
        profile_error = None
        if exit_code == int(CallExitCode.NORMAL) and not (state and state.get("profile_status") == "success"):
            try:
                runtime = self.agent_runtime.get_character_runtime(self.character_id)
                transcript = "\n".join(f"[{item['speaker']}] {item['text']}" for item in turns)
                await runtime.mind.update_user_profile_by_context(
                    user_id=user_id,
                    context={"type": "call", "summary": summary, "transcript": transcript},
                )
            except Exception as exc:
                profile_ok = False
                profile_error = str(exc)[:500]
                self.logger.exception("call profile update failed: call_id=%s", call_id)
        else:
            profile_ok = True
        profile_status = "skipped" if exit_code != int(CallExitCode.NORMAL) else ("success" if profile_ok else "failed")
        await asyncio.to_thread(
            self.call_store.update_postprocess_status,
            call_id,
            "profile",
            profile_status,
            profile_error,
        )
        if exit_code == int(CallExitCode.NORMAL):
            self._record_event(
                "call.profile_update_completed" if profile_ok else "call.profile_update_failed",
                error=(None if profile_ok else {"message": profile_error or "profile_update_failed"}),
            )
        self._record_event(
            "call.settlement_completed" if memory_ok and profile_ok else "call.settlement_failed",
            error=(None if memory_ok and profile_ok else {"message": "one or more postprocess steps failed"}),
        )

    async def _generate_summary(self, turns: list[dict[str, Any]], duration_seconds: int) -> str:
        transcript = "\n".join(f"[{item['speaker']}] {item['text']}" for item in turns)
        if not transcript:
            return "通话中没有形成完整对话。"
        if self.summary_llm is None:
            # 配置错误不应阻塞 call_history；保留可读的确定性降级摘要。
            return transcript[:100]
        kwargs = {
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "duration_seconds": duration_seconds,
            "transcript": transcript,
        }
        summary = (await self.summary_llm.generate_response(**kwargs)).strip()
        if len(summary) > 200:
            summary = (await self.summary_llm.generate_response(**kwargs)).strip()
        return summary if len(summary) <= 200 else summary[:100]

    def _record_event(
        self,
        event_name: str,
        *,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record_call_event(
                event_name=event_name,
                trace_id=f"call-{getattr(self, '_active_call_id', 'unknown')}",
                call_id=getattr(self, "_active_call_id", None),
                user_id=getattr(self, "_active_user_id", None),
                error=error,
                metadata={"character_id": self.character_id, **(metadata or {})},
            )
        except Exception:
            self.logger.debug("record call settlement event failed", exc_info=True)
