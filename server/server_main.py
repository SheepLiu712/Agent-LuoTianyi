import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import uvicorn
import os
import sys
from typing import Dict
import redis
import time
from collections import deque
from threading import Lock

# Ensure src is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import src.system.database as database
from src.system.user_interface import account
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


_RATE_LIMITS = {
    "auth_login": (10, 60),
    "auth_register": (5, 60),
    "auth_auto_login": (10, 60),
    "auth_reset": (3, 300),
}
_rate_limit_lock = Lock()
_rate_limit_store: Dict[str, deque] = {}


def _get_client_key(request: Request, username: str | None) -> str:
    client_ip = request.client.host if request.client else "unknown"
    user = username or "unknown"
    return f"{client_ip}:{user}"


def _enforce_rate_limit(request: Request, bucket: str, username: str | None) -> None:
    if bucket not in _RATE_LIMITS:
        return
    limit, window_sec = _RATE_LIMITS[bucket]
    key = f"{bucket}:{_get_client_key(request, username)}"
    now = time.monotonic()
    with _rate_limit_lock:
        timestamps = _rate_limit_store.setdefault(key, deque())
        while timestamps and now - timestamps[0] > window_sec:
            timestamps.popleft()
        if len(timestamps) >= limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        timestamps.append(now)


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
        await ws_connection.auth(websocket_service)  # 等待认证，认证成功之后将ws和用户信息绑定
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
                    system_runtime.agent.save_preferences(ws_connection.user_uuid, preferences)
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
async def get_public_key():
    return {"public_key": account.get_public_key_pem()}


@app.post("/auth/auto_login")
async def auto_login(
    req: AutoLoginRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_sql_db),
    redis: redis.Redis = Depends(database.get_redis_buffer),
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
    if request is not None:
        _enforce_rate_limit(request, "auth_auto_login", req.username)
    if account.check_auth_token(db, req.username, req.token):
        new_token = account.update_auth_token(db, req.username)
        message_token = account.generate_message_token(db, req.username)
        # 将上下文预先加载到 Redis 中
        user = db.query(database.User).filter_by(username=req.username).first()
        elapsed_from_last_login = database.database_service.update_login_time(db, user.uuid) if user else None
        if user is not None:
            await system_runtime.activity_maker.add_user_login_activity(user.uuid, elapsed_from_last_login)
        background_tasks.add_task(database.prefill_buffer, db, redis, user.uuid)
        return {"message": "登录成功", "user_id": req.username, "login_token": new_token, "message_token": message_token}
    raise HTTPException(status_code=401, detail="登录失败，自动登录验证未通过")


