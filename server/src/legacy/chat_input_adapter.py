from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from src.domain.stimulus import PersistPolicy, SourceChannel, Stimulus, StimulusModality
from src.system.user_interface.types import WSEventType, WSMessage
from src.domain.chat import ChatInputEvent, ChatInputEventType
from src.agent_runtime.character_registry import DEFAULT_CHARACTER_ID


CHAT_RELATED_EVENT_TYPES = {
    WSEventType.USER_MESSAGE.value,
    WSEventType.USER_TEXT.value,
    WSEventType.USER_IMAGE.value,
    WSEventType.USER_TYPING.value,
    WSEventType.USER_IMAGE_SELECTING.value,
    WSEventType.USER_IMAGE_SELECTING_CANCEL.value,
    WSEventType.USER_TOUCH.value,
    "message",
    "chat_message",
    "chat",
}

MAX_TEXT_LENGTH = 20_000
MAX_IMAGE_BASE64_CHARS = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_TYPING_TEXT_LENGTH = 100_000
MAX_TARGET_CHARACTERS = 8
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/webp",
}
TARGET_CHARACTER_KEYS = (
    "target_character_ids",
    "target_characters",
    "character_ids",
    "target_character_id",
    "character_id",
)


def is_chat_related_ws_message(event: WSMessage) -> bool:
    return event.event_type in CHAT_RELATED_EVENT_TYPES


def validate_ws_chat_message(event: WSMessage) -> None:
    """Validate the real client payload before idempotency marking or ACK."""
    if not is_chat_related_ws_message(event):
        raise ValueError("unsupported chat event type")
    if not isinstance(event.payload, dict):
        raise TypeError("chat event payload must be an object")

    payload = event.payload
    _validate_target_character_ids(payload)

    if event.event_type == WSEventType.USER_IMAGE.value:
        _validate_image_payload(payload)
        return
    if event.event_type == WSEventType.USER_TYPING.value:
        text_length = payload.get("text_length")
        if type(text_length) is not int or not 0 <= text_length <= MAX_TYPING_TEXT_LENGTH:
            raise ValueError("text_length must be a non-negative integer")
        return
    if event.event_type == WSEventType.USER_TOUCH.value:
        _validate_touch_payload(payload)
        return
    if event.event_type in {
        WSEventType.USER_IMAGE_SELECTING.value,
        WSEventType.USER_IMAGE_SELECTING_CANCEL.value,
    }:
        return

    text = _extract_text(payload)
    if not text or len(text) > MAX_TEXT_LENGTH:
        raise ValueError("text message must be non-empty and within the size limit")
    if "is_proactive" in payload and type(payload["is_proactive"]) is not bool:
        raise ValueError("is_proactive must be a boolean")


def _validate_image_payload(payload: dict[str, Any]) -> None:
    image_base64 = payload.get("image_base64")
    mime_type = payload.get("mime_type")
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise ValueError("image_base64 is required")
    if len(image_base64) > MAX_IMAGE_BASE64_CHARS:
        raise ValueError("image payload exceeds the size limit")
    if not isinstance(mime_type, str) or mime_type.lower() not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("mime_type is not supported")
    if "image_client_path" in payload:
        path = payload["image_client_path"]
        if path is not None and (not isinstance(path, str) or len(path) > 4096):
            raise ValueError("image_client_path must be a string")

    encoded = image_base64.strip()
    if encoded.startswith("data:"):
        match = re.fullmatch(r"data:([^;,]+);base64,(.*)", encoded, flags=re.DOTALL)
        if match is None or match.group(1).lower() != mime_type.lower():
            raise ValueError("image data URI does not match mime_type")
        encoded = match.group(2)
    encoded = "".join(encoded.split())
    if not encoded:
        raise ValueError("image_base64 is empty")
    encoded += "=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_base64 is invalid") from exc
    if not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError("decoded image exceeds the size limit")


def _validate_touch_payload(payload: dict[str, Any]) -> None:
    touch_areas = payload.get("touchArea")
    if touch_areas is None:
        touch_areas = payload.get("touch_area")
    if isinstance(touch_areas, str):
        areas = [touch_areas]
    elif isinstance(touch_areas, list):
        areas = touch_areas
    else:
        raise ValueError("touch_area or touchArea is required")
    if not 1 <= len(areas) <= 16:
        raise ValueError("touch area count is invalid")
    if any(not isinstance(area, str) or not area.strip() or len(area) > 128 for area in areas):
        raise ValueError("touch areas must be non-empty strings")

    click_frequency = payload.get("click_frequency")
    if click_frequency is not None:
        if not isinstance(click_frequency, dict):
            raise ValueError("click_frequency must be an object")
        for value in click_frequency.values():
            if type(value) is not int or value < 0:
                raise ValueError("click_frequency values must be non-negative integers")


