from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.application.user.account import PasswordDecryptionError, decrypt_password, generate_keys, get_public_key_pem
from src.application.user.user_conversation_helper import UserConversationHelper
from src.web.http.rate_limits import enforce_rate_limit
from src.web.http.types import (
    AutoLoginRequest,
    DynamicCommentCreateRequest,
    DynamicCommentListRequest,
    DynamicCreateRequest,
    DynamicListRequest,
    DynamicReadMarkRequest,
    DynamicUnreadRequest,
    ImageRequest,
    LoginRequest,
    PreferenceGetRequest,
    PreferenceOverwriteRequest,
    RegisterRequest,
    ResetAccountRequest,
)

if TYPE_CHECKING:
    from src.infrastructure.persistence.database import DatabaseManager
    from src.server_runtime import ServerRuntime


class UserInterface:
    def __init__(self, database_manager: "DatabaseManager"):
        self.database_manager: "DatabaseManager" = database_manager
        self.user_conversation_helper = UserConversationHelper(database_manager)
        self._auth_work_slots = asyncio.Semaphore(4)
        self._auth_work_admission_timeout = 1.0

    async def _run_auth_work(self, func, *args):
        try:
            await asyncio.wait_for(
                self._auth_work_slots.acquire(),
                timeout=self._auth_work_admission_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=503, detail="认证服务繁忙，请稍后再试") from exc
        try:
            return await asyncio.to_thread(func, *args)
        finally:
            self._auth_work_slots.release()

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
        try:
            return decrypt_password(encrypted_b64)
        except PasswordDecryptionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # —————————————————————————————————————————————————————————————————
    # 包装用户界面相关的其他方法
    # —————————————————————————————————————————————————————————————————

    async def auto_login(
        self,
        req: AutoLoginRequest,
        background_tasks: BackgroundTasks,
        server_runtime: ServerRuntime,
        request: Request,
    ):
        """
        自动登录：用户提供用户名和上一次分配的自动登录 token，验证通过后发放新的 token。
        """
        if request is not None:
            enforce_rate_limit(request, "auth_auto_login", req.username)
        auth_result = await self._run_auth_work(
            server_runtime.database_manager.credential_service.authenticate_auto_login,
            req.username,
            req.token,
        )
        if auth_result:
            user_uuid = auth_result["user_uuid"]
            elapsed_from_last_login = auth_result["elapsed_from_last_login"]
            seconds_since_midnight = self._seconds_since_midnight()
            if elapsed_from_last_login is None or elapsed_from_last_login >= seconds_since_midnight:
                if server_runtime.stage_manager is None:
                    raise RuntimeError("StageManager is required for login dispatch")
                server_runtime.stage_manager.record_login(
                    user_uuid,
                    server_runtime.agent_runtime.default_character_id,
                    elapsed_from_last_login=elapsed_from_last_login,
                )
            background_tasks.add_task(
                server_runtime.database_manager.conversation_service.prefill_buffer,
                user_uuid,
            )
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
        server_runtime: ServerRuntime,
        request: Request,
    ):
        """用户注册"""
        if request is not None:
            enforce_rate_limit(request, "auth_register", req.username)
        decrypted_password = self.decrypt_user_password(req.password)
        success, msg = await self._run_auth_work(
            server_runtime.database_manager.credential_service.register_user,
            req.username,
            decrypted_password,
            req.invite_code,
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return {"message": "注册成功", "user_id": req.username}

    async def reset_account(
        self,
        req: ResetAccountRequest,
        server_runtime: ServerRuntime,
        request: Request,
    ):
        """以邀请码重置账号的用户名和密码"""
        if request is not None:
            enforce_rate_limit(request, "auth_reset", req.invite_code)
        decrypted_password = self.decrypt_user_password(req.new_password)
        success, msg = await self._run_auth_work(
            server_runtime.database_manager.credential_service.reset_account,
            req.invite_code,
            req.new_username,
            decrypted_password,
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return {"message": "重置成功", "username": req.new_username}

    async def login(
        self,
        req: LoginRequest,
        background_tasks: BackgroundTasks,
        server_runtime: ServerRuntime,
        request: Request,
    ):
        """用户登录"""
        if request is not None:
            enforce_rate_limit(request, "auth_login", req.username)
        decrypted_password = self.decrypt_user_password(req.password)
        auth_result = await self._run_auth_work(
            server_runtime.database_manager.credential_service.authenticate_password_login,
            req.username,
            decrypted_password,
        )
        if auth_result:
            user_uuid = auth_result["user_uuid"]
            background_tasks.add_task(
                server_runtime.database_manager.conversation_service.prefill_buffer,
                user_uuid,
            )
            elapsed_from_last_login = auth_result["elapsed_from_last_login"]
            seconds_since_midnight = self._seconds_since_midnight()
            if elapsed_from_last_login is None or elapsed_from_last_login >= seconds_since_midnight:
                if server_runtime.stage_manager is None:
                    raise RuntimeError("StageManager is required for login dispatch")
                server_runtime.stage_manager.record_login(
                    user_uuid,
                    server_runtime.agent_runtime.default_character_id,
                    elapsed_from_last_login=elapsed_from_last_login,
                )
            return {
                "login_token": auth_result["login_token"],
                "message_token": auth_result["message_token"],
                "user_id": req.username,
            }
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    @staticmethod
    def _seconds_since_midnight() -> float:
        now = time.localtime()
        return float(now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec)

    async def get_preference(
        self,
        req: PreferenceGetRequest,
        server_runtime: ServerRuntime,
    ):
        """获取用户偏好设置"""
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        preferences = server_runtime.database_manager.conversation_service.get_user_preferences(user_uuid)
        if preferences is None:
            raise HTTPException(status_code=404, detail="未找到该用户")
        return {"preferences": preferences}

    async def overwrite_preference(
        self,
        req: PreferenceOverwriteRequest,
        server_runtime: ServerRuntime,
    ):
        """覆盖用户偏好设置"""
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        if not server_runtime.database_manager.conversation_service.save_user_preferences(user_uuid, req.preferences):
            raise HTTPException(status_code=404, detail="未找到该用户")
        return {"status": "success", "message": "Preferences overwritten successfully"}

    async def get_history(
        self,
        username: str,
        token: str,
        count: int,
        end_index: int,
        server_runtime: ServerRuntime,
    ):
        """获取聊天历史"""
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            username, token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        capped_count = min(max(1, count), 200)
        return await self.user_conversation_helper.handle_history_request(user_uuid, capped_count, end_index)

    async def get_image(
        self,
        req: ImageRequest,
        server_runtime: ServerRuntime,
    ):
        """获取图片"""
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        image_server_path = server_runtime.database_manager.conversation_service.get_image_server_path(
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
        server_runtime: ServerRuntime,
    ):
        """更新图片客户端路径"""
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        success = server_runtime.database_manager.conversation_service.update_image_client_path(
            user_uuid, req.uuid, req.image_client_path
        )
        if not success:
            raise HTTPException(status_code=400, detail="更新失败，记录不存在或无权限访问")
        return {"message": "更新成功"}

    async def list_dynamics(
        self,
        req: DynamicListRequest,
        server_runtime: ServerRuntime,
    ):
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token or ""
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        return server_runtime.database_manager.dynamic_store.list_dynamics_for_user(
            user_uuid,
            limit=req.limit,
            cursor=req.cursor,
        )

    async def create_dynamic(
        self,
        req: DynamicCreateRequest,
        server_runtime: ServerRuntime,
    ):
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        ok, message, item = server_runtime.database_manager.dynamic_store.create_dynamic(
            author_type="user",
            author_id=user_uuid,
            owner_user_id=user_uuid,
            visibility="private",
            content=req.content,
            source_type="user_post",
            allow_comment=True,
            memory_policy="candidate",
        )
        if not ok or item is None:
            raise HTTPException(status_code=400, detail=message)
        return {"item": item}

    async def list_dynamic_comments(
        self,
        dynamic_id: str,
        req: DynamicCommentListRequest,
        server_runtime: ServerRuntime,
    ):
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token or ""
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        ok, message, payload = server_runtime.database_manager.dynamic_store.list_dynamic_comments_for_user(
            user_uuid,
            dynamic_id,
            limit=req.limit,
            cursor=req.cursor,
        )
        if not ok:
            raise HTTPException(status_code=404, detail=message)
        return payload

    async def create_dynamic_comment(
        self,
        dynamic_id: str,
        req: DynamicCommentCreateRequest,
        server_runtime: ServerRuntime,
    ):
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        ok, message, item = server_runtime.database_manager.dynamic_store.create_dynamic_comment(
            dynamic_id=dynamic_id,
            author_type="user",
            author_id=user_uuid,
            owner_user_id=user_uuid,
            content=req.content,
            parent_comment_id=req.parent_comment_id,
            memory_policy="candidate",
        )
        if not ok or item is None:
            raise HTTPException(status_code=400, detail=message)
        return {"item": item}

    async def get_dynamic_unread(
        self,
        req: DynamicUnreadRequest,
        server_runtime: ServerRuntime,
    ):
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token or ""
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        return server_runtime.database_manager.dynamic_store.get_dynamic_unread_status(user_uuid)

    async def mark_dynamic_read(
        self,
        req: DynamicReadMarkRequest,
        server_runtime: ServerRuntime,
    ):
        message_token_valid, user_uuid = server_runtime.database_manager.credential_service.check_message_token(
            req.username, req.token
        )
        if not message_token_valid:
            raise HTTPException(status_code=401, detail="消息令牌无效或已过期")
        result = server_runtime.database_manager.dynamic_store.mark_dynamic_read(user_uuid)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail="标记已读失败")
        return result
