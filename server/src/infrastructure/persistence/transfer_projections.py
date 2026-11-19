"""本人媒体、向量投影的准备、发布与补偿；不持有 SQL 事务或角色状态。"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from src.domain.agent import MediaRef
from src.infrastructure.media.media_resolver import MediaResolutionError, MediaResolutionErrorCode
from src.infrastructure.persistence.database.vector_store import Document

_MAX_EXPANDED_BYTES = 256 * 1024 * 1024
_BATCH_SIZE = 128
_MEDIA_PATH = re.compile(r"media/[A-Za-z0-9_-]{1,128}/content\.bin\Z")


def _batches(values):
    for start in range(0, len(values), _BATCH_SIZE):
        yield values[start : start + _BATCH_SIZE]


def _warning(payload, text):
    warnings = payload.setdefault("warnings", [])
    if text not in warnings:
        warnings.append(text)


def _references(payload):
    references = {}
    for row in payload.get("conversations", []):
        kind = row["type"]
        if kind not in {"image", "audio"}:
            continue
        metadata = row.get("meta_data") or {}
        identity = metadata.get("media_id")
        if not identity:
            if row["source"] == "user":
                _warning(payload, f"消息 {row['uuid']} 缺少原媒体引用，无法恢复媒体。")
            continue
        descriptor = {
            "id": identity,
            "kind": kind,
            "mime_type": metadata.get("mime_type") or ("image/jpeg" if kind == "image" else "audio/mp4"),
            "duration_ms": metadata.get("duration_ms") if kind == "audio" else None,
            "path": None,
            "sha256": None,
        }
        if identity in references and references[identity] != descriptor:
            raise ValueError("TRANSFER_MEDIA_REFERENCE_CONFLICT")
        references[identity] = descriptor
    return references


def _vector_document(user_id, row, index, chunk, occurrence):
    # 分块重排不能把待补投影绑到旧下标对应的另一段内容。
    identity = str(
        uuid5(
            NAMESPACE_URL,
            json.dumps(
                [
                    "agentluo-transfer-vector-chunk",
                    user_id,
                    row["id"],
                    chunk.get("chunk_type", "content"),
                    chunk["chunk_text"],
                    occurrence,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )
    metadata = {
        "user_id": user_id,
        "owner_character_id": row["owner_character_id"],
        "memory_type": "user_memory" if row["memory_type"] == "user_fact" else "event_memory",
        "memory_record_id": row["id"],
        "memory_scope": "user",
        "source": row["source"],
        "chunk_index": index,
        "chunk_type": chunk.get("chunk_type", "content"),
    }
    return Document(chunk["chunk_text"], metadata, id=identity)


class TransferProjections:
    def __init__(self, vector_store, media_store, media_resolver):
        self.vector_store = vector_store
        self.media_store = media_store
        self.media_resolver = media_resolver

    def export_media(self, user_id, payload):
        """按本人受控引用导出已校验媒体；缺失项明确保留 descriptor 和 warning。"""
        files, media, total = {}, [], 0
        for identity, descriptor in _references(payload).items():
            try:
                prepared = self.media_store.read_for_transfer(
                    media_ref=MediaRef(media_id=identity),
                    owner_user_id=user_id,
                    expected_kind=descriptor["kind"],
                )
                resolved = self.media_resolver.resolve(
                    MediaRef(media_id=identity),
                    owner_user_id=user_id,
                    expected_kind=descriptor["kind"],
                )
                if resolved.data != prepared.data:
                    raise ValueError("TRANSFER_MEDIA_CHANGED_DURING_EXPORT")
            except MediaResolutionError as error:
                if error.code == MediaResolutionErrorCode.UNAUTHORIZED:
                    raise
                _warning(payload, f"媒体 {identity} 不可读取或校验失败：{error.code}。")
            except (ValueError, OSError) as error:
                _warning(payload, f"媒体 {identity} 不可读取或校验失败：{type(error).__name__}。")
            else:
                descriptor.update(
                    path=f"media/{identity}/content.bin",
                    sha256=sha256(prepared.data).hexdigest(),
                    mime_type=prepared.metadata["mime_type"],
                    duration_ms=prepared.metadata.get("duration_ms"),
                )
                total += len(prepared.data)
                if total > _MAX_EXPANDED_BYTES:
                    raise ValueError("TRANSFER_MEDIA_TOTAL_TOO_LARGE")
                files[descriptor["path"]] = prepared.data
            media.append(descriptor)
        payload["media"] = media
        return files

    async def prepare(self, user_id, payload, mode):
        """先完成所有内容校验和 embedding；本方法不会发布文件、向量或 SQL。"""
        if mode not in {"merge", "replace"} or payload["scope"] not in {"chat", "memory", "all"}:
            raise ValueError("INVALID_TRANSFER_MODE_OR_SCOPE")
        media = self._prepare_media(user_id, payload) if payload["scope"] in {"chat", "all"} else []
        previous, documents, vector_ids, embeddings = [], [], {}, []
        if payload["scope"] in {"memory", "all"}:
            previous = deepcopy(self.vector_store.list_user_documents(user_id))
            self._validate_snapshot(user_id, previous)
            if self.vector_store.enabled:
                documents, vector_ids = self._documents(user_id, payload)
                for batch in _batches(documents):
                    vectors = await self.vector_store.prepare_embeddings([doc.get_content() for doc in batch])
                    self._validate_embeddings(vectors, len(batch))
                    embeddings.extend(vectors)
            elif payload.get("memories"):
                _warning(payload, "向量检索已关闭：长期记忆以规范正本恢复，本次不生成向量投影。")
        return TransferProjectionPlan(
            self.vector_store,
            self.media_store,
            user_id,
            mode,
            payload["scope"],
            media,
            previous,
            documents,
            embeddings,
            vector_ids,
        )

    def _prepare_media(self, user_id, payload):
        references, prepared, seen, total = _references(payload), [], set(), 0
        for descriptor in payload.get("media", []):
            identity = descriptor["id"]
            if identity not in references or identity in seen:
                raise ValueError("TRANSFER_MEDIA_NOT_REFERENCED_OR_DUPLICATED")
            seen.add(identity)
            if descriptor["kind"] != references[identity]["kind"]:
                raise ValueError("TRANSFER_MEDIA_KIND_MISMATCH")
            if descriptor["path"] is None:
                if descriptor.get("sha256") is not None or descriptor.get("data") is not None:
                    raise ValueError("TRANSFER_MISSING_MEDIA_HAS_CONTENT")
                _warning(payload, f"媒体 {identity} 缺失，本次仅恢复消息。")
                continue
            item = self._prepare_media_item(user_id, descriptor)
            duration = references[identity]["duration_ms"]
            if duration is not None and duration != item.metadata.get("duration_ms"):
                raise ValueError("TRANSFER_MEDIA_DURATION_MISMATCH")
            prepared.append(item)
            total += len(item.data)
            if total > _MAX_EXPANDED_BYTES:
                raise ValueError("TRANSFER_MEDIA_TOTAL_TOO_LARGE")
        if set(references) - seen:
            raise ValueError("TRANSFER_MEDIA_DESCRIPTOR_MISSING")
        return prepared

    def _prepare_media_item(self, user_id, descriptor):
        path, data = descriptor["path"], descriptor.get("data")
        if not isinstance(path, str) or _MEDIA_PATH.fullmatch(path) is None:
            raise ValueError("INVALID_TRANSFER_MEDIA_PATH")
        if not isinstance(data, bytes) or sha256(data).hexdigest() != descriptor["sha256"]:
            raise ValueError("TRANSFER_MEDIA_CHECKSUM_MISMATCH")
        return self.media_store.prepare_transfer(
            media_ref=MediaRef(media_id=descriptor["id"]),
            owner_user_id=user_id,
            data=data,
            kind=descriptor["kind"],
            mime_type=descriptor["mime_type"],
            duration_ms=descriptor.get("duration_ms"),
        )

    @staticmethod
    def _documents(user_id, payload):
        documents, vector_ids = [], {}
        for row in payload.get("memories", []):
            if row["subject_user_id"] != user_id:
                raise ValueError("TRANSFER_MEMORY_OWNER_MISMATCH")
            chunks = row.get("chunks") or [{"chunk_text": row["content"], "chunk_type": "content"}]
            occurrences = {}
            for index, chunk in enumerate(chunks):
                key = (chunk["chunk_text"], chunk.get("chunk_type", "content"))
                occurrence = occurrences.get(key, 0)
                occurrences[key] = occurrence + 1
                document = _vector_document(user_id, row, index, chunk, occurrence)
                vector_ids[(row["id"], index)] = document.id
                documents.append(document)
        return documents, vector_ids

    @staticmethod
    def _validate_embeddings(vectors, count):
        if len(vectors) != count:
            raise ValueError("TRANSFER_EMBEDDING_COUNT_MISMATCH")
        for vector in vectors:
            if not vector or not all(type(value) in (float, int) and math.isfinite(value) for value in vector):
                raise ValueError("TRANSFER_EMBEDDING_INVALID")

    @classmethod
    def _validate_snapshot(cls, user_id, previous):
        identities = set()
        for row in previous:
            if row["id"] in identities or row["metadata"].get("user_id") != user_id:
                raise ValueError("TRANSFER_VECTOR_SNAPSHOT_OWNER_MISMATCH")
            cls._validate_embeddings([row["embedding"]], 1)
            identities.add(row["id"])


class TransferProjectionPlan:
    """SQL 提交前 publish；失败时 rollback，成功后 finish 释放恢复材料。

    所有调用都在用户迁移准入栅栏内，SQL 与 Chroma 不承诺跨进程崩溃原子性。
    """

    def __init__(
        self,
        vector_store,
        media_store,
        user_id,
        mode,
        scope,
        media,
        previous,
        documents,
        embeddings,
        vector_ids,
    ):
        self.vector_ids = vector_ids
        self._vector_store, self._media_store = vector_store, media_store
        self._user_id, self._mode, self._scope = user_id, mode, scope
        self._media, self._previous = media, previous
        self._documents, self._embeddings = documents, embeddings
        self._created_media = []
        self._vectors_touched = False
        self._started = False
        self._finished = False

    def publish(self):
        if self._started or self._finished:
            raise RuntimeError("TRANSFER_PROJECTION_ALREADY_PUBLISHED")
        self._started = True
        for item in self._media:
            if self._media_store.publish_transfer(item):
                self._created_media.append(item)
        if self._scope not in {"memory", "all"} or not self._vector_store.enabled:
            return
        if self._mode == "replace":
            self._vectors_touched = True
            self._vector_store.delete_user_records_strict(self._user_id)
        active = set(self.vector_ids.values())
        pairs = [(doc, vector) for doc, vector in zip(self._documents, self._embeddings) if doc.id in active]
        for batch in _batches(pairs):
            self._vectors_touched = True
            self._upsert([doc for doc, _ in batch], [vector for _, vector in batch])

    def _upsert(self, documents, embeddings):
        ids = [doc.id for doc in documents]
        actual = self._vector_store.upsert_documents(documents, ids, embeddings=embeddings)
        if actual != ids:
            raise RuntimeError("TRANSFER_VECTOR_PUBLISH_INCOMPLETE")

    def rollback(self):
        """向量恢复原 embedding；文件仅清理本次实际新建项，失败允许再次重试。"""
        if self._finished:
            raise RuntimeError("TRANSFER_PROJECTION_ALREADY_FINISHED")
        failures = []
        if self._vectors_touched:
            try:
                self._restore_vectors()
            except Exception as error:
                failures.append(error)
            else:
                self._vectors_touched = False
        for item in list(reversed(self._created_media)):
            try:
                self._media_store.rollback_transfer(item)
            except Exception as error:
                failures.append(error)
            else:
                self._created_media.remove(item)
        if failures:
            raise RuntimeError("TRANSFER_PROJECTION_ROLLBACK_FAILED") from failures[0]

    def _restore_vectors(self):
        self._vector_store.delete_user_records_strict(self._user_id)
        for batch in _batches(self._previous):
            self._upsert(
                [Document(row["content"], row["metadata"], id=row["id"]) for row in batch],
                [row["embedding"] for row in batch],
            )

    def finish(self):
        if not self._started:
            raise RuntimeError("TRANSFER_PROJECTION_NOT_PUBLISHED")
        self._finished = True
        self._previous.clear()
        self._created_media.clear()
        self._documents.clear()
        self._embeddings.clear()
