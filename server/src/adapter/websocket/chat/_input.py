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

from ._messages import _BUSINESS_INPUT_EVENTS, WSMessage
from ._voice_upload_helper import VoiceUploadAssembler, VoiceUploadError


async def process_input(
    event: WSMessage,
    user_id: str,
    default_character_id: str,
    media_store: PermanentMediaStore | None,
    voice_uploads: VoiceUploadAssembler,
) -> tuple[d.Stimulus | None, dict]:
    """统一处理普通输入和语音上传，返回 (领域刺激或 None, 状态字典)，不执行 Stage 准入或投递。

    状态 state 为 complete、partial、duplicate 或 error；complete 仍须由 Adapter 实际投递成功后确认。
    ack_payload 和 duplicate 是可选应答元数据；error 保存处理异常。语音取消可携带原绑定标识。
    调用方须串行完成处理、准入及上传候选状态的提交或丢弃。"""
    try:
        if event.event_type == "user_voice":
            targets = input_targets(event, default_character_id)
            return await voice_uploads.process(event=event, user_id=user_id, character_id=targets[0])
        candidate = _prepare_input(event, user_id, default_character_id, media_store)
        return candidate.stimulus, {"state": "complete"}
    except (MediaResolutionError, VoiceUploadError, KeyError, TypeError, ValueError) as error:
        return None, {"state": "error", "error": error}


def input_targets(event: WSMessage, default_character_id: str) -> tuple[str, ...]:
    """校验业务消息信封并取得目标角色；语音上传只允许一个目标角色。"""
    payload = _validate_envelope(event)
    targets = _target_characters(payload, default_character_id)
    if event.event_type == "user_voice" and len(targets) != 1:
        raise ValueError("voice upload requires exactly one target character")
    return targets


def materialize_input(event: WSMessage, stimulus: d.Stimulus, media_store: PermanentMediaStore | None) -> None:
    """在初步准入后完成图片解码和存储；其它刺激无需处理，投递仍由 Adapter 执行。"""
    if not isinstance(stimulus, d.ImageMessage):
        return
    if media_store is None:
        raise ValueError("media store is not configured")
    payload = event.payload
    mime_type = payload.get("mime_type")
    candidate = _PreparedInput(
        stimulus,
        payload["image_base64"].strip(),
        mime_type.strip().lower() if mime_type else None,
    )
    _materialize_image(candidate, media_store)


_TEXT_EVENTS = frozenset({"user_text", "user_message", "message", "chat_message", "chat"})
_INPUT_EVENTS = _BUSINESS_INPUT_EVENTS
_TARGET_KEYS = (
    "target_character_ids",
    "target_characters",
    "character_ids",
    "target_character_id",
    "character_id",
)


@dataclass(frozen=True)
class _PreparedInput:
    """无需媒体物化即可完成准入判断的候选刺激。"""

    stimulus: d.Stimulus
    image_base64: str | None = None
    mime_type: str | None = None


def _prepare_input(
    event: WSMessage,
    user_id: str,
    default_character_id: str,
    media_store: PermanentMediaStore | None = None,
) -> _PreparedInput:
    """校验输入信封并创建准入候选；不解码或写入图片。"""
    payload = _validate_envelope(event)
    targets = _target_characters(payload, default_character_id)
    ephemeral = event.event_type in {
        "user_typing",
        "user_touch",
        "user_image_selecting",
        "user_image_selecting_cancel",
        "user_voice_recording_started",
        "user_voice_recording_cancelled",
    }
    values = _stimulus_values(event, user_id, targets, ephemeral=ephemeral)
    if event.event_type == "user_typing":
        return _prepare_typing(payload, values)
    if event.event_type == "user_image":
        return _prepare_image(event, payload, values, user_id, media_store)
    if event.event_type == "user_touch":
        return _prepare_touch(payload, values)
    if event.event_type == "user_image_selecting":
        return _PreparedInput(d.ImageSelectionOpened(**values))
    if event.event_type == "user_image_selecting_cancel":
        return _PreparedInput(d.ImageSelectionClosed(**values))
    if event.event_type == "user_voice_recording_started":
        return _PreparedInput(d.VoiceRecordingStarted(**values, recording_id=_recording_id(payload)))
    if event.event_type == "user_voice_recording_cancelled":
        return _PreparedInput(d.VoiceRecordingCancelled(**values, recording_id=_recording_id(payload)))
    if event.event_type == "user_voice":
        raise ValueError("user_voice protocol is not implemented")
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


