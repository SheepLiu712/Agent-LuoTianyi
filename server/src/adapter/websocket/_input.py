"""WebSocket 业务输入的内部校验和刺激转换。"""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import src.domain.agent as d
from src.infrastructure.media import (
    MediaResolutionError,
    MediaResolutionErrorCode,
    PermanentMediaStore,
)
from src.web.websocket import BUSINESS_INPUT_EVENTS, WSMessage

_TEXT_EVENTS = frozenset({"user_text", "user_message", "message", "chat_message", "chat"})
_INPUT_EVENTS = BUSINESS_INPUT_EVENTS
_TARGET_KEYS = (
    "target_character_ids",
    "target_characters",
    "character_ids",
    "target_character_id",
    "character_id",
)


@dataclass(frozen=True)
class PreparedInput:
    """无需媒体物化即可完成准入判断的候选刺激。"""

    stimulus: d.Stimulus
    image_base64: str | None = None
    mime_type: str | None = None


def prepare_input(
    event: WSMessage,
    user_id: str,
    default_character_id: str,
    media_store: PermanentMediaStore | None = None,
) -> PreparedInput:
    """校验输入信封并创建准入候选；不解码或写入图片。"""
    payload = _validate_envelope(event)
    targets = _target_characters(payload, default_character_id)
    typing = event.event_type == "user_typing"
    values = _stimulus_values(event, user_id, targets, ephemeral=typing)
    if typing:
        return _prepare_typing(payload, values)
    if event.event_type == "user_image":
        return _prepare_image(event, payload, values, user_id, media_store)
    return _prepare_text(event, payload, values)


def _validate_envelope(event: WSMessage) -> dict:
    if event.event_type not in _INPUT_EVENTS:
        raise ValueError("unsupported business event")
    if not isinstance(event.payload, dict):
        raise TypeError("payload must be an object")
    if not isinstance(event.client_msg_id, str) or not event.client_msg_id.strip() or len(event.client_msg_id) > 128:
        raise ValueError("invalid client_msg_id")
    return event.payload


def _target_characters(payload: dict, default_character_id: str) -> tuple[str, ...]:
    raw_targets = next((payload[key] for key in _TARGET_KEYS if key in payload), None)
    if raw_targets is None:
        raw_targets = [default_character_id]
    elif isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    if not isinstance(raw_targets, (list, tuple)) or not 1 <= len(raw_targets) <= 8:
        raise ValueError("invalid target characters")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 64 for item in raw_targets):
        raise ValueError("invalid target character")
    return tuple(dict.fromkeys(item.strip() for item in raw_targets))


def _stimulus_values(
    event: WSMessage,
    user_id: str,
    targets: tuple[str, ...],
    *,
    ephemeral: bool,
) -> dict:
    return {
        "stimulus_id": str(
            uuid5(
                NAMESPACE_URL,
                json.dumps(["websocket-input", user_id, event.client_msg_id]),
            )
        ),
        "schema_version": 1,
        "occurred_at": _occurred_at(event.ts),
        "source": d.StimulusSource.USER,
        "target_character_ids": targets,
        "user_id": user_id,
        "ephemeral": ephemeral,
    }


def _prepare_typing(payload: dict, values: dict) -> PreparedInput:
    length = payload.get("text_length")
    if type(length) is not int or not 0 <= length <= 100_000:
        raise ValueError("invalid text_length")
    return PreparedInput(d.UserTyping(**values, text_length=length))


def _prepare_image(
    event: WSMessage,
    payload: dict,
    values: dict,
    user_id: str,
    media_store: PermanentMediaStore | None,
) -> PreparedInput:
    if media_store is None:
        raise ValueError("media store is not configured")
    image_base64 = payload.get("image_base64")
    mime_type = payload.get("mime_type")
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise ValueError("invalid image_base64")
    if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
        raise ValueError("invalid image mime_type")
    media_ref = media_store.mint_ref(user_id=user_id, client_msg_id=event.client_msg_id)
    if len(image_base64.encode("utf-8")) > media_store.max_encoded_bytes:
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.TOO_LARGE,
            media_id=media_ref.media_id,
        )
    stimulus = d.ImageMessage(
        **values,
        media_ref=media_ref,
        client_msg_id=event.client_msg_id,
    )
    return PreparedInput(stimulus, image_base64.strip(), mime_type.lower())


def _prepare_text(event: WSMessage, payload: dict, values: dict) -> PreparedInput:
    text = next(
        (
            payload[key].strip()
            for key in ("message", "text", "content")
            if isinstance(payload.get(key), str) and payload[key].strip()
        ),
        "",
    )
    if not text or len(text) > 20_000:
        raise ValueError("invalid text")
    if "is_proactive" in payload and type(payload["is_proactive"]) is not bool:
        raise ValueError("invalid is_proactive")
    return PreparedInput(
        d.TextMessage(
            **values,
            text=text,
            client_msg_id=event.client_msg_id,
        )
    )


def materialize_image(candidate: PreparedInput, media_store: PermanentMediaStore) -> None:
    """解码、校验并永久写入已通过 Stage 准入的图片。"""
    if candidate.image_base64 is None or candidate.mime_type is None:
        return
    encoded = candidate.image_base64
    if encoded.startswith("data:"):
        match = re.fullmatch(r"data:([^;,]+);base64,(.*)", encoded, flags=re.DOTALL)
        if match is None or match.group(1).lower() != candidate.mime_type:
            raise ValueError("image data URI does not match mime_type")
        encoded = match.group(2)
    encoded = "".join(encoded.split())
    encoded += "=" * (-len(encoded) % 4)
    try:
        image_data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        image = candidate.stimulus
        media_id = image.media_ref.media_id if isinstance(image, d.ImageMessage) else "invalid"
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.UNKNOWN,
            media_id=media_id,
        ) from error
    if len(image_data) > media_store.max_bytes:
        image = candidate.stimulus
        media_id = image.media_ref.media_id if isinstance(image, d.ImageMessage) else "invalid"
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.TOO_LARGE,
            media_id=media_id,
        )
    image = candidate.stimulus
    if not isinstance(image, d.ImageMessage):
        raise TypeError("materialized media must belong to an image stimulus")
    media_store.persist_image(
        media_ref=image.media_ref,
        owner_user_id=image.user_id or "",
        data=image_data,
        mime_type=candidate.mime_type,
    )


def convert_input(event: WSMessage, user_id: str, default_character_id: str) -> d.Stimulus:
    """兼容文本与打字的同步转换；图片必须经 Adapter 的异步物化路径。"""
    return prepare_input(event, user_id, default_character_id).stimulus


def _occurred_at(timestamp: int | None) -> datetime:
    if timestamp is None:
        return datetime.now(timezone.utc)
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("invalid timestamp")
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("invalid timestamp") from error
