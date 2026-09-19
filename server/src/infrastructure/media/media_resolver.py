"""把 Agent 的受控 MediaRef 解析为编码字节和 MIME。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from src.domain.agent import MediaRef


class MediaResolutionErrorCode(str, Enum):
    """媒体解析在存储策略落地前保留的稳定失败分类。"""

    NOT_CONFIGURED = "MEDIA_RESOLVER_NOT_CONFIGURED"
    UNKNOWN = "MEDIA_UNKNOWN"
    UNAUTHORIZED = "MEDIA_UNAUTHORIZED"
    EMPTY = "MEDIA_EMPTY"
    UNSUPPORTED_TYPE = "MEDIA_UNSUPPORTED_TYPE"
    TOO_LARGE = "MEDIA_TOO_LARGE"


@dataclass(frozen=True)
class ResolvedMedia:
    """受控引用解析后的媒体编码内容。"""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class MediaResolutionError(Exception):
    """媒体引用无法安全解析时的稳定、可分类错误。"""

    code: MediaResolutionErrorCode | str
    media_id: str

    def __str__(self) -> str:
        return f"{self.code}: media_id={self.media_id}"


class MediaResolver(Protocol):
    """只读、幂等地解析受控媒体引用。"""

    def resolve(self, media_ref: MediaRef, *, owner_user_id: str) -> ResolvedMedia: ...


class UnconfiguredMediaResolver:
    """尚无存储策略时使用的显式失败实现。"""

    def __init__(self, config: dict | None = None) -> None:
        self._config = dict(config or {})

    def resolve(self, media_ref: MediaRef, *, owner_user_id: str) -> ResolvedMedia:
        """拒绝解析，避免把缺省能力伪装成空媒体成功。"""
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.NOT_CONFIGURED,
            media_id=media_ref.media_id,
        )

    def ensure_dependencies(self) -> None:
        """缺省实现不拥有外部依赖。"""


class FilesystemMediaResolver:
    """从永久文件媒体库按 UUID media_id 读取图片。"""

    def __init__(self, config: dict) -> None:
        root = config.get("root")
        if not isinstance(root, str) or not root.strip():
            raise ValueError("media_resolution.root must be a non-empty path")
        self._root = Path(root).resolve()

    def resolve(self, media_ref: MediaRef, *, owner_user_id: str) -> ResolvedMedia:
        """读取完整媒体；未知、空内容、非图片或非法 ID 均稳定失败。"""
        media_dir = self._media_dir(media_ref)
        metadata_path = media_dir / "metadata.json"
        content_path = media_dir / "content.bin"
        if not metadata_path.is_file() or not content_path.is_file():
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            )
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            ) from None
        if not isinstance(metadata, dict):
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            )
        stored_owner = metadata.get("owner_user_id")
        if not isinstance(stored_owner, str) or not stored_owner.strip():
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            )
        if stored_owner != owner_user_id:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNAUTHORIZED,
                media_id=media_ref.media_id,
            )
        mime_type = metadata.get("mime_type")
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNSUPPORTED_TYPE,
                media_id=media_ref.media_id,
            )
        try:
            data = content_path.read_bytes()
        except OSError:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            ) from None
        if not data:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.EMPTY,
                media_id=media_ref.media_id,
            )
        from .image_validation import validate_image_content

        validate_image_content(data, mime_type, media_ref.media_id)
        return ResolvedMedia(data=data, mime_type=mime_type)

    def ensure_dependencies(self) -> None:
        """建立永久媒体根目录并确认它是目录。"""
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise RuntimeError("media resolution root is not a directory")

    def _media_dir(self, media_ref: MediaRef) -> Path:
        try:
            media_id = str(UUID(media_ref.media_id))
        except ValueError:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            ) from None
        media_dir = (self._root / media_id).resolve()
        if media_dir.parent != self._root:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            )
        return media_dir