def _prepare_typing(payload: dict, values: dict) -> _PreparedInput:
    length = payload.get("text_length")
    if type(length) is not int or not 0 <= length <= 100_000:
        raise ValueError("invalid text_length")
    return _PreparedInput(d.UserTyping(**values, text_length=length))


def _recording_id(payload: dict) -> str:
    recording_id = payload.get("recording_id")
    if not isinstance(recording_id, str) or not recording_id.strip() or len(recording_id) > 128:
        raise ValueError("invalid recording_id")
    return recording_id


def _prepare_touch(payload: dict, values: dict) -> _PreparedInput:
    raw_regions = payload.get("touch_area", payload.get("touchArea"))
    if isinstance(raw_regions, str):
        raw_regions = [raw_regions]
    if not isinstance(raw_regions, (list, tuple)) or not 1 <= len(raw_regions) <= 16:
        raise ValueError("invalid touch areas")
    if any(not isinstance(region, str) or not region.strip() or len(region) > 64 for region in raw_regions):
        raise ValueError("invalid touch area")
    body_regions = tuple(d.BodyRegion(value=region) for region in dict.fromkeys(r.strip() for r in raw_regions))

    raw_frequency = payload.get("click_frequency")
    click_frequency = None
    if raw_frequency is not None:
        if not isinstance(raw_frequency, dict):
            raise ValueError("invalid click frequency")
        count_10s = raw_frequency.get("count_10s")
        count_30s = raw_frequency.get("count_30s")
        if type(count_10s) is not int or type(count_30s) is not int:
            raise ValueError("invalid click frequency")
        click_frequency = d.TouchClickFrequency(count_10s=count_10s, count_30s=count_30s)
    return _PreparedInput(
        d.TouchInteraction(
            **values,
            body_regions=body_regions,
            click_frequency=click_frequency,
        )
    )


def _prepare_image(
    event: WSMessage,
    payload: dict,
    values: dict,
    user_id: str,
    media_store: PermanentMediaStore | None,
) -> _PreparedInput:
    if media_store is None:
        raise MediaResolutionError(
            code=MediaResolutionErrorCode.NOT_CONFIGURED,
            media_id=event.client_msg_id or "unassigned",
        )
    image_base64 = payload.get("image_base64")
    mime_type = payload.get("mime_type")
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise ValueError("invalid image_base64")
    if mime_type is not None and not isinstance(mime_type, str):
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
    return _PreparedInput(stimulus, image_base64.strip(), mime_type.strip().lower() if mime_type else None)


def _prepare_text(event: WSMessage, payload: dict, values: dict) -> _PreparedInput:
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
    return _PreparedInput(
        d.TextMessage(
            **values,
            text=text,
            client_msg_id=event.client_msg_id,
        )
    )


def _materialize_image(candidate: _PreparedInput, media_store: PermanentMediaStore) -> None:
    """解码、校验并永久写入已通过 Stage 准入的图片。"""
    if candidate.image_base64 is None:
        return
    encoded = candidate.image_base64
    if encoded.startswith("data:"):
        match = re.fullmatch(r"data:([^;,]+);base64,(.*)", encoded, flags=re.DOTALL)
        if match is None:
            raise ValueError("invalid image data URI")
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


def _convert_input(event: WSMessage, user_id: str, default_character_id: str) -> d.Stimulus:
    """兼容文本与打字的同步转换；图片必须经 Adapter 的异步物化路径。"""
    return _prepare_input(event, user_id, default_character_id).stimulus


def _occurred_at(timestamp: int | None) -> datetime:
    if timestamp is None:
        return datetime.now(timezone.utc)
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("invalid timestamp")
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("invalid timestamp") from error
