"""Decode chat avatars and store a bounded, metadata-free PNG copy."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO

from PIL import Image, ImageOps

MAX_AVATAR_BYTES = 2 * 1024 * 1024


def normalize_avatar(image: str | None) -> str | None:
    if image is None:
        return None
    prefix, separator, encoded = image.partition(",")
    if not separator or prefix not in {"data:image/png;base64", "data:image/jpeg;base64"}:
        raise ValueError("头像仅支持 PNG、JPEG 图片")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("头像图片编码无效") from None
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("头像图片不能超过 2 MiB")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG"}:
                raise ValueError("头像仅支持 PNG、JPEG 图片")
            if source.width * source.height > 16_000_000:
                raise ValueError("头像图片尺寸过大")
            normalized = ImageOps.exif_transpose(source)
            normalized.thumbnail((256, 256), Image.Resampling.LANCZOS)
            output = BytesIO()
            normalized.convert("RGBA").save(output, format="PNG")
    except (OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError("头像图片无法读取") from None
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
