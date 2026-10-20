"""一个呼叫的协议会话，组合唯一 Stage 与跨重连 Delivery。"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from functools import partial

from src.domain.call import CallEndReason, CallFinalSnapshot, CallState
from src.stage.call_stage import (
    CallOutput,
    CallPCM,
    CallPlaybackStop,
    CallReplyFailed,
    CallSetupFailed,
    CallStateChanged,
    CallStreamStarted,
)
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ._delivery import Delivery
from ._input import process_input
from ._messages import CALL_CLOSE_TRY_AGAIN_LATER, InboundFrame, TransportBackpressure, TransportConfig, WireOutput
from ._protocol_translate import encode_control, make_ack, make_error, make_nack
from .errors import CallTransportError


class Session:
    """对外隐藏顺序接纳、恢复事务及下行交付状态，不替代 Stage 的业务状态机。"""

    def __init__(self, stage, *, config=None, call_metrics=None):
        self._stage = stage
        self.call_id = stage.call_id
        self.user_id = stage.user_id
        self.character_id = stage.character_id
        self._config = config or TransportConfig()
        self._delivery = Delivery(self.call_id, self._emit, config=self._config, call_metrics=call_metrics)
        self._binding = None
        self._connection_changed = asyncio.Condition()
        self._input_lock = asyncio.Lock()
        self._client_cursor = 0
        self._client_fingerprints = OrderedDict()
        self._pending = {}
        self._pending_bytes = 0
        self._closed = False
        self._resume_pending = None
        self._resume_bytes = 0

    async def attach(self, binding, *, resume_cursor: int | None = None) -> None:
        """首次绑定或恢复唯一连接，恢复输出排在新业务输出之前。"""
        async with self._connection_changed:
            self._require_open()
            if resume_cursor is None and self._binding is not None:
                raise CallTransportError("CALL_CONNECTION_ACTIVE", close_code=1008)
            if resume_cursor is not None and self._binding is not None:
                old = self._binding
                try:
                    await asyncio.wait_for(
                        self._connection_changed.wait_for(lambda: self._binding is not old or self._closed), timeout=2.5
                    )
                except asyncio.TimeoutError as error:
                    raise CallTransportError("CALL_CONNECTION_ACTIVE", close_code=1008) from error
            self._require_open()
            if self._binding is not None:
                raise CallTransportError("CALL_CONNECTION_ACTIVE", close_code=1008)
            if resume_cursor is None:
                self._binding = binding
                return
            await self._resume_binding(binding, resume_cursor)

    async def _resume_binding(self, binding, resume_cursor):
        outputs = (
            self._preview_resume(resume_cursor)
            if resume_cursor is not None
            else [
                make_ack(self.call_id, self._client_cursor),
                *self._delivery.replay_after(self._delivery.server_ack_cursor),
            ]
        )
        self._resume_pending = []
        self._resume_bytes = 0
        self._binding = binding
        business_started = False
        try:
            business_started = True
            if not await self._stage.reconnect():
                business_started = False
                raise CallTransportError("CALL_RESUME_UNAVAILABLE", close_code=1008)
            if resume_cursor is not None:
                self._delivery.acknowledge_server(resume_cursor)
            for output in outputs + self._resume_pending:
                self._enqueue(binding, output)
            binding.is_ready = True
        except BaseException as original_error:
            binding.invalidate()
            self._binding = None
            self._resume_pending = None
            if business_started:
                try:
                    self._stage.begin_termination(CallEndReason.SYSTEM_FAILURE)
                    await complete_owned(self._stage.wait_realtime_stopped())
                except BaseException as cleanup_error:
                    try:
                        get_logger(__name__).error(
                            "Call resume cleanup failed call=%s original=%s cleanup=%s",
                            self.call_id,
                            type(original_error).__name__,
                            type(cleanup_error).__name__,
                        )
                    except Exception:
                        pass
            raise
        finally:
            self._resume_pending = None
            self._resume_bytes = 0

    async def detach(self, binding) -> None:
        """先使旧连接失效并通知 Stage，再开放恢复槽；旧清理不影响新连接。"""
        binding.invalidate()
        async with self._connection_changed:
            if self._binding is not binding:
                return
            try:
                await self._stage.set_connection_available(False)
            finally:
                self._binding = None
                self._connection_changed.notify_all()

    async def receive(self, binding, frame) -> None:
        """分离协议反馈与有序业务输入，ACK 不等待业务接纳锁。"""
        self._require_current(binding)
        control = frame.control
        if control is not None and control["type"] != "call.start" and control.get("call_id") != self.call_id:
            raise CallTransportError("CALL_OWNERSHIP_MISMATCH", close_code=1008)
        if control is not None and control["type"] in {"ack", "nack"}:
            if control["type"] == "ack":
                self._delivery.acknowledge_server(int(control["ack_seq"]))
            else:
                for output in self._delivery.replay_missing(int(control["missing_seq"])):
                    self._enqueue(binding, output)
            return
        async with self._input_lock:
            self._require_current(binding)
            if control is not None and control["type"] == "call.start":
                await self._receive_start(binding, frame)
                return
            if control is not None:
                if control["type"] not in {"call.hangup", "playback.completed", "playback.stopped"}:
                    raise CallTransportError("UNEXPECTED_CONTROL")
                self._delivery.validate_client_control(control)
            outputs = await self._receive_ordered(frame)
            # 交付已提交的游标即使遇到断线也保留，新连接会重新协商确认。
            if self._binding is binding and not binding.is_closed:
                for output in outputs:
                    self._enqueue(binding, output)

    async def _receive_start(self, binding, frame):
        control = frame.control
        if frame.seq != 1 or control["character_id"] != self.character_id:
            raise CallTransportError("INVALID_CALL_START")
        digest = self._fingerprint(frame)
        known = self._client_fingerprints.get(1)
        if known is not None and known != digest:
            raise CallTransportError("SEQ_CONFLICT")
        if known is not None and not binding.is_ready:
            async with self._connection_changed:
                await self._resume_binding(binding, None)
            return
        if known is None:
            if self._client_cursor != 0:
                raise CallTransportError("INVALID_CALL_START")
            await self._delivery.send_state(
                CallStateChanged(self.call_id, CallState.PREPARING, self._stage.client_request_id)
            )
            self._client_fingerprints[1] = digest
            self._client_cursor = 1
        self._enqueue(binding, make_ack(self.call_id, self._client_cursor))
        if known is not None:
            for output in self._delivery.replay_after(self._delivery.server_ack_cursor):
                self._enqueue(binding, output)
        binding.is_ready = True

    async def _accept(self, frame, fingerprint):
        stopped = None
        if frame.control is not None and frame.control["type"] == "playback.stopped":
            stopped = self._delivery.stopped_stream(str(frame.control["response_id"]), int(frame.control["stop_seq"]))
        value, status = process_input(frame, call_id=self.call_id, fingerprint=fingerprint, stopped_stream_id=stopped)
        if status["state"] == "error":
            raise status["error"]
        if value[0] == "pcm":
            return self._stage.accept_pcm(value[1], value[2])
        if value[0] == "completed":
            self._stage.playback_completed(value[1], value[2])
        elif value[0] == "stopped":
            self._stage.playback_stopped(value[1], value[2])
        else:
            self._stage.begin_termination()
            await self._stage.wait_realtime_stopped()
        return True

    async def submit_output(self, output) -> None:
        """接纳领域输出并交给内部 Delivery，完成不代表网络或客户端确认。"""
        self._require_open()
        if isinstance(output, (CallStateChanged, CallReplyFailed, CallOutput)):
            await self._delivery.send_state(output)
        elif isinstance(output, CallFinalSnapshot):
            await self._delivery.send_ended(output)
        elif isinstance(output, CallSetupFailed):
            await self._delivery.send_failed(output.reason)
        elif isinstance(output, CallStreamStarted):
            await self._delivery.start_stream(output.response_id, output.stream_id, output.audio_format)
        elif isinstance(output, CallPCM):
            await self._delivery.send_pcm(output.response_id, output.stream_id, output.payload, final=output.final)
        elif isinstance(output, CallPlaybackStop):
            await self._delivery.stop_response(output.response_id, output.stream_ids)
        else:
            raise TypeError("unsupported call output")

    async def _emit(self, output):
        self._require_open()
        if self._resume_pending is not None:
            size = len(output.binary) if output.binary is not None else len(output.text.encode("utf-8"))
            if len(self._resume_pending) >= 256 or self._resume_bytes + size > 4 * 1024 * 1024:
                raise TransportBackpressure("RESUME_OUTPUT_BUFFER_FULL")
            self._resume_pending.append(output)
            self._resume_bytes += size
        elif self._binding is not None and not self._binding.is_closed:
            self._enqueue(self._binding, output)

    def _enqueue(self, binding, output):
        on_sent = (
            partial(self._stage.audio_sent, output.audio_response_id) if output.audio_response_id is not None else None
        )
        binding.enqueue(output.text if output.text is not None else output.binary, on_sent=on_sent)

    def _preview_resume(self, cursor):
        self._require_open()
        if cursor < self._delivery.server_ack_cursor or cursor > self._delivery.last_server_seq:
            raise CallTransportError("INVALID_RESUME_CURSOR")
        resumed = encode_control(
            {
                "protocol": "call.v1",
                "type": "call.resumed",
                "call_id": self.call_id,
                "character_id": self.character_id,
                "last_contiguous_client_seq": self._client_cursor,
                "last_contiguous_server_seq": cursor,
            }
        )
        return [resumed, *self._delivery.replay_after(cursor)]

    def _require_current(self, binding):
        self._require_open()
        if binding.is_closed or self._binding is not binding:
            raise CallTransportError("STALE_CALL_CONNECTION", close_code=1008)

    async def close(self) -> None:
        """释放协议资源并唤醒所有等待者；不替代 Stage 的业务收尾。"""
        async with self._input_lock:
            await self._close_binding()

    async def _close_binding(self) -> None:
        async with self._connection_changed:
            if self._closed:
                return
            self._closed = True
            self._delivery.close()
            self._pending.clear()
            self._pending_bytes = 0
            self._client_fingerprints.clear()
            if self._binding is not None:
                self._binding.invalidate()
            self._binding = None
            self._connection_changed.notify_all()

    async def drain_terminal(self) -> None:
        """在实时停止后有限等待终态入队和网络发送，不等待客户端 ACK。"""
        try:
            await asyncio.wait_for(self._delivery.terminal_enqueued.wait(), timeout=2.0)
            # 挂断的业务接纳提交及 ACK 入队完成后，才判断网络队列是否已排空。
            async with self._input_lock:
                pass
            binding = self._binding
            if binding is not None and not binding.is_closed:
                await asyncio.wait_for(binding.drain(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    async def _receive_ordered(self, frame: InboundFrame) -> list[WireOutput]:
        digest = self._fingerprint(frame)
        duplicate = self._duplicate_result(frame, digest)
        if duplicate is not None:
            return duplicate
        if frame.seq <= self._client_cursor:
            return [make_ack(self.call_id, self._client_cursor)]
        pending = self._pending.get(frame.seq)
        if pending is None and frame.seq == self._client_cursor + 1:
            self._pending[frame.seq] = frame
            self._pending_bytes += len(frame.raw)
        elif pending is None:
            self._add_pending(frame)
        if frame.seq > self._client_cursor + 1:
            return [make_nack(self.call_id, self._client_cursor + 1)]
        outputs: list[WireOutput] = []
        while (next_seq := self._client_cursor + 1) in self._pending:
            candidate = self._pending[next_seq]
            if len(self._client_fingerprints) >= self._config.max_received_fingerprints:
                raise CallTransportError("RECEIVE_HISTORY_FULL", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
            accepted = await complete_owned(self._accept_and_commit(candidate))
            if not accepted:
                outputs.append(self._error_output("OVERLOADED", request_seq=next_seq, retryable=True))
                return outputs
        outputs.append(make_ack(self.call_id, self._client_cursor))
        return outputs

    async def _accept_and_commit(self, frame: InboundFrame) -> bool:
        digest = self._fingerprint(frame)
        accepted = await self._accept(frame, digest)
        if not accepted:
            return False
        self._pending.pop(frame.seq)
        self._pending_bytes -= len(frame.raw)
        self._client_fingerprints[frame.seq] = digest
        self._client_cursor = frame.seq
        return True

    def _duplicate_result(self, frame: InboundFrame, digest: bytes) -> list[WireOutput] | None:
        known = self._client_fingerprints.get(frame.seq)
        if known is not None:
            if known != digest:
                raise CallTransportError("SEQ_CONFLICT")
            return [make_ack(self.call_id, self._client_cursor)]
        pending = self._pending.get(frame.seq)
        if pending is None:
            return None
        if self._fingerprint(pending) != digest:
            raise CallTransportError("SEQ_CONFLICT")
        if frame.seq > self._client_cursor + 1:
            return [make_nack(self.call_id, self._client_cursor + 1)]
        return None

    def _add_pending(self, frame: InboundFrame) -> None:
        if len(self._pending) >= self._config.max_pending_frames:
            raise CallTransportError("PENDING_WINDOW_FULL", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
        if self._pending_bytes + len(frame.raw) > self._config.max_pending_bytes:
            raise CallTransportError("PENDING_BYTES_FULL", close_code=CALL_CLOSE_TRY_AGAIN_LATER)
        self._pending[frame.seq] = frame
        self._pending_bytes += len(frame.raw)

    @staticmethod
    def _fingerprint(frame: InboundFrame) -> bytes:
        return hashlib.sha256(frame.kind.encode("ascii") + b"\0" + frame.raw).digest()

    def _require_open(self) -> None:
        if self._closed:
            raise CallTransportError("TRANSPORT_CLOSED", close_code=CALL_CLOSE_TRY_AGAIN_LATER)

    def _error_output(self, code: str, *, request_seq: int, retryable: bool) -> WireOutput:
        return encode_control(
            make_error(
                self.call_id,
                code,
                "business sink did not accept the ordered frame",
                retryable=retryable,
                request_seq=request_seq,
            )
        )
