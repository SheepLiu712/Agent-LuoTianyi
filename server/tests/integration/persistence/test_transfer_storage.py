"""用隔离 SQL、媒体及向量故障证明本人迁移、幂等与补偿边界。"""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from support.audio_samples import recorded_aac_bytes

from src.domain.agent import MediaRef
from src.infrastructure.media import FilesystemMediaResolver, PermanentMediaStore, parse_m4a_audio
from src.infrastructure.media.media_resolver import MediaResolutionError
from src.infrastructure.persistence.database import vector_store as stores
from src.infrastructure.persistence.database.sql_database import (
    AgentMemoryRecord,
    Base,
    Conversation,
    ConversationContext,
    MemoryChunkRecord,
    MemoryEventBatch,
    User,
)
from src.infrastructure.persistence.transfer_projections import TransferProjections
from src.infrastructure.persistence.user_data_transfer import TransferConflict, UserDataRepository, dump_json

_NOW = "2026-11-19T12:00:00"


class Vectors:
    enabled = True

    def __init__(self):
        self.rows = {}
        self.prepared = []
        self.published = []
        self.embedding_failure = False
        self.publish_failure = False

    def list_user_documents(self, user_id):
        return deepcopy([row for row in self.rows.values() if row["metadata"]["user_id"] == user_id])

    async def prepare_embeddings(self, texts):
        self.prepared.extend(texts)
        if self.embedding_failure:
            raise OSError("embedding unavailable")
        return [[1.0, 0.5] for _ in texts]

    def delete_user_records_strict(self, user_id):
        identities = [row["id"] for row in self.list_user_documents(user_id)]
        for identity in identities:
            del self.rows[identity]
        return len(identities)

    def upsert_documents(self, documents, ids, *, embeddings):
        for document, identity, embedding in zip(documents, ids, embeddings):
            self.rows[identity] = {
                "id": identity,
                "content": document.get_content(),
                "metadata": deepcopy(document.get_metadata()),
                "embedding": list(embedding),
            }
        self.published.extend(ids)
        if self.publish_failure:
            self.publish_failure = False
            raise OSError("partial vector publish")
        return list(ids)


def _conversation(identity="chat", *, user="a", timestamp=_NOW, metadata=None, kind="text", character="luotianyi"):
    return {
        "uuid": identity,
        "user_id": user,
        "character_id": character,
        "timestamp": timestamp,
        "source": "user",
        "type": kind,
        "content": f"消息 {identity}",
        "meta_data": metadata or {},
    }


def _memory(identity="memory", *, user="a", **changes):
    row = {
        "id": identity,
        "subject_user_id": user,
        "owner_character_id": "luotianyi",
        "memory_type": "user_fact",
        "visibility": "private",
        "source": "explicit_memory",
        "content": "喜欢音乐",
        "summary": None,
        "importance": 0.7,
        "confidence": 0.9,
        "emotional_valence": None,
        "happened_at": None,
        "created_at": _NOW,
        "last_accessed_at": None,
        "meta_data": {"source_id": "fact"},
        "chunks": [{"chunk_text": "喜欢音乐", "chunk_type": "content"}],
    }
    row.update(changes)
    return row


def _context(*, progress=None, count=1, summary="原生摘要", character="luotianyi"):
    return {
        "character_id": character,
        "context_summary": summary,
        "context_memory_count": count,
        "maintenance_entry_id": progress,
        "updated_at": _NOW,
    }


def _payload(*, scope="all", user="a", conversations=None, memories=None, contexts=None):
    return {
        "format": "agentluo-data",
        "version": 1,
        "scope": scope,
        "source_user_id": user,
        "source_format": "native",
        "exported_at": _NOW,
        "conversations": conversations or [],
        "memories": memories or [],
        "contexts": contexts or [],
        "profile": {"description": "画像", "preferences": {"tone": "温柔"}} if scope != "chat" else {},
        "media": [],
        "memory_edges": [],
        "warnings": [],
    }


def _snapshot(repo, user="a", scope="all"):
    result = repo.snapshot(user, scope)
    result.pop("exported_at")
    return result


def _png():
    output = BytesIO()
    Image.new("RGB", (2, 2), color="pink").save(output, format="PNG")
    return output.getvalue()


