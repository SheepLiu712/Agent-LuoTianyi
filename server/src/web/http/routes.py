from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from src.application.admin import get_admin_shell
from src.utils.logger import get_logger

from .data_transfer_routes import register_data_transfer_routes
from .runtime_access import require_bearer_token, runtime_not_ready_detail
from .types import (
    AgreementAcceptRequest,
    AutoLoginRequest,
    AvatarUpdateRequest,
    CallCapabilityQuery,
    CallCapabilityResponse,
    DynamicCommentCreateRequest,
    DynamicCommentListQuery,
    DynamicCommentListRequest,
    DynamicCreateRequest,
    DynamicListQuery,
    DynamicListRequest,
    DynamicReadMarkRequest,
    DynamicUnreadQuery,
    DynamicUnreadRequest,
    HistoryQuery,
    ImageRequest,
    LoginRequest,
    PreferenceGetRequest,
    PreferenceOverwriteRequest,
    RegisterRequest,
    ResetAccountRequest,
    UserDataResetRequest,
)

if TYPE_CHECKING:
    from src.server_runtime import ServerRuntime

logger = get_logger(__name__)
router = APIRouter()


def get_runtime() -> "ServerRuntime":
    runtime = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail=runtime_not_ready_detail())
    return runtime


register_data_transfer_routes(router, get_runtime)


@router.get("/auth/public_key")
async def get_public_key(server_runtime: "ServerRuntime" = Depends(get_runtime)):
    return {"public_key": server_runtime.user_interface.get_public_key_pem()}


