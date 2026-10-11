from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.application.user.user_reset import UserResetService
from src.domain.agent import MaintenanceCandidate, MaintenanceMemoryType
from src.domain.call import CallState
from src.infrastructure.persistence.call_maintenance import CallMaintenanceBatch, SqlCallMaintenanceBatchRepository
from src.infrastructure.persistence.call_sessions import CallSessionRecord, SqlCallSessionRepository
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.memory_store import MemoryStore
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import (
    AgentMemoryRecord,
    Base,
    Conversation,
    MemoryChunkRecord,
    MemoryEdgeRecord,
    User,
)


class _Fence:
    def __init__(self):
        self.blocked = set()
        self.active_writes = 1
        self.drained = asyncio.Event()

    async def begin_user_data_reset(self, user_id):
        self.blocked.add(user_id)
        return object()

    async def stop_user_interactions(self, user_id):
        assert user_id in self.blocked
        return 2

    async def wait_user_settlements(self, user_id):
        assert user_id in self.blocked
        await self.drained.wait()

    async def end_user_data_reset(self, user_id, token):
        self.blocked.discard(user_id)


class _Vectors:
    def __init__(self):
        self.owners = {"owner": {"v1"}, "other": {"v2"}}
        self.fail = False

    def delete_user_records_strict(self, user_id):
        if self.fail:
            raise OSError("vector unavailable")
        return len(self.owners.pop(user_id, set()))


class _Media:
    def delete_owned_by(self, *, owner_user_id):
        return SimpleNamespace(deleted_count=1, failures=())


def _fixture(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reset.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    redis = RedisBuffer()
    users = UserStore({}, sessions, redis)
    conversations = ConversationService(sql_session_factory=sessions, redis_buffer=redis, user_store=users)
    memories = MemoryStore({}, sessions, redis)
    calls = SqlCallSessionRepository(sessions)
    batches = SqlCallMaintenanceBatchRepository(sessions)
    now = datetime.now(timezone.utc)
    with sessions() as session:
        session.add_all(
            [
                User(uuid="owner", username="owner", password="hash", description="private profile"),
                User(uuid="other", username="other", password="hash", description="other profile"),
                Conversation(
                    uuid="owner-conv",
                    user_id="owner",
                    character_id="luotianyi",
                    source="user",
                    type="text",
                    content="private",
                ),
                Conversation(
                    uuid="other-conv",
                    user_id="other",
                    character_id="luotianyi",
                    source="user",
                    type="text",
                    content="other",
                ),
                AgentMemoryRecord(
                    id="owner-memory",
                    owner_character_id="luotianyi",
                    subject_user_id="owner",
                    memory_type="event",
                    visibility="private",
                    source="maintenance",
                    content="private memory",
                ),
                AgentMemoryRecord(
                    id="other-memory",
                    owner_character_id="luotianyi",
                    subject_user_id="other",
                    memory_type="event",
                    visibility="private",
                    source="maintenance",
                    content="other memory",
                ),
                MemoryChunkRecord(
                    id="owner-chunk", memory_record_id="owner-memory", chunk_text="private", embedding_id="v1"
                ),
                MemoryChunkRecord(
                    id="other-chunk", memory_record_id="other-memory", chunk_text="other", embedding_id="v2"
                ),
                MemoryEdgeRecord(from_memory_id="owner-memory", to_memory_id="other-memory", relation_type="related"),
            ]
        )
        session.commit()
    for user_id in ("owner", "other"):
        record = CallSessionRecord(
            call_id=uuid4(),
            client_request_id=str(uuid4()),
            user_id=user_id,
            character_id="luotianyi",
            state=CallState.PREPARING,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        calls.create_if_absent(record)
        batches.create_or_load(
            CallMaintenanceBatch(
                maintenance_id=str(uuid4()),
                call_id=record.call_id,
                user_id=user_id,
                character_id="luotianyi",
                previous_turn_seq=0,
                target_turn_seq=1,
                settlement_input_digest="a" * 64,
                candidates=(MaintenanceCandidate(MaintenanceMemoryType.INTERACTION_EVENT, "candidate"),),
                proposed_profile="profile",
                status="frozen",
            )
        )
    redis.setex("user_description:owner", 3600, "private profile")
    redis.setex("user_description:other", 3600, "other profile")
    return engine, sessions, redis, users, conversations, memories, calls, batches


def test_reset_fences_inflight_work_deletes_owner_graph_and_is_retryable(tmp_path):
    engine, sessions, redis, users, conversations, memories, calls, batches = _fixture(tmp_path)
    fence = _Fence()
    vectors = _Vectors()
    service = UserResetService(
        interactions=fence,
        conversation_service=conversations,
        memory_store=memories,
        user_store=users,
        vector_store=vectors,
        redis_buffer=redis,
        media_store=_Media(),
        call_sessions=calls,
        call_maintenance_batches=batches,
    )

    async def scenario():
        task = asyncio.create_task(service.reset("owner"))
        for _ in range(10):
            if "owner" in fence.blocked:
                break
            await asyncio.sleep(0)
        assert "owner" in fence.blocked
        with sessions() as session:
            assert session.query(Conversation).filter_by(user_id="owner").count() == 1
        fence.drained.set()
        return await task

    first = asyncio.run(scenario())
    assert first.success
    with sessions() as session:
        assert session.query(Conversation).filter_by(user_id="owner").count() == 0
        assert session.query(Conversation).filter_by(user_id="other").count() == 1
        assert session.query(AgentMemoryRecord).filter_by(subject_user_id="owner").count() == 0
        assert session.query(MemoryChunkRecord).filter_by(id="owner-chunk").count() == 0
        assert session.query(MemoryEdgeRecord).count() == 0
        assert session.query(AgentMemoryRecord).filter_by(subject_user_id="other").count() == 1
        assert session.query(User).filter_by(uuid="owner").one().description == ""
        assert session.query(User).filter_by(uuid="other").one().description == "other profile"
    assert calls.delete_by_user("owner") == 0
    assert len(batches.list_for_call(call_id=uuid4(), user_id="owner", character_id="luotianyi")) == 0
    assert redis.get("user_description:owner") is None
    assert redis.get("user_description:other") == "other profile"

    second = asyncio.run(service.reset("owner"))
    assert second.success
    engine.dispose()


def test_reset_reports_partial_failure_and_retry_converges(tmp_path):
    engine, _, redis, users, conversations, memories, calls, batches = _fixture(tmp_path)
    fence = _Fence()
    fence.drained.set()
    vectors = _Vectors()
    vectors.fail = True
    service = UserResetService(
        interactions=fence,
        conversation_service=conversations,
        memory_store=memories,
        user_store=users,
        vector_store=vectors,
        redis_buffer=redis,
        media_store=_Media(),
        call_sessions=calls,
        call_maintenance_batches=batches,
    )
    first = asyncio.run(service.reset("owner"))
    assert first.failed_steps == ("vectors",)
    vectors.fail = False
    second = asyncio.run(service.reset("owner"))
    assert second.success
    assert "owner" not in vectors.owners
    engine.dispose()