def _media_payload(ids, *, data=None, kind="image", duration_ms=None, mode_scope="all"):
    data = _png() if data is None else data
    mime = "image/png" if kind == "image" else "audio/mp4"
    conversations = [
        _conversation(
            f"message-{index}",
            kind=kind,
            metadata={
                "media_id": identity,
                "mime_type": mime,
                **({"duration_ms": duration_ms} if kind == "audio" else {}),
            },
        )
        for index, identity in enumerate(ids)
    ]
    payload = _payload(scope=mode_scope, conversations=conversations)
    payload["media"] = [
        {
            "id": identity,
            "kind": kind,
            "mime_type": mime,
            "duration_ms": duration_ms,
            "path": f"media/{identity}/content.bin",
            "sha256": sha256(data).hexdigest(),
            "data": data,
        }
        for identity in ids
    ]
    return payload


@pytest.fixture
def state(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'transfer.sqlite'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions.begin() as db:
        db.add_all(
            [
                User(
                    uuid=user,
                    username=user,
                    password=f"password-{user}",
                    auth_token=f"token-{user}",
                    affection_score=17,
                )
                for user in ("a", "b")
            ]
        )
    config = {"root": str(tmp_path / "media"), "max_bytes": 6 * 1024 * 1024}
    media, vectors = PermanentMediaStore(config), Vectors()
    resolver = FilesystemMediaResolver(config)
    yield SimpleNamespace(
        repo=UserDataRepository(sessions),
        sessions=sessions,
        engine=engine,
        vectors=vectors,
        media=media,
        resolver=resolver,
        projection=TransferProjections(vectors, media, resolver),
        media_root=tmp_path / "media",
        tmp_path=tmp_path,
    )
    engine.dispose()


def test_snapshot_contains_only_owner_scope_chunks_and_internal_edges(state):
    payload = _payload(conversations=[_conversation()], memories=[_memory(), _memory("second")])
    payload["memory_edges"] = [
        {
            "id": "edge",
            "from_memory_id": "memory",
            "to_memory_id": "second",
            "relation_type": "supports",
            "weight": 0.6,
            "created_at": _NOW,
            "meta_data": {"evidence": "测试"},
        }
    ]
    state.repo.apply("a", payload, mode="merge", vector_ids={("memory", 0): "vector-private"})
    state.repo.apply(
        "b",
        _payload(
            user="b", conversations=[_conversation("other-chat", user="b")], memories=[_memory("other", user="b")]
        ),
        mode="merge",
    )
    with state.sessions.begin() as db:
        db.add(
            AgentMemoryRecord(
                id="public",
                owner_character_id="luotianyi",
                subject_user_id=None,
                memory_type="agent_life",
                visibility="public",
                source="test",
                content="公共记忆",
            )
        )
    exported = state.repo.snapshot("a")
    assert {row["uuid"] for row in exported["conversations"]} == {"chat"}
    assert {row["id"] for row in exported["memories"]} == {"memory", "second"}
    assert [row["id"] for row in exported["memory_edges"]] == ["edge"]
    assert "vector-private" not in dump_json(exported)
    assert "password-a" not in dump_json(exported) and "token-a" not in dump_json(exported)
    assert state.repo.snapshot("a", "chat")["memories"] == []
    assert state.repo.snapshot("a", "memory")["conversations"] == []
    assert state.repo.snapshot("a", "memory")["contexts"] == []


def test_duplicate_merge_ignores_transfer_origins_cache_paths_and_history_marker(state):
    row = _conversation(metadata={"semantic": "same", "image_client_path": "cache-before"})
    payload = _payload(conversations=[row], memories=[_memory()])
    assert state.repo.apply("a", payload, mode="merge")[0] == {"conversations": 1, "memories": 1}
    original = _snapshot(state.repo)
    row["meta_data"].update(
        {
            "_transfer_origin": {"user_id": "original", "id": "source"},
            "_transfer_media_origin": {"user_id": "original", "id": "media"},
            "_transfer_history_only": True,
            "image_server_path": "C:/untrusted",
            "image_client_path": "cache-after",
        }
    )
    payload["memories"][0]["meta_data"]["_transfer_origin"] = {"user_id": "original", "id": "source-memory"}
    assert state.repo.apply("a", payload, mode="merge")[1] == {"conversations": 1, "memories": 1}
    assert _snapshot(state.repo) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("content", "不同内容"),
        ("summary", "不同摘要"),
        ("importance", 0.1),
        ("confidence", 0.2),
        ("happened_at", "2026-11-18T12:00:00"),
        ("created_at", "2026-11-18T12:00:00"),
        ("meta_data", {"source_id": "changed"}),
        ("chunks", [{"chunk_text": "不同分块", "chunk_type": "content"}]),
    ],
)
def test_memory_identity_conflict_rolls_back_prior_chat_insert(state, field, value):
    state.repo.apply("a", _payload(memories=[_memory()]), mode="merge")
    before = _snapshot(state.repo)
    incoming = _payload(conversations=[_conversation("new")], memories=[_memory(**{field: value})])
    with pytest.raises(TransferConflict):
        state.repo.apply("a", incoming, mode="merge")
    assert _snapshot(state.repo) == before