@router.get("/auth/agreement/policy")
async def get_agreement_policy(server_runtime: "ServerRuntime" = Depends(get_runtime)):
    return JSONResponse(
        {"require_acceptance": server_runtime.agreement_service.require_acceptance},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/auth/agreement")
async def get_agreement(server_runtime: "ServerRuntime" = Depends(get_runtime)):
    agreement_doc = server_runtime.agreement_service.get_current()
    return JSONResponse(
        {
            "version": agreement_doc.version,
            "title": agreement_doc.title,
            "format": agreement_doc.format,
            "blocks": agreement_doc.blocks,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/auth/agreement/accept")
async def accept_agreement(
    req: AgreementAcceptRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
    request: Request = None,
):
    return await server_runtime.user_interface.accept_agreement(req, server_runtime, request)


@router.get("/llm/client-model-types")
async def get_client_model_types(server_runtime: "ServerRuntime" = Depends(get_runtime)):
    return {"types": server_runtime.llm_service.get_client_model_types()}


@router.post("/auth/auto_login")
async def auto_login(
    req: AutoLoginRequest,
    background_tasks: BackgroundTasks,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
    request: Request = None,
):
    logger.info("Auto login request: %s", req.username)
    return await server_runtime.user_interface.auto_login(req, background_tasks, server_runtime, request)


@router.post("/auth/register")
async def register(
    req: RegisterRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
    request: Request = None,
):
    logger.info("Register request for username=%s", req.username)
    return await server_runtime.user_interface.register(req, server_runtime, request)


@router.post("/auth/reset_account")
async def reset_account(
    req: ResetAccountRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
    request: Request = None,
):
    logger.info("Reset account request for username=%s", req.new_username)
    return await server_runtime.user_interface.reset_account(req, server_runtime, request)


@router.post("/user/data/reset")
async def reset_user_data(
    req: UserDataResetRequest,
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    return await server_runtime.user_interface.reset_user_data(req, token, server_runtime)


@router.post("/auth/login")
async def login(
    req: LoginRequest,
    background_tasks: BackgroundTasks,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
    request: Request = None,
):
    logger.info("Login request: %s", req.username)
    return await server_runtime.user_interface.login(req, background_tasks, server_runtime, request)


@router.get("/avatars")
async def get_avatars(
    username: str,
    authorization: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    snapshot = await server_runtime.user_interface.get_avatars(username, require_bearer_token(authorization))
    headers = {
        "ETag": f'"{snapshot["revision"]}"',
        "Cache-Control": "no-store",
        "X-Avatar-Token": snapshot["sync_token"],
    }
    if if_none_match and if_none_match.strip('"') == snapshot["revision"]:
        return Response(status_code=304, headers=headers)
    return JSONResponse(snapshot, headers=headers)


@router.put("/avatars/{side}")
async def put_avatar(
    side: Literal["user", "agent"],
    username: str,
    request: AvatarUpdateRequest,
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    snapshot = await server_runtime.user_interface.put_avatar(
        username, require_bearer_token(authorization), side, request.image
    )
    return JSONResponse(snapshot, headers={"Cache-Control": "no-store", "ETag": f'"{snapshot["revision"]}"'})


@router.post("/preference/get")
async def get_preference(
    req: PreferenceGetRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    return await server_runtime.user_interface.get_preference(req, server_runtime)


@router.post("/preference/overwrite")
async def overwrite_preference(
    req: PreferenceOverwriteRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    return await server_runtime.user_interface.overwrite_preference(req, server_runtime)


@router.get("/history")
async def get_history(
    request: HistoryQuery = Depends(),
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    logger.info("Server received: Get history request from %s", request.username)
    token = require_bearer_token(authorization)
    return await server_runtime.user_interface.get_history(
        request.username,
        token,
        request.count,
        request.end_index,
    )


@router.get("/call/capability", response_model=CallCapabilityResponse)
async def get_call_capability(
    request: CallCapabilityQuery = Depends(),
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    return await server_runtime.user_interface.get_call_capability(token, request.character_id, server_runtime)


@router.get("/media/audio/{message_uuid}")
async def get_audio(
    message_uuid: str,
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    return await server_runtime.user_interface.get_audio(token, message_uuid)


@router.get("/dynamics")
async def list_dynamics(
    request: DynamicListQuery = Depends(),
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    req = DynamicListRequest(
        username=request.username,
        token=token,
        limit=request.limit,
        cursor=request.cursor,
    )
    return await server_runtime.user_interface.list_dynamics(req, server_runtime)


@router.post("/dynamics")
async def create_dynamic(
    request: DynamicCreateRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    return await server_runtime.user_interface.create_dynamic(request, server_runtime)


@router.get("/dynamics/unread")
async def get_dynamic_unread(
    request: DynamicUnreadQuery = Depends(),
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    req = DynamicUnreadRequest(username=request.username, token=token)
    return await server_runtime.user_interface.get_dynamic_unread(req, server_runtime)


@router.post("/dynamics/read")
async def mark_dynamic_read(
    request: DynamicReadMarkRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    return await server_runtime.user_interface.mark_dynamic_read(request, server_runtime)


@router.get("/dynamics/{dynamic_id}/comments")
async def list_dynamic_comments(
    dynamic_id: str,
    request: DynamicCommentListQuery = Depends(),
    authorization: str | None = Header(default=None),
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    req = DynamicCommentListRequest(
        username=request.username,
        token=token,
        limit=request.limit,
        cursor=request.cursor,
    )
    return await server_runtime.user_interface.list_dynamic_comments(dynamic_id, req, server_runtime)


@router.post("/dynamics/{dynamic_id}/comments")
async def create_dynamic_comment(
    dynamic_id: str,
    request: DynamicCommentCreateRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    return await server_runtime.user_interface.create_dynamic_comment(dynamic_id, request, server_runtime)


@router.post("/get_image")
async def get_image(
    request: ImageRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    logger.info("Get image request from %s for %s", request.username, request.uuid)
    return await server_runtime.user_interface.get_image(request)


@router.post("/update_image_client_path")
async def update_image_client_path(
    request: ImageRequest,
    server_runtime: "ServerRuntime" = Depends(get_runtime),
):
    logger.info("Update image client path request from %s for %s", request.username, request.uuid)
    return await server_runtime.user_interface.update_image_client_path(request, server_runtime)
