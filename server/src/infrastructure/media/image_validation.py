"""媒体存储与解析共享的图片内容校验。"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from src.utils.logger import get_logger

from .media_resolver import MediaResolutionError, MediaResolutionErrorCode

logger = get_logger(__name__)

_FORMAT_MIME = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def validate_image_content(data: bytes, mime_type: str | None, media_id: str) -> str:
    """校验图片内容并返回实际 MIME；声明仅用于诊断，不决定是否接收。"""
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
    if detected_mime is None:
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.UNSUPPORTED_TYPE,
            media_id=media_id,
        )
    if normalized and normalized != detected_mime:
        logger.debug("图片 MIME 声明与实际格式不一致: media_id=%s detected=%s", media_id, detected_mime)
    return detected_mime
