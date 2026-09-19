"""媒体存储与解析共享的图片内容校验。"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .media_resolver import MediaResolutionError, MediaResolutionErrorCode

_FORMAT_MIME = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def validate_image_content(data: bytes, mime_type: str, media_id: str) -> None:
    """完整解码图片并确认实际格式与声明 MIME 一致。"""
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            detected_mime = _FORMAT_MIME.get(image.format or "")
    except (OSError, UnidentifiedImageError):
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.UNKNOWN,
            media_id=media_id,
        ) from None
    normalized = "image/jpeg" if mime_type == "image/jpg" else mime_type
    if detected_mime is None or normalized != detected_mime:
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.UNSUPPORTED_TYPE,
            media_id=media_id,
        )
