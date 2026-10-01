"""把 Agent 的受控 MediaRef 解析为编码字节和 MIME。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol
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
    INVALID_DURATION = "MEDIA_INVALID_DURATION"


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

    def resolve(
        self,
        media_ref: MediaRef,
        *,
        owner_user_id: str,
        expected_kind: Literal["image", "audio"] | None = None,
    ) -> ResolvedMedia: ...

    def ensure_dependencies(self) -> None: ...


def create_media_resolver(config: dict | None = None) -> MediaResolver:
    """Build the configured neutral media adapter without a runtime container."""
    resolved = dict(config or {})
    return FilesystemMediaResolver(resolved) if resolved.get("root") else UnconfiguredMediaResolver(resolved)


class UnconfiguredMediaResolver:
    """尚无存储策略时使用的显式失败实现。"""

    def __init__(self, config: dict | None = None) -> None:
        self._config = dict(config or {})

    def resolve(
        self,
        media_ref: MediaRef,
        *,
        owner_user_id: str,
        expected_kind: Literal["image", "audio"] | None = None,
    ) -> ResolvedMedia:
        """拒绝解析，避免把缺省能力伪装成空媒体成功。"""
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.NOT_CONFIGURED,
            media_id=media_ref.media_id,
        )

    def ensure_dependencies(self) -> None:
        """缺省实现不拥有外部依赖。"""


class FilesystemMediaResolver:
    """从永久文件媒体库按 UUID media_id 读取图片或音频。"""

    def __init__(self, config: dict) -> None:
        root = config.get("root")
        if not isinstance(root, str) or not root.strip():
            raise ValueError("media_resolution.root must be a non-empty path")
        self._root = Path(root).resolve()

    def resolve(
        self,
        media_ref: MediaRef,
        *,
        owner_user_id: str,
        expected_kind: Literal["image", "audio"] | None = None,
    ) -> ResolvedMedia:
        """读取完整媒体并校验所有者、媒体类型和实际内容。"""
        media_dir = self._media_dir(media_ref)
        metadata_path = media_dir / "metadata.json"
        content_path = media_dir / "content.bin"
        if not metadata_path.is_file() or not content_path.is_file():
            self._raise(MediaResolutionErrorCode.UNKNOWN, media_ref)
        metadata = self._read_metadata(metadata_path, media_ref)
        stored_owner = metadata.get("owner_user_id")
        if not isinstance(stored_owner, str) or not stored_owner.strip():
            self._raise(MediaResolutionErrorCode.UNKNOWN, media_ref)
        if stored_owner != owner_user_id:
            self._raise(MediaResolutionErrorCode.UNAUTHORIZED, media_ref)
        media_kind, mime_type = self._media_type(metadata, media_ref)
        if expected_kind is not None and media_kind != expected_kind:
            self._raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_ref)
        try:
            data = content_path.read_bytes()
        except OSError:
            self._raise(MediaResolutionErrorCode.UNKNOWN, media_ref)
        if not data:
            self._raise(MediaResolutionErrorCode.EMPTY, media_ref)
        if media_kind == "image":
            from .image_validation import validate_image_content

            validate_image_content(data, mime_type, media_ref.media_id)
        else:
            from .audio_validation import parse_m4a_audio

            parse_m4a_audio(data, mime_type, media_ref.media_id)
        return ResolvedMedia(data=data, mime_type=mime_type)

    @classmethod
    def _read_metadata(cls, metadata_path: Path, media_ref: MediaRef) -> dict:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cls._raise(MediaResolutionErrorCode.UNKNOWN, media_ref)
        if not isinstance(metadata, dict):
            cls._raise(MediaResolutionErrorCode.UNKNOWN, media_ref)
        return metadata

    @classmethod
    def _media_type(cls, metadata: dict, media_ref: MediaRef) -> tuple[Literal["image", "audio"], str]:
        mime_type = metadata.get("mime_type")
        media_kind = metadata.get("media_kind")
        if media_kind is None and isinstance(mime_type, str):
            media_kind = "image" if mime_type.startswith("image/") else "audio" if mime_type == "audio/mp4" else None
        if media_kind not in {"image", "audio"} or not isinstance(mime_type, str):
            cls._raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_ref)
        return media_kind, mime_type

    @staticmethod
    def _raise(code: MediaResolutionErrorCode, media_ref: MediaRef) -> None:
        raise MediaResolutionError(code=code, media_id=media_ref.media_id)

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
