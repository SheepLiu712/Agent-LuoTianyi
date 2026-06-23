from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.responses import StreamingResponse
import uvicorn
import os
import sys

# Ensure src is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.system.user_interface.types import (
    RegisterRequest,
    LoginRequest,
    AutoLoginRequest,
    HistoryRequest,
    ImageRequest,
    ResetAccountRequest,
    WSEventType,
    PreferenceGetRequest,
    PreferenceOverwriteRequest,
)
from src.system.user_interface.websocket_service import WebSocketConnection
from src.system.system_runtime import (
    SystemRuntime,
    get_system_runtime,
    init_system_runtime,
    shutdown_system_runtime,
)

from src.utils.helpers import load_config
from src.utils.logger import get_logger

logger = get_logger("server_main")
config = load_config("config/config.json")


@asynccontextmanager
async def startup_event(app: FastAPI):
    await init_system_runtime(config)
    try:
        yield
    finally:
        await shutdown_system_runtime()


def get_runtime() -> SystemRuntime:
    return get_system_runtime()


app = FastAPI(lifespan=startup_event)

# ——————————————————————————————————————————————————————————————————
# 主要的 API 路由定义
# ——————————————————————————————————————————————————————————————————

@app.websocket("/chat_ws")
async def chat_ws(
    websocket: WebSocket,
    system_runtime: SystemRuntime = Depends(get_runtime),
):
    await websocket.accept()
    logger.info("WebSocket client connected to /chat_ws")
    websocket_service = system_runtime.websocket_service  # WebSocketService 实例
    gcsm = system_runtime.gcsm  # 全局聊天流管理器实例
    await websocket_service.send_system_ready_event(websocket)
    ws_connection = WebSocketConnection(websocket=websocket, user_uuid=None, user_name=None)
    try:
        await ws_connection.auth(websocket_service, system_runtime.database_manager)  # 等待认证，认证成功之后将ws和用户信息绑定
        chat_stream = gcsm.get_or_register_chat_stream(
            ws_connection, system_runtime=system_runtime
        )  # 根据ws连接获取对应的聊天流实例，内部会根据用户UUID进行管理
        while True:
            event = await websocket_service.try_recv_client_msg(ws_connection)
            if event is None:
                continue

            if event.event_type == WSEventType.HB_PING.value:
                await websocket_service.handle_ping_event(ws_connection, event)
                continue

            # 处理用户偏好同步事件
            if event.event_type == WSEventType.USER_PREFERENCE_SYNC.value:
                await websocket_service.send_ack_event(ws_connection, event)
                preferences = event.payload if isinstance(event.payload, dict) else {}
                if ws_connection.user_uuid and preferences:
                    system_runtime.database_manager.save_user_preferences(ws_connection.user_uuid, preferences)
                continue

            chat_event = websocket_service.convert_to_chat_input_event(
                event,
                sender_user_id=ws_connection.user_uuid,
            )
            if chat_event is None:
                continue
            await websocket_service.send_ack_event(ws_connection, event)  # 收到消息后发送 ACK 确认收到，之后进处理流程
            await chat_stream.feed_event(chat_event)
    except WebSocketDisconnect:
        gcsm.ws_lost_connection(ws_connection)
        logger.info("WebSocket client disconnected from /chat_ws")
    except Exception as e:
        gcsm.ws_lost_connection(ws_connection)
        logger.error(f"Error in /chat_ws: {e}")


@app.get("/auth/public_key")
async def get_public_key(system_runtime: SystemRuntime = Depends(get_runtime)):
    """
    获取用户登录加密密码时使用的公钥。客户端在登录或注册时使用该公钥加密密码后发送给服务器。
    """
    return {"public_key": system_runtime.user_interface.get_public_key_pem()}


@app.post("/auth/auto_login")
async def auto_login(
    req: AutoLoginRequest,
    background_tasks: BackgroundTasks,
    system_runtime: SystemRuntime = Depends(get_runtime),
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
    system_runtime: SystemRuntime = Depends(get_runtime),
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
    logger.info(f"Register request: {req.username} with code {req.invite_code}")
    return await system_runtime.user_interface.register(
        req, system_runtime, request
    )


@app.post("/auth/reset_account")
async def reset_account(
    req: ResetAccountRequest,
    system_runtime: SystemRuntime = Depends(get_runtime),
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
    logger.info(f"Reset account request for invite_code: {req.invite_code[:4]}****")
    return await system_runtime.user_interface.reset_account(
        req, system_runtime, request
    )


@app.post("/auth/login")
async def login(
    req: LoginRequest,
    background_tasks: BackgroundTasks,
    system_runtime: SystemRuntime = Depends(get_runtime),
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
    system_runtime: SystemRuntime = Depends(get_runtime),
):
    """获取偏好设置：委托到 UserInterface。"""
    return await system_runtime.user_interface.get_preference(req, system_runtime)


@app.post("/preference/overwrite")
async def overwrite_preference(
    req: PreferenceOverwriteRequest,
    system_runtime: SystemRuntime = Depends(get_runtime),
):
    """覆盖偏好设置：委托到 UserInterface。"""
    return await system_runtime.user_interface.overwrite_preference(req, system_runtime)


@app.get("/history")
async def get_history(
    request: HistoryRequest = Depends(),
    authorization: str | None = Header(default=None),
    system_runtime: SystemRuntime = Depends(get_runtime),
):
    """获取聊天历史：委托到 UserInterface。"""
    logger.info(f"Server received: Get history request from {request.username}")
    token = request.token
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not token:
        raise HTTPException(status_code=401, detail="消息令牌缺失")
    return await system_runtime.user_interface.get_history(
        request.username, token, request.count, request.end_index, system_runtime
    )


@app.post("/get_image")
async def get_image(
    request: ImageRequest,
    system_runtime: SystemRuntime = Depends(get_runtime),
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
    system_runtime: SystemRuntime = Depends(get_runtime),
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
    uvicorn.run(app, host="127.0.0.1", port=60030)
