"""禁用向量时以真实 SQLite 证明正本、身份与无索引关联。"""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.skill_support import invocation

from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.adapters.memory.writer import MemoryWriter
from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.knowledge.song_acceptance import SongKnowledgeStore
from src.agent.skills.memory_retrieval import MemoryQuery, MemoryRetrievalSkill, RetrievalScope
from src.agent.skills.memory_write import MemoryBasis, MemoryFact, MemoryScope, MemoryWriteSkill, MemoryWriteStatus
from src.domain.agent.maintenance import MaintenanceCandidate, MaintenanceMemoryType, MemoryWriteResult
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.memory_store import MemoryStore
from src.infrastructure.persistence.database.sql_database import Base, MemoryChunkRecord
from src.infrastructure.persistence.database.vector_store import VectorStoreFactory


@pytest.fixture
def memory_state(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    memory = MemoryStore({}, sessions, RedisBuffer())
    vectors = VectorStoreFactory.create_vector_store(
        "chroma", {"enabled": False, "vector_store_path": str(tmp_path / "uncreated-vectors")}
    )
    models = SimpleNamespace(register_llm_module=lambda *args, **kwargs: object())
    skill = MemoryWriteSkill(
        {"llm_module": {"llm": {"name": "unused"}}},
        llm_service=models,
        memory_store=memory,
        vector_store=vectors,
        characters=("luotianyi", "miku"),
    )
    yield SimpleNamespace(memory=memory, vectors=vectors, skill=skill, sessions=sessions, models=models)
    vectors.close()
    engine.dispose()


def memory_fact(content="测试编号412", source_id="message-1", scope=MemoryScope.USER):
    return MemoryFact(
        source="explicit_memory",
        source_id=source_id,
        occurred_at=datetime(2026, 11, 17, 2),
        content=content,
        scope=scope,
        basis=MemoryBasis.USER_REQUEST,
    )


async def test_disabled_fact_is_retrievable_from_sql_and_redelivery_is_idempotent(memory_state):
    state = memory_state
    first = await state.skill.commit_fact(invocation(), fact=memory_fact())
    repeated = await state.skill.commit_fact(invocation(), fact=memory_fact())

    assert first.status is MemoryWriteStatus.CREATED
    assert repeated.status is MemoryWriteStatus.DUPLICATE
    assert first.memory_ids == repeated.memory_ids
    record = state.memory.get_agent_memory_record(first.memory_ids[0])
    assert (record.owner_character_id, record.subject_user_id, record.content) == ("luotianyi", "u", "测试编号412")
    assert not state.memory.agent_memory_record_has_embeddings(record.id)
    with state.sessions() as session:
        assert session.query(MemoryChunkRecord).count() == 0
    assert first.retrieval_enabled is False


async def test_reenabling_real_vector_backend_does_not_backfill_sql_only_records(memory_state, tmp_path, monkeypatch):
    from src.infrastructure.models.llm.embedding import SiliconFlowEmbeddings

    state = memory_state
    result = await state.skill.commit_fact(invocation(), fact=memory_fact())

    async def forbidden_embed(*args, **kwargs):
        pytest.fail("reenabling must not automatically embed saved canonical records")

    monkeypatch.setattr(SiliconFlowEmbeddings, "aembed_documents", forbidden_embed)
    active = VectorStoreFactory.create_vector_store(
        "chroma",
        {
            "enabled": True,
            "vector_store_path": str(tmp_path / "real-vectors"),
            "embedding_model": {"api_key": "test-no-requests"},
        },
    )
    try:
        assert active.enabled is True
        assert active.collection.count() == 0
        assert state.memory.get_agent_memory_record(result.memory_ids[0]).content == "测试编号412"
        assert not state.memory.agent_memory_record_has_embeddings(result.memory_ids[0])
    finally:
        active.close()


async def test_disabled_fact_identity_scopes_user_and_character_and_rejects_changed_content(memory_state):
    state = memory_state
    calls = (("luotianyi", "u"), ("miku", "u"), ("luotianyi", "other"))
    identifiers = []
    for character, user in calls:
        result = await state.skill.commit_fact(invocation(character, user_id=user), fact=memory_fact())
        identifiers.extend(result.memory_ids)
        record = state.memory.get_agent_memory_record(result.memory_ids[0])
        assert (record.owner_character_id, record.subject_user_id) == (character, user)
    assert len(set(identifiers)) == 3
    with pytest.raises(ValueError, match="identity conflicts"):
        await state.skill.commit_fact(invocation(), fact=memory_fact("不能覆盖"))
    assert state.memory.get_agent_memory_record(identifiers[0]).content == "测试编号412"
    with state.sessions() as session:
        assert session.query(MemoryChunkRecord).count() == 0


async def test_disabled_character_fact_retains_private_owner_without_a_user(memory_state):
    from src.domain.memory_record import MemoryVisibility

    fact = MemoryFact(
        source="song_learned",
        source_id="job",
        occurred_at=datetime(2026, 11, 17),
        content="角色经历",
        scope=MemoryScope.CHARACTER,
        basis=MemoryBasis.CONFIRMED_FACT,
    )
    result = await memory_state.skill.commit_fact(invocation(user_id=None), fact=fact)
    record = memory_state.memory.get_agent_memory_record(result.memory_ids[0])
    assert record.owner_character_id == "luotianyi"
    assert record.subject_user_id is None
    assert record.visibility is MemoryVisibility.CHARACTER_PRIVATE
    assert not memory_state.memory.agent_memory_record_has_embeddings(record.id)


async def test_disabled_fact_does_not_convert_sql_failure_to_success(memory_state):
    memory_state.memory.sql_session_factory = lambda: (_ for _ in ()).throw(OSError("sql unavailable"))
    with pytest.raises(OSError, match="sql unavailable"):
        await memory_state.skill.commit_fact(invocation(), fact=memory_fact())


async def test_disabled_maintenance_saves_frozen_candidates_without_embedding(memory_state):
    state = memory_state
    writer = MemoryWriter({}, object())
    kwargs = dict(
        vector_store=state.vectors,
        memory_store=state.memory,
        user_id="u",
        owner_character_id="luotianyi",
        maintenance_id="batch-1",
        candidates=(MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "喜欢茶"),),
    )

    first = await writer.write_maintenance_candidates(**kwargs)
    repeated = await writer.write_maintenance_candidates(**kwargs)

    assert first is MemoryWriteResult.CANONICAL_ONLY
    assert repeated is first
    with state.sessions() as session:
        from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord

        rows = session.query(AgentMemoryRecord).all()
        assert len(rows) == 1
        assert rows[0].content == "喜欢茶"
        assert rows[0].owner_character_id == "luotianyi"
        assert rows[0].subject_user_id == "u"
        assert session.query(MemoryChunkRecord).count() == 0