@pytest.mark.parametrize("scope", ["chat", "memory"])
def test_replace_changes_only_requested_scope_and_preserves_other_user_and_credentials(state, scope):
    state.repo.apply("a", _payload(conversations=[_conversation()], memories=[_memory()]), mode="merge")
    state.repo.apply(
        "b",
        _payload(user="b", conversations=[_conversation("b-chat", user="b")], memories=[_memory("b-memory", user="b")]),
        mode="merge",
    )
    other = _snapshot(state.repo, "b")
    incoming = _payload(scope=scope, conversations=[_conversation("new-chat")], memories=[_memory("new-memory")])
    state.repo.apply("a", incoming, mode="replace")
    after = _snapshot(state.repo)
    assert {r["uuid"] for r in after["conversations"]} == ({"new-chat"} if scope == "chat" else {"chat"})
    assert {r["id"] for r in after["memories"]} == ({"new-memory"} if scope == "memory" else {"memory"})
    assert _snapshot(state.repo, "b") == other
    with state.sessions() as db:
        user = db.get(User, "a")
        assert (user.password, user.auth_token, user.affection_score) == ("password-a", "token-a", 17)


def test_native_merge_preserves_unmaintained_context_and_marks_new_rows_history_only(state):
    payload = _payload(
        scope="chat",
        conversations=[
            _conversation("maintained", timestamp="2026-11-19T10:00:00"),
            _conversation("pending", timestamp="2026-11-19T11:00:00"),
        ],
        contexts=[_context(progress="maintained", count=1)],
    )
    state.repo.apply("a", payload, mode="merge")
    before = _snapshot(state.repo)["contexts"]
    incoming = _payload(
        scope="chat",
        conversations=[_conversation("imported")],
        contexts=[_context(progress="imported", summary="不覆盖")],
    )
    state.repo.apply("a", incoming, mode="merge")
    assert _snapshot(state.repo)["contexts"] == before
    with state.sessions() as db:
        row = db.get(Conversation, "imported")
        assert '"_transfer_history_only":true' in row.meta_data
        context = db.query(ConversationContext).filter_by(user_id="a").one()
        assert (context.maintenance_entry_id, context.context_memory_count) == ("maintained", 1)
    assert state.repo.apply("a", incoming, mode="merge")[1]["conversations"] == 1
    assert _snapshot(state.repo)["contexts"] == before


@pytest.mark.parametrize("mode", ["merge", "replace"])
def test_native_new_context_restores_source_progress_and_ignores_external_history_in_count(state, mode):
    payload = _payload(
        scope="chat",
        conversations=[
            _conversation("mapped-maintained"),
            _conversation("mapped-pending", timestamp="2026-11-19T12:01:00"),
            _conversation("external", timestamp="2026-11-19T12:02:00", metadata={"_transfer_external": True}),
        ],
        contexts=[_context(progress="mapped-maintained", count=2)],
    )
    state.repo.apply("a", payload, mode=mode)
    context = _snapshot(state.repo)["contexts"][0]
    assert (context["maintenance_entry_id"], context["context_memory_count"], context["context_summary"]) == (
        "mapped-maintained",
        2,
        "原生摘要",
    )
    assert state.repo.snapshot("a")["conversations"][-1]["meta_data"]["_transfer_external"] is True


def test_external_merge_leaves_existing_context_and_watermark_unchanged(state):
    state.repo.apply("a", _payload(scope="chat", conversations=[_conversation()], contexts=[_context()]), mode="merge")
    before = _snapshot(state.repo)["contexts"]
    external = _payload(scope="chat", conversations=[_conversation("external", metadata={"_transfer_external": True})])
    state.repo.apply("a", external, mode="merge")
    assert _snapshot(state.repo)["contexts"] == before