def _validate_target_character_ids(payload: dict[str, Any]) -> None:
    raw_targets = next(
        (payload[key] for key in TARGET_CHARACTER_KEYS if key in payload),
        None,
    )
    if raw_targets is None:
        return
    if isinstance(raw_targets, str):
        targets = [raw_targets]
    elif isinstance(raw_targets, (list, tuple)):
        targets = list(raw_targets)
    else:
        raise ValueError("target character ids must be a string or list")
    if not 1 <= len(targets) <= MAX_TARGET_CHARACTERS:
        raise ValueError("target character count is invalid")
    if any(
        not isinstance(target, str) or not target.strip() or len(target) > 64
        for target in targets
    ):
        raise ValueError("target character ids must be non-empty strings")


def ws_message_to_stimulus(
    event: WSMessage,
    *,
    sender_user_id: str | None = None,
    default_character_id: str = DEFAULT_CHARACTER_ID,
) -> Stimulus | None:
    """Normalize a legacy WebSocket message into a runtime Stimulus."""

    if not is_chat_related_ws_message(event):
        return None

    payload = event.payload if isinstance(event.payload, dict) else {}
    targets = _extract_target_character_ids(payload, default_character_id)

    if event.event_type == WSEventType.USER_TYPING.value:
        return Stimulus(
            source_channel=SourceChannel.WEBSOCKET,
            modality=StimulusModality.TYPING,
            payload=payload,
            sender_user_id=sender_user_id,
            target_character_ids=targets,
            raw_event_type=event.event_type,
            client_msg_id=event.client_msg_id,
            timestamp_ms=event.ts,
            persist_policy=PersistPolicy.EPHEMERAL_ONLY,
            ephemeral=True,
        )

    if event.event_type == WSEventType.USER_IMAGE_SELECTING.value:
        return Stimulus(
            source_channel=SourceChannel.WEBSOCKET,
            modality=StimulusModality.IMAGE_SELECTING,
            payload=payload,
            sender_user_id=sender_user_id,
            target_character_ids=targets,
            raw_event_type=event.event_type,
            client_msg_id=event.client_msg_id,
            timestamp_ms=event.ts,
            persist_policy=PersistPolicy.EPHEMERAL_ONLY,
            ephemeral=True,
        )

    if event.event_type == WSEventType.USER_IMAGE_SELECTING_CANCEL.value:
        return Stimulus(
            source_channel=SourceChannel.WEBSOCKET,
            modality=StimulusModality.IMAGE_SELECTING_CANCEL,
            payload=payload,
            sender_user_id=sender_user_id,
            target_character_ids=targets,
            raw_event_type=event.event_type,
            client_msg_id=event.client_msg_id,
            timestamp_ms=event.ts,
            persist_policy=PersistPolicy.EPHEMERAL_ONLY,
            ephemeral=True,
        )

    if event.event_type == WSEventType.USER_TOUCH.value:
        text = _build_touch_description(payload)
        return Stimulus(
            source_channel=SourceChannel.WEBSOCKET,
            modality=StimulusModality.TOUCH,
            text=f"[{text}]",
            payload=payload,
            sender_user_id=sender_user_id,
            target_character_ids=targets,
            raw_event_type=event.event_type,
            client_msg_id=event.client_msg_id,
            timestamp_ms=event.ts,
            persist_policy=PersistPolicy.EPHEMERAL_ONLY,
            ephemeral=True,
        )

    if event.event_type == WSEventType.USER_IMAGE.value:
        return Stimulus(
            source_channel=SourceChannel.WEBSOCKET,
            modality=StimulusModality.IMAGE,
            text="[用户发送了一张图片]",
            payload=payload,
            sender_user_id=sender_user_id,
            target_character_ids=targets,
            raw_event_type=event.event_type,
            client_msg_id=event.client_msg_id,
            timestamp_ms=event.ts,
            persist_policy=PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE,
        )

    return Stimulus(
        source_channel=SourceChannel.WEBSOCKET,
        modality=StimulusModality.TEXT,
        text=_extract_text(payload),
        payload=payload,
        sender_user_id=sender_user_id,
        target_character_ids=targets,
        raw_event_type=event.event_type,
        client_msg_id=event.client_msg_id,
        timestamp_ms=event.ts,
        persist_policy=PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE,
    )


