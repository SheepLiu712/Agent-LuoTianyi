"""本人数据的逻辑快照与 SQL 事务恢复；不复制账号凭据或供应商索引。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_

from src.infrastructure.persistence.database.sql_database import (
    AgentMemoryRecord,
    CallMaintenanceBatch,
    CallSession,
    CognitiveMaintenanceBatch,
    Conversation,
    ConversationContext,
    MemoryChunkRecord,
    MemoryEdgeRecord,
    MemoryEventBatch,
    User,
)

_SCOPES = {"chat", "memory", "all"}
_LOCAL_METADATA = {
    "_transfer_origin",
    "_transfer_media_origin",
    "_transfer_call_origin",
    "_transfer_history_only",
    "image_server_path",
    "image_client_path",
}
_MEMORY_TIMES = {"created_at", "happened_at", "last_accessed_at"}
_RECEIPT_PREFIX = "data-transfer-commit:"


class TransferConflict(ValueError):
    """归档身份与现存内容不一致，不能把去重变成静默覆盖。"""


def as_json(value):
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return value or {}


def dump_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_time(value):
    if value is None:
        return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # 既有 SQL 时间线使用本地 naive 时间；保留本地显示与排序语义。
    return result.astimezone().replace(tzinfo=None) if result.tzinfo else result


def stable_id(kind, user_id, source_user_id, identity):
    if source_user_id == user_id:
        return identity
    return str(uuid5(NAMESPACE_URL, dump_json(["agentluo-transfer", kind, user_id, source_user_id, identity])))


def _metadata(value):
    return {key: item for key, item in as_json(value).items() if key not in _LOCAL_METADATA}


def _row_dict(row, *, exclude=()):
    result = {}
    for column in row.__table__.columns:
        if column.name in exclude:
            continue
        value = getattr(row, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        if column.name == "meta_data":
            value = as_json(value)
        result[column.name] = value
    return result


def _chunks(row):
    return row.get("chunks") or [{"chunk_text": row["content"], "chunk_type": "content"}]


def _chunk_values(chunks):
    return sorted((chunk["chunk_text"], chunk.get("chunk_type", "content")) for chunk in chunks)


def _external(row):
    return as_json(row["meta_data"]).get("_transfer_external") is True


class UserDataRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    def snapshot(self, user_id, scope="all"):
        if scope not in _SCOPES:
            raise ValueError("INVALID_TRANSFER_SCOPE")
        with self._sessions() as db:
            user = db.get(User, user_id)
            if user is None:
                raise ValueError("USER_NOT_FOUND")
            payload = {
                "format": "agentluo-data",
                "version": 1,
                "scope": scope,
                "source_format": "native",
                "source_user_id": user_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "conversations": [],
                "contexts": [],
                "memories": [],
                "memory_edges": [],
                "profile": {},
                "media": [],
                "warnings": [],
            }
            if scope in {"chat", "all"}:
                payload["conversations"] = [
                    _row_dict(row)
                    for row in db.query(Conversation)
                    .filter_by(user_id=user_id)
                    .order_by(Conversation.timestamp, Conversation.uuid)
                ]
                payload["contexts"] = list(self._context_states(db, user).values())
            if scope in {"memory", "all"}:
                self._snapshot_memory(db, user_id, payload)
                payload["profile"] = {"description": user.description or "", "preferences": as_json(user.preferences)}
            return payload

    @staticmethod
    def _snapshot_memory(db, user_id, payload):
        records = db.query(AgentMemoryRecord).filter_by(subject_user_id=user_id).order_by(AgentMemoryRecord.id).all()
        for record in records:
            row = _row_dict(record)
            row["chunks"] = [
                {"chunk_text": chunk.chunk_text, "chunk_type": chunk.chunk_type}
                for chunk in sorted(record.chunks, key=lambda item: item.id)
            ]
            payload["memories"].append(row)
        ids = [row.id for row in records]
        if ids:
            payload["memory_edges"] = [
                _row_dict(edge)
                for edge in db.query(MemoryEdgeRecord)
                .filter(MemoryEdgeRecord.from_memory_id.in_(ids), MemoryEdgeRecord.to_memory_id.in_(ids))
                .order_by(MemoryEdgeRecord.id)
            ]

    def backfill_legacy(self, user_id, vectors):
        """仅提升本人且尚未关联正本的旧向量；稳定身份使导出重试幂等。"""
        count = 0
        with self._sessions() as db, db.begin():
            if db.get(User, user_id) is None:
                raise ValueError("USER_NOT_FOUND")
            for vector in vectors:
                _, _, character_id = self._legacy_fields(user_id, vector)
                linked = db.query(MemoryChunkRecord).filter_by(embedding_id=vector["id"]).first()
                if linked is not None:
                    record = db.get(AgentMemoryRecord, linked.memory_record_id)
                    if record is None or (record.subject_user_id, record.owner_character_id, linked.chunk_text) != (
                        user_id,
                        character_id,
                        vector["content"],
                    ):
                        raise TransferConflict("LEGACY_MEMORY_LINK_CONFLICT")
                    continue
                if "memory_scope" in vector["metadata"]:
                    raise TransferConflict("CANONICAL_VECTOR_WITHOUT_MEMORY")
                row = self._legacy_row(user_id, vector)
                if self._add_memory(db, user_id, row, {(row["id"], 0): vector["id"]}):
                    count += 1
        return count

    @staticmethod
    def _legacy_fields(user_id, vector):
        metadata, content, identity = vector["metadata"], vector["content"], vector["id"]
        if not isinstance(metadata, dict) or metadata.get("user_id") != user_id:
            raise ValueError("LEGACY_MEMORY_OWNER_MISMATCH")
        character_id = metadata.get("owner_character_id", "luotianyi")
        if not all(isinstance(item, str) and item.strip() for item in (identity, content, character_id)):
            raise ValueError("LEGACY_MEMORY_INVALID")
        return identity, content, character_id

    @classmethod
    def _legacy_row(cls, user_id, vector):
        identity, content, character_id = cls._legacy_fields(user_id, vector)
        metadata = vector["metadata"]
        return {
            "id": stable_id("legacy-memory", user_id, "legacy-vector", identity),
            "owner_character_id": character_id,
            "subject_user_id": user_id,
            "memory_type": "user_fact" if metadata.get("memory_type") == "user_memory" else "interaction_event",
            "visibility": "private",
            "source": "legacy_vector",
            "content": content,
            "summary": None,
            "importance": 0.5,
            "confidence": 1.0,
            "emotional_valence": None,
            "happened_at": None,
            "created_at": parse_time(metadata.get("timestamp") or "1970-01-01T00:00:00"),
            "last_accessed_at": None,
            "meta_data": {"legacy_vector_id": identity, "legacy_metadata": metadata},
        }

    def receipt(self, user_id, preview_id):
        """只读本人 SQL 权威提交回执；旁路结果文件失效时仍可确认已经提交。"""
        with self._sessions() as db:
            row = db.get(MemoryEventBatch, _RECEIPT_PREFIX + preview_id)
            if row is None or row.subject_user_id != user_id:
                return None
            return self._receipt_value(row, preview_id)

    def update_receipt(self, user_id, preview_id, result):
        """在显式提取完成后更新本人权威结果，不允许把已提交状态倒退为未提交。"""
        with self._sessions() as db, db.begin():
            row = db.get(MemoryEventBatch, _RECEIPT_PREFIX + preview_id)
            if row is None or row.subject_user_id != user_id:
                raise TransferConflict("TRANSFER_RECEIPT_NOT_FOUND")
            previous = self._receipt_value(row, preview_id)
            if not isinstance(result, dict) or result.get("committed") is not True:
                raise TransferConflict("TRANSFER_RECEIPT_INVALID")
            stable_fields = ("imported", "skipped", "backup_id")
            if any(result.get(key) != previous.get(key) for key in stable_fields):
                raise TransferConflict("TRANSFER_RECEIPT_IDENTITY_CONFLICT")
            row.candidates = dump_json(result)
        return True

    @staticmethod
    def _receipt_value(row, preview_id):
        try:
            envelope, result = as_json(row.envelope), as_json(row.candidates)
            if envelope != {"kind": "data_transfer_commit", "preview_id": preview_id}:
                raise ValueError("invalid receipt identity")
            if not isinstance(result, dict) or result.get("committed") is not True:
                raise ValueError("invalid receipt result")
        except (TypeError, ValueError):
            raise TransferConflict("TRANSFER_RECEIPT_INVALID") from None
        return result

    @staticmethod
    def _write_receipt(db, user_id, receipt, payload, imported, skipped):
        identity = _RECEIPT_PREFIX + receipt["preview_id"]
        if db.get(MemoryEventBatch, identity) is not None:
            raise TransferConflict("TRANSFER_RECEIPT_ALREADY_EXISTS")
        extraction = {"status": "not_requested", "memories": 0}
        if receipt.get("extract_memories", False):
            extraction.update(status="failed", error="INTERRUPTED_EXTRACTION")
        result = {
            "success": True,
            "committed": True,
            "failed_phase": None,
            "imported": imported,
            "skipped": skipped,
            "backup_id": receipt.get("backup_id"),
            "extraction": extraction,
            "warnings": payload.get("warnings", []),
        }
        db.add(
            MemoryEventBatch(
                identity=identity,
                subject_user_id=user_id,
                envelope=dump_json({"kind": "data_transfer_commit", "preview_id": receipt["preview_id"]}),
                candidates=dump_json(result),
            )
        )
        db.flush()

    def apply(self, user_id, payload, *, mode, vector_ids=None, publish=None, receipt=None):
        """单事务接纳已重绑定的归档；投影发布失败或 SQL commit 失败均向上传播。

        相同正本会消费并移除 vector_ids 的对应映射，避免发布无人引用的重复投影。
        调用者须在本方法失败时 rollback 投影，成功后 finish。
        """
        scope = payload["scope"]
        if scope not in _SCOPES or mode not in {"merge", "replace"}:
            raise ValueError("INVALID_TRANSFER_MODE_OR_SCOPE")
        vector_ids = {} if vector_ids is None else vector_ids
        with self._sessions() as db, db.begin():
            user = db.get(User, user_id)
            if user is None:
                raise ValueError("USER_NOT_FOUND")
            states = self._context_states(db, user) if scope in {"chat", "all"} else {}
            if mode == "replace":
                self._delete_scope(db, user_id, scope)
                db.flush()
            preserved = set(states) if mode == "merge" else set()
            imported, skipped, native = self._apply_rows(db, user_id, payload, vector_ids, preserved)
            if scope in {"memory", "all"}:
                self._apply_edges(db, user_id, payload.get("memory_edges", []))
                self._apply_profile(user, payload["profile"], mode)
            if scope in {"chat", "all"}:
                self._apply_contexts(db, user, payload, mode, states, native)
            db.flush()
            if publish is not None:
                publish()
            if receipt is not None:
                self._write_receipt(db, user_id, receipt, payload, imported, skipped)
            return imported, skipped

    def _apply_rows(self, db, user_id, payload, vector_ids, preserved):
        imported = {"conversations": 0, "memories": 0}
        skipped = {"conversations": 0, "memories": 0}
        native = defaultdict(list)
        if payload["scope"] in {"chat", "all"}:
            for row in payload["conversations"]:
                history_only = row["character_id"] in preserved
                added = self._add_conversation(db, user_id, row, history_only=history_only)
                (imported if added else skipped)["conversations"] += 1
                if added and not _external(row) and not history_only:
                    native[row["character_id"]].append(row)
        if payload["scope"] in {"memory", "all"}:
            for row in payload["memories"]:
                added = self._add_memory(db, user_id, row, vector_ids)
                (imported if added else skipped)["memories"] += 1
        return imported, skipped, native

    @staticmethod
    def _add_conversation(db, user_id, row, *, history_only=False):
        if row.get("user_id") != user_id:
            raise TransferConflict("CONVERSATION_OWNER_MISMATCH")
        existing = db.get(Conversation, row["uuid"])
        values = {key: row[key] for key in ("uuid", "character_id", "source", "type", "content")}
        values.update(user_id=user_id, timestamp=parse_time(row["timestamp"]), meta_data=dump_json(row["meta_data"]))
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in values.items() if key != "meta_data"):
                raise TransferConflict("CONVERSATION_IDENTITY_CONFLICT")
            if _metadata(existing.meta_data) != _metadata(row["meta_data"]):
                raise TransferConflict("CONVERSATION_METADATA_CONFLICT")
            return False
        # 缓存路径不接受包内提供的服务器路径，也不成为未来历史查询的直接文件入口。
        values["meta_data"] = dump_json(
            {
                key: value
                for key, value in as_json(row["meta_data"]).items()
                if key not in {"image_server_path", "image_client_path"}
            }
        )
        if history_only:
            metadata = as_json(values["meta_data"])
            metadata["_transfer_history_only"] = True
            values["meta_data"] = dump_json(metadata)
        db.add(Conversation(**values))
        db.flush()
        return True

    @staticmethod
    def _memory_values(user_id, row):
        if row.get("subject_user_id") != user_id:
            raise TransferConflict("MEMORY_OWNER_MISMATCH")
        values = {column.name: row[column.name] for column in AgentMemoryRecord.__table__.columns if column.name in row}
        values["subject_user_id"] = user_id
        values["meta_data"] = dump_json(row.get("meta_data", {}))
        for key in _MEMORY_TIMES:
            values[key] = parse_time(values.get(key))
        return values

    def _add_memory(self, db, user_id, row, vector_ids):
        values = self._memory_values(user_id, row)
        existing = db.get(AgentMemoryRecord, row["id"])
        if existing is not None:
            for key, value in values.items():
                if key == "last_accessed_at":
                    continue
                actual = getattr(existing, key)
                matches = _metadata(actual) == _metadata(value) if key == "meta_data" else actual == value
                if not matches:
                    raise TransferConflict("MEMORY_IDENTITY_CONFLICT")
            existing.last_accessed_at = max(
                (time for time in (existing.last_accessed_at, values.get("last_accessed_at")) if time is not None),
                default=None,
            )
            persisted = [{"chunk_text": c.chunk_text, "chunk_type": c.chunk_type} for c in existing.chunks]
            # SQL-only 正本没有 chunks 时，可移植的默认分块只代表原 content。
            persisted = persisted or [{"chunk_text": existing.content, "chunk_type": "content"}]
            if _chunk_values(persisted) != _chunk_values(_chunks(row)):
                raise TransferConflict("MEMORY_CHUNK_CONFLICT")
            for index, _ in enumerate(_chunks(row)):
                vector_ids.pop((row["id"], index), None)
            return False
        db.add(AgentMemoryRecord(**values))
        db.flush()
        for index, chunk in enumerate(_chunks(row)):
            db.add(
                MemoryChunkRecord(
                    id=str(uuid5(NAMESPACE_URL, dump_json(["transfer-chunk", row["id"], index]))),
                    memory_record_id=row["id"],
                    chunk_text=chunk["chunk_text"],
                    chunk_type=chunk.get("chunk_type", "content"),
                    embedding_id=vector_ids.get((row["id"], index)),
                )
            )
        db.flush()
        return True

    @staticmethod
    def _apply_edges(db, user_id, edges):
        for row in edges:
            endpoints = [db.get(AgentMemoryRecord, row[key]) for key in ("from_memory_id", "to_memory_id")]
            if any(record is None or record.subject_user_id != user_id for record in endpoints):
                raise TransferConflict("MEMORY_EDGE_OWNER_MISMATCH")
            values = {
                "id": row["id"],
                "from_memory_id": row["from_memory_id"],
                "to_memory_id": row["to_memory_id"],
                "relation_type": row["relation_type"],
                "weight": row.get("weight", 1.0),
                "created_at": parse_time(row.get("created_at")),
                "meta_data": dump_json(row.get("meta_data", {})),
            }
            existing = db.get(MemoryEdgeRecord, row["id"])
            if existing is None:
                db.add(MemoryEdgeRecord(**values))
            elif any(
                (
                    _metadata(existing.meta_data) != _metadata(value)
                    if key == "meta_data"
                    else getattr(existing, key) != value
                )
                for key, value in values.items()
            ):
                raise TransferConflict("MEMORY_EDGE_IDENTITY_CONFLICT")
            db.flush()

    @staticmethod
    def _apply_profile(user, profile, mode):
        if mode == "replace" or not user.description:
            user.description = profile.get("description", "")
        if mode == "replace" or not as_json(user.preferences):
            user.preferences = dump_json(profile.get("preferences", {}))

    @staticmethod
    def _eligible_rows(db, user_id):
        return [
            _row_dict(row)
            for row in db.query(Conversation)
            .filter_by(user_id=user_id)
            .order_by(Conversation.timestamp, Conversation.uuid)
            if not any(
                as_json(row.meta_data).get(key, False) for key in ("_transfer_external", "_transfer_history_only")
            )
        ]

    def _context_states(self, db, user):
        states = {
            row.character_id: _row_dict(row, exclude={"id", "user_id"})
            for row in db.query(ConversationContext).filter_by(user_id=user.uuid)
        }
        if "luotianyi" not in states and (user.context_summary or user.context_memory_count):
            states["luotianyi"] = {
                "character_id": "luotianyi",
                "context_summary": user.context_summary or "",
                "context_memory_count": user.context_memory_count or 0,
                "maintenance_entry_id": None,
                "updated_at": (user.created_at or datetime(1970, 1, 1)).isoformat(),
            }
        return states

    def _apply_contexts(self, db, user, payload, mode, states, native):
        incoming = {row["character_id"]: row for row in payload.get("contexts", [])}
        eligible = self._eligible_rows(db, user.uuid)
        characters = set(incoming) | {row["character_id"] for row in payload["conversations"]}
        for character in characters:
            if mode == "merge" and character in states:
                continue
            rows = [row for row in eligible if row["character_id"] == character]
            original = incoming.get(character, {})
            state = self._restored_context(rows, original, native[character])
            context = db.query(ConversationContext).filter_by(user_id=user.uuid, character_id=character).first()
            if context is None:
                context = ConversationContext(user_id=user.uuid, character_id=character)
                db.add(context)
            for key, value in state.items():
                setattr(context, key, value)
            if character == "luotianyi":
                user.context_summary = context.context_summary
                user.context_memory_count = context.context_memory_count
        user.all_memory_count = len(eligible)
        if mode == "replace" and "luotianyi" not in characters:
            user.context_summary, user.context_memory_count = "", 0

    @staticmethod
    def _restored_context(rows, original, added):
        by_id = {row["uuid"]: index for index, row in enumerate(rows)}
        progress = original.get("maintenance_entry_id")
        if progress is not None and progress not in by_id:
            raise TransferConflict("CONTEXT_PROGRESS_OUTSIDE_SCOPE")
        count = min(original.get("context_memory_count", len(added)), len(rows))
        state = {
            "context_summary": original.get("context_summary", ""),
            "context_memory_count": count,
            "maintenance_entry_id": progress,
        }
        if original.get("updated_at"):
            state["updated_at"] = parse_time(original["updated_at"])
        return state

    @staticmethod
    def _delete_scope(db, user_id, scope):
        if scope in {"all", "chat"}:
            for model in (
                CognitiveMaintenanceBatch,
                CallMaintenanceBatch,
                CallSession,
                ConversationContext,
                Conversation,
            ):
                db.query(model).filter_by(user_id=user_id).delete(synchronize_session=False)
        if scope in {"all", "memory"}:
            ids = [value for (value,) in db.query(AgentMemoryRecord.id).filter_by(subject_user_id=user_id)]
            if ids:
                db.query(MemoryEdgeRecord).filter(
                    or_(MemoryEdgeRecord.from_memory_id.in_(ids), MemoryEdgeRecord.to_memory_id.in_(ids))
                ).delete(synchronize_session=False)
                db.query(MemoryChunkRecord).filter(MemoryChunkRecord.memory_record_id.in_(ids)).delete(
                    synchronize_session=False
                )
                db.query(AgentMemoryRecord).filter(AgentMemoryRecord.id.in_(ids)).delete(synchronize_session=False)
            db.query(MemoryEventBatch).filter(
                MemoryEventBatch.subject_user_id == user_id,
                ~MemoryEventBatch.identity.startswith(_RECEIPT_PREFIX),
            ).delete(synchronize_session=False)
