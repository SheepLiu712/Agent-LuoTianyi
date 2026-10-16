"""未决注册请求的本地记录（UA-2）。

只允许保存请求 ID 与用户名：密码与邀请码绝不落盘（spec 接口规范 4）。
用途是"响应丢失后重试同一次请求"与"重启后知道自己还有一次未决提交"，
不构成"已在本地宣布注册成功"的依据——成功与否一律以服务端结果为准。
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from ..safety import storage

FILENAME = "registration_request.json"


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
    return {
        "registration_request_id": request_id,
        "username": username if isinstance(username, str) else "",
        "agreement_version": agreement_version if isinstance(agreement_version, str) else "",
    }


def save_pending(request_id: str, username: str, agreement_version: str = "") -> None:
    """在正式提交前记录请求 ID、用户名和原协议版本；不保存密码或邀请码。"""
    storage.atomic_write_json(
        record_path(),
        {
            "registration_request_id": request_id,
            "username": username,
            "agreement_version": agreement_version,
        },
    )


def clear_pending() -> None:
    """注册成功、或用户改用新的提交内容后清除。"""
    try:
        os.remove(record_path())
    except FileNotFoundError:
        pass


def request_id_for(username: str) -> str:
    """为本次提交取请求 ID：同一用户名沿用未决请求，否则开始新请求。"""
    pending = load_pending()
    if pending and pending["username"] == username:
        return pending["registration_request_id"]
    return new_request_id()