@pytest.mark.parametrize("changed", [{"owner_character_id": "miku"}, {"user_id": "other"}])
async def test_disabled_maintenance_rejects_cross_identity_batch_collision(memory_state, changed):
    state = memory_state
    writer = MemoryWriter({}, object())
    kwargs = dict(
        vector_store=state.vectors,
        memory_store=state.memory,
        user_id="u",
        owner_character_id="luotianyi",
        maintenance_id="same-batch",
        candidates=(MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "原正本"),),
    )
    await writer.write_maintenance_candidates(**kwargs)

    with pytest.raises(ValueError, match="identity conflicts"):
        await writer.write_maintenance_candidates(**{**kwargs, **changed})
    with state.sessions() as session:
        from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord

        rows = session.query(AgentMemoryRecord).all()
        assert [(row.owner_character_id, row.subject_user_id, row.content) for row in rows] == [
            ("luotianyi", "u", "原正本")
        ]


def retrieval_for(state, tmp_path):
    config = {"llm_module": {"llm": {"name": "unused"}}}
    memory = AgentMemory(
        {"memory_writer": config, "user_profile": config},
        state.models,
        database_manager=SimpleNamespace(memory_store=state.memory),
        vector_store=state.vectors,
        owner_character_id="luotianyi",
    )
    singing = SingingSkill({"characters": {"luotianyi": {"resource_path": str(tmp_path / "songs")}}})
    knowledge = SongKnowledgeStore({"song_database": {"db_folder": str(tmp_path), "db_file": "songs.sqlite"}})
    return MemoryRetrievalSkill({}, memories={"luotianyi": memory}, singing=singing, knowledge=knowledge), memory


async def test_disabled_retrieval_is_empty_without_embedding_after_identity_validation(memory_state, tmp_path):
    retrieval, memory = retrieval_for(memory_state, tmp_path)

    # 适配器的两类长期召回共享禁用语义，调用方无需先读取能力开关。
    assert (await memory.search_memory_context_for_topic("user-1", ["测试编号412"])).hits == ()
    assert (await memory.citywalk_memory_on(datetime(2026, 11, 17).date())).hits == ()

    result = await retrieval.search(invocation(), query=MemoryQuery(("测试编号412",)))

    assert result.hits == ()
    with pytest.raises(RuntimeError, match="已认证用户"):
        await retrieval.search(invocation(user_id=None), query=MemoryQuery(("查询",)))
    with pytest.raises(KeyError):
        await retrieval.search(invocation("unknown"), query=MemoryQuery(("查询",)))
    assert (
        await retrieval.search(
            invocation(user_id=None),
            query=MemoryQuery(("/YesterdayCityWalk",), scopes=frozenset((RetrievalScope.CHARACTER,))),
        )
    ).hits == ()


