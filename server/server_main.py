from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import sys

# Ensure src is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(current_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.system.user_interface.types import (
    RegisterRequest,
    LoginRequest,
    AutoLoginRequest,
    HistoryQuery,
    ImageRequest,
    ResetAccountRequest,
    WSEventType,
    PreferenceGetRequest,
    PreferenceOverwriteRequest,
    DynamicListRequest,
    DynamicListQuery,
    DynamicCreateRequest,
    DynamicCommentListRequest,
    DynamicCommentListQuery,
    DynamicCommentCreateRequest,
    DynamicUnreadRequest,
    DynamicUnreadQuery,
    DynamicReadMarkRequest,
)
from src.system.user_interface.websocket_service import ChatEventAcceptance, WebSocketConnection
from src.system.admin.admin_interface import router as admin_router
from src.system.admin import get_admin_shell, init_admin_shell, shutdown_admin_shell

from src.utils.helpers import load_config
from src.utils.logger import get_logger, install_access_log_filter

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime

logger = get_logger("server_main")
config = load_config("config/config.json")


@asynccontextmanager
async def startup_event(app: FastAPI):
    install_access_log_filter()
    admin_shell = await init_admin_shell(root_dir=current_dir)
    logger.info("AdminShell 初始化完成，正在校验配置并启动系统运行时")
    runtime_status = await admin_shell.runtime_supervisor.start()
    if runtime_status.get("running"):
        logger.info("配置校验通过，SystemRuntime 已自动启动")
    else:
        logger.warning(
            "SystemRuntime 未自动启动: state=%s, error=%s",
            runtime_status.get("state"),
            runtime_status.get("last_error"),
        )
    try:
        yield
    finally:
        logger.info("正在关闭 AdminShell 和系统运行时")
        await shutdown_admin_shell()
        logger.info("AdminShell 已关闭")


def runtime_not_ready_detail() -> dict:
    status = get_admin_shell().runtime_supervisor.public_status()
    return {
        "ok": False,
        "code": "SYSTEM_RUNTIME_NOT_READY",
        "message": "服务端尚未完成配置或系统运行时未启动",
        "runtime": status,
    }


def get_runtime():
    runtime = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        raise HTTPException(status_code=503, detail=runtime_not_ready_detail())
    return runtime


def require_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="消息令牌缺失")
    scheme, separator, token = authorization.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not token
        or any(character.isspace() for character in token)
    ):
        raise HTTPException(status_code=401, detail="无效的 Authorization 请求头")
    return token


app = FastAPI(lifespan=startup_event)
app.include_router(admin_router)

admin_ui_build = os.path.join(current_dir, "admin_ui", "admin_static")
admin_ui_assets = os.path.join(admin_ui_build, "assets")
project_plan_path = os.path.join(
    os.path.dirname(current_dir),
    "docs",
    "项目计划书",
    "AgentLuo项目计划书.html",
)
if os.path.isdir(admin_ui_assets):
    app.mount("/admin/assets", StaticFiles(directory=admin_ui_assets), name="admin-assets")

# ——————————————————————————————————————————————————————————————————
# 主要的 API 路由定义
# ——————————————————————————————————————————————————————————————————

