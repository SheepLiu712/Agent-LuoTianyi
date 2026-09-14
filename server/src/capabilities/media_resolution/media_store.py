"""Adapter 使用的永久文件媒体存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

from src.domain.agent import MediaRef


class PermanentMediaStore:
    """以认证用户和客户端消息身份永久保存原始媒体。"""

    def __init__(self, config: dict) -> None:
        root = config.get("root")
        if not isinstance(root, str) or not root.strip():
            raise ValueError("media_store.root must be a non-empty path")
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def persist_image(
        self,
        *,
        user_id: str,
        client_msg_id: str,
        data: bytes,
        mime_type: str,
    ) -> MediaRef:
        """永久写入图片并返回可重复生成的窄 MediaRef。"""
        media_id = str(uuid5(
            NAMESPACE_URL,
            json.dumps(["websocket-media", user_id, client_msg_id]),
        ))
        with self._lock:
            media_dir = self._root / media_id
            media_dir.mkdir(exist_ok=True)
            content_path = media_dir / "content.bin"
            metadata_path = media_dir / "metadata.json"
            if content_path.exists() or metadata_path.exists():
                if (
                    content_path.read_bytes() != data
                    or json.loads(metadata_path.read_text(encoding="utf-8"))
                    != {"mime_type": mime_type}
                ):
                    raise ValueError("media identity content conflict")
                return MediaRef(media_id=media_id)
            content_temp = media_dir / "content.tmp"
            metadata_temp = media_dir / "metadata.tmp"
            content_temp.write_bytes(data)
            metadata_temp.write_text(
                json.dumps({"mime_type": mime_type}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(content_temp, content_path)
            os.replace(metadata_temp, metadata_path)
        return MediaRef(media_id=media_id)
