"""桌面客户端图片编码管道，供消息处理流程使用。"""

from __future__ import annotations

import base64
import datetime
import os

from .image_rules import detect_image_mime


def save_image_to_temp(image_data: bytes, postfix: str, *, base_dir: str | None = None) -> str:
    """将图片字节保存到 temp/images/<时间戳><后缀> 并返回路径。"""
    cwd = base_dir or os.getcwd()
    new_file_path = os.path.join(
        cwd,
        "temp",
        "images",
        datetime.datetime.now().strftime("%Y%m%d%H%M%S") + postfix,
    )
    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
    with open(new_file_path, "wb") as f:
        f.write(image_data)
    return new_file_path


def prepare_image_payload(image_path: str) -> dict:
    """读取图片并产出发送载荷（读文件 → 临时副本 → Base64 → MIME）。"""
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
        postfix = os.path.splitext(image_path)[1]
        new_file_path = save_image_to_temp(image_data, postfix)
    except Exception as exc:
        return {"ok": False, "error": f"Failed to read image file: {exc}", "drop": True}

    mime_type = detect_image_mime(image_path) or "image/png"

    return {
        "ok": True,
        "image_base64": base64.b64encode(image_data).decode("utf-8"),
        "mime_type": mime_type,
        "image_client_path": new_file_path,
    }
