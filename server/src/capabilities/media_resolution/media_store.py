"""Adapter 使用的永久文件媒体存储。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from src.domain.agent import MediaRef

from .image_validation import validate_image_content
from .media_resolver import MediaResolutionError, MediaResolutionErrorCode


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
        return MediaRef(media_id=str(uuid5(
            NAMESPACE_URL,
            json.dumps(["websocket-media", user_id, client_msg_id]),
        )))

    def persist_image(
        self,
        *,
        media_ref: MediaRef,
        owner_user_id: str,
        data: bytes,
        mime_type: str,
    ) -> None:
        """校验后以完整目录原子发布；重放只接受相同所有者与内容。"""
        if len(data) > self.max_bytes:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.TOO_LARGE,
                media_id=media_ref.media_id,
            )
        validate_image_content(data, mime_type, media_ref.media_id)
        expected_metadata = {
            "mime_type": mime_type,
            "owner_user_id": owner_user_id,
        }
        final_dir = self._root / media_ref.media_id
        if final_dir.exists():
            self._verify_replay(final_dir, data, expected_metadata, media_ref)
            return
        staging_dir = Path(tempfile.mkdtemp(prefix=".media-", dir=self._root))
        try:
            (staging_dir / "content.bin").write_bytes(data)
            (staging_dir / "metadata.json").write_text(
                json.dumps(expected_metadata, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                os.rename(staging_dir, final_dir)
            except FileExistsError:
                self._verify_replay(final_dir, data, expected_metadata, media_ref)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

    @staticmethod
    def _verify_replay(
        final_dir: Path,
        data: bytes,
        expected_metadata: dict[str, str],
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
        if existing_data != data or existing_metadata != expected_metadata:
            raise ValueError("media identity content conflict")