def test_external_only_new_account_has_no_active_context_entries(state):
    payload = _payload(scope="chat", conversations=[_conversation(metadata={"_transfer_external": True})])
    state.repo.apply("a", payload, mode="merge")
    context = state.repo.snapshot("a")["contexts"][0]
    assert context["context_memory_count"] == 0 and context["maintenance_entry_id"] is None


def test_context_progress_cannot_reference_another_users_conversation(state):
    state.repo.apply(
        "b", _payload(user="b", scope="chat", conversations=[_conversation("b-chat", user="b")]), mode="merge"
    )
    with pytest.raises(TransferConflict, match="CONTEXT_PROGRESS_OUTSIDE_SCOPE"):
        state.repo.apply(
            "a",
            _payload(scope="chat", conversations=[_conversation()], contexts=[_context(progress="b-chat")]),
            mode="merge",
        )
    assert state.repo.snapshot("a")["conversations"] == []


def test_legacy_backfill_is_stable_owner_scoped_and_preserves_metadata(state):
    vectors = [
        {
            "id": "legacy",
            "content": "旧向量记忆",
            "metadata": {
                "user_id": "a",
                "memory_type": "user_memory",
                "timestamp": "2020-01-01",
                "source": "old-writer",
            },
        }
    ]
    assert state.repo.backfill_legacy("a", vectors) == 1
    first = state.repo.snapshot("a", "memory")["memories"]
    assert state.repo.backfill_legacy("a", vectors) == 0
    assert state.repo.snapshot("a", "memory")["memories"] == first
    assert first[0]["owner_character_id"] == "luotianyi"
    assert first[0]["meta_data"]["legacy_metadata"] == vectors[0]["metadata"]
    assert state.repo.snapshot("b", "memory")["memories"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"metadata": {"user_id": "b"}},
        {"content": " "},
        {"metadata": {"user_id": "a", "memory_scope": "user"}},
        {"metadata": {"user_id": "a", "owner_character_id": ""}},
    ],
)
def test_invalid_legacy_batch_rolls_back_all_canonical_inserts(state, change):
    valid = {"id": "first", "content": "旧记忆", "metadata": {"user_id": "a"}}
    invalid = {"id": "second", "content": "旧记忆二", "metadata": {"user_id": "a"}, **change}
    with pytest.raises(ValueError):
        state.repo.backfill_legacy("a", [valid, invalid])
    assert state.repo.snapshot("a", "memory")["memories"] == []


async def test_embedding_failure_precedes_sql_and_media_writes(state):
    payload = _media_payload([str(uuid4())])
    payload["memories"] = [_memory()]
    state.vectors.embedding_failure = True
    before = _snapshot(state.repo)
    with pytest.raises(OSError, match="embedding unavailable"):
        await state.projection.prepare("a", payload, "replace")
    assert _snapshot(state.repo) == before
    assert not list(state.media_root.iterdir()) and state.vectors.rows == {}


@pytest.mark.parametrize("mode", ["merge", "replace"])
async def test_partial_vector_publish_restores_old_embeddings_sql_and_only_new_media(state, mode):
    existing_id, new_id = str(uuid4()), str(uuid4())
    state.media.persist_image(
        media_ref=MediaRef(media_id=existing_id), owner_user_id="a", data=_png(), mime_type="image/png"
    )
    state.repo.apply("a", _payload(conversations=[_conversation("original")], memories=[_memory("old")]), mode="merge")
    state.vectors.rows = {
        "old-vector": {
            "id": "old-vector",
            "content": "旧向量",
            "metadata": {"user_id": "a"},
            "embedding": [0.125, 0.75],
        },
        "other-vector": {
            "id": "other-vector",
            "content": "他人向量",
            "metadata": {"user_id": "b"},
            "embedding": [0.5, 0.25],
        },
    }
    vectors_before, sql_before = deepcopy(state.vectors.rows), _snapshot(state.repo)
    payload = _media_payload([existing_id, new_id])
    payload["memories"] = [_memory("new")]
    plan = await state.projection.prepare("a", payload, mode)
    state.vectors.publish_failure = True
    with pytest.raises(OSError, match="partial vector publish"):
        state.repo.apply("a", payload, mode=mode, vector_ids=plan.vector_ids, publish=plan.publish)
    plan.rollback()
    plan.rollback()
    assert _snapshot(state.repo) == sql_before and state.vectors.rows == vectors_before
    assert (state.media_root / existing_id / "content.bin").read_bytes() == _png()
    assert not (state.media_root / new_id).exists()


