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
