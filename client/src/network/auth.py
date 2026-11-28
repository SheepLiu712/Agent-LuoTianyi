from dataclasses import dataclass, field
from threading import Event
from typing import Optional, Tuple

import requests

from ..safety import encrypt_pwd
from ..utils.http_client import HttpClientFactory
from ..utils.logger import get_logger
from .agreement import validate_agreement_payload

logger = get_logger("auth")


@dataclass(frozen=True)
class RegisterOutcome:
    """注册结果：除文案外带上服务端错误码，供流程分支（换版、冲突、恢复成功）。"""

    ok: bool
    message: str
    code: str = ""
    agreement_version: str = ""
    status_code: int = 0  # 0 表示没有拿到 HTTP 响应（传输失败，结果未知）


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
    agreement_version: str = ""
    token: str | None = field(default=None, repr=False)

    def execute(self, cancelled: Event) -> tuple[bool, str, dict]:
        if cancelled.is_set():
            return False, "Request cancelled", {}
        with HttpClientFactory.create_session() as session:
            api = AuthApi(self.base_url, session=session, cancelled=cancelled)
            if self.action == "agreement_login":
                accepted = api.accept_agreement(
                    self.username,
                    self.agreement_version,
                    password=None if self.token is not None else self.password,
                    token=self.token,
                )
                if not accepted[0] or cancelled.is_set():
                    return accepted if not cancelled.is_set() else (False, "Request cancelled", {})
                if self.token is not None:
                    ok, data = api.auto_login(self.username, self.token)
                    return (
                        ok,
                        "登录成功" if ok else data.get("message", "登录失败"),
                        data,
                    )
                return api.login(self.username, self.password, self.remember)
            if self.action == "login":
                return api.login(self.username, self.password, self.remember)
            if self.action == "register":
                ok, message, policy = api.fetch_agreement_policy()
                if not ok:
                    return False, message, {}
                if policy["require_acceptance"]:
                    return False, "请阅读并同意用户协议", {"code": "AGREEMENT_REQUIRED"}
                outcome = api.register_with_agreement(self.username, self.password, self.invite)
                return outcome.ok, outcome.message, {"code": outcome.code}
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
            return False, "密码加密失败，请检查网络连接后重试", {}

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
            return (
                False,
                _error_detail(resp, "登录失败，请检查用户名和密码"),
                {
                    "code": _error_code(resp),
                    "agreement_version": _agreement_version(resp),
                    "status_code": resp.status_code,
                },
            )

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
            return False, {
                "code": _error_code(resp),
                "message": _error_detail(resp, "登录失败"),
                "agreement_version": _agreement_version(resp),
                "status_code": resp.status_code,
            }
        return True, resp.json()

    def accept_agreement(
        self,
        username: str,
        version: str,
        *,
        password: str | None = None,
        token: str | None = None,
    ):
        if (password is None) == (token is None):
            return False, "协议签署凭据无效", {"status_code": 422}
        if password is not None:
            encrypted = encrypt_pwd.encrypt_password(password, base_url=self.base_url, verify_ssl=self.verify_ssl)
            if not encrypted:
                return (
                    False,
                    "无法发送协议签署请求，请检查服务器连接后重试",
                    {"code": "AGREEMENT_NOT_SENT"},
                )
            credential = {
                "kind": "password",
                "username": username,
                "password": encrypted,
            }
        else:
            credential = {
                "kind": "auto_login",
                "username": username,
                "token": token or "",
            }
        resp = self.session.post(
            f"{self.base_url}/auth/agreement/accept",
            json={
                "agreement_version": version,
                "accepted": True,
                "credential": credential,
            },
            verify=self.verify_ssl,
            timeout=15,
        )
        try:
            body = resp.json()
        except Exception:
            body = {}
        if resp.status_code == 200:
            return True, "协议签署成功", body
        return (
            False,
            _error_detail(resp, "协议签署失败"),
            {
                "code": _error_code(resp),
                "agreement_version": _agreement_version(resp),
                "status_code": resp.status_code,
            },
        )

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
        # 服务端换钥后，本地仍能用旧公钥生成合法密文，失败只会在服务端解密时暴露；
        # 收到 PASSWORD_DECRYPT_FAILED 时刷新公钥重试一次（同一 payload，保持幂等）。
        for attempt in range(2):
            encrypted_password = encrypt_pwd.encrypt_password(
                password, base_url=self.base_url, verify_ssl=self.verify_ssl, session=self.session
            )
            if not encrypted_password:
                return RegisterOutcome(False, "无法发送注册请求，请检查服务器连接后重试", code="REGISTRATION_NOT_SENT")

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

            if self._cancelled():
                return RegisterOutcome(False, "Request cancelled", code="REGISTRATION_NOT_SENT")
            try:
                resp = self.session.post(
                    f"{self.base_url}/auth/register",
                    json=payload,
                    verify=self.verify_ssl,
                    timeout=15,
                )
            except requests.RequestException as error:  # 传输失败：本次结果未知
                logger.error(f"Register request failed: {error}")
                return RegisterOutcome(False, "网络异常，请检查网络连接后重试", code="NETWORK_ERROR")
            if resp.status_code == 200:
                return RegisterOutcome(True, "Registration Successful")

            code = _error_code(resp)
            if code == "PASSWORD_DECRYPT_FAILED" and attempt == 0:
                continue

            return RegisterOutcome(
                False,
                _error_detail(resp, "注册失败，请稍后重试"),
                code=code,
                agreement_version=_agreement_version(resp),
                status_code=resp.status_code,
            )

        return RegisterOutcome(False, "注册失败，请稍后重试")

    def reset_account(self, invite_code: str, new_username: str, new_password: str) -> Tuple[bool, str]:
        """通过邀请码重置账号的用户名和密码。"""
        encrypted_password = encrypt_pwd.encrypt_password(
            new_password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
            session=self.session,
        )
        if not encrypted_password:
            return False, "密码加密失败，请检查网络连接后重试"

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
        return False, _error_detail(resp, "重置失败，请稍后重试")

    def fetch_agreement_policy(self) -> tuple[bool, str, dict]:
        response = self.session.get(f"{self.base_url}/auth/agreement/policy", verify=self.verify_ssl, timeout=15)
        data = response.json()
        if (
            response.status_code != 200
            or not isinstance(data, dict)
            or type(data.get("require_acceptance")) is not bool
        ):
            return False, "无法获取注册策略，请稍后重试", {}
        return True, "", data

    def fetch_current_agreement(self) -> Tuple[bool, str, dict]:
        """获取当前的用户协议。"""
        resp = self.session.get(
            f"{self.base_url}/auth/agreement",
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            return False, _error_detail(resp, "用户协议加载失败，请重试"), {}
        try:
            payload = validate_agreement_payload(resp.json())
        except Exception:
            payload = None
        if payload is None:
            return False, "用户协议加载失败，请重试", {}
        return True, "", payload
