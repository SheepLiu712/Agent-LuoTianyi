from __future__ import annotations

from typing import TYPE_CHECKING, Optional
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Header, Request
from fastapi.responses import StreamingResponse
from .types import (
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

from .account import get_public_key_pem, decrypt_password, generate_keys
from .websocket_service import WebSocketService
from .user_conversation_helper import UserConversationHelper
from .rate_limits import enforce_rate_limit

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.system.database import DatabaseManager

class UserInterface:
    def __init__(self, database_manager: "DatabaseManager"):
        self.websocket_service: WebSocketService = WebSocketService()
        self.database_manager: "DatabaseManager" = database_manager
        self.user_conversation_helper = UserConversationHelper(database_manager)


    def bind_database_manager(self, database_manager: "DatabaseManager"):
        self.database_manager = database_manager
        self.user_conversation_helper = UserConversationHelper(database_manager)

    def wire_dependencies(self, *, database_manager: "DatabaseManager") -> None:
        """注入用户接口层所需依赖。"""
        self.bind_database_manager(database_manager)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查用户接口层依赖已经初始化。"""
        required = {
            "database_manager": self.database_manager,
            "websocket_service": self.websocket_service,
            "user_conversation_helper": self.user_conversation_helper,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"UserInterface dependencies are missing: {', '.join(missing)}")

    # —————————————————————————————————————————————————————————————————
    # 账号安全相关方法
    # —————————————————————————————————————————————————————————————————
    def generate_rsa_keys(self):
        generate_keys()

    def get_public_key_pem(self) -> str:
        return get_public_key_pem()
    
    def decrypt_user_password(self, encrypted_b64: str) -> str:
        return decrypt_password(encrypted_b64)
    
    # —————————————————————————————————————————————————————————————————
    # 包装用户界面相关的其他方法
    # —————————————————————————————————————————————————————————————————   

    async def auto_login(
        self,
        req: AutoLoginRequest,
        background_tasks: BackgroundTasks,
        system_runtime: SystemRuntime,
        request: Request,
    ):
        """
        自动登录：用户提供用户名和上一次分配的自动登录 token，验证通过后发放新的 token。
        """
        if request is not None:
            enforce_rate_limit(request, "auth_auto_login", req.username)
        auth_result = system_runtime.database_manager.authenticate_auto_login(req.username, req.token)
        if auth_result:
            user_uuid = auth_result["user_uuid"]
            await system_runtime.chat_session_manager.on_user_login(
                user_uuid, auth_result["elapsed_from_last_login"]
            )
            background_tasks.add_task(system_runtime.database_manager.prefill_buffer, user_uuid)
            return {
                "message": "登录成功",
                "user_id": req.username,
                "login_token": auth_result["login_token"],
                "message_token": auth_result["message_token"],
            }
        raise HTTPException(status_code=401, detail="登录失败，自动登录验证未通过")

    async def register(
        self,
        req: RegisterRequest,
        system_runtime: SystemRuntime,
        request: Request,
    ):
        """用户注册"""
        if request is not None:
            enforce_rate_limit(request, "auth_register", req.username)
        decrypted_password = self.decrypt_user_password(req.password)
        success, msg = system_runtime.database_manager.register_user(
            req.username, decrypted_password, req.invite_code
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return {"message": "注册成功", "user_id": req.username}

    async def reset_account(
        self,
        req: ResetAccountRequest,
        system_runtime: SystemRuntime,
        request: Request,
    ):
        """以邀请码重置账号的用户名和密码"""
        if request is not None:
            enforce_rate_limit(request, "auth_reset", req.new_username)
        decrypted_password = self.decrypt_user_password(req.new_password)
        success, msg = system_runtime.database_manager.reset_account(
            req.invite_code, req.new_username, decrypted_password
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return {"message": "重置成功", "username": req.new_username}

    async def login(
        self,
        req: LoginRequest,
        background_tasks: BackgroundTasks,
        system_runtime: SystemRuntime,
        request: Request,
    ):
        """用户登录"""
        if request is not None:
            enforce_rate_limit(request, "auth_login", req.username)
        decrypted_password = self.decrypt_user_password(req.password)
        auth_result = system_runtime.database_manager.authenticate_password_login(
            req.username, decrypted_password
        )
        if auth_result:
            user_uuid = auth_result["user_uuid"]
            background_tasks.add_task(system_runtime.database_manager.prefill_buffer, user_uuid)
            await system_runtime.chat_session_manager.on_user_login(
                user_uuid,
                auth_result["elapsed_from_last_login"],
            )
            return {
                "login_token": auth_result["login_token"],
                "message_token": auth_result["message_token"],
                "user_id": req.username,
            }
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    async def get_preference(
        self,
        req: PreferenceGetRequest,
        system_runtime: SystemRuntime,
    ):
        """获取用户偏好设置"""
        message_token_valid, user_uuid = system_runtime.database_manager.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        preferences = system_runtime.database_manager.get_user_preferences(user_uuid)
        if preferences is None:
            raise HTTPException(status_code=404, detail="未找到该用户")
        return {"preferences": preferences}

    async def overwrite_preference(
        self,
        req: PreferenceOverwriteRequest,
        system_runtime: SystemRuntime,
    ):
        """覆盖用户偏好设置"""
        message_token_valid, user_uuid = system_runtime.database_manager.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        if not system_runtime.database_manager.save_user_preferences(user_uuid, req.preferences):
            raise HTTPException(status_code=404, detail="未找到该用户")
        return {"status": "success", "message": "Preferences overwritten successfully"}

    async def get_history(
        self,
        username: str,
        token: str,
        count: int,
        end_index: int,
        system_runtime: SystemRuntime,
    ):
        """获取聊天历史"""
        message_token_valid, user_uuid = system_runtime.database_manager.check_message_token(
            username, token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        capped_count = min(max(1, count), 200)
        return await self.user_conversation_helper.handle_history_request(
            user_uuid, capped_count, end_index
        )

    async def get_image(
        self,
        req: ImageRequest,
        system_runtime: SystemRuntime,
    ):
        """获取图片"""
        message_token_valid, user_uuid = system_runtime.database_manager.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        image_server_path = system_runtime.database_manager.get_image_server_path(
            user_uuid, req.uuid
        )
        if not image_server_path:
            raise HTTPException(status_code=400, detail="获取图片失败，图片不存在或无权限访问")
        if not os.path.isfile(image_server_path):
            raise HTTPException(status_code=400, detail="获取图片失败，文件不存在")
        try:
            with open(image_server_path, "rb") as f:
                image_data = f.read()
            ext = os.path.splitext(image_server_path)[1].lower()
            content_type = "image/png"
            if ext in [".jpg", ".jpeg"]:
                content_type = "image/jpeg"
            elif ext == ".gif":
                content_type = "image/gif"
            return StreamingResponse(iter([image_data]), media_type=content_type)
        except Exception as e:
            from src.utils.logger import get_logger
            logger = get_logger("user_interface")
            logger.error(f"Error reading image file: {e}")
            raise HTTPException(status_code=400, detail="获取图片失败，读取文件出错")

    async def update_image_client_path(
        self,
        req: ImageRequest,
        system_runtime: SystemRuntime,
    ):
        """更新图片客户端路径"""
        message_token_valid, user_uuid = system_runtime.database_manager.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        success = system_runtime.database_manager.update_image_client_path(
            user_uuid, req.uuid, req.image_client_path
        )
        if not success:
            raise HTTPException(status_code=400, detail="更新失败，记录不存在或无权限访问")
        return {"message": "更新成功"}
    

