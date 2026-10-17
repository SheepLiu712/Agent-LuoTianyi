"""未决注册请求的本地记录（UA-2）。

仅保存请求 ID、用户名、协议版本、服务器身份和必要的确认状态；密码、邀请码及其
可离线猜测的摘要绝不落盘。记录用于响应丢失后的同请求核验和重启后的恢复，不构成
本地成功结论，结果一律以服务端为准。
"""

from __future__ import annotations

import os
import uuid
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from ..safety import storage

FILENAME = "registration_request.json"


def normalize_server_url(value: str) -> str:
    """规范化待决注册所绑定的服务器 origin，不保存凭据或摘要。"""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    ).rstrip("/")


def new_request_id() -> str:
    """生成新的注册请求 ID。"""
    return str(uuid.uuid4())


def record_path() -> str:
    return storage.temp_path(FILENAME)


def load_pending() -> Optional[dict]:
    """读取未决请求；没有或损坏时返回 None。"""
    data = storage.read_json_file(record_path())
    request_id = data.get("registration_request_id")
    if not isinstance(request_id, str) or not request_id:
        return None
    username = data.get("username")
    agreement_version = data.get("agreement_version")
    server_url = data.get("server_url")
    confirmation_required = data.get("confirmation_required")
    return {
        "registration_request_id": request_id,
        "username": username if isinstance(username, str) else "",
        "agreement_version": (
            agreement_version if isinstance(agreement_version, str) else ""
        ),
        "server_url": (
            normalize_server_url(server_url) if isinstance(server_url, str) else ""
        ),
        "confirmation_required": (
            confirmation_required if isinstance(confirmation_required, str) else ""
        ),
    }


def save_pending(
    request_id: str,
    username: str,
    agreement_version: str = "",
    server_url: str = "",
    confirmation_required: Optional[str] = None,
) -> None:
    """在正式提交前记录请求 ID、用户名和原协议版本；不保存密码或邀请码。"""
    existing = load_pending()
    same_identity = bool(
        existing
        and existing.get("registration_request_id") == request_id
        and existing.get("username") == username
        and existing.get("server_url") == normalize_server_url(server_url)
    )
    if confirmation_required is None and same_identity:
        confirmation_required = (
            existing.get("confirmation_required", "") if existing else ""
        )
    elif confirmation_required is None:
        confirmation_required = ""
    payload = {
        "registration_request_id": request_id,
        "username": username,
        "agreement_version": agreement_version,
        "server_url": normalize_server_url(server_url),
    }
    if confirmation_required:
        payload["confirmation_required"] = confirmation_required
    storage.atomic_write_json(record_path(), payload)


def clear_pending() -> None:
    """注册成功、或用户改用新的提交内容后清除。"""
    try:
        os.remove(record_path())
    except FileNotFoundError:
        pass


def request_id_for(username: str, *, resume_pending: bool = False) -> str:
    """为注册提交取请求 ID。

    请求 ID 只有在调用方明确处于“核验待决请求”流程时才会复用。不能仅凭用户名
    猜测本地记录属于当前表单：密码和邀请码不落盘，也不能保存它们的可离线猜测摘要。
    """
    if resume_pending:
        pending = load_pending()
        if pending and pending["username"] == username:
            return pending["registration_request_id"]
    return new_request_id()
