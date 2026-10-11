"""Fast call routing, per-call recalled-memory pooling, and call reply generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from src.agent.call import CallMemory, CallMemoryPool
from src.agent.context.models import UserContextSnapshot
from src.agent.skills.contracts import ReplyDraft, SkillInvocation
from src.domain.call import AckStyle, CallRecallDecision, RecallMode
from src.utils.logger import get_logger


class _DecisionModel(Protocol):
    async def generate_response(self, **kwargs) -> str: ...


class _Memory(Protocol):
    async def search_memory_context_for_topic(self, user_id: str, queries: list[str]): ...


class _ReplyGenerator(Protocol):
    async def generate(
        self,
        *,
        reply_topic: str,
        user_context: UserContextSnapshot,
        conversation_history: str,
        fact_hits: list[str],
        memory_hits: list[str],
        sing_plan: tuple[str, str] | None,
    ) -> tuple[ReplyDraft, ...]: ...


class SilenceDecision(str, Enum):
    SPEAK = "speak"
    WAIT = "wait"
    END_CALL = "end_call"


class CallRecallDecisionSkill:
    """Use one fast decision and at most one vector recall per completed call turn."""

    def __init__(
        self,
        *,
        memories: Mapping[str, _Memory],
        model: _DecisionModel | None = None,
        capacity: int = 10,
    ) -> None:
        if not memories:
            raise ValueError("call recall requires character memories")
        self._memories = dict(memories)
        self._model = model
        self._capacity = capacity
        self._pools: dict[UUID, CallMemoryPool] = {}
        self._logger = get_logger(__name__)

    async def decide(
        self,
        invocation: SkillInvocation,
        *,
        call_id: UUID,
        audio_semantic: str,
        conversation_history: str,
        user_context: UserContextSnapshot,
    ) -> CallRecallDecision:
        """Return DIRECT/RECALL; any decision failure safely degrades to RECALL."""
        if self._model is None:
            return self._fallback(audio_semantic)
        try:
            response = await self._model.generate_response(
                audio_semantic=audio_semantic,
                conversation_history=conversation_history,
                user_profile=user_context.profile.description,
                memory_pool=self.pool_texts(call_id),
            )
            return self._parse_decision(response)
        except Exception as error:
            self._logger.warning("call recall decision failed; degrading to RECALL: %s", type(error).__name__)
            return self._fallback(audio_semantic)

    async def recall_once(
        self,
        invocation: SkillInvocation,
        *,
        call_id: UUID,
        queries: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Execute one memory API call and update the call-local approximate LRU pool."""
        if not queries:
            return self.pool_texts(call_id)
        try:
            context = await self._memories[invocation.character_id].search_memory_context_for_topic(
                invocation.require_user_id(), list(queries)
            )
        except Exception as error:
            self._logger.warning("call memory recall failed; continuing with existing pool: %s", type(error).__name__)
            return self.pool_texts(call_id)
        pool = self._pools.setdefault(call_id, CallMemoryPool(self._capacity))
        for hit in tuple(getattr(context, "hits", ()) or ()):
            text = str(getattr(hit, "rendered_text", "") or "").strip()
            if not text:
                continue
            identity = (
                str(getattr(hit, "memory_record_id", "") or "").strip()
                or str(getattr(hit, "vector_id", "") or "").strip()
                or hashlib.sha256(text.encode("utf-8")).hexdigest()
            )
            pool.remember(CallMemory(identity, text))
        return self.pool_texts(call_id)

    async def decide_silence(
        self,
        invocation: SkillInvocation,
        *,
        call_id: UUID,
        silence_ms: int,
        conversation_history: str,
    ) -> SilenceDecision:
        """Choose SPEAK/WAIT/END_CALL without fixed silence-count termination."""
        _ = invocation
        if self._model is None:
            return SilenceDecision.WAIT
        try:
            response = await self._model.generate_response(
                silence_ms=silence_ms,
                conversation_history=conversation_history,
                memory_pool=self.pool_texts(call_id),
            )
            payload = self._json_object(response)
            return SilenceDecision(str(payload["decision"]).strip().lower())
        except Exception as error:
            self._logger.warning("call silence decision failed; waiting: %s", type(error).__name__)
            return SilenceDecision.WAIT

    def pool_texts(self, call_id: UUID) -> tuple[str, ...]:
        pool = self._pools.get(call_id)
        return tuple(item.content for item in pool.snapshot()) if pool is not None else ()

    def release_call_memory(self, call_id: UUID) -> bool:
        """Release one call's in-memory recall pool after settlement or its deadline."""
        if not isinstance(call_id, UUID):
            raise TypeError("call_id must be UUID")
        pool = self._pools.pop(call_id, None)
        if pool is None:
            return False
        pool.clear()
        return True

    @classmethod
    def _parse_decision(cls, response: str) -> CallRecallDecision:
        payload = cls._json_object(response)
        mode = RecallMode(str(payload["mode"]).strip().lower())
        queries = payload.get("memory_queries", [])
        if not isinstance(queries, list) or any(not isinstance(item, str) for item in queries):
            raise ValueError("memory_queries must be a string list")
        ack_style = AckStyle(str(payload.get("ack_style", "none")).strip().lower())
        return CallRecallDecision(mode, tuple(queries), ack_style)

    @staticmethod
    def _json_object(response: str) -> dict[str, Any]:
        if not isinstance(response, str) or not response.strip():
            raise ValueError("empty call decision")
        text = response.strip()
        if text.startswith("```") and text.endswith("```"):
            text = "\n".join(text.splitlines()[1:-1]).strip()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("call decision must be a JSON object")
        return payload

    @staticmethod
    def _fallback(audio_semantic: str) -> CallRecallDecision:
        query = audio_semantic.strip() or "当前通话内容"
        return CallRecallDecision(RecallMode.RECALL, (query,), AckStyle.THINKING)


class CallReplySkill:
    """Generate call-only spoken drafts without singing or ordinary chat composition."""

    def __init__(self, generators: Mapping[str, _ReplyGenerator]) -> None:
        if not generators:
            raise ValueError("call reply requires character generators")
        self._generators = dict(generators)

    async def generate(
        self,
        invocation: SkillInvocation,
        *,
        reply_topic: str,
        user_context: UserContextSnapshot,
        conversation_history: str,
        memory_pool: tuple[str, ...],
    ) -> tuple[ReplyDraft, ...]:
        drafts = await self._generators[invocation.character_id].generate(
            reply_topic=reply_topic,
            user_context=user_context,
            conversation_history=conversation_history,
            fact_hits=[],
            memory_hits=list(memory_pool),
            sing_plan=None,
        )
        return tuple(
            draft for draft in drafts if draft.sing is None and draft.content.strip() and draft.sound_content.strip()
        )