async def test_sql_commit_failure_after_publish_is_recoverable_without_provider_call(state):
    payload = _media_payload([str(uuid4())])
    payload["memories"] = [_memory()]
    before = _snapshot(state.repo)
    plan = await state.projection.prepare("a", payload, "replace")

    def fail_commit(session):
        raise OSError("SQL commit unavailable")

    event.listen(state.sessions.class_, "before_commit", fail_commit)
    try:
        with pytest.raises(OSError, match="SQL commit unavailable"):
            state.repo.apply(
                "a",
                payload,
                mode="replace",
                vector_ids=plan.vector_ids,
                publish=plan.publish,
                receipt={"preview_id": "failed-sql", "backup_id": "recover-before-replace"},
            )
    finally:
        event.remove(state.sessions.class_, "before_commit", fail_commit)
    assert state.repo.receipt("a", "failed-sql") is None
    state.vectors.embedding_failure = True
    plan.rollback()
    assert _snapshot(state.repo) == before and state.vectors.rows == {}
    assert not list(state.media_root.iterdir())


async def test_identical_memory_merge_does_not_publish_unlinked_duplicate_vectors(state):
    payload = _payload(memories=[_memory()])
    for _ in range(2):
        plan = await state.projection.prepare("a", payload, "merge")
        state.repo.apply("a", payload, mode="merge", vector_ids=plan.vector_ids, publish=plan.publish)
        plan.finish()
    assert len(state.vectors.rows) == 1 and len(state.vectors.published) == 1
    with state.sessions() as db:
        assert db.query(AgentMemoryRecord).count() == 1 and db.query(MemoryChunkRecord).count() == 1
        assert db.query(MemoryChunkRecord).one().embedding_id in state.vectors.rows


async def test_chat_replace_never_touches_vectors(state):
    state.vectors.rows = {
        "old": {"id": "old", "content": "旧记忆", "metadata": {"user_id": "a"}, "embedding": [0.2, 0.4]}
    }
    before = deepcopy(state.vectors.rows)
    payload = _payload(scope="chat", conversations=[_conversation()])
    plan = await state.projection.prepare("a", payload, "replace")
    state.repo.apply("a", payload, mode="replace", vector_ids=plan.vector_ids, publish=plan.publish)
    plan.finish()
    assert state.vectors.rows == before


@pytest.mark.parametrize(
    "problem", ["checksum", "invalid-content", "server-path", "escaped-id", "too-large", "not-referenced"]
)
async def test_media_prevalidation_rejects_bad_input_without_writes(state, problem):
    identity = str(uuid4())
    payload = _media_payload([identity])
    media = payload["media"][0]
    if problem == "checksum":
        media["sha256"] = "0" * 64
    elif problem == "invalid-content":
        media.update(data=b"not an image", sha256=sha256(b"not an image").hexdigest())
    elif problem == "server-path":
        media["path"] = "C:/server/private.bin"
    elif problem == "escaped-id":
        media["id"] = "../private"
        payload["conversations"][0]["meta_data"]["media_id"] = "../private"
    elif problem == "too-large":
        state.media.max_bytes = len(_png()) - 1
    else:
        payload["conversations"] = []
    with pytest.raises((ValueError, MediaResolutionError)):
        await state.projection.prepare("a", payload, "merge")
    assert not list(state.media_root.iterdir()) and state.vectors.rows == {}


async def test_media_publication_failure_removes_first_new_file_and_sql_rows(state, monkeypatch):
    identities = [str(uuid4()), str(uuid4())]
    payload = _media_payload(identities)
    plan = await state.projection.prepare("a", payload, "merge")
    original = state.media.publish_transfer
    calls = []

    def publish(item):
        calls.append(item)
        if len(calls) == 2:
            raise OSError("disk full")
        return original(item)

    monkeypatch.setattr(state.media, "publish_transfer", publish)
    with pytest.raises(OSError, match="disk full"):
        state.repo.apply("a", payload, mode="merge", publish=plan.publish)
    plan.rollback()
    assert not list(state.media_root.iterdir()) and state.repo.snapshot("a")["conversations"] == []


