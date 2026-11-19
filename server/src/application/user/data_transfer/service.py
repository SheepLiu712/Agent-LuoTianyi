"""本人迁移用例：校验预览、暂停交互、备份、事务接纳与显式记忆提取。"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict

from src.infrastructure.data_transfer import decode_import, encode_archive, render_readable
from src.infrastructure.persistence.user_data_transfer import dump_json
from src.utils.owned_operation import complete_owned

from .identity import bind_import


class TransferCommitError(RuntimeError):
    def __init__(self, code, *, backup_id=None, rollback_error=None):
        self.code = code
        self.backup_id = backup_id
        self.rollback_error = rollback_error
        super().__init__(code)


class UserDataTransferService:
    def __init__(self, *, repository, projections, vectors, interactions, redis, workspace, characters, extract=None):
        self._repository = repository
        self._projections = projections
        self._vectors = vectors
        self._interactions = interactions
        self._redis = redis
        self._workspace = workspace
        self._characters = tuple(characters)
        self._extract = extract
        self._busy = set()

    async def export(self, user_id, *, scope="all", format="zip"):
        self._validate_scope(scope)
        if format not in {"zip", "markdown", "txt"}:
            raise ValueError("UNSUPPORTED_EXPORT_FORMAT")
        return await complete_owned(self._export_owned(user_id, scope, format))

    async def _export_owned(self, user_id, scope, format):
        self._claim(user_id)
        token = None
        try:
            token = await self._interactions.begin_user_data_transfer(user_id)
            payload, files = await self._snapshot(user_id, scope)
            data = (
                await asyncio.to_thread(encode_archive, payload, files)
                if format == "zip"
                else await asyncio.to_thread(render_readable, payload, format)
            )
            return data
        finally:
            if token is not None:
                await self._interactions.end_user_data_reset(user_id, token)
            self._busy.discard(user_id)

    async def preview(self, user_id, data, *, source_format="auto", scope="all", character_id="luotianyi"):
        self._validate_scope(scope)
        if character_id not in self._characters:
            raise ValueError("CHARACTER_NOT_ENABLED")
        payload, files = await asyncio.to_thread(
            decode_import, data, source_format=source_format, character_id=character_id, scope=scope
        )
        # 完整语义校验在任何写入之前进行；不触碰聊天生命周期。
        bound = bind_import(payload, files, user_id, self._characters)
        identity = await asyncio.to_thread(
            self._workspace.put,
            "previews",
            user_id,
            data,
            {"source_format": source_format, "scope": scope, "character_id": character_id},
        )
        return {
            "preview_id": identity,
            "source_format": payload.get("source_format", "native"),
            "scope": payload["scope"],
            "counts": self._counts(bound),
            "warnings": payload.get("warnings", []),
        }

    async def commit(self, user_id, preview_id, *, mode="merge", confirm_replace=False, extract_memories=False):
        if mode not in {"merge", "replace"}:
            raise ValueError("INVALID_IMPORT_MODE")
        if mode == "replace" and not confirm_replace:
            raise ValueError("REPLACE_CONFIRMATION_REQUIRED")
        return await complete_owned(self._commit_owned(user_id, preview_id, mode, extract_memories))

    async def _commit_owned(self, user_id, preview_id, mode, extract_memories):
        self._claim(user_id)
        token = None
        try:
            previous = await self._previous_result(user_id, preview_id)
            retry_extraction = (
                previous is not None
                and previous.get("committed")
                and previous.get("extraction", {}).get("status") in {"failed", "unavailable"}
                and extract_memories
            )
            if previous is not None and not retry_extraction:
                return previous
            data, info = await asyncio.to_thread(self._workspace.get, "previews", preview_id, user_id)
            payload, files = await asyncio.to_thread(
                decode_import,
                data,
                source_format=info["source_format"],
                scope=info["scope"],
                character_id=info["character_id"],
            )
            bound = bind_import(payload, files, user_id, self._characters)
            token = await self._interactions.begin_user_data_transfer(user_id)
            if retry_extraction:
                result = previous
            else:
                backup_id = await self._backup(user_id, bound["scope"]) if mode == "replace" else None
                # 破坏性写入前先持久化备份位置；失败或响应丢失仍能由同预览取回。
                pending = {"success": False, "committed": False, "failed_phase": "commit", "backup_id": backup_id}
                try:
                    await asyncio.to_thread(self._workspace.save_result, preview_id, user_id, pending)
                except OSError as error:
                    raise TransferCommitError("TRANSFER_RECEIPT_UNAVAILABLE", backup_id=backup_id) from error
                try:
                    result = await self._apply(user_id, bound, mode, backup_id, preview_id, extract_memories)
                except Exception as error:
                    pending.update(error=type(error).__name__, rollback_error=getattr(error, "rollback_error", None))
                    await self._cache_result(user_id, preview_id, pending)
                    return pending
                result.update(
                    extraction={"status": "failed" if extract_memories else "not_requested", "memories": 0},
                    warnings=bound.get("warnings", []),
                )
                await self._cache_result(user_id, preview_id, result)
            result["extraction"] = await self._extraction(user_id, bound, extract_memories)
            result["warnings"] = bound.get("warnings", [])
            try:
                await asyncio.to_thread(self._repository.update_receipt, user_id, preview_id, result)
            except Exception as error:
                result["warnings"].append(f"最终提取状态暂未保存，可安全重试：{type(error).__name__}")
            await self._cache_result(user_id, preview_id, result)
            return result
        finally:
            if token is not None:
                await self._interactions.end_user_data_reset(user_id, token)
            self._busy.discard(user_id)

    async def _previous_result(self, user_id, preview_id):
        authoritative = await asyncio.to_thread(self._repository.receipt, user_id, preview_id)
        try:
            cached = await asyncio.to_thread(self._workspace.result, preview_id, user_id)
        except (OSError, ValueError):
            if authoritative is None:
                raise
            cached = None
        if authoritative is not None:
            # 文件缓存只能补充提示，提交与提取状态始终服从 SQL 事务回执。
            warnings = [*authoritative.get("warnings", []), *(cached or {}).get("warnings", [])]
            authoritative["warnings"] = list(dict.fromkeys(warnings))
            return authoritative
        return cached

    async def _cache_result(self, user_id, preview_id, result):
        try:
            await asyncio.to_thread(self._workspace.save_result, preview_id, user_id, result)
        except OSError:
            result.setdefault("warnings", []).append("结果文件未能保存；提交状态和备份编号可通过同一预览重试查询。")

    async def _apply(self, user_id, payload, mode, backup_id, preview_id, extract_memories):
        plan = await self._projections.prepare(user_id, payload, mode)
        try:
            imported, skipped = await asyncio.to_thread(
                self._repository.apply,
                user_id,
                payload,
                mode=mode,
                vector_ids=plan.vector_ids,
                publish=plan.publish,
                receipt={"preview_id": preview_id, "backup_id": backup_id, "extract_memories": extract_memories},
            )
        except BaseException as error:
            rollback_error = None
            try:
                await asyncio.to_thread(plan.rollback)
            except Exception as rollback:
                rollback_error = type(rollback).__name__
            raise TransferCommitError(
                "TRANSFER_COMMIT_FAILED", backup_id=backup_id, rollback_error=rollback_error
            ) from error
        # SQL 已提交，缓存失效/清理失败也不能误称未提交或再次执行 replace。
        warnings = payload.setdefault("warnings", [])
        try:
            await asyncio.to_thread(self._redis.clear_user, user_id)
            await asyncio.to_thread(plan.finish)
        except Exception as error:
            warnings.append(f"数据已提交，缓存刷新或旧投影清理失败：{type(error).__name__}")
        return {
            "success": True,
            "committed": True,
            "failed_phase": None,
            "imported": imported,
            "skipped": skipped,
            "backup_id": backup_id,
        }

    async def _snapshot(self, user_id, scope):
        if scope in {"memory", "all"}:
            vectors = await asyncio.to_thread(self._vectors.list_user_documents, user_id)
            await asyncio.to_thread(self._repository.backfill_legacy, user_id, vectors)
        payload = await asyncio.to_thread(self._repository.snapshot, user_id, scope)
        files = await asyncio.to_thread(self._projections.export_media, user_id, payload)
        return payload, files

    async def _backup(self, user_id, scope):
        payload, files = await self._snapshot(user_id, scope)
        data = await asyncio.to_thread(encode_archive, payload, files)
        identity = await asyncio.to_thread(self._workspace.put, "backups", user_id, data)
        await asyncio.to_thread(self._workspace.get, "backups", identity, user_id)
        return identity

    async def backup(self, user_id, backup_id):
        data, _ = await asyncio.to_thread(self._workspace.get, "backups", backup_id, user_id)
        return data

    async def _extraction(self, user_id, payload, requested):
        empty = {"status": "not_requested", "memories": 0}
        if not requested or payload.get("source_format", "native") == "native":
            return empty
        if self._extract is None:
            return {"status": "unavailable", "memories": 0}
        by_character = defaultdict(list)
        for row in payload["conversations"]:
            by_character[row["character_id"]].append(row)
        count = 0
        try:
            for character_id, rows in by_character.items():
                for batch in self._batches(rows):
                    digest = hashlib.sha256(dump_json(batch).encode("utf-8")).hexdigest()
                    count += await self._extract(user_id, character_id, digest, batch)
        except Exception as error:
            return {"status": "failed", "memories": count, "error": type(error).__name__}
        return {"status": "succeeded", "memories": count}

    @staticmethod
    def _batches(rows):
        batch, length = [], 0
        for row in rows:
            content = row["content"]
            for offset in range(0, max(len(content), 1), 8000):
                item = {"uuid": row["uuid"], "source": row["source"], "content": content[offset : offset + 8000]}
                if batch and length + len(item["content"]) > 12000:
                    yield batch
                    batch, length = [], 0
                batch.append(item)
                length += len(item["content"])
        if batch:
            yield batch

    def _claim(self, user_id):
        if user_id in self._busy:
            raise RuntimeError("USER_DATA_TRANSFER_IN_PROGRESS")
        self._busy.add(user_id)

    @staticmethod
    def _validate_scope(scope):
        if scope not in {"chat", "memory", "all"}:
            raise ValueError("INVALID_TRANSFER_SCOPE")

    @staticmethod
    def _counts(payload):
        return {key: len(payload[key]) for key in ("conversations", "memories", "media")}
