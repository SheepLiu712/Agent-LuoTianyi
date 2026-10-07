"""Adapter 使用的永久文件媒体存储。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from src.domain.agent import MediaRef

from .audio_validation import parse_m4a_audio
from .image_validation import validate_image_content
from .media_resolver import MediaResolutionError, MediaResolutionErrorCode


@dataclass(frozen=True)
class MediaDeletionFailure:
    media_id: str
    reason: str


@dataclass(frozen=True)
class MediaDeletionReport:
    deleted_count: int
    failures: tuple[MediaDeletionFailure, ...]


class PermanentMediaStore:
    """以认证用户和客户端消息身份永久保存已校验媒体。"""

    def __init__(self, config: dict) -> None:
        root = config.get("root")
        max_bytes = config.get("max_bytes", 6 * 1024 * 1024)
        max_encoded_bytes = config.get("max_encoded_bytes", 8 * 1024 * 1024)
        if not isinstance(root, str) or not root.strip():
            raise ValueError("media_store.root must be a non-empty path")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("media_store.max_bytes must be a positive integer")
        if type(max_encoded_bytes) is not int or max_encoded_bytes <= 0:
            raise ValueError("media_store.max_encoded_bytes must be a positive integer")
        self._root = Path(root).resolve()
        self.max_bytes = max_bytes
        self.max_encoded_bytes = max_encoded_bytes
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def mint_ref(*, user_id: str, client_msg_id: str) -> MediaRef:
        """按认证上传者和客户端消息稳定生成永久媒体身份。"""
        return MediaRef(
            media_id=str(
                uuid5(
                    NAMESPACE_URL,
                    json.dumps(["websocket-media", user_id, client_msg_id]),
                )
            )
        )

    def persist_image(
        self,
        *,
        media_ref: MediaRef,
        owner_user_id: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> None:
        """校验后以完整目录原子发布；重放只接受相同所有者与内容。"""
        if len(data) > self.max_bytes:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.TOO_LARGE,
                media_id=media_ref.media_id,
            )
        mime_type = validate_image_content(data, mime_type, media_ref.media_id)
        expected_metadata: dict[str, object] = {
            "media_kind": "image",
            "mime_type": mime_type,
            "owner_user_id": owner_user_id,
            "byte_length": len(data),
            "sha256": sha256(data).hexdigest(),
        }
        self._persist(media_ref=media_ref, data=data, metadata=expected_metadata)

    def persist_audio(
        self,
        *,
        media_ref: MediaRef,
        owner_user_id: str,
        data: bytes,
        mime_type: str,
        duration_ms: int,
    ) -> None:
        """校验 M4A/AAC-LC 后以完整目录原子发布。"""
        if len(data) > self.max_bytes:
            raise MediaResolutionError(code=MediaResolutionErrorCode.TOO_LARGE, media_id=media_ref.media_id)
        parsed = parse_m4a_audio(data, mime_type, media_ref.media_id)
        if type(duration_ms) is not int or duration_ms != parsed.duration_ms:
            raise MediaResolutionError(code=MediaResolutionErrorCode.INVALID_DURATION, media_id=media_ref.media_id)
        metadata: dict[str, object] = {
            "media_kind": "audio",
            "mime_type": mime_type,
            "owner_user_id": owner_user_id,
            "byte_length": len(data),
            "sha256": sha256(data).hexdigest(),
            "duration_ms": parsed.duration_ms,
            "container": parsed.container,
            "codec": parsed.codec,
        }
        self._persist(media_ref=media_ref, data=data, metadata=metadata)

    def read_audio_receipt(self, *, media_ref: MediaRef, owner_user_id: str) -> dict | None:
        """读取音频附属凭据；仅校验媒体所有权，凭据的业务含义由调用者解释。"""
        directory = self._owned_audio_directory(media_ref, owner_user_id)
        if directory is None:
            return None
        path = directory / "ingress_receipt.json"
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(receipt, dict):
            raise ValueError("invalid audio receipt")
        return receipt

    def write_audio_receipt(self, *, media_ref: MediaRef, owner_user_id: str, receipt: dict) -> None:
        """原子写入已存在音频的附属凭据；随媒体目录一同删除。"""
        directory = self._owned_audio_directory(media_ref, owner_user_id)
        if directory is None:
            raise ValueError("audio media is missing")
        fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(receipt, stream, ensure_ascii=False)
            os.replace(temporary, directory / "ingress_receipt.json")
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _owned_audio_directory(self, media_ref: MediaRef, owner_user_id: str) -> Path | None:
        directory = self._root / str(UUID(media_ref.media_id))
        try:
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if (
            not isinstance(metadata, dict)
            or metadata.get("owner_user_id") != owner_user_id
            or metadata.get("media_kind") != "audio"
        ):
            raise ValueError("audio media identity mismatch")
        return directory if (directory / "content.bin").is_file() else None

    def delete_owned_by(self, *, owner_user_id: str) -> MediaDeletionReport:
        """幂等删除所有属于指定用户的完整媒体目录。"""
        deleted_count = 0
        failures: list[MediaDeletionFailure] = []
        for media_dir in self._root.iterdir():
            if not media_dir.is_dir() or media_dir.name.startswith(".media-"):
                continue
            try:
                UUID(media_dir.name)
            except ValueError:
                continue
            try:
                metadata = json.loads((media_dir / "metadata.json").read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as error:
                failures.append(MediaDeletionFailure(media_id=media_dir.name, reason=type(error).__name__))
                continue
            if not isinstance(metadata, dict) or metadata.get("owner_user_id") != owner_user_id:
                continue
            try:
                shutil.rmtree(media_dir)
            except FileNotFoundError:
                continue
            except OSError as error:
                failures.append(MediaDeletionFailure(media_id=media_dir.name, reason=type(error).__name__))
            else:
                deleted_count += 1
        return MediaDeletionReport(deleted_count=deleted_count, failures=tuple(failures))

    def _persist(self, *, media_ref: MediaRef, data: bytes, metadata: dict[str, object]) -> None:
        final_dir = self._root / media_ref.media_id
        if final_dir.exists():
            self._verify_replay(final_dir, data, metadata, media_ref)
            return
        staging_dir = Path(tempfile.mkdtemp(prefix=".media-", dir=self._root))
        try:
            (staging_dir / "content.bin").write_bytes(data)
            (staging_dir / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                os.rename(staging_dir, final_dir)
            except FileExistsError:
                self._verify_replay(final_dir, data, metadata, media_ref)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

    @staticmethod
    def _verify_replay(
        final_dir: Path,
        data: bytes,
        expected_metadata: dict[str, object],
        media_ref: MediaRef,
    ) -> None:
        content_path = final_dir / "content.bin"
        metadata_path = final_dir / "metadata.json"
        try:
            existing_data = content_path.read_bytes()
            existing_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNKNOWN,
                media_id=media_ref.media_id,
            ) from None
        required_identity = {"mime_type", "owner_user_id"}
        identity_matches = all(existing_metadata.get(key) == expected_metadata[key] for key in required_identity)
        new_fields_match = all(
            key not in existing_metadata or existing_metadata[key] == value for key, value in expected_metadata.items()
        )
        if existing_data != data or not identity_matches or not new_fields_match:
            raise ValueError("media identity content conflict")
