"""Production-shaped bridge between CallStage semantics and call.v1 transport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

import src.domain.agent as d
from src.domain.call import CallEndReason, CallFinalSnapshot, CallState
from src.stage.call_stage import CallIngressReceipt, CallOutput, CallStage, CallStateChanged

from .audio_codec import CALL_ROUTE, FINAL_FLAG, VERSION, BinaryAudioFrameCodec, WireAudioFrame
from .control import ControlMessage
from .transport import CallAcceptanceReceipt, CallBusinessAcceptanceSink, CallTransportSession, InboundCallFrame


class CallStageBinding(CallBusinessAcceptanceSink):
    """Translate ordered wire frames and Stage output through one transport session."""

    def __init__(self, *, call_id: str, deliver: Callable[[object], Awaitable[None]]) -> None:
        self.call_id = call_id
        self._deliver = deliver
        self._stage: CallStage | None = None
        self._session: CallTransportSession | None = None
        self._codec = BinaryAudioFrameCodec()
        self._terminal_sent = False

    def bind(self, *, stage: CallStage, session: CallTransportSession) -> None:
        if session.call_id != self.call_id or stage.snapshot is not None:
            raise ValueError("call binding identity is unavailable")
        if self._stage is not None or self._session is not None:
            raise ValueError("call binding is already active")
        self._stage, self._session = stage, session

    async def accept(self, frame: InboundCallFrame, receipt: CallAcceptanceReceipt) -> bool:
        stage = self._require_stage()
        if frame.audio is not None:
            return stage.accept_pcm(
                CallIngressReceipt(receipt.call_id, receipt.direction, receipt.seq, receipt.fingerprint),
                frame.audio.payload,
            )
        message = frame.control
        if message is None:
            return False
        if message["type"] == "playback.completed":
            stage.playback_completed(str(message["response_id"]), int(message["stream_id"]))
            return True
        if message["type"] == "playback.stopped":
            response_id = str(message["response_id"])
            return any(
                stage.playback_stopped(response_id, stream_id)
                for item_response, stream_id in stage._playback.pending_streams
                if item_response == response_id
            )
        if message["type"] == "call.hangup":
            await stage.terminate()
            return True
        return False

    async def send_state(self, item: object) -> None:
        session = self._require_session()
        if isinstance(item, CallOutput):
            return
        if not isinstance(item, CallStateChanged):
            raise TypeError("unsupported CallStage state output")
        if item.state not in {CallState.PREPARING, CallState.RINGING, CallState.ACTIVE}:
            return
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "call.state",
            "seq": session.next_server_seq,
            "call_id": self.call_id,
            "client_request_id": self._require_stage()._ownership.client_request_id,
            "state": item.state.value,
        }
        if item.state is CallState.ACTIVE:
            connected = self._require_stage()._record.connected_at
            assert isinstance(connected, datetime)
            message = {
                "protocol": "call.v1",
                "type": "call.active",
                "seq": session.next_server_seq,
                "call_id": self.call_id,
                "connected_at_ms": int(connected.timestamp() * 1000),
            }
        await self._deliver(session.send_control(message))

    async def send_ended(self, snapshot: CallFinalSnapshot) -> None:
        if self._terminal_sent:
            return
        if str(snapshot.terminal.call_id) != self.call_id:
            raise ValueError("terminal snapshot does not match binding")
        session = self._require_session()
        terminal = snapshot.terminal
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "call.ended",
            "seq": session.next_server_seq,
            "call_id": self.call_id,
            "outcome": terminal.outcome.value,
            "end_reason": terminal.end_reason.value,
            "active_duration_ms": terminal.active_duration_ms,
        }
        await self._deliver(session.send_control(message))
        self._terminal_sent = True

    async def send_failed(self, reason: CallEndReason) -> None:
        if self._terminal_sent:
            return
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "error",
            "code": "CALL_SETUP_FAILED",
            "message": reason.value,
            "retryable": False,
            "call_id": self.call_id,
        }
        await self._deliver(self._require_session().send_control(message))
        self._terminal_sent = True

    async def start_stream(self, response_id: str, stream_id: int, audio_format: d.AudioFormat) -> None:
        session = self._require_session()
        message: ControlMessage = {
            "protocol": "call.v1",
            "type": "audio.stream_started",
            "seq": session.next_server_seq,
            "call_id": self.call_id,
            "audio_route": "CALL",
            "stream_id": stream_id,
            "response_id": response_id,
            "encoding": audio_format.encoding.value,
            "sample_rate": audio_format.sample_rate,
            "channels": audio_format.channels,
        }
        await self._deliver(session.send_control(message))

    async def send_pcm(self, response_id: str, stream_id: int, payload: bytes, *, final: bool) -> None:
        session = self._require_session()
        frame = WireAudioFrame(
            VERSION,
            CALL_ROUTE,
            FINAL_FLAG if final else 0,
            stream_id,
            session.next_server_seq,
            payload,
        )
        wire_bytes = len(self._codec.encode(frame))
        await session.wait_for_audio_capacity(response_id, wire_bytes, len(payload))
        await self._deliver(session.send_audio(frame))

    async def stop_response(self, response_id: str, stream_ids: tuple[int, ...]) -> None:
        session = self._require_session()
        for stream_id in stream_ids:
            start, through = session.response_server_range(response_id, stream_id)
            message: ControlMessage = {
                "protocol": "call.v1",
                "type": "playback.stop",
                "seq": session.next_server_seq,
                "call_id": self.call_id,
                "response_id": response_id,
                "stream_id": stream_id,
                "retire_server_seq": {"from": start, "through": through},
                "reason": "user_interrupted",
            }
            await self._deliver(session.send_control(message))

    def _require_stage(self) -> CallStage:
        if self._stage is None:
            raise RuntimeError("CallStage is not bound")
        return self._stage

    def _require_session(self) -> CallTransportSession:
        if self._session is None:
            raise RuntimeError("CallTransportSession is not bound")
        return self._session
