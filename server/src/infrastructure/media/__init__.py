"""受控媒体引用解析与持久存储适配器。"""

from .audio_validation import ParsedAudio, parse_m4a_audio
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
from .media_store import MediaDeletionFailure, MediaDeletionReport, PermanentMediaStore

__all__ = [
    "FilesystemMediaResolver",
    "MediaResolutionError",
    "MediaResolutionErrorCode",
    "MediaResolver",
    "MediaDeletionFailure",
    "MediaDeletionReport",
    "ParsedAudio",
    "PermanentMediaStore",
    "ResolvedMedia",
    "UnconfiguredMediaResolver",
    "create_media_resolver",
    "parse_m4a_audio",
    "validate_image_content",
]