async def test_actual_image_and_audio_round_trip_rebinds_owner_and_preserves_bytes(state):
    audio = recorded_aac_bytes()
    duration = parse_m4a_audio(audio).duration_ms
    for kind, content in (("image", _png()), ("audio", audio)):
        source_id, target_id = str(uuid4()), str(uuid4())
        source_ref = MediaRef(media_id=source_id)
        prepared = state.media.prepare_transfer(
            media_ref=source_ref,
            owner_user_id="a",
            data=content,
            kind=kind,
            mime_type="image/png" if kind == "image" else "audio/mp4",
            duration_ms=duration if kind == "audio" else None,
        )
        state.media.publish_transfer(prepared)
        payload = _media_payload(
            [source_id], data=content, kind=kind, duration_ms=duration if kind == "audio" else None
        )
        files = state.projection.export_media("a", payload)
        descriptor = payload["media"][0]
        assert files[descriptor["path"]] == content and "data" not in descriptor
        # 应用层负责身份映射；archive path 继续作为原包键，不成为本地路径。
        payload["conversations"][0]["meta_data"]["media_id"] = target_id
        descriptor.update(id=target_id, data=files[descriptor["path"]])
        plan = await state.projection.prepare("b", payload, "merge")
        plan.publish()
        plan.finish()
        actual = state.resolver.resolve(MediaRef(media_id=target_id), owner_user_id="b", expected_kind=kind)
        assert actual.data == content
        with pytest.raises(MediaResolutionError):
            state.resolver.resolve(MediaRef(media_id=target_id), owner_user_id="a", expected_kind=kind)


def test_missing_media_exports_explicit_descriptor_warning_without_reading_legacy_path(state):
    identity = str(uuid4())
    payload = _media_payload([identity])
    payload["conversations"][0]["meta_data"]["image_server_path"] = "C:/must-not-open"
    assert state.projection.export_media("a", payload) == {}
    assert payload["media"][0]["path"] is None and payload["media"][0]["sha256"] is None
    assert payload["warnings"]


def test_export_cannot_read_other_owners_media(state):
    identity = str(uuid4())
    state.media.persist_image(
        media_ref=MediaRef(media_id=identity), owner_user_id="b", data=_png(), mime_type="image/png"
    )
    with pytest.raises(MediaResolutionError):
        state.projection.export_media("a", _media_payload([identity]))


async def test_disabled_vectors_with_existing_files_refuse_incomplete_snapshot_and_import(state):
    directory = state.tmp_path / "old-vectors"
    directory.mkdir()
    (directory / "index-marker").write_bytes(b"synthetic-index")
    disabled = stores.DisabledVectorStore({"vector_store_path": str(directory)})
    with pytest.raises(stores.VectorDeletionUnavailable):
        disabled.list_user_documents("a")
    projection = TransferProjections(disabled, state.media, state.resolver)
    with pytest.raises(stores.VectorDeletionUnavailable):
        await projection.prepare("a", _payload(memories=[_memory()]), "replace")
    assert (directory / "index-marker").read_bytes() == b"synthetic-index"


async def test_disabled_empty_vectors_restore_canonical_and_warn(state):
    disabled = stores.DisabledVectorStore({"vector_store_path": str(state.tmp_path / "absent-vectors")})
    payload = _payload(memories=[_memory()])
    projection = TransferProjections(disabled, state.media, state.resolver)
    plan = await projection.prepare("a", payload, "merge")
    assert plan.vector_ids == {} and payload["warnings"]
    state.repo.apply("a", payload, mode="merge", vector_ids=plan.vector_ids, publish=plan.publish)
    plan.finish()
    with state.sessions() as db:
        assert db.query(AgentMemoryRecord).count() == 1
        assert db.query(MemoryChunkRecord).one().embedding_id is None


@pytest.mark.parametrize(
    "incoming,current,expected",
    [
        (None, "2026-11-19T13:00:00", "2026-11-19T13:00:00"),
        ("2026-11-19T14:00:00", "2026-11-19T13:00:00", "2026-11-19T14:00:00"),
    ],
)
def test_duplicate_memory_preserves_later_mutable_access_time(state, incoming, current, expected):
    state.repo.apply("a", _payload(memories=[_memory()]), mode="merge")
    with state.sessions.begin() as db:
        db.get(AgentMemoryRecord, "memory").last_accessed_at = datetime.fromisoformat(current)
    result = state.repo.apply("a", _payload(memories=[_memory(last_accessed_at=incoming)]), mode="merge")
    assert result[1]["memories"] == 1
    assert state.repo.snapshot("a", "memory")["memories"][0]["last_accessed_at"] == expected


