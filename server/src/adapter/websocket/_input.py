"""WebSocket 业务输入的内部校验和刺激转换。"""

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import src.domain.agent as d
from src.capabilities.media_resolution import PermanentMediaStore
from src.system.user_interface.types import WSMessage

_TEXT_EVENTS = frozenset({"user_text", "user_message", "message", "chat_message", "chat"})
_INPUT_EVENTS = _TEXT_EVENTS | {"user_typing", "user_image"}
_TARGET_KEYS = ("target_character_ids", "target_characters", "character_ids",
                "target_character_id", "character_id")


def convert_input(
    event: WSMessage,
    user_id: str,
    default_character_id: str,
    media_store: PermanentMediaStore | None = None,
) -> d.Stimulus:
    """用认证身份转换输入；图片先由 Adapter 永久保存并收窄为 MediaRef。"""
    if event.event_type not in _INPUT_EVENTS:
        raise ValueError("unsupported business event")
    if not isinstance(event.payload, dict):
        raise ValueError("payload must be an object")
    if not isinstance(event.client_msg_id, str) or not event.client_msg_id.strip() or len(event.client_msg_id) > 128:
        raise ValueError("invalid client_msg_id")
    payload = event.payload
    raw_targets = next((payload[key] for key in _TARGET_KEYS if key in payload), None)
    if raw_targets is None:
        raw_targets = [default_character_id]
    elif isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    if not isinstance(raw_targets, (list, tuple)) or not 1 <= len(raw_targets) <= 8:
        raise ValueError("invalid target characters")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 64 for item in raw_targets):
        raise ValueError("invalid target character")
    targets = tuple(dict.fromkeys(item.strip() for item in raw_targets))
    if event.ts is None:
        occurred_at = datetime.now(timezone.utc)
    else:
        if type(event.ts) is not int or event.ts < 0:
            raise ValueError("invalid timestamp")
        try:
            occurred_at = datetime.fromtimestamp(event.ts / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError("invalid timestamp") from error
    typing = event.event_type == "user_typing"
    values = dict(
        stimulus_id=str(uuid5(NAMESPACE_URL, json.dumps(["websocket-input", user_id, event.client_msg_id]))),
        schema_version=1, occurred_at=occurred_at, source=d.StimulusSource.USER,
        target_character_ids=targets, user_id=user_id, ephemeral=typing,
    )
    if typing:
        length = payload.get("text_length")
        if type(length) is not int or not 0 <= length <= 100_000:
            raise ValueError("invalid text_length")
        return d.UserTyping(**values, text_length=length)
    if event.event_type == "user_image":
        if media_store is None:
            raise ValueError("media store is not configured")
        image_base64 = payload.get("image_base64")
        mime_type = payload.get("mime_type")
        if not isinstance(image_base64, str) or not image_base64.strip():
            raise ValueError("invalid image_base64")
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            raise ValueError("invalid image mime_type")
        encoded = image_base64.strip()
        if encoded.startswith("data:"):
            match = re.fullmatch(r"data:([^;,]+);base64,(.*)", encoded, flags=re.DOTALL)
            if match is None or match.group(1).lower() != mime_type.lower():
                raise ValueError("image data URI does not match mime_type")
            encoded = match.group(2)
        encoded = "".join(encoded.split())
        encoded += "=" * (-len(encoded) % 4)
        try:
            image_data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("invalid image_base64") from error
        if not image_data:
            raise ValueError("empty image")
        media_ref = media_store.persist_image(
            user_id=user_id,
            client_msg_id=event.client_msg_id,
            data=image_data,
            mime_type=mime_type.lower(),
        )
        caption = payload.get("caption")
        if caption is not None and (not isinstance(caption, str) or not caption.strip()):
            raise ValueError("invalid image caption")
        return d.ImageMessage(
            **values,
            media_ref=media_ref,
            caption=caption.strip() if isinstance(caption, str) else None,
            client_msg_id=event.client_msg_id,
        )
    text = next((payload[key].strip() for key in ("message", "text", "content")
                 if isinstance(payload.get(key), str) and payload[key].strip()), "")
    if not text or len(text) > 20_000:
        raise ValueError("invalid text")
    if "is_proactive" in payload and type(payload["is_proactive"]) is not bool:
        raise ValueError("invalid is_proactive")
    return d.TextMessage(**values, text=text, client_msg_id=event.client_msg_id)