def stimulus_to_chat_input_event(stimulus: Stimulus) -> ChatInputEvent | None:
    """Adapt a runtime Stimulus back into the legacy chat pipeline event."""

    event_type = _stimulus_modality_to_chat_event_type(stimulus.modality)
    if event_type is None:
        return None

    payload = dict(stimulus.payload or {})
    payload["target_character_ids"] = list(stimulus.target_character_ids)
    payload.setdefault("ephemeral", stimulus.ephemeral)
    payload.setdefault("persist_policy", stimulus.persist_policy.value)

    return ChatInputEvent(
        event_type=event_type,
        text=stimulus.text,
        payload=payload,
        client_msg_id=stimulus.client_msg_id,
        ts=stimulus.timestamp_ms,
    )


def _extract_target_character_ids(payload: dict[str, Any], default_character_id: str) -> tuple[str, ...]:
    raw_targets = (
        payload.get("target_character_ids")
        or payload.get("target_characters")
        or payload.get("character_ids")
        or payload.get("target_character_id")
        or payload.get("character_id")
    )
    if raw_targets is None:
        return (default_character_id,)
    if isinstance(raw_targets, str):
        targets = [raw_targets]
    elif isinstance(raw_targets, (list, tuple, set)):
        targets = [str(item) for item in raw_targets]
    else:
        targets = [str(raw_targets)]

    cleaned = tuple(target.strip() for target in targets if target and target.strip())
    return cleaned or (default_character_id,)


def _extract_text(payload: dict[str, Any]) -> str:
    for key in ("message", "text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_touch_description(payload: dict[str, Any]) -> str:
    touch_areas = payload.get("touchArea")
    if touch_areas is None:
        touch_area = payload.get("touch_area", "天依")
        touch_areas = [touch_area]
    if not isinstance(touch_areas, list):
        touch_areas = [touch_areas]

    area_to_description = {
        "head": "用户摸了摸天依的头",
        "body": "用户碰了碰天依的身体",
        "legs": "用户戳了戳天依的腿",
        "hands": "用户握了握天依的手",
        "头": "用户轻轻摸了摸天依的头",
        "辫子": "用户轻轻拉了拉天依的辫子",
        "耳机": "用户碰了碰天依的耳机",
        "袖": "用户扯了扯天依的袖子",
        "左腿": "用户戳了戳天依的腿",
        "右腿": "用户戳了戳天依的腿",
        "身体": "用户碰了碰天依的身体",
        "裙子": "用户扯了扯天依的裙子",
        "8": "用户戳了戳天依",
        "左手": "用户握了握天依的左手",
        "右手": "用户握了握天依的右手",
    }
    descriptions = [
        area_to_description.get(area, f"用户碰了碰天依的{area}")
        for area in touch_areas
    ]
    text = "；".join(descriptions)
    click_frequency = payload.get("click_frequency")
    if click_frequency:
        count_10s = click_frequency.get("count_10s", 0)
        count_30s = click_frequency.get("count_30s", 0)
        text += f"（点击频率：最近10秒{count_10s}次，最近30秒{count_30s}次）"
    return text


def _stimulus_modality_to_chat_event_type(modality: StimulusModality) -> ChatInputEventType | None:
    mapping = {
        StimulusModality.TEXT: ChatInputEventType.USER_TEXT,
        StimulusModality.IMAGE: ChatInputEventType.USER_IMAGE,
        StimulusModality.TYPING: ChatInputEventType.USER_TYPING,
        StimulusModality.TOUCH: ChatInputEventType.USER_TOUCH,
        StimulusModality.IMAGE_SELECTING: ChatInputEventType.USER_IMAGE_SELECTING,
        StimulusModality.IMAGE_SELECTING_CANCEL: ChatInputEventType.USER_IMAGE_SELECTING_CANCEL,
        StimulusModality.SYSTEM_EVENT: ChatInputEventType.SYSTEM_EVENT,
    }
    return mapping.get(modality)
