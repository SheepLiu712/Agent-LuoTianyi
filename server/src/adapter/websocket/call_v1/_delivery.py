"""通话下行编号、容量、重放和取消结算；由 Session 独占持有。"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import src.domain.agent as d
from src.domain.call import CallEndReason, CallFinalSnapshot
from src.infrastructure.observability.call_metrics import CallMetric, CallMetricName, CallMetricResult, CallMetricStatus

from ._audio_codec import CALL_ROUTE, FINAL_FLAG, HEADER_SIZE, VERSION, WireAudioFrame
from ._control import ControlMessage
from ._messages import (
    CALL_CLOSE_POLICY_VIOLATION,
    CALL_CLOSE_TRY_AGAIN_LATER,
    TransportBackpressure,
    TransportConfig,
    WireOutput,
)
from ._protocol_translate import (
    encode_audio,
    encode_control,
    make_ended,
    make_error,
    make_playback_stop,
    make_state,
    make_stream_started,
)
from .errors import CallTransportError


@dataclass(slots=True)
class _ReplayEntry:
    seq: int
    output: WireOutput
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
    last_seq: int
    encoding: str
    sample_rate: int
    channels: int
    final_seen: bool = False
    contiguous: bool = True


@dataclass(frozen=True, slots=True)
class _StopMetadata:
    stop_seq: int
    response_id: str
    stream_id: int


class Delivery:
    """维护一个呼叫的下行状态，网络断线不清除未确认消息。"""

    def __init__(self, call_id, emit, *, config=None, call_metrics=None):
        self.call_id = call_id
        self._deliver = emit
        self._config = config or TransportConfig()
        self._call_metrics = call_metrics
        self._server_next_seq = 1
        self._server_ack_cursor = 0
        self._replay = OrderedDict()
        self._replay_bytes = 0
        self._streams = {}
        self._response_formats = {}
        self._response_audio_bytes = {}
        self._stop_metadata = {}
        self._replay_capacity_event = asyncio.Event()
        self._replay_capacity_event.set()
        self._closed = False
        self._ack_retry_count = 0
        self._terminal_sent = False
        self.terminal_enqueued = asyncio.Event()

    @property
    def server_ack_cursor(self) -> int:
        """返回客户端已连续确认的下行序号。"""
        return self._server_ack_cursor

    @property
    def last_server_seq(self) -> int:
        """返回已经分配的最大下行序号。"""
        return self._server_next_seq - 1

    @property
    def _next_server_seq(self) -> int:
        """Return the next shared control/audio sequence owned by this session."""
        self._require_open()
        return self._server_next_seq

    def _response_server_range(self, response_id: str, stream_id: int) -> tuple[int, int]:
        """Return the allocated replay range for one registered response stream."""
        registration = self._streams.get(stream_id)
        if registration is None or registration.response_id != response_id:
            raise CallTransportError("UNREGISTERED_STREAM")
        return registration.first_seq, registration.last_seq

    def stopped_stream(self, response_id: str, stop_seq: int) -> int:
        """根据已登记的停止回执解析流，支持重复确认。"""
        stop = self._stop_metadata.get(stop_seq)
        if stop is None or stop.response_id != response_id:
            raise CallTransportError("INVALID_PLAYBACK_STOP_CONFIRMATION")
        return stop.stream_id

    def _send_control(self, message: ControlMessage) -> WireOutput:
        self._require_open()
        if message["type"] in {"ack", "nack", "call.resumed", "error"}:
            return encode_control(message)
        seq = int(message.get("seq", 0))
        self._require_next_server_seq(seq)
        output = encode_control(message)
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
                last_seq=seq,
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

    def _send_audio(self, frame: WireAudioFrame) -> WireOutput:
        self._require_open()
        self._require_next_server_seq(frame.seq)
        if frame.route != CALL_ROUTE or frame.stream_id == 0:
            raise CallTransportError("INVALID_SERVER_AUDIO_ROUTE")
        registration = self._streams.get(frame.stream_id)
        if registration is None:
            raise CallTransportError("UNREGISTERED_STREAM")
        if registration.final_seen:
            raise CallTransportError("STREAM_ALREADY_FINAL")
        raw = encode_audio(frame).binary
        output = WireOutput(binary=raw)
        self._require_response_audio_capacity(registration, len(frame.payload))
        self._store_replay(
            frame.seq,
            output,
            response_id=registration.response_id,
            stream_id=registration.stream_id,
            audio_payload_bytes=len(frame.payload),
        )
        registration.contiguous = registration.contiguous and frame.seq == registration.last_seq + 1
        registration.last_seq = frame.seq
        self._response_audio_bytes[registration.response_id] += len(frame.payload)
        self._record_metric(
            CallMetricName.BUFFER,
            numeric={"buffered_bytes": self._replay_bytes},
            labels={"result": CallMetricResult.SUCCEEDED.value},
        )
        if frame.flags & FINAL_FLAG:
            registration.final_seen = True
        self._server_next_seq += 1
        return output

    def _store_replay(
        self,
        seq: int,
        output: WireOutput,
        *,
        response_id: str | None,
        stream_id: int | None,
        audio_payload_bytes: int = 0,
    ) -> None:
        byte_size = len(output.binary if output.binary is not None else output.text.encode("utf-8"))
        if self._replay_bytes + byte_size > self._config.max_replay_bytes:
            self._replay_capacity_event.clear()
            raise TransportBackpressure("REPLAY_BUFFER_FULL")
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
            raise TransportBackpressure("RESPONSE_AUDIO_BUFFER_FULL")

    async def _wait_for_replay_capacity(self, byte_size: int) -> None:
        """Wait without spawning tasks until an ACK frees the requested capacity."""
        if type(byte_size) is not int or byte_size <= 0 or byte_size > self._config.max_replay_bytes:
            raise ValueError("byte_size must fit the replay buffer")
        while not self._closed and self._replay_bytes + byte_size > self._config.max_replay_bytes:
            self._replay_capacity_event.clear()
            await self._replay_capacity_event.wait()
        self._require_open()

    async def _wait_for_audio_capacity(self, response_id: str, wire_bytes: int, payload_bytes: int) -> None:
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
        if through > registration.last_seq or not registration.contiguous:
            raise CallTransportError("INVALID_RETIRE_RANGE")
        for seq in range(max(start, self._server_ack_cursor + 1), through + 1):
            entry = self._replay.get(seq)
            if entry is None or entry.response_id != response_id or entry.stream_id != stream_id:
                raise CallTransportError("INVALID_RETIRE_RANGE")

    def _send_stop_atomically(self, message: ControlMessage, output: WireOutput) -> WireOutput:
        self._validate_retirement(message)
        if len(self._stop_metadata) >= self._config.max_stop_metadata:
            raise TransportBackpressure("STOP_METADATA_FULL")
        retired = message["retire_server_seq"]
        assert isinstance(retired, dict)
        start, through, stop_seq = int(retired["from"]), int(retired["through"]), int(message["seq"])
        stop_bytes = len(output.text.encode("utf-8"))
        retired_bytes = sum(entry.byte_size for seq, entry in self._replay.items() if start <= seq <= through)
        if self._replay_bytes - retired_bytes + stop_bytes > self._config.max_replay_bytes:
            self._replay_capacity_event.clear()
            raise TransportBackpressure("REPLAY_BUFFER_FULL")
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
        for seq in range(max(start, self._server_ack_cursor + 1), through + 1):
            entry = self._replay[seq]
            self._replay_bytes -= entry.byte_size
            self._release_response_audio(entry)
            entry.output = WireOutput(text="")
            entry.byte_size = 0
            entry.retired_by = stop_seq
        self._replay_capacity_event.set()
        self._record_metric(
            CallMetricName.PLAYBACK_BACKLOG,
            numeric={"buffered_bytes": self._replay_bytes},
            labels={"result": CallMetricResult.SUCCEEDED.value},
        )

    def validate_client_control(self, message: ControlMessage) -> None:
        """根据下行流与停止元数据校验客户端播放反馈。"""
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
        """推进连续确认游标并释放已确认的重放容量。"""
        self._require_open()
        if ack_seq < self._server_ack_cursor or ack_seq > self.last_server_seq:
            raise CallTransportError("INVALID_ACK_CURSOR")
        self._server_ack_cursor = ack_seq
        while self._replay and next(iter(self._replay)) <= ack_seq:
            _, entry = self._replay.popitem(last=False)
            self._replay_bytes -= entry.byte_size
            self._release_response_audio(entry)
        self._replay_capacity_event.set()

    def replay_after(self, cursor: int) -> list[WireOutput]:
        """返回游标之后仍需重放的原始报文，不重新编号。"""
        self._require_open()
        if cursor < self._server_ack_cursor or cursor > self.last_server_seq:
            raise CallTransportError("INVALID_REPLAY_CURSOR")
        return [entry.output for seq, entry in self._replay.items() if seq > cursor and entry.retired_by is None]

    def replay_missing(self, missing_seq: int) -> list[WireOutput]:
        """重放指定缺口起的有效报文，已撤回音频以停止消息替代。"""
        self._require_open()
        self._ack_retry_count += 1
        self._record_metric(
            CallMetricName.PLAYBACK_ACK_RETRY,
            numeric={"ack_retry_count": self._ack_retry_count},
            labels={"result": CallMetricResult.SUCCEEDED.value},
        )
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

    def _require_open(self) -> None:
        if self._closed:
            raise CallTransportError("TRANSPORT_CLOSED", close_code=CALL_CLOSE_TRY_AGAIN_LATER)

    def _record_metric(self, name, *, numeric=None, labels=None) -> None:
        if self._call_metrics is None:
            return
        try:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            self._call_metrics.record(
                CallMetric(
                    call_id=UUID(self.call_id),
                    name=name,
                    start_ts=timestamp,
                    end_ts=timestamp,
                    duration_ms=0,
                    status=CallMetricStatus.SUCCESS,
                    numeric=numeric,
                    labels=labels,
                )
            )
        except Exception:
            pass

    async def send_state(self, item: object) -> None:
        """将状态或回复错误转换为下行协议并保留可重放内容。"""
        message = make_state(self.call_id, item, self._next_server_seq)
        if message is not None:
            await self._deliver(self._send_control(message))

    async def send_ended(self, snapshot: CallFinalSnapshot) -> None:
        """幂等排入通话终止消息，标记终态输出已接纳。"""
        if self._terminal_sent:
            return
        await self._deliver(self._send_control(make_ended(self.call_id, snapshot, self._next_server_seq)))
        self._terminal_sent = True
        self.terminal_enqueued.set()

    async def send_failed(self, reason: CallEndReason) -> None:
        """幂等排入建立失败消息，标记终态输出已接纳。"""
        if self._terminal_sent:
            return
        await self._deliver(self._send_control(make_error(self.call_id, "CALL_SETUP_FAILED", reason.value)))
        self._terminal_sent = True
        self.terminal_enqueued.set()

    async def start_stream(self, response_id: str, stream_id: int, audio_format: d.AudioFormat) -> None:
        """原子登记音频流、分配序号并排入流开始消息。"""
        message = make_stream_started(self.call_id, response_id, stream_id, audio_format, self._next_server_seq)
        await self._deliver(self._send_control(message))

    async def send_pcm(self, response_id: str, stream_id: int, payload: bytes, *, final: bool) -> None:
        """等待容量后分配序号，保存音频重放内容并排入当前连接。"""
        wire_bytes = HEADER_SIZE + len(payload)
        await self._wait_for_audio_capacity(response_id, wire_bytes, len(payload))
        frame = WireAudioFrame(
            VERSION, CALL_ROUTE, FINAL_FLAG if final else 0, stream_id, self._next_server_seq, payload
        )
        await self._deliver(self._send_audio(frame))

    async def stop_response(self, response_id: str, stream_ids: tuple[int, ...]) -> None:
        """撤回响应音频并排入对应停止消息，保留停止回执元数据。"""
        for stream_id in stream_ids:
            start, through = self._response_server_range(response_id, stream_id)
            message = make_playback_stop(self.call_id, response_id, stream_id, self._next_server_seq, start, through)
            await self._deliver(self._send_control(message))

    def close(self) -> None:
        """释放协议缓存并唤醒容量等待者。"""
        if self._closed:
            return
        self._closed = True
        self._replay.clear()
        self._replay_bytes = 0
        self._streams.clear()
        self._response_formats.clear()
        self._response_audio_bytes.clear()
        self._stop_metadata.clear()
        self._replay_capacity_event.set()
