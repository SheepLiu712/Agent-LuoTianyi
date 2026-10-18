"""语音分片上传的校验、组装与幂等；不执行 Stage 准入或投递。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

import src.domain.agent as d
from src.infrastructure.media import (
    MediaResolutionError,
    MediaResolutionErrorCode,
    PermanentMediaStore,
    parse_m4a_audio,
)
from src.utils.logger import get_logger

from ._messages import _WSMessage

MAX_CHUNK_BYTES = 48 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_CHUNKS = 32


@dataclass(frozen=True)
class _VoiceUploadError(Exception):
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class _VoiceUploadAck:
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
    binding: object | None
    created_at: float
    chunks: dict[int, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class _Completed:
    parameters: tuple[object, ...]
    chunk_digests: tuple[bytes, ...]
    message_uuid: str
    duration_ms: int
    completed_at: float
    persisted: bool = False


class _VoiceUploadAssembler:
    """Prepare upload stimuli; only the Adapter may admit them and commit progress."""

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
        self._prepared: tuple[tuple[str, str], _Upload | _Completed | None] | None = None
        self._notifications: list[tuple[object, d.Stimulus]] = []

    async def process(
        self,
        *,
        event: _WSMessage,
        user_id: str,
        character_id: str,
    ) -> tuple[d.Stimulus | None, dict]:
        """Prepare one frame; caller serializes processing through admission/commit."""
        self._prepared = None
        self._cleanup_expired(time.monotonic())
        payload = _payload(event)
        phase = payload.get("phase")
        upload_id = _uuid_field(payload, "upload_id")
        await self._restore_completion(user_id, character_id, upload_id)
        if phase == "begin":
            result = self._begin(event, payload, user_id, character_id, upload_id)
        elif phase == "chunk":
            result = self._chunk(payload, user_id, upload_id)
        elif phase == "finalize":
            result = await self._finalize(event, payload, user_id, character_id, upload_id)
        elif phase == "abort":
            result = self._abort(event, payload, user_id, upload_id)
        else:
            raise _VoiceUploadError("BAD_MESSAGE", "invalid voice upload phase")
        if isinstance(result, tuple):
            return result
        return None, {
            "state": "duplicate" if result.duplicate else "partial",
            "ack_payload": result.payload,
            "duplicate": result.duplicate,
        }

    async def commit(self, binding: object) -> None:
        """Record completion only after the Adapter reports successful Stage admission."""
        prepared, self._prepared = self._prepared, None
        if prepared is None:
            return
        key, value = prepared
        if value is None:
            self._uploads.pop(key, None)
        elif isinstance(value, _Upload):
            value.binding = binding
            self._uploads[key] = value
        else:
            # Keep the receipt in memory before the first await: retries must not redeliver.
            self._completed[key] = value
            del self._uploads[key]
            await self._persist_completion(key)

    def discard_prepared(self) -> None:
        self._prepared = None

    def take_notifications(self) -> list[tuple[object, d.Stimulus]]:
        notifications, self._notifications = self._notifications, []
        return notifications

    async def _restore_completion(self, user_id: str, character_id: str, upload_id: str) -> None:
        key = (user_id, upload_id)
        existing = self._completed.get(key)
        if existing is not None:
            if existing.parameters[0] != character_id:
                raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload target changed")
            if not existing.persisted:
                await self._persist_completion(key)
            return
        if self._media_store is None:
            return
        message_uuid = _message_uuid(user_id, character_id, upload_id)
        media_ref = self._media_store.mint_ref(user_id=user_id, client_msg_id=message_uuid)
        try:
            receipt = await asyncio.to_thread(
                self._media_store.read_audio_receipt,
                media_ref=media_ref,
                owner_user_id=user_id,
            )
            if receipt is None:
                return
            parameters = tuple(receipt["parameters"])
            digests = tuple(bytes.fromhex(value) for value in receipt["chunk_digests"])
            duration = receipt["duration_ms"]
            if (
                receipt["version"] != 1
                or receipt["message_uuid"] != message_uuid
                or len(parameters) != 6
                or parameters[0] != character_id
                or parameters[1:4] != ("audio/mp4", "m4a", "aac_lc")
                or type(parameters[4]) is not int
                or not 0 < parameters[4] <= MAX_TOTAL_BYTES
                or parameters[5] != len(digests)
                or not 0 < len(digests) <= MAX_CHUNKS
                or any(len(value) != 32 for value in digests)
                or type(duration) is not int
                or not 500 <= duration <= 30_500
            ):
                raise ValueError("invalid voice receipt")
            self._completed[key] = _Completed(parameters, digests, message_uuid, duration, time.monotonic(), True)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise _VoiceUploadError("OVERLOADED", "voice completion receipt unavailable", retryable=True) from error

    async def _persist_completion(self, key: tuple[str, str]) -> None:
        completed = self._completed[key]
        media_ref = self._media_store.mint_ref(user_id=key[0], client_msg_id=completed.message_uuid)
        receipt = {
            "version": 1,
            "parameters": completed.parameters,
            "chunk_digests": [value.hex() for value in completed.chunk_digests],
            "message_uuid": completed.message_uuid,
            "duration_ms": completed.duration_ms,
        }
        try:
            await asyncio.to_thread(
                self._media_store.write_audio_receipt,
                media_ref=media_ref,
                owner_user_id=key[0],
                receipt=receipt,
            )
        except (OSError, ValueError):
            # Admission already happened: retain the small in-memory receipt beyond TTL and retry its write.
            get_logger(__name__).exception(
                "Voice admission receipt persistence failed message=%s", completed.message_uuid
            )
            return
        self._completed[key] = replace(completed, persisted=True)

    def _begin(
        self,
        event: _WSMessage,
        payload: dict,
        user_id: str,
        character_id: str,
        upload_id: str,
    ) -> _VoiceUploadAck | tuple[d.Stimulus, dict]:
        mime_type = _string_field(payload, "mime_type")
        container = _string_field(payload, "container")
        codec = _string_field(payload, "codec")
        byte_length = _int_field(payload, "byte_length", minimum=1)
        total_chunks = _int_field(payload, "total_chunks", minimum=1)
        if byte_length > MAX_TOTAL_BYTES or total_chunks > MAX_CHUNKS:
            raise _VoiceUploadError("VOICE_TOO_LARGE", "voice upload exceeds size or chunk limits")
        if (mime_type, container, codec) != ("audio/mp4", "m4a", "aac_lc"):
            raise _VoiceUploadError("VOICE_UNSUPPORTED_MEDIA", "voice media declaration is unsupported")
        key = (user_id, upload_id)
        parameters = (character_id, mime_type, container, codec, byte_length, total_chunks)
        completed = self._completed.get(key)
        if completed is not None:
            if completed.parameters != parameters:
                raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload identity conflicts with completed media")
            return _VoiceUploadAck(duplicate=True)
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
                raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload parameters changed")
            return _VoiceUploadAck(duplicate=True)
        if any(upload.user_id == user_id for upload in self._uploads.values()):
            raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "user already has an incomplete voice upload")
        if (
            len(self._uploads) >= self._max_incomplete
            or sum(not item.persisted for item in self._completed.values()) >= self._max_incomplete
        ):
            raise _VoiceUploadError("OVERLOADED", "voice upload capacity is full", retryable=True)
        stimulus = d.VoiceRecordingCommitted(
            **_stimulus_fields(event, user_id, character_id, ephemeral=True),
            upload_id=upload_id,
        )
        upload = _Upload(
            user_id=user_id,
            character_id=character_id,
            upload_id=upload_id,
            mime_type=mime_type,
            container=container,
            codec=codec,
            byte_length=byte_length,
            total_chunks=total_chunks,
            binding=None,
            created_at=time.monotonic(),
        )
        self._prepared = (key, upload)
        return stimulus, {"state": "complete", "ack_payload": {}}

    def _chunk(self, payload: dict, user_id: str, upload_id: str) -> _VoiceUploadAck:
        chunk_index = _int_field(payload, "chunk_index", minimum=0)
        encoded = _string_field(payload, "audio_base64", allow_blank=True)
        key = (user_id, upload_id)
        upload = self._uploads.get(key)
        if upload is None:
            return self._replay_completed_chunk(key, chunk_index, encoded)
        if chunk_index >= upload.total_chunks:
            raise _VoiceUploadError("BAD_MESSAGE", "voice chunk index is out of range")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise _VoiceUploadError("BAD_MESSAGE", "voice chunk is not valid base64") from error
        if len(decoded) > MAX_CHUNK_BYTES:
            raise _VoiceUploadError("VOICE_TOO_LARGE", "voice chunk exceeds the size limit")
        existing = upload.chunks.get(chunk_index)
        if existing is not None:
            if existing != decoded:
                raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice chunk content changed")
            return _VoiceUploadAck(duplicate=True)
        upload.chunks[chunk_index] = decoded
        return _VoiceUploadAck()

    def _replay_completed_chunk(
        self,
        key: tuple[str, str],
        chunk_index: int,
        encoded: str,
    ) -> _VoiceUploadAck:
        completed = self._completed.get(key)
        if completed is None:
            raise _VoiceUploadError("VOICE_UPLOAD_NOT_FOUND", "voice upload session was not found", retryable=True)
        if chunk_index >= len(completed.chunk_digests):
            raise _VoiceUploadError("BAD_MESSAGE", "voice chunk index is out of range")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise _VoiceUploadError("BAD_MESSAGE", "voice chunk is not valid base64") from error
        if len(decoded) > MAX_CHUNK_BYTES:
            raise _VoiceUploadError("VOICE_TOO_LARGE", "voice chunk exceeds the size limit")
        if completed.chunk_digests[chunk_index] != sha256(decoded).digest():
            raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice chunk content changed")
        return _VoiceUploadAck(duplicate=True)

    async def _finalize(
        self,
        event: _WSMessage,
        payload: dict,
        user_id: str,
        character_id: str,
        upload_id: str,
    ) -> _VoiceUploadAck | tuple[d.Stimulus, dict]:
        if set(payload) - {"phase", "upload_id", "target_character_ids", "target_character_id", "character_id"}:
            raise _VoiceUploadError("BAD_MESSAGE", "finalize contains unsupported fields")
        key = (user_id, upload_id)
        completed = self._completed.get(key)
        if completed is not None:
            return _VoiceUploadAck(
                {"message_uuid": completed.message_uuid, "duration_ms": completed.duration_ms},
                duplicate=True,
            )
        upload = self._uploads.get(key)
        if upload is None:
            raise _VoiceUploadError("VOICE_UPLOAD_NOT_FOUND", "voice upload session was not found", retryable=True)
        if character_id != upload.character_id:
            raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice upload target changed")
        if set(upload.chunks) != set(range(upload.total_chunks)):
            raise _VoiceUploadError("VOICE_MISSING_CHUNKS", "voice upload has missing chunks", retryable=True)
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
        parameters = (
            upload.character_id,
            upload.mime_type,
            upload.container,
            upload.codec,
            upload.byte_length,
            upload.total_chunks,
        )
        completed = _Completed(
            parameters=parameters,
            chunk_digests=tuple(sha256(upload.chunks[index]).digest() for index in range(upload.total_chunks)),
            message_uuid=message_uuid,
            duration_ms=duration_ms,
            completed_at=time.monotonic(),
        )
        self._prepared = (key, completed)
        return stimulus, {
            "state": "complete",
            "ack_payload": {"message_uuid": message_uuid, "duration_ms": duration_ms},
        }

    async def _validate_and_persist(
        self,
        key: tuple[str, str],
        event: _WSMessage,
        upload: _Upload,
    ) -> tuple[bytes, d.MediaRef, int]:
        data = b"".join(upload.chunks[index] for index in range(upload.total_chunks))
        if len(data) != upload.byte_length:
            self._fail_upload(key, event, "size_mismatch")
            raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice byte length does not match declaration")
        if self._media_store is None:
            raise _VoiceUploadError("OVERLOADED", "media store is not configured", retryable=True)
        message_uuid = _message_uuid(upload.user_id, upload.character_id, upload.upload_id)
        media_ref = self._media_store.mint_ref(user_id=upload.user_id, client_msg_id=message_uuid)
        try:
            parsed = await asyncio.to_thread(parse_m4a_audio, data, upload.mime_type, media_ref.media_id)
        except MediaResolutionError as error:
            self._fail_upload(key, event, "invalid_media")
            if error.code is MediaResolutionErrorCode.INVALID_DURATION:
                raise _VoiceUploadError("VOICE_INVALID_DURATION", "voice duration is invalid") from error
            raise _VoiceUploadError("VOICE_UNSUPPORTED_MEDIA", "voice media content is unsupported") from error
        if not 500 <= parsed.duration_ms <= 30_500:
            self._fail_upload(key, event, "invalid_duration")
            raise _VoiceUploadError("VOICE_INVALID_DURATION", "voice duration is outside the allowed range")
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
            raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "voice media identity conflicts") from error
        return data, media_ref, parsed.duration_ms

    def _abort(
        self, event: _WSMessage, payload: dict, user_id: str, upload_id: str
    ) -> _VoiceUploadAck | tuple[d.Stimulus, dict]:
        if set(payload) - {"phase", "upload_id"}:
            raise _VoiceUploadError("BAD_MESSAGE", "abort contains unsupported fields")
        key = (user_id, upload_id)
        if key in self._completed:
            raise _VoiceUploadError("VOICE_UPLOAD_CONFLICT", "finalized voice upload cannot be aborted")
        upload = self._uploads.get(key)
        if upload is not None:
            stimulus = d.VoiceUploadFailed(
                **_stimulus_fields(event, user_id, upload.character_id, ephemeral=True),
                upload_id=upload_id,
                reason="aborted",
            )
            self._prepared = (key, None)
            return stimulus, {"state": "complete", "ack_payload": {}, "binding": upload.binding}
        return _VoiceUploadAck()

    def _fail_upload(self, key: tuple[str, str], event: _WSMessage, reason: str) -> None:
        upload = self._uploads.pop(key, None)
        if upload is None:
            return
        stimulus = d.VoiceUploadFailed(
            **_stimulus_fields(event, upload.user_id, upload.character_id, ephemeral=True),
            upload_id=upload.upload_id,
            reason=reason,
        )
        self._notifications.append((upload.binding, stimulus))

    def _cleanup_expired(self, now: float) -> None:
        expired = [key for key, upload in self._uploads.items() if now - upload.created_at >= self._ttl_seconds]
        for key in expired:
            upload = self._uploads.pop(key)
            event = _WSMessage(event_type="user_voice", payload={}, client_msg_id=f"{upload.upload_id}:ttl")
            stimulus = d.VoiceUploadFailed(
                **_stimulus_fields(event, upload.user_id, upload.character_id, ephemeral=True),
                upload_id=upload.upload_id,
                reason="expired",
            )
            self._notifications.append((upload.binding, stimulus))
        completed_expired = [
            key
            for key, completed in self._completed.items()
            if completed.persisted and now - completed.completed_at >= self._ttl_seconds
        ]
        for key in completed_expired:
            del self._completed[key]


def _payload(event: _WSMessage) -> dict:
    if not isinstance(event.payload, dict):
        raise _VoiceUploadError("BAD_MESSAGE", "voice payload must be an object")
    if not isinstance(event.client_msg_id, str) or not 0 < len(event.client_msg_id) <= 128:
        raise _VoiceUploadError("BAD_MESSAGE", "invalid client_msg_id")
    if event.ts is not None and (type(event.ts) is not int or event.ts < 0):
        raise _VoiceUploadError("BAD_MESSAGE", "invalid timestamp")
    return event.payload


def _string_field(payload: dict, name: str, *, allow_blank: bool = False) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise _VoiceUploadError("BAD_MESSAGE", f"invalid {name}")
    return value


def _uuid_field(payload: dict, name: str) -> str:
    value = _string_field(payload, name)
    try:
        UUID(value)
    except ValueError as error:
        raise _VoiceUploadError("BAD_MESSAGE", f"invalid {name}") from error
    return value


def _int_field(payload: dict, name: str, *, minimum: int) -> int:
    value = payload.get(name)
    if type(value) is not int or value < minimum:
        raise _VoiceUploadError("BAD_MESSAGE", f"invalid {name}")
    return value


def _message_uuid(user_id: str, character_id: str, upload_id: str) -> str:
    identity = json.dumps(
        ["conversation-audio", user_id, character_id, upload_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return str(uuid5(NAMESPACE_URL, identity))


def _stimulus_fields(
    event: _WSMessage,
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
            raise _VoiceUploadError("BAD_MESSAGE", "invalid timestamp") from error
    return {
        "stimulus_id": str(uuid5(NAMESPACE_URL, json.dumps(["websocket-input", user_id, event.client_msg_id]))),
        "schema_version": 1,
        "occurred_at": occurred_at,
        "source": d.StimulusSource.USER,
        "target_character_ids": (character_id,),
        "user_id": user_id,
        "ephemeral": ephemeral,
    }
