"""Stateful, bounded ``call.v1`` transport without CallStage ownership.

The transport owns wire ordering, acknowledgements, replay bytes and stream
registration.  A narrow acceptance sink decides whether an ordered business
frame has actually entered the future call lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal, Protocol

from src.utils.owned_operation import complete_owned

from .audio_codec import CALL_ROUTE, FINAL_FLAG, BinaryAudioFrameCodec, WireAudioFrame
from .control import ControlMessage, ControlProtocolError, decode_control_text, encode_control_message

CALL_CLOSE_PROTOCOL_ERROR = 1002
CALL_CLOSE_POLICY_VIOLATION = 1008
CALL_CLOSE_TOO_LARGE = 1009
CALL_CLOSE_TRY_AGAIN_LATER = 1013


def parse_call_transport_enabled(config: dict) -> bool:
    """Parse the operator request strictly; it does not make production available."""
    section = config.get("call_transport", {})
    if not isinstance(section, dict):
        raise ValueError("call_transport must be an object")
    value = section.get("enabled", False)
    if type(value) is not bool:
        raise ValueError("call_transport.enabled must be a boolean")
    return value


class CallTransportError(ValueError):
    """A stable transport failure carrying its WebSocket close code."""

    def __init__(self, code: str, *, close_code: int = CALL_CLOSE_PROTOCOL_ERROR) -> None:
        self.code = code
        self.close_code = close_code
        super().__init__(code)


class CallTransportBackpressure(RuntimeError):
    """Outbound capacity is full; the producer may wait or retry after ACK."""


@dataclass(frozen=True, slots=True)
class InboundCallFrame:
    seq: int
    kind: Literal["control", "audio"]
    raw: bytes
    control: ControlMessage | None = None
    audio: WireAudioFrame | None = None


@dataclass(frozen=True, slots=True)
class CallAcceptanceReceipt:
    """Stable business idempotency identity for one accepted inbound frame."""

    call_id: str
    direction: Literal["client_to_server"]
    seq: int
    fingerprint: bytes


class CallBusinessAcceptanceSink(Protocol):
    async def accept(self, frame: InboundCallFrame, receipt: CallAcceptanceReceipt) -> bool:
        """Accept idempotently by receipt; exceptions may follow partial side effects.

        Implementations must use the receipt as their business idempotency key.
        The transport provides at-least-once retry safety, not exactly-once side
        effects inside an arbitrary sink.
        """


@dataclass(frozen=True, slots=True)
class CallWireOutput:
    text: str | None = None
    binary: bytes | None = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.binary is None):
            raise ValueError("exactly one wire payload is required")


@dataclass(frozen=True, slots=True)
class CallTransportConfig:
    max_pending_frames: int = 256
    max_pending_bytes: int = 4 * 1024 * 1024
    max_replay_bytes: int = 4 * 1024 * 1024
    max_received_fingerprints: int = 131_072
    max_stop_metadata: int = 4096
    max_response_audio_seconds: int = 30

    def __post_init__(self) -> None:
        for name in (
            "max_pending_frames",
            "max_pending_bytes",
            "max_replay_bytes",
            "max_received_fingerprints",
            "max_stop_metadata",
            "max_response_audio_seconds",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(slots=True)
class _ReplayEntry:
    seq: int
    output: CallWireOutput
    byte_size: int
    response_id: str | None = None
    stream_id: int | None = None
    retired_by: int | None = None
    audio_payload_bytes: int = 0


@dataclass(slots=True)
class _ResponseRegistration:
    response_id: str
    stream_id: int
    first_seq: int
    encoding: str
    sample_rate: int
    channels: int
    final_seen: bool = False


@dataclass(frozen=True, slots=True)
class _StopMetadata:
    stop_seq: int
    response_id: str
    stream_id: int


class CallTransportSession:
    """One authenticated call's ordered ingress and bounded egress replay."""

    def __init__(
        self,
        *,
        call_id: str,
        user_id: str,
        character_id: str,
        sink: CallBusinessAcceptanceSink,
        config: CallTransportConfig | None = None,
    ) -> None:
        if not call_id or not user_id or not character_id:
            raise ValueError("call_id, user_id and character_id are required")
        self.call_id = call_id
        self.user_id = user_id
        self.character_id = character_id
        self._sink = sink
        self._config = config or CallTransportConfig()
        self._codec = BinaryAudioFrameCodec()
        self._client_cursor = 0
        self._client_fingerprints: OrderedDict[int, bytes] = OrderedDict()
        self._pending: dict[int, InboundCallFrame] = {}
        self._pending_bytes = 0
        self._server_next_seq = 1
        self._server_ack_cursor = 0
        self._replay: OrderedDict[int, _ReplayEntry] = OrderedDict()
        self._replay_bytes = 0
        self._streams: dict[int, _ResponseRegistration] = {}
        self._response_formats: dict[str, tuple[str, int, int]] = {}
        self._response_audio_bytes: dict[str, int] = {}
        self._stop_metadata: dict[int, _StopMetadata] = {}
        self._replay_capacity_event = asyncio.Event()
        self._replay_capacity_event.set()
        self._closed = False

    @property
    def client_cursor(self) -> int:
        return self._client_cursor

    @property
    def server_ack_cursor(self) -> int:
        return self._server_ack_cursor

    @property
    def last_server_seq(self) -> int:
        return self._server_next_seq - 1

    @property
    def next_server_seq(self) -> int:
        """Return the next shared control/audio sequence owned by this session."""
        self._require_open()
        return self._server_next_seq

    def response_server_range(self, response_id: str, stream_id: int) -> tuple[int, int]:
        """Return the allocated replay range for one registered response stream."""
        registration = self._streams.get(stream_id)
        if registration is None or registration.response_id != response_id:
            raise CallTransportError("UNREGISTERED_STREAM")
        through = max(
            (
                seq
                for seq, entry in self._replay.items()
                if entry.response_id == response_id and entry.stream_id == stream_id and entry.retired_by is None
            ),
            default=registration.first_seq,
        )
        return registration.first_seq, through

    async def receive_text(self, raw: str) -> list[CallWireOutput]:
        self._require_open()
        try:
            message = decode_control_text(raw, sender="client", transport="call_ws")
        except ControlProtocolError as error:
            close_code = CALL_CLOSE_TOO_LARGE if error.code == "CONTROL_TOO_LARGE" else CALL_CLOSE_PROTOCOL_ERROR
            raise CallTransportError(error.code, close_code=close_code) from error
        message_type = message["type"]
        if message_type == "ack":
            self.acknowledge_server(int(message["ack_seq"]))
            return []
        if message_type == "nack":
            return self.replay_missing(int(message["missing_seq"]))
        if message_type == "call.resume":
            return self.resume(message)
        if message_type in {"call.resumed", "call.switch_prepare", "call.switch_ready", "error"}:
            raise CallTransportError("UNEXPECTED_CONTROL")
        self._validate_client_control(message)
        encoded = raw.encode("utf-8")
        return await self._receive_ordered(
            InboundCallFrame(seq=int(message["seq"]), kind="control", raw=encoded, control=message)
        )

    async def receive_binary(self, raw: bytes) -> list[CallWireOutput]:
        self._require_open()
        try:
            frame = self._codec.decode(raw)
        except ValueError as error:
            raise CallTransportError(getattr(error, "code", "BAD_AUDIO_FRAME")) from error
        if frame.route != CALL_ROUTE or frame.stream_id != 0:
            raise CallTransportError("INVALID_CLIENT_AUDIO_ROUTE")
        return await self._receive_ordered(InboundCallFrame(seq=frame.seq, kind="audio", raw=raw, audio=frame))

    async def _receive_ordered(self, frame: InboundCallFrame) -> list[CallWireOutput]:
        digest = self._fingerprint(frame)
        duplicate = self._duplicate_result(frame, digest)
        if duplicate is not None:
            return duplicate
        if frame.seq <= self._client_cursor:
            return [self._ack_output()]
        pending = self._pending.get(frame.seq)
        if pending is None and frame.seq == self._client_cursor + 1:
            self._pending[frame.seq] = frame
            self._pending_bytes += len(frame.raw)
        elif pending is None:
            self._add_pending(frame)
        if frame.seq > self._client_cursor + 1:
            return [self._nack_output(self._client_cursor + 1)]
        outputs: list[CallWireOutput] = []
        while (next_seq := self._client_cursor + 1) in self._pending:
            candidate = self._pending[next_seq]
            if len(self._client_fingerprints) >= self._config.max_received_fingerprints:
                raise CallTransportError("RECEIVE_HISTORY_FULL", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
            accepted = await complete_owned(self._accept_and_commit(candidate))
            if not accepted:
                outputs.append(self._error_output("OVERLOADED", request_seq=next_seq, retryable=True))
                return outputs
        outputs.append(self._ack_output())
        return outputs

    async def _accept_and_commit(self, frame: InboundCallFrame) -> bool:
        digest = self._fingerprint(frame)
        receipt = CallAcceptanceReceipt(
            call_id=self.call_id,
            direction="client_to_server",
            seq=frame.seq,
            fingerprint=digest,
        )
        accepted = await self._sink.accept(frame, receipt)
        if not accepted:
            return False
        self._pending.pop(frame.seq)
        self._pending_bytes -= len(frame.raw)
        self._client_fingerprints[frame.seq] = digest
        self._client_cursor = frame.seq
        return True

    def _duplicate_result(self, frame: InboundCallFrame, digest: bytes) -> list[CallWireOutput] | None:
        known = self._client_fingerprints.get(frame.seq)
        if known is not None:
            if known != digest:
                raise CallTransportError("SEQ_CONFLICT")
            return [self._ack_output()]
        pending = self._pending.get(frame.seq)
        if pending is None:
            return None
        if self._fingerprint(pending) != digest:
            raise CallTransportError("SEQ_CONFLICT")
        if frame.seq > self._client_cursor + 1:
            return [self._nack_output(self._client_cursor + 1)]
        return None

    def _add_pending(self, frame: InboundCallFrame) -> None:
        if len(self._pending) >= self._config.max_pending_frames:
            raise CallTransportError("PENDING_WINDOW_FULL", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
        if self._pending_bytes + len(frame.raw) > self._config.max_pending_bytes:
            raise CallTransportError("PENDING_BYTES_FULL", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
        self._pending[frame.seq] = frame
        self._pending_bytes += len(frame.raw)

    @staticmethod
    def _fingerprint(frame: InboundCallFrame) -> bytes:
        return hashlib.sha256(frame.kind.encode("ascii") + b"\0" + frame.raw).digest()

    def resume(self, message: ControlMessage) -> list[CallWireOutput]:
        self._require_open()
        if message["type"] != "call.resume":
            raise CallTransportError("INVALID_RESUME")
        if message["call_id"] != self.call_id or message["character_id"] != self.character_id:
            raise CallTransportError("RESUME_OWNERSHIP_MISMATCH", close_code=CALL_CLOSE_POLICY_VIOLATION)
        cursor = int(message["last_contiguous_server_seq"])
        if cursor > self.last_server_seq:
            raise CallTransportError("INVALID_RESUME_CURSOR")
        self.acknowledge_server(cursor)
        resumed: ControlMessage = {
            "protocol": "call.v1",
            "type": "call.resumed",
            "call_id": self.call_id,
            "character_id": self.character_id,
            "last_contiguous_client_seq": self._client_cursor,
            "last_contiguous_server_seq": cursor,
        }
        output = CallWireOutput(text=encode_control_message(resumed, sender="server", transport="call_ws"))
        return [output, *self.replay_after(cursor)]

    def send_control(self, message: ControlMessage) -> CallWireOutput:
        self._require_open()
        if message["type"] in {"ack", "nack", "call.resumed", "error"}:
            return CallWireOutput(text=encode_control_message(message, sender="server", transport="call_ws"))
        seq = int(message.get("seq", 0))
        self._require_next_server_seq(seq)
        raw = encode_control_message(message, sender="server", transport="call_ws")
        output = CallWireOutput(text=raw)
        response_id = None
        stream_id = None
        if message["type"] == "audio.stream_started":
            response_id = str(message["response_id"])
            stream_id = int(message["stream_id"])
            if stream_id == 0 or stream_id in self._streams:
                raise CallTransportError("STREAM_ID_CONFLICT")
            audio_format = (str(message["encoding"]), int(message["sample_rate"]), int(message["channels"]))
            known_format = self._response_formats.get(response_id)
            if known_format is not None and known_format != audio_format:
                raise CallTransportError("RESPONSE_AUDIO_FORMAT_CONFLICT")
            registration = _ResponseRegistration(
                response_id=response_id,
                stream_id=stream_id,
                first_seq=seq,
                encoding=audio_format[0],
                sample_rate=audio_format[1],
                channels=audio_format[2],
            )
        if message["type"] == "playback.stop":
            return self._send_stop_atomically(message, output)
        self._store_replay(seq, output, response_id=response_id, stream_id=stream_id)
        if message["type"] == "audio.stream_started":
            self._streams[stream_id] = registration
            self._response_formats.setdefault(response_id, audio_format)
            self._response_audio_bytes.setdefault(response_id, 0)
        self._server_next_seq += 1
        return output

    def send_audio(self, frame: WireAudioFrame) -> CallWireOutput:
        self._require_open()
        self._require_next_server_seq(frame.seq)
        if frame.route != CALL_ROUTE or frame.stream_id == 0:
            raise CallTransportError("INVALID_SERVER_AUDIO_ROUTE")
        registration = self._streams.get(frame.stream_id)
        if registration is None:
            raise CallTransportError("UNREGISTERED_STREAM")
        if registration.final_seen:
            raise CallTransportError("STREAM_ALREADY_FINAL")
        raw = self._codec.encode(frame)
        output = CallWireOutput(binary=raw)
        self._require_response_audio_capacity(registration, len(frame.payload))
        self._store_replay(
            frame.seq,
            output,
            response_id=registration.response_id,
            stream_id=registration.stream_id,
            audio_payload_bytes=len(frame.payload),
        )
        self._response_audio_bytes[registration.response_id] += len(frame.payload)
        if frame.flags & FINAL_FLAG:
            registration.final_seen = True
        self._server_next_seq += 1
        return output

    def _store_replay(
        self,
        seq: int,
        output: CallWireOutput,
        *,
        response_id: str | None,
        stream_id: int | None,
        audio_payload_bytes: int = 0,
    ) -> None:
        byte_size = len(output.binary if output.binary is not None else output.text.encode("utf-8"))
        if self._replay_bytes + byte_size > self._config.max_replay_bytes:
            self._replay_capacity_event.clear()
            raise CallTransportBackpressure("REPLAY_BUFFER_FULL")
        self._replay[seq] = _ReplayEntry(
            seq=seq,
            output=output,
            byte_size=byte_size,
            response_id=response_id,
            stream_id=stream_id,
            audio_payload_bytes=audio_payload_bytes,
        )
        self._replay_bytes += byte_size

    def _require_response_audio_capacity(
        self,
        registration: _ResponseRegistration,
        payload_bytes: int,
    ) -> None:
        if registration.encoding != "pcm_s16le":
            raise CallTransportError("UNSUPPORTED_RESPONSE_AUDIO_FORMAT")
        maximum = self._response_audio_limit(registration.response_id)
        current = self._response_audio_bytes.get(registration.response_id, 0)
        if current + payload_bytes > maximum:
            raise CallTransportBackpressure("RESPONSE_AUDIO_BUFFER_FULL")

    async def wait_for_replay_capacity(self, byte_size: int) -> None:
        """Wait without spawning tasks until an ACK frees the requested capacity."""
        if type(byte_size) is not int or byte_size <= 0 or byte_size > self._config.max_replay_bytes:
            raise ValueError("byte_size must fit the replay buffer")
        while not self._closed and self._replay_bytes + byte_size > self._config.max_replay_bytes:
            self._replay_capacity_event.clear()
            await self._replay_capacity_event.wait()
        self._require_open()

    async def wait_for_audio_capacity(self, response_id: str, wire_bytes: int, payload_bytes: int) -> None:
        """Wait until both global replay and one response's PCM budgets can accept a frame."""
        if not response_id or type(wire_bytes) is not int or type(payload_bytes) is not int:
            raise ValueError("response_id and integer byte sizes are required")
        if wire_bytes <= 0 or wire_bytes > self._config.max_replay_bytes:
            raise ValueError("wire_bytes can never fit the replay buffer")
        maximum_audio = self._response_audio_limit(response_id)
        if payload_bytes <= 0 or payload_bytes > maximum_audio:
            raise ValueError("payload_bytes can never fit the response audio budget")
        while not self._closed:
            global_full = self._replay_bytes + wire_bytes > self._config.max_replay_bytes
            response_full = self._response_audio_bytes.get(response_id, 0) + payload_bytes > maximum_audio
            if not global_full and not response_full:
                return
            self._replay_capacity_event.clear()
            await self._replay_capacity_event.wait()
        self._require_open()

    def _validate_retirement(self, message: ControlMessage) -> None:
        response_id = str(message["response_id"])
        stream_id = int(message["stream_id"])
        retired = message["retire_server_seq"]
        assert isinstance(retired, dict)
        start, through = int(retired["from"]), int(retired["through"])
        registration = self._streams.get(stream_id)
        if registration is None or registration.response_id != response_id or registration.first_seq != start:
            raise CallTransportError("INVALID_RETIRE_RANGE")
        for seq in range(start, through + 1):
            entry = self._replay.get(seq)
            if entry is None or entry.response_id != response_id or entry.stream_id != stream_id:
                raise CallTransportError("INVALID_RETIRE_RANGE")

    def _send_stop_atomically(self, message: ControlMessage, output: CallWireOutput) -> CallWireOutput:
        self._validate_retirement(message)
        if len(self._stop_metadata) >= self._config.max_stop_metadata:
            raise CallTransportBackpressure("STOP_METADATA_FULL")
        retired = message["retire_server_seq"]
        assert isinstance(retired, dict)
        start, through, stop_seq = int(retired["from"]), int(retired["through"]), int(message["seq"])
        stop_bytes = len(output.text.encode("utf-8"))
        retired_bytes = sum(self._replay[seq].byte_size for seq in range(start, through + 1))
        if self._replay_bytes - retired_bytes + stop_bytes > self._config.max_replay_bytes:
            self._replay_capacity_event.clear()
            raise CallTransportBackpressure("REPLAY_BUFFER_FULL")
        self._replay[stop_seq] = _ReplayEntry(
            seq=stop_seq,
            output=output,
            byte_size=stop_bytes,
            response_id=str(message["response_id"]),
            stream_id=int(message["stream_id"]),
        )
        self._replay_bytes += stop_bytes
        self._stop_metadata[stop_seq] = _StopMetadata(
            stop_seq=stop_seq,
            response_id=str(message["response_id"]),
            stream_id=int(message["stream_id"]),
        )
        self._apply_retirement(message)
        self._server_next_seq += 1
        return output

    def _apply_retirement(self, message: ControlMessage) -> None:
        retired = message["retire_server_seq"]
        assert isinstance(retired, dict)
        start, through, stop_seq = int(retired["from"]), int(retired["through"]), int(message["seq"])
        for seq in range(start, through + 1):
            entry = self._replay[seq]
            self._replay_bytes -= entry.byte_size
            self._release_response_audio(entry)
            entry.output = CallWireOutput(text="")
            entry.byte_size = 0
            entry.retired_by = stop_seq
        self._replay_capacity_event.set()

    def _validate_client_control(self, message: ControlMessage) -> None:
        message_type = message["type"]
        if message_type == "call.start":
            raise CallTransportError("CALL_START_UNAVAILABLE", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
        call_id = message.get("call_id")
        if call_id is not None and call_id != self.call_id:
            raise CallTransportError("CALL_OWNERSHIP_MISMATCH", close_code=CALL_CLOSE_POLICY_VIOLATION)
        if message_type == "playback.completed":
            registration = self._streams.get(int(message["stream_id"]))
            if (
                registration is None
                or registration.response_id != message["response_id"]
                or not registration.final_seen
            ):
                raise CallTransportError("INVALID_PLAYBACK_COMPLETION")
        if message_type == "playback.stopped":
            stop = self._stop_metadata.get(int(message["stop_seq"]))
            if stop is None:
                raise CallTransportError("INVALID_PLAYBACK_STOP_CONFIRMATION")
            if stop.response_id != message["response_id"]:
                raise CallTransportError("INVALID_PLAYBACK_STOP_CONFIRMATION")

    def acknowledge_server(self, ack_seq: int) -> None:
        self._require_open()
        if ack_seq < self._server_ack_cursor or ack_seq > self.last_server_seq:
            raise CallTransportError("INVALID_ACK_CURSOR")
        self._server_ack_cursor = ack_seq
        while self._replay and next(iter(self._replay)) <= ack_seq:
            _, entry = self._replay.popitem(last=False)
            self._replay_bytes -= entry.byte_size
            self._release_response_audio(entry)
        self._replay_capacity_event.set()

    def replay_after(self, cursor: int) -> list[CallWireOutput]:
        self._require_open()
        if cursor < self._server_ack_cursor or cursor > self.last_server_seq:
            raise CallTransportError("INVALID_REPLAY_CURSOR")
        return [entry.output for seq, entry in self._replay.items() if seq > cursor and entry.retired_by is None]

    def replay_missing(self, missing_seq: int) -> list[CallWireOutput]:
        self._require_open()
        entry = self._replay.get(missing_seq)
        if entry is None:
            raise CallTransportError("REPLAY_NOT_AVAILABLE")
        if entry.retired_by is not None:
            stop = self._replay.get(entry.retired_by)
            if stop is None:
                raise CallTransportError("REPLAY_NOT_AVAILABLE")
            return [stop.output]
        return [entry.output]

    def _require_next_server_seq(self, seq: int) -> None:
        if seq != self._server_next_seq:
            raise CallTransportError("INVALID_SERVER_SEQ")

    def _release_response_audio(self, entry: _ReplayEntry) -> None:
        if entry.response_id is None or entry.audio_payload_bytes == 0:
            return
        remaining = self._response_audio_bytes.get(entry.response_id, 0) - entry.audio_payload_bytes
        self._response_audio_bytes[entry.response_id] = max(0, remaining)
        entry.audio_payload_bytes = 0

    def _response_audio_limit(self, response_id: str) -> int:
        audio_format = self._response_formats.get(response_id)
        if audio_format is None:
            raise ValueError("response_id is not registered")
        encoding, sample_rate, channels = audio_format
        if encoding != "pcm_s16le":
            raise ValueError("response audio format has no retention budget")
        return sample_rate * channels * 2 * self._config.max_response_audio_seconds

    def close(self) -> None:
        """Release every bounded buffer and wake capacity waiters."""
        if self._closed:
            return
        self._closed = True
        self._pending.clear()
        self._pending_bytes = 0
        self._client_fingerprints.clear()
        self._replay.clear()
        self._replay_bytes = 0
        self._streams.clear()
        self._response_formats.clear()
        self._response_audio_bytes.clear()
        self._stop_metadata.clear()
        self._replay_capacity_event.set()

    def _require_open(self) -> None:
        if self._closed:
            raise CallTransportError("TRANSPORT_CLOSED", close_code=CALL_CLOSE_TRY_AGAIN_LATER)

    def _ack_output(self) -> CallWireOutput:
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "ack",
            "call_id": self.call_id,
            "ack_seq": self._client_cursor,
        }
        return CallWireOutput(text=encode_control_message(message, sender="server", transport="call_ws"))

    def _nack_output(self, missing_seq: int) -> CallWireOutput:
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "nack",
            "call_id": self.call_id,
            "missing_seq": missing_seq,
        }
        return CallWireOutput(text=encode_control_message(message, sender="server", transport="call_ws"))

    def _error_output(self, code: str, *, request_seq: int, retryable: bool) -> CallWireOutput:
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "error",
            "code": code,
            "message": "business sink did not accept the ordered frame",
            "retryable": retryable,
            "request_seq": request_seq,
            "call_id": self.call_id,
        }
        return CallWireOutput(text=encode_control_message(message, sender="server", transport="call_ws"))


@dataclass(frozen=True, slots=True)
class CallTransportBinding:
    session: CallTransportSession
    generation: int
    connection_id: object


@dataclass(slots=True)
class _HubEntry:
    session: CallTransportSession
    generation: int = 0
    connection_id: object | None = None


class CallTransportHub:
    """Session registry with atomic single-connection generation bindings."""

    def __init__(self) -> None:
        self._sessions: dict[str, _HubEntry] = {}
        self._lock = asyncio.Lock()

    def register(self, session: CallTransportSession) -> None:
        existing = self._sessions.get(session.call_id)
        if existing is not None and existing.session is not session:
            raise ValueError("call session already registered")
        self._sessions.setdefault(session.call_id, _HubEntry(session=session))

    async def unregister(self, call_id: str, *, expected_session: CallTransportSession) -> bool:
        async with self._lock:
            entry = self._sessions.get(call_id)
            if entry is None or entry.session is not expected_session:
                return False
            self._sessions.pop(call_id)
            expected_session.close()
            return True

    async def attach_resume(self, raw: str, *, user_id: str, connection_id: object) -> CallTransportBinding:
        try:
            message = decode_control_text(raw, sender="client", transport="call_ws")
        except ControlProtocolError as error:
            raise CallTransportError(error.code) from error
        if message["type"] != "call.resume":
            raise CallTransportError("CALL_START_UNAVAILABLE", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
        async with self._lock:
            entry = self._sessions.get(str(message["call_id"]))
            if entry is None:
                raise CallTransportError("CALL_NOT_FOUND", close_code=CALL_CLOSE_POLICY_VIOLATION)
            if entry.session.user_id != user_id:
                raise CallTransportError("RESUME_OWNERSHIP_MISMATCH", close_code=CALL_CLOSE_POLICY_VIOLATION)
            if entry.connection_id is not None:
                raise CallTransportError("CALL_CONNECTION_ACTIVE", close_code=CALL_CLOSE_POLICY_VIOLATION)
            entry.generation += 1
            entry.connection_id = connection_id
            return CallTransportBinding(entry.session, entry.generation, connection_id)

    def is_current(self, binding: CallTransportBinding) -> bool:
        entry = self._sessions.get(binding.session.call_id)
        return (
            entry is not None
            and entry.session is binding.session
            and entry.generation == binding.generation
            and entry.connection_id is binding.connection_id
        )

    def require_current(self, binding: CallTransportBinding) -> None:
        if not self.is_current(binding):
            raise CallTransportError("STALE_CALL_CONNECTION", close_code=CALL_CLOSE_POLICY_VIOLATION)

    def acknowledge_bound(self, binding: CallTransportBinding, ack_seq: int) -> None:
        self.require_current(binding)
        binding.session.acknowledge_server(ack_seq)

    async def detach(self, binding: CallTransportBinding) -> bool:
        async with self._lock:
            if not self.is_current(binding):
                return False
            entry = self._sessions[binding.session.call_id]
            entry.connection_id = None
            return True