async def test_disabled_mixed_retrieval_keeps_real_public_song_sql(memory_state, tmp_path):
    from src.infrastructure.persistence.song_knowledge import Song, get_song_session

    retrieval, _ = retrieval_for(memory_state, tmp_path)
    await retrieval.get_song(invocation(), song_id="纸飞机")
    with get_song_session() as session:
        session.add(
            Song(uuid="public-song", name="纸飞机", safe_name="纸飞机", introduction="旅行与春风", lyrics="飞吧")
        )
        session.commit()

    result = await retrieval.search(
        invocation(),
        query=MemoryQuery(
            ("旅行",),
            scopes=frozenset((RetrievalScope.USER, RetrievalScope.CHARACTER, RetrievalScope.PUBLIC_KNOWLEDGE)),
        ),
    )

    assert [(hit.source_record_id, hit.source) for hit in result.hits] == [("public-song", "song_knowledge")]


async def test_disabled_legacy_intentional_retries_keep_real_sql_without_links(memory_state):
    state = memory_state
    writer = MemoryWriter({}, object())

    first_id, created = await writer.commit_user_memory(state.vectors, state.memory, "u", "喜欢乌龙茶", "luotianyi")
    repeated_id, repeated = await writer.commit_user_memory(state.vectors, state.memory, "u", "喜欢乌龙茶", "luotianyi")

    assert created is True
    assert repeated is False
    assert first_id == repeated_id
    assert state.memory.get_agent_memory_record(first_id).content == "喜欢乌龙茶"
    assert not state.memory.agent_memory_record_has_embeddings(first_id)


@pytest.mark.parametrize("operation", ["write_user_memory", "write_event_memory"])
async def test_disabled_legacy_boolean_writes_are_real_sql_and_idempotent(memory_state, operation):
    state = memory_state
    writer = MemoryWriter({}, object())
    write = getattr(writer, operation)

    first = await write(state.vectors, state.memory, "u", "真实旧入口记忆", "luotianyi")
    repeated = await write(state.vectors, state.memory, "u", "真实旧入口记忆", "luotianyi")

    assert first is True
    assert repeated is False
    with state.sessions() as session:
        from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord

        rows = session.query(AgentMemoryRecord).all()
        assert len(rows) == 1
        assert rows[0].content == "真实旧入口记忆"
        assert rows[0].owner_character_id == "luotianyi"
        assert rows[0].subject_user_id == "u"
        assert session.query(MemoryChunkRecord).count() == 0


@pytest.mark.parametrize("operation", ["commit_user_memory", "write_user_memory", "write_event_memory"])
async def test_disabled_legacy_no_commit_does_not_claim_or_create_persistence(memory_state, operation):
    from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord, MemoryUpdateRecord

    state = memory_state
    write = getattr(MemoryWriter({}, object()), operation)
    result = await write(state.vectors, state.memory, "u", "未提交内容", "luotianyi", commit=False)

    assert result == (("", False) if operation == "commit_user_memory" else False)
    with state.sessions() as session:
        assert session.query(AgentMemoryRecord).count() == 0
        assert session.query(MemoryUpdateRecord).count() == 0
        assert session.query(MemoryChunkRecord).count() == 0

    persisted = await write(state.vectors, state.memory, "u", "未提交内容", "luotianyi")
    repeated = await write(state.vectors, state.memory, "u", "未提交内容", "luotianyi", commit=False)
    if operation == "commit_user_memory":
        assert persisted[1] is True
        assert repeated == (persisted[0], False)
    else:
        assert persisted is True
        assert repeated is False
    with state.sessions() as session:
        assert session.query(AgentMemoryRecord).count() == 1
        assert session.query(AgentMemoryRecord).one().content == "未提交内容"


