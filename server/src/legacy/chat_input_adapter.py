from __future__ import annotations

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


def is_chat_related_ws_message(event: WSMessage) -> bool:
    return event.event_type in CHAT_RELATED_EVENT_TYPES


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
    payload.setdefault("target_character_ids", list(stimulus.target_character_ids))
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