def test_sql_only_canonical_without_chunks_rejects_changed_chunk_text(state):
    state.repo.apply("a", _payload(memories=[_memory()]), mode="merge")
    with state.sessions.begin() as db:
        db.query(MemoryChunkRecord).delete()
    changed = _memory(chunks=[{"chunk_text": "不同分块", "chunk_type": "content"}])
    with pytest.raises(TransferConflict, match="MEMORY_CHUNK_CONFLICT"):
        state.repo.apply("a", _payload(memories=[changed]), mode="merge")


def test_linked_canonical_uses_sql_authority_instead_of_reparsing_legacy_timestamp(state):
    state.repo.apply("a", _payload(memories=[_memory()]), mode="merge", vector_ids={("memory", 0): "linked"})
    before = _snapshot(state.repo)
    assert (
        state.repo.backfill_legacy(
            "a",
            [
                {
                    "id": "linked",
                    "content": "喜欢音乐",
                    "metadata": {"user_id": "a", "memory_scope": "user", "timestamp": "not-legacy-time"},
                }
            ],
        )
        == 0
    )
    assert _snapshot(state.repo) == before
    with pytest.raises(TransferConflict, match="LEGACY_MEMORY_LINK_CONFLICT"):
        state.repo.backfill_legacy(
            "a",
            [
                {
                    "id": "linked",
                    "content": "喜欢音乐",
                    "metadata": {"user_id": "a", "owner_character_id": "miku"},
                }
            ],
        )


async def test_total_media_budget_is_enforced_before_publication(state, monkeypatch):
    from src.infrastructure.persistence import transfer_projections

    payload = _media_payload([str(uuid4()), str(uuid4())])
    monkeypatch.setattr(transfer_projections, "_MAX_EXPANDED_BYTES", len(_png()))
    with pytest.raises(ValueError, match="TRANSFER_MEDIA_TOTAL_TOO_LARGE"):
        await state.projection.prepare("a", payload, "merge")
    assert not list(state.media_root.iterdir())