@pytest.mark.parametrize("operation", ["commit_user_memory", "write_user_memory", "write_event_memory"])
async def test_disabled_legacy_no_commit_rejects_existing_identity_conflict(memory_state, operation):
    from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord

    state = memory_state
    write = getattr(MemoryWriter({}, object()), operation)
    await write(state.vectors, state.memory, "u", "原文", "luotianyi")
    with state.sessions() as session:
        row = session.query(AgentMemoryRecord).one()
        row.owner_character_id = "other-character"
        session.commit()
    with pytest.raises(ValueError, match="identity conflicts"):
        await write(state.vectors, state.memory, "u", "原文", "luotianyi", commit=False)
    with state.sessions() as session:
        assert session.query(AgentMemoryRecord).one().owner_character_id == "other-character"


@pytest.mark.parametrize("operation", ["commit_user_memory", "write_user_memory", "write_event_memory"])
async def test_disabled_legacy_sql_failure_never_returns_success(memory_state, operation):
    def broken_session():
        raise OSError("SQL failed")

    memory_state.memory.sql_session_factory = broken_session
    with pytest.raises(OSError, match="SQL failed"):
        await getattr(MemoryWriter({}, object()), operation)(
            memory_state.vectors, memory_state.memory, "u", "真实失败", "luotianyi"
        )


async def test_disabled_event_redelivery_reuses_frozen_candidates_and_rejects_changed_envelope(memory_state):
    from src.agent.skills.memory_write import MemoryEvent

    state = memory_state
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return '{"user_memory":["只提取一次"],"event_memory":[]}'

    models = SimpleNamespace(register_llm_module=lambda *args: SimpleNamespace(generate_response=generate))
    writer = MemoryWriteSkill(
        {"llm_module": {"llm": {"name": "test"}}},
        llm_service=models,
        memory_store=state.memory,
        vector_store=state.vectors,
        characters=("luotianyi",),
    )
    event = MemoryEvent("dynamic", "event-1", datetime(2026, 11, 17), "原事件", MemoryScope.USER)
    first = await writer.remember_event(invocation(), event=event)
    repeated = await writer.remember_event(invocation(), event=event)
    assert first.memory_ids == repeated.memory_ids
    assert len(calls) == 1
    with pytest.raises(ValueError, match="冻结正文冲突"):
        await writer.remember_event(invocation(), event=replace(event, body="不同事件"))
    assert state.memory.get_agent_memory_record(first.memory_ids[0]).content == "只提取一次"


@pytest.mark.parametrize("failure", [False, True, "cancel", "conflict"])
async def test_disabled_maintenance_real_context_commits_only_after_sql_success(memory_state, failure):
    from support.context_support import entry

    from src.agent.context import ContextFactory, ConversationMode
    from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill, MaintenanceRequest
    from src.domain.agent.maintenance import MaintenanceReason, MaintenanceStatus
    from src.infrastructure.persistence.database.services.conversation_service import ConversationService
    from src.infrastructure.persistence.database.services.user_store import UserStore
    from src.infrastructure.persistence.database.sql_database import AgentMemoryRecord, User

    state = memory_state
    with state.sessions() as session:
        session.add(User(uuid="u", username="user", password="unused", description="旧画像"))
        session.commit()
    cache = RedisBuffer()
    users = UserStore({}, state.sessions, cache)
    conversations = ConversationService(sql_session_factory=state.sessions, redis_buffer=cache, user_store=users)

    class Models:
        def register_llm_module(self, name, config):
            async def generate_response(**kwargs):
                if "extract" in name:
                    values = '["爱喝茶","喜欢春风"]' if failure else '["爱喝茶"]'
                    return '{"user_memory":' + values + ',"event_memory":[]}'
                if "profile" in name:
                    return "新画像"
                return "新摘要"

            return SimpleNamespace(generate_response=generate_response)

    models = Models()
    module = {"llm_module": {"llm": {"name": "test"}}}
    memory = AgentMemory(
        {"memory_writer": module, "user_profile": module},
        models,
        database_manager=SimpleNamespace(memory_store=state.memory),
        vector_store=state.vectors,
    )
    maintenance = CognitiveMaintenanceSkill(
        {"conversation_compaction": {**module, "raw_conversation_context_limit": 1, "not_zip_conversation_count": 1}},
        llm_service=models,
        memories={"luotianyi": memory},
    )
    context = await ContextFactory(character_id="luotianyi", database=conversations).create(
        "maintenance", user_id="u", mode=ConversationMode.CHAT
    )
    try:
        await context.conversation.append((entry(1), entry(2)))
        if failure:
            import asyncio

            from src.domain.agent import CancellationReason, CancellationToken

            token = CancellationToken()
            write_sql = state.memory.write_agent_memory_record_if_absent
            written = []

            def fail_sql(record):
                written.append(record.id)
                if len(written) == 1 and failure is True:
                    return write_sql(record)
                if failure == "cancel":
                    created = write_sql(record)
                    token.cancel(CancellationReason.NO_LONGER_NEEDED)
                    return created
                if failure == "conflict":
                    raise ValueError("canonical identity conflicts")
                raise OSError("canonical SQL unavailable")

            state.memory.write_agent_memory_record_if_absent = fail_sql
            error_type = {"cancel": asyncio.CancelledError, "conflict": ValueError}.get(failure, OSError)
            with pytest.raises(error_type):
                await maintenance.maintain(
                    invocation(cancellation=token),
                    request=MaintenanceRequest(reason=MaintenanceReason.INTERACTION_ENDING, context=context),
                )
            assert await context.conversation.read_maintenance_progress() is None
            assert context.conversation.read().summary.text == ""
            assert context.user.read().profile.description == "旧画像"
            return
        report = await maintenance.maintain(
            invocation(), request=MaintenanceRequest(reason=MaintenanceReason.INTERACTION_ENDING, context=context)
        )
        assert report.status is MaintenanceStatus.COMPLETED
        assert report.memory_skipped_count == 0
        assert report.compacted is True
        assert await context.conversation.read_maintenance_progress() == "2"
        assert context.conversation.read().summary.text == "新摘要"
        assert context.user.read().profile.description == "新画像"
        with state.sessions() as session:
            assert session.query(AgentMemoryRecord).count() == 2
            assert session.query(MemoryChunkRecord).count() == 0
    finally:
        await context.close()


