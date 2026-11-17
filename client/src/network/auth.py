from dataclasses import dataclass, field
from threading import Event
from typing import Tuple

import requests

from ..safety import encrypt_pwd
from ..utils.http_client import HttpClientFactory


@dataclass(frozen=True)
class AccountRequest:
    """窗口调度时的纯网络输入，不持有客户端、Binder 或 Qt 对象。"""

    context: tuple = field(repr=False)
    action: str
    base_url: str
    username: str = ""
    password: str = field(default="", repr=False)
    invite: str = field(default="", repr=False)
    remember: bool = False

    def execute(self, cancelled: Event) -> tuple[bool, str, dict]:
        if cancelled.is_set():
            return False, "Request cancelled", {}
        with HttpClientFactory.create_session() as session:
            api = AuthApi(self.base_url, session=session, cancelled=cancelled)
            if self.action == "login":
                return api.login(self.username, self.password, self.remember)
            if self.action == "register":
                ok, message = api.register(self.username, self.password, self.invite)
                return ok, message, {}
            if self.action == "reset":
                ok, message = api.reset_account(self.invite, self.username, self.password)
                return ok, message, {}
            if self.action == "server":
                response = session.get(f"{self.base_url}/auth/public_key", verify=True, timeout=10)
                return response.status_code == 200, f"服务器返回状态码: {response.status_code}", {}
            raise ValueError("Unknown account operation")


class AuthApi:
    def __init__(self, base_url: str, verify_ssl: bool = True, session=None, cancelled: Event | None = None):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.session = session if session is not None else HttpClientFactory.get_session(verify_ssl=self.verify_ssl)
        self.cancelled = cancelled

    def _cancelled(self) -> bool:
        return self.cancelled is not None and self.cancelled.is_set()

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
            session=self.session,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection.", {}

        if self._cancelled():
            return False, "Request cancelled", {}
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
            detail = "Login Failed"
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            return False, detail, {}

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
        encrypted_password = encrypt_pwd.encrypt_password(
            password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
            session=self.session,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection."

        if self._cancelled():
            return False, "Request cancelled"
        resp = self.session.post(
            f"{self.base_url}/auth/register",
            json={"username": username, "password": encrypted_password, "invite_code": invite_code},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code == 200:
            return True, "Registration Successful"
        try:
            detail = resp.json().get("detail", "Registration Failed")
        except Exception:
            detail = "Registration Failed"
        return False, detail

    def reset_account(self, invite_code: str, new_username: str, new_password: str) -> Tuple[bool, str]:
        """通过邀请码重置账号的用户名和密码。"""
        encrypted_password = encrypt_pwd.encrypt_password(
            new_password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
            session=self.session,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection."

        if self._cancelled():
            return False, "Request cancelled"
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
        try:
            detail = resp.json().get("detail", "Reset Failed")
        except Exception:
            detail = "Reset Failed"
        return False, detail