@app.post("/auth/register")
async def register(
    req: RegisterRequest,
    db: Session = Depends(database.get_sql_db),
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
    if request is not None:
        _enforce_rate_limit(request, "auth_register", req.username)
    decrypted_password = account.decrypt_password(req.password)

    success, msg = account.register_user(db, req.username, decrypted_password, req.invite_code)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": "注册成功", "user_id": req.username}


@app.post("/auth/reset_account")
async def reset_account(
    req: ResetAccountRequest,
    db: Session = Depends(database.get_sql_db),
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
    if request is not None:
        _enforce_rate_limit(request, "auth_reset", req.new_username)
    decrypted_password = account.decrypt_password(req.new_password)

    success, msg = account.reset_account(db, req.invite_code, req.new_username, decrypted_password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": "重置成功", "username": req.new_username}


@app.post("/auth/login")
async def login(
    req: LoginRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_sql_db),
    redis: redis.Redis = Depends(database.get_redis_buffer),
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
    if request is not None:
        _enforce_rate_limit(request, "auth_login", req.username)
    decrypted_password = account.decrypt_password(req.password)

    if account.verify_user(db, req.username, decrypted_password):
        token = account.update_auth_token(db, req.username)
        message_token = account.generate_message_token(db, req.username)

        # 将上下文预先加载到 Redis 中
        user = db.query(database.User).filter_by(username=req.username).first()
        background_tasks.add_task(database.prefill_buffer, db, redis, user.uuid)
        elapsed_from_last_login = database.database_service.update_login_time(db, user.uuid) if user else None
        if user is not None:
            await system_runtime.activity_maker.add_user_login_activity(user.uuid, elapsed_from_last_login)
        return {"login_token": token, "message_token": message_token, "user_id": req.username}
    raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.post("/preference/get")
async def get_preference(
    req: PreferenceGetRequest,
    db: Session = Depends(database.get_sql_db)
):
    message_token_valid, user_uuid = account.check_message_token(db, req.username, req.token)
    if not message_token_valid:
        raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
    user = db.query(database.User).filter_by(uuid=user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="未找到该用户")
    preferences = json.loads(user.preferences) if user.preferences else {}
    return {"preferences": preferences}


@app.post("/preference/overwrite")
async def overwrite_preference(
    req: PreferenceOverwriteRequest,
    db: Session = Depends(database.get_sql_db)
):
    message_token_valid, user_uuid = account.check_message_token(db, req.username, req.token)
    if not message_token_valid:
        raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
    
    user = db.query(database.User).filter_by(uuid=user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="未找到该用户")
    
    user.preferences = json.dumps(req.preferences, ensure_ascii=False)

    db.commit()
    return {"status": "success", "message": "Preferences overwritten successfully"}
    


@app.get("/history")
async def get_history(
    request: HistoryRequest = Depends(),
    authorization: str | None = Header(default=None),
    db: Session = Depends(database.get_sql_db),
    system_runtime: SystemRuntime = Depends(get_runtime),
):
    logger.info(f"Server received: Get history request from {request.username}")
    token = request.token
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not token:
        raise HTTPException(status_code=401, detail="消息令牌缺失")
    message_token_valid, user_uuid = account.check_message_token(db, request.username, token)
    if not message_token_valid:
        raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
    # Cap count to prevent excessive reads
    capped_count = min(max(1, request.count), 200)
    return await system_runtime.conversation_service.handle_history_request(
        user_uuid, capped_count, request.end_index
    )





@app.post("/get_image")
async def get_image(request: ImageRequest, db: Session = Depends(database.get_sql_db)):
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
    message_token_valid, user_uuid = account.check_message_token(db, request.username, request.token)
    if not message_token_valid:
        raise HTTPException(status_code=401, detail="消息令牌无效或已过期")

    # 获取图片服务器路径
    image_server_path = database.database_service.get_image_server_path(db, user_uuid, request.uuid)
    if not image_server_path:
        raise HTTPException(status_code=400, detail="获取图片失败，图片不存在或无权限访问")

    if not os.path.isfile(image_server_path):
        raise HTTPException(status_code=400, detail="获取图片失败，文件不存在")

    # 读取图片二进制数据
    try:
        with open(image_server_path, "rb") as f:
            image_data = f.read()

        # 根据文件扩展名设置 Content-Type
        ext = os.path.splitext(image_server_path)[1].lower()
        content_type = "image/png"
        if ext in [".jpg", ".jpeg"]:
            content_type = "image/jpeg"
        elif ext == ".gif":
            content_type = "image/gif"

        return StreamingResponse(iter([image_data]), media_type=content_type)
    except Exception as e:
        logger.error(f"Error reading image file: {e}")
        raise HTTPException(status_code=400, detail="获取图片失败，读取文件出错")


@app.post("/update_image_client_path")
async def update_image_client_path(request: ImageRequest, db: Session = Depends(database.get_sql_db)):
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
    message_token_valid, user_uuid = account.check_message_token(db, request.username, request.token)
    if not message_token_valid:
        raise HTTPException(status_code=401, detail="消息令牌无效或已过期")

    success = database.database_service.update_image_client_path(db, user_uuid, request.uuid, request.image_client_path)
    if not success:
        raise HTTPException(status_code=400, detail="更新失败，记录不存在或无权限访问")

    return {"message": "更新成功"}


if __name__ == "__main__":
    # 使用 127.0.0.1 配合内网穿透，或使用 0.0.0.0 直接公网访问
    # 通过 SakuraFrp 等内网穿透服务时，保持 127.0.0.1 即可

    is_debug = config.get("is_debug", False)
    if is_debug:
        logger.info("服务器正在以调试模式运行")
    will_use_https = False  # 调试模式下默认不使用 HTTPS，避免证书问题

    # HTTPS 配置（用于 SakuraFrp TCP 隧道）
    cert_file = os.path.join(current_dir, "certs", "cert.pem")
    key_file = os.path.join(current_dir, "certs", "key.pem")

    # 检查是否存在 SSL 证书
    if will_use_https and os.path.exists(cert_file) and os.path.exists(key_file):
        logger.info("启用 HTTPS 模式")
        uvicorn.run(app, host="127.0.0.1", port=60030, ssl_keyfile=key_file, ssl_certfile=cert_file)
    else:
        if will_use_https:  # 想要用HTTPS但没有证书
            logger.warning("未找到 SSL 证书，使用 HTTP 模式")
            logger.warning(f"如需启用 HTTPS，请运行: python scripts/generate_cert.py")
        else:
            logger.info("启用 HTTP 模式")
        uvicorn.run(app, host="127.0.0.1", port=60030)