@pytest.mark.parametrize("old_index", [False, True, "unknown"])
async def test_disabled_reset_reports_real_vector_failure_without_erasing_old_index(
    memory_state, tmp_path, monkeypatch, old_index
):
    from fastapi import HTTPException

    from src.application.user.user_reset import UserResetService
    from src.infrastructure.persistence.database.services.conversation_service import ConversationService
    from src.infrastructure.persistence.database.services.user_store import UserStore
    from src.infrastructure.persistence.database.sql_database import User
    from src.web.http.types import UserDataResetRequest
    from src.web.http.user_interface import UserInterface

    state = memory_state
    with state.sessions() as session:
        session.add(User(uuid="u", username="user", password="unused"))
        session.commit()
    result = await state.skill.commit_fact(invocation(), fact=memory_fact())
    path = state.vectors.persist_directory
    if old_index:
        path.mkdir()
        (path / "old-data").write_bytes(b"must remain")
    if old_index == "unknown":
        from pathlib import Path

        original_stat = Path.stat

        def denied(self, *args, **kwargs):
            if self == path:
                raise PermissionError("index inaccessible")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", denied)
    held = set()

    async def begin(user_id):
        held.add(user_id)
        return object()

    async def end(user_id, token):
        held.discard(user_id)

    cache = RedisBuffer()
    users = UserStore({}, state.sessions, cache)
    conversations = ConversationService(sql_session_factory=state.sessions, redis_buffer=cache, user_store=users)
    fence = SimpleNamespace(begin_user_data_reset=begin, end_user_data_reset=end)
    empty_rows = SimpleNamespace(delete_by_user=lambda user_id: 0)
    reset = UserResetService(
        interactions=fence,
        conversation_service=conversations,
        memory_store=state.memory,
        user_store=users,
        vector_store=state.vectors,
        redis_buffer=cache,
        media_store=SimpleNamespace(delete_owned_by=lambda **kwargs: SimpleNamespace(deleted_count=0, failures=())),
        call_sessions=empty_rows,
        call_maintenance_batches=empty_rows,
    )
    database = SimpleNamespace(
        credential_service=SimpleNamespace(check_message_token=lambda name, token: (True, "u")),
    )
    interface = UserInterface(database, SimpleNamespace(ensure_dependencies=lambda: None))
    request = UserDataResetRequest(username="user")
    runtime = SimpleNamespace(database_manager=database, user_reset_service=reset)
    if old_index:
        with pytest.raises(HTTPException) as error:
            await interface.reset_user_data(request, "token", runtime)
        assert error.value.status_code == 500
        steps = error.value.detail["steps"]
        vector_step = next(step for step in steps if step["name"] == "vectors")
        assert vector_step["success"] is False
        assert vector_step["error"] == "VectorDeletionUnavailable"
        assert (path / "old-data").read_bytes() == b"must remain"
    else:
        report = await interface.reset_user_data(request, "token", runtime)
        assert report["ok"] is True
    assert held == set()
    assert state.memory.get_agent_memory_record(result.memory_ids[0]) is None
