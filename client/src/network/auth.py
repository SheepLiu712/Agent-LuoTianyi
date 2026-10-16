from dataclasses import dataclass
from typing import Optional, Tuple

import requests

from ..safety import encrypt_pwd
from ..utils.http_client import HttpClientFactory
from .agreement import validate_agreement_payload


@dataclass(frozen=True)
class RegisterOutcome:
    """注册结果：除文案外带上服务端错误码，供流程分支（换版、冲突、恢复成功）。"""

    ok: bool
    message: str
    code: str = ""
    agreement_version: str = ""


def _error_code(response: requests.Response) -> str:
    """取稳定错误码；兼容顶层平铺与嵌在 detail 里的两种形态。"""
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    code = body.get("code")
    if isinstance(code, str):
        return code
    detail = body.get("detail")
    if isinstance(detail, dict):
        nested = detail.get("code")
        if isinstance(nested, str):
            return nested
    return ""


def _agreement_version(response: requests.Response) -> str:
    """换版响应会带上当前协议版本；顶层或 detail 内都接受。"""
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    version = body.get("agreement_version")
    if isinstance(version, str):
        return version
    detail = body.get("detail")
    if isinstance(detail, dict):
        nested = detail.get("agreement_version")
        if isinstance(nested, str):
            return nested
    return ""


def _error_detail(response: requests.Response, fallback: str) -> str:
    """从失败响应里取一句可直接显示的文案。

    服务端的 ``detail`` 可能是字符串，也可能是对象——运行时未就绪的 503 会返回
    ``{"ok": false, "code": "SYSTEM_RUNTIME_NOT_READY", "message": "...", "runtime": {...}}``
    （见 ``server/src/web/http/runtime_access.py``）。直接把它当字符串插值会把整个信封打印成
    Python 字典字面量，这里只取可显示的那一层。
    """
    try:
        detail = response.json().get("detail", fallback)
    except Exception:
        return fallback
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return fallback


class AuthApi:
    def __init__(self, base_url: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.session = HttpClientFactory.get_session(verify_ssl=self.verify_ssl)

    def set_base_url(self, base_url: str, verify_ssl: bool) -> None:
        """更新服务器地址，同时重新创建 HTTP 会话。"""
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.session = HttpClientFactory.get_session(verify_ssl=self.verify_ssl)

    def login(self, username: str, password: str, request_token: bool = False) -> Tuple[bool, str, dict]:
        encrypted_password = encrypt_pwd.encrypt_password(
            password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection.", {}

        resp = self.session.post(
            f"{self.base_url}/auth/login",
            json={
                "username": username,
                "password": encrypted_password,
                "request_token": request_token,
            },
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            return False, _error_detail(resp, "Login Failed"), {}

        data = resp.json()
        return True, "Login Successful", data

    def auto_login(self, username: str, token: str) -> tuple[bool, dict]:
        resp = self.session.post(
            f"{self.base_url}/auth/auto_login",
            json={"username": username, "token": token},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            return False, {}
        return True, resp.json()

    def register(self, username: str, password: str, invite_code: str) -> Tuple[bool, str]:
        outcome = self.register_with_agreement(username, password, invite_code)
        return outcome.ok, outcome.message

    def register_with_agreement(
        self,
        username: str,
        password: str,
        invite_code: str,
        *,
        registration_request_id: Optional[str] = None,
        agreement_version: Optional[str] = None,
        accepted: Optional[bool] = None,
    ) -> RegisterOutcome:
        """带协议同意的注册提交；返回错误码而不仅是文案。

        旧调用方（不带协议字段）仍走同一入口：服务端会返回 AGREEMENT_REQUIRED，
        客户端据此打开协议窗口。
        """
        encrypted_password = encrypt_pwd.encrypt_password(
            password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
        )
        if not encrypted_password:
            return RegisterOutcome(False, "Failed to encrypt password. Check server connection.")

        payload: dict = {
            "username": username,
            "password": encrypted_password,
            "invite_code": invite_code,
        }
        if registration_request_id is not None:
            payload["registration_request_id"] = registration_request_id
        if agreement_version is not None:
            payload["agreement_version"] = agreement_version
        if accepted is not None:
            payload["accepted"] = accepted

        resp = self.session.post(
            f"{self.base_url}/auth/register",
            json=payload,
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code == 200:
            return RegisterOutcome(True, "Registration Successful")

        message = _error_detail(resp, "Registration Failed")
        return RegisterOutcome(
            False,
            message,
            code=_error_code(resp),
            agreement_version=_agreement_version(resp),
        )

    def reset_account(self, invite_code: str, new_username: str, new_password: str) -> Tuple[bool, str]:
        """通过邀请码重置账号的用户名和密码。"""
        encrypted_password = encrypt_pwd.encrypt_password(
            new_password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection."

        resp = self.session.post(
            f"{self.base_url}/auth/reset_account",
            json={
                "invite_code": invite_code,
                "new_username": new_username,
                "new_password": encrypted_password,
            },
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code == 200:
            return True, "Reset Successful"
        return False, _error_detail(resp, "Reset Failed")

    def fetch_current_agreement(self) -> Tuple[bool, str, dict]:
        """获取当前的用户协议。"""
        resp = self.session.get(
            f"{self.base_url}/auth/agreement",
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            return False, _error_detail(resp, "Failed to load agreement"), {}
        try:
            payload = validate_agreement_payload(resp.json())
        except Exception:
            payload = None
        if payload is None:
            return False, "Failed to load agreement", {}
        return True, "", payload
