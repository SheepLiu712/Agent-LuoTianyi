"""客户端图片媒体规则（单一来源，镜像服务端规则；勿在其他模块重复定义）。

来源：服务端媒体配置与 src/infrastructure/media/image_validation.py 的解码格式。
防漂移：client/tests/test_image_rules_mirror.py 读取服务端源码断言一致。
"""

from __future__ import annotations

import os

ALLOWED_IMAGE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/bmp",
        "image/webp",
    }
)

MAX_IMAGE_BYTES = 6 * 1024 * 1024

_EXTENSION_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


def detect_image_mime(image_path: str) -> str | None:
    """按扩展名返回图片 MIME；未知扩展名返回 None（不做内容嗅探）。"""
    extension = os.path.splitext(image_path)[1].lower()
    return _EXTENSION_MIME.get(extension)


def validate_image_file(image_path: str) -> tuple[str | None, str | None]:
    """校验待发送文件的扩展名与大小，返回 MIME 和中文错误提示。"""
    mime_type = detect_image_mime(image_path)
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        return None, "不支持的图片格式，请选择 JPG、PNG、GIF、BMP 或 WebP 图片"
    try:
        size = os.path.getsize(image_path)
    except OSError:
        return None, "图片无法读取，请确认文件仍然存在且可访问"
    if size > MAX_IMAGE_BYTES:
        return None, "图片过大（上限约 6 MB），请选择更小的图片"
    return mime_type, None