@app.get("/admin")
@app.get("/admin/{path:path}")
async def admin_index(path: str = ""):
    index_path = os.path.join(admin_ui_build, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(
        "<h1>AgentLuo Server Console</h1>"
        "<p>Admin UI has not been built yet. Run <code>cd server/admin_ui && npm install && npm run build</code>.</p>"
    )


@app.get("/project-plan", include_in_schema=False)
@app.get("/project-plan/", include_in_schema=False)
async def project_plan():
    if not os.path.isfile(project_plan_path):
        raise HTTPException(status_code=404, detail="项目计划书页面尚未生成")
    return FileResponse(project_plan_path, media_type="text/html")

@app.websocket("/chat_ws")
async def chat_ws(websocket: WebSocket):
    try:
        await websocket.accept()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected before accept on /chat_ws")
        return

    system_runtime: "SystemRuntime" = get_admin_shell().runtime_supervisor.runtime
    if system_runtime is None:
        try:
            await websocket.send_json(
                {
                    "type": "system_not_ready",
                    "payload": runtime_not_ready_detail(),
                }
            )
            await websocket.close(code=1013)
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected before system_not_ready on /chat_ws")
        return

    logger.info("WebSocket client connected to /chat_ws")
    websocket_service = system_runtime.websocket_service  # WebSocketService 实例
    gcsm = system_runtime.gcsm  # 全局聊天流管理器实例
    try:
        await websocket_service.send_system_ready_event(websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected before system_ready on /chat_ws")
        return

    ws_connection = WebSocketConnection(websocket=websocket, user_uuid=None, user_name=None)
    try:
        authenticated = await ws_connection.auth(
            websocket_service,
            system_runtime.database_manager,
        )
        if not authenticated:
            return
        chat_stream = await gcsm.get_or_register_chat_stream(
            ws_connection, system_runtime=system_runtime
        )  # 根据ws连接获取对应的聊天流实例，内部会根据用户UUID进行管理
        while True:
            event = await websocket_service.try_recv_client_msg(ws_connection)
            if event is None:
                continue

            if event.event_type == WSEventType.HB_PING.value:
                await websocket_service.handle_ping_event(ws_connection, event)
                continue

            if websocket_service.is_chat_related_event(event):
                acceptance = websocket_service.try_accept_chat_event(
                    ws_connection,
                    event,
                    chat_stream,
                )
                if acceptance == ChatEventAcceptance.DUPLICATE:
                    await websocket_service.send_duplicate_ack_event(ws_connection, event)
                    continue
                if acceptance == ChatEventAcceptance.BAD_MESSAGE:
                    await websocket_service.send_nack_event(
                        ws_connection,
                        event,
                        code="BAD_MESSAGE",
                        message="chat event payload is invalid",
                        retryable=False,
                    )
                    continue
                if acceptance == ChatEventAcceptance.UNSUPPORTED:
                    await websocket_service.send_nack_event(
                        ws_connection,
                        event,
                        code="UNSUPPORTED_EVENT",
                        message="chat event type is not supported",
                        retryable=False,
                    )
                    continue
                if acceptance == ChatEventAcceptance.OVERLOADED:
                    await websocket_service.send_nack_event(
                        ws_connection,
                        event,
                        code="OVERLOADED",
                        message="chat ingress queue is full",
                        retryable=True,
                    )
                    continue
                await websocket_service.send_ack_event(ws_connection, event)
    except WebSocketDisconnect:
        gcsm.ws_lost_connection(ws_connection)
        logger.info("WebSocket client disconnected from /chat_ws")
    except Exception as e:
        gcsm.ws_lost_connection(ws_connection)
        logger.error(f"Error in /chat_ws: {e}")


@app.get("/auth/public_key")
async def get_public_key(system_runtime = Depends(get_runtime)):
    """
    获取用户登录加密密码时使用的公钥。客户端在登录或注册时使用该公钥加密密码后发送给服务器。
    """
    return {"public_key": system_runtime.user_interface.get_public_key_pem()}


@app.post("/auth/auto_login")
async def auto_login(
    req: AutoLoginRequest,
    background_tasks: BackgroundTasks,
    system_runtime = Depends(get_runtime),
    request: Request = None,
):
    """
    自动登录：用户提供用户名和上一次分配的自动登录 token，验证通过后发放新的 token。

    请求参数：
    - req.username: 用户名
    - req.token: 上一次分配的自动登录 token
    返回值：
    - 成功：{"message": "登录成功", "user_id": req.username, "token": new_token}
    - 失败：HTTP 401 错误，{"detail": "登录失败，自动登录验证未通过"}
    """
    logger.info(f"Auto login request: {req.username}")
    return await system_runtime.user_interface.auto_login(
        req, background_tasks, system_runtime, request
    )


@app.post("/auth/register")
async def register(
    req: RegisterRequest,
    system_runtime = Depends(get_runtime),
    request: Request = None,
):
    """
    用户注册接口。用户提供用户名、密码和邀请码进行注册。

    请求参数：
    - req.username: 用户名
    - req.password: 加密后的密码（Base64 编码）
    - req.invite_code: 邀请码
    返回值：
    - 成功：{"message": "注册成功", "user_id": req.username}
    - 失败：HTTP 400 错误，{"detail": "注册失败，失败原因"}
    """
    logger.info("Register request for username=%s", req.username)
    return await system_runtime.user_interface.register(
        req, system_runtime, request
    )


@app.post("/auth/reset_account")
async def reset_account(
    req: ResetAccountRequest,
    system_runtime = Depends(get_runtime),
    request: Request = None,
):
    """以邀请码重置账号的用户名和密码。

    请求参数：
    - req.invite_code: 已使用过的邀请码（关联到要重置的用户）
    - req.new_username: 新的用户名
    - req.new_password: 新的密码（Base64 加密后）
    返回值：
    - 成功：{"message": "重置成功"}
    - 失败：HTTP 400 错误，{"detail": "失败原因"}
    """
    logger.info("Reset account request for username=%s", req.new_username)
    return await system_runtime.user_interface.reset_account(
        req, system_runtime, request
    )


@app.post("/auth/login")
async def login(
    req: LoginRequest,
    background_tasks: BackgroundTasks,
    system_runtime = Depends(get_runtime),
    request: Request = None,
):
    """
    用户登录接口。用户提供用户名和密码进行登录。

    请求参数：
    - req.username: 用户名
    - req.password: 加密后的密码（Base64 编码）
    返回值：
    - 成功：{"login_token": auth_token, "message_token": message_token, "user_id": req.username}
    - 失败：HTTP 401 错误，{"detail": "用户名或密码错误"}
    """
    logger.info(f"Login request: {req.username}")
    return await system_runtime.user_interface.login(
        req, background_tasks, system_runtime, request
    )


@app.post("/preference/get")
async def get_preference(
    req: PreferenceGetRequest,
    system_runtime = Depends(get_runtime),
):
    """获取偏好设置：委托到 UserInterface。"""
    return await system_runtime.user_interface.get_preference(req, system_runtime)


@app.post("/preference/overwrite")
async def overwrite_preference(
    req: PreferenceOverwriteRequest,
    system_runtime = Depends(get_runtime),
):
    """覆盖偏好设置：委托到 UserInterface。"""
    return await system_runtime.user_interface.overwrite_preference(req, system_runtime)


@app.get("/history")
async def get_history(
    request: HistoryQuery = Depends(),
    authorization: str | None = Header(default=None),
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    """获取聊天历史：委托到 UserInterface。"""
    logger.info(f"Server received: Get history request from {request.username}")
    token = require_bearer_token(authorization)
    return await system_runtime.user_interface.get_history(
        request.username, token, request.count, request.end_index, system_runtime
    )


@app.get("/dynamics")
async def list_dynamics(
    request: DynamicListQuery = Depends(),
    authorization: str | None = Header(default=None),
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    req = DynamicListRequest(
        username=request.username,
        token=token,
        limit=request.limit,
        cursor=request.cursor,
    )
    return await system_runtime.user_interface.list_dynamics(req, system_runtime)


@app.post("/dynamics")
async def create_dynamic(
    request: DynamicCreateRequest,
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    return await system_runtime.user_interface.create_dynamic(request, system_runtime)


@app.get("/dynamics/unread")
async def get_dynamic_unread(
    request: DynamicUnreadQuery = Depends(),
    authorization: str | None = Header(default=None),
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    req = DynamicUnreadRequest(username=request.username, token=token)
    return await system_runtime.user_interface.get_dynamic_unread(req, system_runtime)


@app.post("/dynamics/read")
async def mark_dynamic_read(
    request: DynamicReadMarkRequest,
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    return await system_runtime.user_interface.mark_dynamic_read(request, system_runtime)


@app.get("/dynamics/{dynamic_id}/comments")
async def list_dynamic_comments(
    dynamic_id: str,
    request: DynamicCommentListQuery = Depends(),
    authorization: str | None = Header(default=None),
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    token = require_bearer_token(authorization)
    req = DynamicCommentListRequest(
        username=request.username,
        token=token,
        limit=request.limit,
        cursor=request.cursor,
    )
    return await system_runtime.user_interface.list_dynamic_comments(dynamic_id, req, system_runtime)


@app.post("/dynamics/{dynamic_id}/comments")
async def create_dynamic_comment(
    dynamic_id: str,
    request: DynamicCommentCreateRequest,
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    return await system_runtime.user_interface.create_dynamic_comment(dynamic_id, request, system_runtime)


@app.post("/get_image")
async def get_image(
    request: ImageRequest,
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    """
    获取图片接口。用户提供图片的服务器路径，服务器返回图片二进制数据。

    请求参数：
    - request.username: 用户名
    - request.token: 认证 token
    - request.uuid: 图片在服务器上的uuid
    返回值：
    - 成功：图片的二进制数据，Content-Type 根据图片类型设置
    - 失败：HTTP 400 错误，{"detail": "获取图片失败，失败原因"}
    """
    logger.info(f"Get image request from {request.username} for {request.uuid}")
    return await system_runtime.user_interface.get_image(request, system_runtime)


@app.post("/update_image_client_path")
async def update_image_client_path(
    request: ImageRequest,
    system_runtime: "SystemRuntime" = Depends(get_runtime),
):
    """
    更新图片的客户端路径。用户提供图片的 UUID 和新的客户端路径，服务器更新数据库记录。

    请求参数：
    - request.username: 用户名
    - request.token: 认证 token
    - request.uuid: 图片对应的对话记录 UUID
    - request.image_client_path: 图片在客户端的路径
    返回值：
    - 成功：{"message": "更新成功"}
    - 失败：HTTP 400 错误，{"detail": "更新失败，失败原因"}
    """
    logger.info(f"Update image client path request from {request.username} for {request.uuid}")
    return await system_runtime.user_interface.update_image_client_path(request, system_runtime)


if __name__ == "__main__":
    is_debug = config.get("is_debug", False)
    if is_debug:
        logger.info("服务器正在以调试模式运行")
    logger.info("启用 HTTP 模式")
    host = os.environ.get("SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("SERVER_PORT", "60030"))
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    admin_url = f"http://{display_host}:{port}/admin"
    logger.info(f"控制台地址: {admin_url}")
    print(f"\nAgentLuo 控制台: {admin_url}\n", flush=True)
    uvicorn.run(app, host=host, port=port)