def test_corrupt_stored_checksum_becomes_missing_media_warning_not_exported_bytes(state):
    identity = str(uuid4())
    state.media.persist_image(
        media_ref=MediaRef(media_id=identity), owner_user_id="a", data=_png(), mime_type="image/png"
    )
    metadata_file = state.media_root / identity / "metadata.json"
    metadata_file.write_text(
        dump_json(
            {
                "media_kind": "image",
                "mime_type": "image/png",
                "owner_user_id": "a",
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    payload = _media_payload([identity])
    assert state.projection.export_media("a", payload) == {}
    assert payload["warnings"] and payload["media"][0]["path"] is None


@pytest.mark.parametrize("requested", [False, True])
@pytest.mark.parametrize("mode", ["merge", "replace"])
def test_authoritative_receipt_commits_with_sql_and_is_user_scoped(state, requested, mode):
    payload = _payload(conversations=[_conversation()], memories=[_memory()])
    payload["warnings"] = ["测试迁移警告"]
    calls = []

    def publish():
        calls.append("publish")
        assert state.repo.receipt("a", "preview") is None

    imported, skipped = state.repo.apply(
        "a",
        payload,
        mode=mode,
        publish=publish,
        receipt={"preview_id": "preview", "backup_id": "backup", "extract_memories": requested},
    )
    result = state.repo.receipt("a", "preview")
    assert calls == ["publish"]
    assert result["committed"] is True and result["failed_phase"] is None
    assert result["imported"] == imported and result["skipped"] == skipped
    assert result["backup_id"] == "backup" and result["warnings"] == payload["warnings"]
    assert result["extraction"]["status"] == ("failed" if requested else "not_requested")
    if requested:
        assert result["extraction"]["error"] == "INTERRUPTED_EXTRACTION"
    assert state.repo.receipt("b", "preview") is None
    assert state.repo.receipt("a", "missing") is None
    assert "data_transfer_commit" not in dump_json(state.repo.snapshot("a"))


def test_publish_failure_does_not_leave_sql_receipt_or_imported_rows(state):
    def fail_publish():
        raise OSError("projection failed")

    with pytest.raises(OSError, match="projection failed"):
        state.repo.apply(
            "a",
            _payload(conversations=[_conversation()]),
            mode="merge",
            publish=fail_publish,
            receipt={"preview_id": "not-committed", "backup_id": None},
        )
    assert state.repo.receipt("a", "not-committed") is None
    assert state.repo.snapshot("a")["conversations"] == []


def test_update_receipt_keeps_final_extraction_and_refuses_foreign_user_or_commit_reversal(state):
    state.repo.apply("a", _payload(), mode="merge", receipt={"preview_id": "preview", "backup_id": "backup"})
    original = state.repo.receipt("a", "preview")
    updated = deepcopy(original)
    updated["extraction"] = {"status": "succeeded", "memories": 2}
    with pytest.raises(TransferConflict, match="TRANSFER_RECEIPT_NOT_FOUND"):
        state.repo.update_receipt("b", "preview", updated)
    assert state.repo.receipt("a", "preview") == original
    assert state.repo.update_receipt("a", "preview", updated) is True
    assert state.repo.receipt("a", "preview")["extraction"] == {"status": "succeeded", "memories": 2}
    for changed in ({**updated, "committed": False}, {**updated, "backup_id": "different"}):
        with pytest.raises(TransferConflict):
            state.repo.update_receipt("a", "preview", changed)
    assert state.repo.receipt("a", "preview") == updated


def test_memory_replace_preserves_previous_receipts_and_other_users_memory_events(state):
    state.repo.apply("a", _payload(memories=[_memory()]), mode="merge", receipt={"preview_id": "first"})
    original = state.repo.receipt("a", "first")
    with state.sessions.begin() as db:
        db.add(MemoryEventBatch(identity="other-event", subject_user_id="b", envelope="{}", candidates="[]"))
    state.repo.apply("a", _payload(scope="memory"), mode="replace", receipt={"preview_id": "second"})
    assert state.repo.receipt("a", "first") == original
    assert state.repo.receipt("a", "second")["committed"] is True
    with state.sessions() as db:
        assert db.get(MemoryEventBatch, "other-event").candidates == "[]"


def test_receipt_kind_collision_cannot_expose_or_change_normal_memory_batch(state):
    with state.sessions.begin() as db:
        db.add(
            MemoryEventBatch(
                identity="data-transfer-commit:collision",
                subject_user_id="a",
                envelope='{"kind":"other"}',
                candidates="[]",
            )
        )
    with pytest.raises(TransferConflict, match="TRANSFER_RECEIPT_INVALID"):
        state.repo.receipt("a", "collision")
    with pytest.raises(TransferConflict, match="TRANSFER_RECEIPT_INVALID"):
        state.repo.update_receipt("a", "collision", {"committed": True})
    assert state.repo.receipt("b", "collision") is None
    with state.sessions() as db:
        assert db.get(MemoryEventBatch, "data-transfer-commit:collision").candidates == "[]"


def test_real_chroma_lists_all_pages_including_embeddings_and_deletes_only_owner(state, monkeypatch):
    monkeypatch.setattr(stores, "_USER_RECORD_PAGE_SIZE", 2)
    store = stores.ChromaVectorStore(
        {
            "vector_store_path": str(state.tmp_path / "real-vectors"),
            "embedding_model": {"api_key": "test-no-network"},
        }
    )
    identities = [f"vector-{index}" for index in range(5)]
    try:
        store.collection.add(
            ids=identities + ["other"],
            documents=["事实"] * 6,
            metadatas=[{"user_id": "a"}] * 5 + [{"user_id": "b"}],
            embeddings=[[1.0, 0.25]] * 6,
        )
        snapshot = store.list_user_documents("a")
        assert {row["id"] for row in snapshot} == set(identities)
        assert all(row["embedding"] == [1.0, 0.25] and row["content"] == "事实" for row in snapshot)
        assert store.delete_user_records_strict("a") == 5
        assert store.list_user_documents("a") == []
        assert [row["id"] for row in store.list_user_documents("b")] == ["other"]
        docs = [stores.Document(row["content"], row["metadata"], id=row["id"]) for row in snapshot]
        store.upsert_documents(docs, identities, embeddings=[row["embedding"] for row in snapshot])
        assert len(store.list_user_documents("a")) == 5
    finally:
        store.close()
