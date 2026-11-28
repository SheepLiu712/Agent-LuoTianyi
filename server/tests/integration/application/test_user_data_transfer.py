"""隔离账号从真实 HTTP 迁移入口恢复 SQL、媒体和记忆；不使用现用数据。"""

import copy
import io
import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.application.user.data_transfer import TransferWorkspace, UserDataTransferService
from src.domain.agent import MediaRef
from src.infrastructure.data_transfer import decode_import, encode_archive
from src.infrastructure.media import PermanentMediaStore, create_media_resolver
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.credential_service import CredentialService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import (
    AgentMemoryRecord,
    Base,
    Conversation,
    ConversationContext,
    MemoryChunkRecord,
    User,
)
from src.infrastructure.persistence.transfer_projections import TransferProjections
from src.infrastructure.persistence.user_data_transfer import UserDataRepository
from src.web.http import routes
from src.web.http.user_interface import UserInterface


class Vectors:
    enabled = True

    def __init__(self):
        self.rows = {}
        self.fail_once = False
        self.embedding_calls = 0

    def list_user_documents(self, user_id):
        return copy.deepcopy([row for row in self.rows.values() if row["metadata"]["user_id"] == user_id])

    async def prepare_embeddings(self, texts):
        self.embedding_calls += 1
        return [[float(len(text)), 1.0] for text in texts]

    def upsert_documents(self, documents, ids, *, embeddings):
        for document, identity, vector in zip(documents, ids, embeddings):
            self.rows[identity] = {
                "id": identity,
                "content": document.content,
                "metadata": document.metadata,
                "embedding": vector,
            }
        if self.fail_once:
            self.fail_once = False
            raise OSError("controlled vector failure")
        return ids

    def delete_user_records_strict(self, user_id):
        identities = [key for key, row in self.rows.items() if row["metadata"]["user_id"] == user_id]
        for key in identities:
            self.rows.pop(key)
        return len(identities)

    def delete_documents(self, identities):
        for identity in identities:
            self.rows.pop(identity, None)
        return True


class Interactions:
    def __init__(self):
        self.blocked = set()
        self.busy = False

    async def begin_user_data_transfer(self, user_id):
        if self.busy:
            raise RuntimeError("USER_INTERACTION_BUSY")
        assert user_id not in self.blocked
        self.blocked.add(user_id)
        return object()

    async def end_user_data_reset(self, user_id, token):
        self.blocked.remove(user_id)


