"""语音分片上传的校验、组装、幂等与最终投递。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import src.domain.agent as d
from src.infrastructure.media import (
    MediaResolutionError,
    MediaResolutionErrorCode,
    PermanentMediaStore,
    parse_m4a_audio,
)
from src.web.websocket import WSMessage

MAX_CHUNK_BYTES = 48 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_CHUNKS = 32


class StimulusSink(Protocol):
    def can_accept(self, stimulus: d.Stimulus) -> bool: ...

    def submit(self, stimulus: d.Stimulus) -> bool: ...


@dataclass(frozen=True)
class VoiceUploadError(Exception):
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class VoiceUploadAck:
    payload: dict[str, object] = field(default_factory=dict)
    duplicate: bool = False


@dataclass
class _Upload:
    user_id: str
    character_id: str
    upload_id: str
    mime_type: str
    container: str
    codec: str
    byte_length: int
    total_chunks: int
    sink: StimulusSink
    created_at: float
    chunks: dict[int, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class _Completed:
    parameters: tuple[object, ...]
    chunk_digests: tuple[bytes, ...]
    message_uuid: str
    duration_ms: int
    completed_at: float


class VoiceUploadAssembler:
    """隐藏语音上传状态机，并只在 finalize 完成后暴露领域消息。"""

    def __init__(
        self,
        media_store: PermanentMediaStore | None,
        *,
        max_incomplete: int = 128,
        ttl_seconds: float = 600.0,
    ) -> None:
        if type(max_incomplete) is not int or max_incomplete <= 0:
            raise ValueError("voice upload max_incomplete must be a positive integer")
        if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
            raise ValueError("voice upload ttl_seconds must be positive")
        self._media_store = media_store
        self._max_incomplete = max_incomplete
        self._ttl_seconds = float(ttl_seconds)
        self._uploads: dict[tuple[str, str], _Upload] = {}
        self._completed: dict[tuple[str, str], _Completed] = {}
        self._lock = asyncio.Lock()

    async def process(
        self,
        *,
        event: WSMessage,
        user_id: str,
        character_id: str,
        sink: StimulusSink,
    ) -> VoiceUploadAck:
        """执行一个 begin/chunk/finalize/abort 操作并返回阶段 ACK 数据。"""
        async with self._lock:
            self._cleanup_expired(time.monotonic())
            payload = _payload(event)
            phase = payload.get("phase")
            upload_id = _uuid_field(payload, "upload_id")
            if phase == "begin":
                return self._begin(event, payload, user_id, character_id, upload_id, sink)
            if phase == "chunk":
                return self._chunk(payload, user_id, upload_id)
            if phase == "finalize":
                return await self._finalize(event, payload, user_id, character_id, upload_id)
            if phase == "abort":
                return self._abort(event, payload, user_id, upload_id)
            raise VoiceUploadError("BAD_MESSAGE", "invalid voice upload phase")

    def _begin(
        self,
        event: WSMessage,
        payload: dict,
        user_id: str,
        character_id: str,
        upload_id: str,
        sink: StimulusSink,
    ) -> VoiceUploadAck:
        mime_type = _string_field(payload, "mime_type")
        container = _string_field(payload, "container")
        codec = _string_field(payload, "codec")
        byte_length = _int_field(payload, "byte_length", minimum=1)
        total_chunks = _int_field(payload, "total_chunks", minimum=1)
        if byte_length > MAX_TOTAL_BYTES or total_chunks > MAX_CHUNKS:
            raise VoiceUploadError("VOICE_TOO_LARGE", "voice upload exceeds size or chunk limits")
        if (mime_type, container, codec) != ("audio/mp4", "m4a", "aac_lc"):
            raise VoiceUploadError("VOICE_UNSUPPORTED_MEDIA", "voice media declaration is unsupported")
        key = (user_id, upload_id)
        parameters = (character_id, mime_type, container, codec, byte_length, total_chunks)
        completed = self._completed.get(key)
        if completed is not None:
            if completed.parameters != parameters:
                raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload identity conflicts with completed media")
            return VoiceUploadAck(duplicate=True)
        existing = self._uploads.get(key)
        if existing is not None:
            existing_parameters = (
                existing.character_id,
                existing.mime_type,
                existing.container,
                existing.codec,
                existing.byte_length,
                existing.total_chunks,
            )
            if existing_parameters != parameters:
                raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload parameters changed")
            return VoiceUploadAck(duplicate=True)
        if any(upload.user_id == user_id for upload in self._uploads.values()):
            raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "user already has an incomplete voice upload")
        if len(self._uploads) >= self._max_incomplete:
            raise VoiceUploadError("OVERLOADED", "voice upload capacity is full", retryable=True)
        stimulus = d.VoiceRecordingCommitted(
            **_stimulus_fields(event, user_id, character_id, ephemeral=True),
            upload_id=upload_id,
        )
        if not sink.can_accept(stimulus) or not sink.submit(stimulus):
            raise VoiceUploadError("OVERLOADED", "chat ingress queue is full", retryable=True)
        self._uploads[key] = _Upload(
            user_id=user_id,
            character_id=character_id,
            upload_id=upload_id,
            mime_type=mime_type,
            container=container,
            codec=codec,
            byte_length=byte_length,
            total_chunks=total_chunks,
            sink=sink,
            created_at=time.monotonic(),
        )
        return VoiceUploadAck()

    def _chunk(self, payload: dict, user_id: str, upload_id: str) -> VoiceUploadAck:
        chunk_index = _int_field(payload, "chunk_index", minimum=0)
        encoded = _string_field(payload, "audio_base64", allow_blank=True)
        key = (user_id, upload_id)
        upload = self._uploads.get(key)
        if upload is None:
            return self._replay_completed_chunk(key, chunk_index, encoded)
        if chunk_index >= upload.total_chunks:
            raise VoiceUploadError("BAD_MESSAGE", "voice chunk index is out of range")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VoiceUploadError("BAD_MESSAGE", "voice chunk is not valid base64") from error
        if len(decoded) > MAX_CHUNK_BYTES:
            raise VoiceUploadError("VOICE_TOO_LARGE", "voice chunk exceeds the size limit")
        existing = upload.chunks.get(chunk_index)
        if existing is not None:
            if existing != decoded:
                raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice chunk content changed")
            return VoiceUploadAck(duplicate=True)
        upload.chunks[chunk_index] = decoded
        return VoiceUploadAck()

    def _replay_completed_chunk(
        self,
        key: tuple[str, str],
        chunk_index: int,
        encoded: str,
    ) -> VoiceUploadAck:
        completed = self._completed.get(key)
        if completed is None:
            raise VoiceUploadError("VOICE_UPLOAD_NOT_FOUND", "voice upload session was not found", retryable=True)
        if chunk_index >= len(completed.chunk_digests):
            raise VoiceUploadError("BAD_MESSAGE", "voice chunk index is out of range")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise VoiceUploadError("BAD_MESSAGE", "voice chunk is not valid base64") from error
        if completed.chunk_digests[chunk_index] != decoded:
            raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice chunk content changed")
        return VoiceUploadAck(duplicate=True)

    async def _finalize(
        self,
        event: WSMessage,
        payload: dict,
        user_id: str,
        character_id: str,
        upload_id: str,
    ) -> VoiceUploadAck:
        if set(payload) - {"phase", "upload_id", "target_character_ids", "target_character_id", "character_id"}:
            raise VoiceUploadError("BAD_MESSAGE", "finalize contains unsupported fields")
        key = (user_id, upload_id)
        completed = self._completed.get(key)
        if completed is not None:
            return VoiceUploadAck(
                {"message_uuid": completed.message_uuid, "duration_ms": completed.duration_ms},
                duplicate=True,
            )
        upload = self._uploads.get(key)
        if upload is None:
            raise VoiceUploadError("VOICE_UPLOAD_NOT_FOUND", "voice upload session was not found", retryable=True)
        if character_id != upload.character_id:
            raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload target changed")
        if set(upload.chunks) != set(range(upload.total_chunks)):
            raise VoiceUploadError("VOICE_MISSING_CHUNKS", "voice upload has missing chunks", retryable=True)
        _, media_ref, duration_ms = await self._validate_and_persist(key, event, upload)
        message_uuid = _message_uuid(user_id, character_id, upload_id)
        stimulus = d.VoiceMessage(
            **_stimulus_fields(event, user_id, character_id, ephemeral=False),
            message_uuid=message_uuid,
            media_ref=media_ref,
            transcript=None,
            client_msg_id=upload_id,
            duration_ms=duration_ms,
        )
        if not upload.sink.can_accept(stimulus) or not upload.sink.submit(stimulus):
            raise VoiceUploadError("OVERLOADED", "chat ingress queue is full", retryable=True)
        parameters = (
            upload.character_id,
            upload.mime_type,
            upload.container,
            upload.codec,
            upload.byte_length,
            upload.total_chunks,
        )
        self._completed[key] = _Completed(
            parameters=parameters,
            chunk_digests=tuple(upload.chunks[index] for index in range(upload.total_chunks)),
            message_uuid=message_uuid,
            duration_ms=duration_ms,
            completed_at=time.monotonic(),
        )
        del self._uploads[key]
        return VoiceUploadAck({"message_uuid": message_uuid, "duration_ms": duration_ms})

    async def _validate_and_persist(
        self,
        key: tuple[str, str],
        event: WSMessage,
        upload: _Upload,
    ) -> tuple[bytes, d.MediaRef, int]:
        data = b"".join(upload.chunks[index] for index in range(upload.total_chunks))
        if len(data) != upload.byte_length:
            self._fail_upload(key, event, "size_mismatch")
            raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice byte length does not match declaration")
        if self._media_store is None:
            raise VoiceUploadError("OVERLOADED", "media store is not configured", retryable=True)
        message_uuid = _message_uuid(upload.user_id, upload.character_id, upload.upload_id)
        media_ref = self._media_store.mint_ref(user_id=upload.user_id, client_msg_id=message_uuid)
        try:
            parsed = await asyncio.to_thread(parse_m4a_audio, data, upload.mime_type, media_ref.media_id)
        except MediaResolutionError as error:
            self._fail_upload(key, event, "invalid_media")
            if error.code is MediaResolutionErrorCode.INVALID_DURATION:
                raise VoiceUploadError("VOICE_INVALID_DURATION", "voice duration is invalid") from error
            raise VoiceUploadError("VOICE_UNSUPPORTED_MEDIA", "voice media content is unsupported") from error
        if not 500 <= parsed.duration_ms <= 30_500:
            self._fail_upload(key, event, "invalid_duration")
            raise VoiceUploadError("VOICE_INVALID_DURATION", "voice duration is outside the allowed range")
        try:
            await asyncio.to_thread(
                self._media_store.persist_audio,
                media_ref=media_ref,
                owner_user_id=upload.user_id,
                data=data,
                mime_type=upload.mime_type,
                duration_ms=parsed.duration_ms,
            )
        except ValueError as error:
            self._fail_upload(key, event, "content_conflict")
            raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice media identity conflicts") from error
        return data, media_ref, parsed.duration_ms

    def _abort(self, event: WSMessage, payload: dict, user_id: str, upload_id: str) -> VoiceUploadAck:
        if set(payload) - {"phase", "upload_id"}:
            raise VoiceUploadError("BAD_MESSAGE", "abort contains unsupported fields")
        key = (user_id, upload_id)
        if key in self._completed:
            raise VoiceUploadError("VOICE_UPLOAD_CONFLICT", "finalized voice upload cannot be aborted")
        if key in self._uploads:
            self._fail_upload(key, event, "aborted")
        return VoiceUploadAck()

    def _fail_upload(self, key: tuple[str, str], event: WSMessage, reason: str) -> None:
        upload = self._uploads.pop(key, None)
        if upload is None:
            return
        stimulus = d.VoiceUploadFailed(
            **_stimulus_fields(event, upload.user_id, upload.character_id, ephemeral=True),
            upload_id=upload.upload_id,
            reason=reason,
        )
        if upload.sink.can_accept(stimulus):
            upload.sink.submit(stimulus)

    def _cleanup_expired(self, now: float) -> None:
        expired = [key for key, upload in self._uploads.items() if now - upload.created_at >= self._ttl_seconds]
        for key in expired:
            upload = self._uploads.pop(key)
            event = WSMessage(event_type="user_voice", payload={}, client_msg_id=f"{upload.upload_id}:ttl")
            stimulus = d.VoiceUploadFailed(
                **_stimulus_fields(event, upload.user_id, upload.character_id, ephemeral=True),
                upload_id=upload.upload_id,
                reason="expired",
            )
            if upload.sink.can_accept(stimulus):
                upload.sink.submit(stimulus)
        completed_expired = [
            key for key, completed in self._completed.items() if now - completed.completed_at >= self._ttl_seconds
        ]
        for key in completed_expired:
            del self._completed[key]


def _payload(event: WSMessage) -> dict:
    if not isinstance(event.payload, dict):
        raise VoiceUploadError("BAD_MESSAGE", "voice payload must be an object")
    if not isinstance(event.client_msg_id, str) or not 0 < len(event.client_msg_id) <= 128:
        raise VoiceUploadError("BAD_MESSAGE", "invalid client_msg_id")
    if event.ts is not None and (type(event.ts) is not int or event.ts < 0):
        raise VoiceUploadError("BAD_MESSAGE", "invalid timestamp")
    return event.payload


def _string_field(payload: dict, name: str, *, allow_blank: bool = False) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise VoiceUploadError("BAD_MESSAGE", f"invalid {name}")
    return value


def _uuid_field(payload: dict, name: str) -> str:
    value = _string_field(payload, name)
    try:
        UUID(value)
    except ValueError as error:
        raise VoiceUploadError("BAD_MESSAGE", f"invalid {name}") from error
    return value


def _int_field(payload: dict, name: str, *, minimum: int) -> int:
    value = payload.get(name)
    if type(value) is not int or value < minimum:
        raise VoiceUploadError("BAD_MESSAGE", f"invalid {name}")
    return value


def _message_uuid(user_id: str, character_id: str, upload_id: str) -> str:
    identity = json.dumps(
        ["conversation-audio", user_id, character_id, upload_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return str(uuid5(NAMESPACE_URL, identity))


def _stimulus_fields(
    event: WSMessage,
    user_id: str,
    character_id: str,
    *,
    ephemeral: bool,
) -> dict[str, object]:
    occurred_at = datetime.now(timezone.utc)
    if event.ts is not None:
        try:
            occurred_at = datetime.fromtimestamp(event.ts / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise VoiceUploadError("BAD_MESSAGE", "invalid timestamp") from error
    return {
        "stimulus_id": str(uuid5(NAMESPACE_URL, json.dumps(["websocket-input", user_id, event.client_msg_id]))),
        "schema_version": 1,
        "occurred_at": occurred_at,
        "source": d.StimulusSource.USER,
        "target_character_ids": (character_id,),
        "user_id": user_id,
        "ephemeral": ephemeral,
    }
