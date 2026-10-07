"""受控媒体引用解析与持久存储适配器。"""

from .image_validation import validate_image_content
from .media_resolver import (
    FilesystemMediaResolver,
    MediaResolutionError,
    MediaResolutionErrorCode,
    MediaResolver,
    ResolvedMedia,
    UnconfiguredMediaResolver,
    create_media_resolver,
)
from .media_store import PermanentMediaStore

__all__ = [
    "FilesystemMediaResolver",
    "MediaResolutionError",
    "MediaResolutionErrorCode",
    "MediaResolver",
    "PermanentMediaStore",
    "ResolvedMedia",
    "UnconfiguredMediaResolver",
    "create_media_resolver",
    "validate_image_content",
]