@pytest.fixture
def transfer(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'transfer.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    redis = RedisBuffer()
    users = UserStore({}, sessions, redis)
    history = ConversationService(sql_session_factory=sessions, redis_buffer=redis, user_store=users)
    credentials = CredentialService(
        sql_session_factory=sessions,
        redis_buffer=redis,
        jwt_secret="offline-transfer-test",
        message_token_ttl_seconds=3600,
    )
    config = {"root": str(tmp_path / "media")}
    media, resolver = PermanentMediaStore(config), create_media_resolver(config)
    vectors, interactions = Vectors(), Interactions()
    repository = UserDataRepository(sessions)
    service = UserDataTransferService(
        repository=repository,
        projections=TransferProjections(vectors, media, resolver),
        vectors=vectors,
        interactions=interactions,
        redis=redis,
        workspace=TransferWorkspace(tmp_path / "transfers"),
        characters=("luotianyi", "other-character"),
    )
    with sessions() as db:
        db.add_all(
            [
                User(
                    uuid="alice",
                    username="alice",
                    password="hash-a",
                    auth_token="auth-a",
                    description="用户喜欢薄荷",
                    preferences='{"relationship":"朋友"}',
                ),
                User(uuid="bob", username="bob", password="hash-b", auth_token="auth-b"),
            ]
        )
        db.commit()
    runtime = SimpleNamespace(
        database_manager=SimpleNamespace(credential_service=credentials),
        user_data_transfer_service=service,
        user_interface=UserInterface(
            SimpleNamespace(credential_service=credentials, conversation_service=history), resolver
        ),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield SimpleNamespace(
            sessions=sessions,
            redis=redis,
            history=history,
            credentials=credentials,
            media=media,
            resolver=resolver,
            vectors=vectors,
            interactions=interactions,
            repository=repository,
            service=service,
            client=client,
            headers=lambda user: {"Authorization": f"Bearer {credentials.generate_message_token(user)}"},
        )
    engine.dispose()


def seed_native(state):
    media_id, text_id, image_id, memory_id = (str(uuid4()) for _ in range(4))
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image, format="PNG")
    state.media.persist_image(
        media_ref=MediaRef(media_id=media_id), owner_user_id="alice", data=image.getvalue(), mime_type="image/png"
    )
    stamp = datetime(2026, 1, 2, 12, 0)
    with state.sessions() as db:
        db.add_all(
            [
                Conversation(
                    uuid=text_id,
                    user_id="alice",
                    character_id="luotianyi",
                    timestamp=stamp,
                    source="user",
                    type="text",
                    content="测试用户喜欢薄荷",
                    meta_data="{}",
                ),
                Conversation(
                    uuid=image_id,
                    user_id="alice",
                    character_id="luotianyi",
                    timestamp=stamp,
                    source="user",
                    type="image",
                    content="蓝色图片",
                    meta_data=json.dumps({"media_id": media_id, "mime_type": "image/png"}),
                ),
                AgentMemoryRecord(
                    id=memory_id,
                    subject_user_id="alice",
                    owner_character_id="luotianyi",
                    memory_type="user_fact",
                    visibility="private",
                    source="chat",
                    content="用户喜欢薄荷",
                    created_at=stamp,
                ),
                ConversationContext(
                    user_id="alice",
                    character_id="luotianyi",
                    context_summary="已有测试总结",
                    context_memory_count=2,
                    maintenance_entry_id=text_id,
                    updated_at=stamp,
                ),
            ]
        )
        db.commit()
    return media_id


def preview(state, data, user="bob", **params):
    response = state.client.post("/user/data/import/preview", content=data, params=params, headers=state.headers(user))
    assert response.status_code == 200, response.text
    return response.json()


def commit(state, view, user="bob", **options):
    return state.client.post(
        "/user/data/import/commit", json={"preview_id": view["preview_id"], **options}, headers=state.headers(user)
    )


def test_http_native_cross_account_roundtrip_media_profile_and_repeat(transfer):
    seed_native(transfer)
    response = transfer.client.get("/user/data/export", headers=transfer.headers("alice"))
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    payload, files = decode_import(response.content)
    assert payload["source_user_id"] == "alice"
    assert b"auth-a" not in response.content and len(files) == 1
    view = preview(transfer, response.content)
    result = commit(transfer, view).json()
    assert result["success"] and result["committed"]
    assert result["imported"] == {"conversations": 2, "memories": 1}
    again = commit(transfer, preview(transfer, response.content)).json()
    assert again["imported"] == {"conversations": 0, "memories": 0}
    with transfer.sessions() as db:
        bob = db.get(User, "bob")
        assert bob.description == "用户喜欢薄荷" and json.loads(bob.preferences)["relationship"] == "朋友"
        assert bob.password == "hash-b" and bob.auth_token == "auth-b"
        rows = db.query(Conversation).filter_by(user_id="bob").all()
        assert len(rows) == 2 and all(
            row.uuid not in {item["uuid"] for item in payload["conversations"]} for row in rows
        )
        image_row = next(row for row in rows if row.type == "image")
        image_identity = json.loads(image_row.meta_data)["media_id"]
        assert len(transfer.resolver.resolve(MediaRef(media_id=image_identity), owner_user_id="bob").data) > 0
        assert db.query(AgentMemoryRecord).filter_by(subject_user_id="bob").count() == 1
    image_response = transfer.client.post(
        "/get_image",
        json={"username": "bob", "token": transfer.credentials.generate_message_token("bob"), "uuid": image_row.uuid},
    )
    assert image_response.status_code == 200 and image_response.headers["content-type"] == "image/png"


def test_replace_clears_cached_context_before_subsequent_chat(transfer):
    seed_native(transfer)
    old = transfer.history.get_conversation_context_state("alice")
    assert len(old["conversations"]) == 2
    transfer.redis.setex("user_context:alice:other-character", 3600, "another role")
    transfer.redis.setex("user_context:bob:alice", 3600, "other user")
    view = preview(
        transfer, b'[{"role":"user","content":"replacement history"}]', user="alice", source_format="generic"
    )
    result = commit(transfer, view, user="alice", mode="replace", confirm_replace=True)
    assert result.status_code == 200 and result.json()["success"]
    current = transfer.history.get_conversation_context_state("alice")
    assert current["conversations"] == []  # 外部记录只进入历史，不进入角色上下文。
    assert current["summary"] == ""
    assert current["context_count"] == 0
    assert transfer.redis.get("user_context:alice:other-character") is None
    assert transfer.redis.get("user_context:bob:alice") == "other user"


def test_http_isolation_preview_backup_and_missing_auth(transfer):
    assert transfer.client.get("/user/data/export").status_code == 401
    view = preview(transfer, b'[{"role":"user","content":"offline input"}]', source_format="generic")
    assert commit(transfer, view, user="alice").status_code == 404
    assert commit(transfer, view, mode="replace").status_code == 400
    done = commit(transfer, view, mode="replace", confirm_replace=True).json()
    backup_id = done["backup_id"]
    assert done["success"] and backup_id
    assert transfer.client.get(f"/user/data/backups/{backup_id}", headers=transfer.headers("alice")).status_code == 404
    assert transfer.client.get(f"/user/data/backups/{backup_id}", headers=transfer.headers("bob")).status_code == 200
    assert commit(transfer, view, mode="replace", confirm_replace=True).json() == done


def test_external_history_never_enters_automatic_context_and_optional_extraction_retries(transfer):
    calls = []

    async def extract(owner, character, batch, rows):
        calls.append((owner, character, batch, rows))
        if len(calls) == 1:
            raise OSError("offline model unavailable")
        return 1

    transfer.service._extract = extract
    data = json.dumps(
        [{"role": "user", "content": "我喜欢测试音乐", "timestamp": "2026-01-02T12:00:00"}], ensure_ascii=False
    ).encode()
    view = preview(transfer, data, source_format="generic")
    first = commit(transfer, view).json()
    assert first["success"] and calls == []
    context = transfer.history.get_conversation_context_state("bob")
    assert context["conversations"] == []
    view = preview(transfer, data, source_format="generic")
    failed = commit(transfer, view, extract_memories=True).json()
    assert failed["success"] and failed["extraction"]["status"] == "failed"
    retried = commit(transfer, view, extract_memories=True).json()
    assert retried["success"] and retried["extraction"]["status"] == "succeeded"
    assert calls[0][2] == calls[1][2]
    with transfer.sessions() as db:
        assert db.query(Conversation).filter_by(user_id="bob").count() == 1


def test_replace_projection_failure_rolls_back_and_backup_remains_downloadable(transfer):
    seed_native(transfer)
    exported = transfer.client.get("/user/data/export", headers=transfer.headers("alice")).content
    with transfer.sessions() as db:
        db.add(
            Conversation(
                uuid=str(uuid4()),
                user_id="bob",
                character_id="luotianyi",
                type="text",
                source="user",
                content="原先的测试记录",
            )
        )
        db.commit()
    view = preview(transfer, exported)
    transfer.vectors.fail_once = True
    result = commit(transfer, view, mode="replace", confirm_replace=True).json()
    assert result["success"] is False and result["committed"] is False
    assert result["backup_id"]
    with transfer.sessions() as db:
        assert [row.content for row in db.query(Conversation).filter_by(user_id="bob")] == ["原先的测试记录"]
        assert db.query(AgentMemoryRecord).filter_by(subject_user_id="bob").count() == 0
    backup = transfer.client.get(f'/user/data/backups/{result["backup_id"]}', headers=transfer.headers("bob"))
    assert backup.status_code == 200
    assert decode_import(backup.content)[0]["conversations"][0]["content"] == "原先的测试记录"
    assert commit(transfer, view, mode="replace", confirm_replace=True).json() == result
    assert transfer.interactions.blocked == set()


def test_busy_and_untrusted_native_paths_rejected_without_data_loss(transfer):
    data = b'[{"role":"user","content":"test"}]'
    view = preview(transfer, data)
    transfer.interactions.busy = True
    assert commit(transfer, view).status_code == 409
    transfer.interactions.busy = False
    assert commit(transfer, view).json()["success"]
    seed_native(transfer)
    native = transfer.client.get("/user/data/export", headers=transfer.headers("alice")).content
    payload, files = decode_import(native)
    payload["conversations"][0]["meta_data"]["image_server_path"] = "C:/untrusted-archive-path"
    view = preview(transfer, encode_archive(payload, files))
    assert commit(transfer, view).json()["success"]
    with transfer.sessions() as db:
        for row in db.query(Conversation).filter_by(user_id="bob"):
            assert "image_server_path" not in json.loads(row.meta_data or "{}")


def test_export_backfills_only_owner_legacy_and_readable_output(transfer):
    transfer.vectors.rows = {
        "old-a": {
            "id": "old-a",
            "content": "旧版测试偏好",
            "metadata": {"user_id": "alice", "owner_character_id": "luotianyi", "memory_type": "user_memory"},
            "embedding": [1.0, 0.0],
        },
        "old-b": {
            "id": "old-b",
            "content": "另一个账号测试",
            "metadata": {"user_id": "bob", "owner_character_id": "luotianyi"},
            "embedding": [0.0, 1.0],
        },
    }
    response = transfer.client.get("/user/data/export?scope=memory", headers=transfer.headers("alice"))
    assert response.status_code == 200, response.text
    again = transfer.client.get("/user/data/export?scope=memory&format=markdown", headers=transfer.headers("alice"))
    assert again.status_code == 200 and "旧版测试偏好" in again.text
    with transfer.sessions() as db:
        assert db.query(AgentMemoryRecord).filter_by(subject_user_id="alice").count() == 1
        assert db.query(AgentMemoryRecord).filter_by(subject_user_id="bob").count() == 0
        assert db.query(MemoryChunkRecord).filter_by(embedding_id="old-a").count() == 1


def test_explicit_extraction_freezes_candidates_and_recovers_partial_memory_write(transfer):
    from functools import partial

    from src.agent.skills.adapters.memory.writer import MemoryWriter
    from src.agent.skills.imported_memory import ImportedMemorySkill
    from src.infrastructure.persistence.database.services.memory_store import MemoryStore

    class OfflineModel:
        calls = 0

        async def generate_response(self, **kwargs):
            self.calls += 1
            assert "外部助手不是当前角色" in kwargs["history"]
            return json.dumps({"user_memory": ["测试用户喜欢音乐"], "event_memory": ["外部助手在旅行"]})

    model = OfflineModel()
    writer = MemoryWriter({}, model)
    store = MemoryStore({}, transfer.sessions, transfer.redis)
    memory = SimpleNamespace(
        extract_maintenance_candidates=writer.extract_maintenance_candidates,
        write_maintenance_candidates=partial(
            writer.write_maintenance_candidates,
            vector_store=transfer.vectors,
            memory_store=store,
            owner_character_id="luotianyi",
        ),
    )
    skill = ImportedMemorySkill(memories={"luotianyi": memory}, session_factory=transfer.sessions)
    transfer.service._extract = skill.extract
    view = preview(transfer, b'[{"role":"user","content":"music"}]')
    transfer.vectors.fail_once = True
    first = commit(transfer, view, extract_memories=True).json()
    assert first["extraction"]["status"] == "failed"
    second = commit(transfer, view, extract_memories=True).json()
    assert second["extraction"] == {"status": "succeeded", "memories": 1}
    assert model.calls == 1
    with transfer.sessions() as db:
        rows = db.query(AgentMemoryRecord).filter_by(subject_user_id="bob").all()
        assert [row.content for row in rows] == ["测试用户喜欢音乐"]
        assert db.query(MemoryChunkRecord).count() == 1


def test_corrupt_archive_rejected_before_write_and_backup_failure_preserves_existing(transfer, monkeypatch):
    seed_native(transfer)
    exported = transfer.client.get("/user/data/export", headers=transfer.headers("alice")).content
    bad = transfer.client.post("/user/data/import/preview", content=exported[:30], headers=transfer.headers("bob"))
    assert bad.status_code == 400
    view = preview(transfer, exported)
    with transfer.sessions() as db:
        db.add(
            Conversation(
                uuid=str(uuid4()),
                user_id="bob",
                character_id="luotianyi",
                source="user",
                type="text",
                content="keep-on-backup-failure",
            )
        )
        db.commit()

    def fail(*args, **kwargs):
        raise OSError("test backup disk unavailable")

    monkeypatch.setattr(transfer.service._workspace, "put", fail)
    assert commit(transfer, view, mode="replace", confirm_replace=True).status_code == 503
    with transfer.sessions() as db:
        assert [row.content for row in db.query(Conversation).filter_by(user_id="bob")] == ["keep-on-backup-failure"]
    assert transfer.interactions.blocked == set()


def test_call_and_media_identities_survive_return_to_original_account(transfer):
    from src.domain.call import CallContent, CallEndReason, CallOutcome

    seed_native(transfer)
    call = CallContent(
        call_id=uuid4(),
        outcome=CallOutcome.CONNECTED,
        active_duration_ms=1500,
        summary="测试通话概要",
        end_reason=CallEndReason.USER_HANGUP,
    )
    metadata = {
        "call_id": str(call.call_id),
        "outcome": call.outcome.value,
        "active_duration_ms": call.active_duration_ms,
        "summary": call.summary,
        "end_reason": call.end_reason.value,
    }
    with transfer.sessions() as db:
        db.add(
            Conversation(
                uuid=str(uuid4()),
                user_id="alice",
                character_id="luotianyi",
                source="user",
                type="call",
                content=call.text,
                meta_data=json.dumps(metadata),
                timestamp=datetime(2026, 1, 2, 12, 1),
            )
        )
        db.commit()
    original = transfer.client.get("/user/data/export", headers=transfer.headers("alice")).content
    assert commit(transfer, preview(transfer, original)).json()["success"]
    returned = transfer.client.get("/user/data/export", headers=transfer.headers("bob")).content
    result = commit(transfer, preview(transfer, returned, user="alice"), user="alice").json()
    assert result["success"] and result["imported"] == {"conversations": 0, "memories": 0}
    with transfer.sessions() as db:
        alice_call = db.query(Conversation).filter_by(user_id="alice", type="call").one()
        assert json.loads(alice_call.meta_data)["call_id"] == str(call.call_id)


def test_invalid_native_content_is_rejected_during_preview(transfer):
    seed_native(transfer)
    original = transfer.client.get("/user/data/export", headers=transfer.headers("alice")).content
    payload, files = decode_import(original)
    payload["conversations"][0].update(type="audio", meta_data={}, content="invalid audio metadata")
    response = transfer.client.post(
        "/user/data/import/preview", content=encode_archive(payload, files), headers=transfer.headers("bob")
    )
    assert response.status_code == 400
    with transfer.sessions() as db:
        assert db.query(Conversation).filter_by(user_id="bob").count() == 0
