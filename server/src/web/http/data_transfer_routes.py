"""聊天与记忆迁移 HTTP 边界；本人 Bearer 鉴权先于上传读取。"""

from __future__ import annotations

import asyncio

from fastapi import Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, StrictBool

from src.application.user.data_transfer import TransferCommitError
from src.infrastructure.data_transfer import MAX_UPLOAD_BYTES, TransferFormatError
from src.infrastructure.persistence.user_data_transfer import TransferConflict
from src.web.http.runtime_access import require_bearer_token


class ImportCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    mode: str = "merge"
    confirm_replace: StrictBool = False
    extract_memories: StrictBool = False


async def _owner(runtime, authorization):
    token = require_bearer_token(authorization)
    user_id = await asyncio.to_thread(runtime.database_manager.credential_service.authenticate_message_token, token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
    service = getattr(runtime, "user_data_transfer_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="数据迁移尚未就绪")
    return user_id, service


async def _invoke(operation):
    try:
        return await operation
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": str(error)}) from error
    except (TransferFormatError, TransferConflict, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, ValueError) else "INVALID_TRANSFER_DATA"
        raise HTTPException(status_code=400, detail={"code": code[:200]}) from error
    except TransferCommitError as error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": error.code,
                "backup_id": error.backup_id,
                "committed": False,
                "failed_phase": "commit",
                "rollback_error": error.rollback_error,
            },
        ) from error
    except RuntimeError as error:
        if str(error).startswith(("USER_", "STAGE_MANAGER_")):
            raise HTTPException(status_code=409, detail={"code": str(error), "retryable": True}) from error
        raise HTTPException(status_code=503, detail={"code": "TRANSFER_STORAGE_UNAVAILABLE"}) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail={"code": "TRANSFER_STORAGE_UNAVAILABLE"}) from error


def _download(data, filename, content_type):
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _read_upload(request):
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="无效的上传大小") from error
        if size < 0 or size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="迁移文件不能超过 64 MiB")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="迁移文件不能超过 64 MiB")
        data.extend(chunk)
    return bytes(data)


def register_data_transfer_routes(router, get_runtime):
    from fastapi import Depends

    @router.get("/user/data/export")
    async def export_user_data(
        scope: str = "all",
        format: str = "zip",
        authorization: str | None = Header(default=None),
        runtime=Depends(get_runtime),
    ):
        owner, service = await _owner(runtime, authorization)
        data = await _invoke(service.export(owner, scope=scope, format=format))
        extension = {"zip": "zip", "markdown": "md", "txt": "txt"}[format]
        content_type = {"zip": "application/zip", "markdown": "text/markdown", "txt": "text/plain"}[format]
        return _download(data, f"agentluo-{scope}.{extension}", content_type)

    @router.post("/user/data/import/preview")
    async def preview_import(
        request: Request,
        source_format: str = "auto",
        scope: str = "all",
        character_id: str = "luotianyi",
        authorization: str | None = Header(default=None),
        runtime=Depends(get_runtime),
    ):
        owner, service = await _owner(runtime, authorization)
        data = await _read_upload(request)
        return await _invoke(
            service.preview(owner, data, source_format=source_format, scope=scope, character_id=character_id)
        )

    @router.post("/user/data/import/commit")
    async def commit_import(
        body: ImportCommitRequest,
        authorization: str | None = Header(default=None),
        runtime=Depends(get_runtime),
    ):
        owner, service = await _owner(runtime, authorization)
        return await _invoke(service.commit(owner, **body.model_dump()))

    @router.get("/user/data/backups/{backup_id}")
    async def download_backup(
        backup_id: str,
        authorization: str | None = Header(default=None),
        runtime=Depends(get_runtime),
    ):
        owner, service = await _owner(runtime, authorization)
        data = await _invoke(service.backup(owner, backup_id))
        return _download(data, "agentluo-before-replace.zip", "application/zip")
