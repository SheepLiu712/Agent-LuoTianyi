"""按受信身份提取、冻结并提交长期记忆。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from uuid import NAMESPACE_URL, uuid5

from src.agent.skills.adapters.memory.writer import MemoryWriter
from src.agent.skills.contracts import SkillInvocation
from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.infrastructure.persistence.database.vector_store import Document
from src.infrastructure.persistence.memory_events import MemoryEventStore
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned


class MemoryScope(str, Enum):
    USER = "user"
    CHARACTER = "character"


class MemoryBasis(str, Enum):
    CONFIRMED_FACT = "confirmed_fact"
    USER_REQUEST = "user_request"


class MemoryWriteStatus(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class MemoryEvent:
    source: str
    source_id: str
    occurred_at: datetime
    body: str
    scope: MemoryScope
    background: str = ""


@dataclass(frozen=True)
class MemoryFact:
    source: str
    source_id: str
    occurred_at: datetime
    content: str
    scope: MemoryScope
    basis: MemoryBasis


@dataclass(frozen=True)
class MemoryWriteResult:
    status: MemoryWriteStatus
    memory_ids: tuple[str, ...]
    source_id: str


class MemoryWriteSkill:
    """模型只提取事件；事实直接提交，正本与索引失败均向上抛出。"""

    def __init__(self, config: dict, *, llm_service, memory_store, vector_store, characters) -> None:
        self._store = memory_store
        self._vectors = vector_store
        self._events = MemoryEventStore(memory_store.sql_session_factory)
        self._extractors = {
            key: MemoryWriter(
                config, llm_service.register_llm_module(f"skill.memory_write.extract.{key}", config["llm_module"])
            )
            for key in characters
        }

    async def remember_event(self, invocation: SkillInvocation, *, event: MemoryEvent) -> MemoryWriteResult:
        """先冻结候选，再逐条提交；重试使用同一候选序列，不重新调用提取模型。"""
        identity = self._identity(invocation, event.source, event.source_id, event.scope)
        envelope = json.dumps(
            {"body": event.body, "background": event.background, "occurred_at": event.occurred_at.isoformat()},
            ensure_ascii=False,
            sort_keys=True,
        )
        frozen = await asyncio.to_thread(self._events.load, identity, envelope)
        if frozen is None:
            try:
                candidates = await self._extractors[invocation.character_id].extract_maintenance_candidates(
                    history=event.background, current_dialogue=event.body
                )
            except Exception:
                get_logger(__name__).exception("事件记忆提取失败 source=%s source_id=%s", event.source, event.source_id)
                raise
            proposed = [(candidate.memory_type.value, candidate.content) for candidate in candidates]
            subject = invocation.require_user_id() if event.scope is MemoryScope.USER else None
            frozen = await complete_owned(asyncio.to_thread(self._events.freeze, identity, envelope, proposed, subject))
        candidates, timestamp = frozen
        event = replace(event, occurred_at=datetime.fromisoformat(timestamp))
        return await self._commit(invocation, event, identity, candidates)

    async def commit_fact(self, invocation: SkillInvocation, *, fact: MemoryFact) -> MemoryWriteResult:
        """已确认事实与明确用户要求均不经过模型提取。"""
        if not isinstance(fact.basis, MemoryBasis):
            raise TypeError("记忆提交必须声明依据")
        if fact.basis is MemoryBasis.USER_REQUEST and fact.scope is not MemoryScope.USER:
            raise ValueError("用户明确要求只能写入该用户的私有记忆")
        identity = self._identity(invocation, fact.source, fact.source_id, fact.scope)
        if not fact.content.strip():
            raise ValueError("已确认记忆正文不能为空")
        kind = MemoryType.USER_FACT.value if fact.scope is MemoryScope.USER else MemoryType.AGENT_LIFE.value
        return await self._commit(invocation, fact, identity, [(kind, fact.content.strip())])

    def _identity(self, invocation, source, source_id, scope) -> str:
        if invocation.character_id not in self._extractors:
            raise KeyError(invocation.character_id)
        if not source.strip() or not source_id.strip():
            raise ValueError("记忆来源类型和稳定来源标识不能为空")
        if not isinstance(scope, MemoryScope):
            raise TypeError("记忆作用域必须显式声明")
        subject = invocation.require_user_id() if scope is MemoryScope.USER else None
        return str(
            uuid5(NAMESPACE_URL, json.dumps(["memory-event", invocation.character_id, subject, source, source_id]))
        )

    async def _commit(self, invocation, value, identity, candidates) -> MemoryWriteResult:
        identifiers = []
        created = False
        for index, (kind, content) in enumerate(candidates):
            record_id = str(uuid5(NAMESPACE_URL, f"memory:{identity}:{index}"))
            vector_id = str(uuid5(NAMESPACE_URL, f"memory-vector:{identity}:{index}"))
            subject = invocation.require_user_id() if value.scope is MemoryScope.USER else None
            record = MemoryRecord(
                id=record_id,
                owner_character_id=invocation.character_id,
                subject_user_id=subject,
                memory_type=MemoryType(kind) if subject else MemoryType.AGENT_LIFE,
                visibility=MemoryVisibility.PRIVATE if subject else MemoryVisibility.CHARACTER_PRIVATE,
                source=value.source,
                content=content,
                happened_at=value.occurred_at,
                metadata={"source_id": value.source_id, "candidate_index": index, "memory_scope": value.scope.value},
            )
            try:
                new = await complete_owned(asyncio.to_thread(self._store.write_agent_memory_record_if_absent, record))
                document = Document(
                    content,
                    {
                        "user_id": subject or "",
                        "owner_character_id": invocation.character_id,
                        "memory_scope": value.scope.value,
                        "source_id": value.source_id,
                    },
                    id=vector_id,
                )
                ids = await complete_owned(asyncio.to_thread(self._vectors.upsert_documents, [document], [vector_id]))
                if ids != [vector_id]:
                    raise RuntimeError("记忆索引未确认预期向量标识")
                await complete_owned(
                    asyncio.to_thread(
                        self._store.link_agent_memory_embeddings,
                        record_id,
                        chunk_texts=[content],
                        embedding_ids=[vector_id],
                    )
                )
            except Exception:
                get_logger(__name__).exception("记忆提交未完成 source_id=%s candidate=%s", value.source_id, index)
                raise
            identifiers.append(record_id)
            created = created or new
        status = MemoryWriteStatus.CREATED if created else MemoryWriteStatus.DUPLICATE
        if not candidates:
            status = MemoryWriteStatus.NO_CANDIDATE
        return MemoryWriteResult(status, tuple(identifiers), value.source_id)
