"""原始 WebSocket 报文与通话内部帧之间的无状态转换。"""

from ._audio_codec import CALL_ROUTE, BinaryAudioFrameCodec
from ._control import ControlProtocolError, decode_control_text, encode_control_message
from ._messages import InboundFrame, WireOutput
from .errors import CallTransportError


def parse_message(raw: str | bytes) -> InboundFrame:
    """校验控制或音频帧并保留用于去重的原始内容，不推进协议状态。"""
    try:
        if isinstance(raw, bytes):
            audio = BinaryAudioFrameCodec().decode(raw)
            if audio.route != CALL_ROUTE or audio.stream_id != 0:
                raise CallTransportError("INVALID_CLIENT_AUDIO_ROUTE")
            return InboundFrame(seq=audio.seq, kind="audio", raw=raw, audio=audio)
        if not isinstance(raw, str):
            raise CallTransportError("INVALID_WEBSOCKET_FRAME")
        control = decode_control_text(raw, sender="client", transport="call_ws")
        return InboundFrame(seq=int(control.get("seq", 0)), kind="control", raw=raw.encode("utf-8"), control=control)
    except ControlProtocolError as error:
        raise CallTransportError(error.code, close_code=1009 if error.code == "CONTROL_TOO_LARGE" else 1002) from error
    except ValueError as error:
        raise CallTransportError(getattr(error, "code", "BAD_AUDIO_FRAME")) from error


def encode_control(message) -> WireOutput:
    """编码服务端控制报文，不修改调用方提供的序号。"""
    return WireOutput(text=encode_control_message(message, sender="server", transport="call_ws"))


def make_ack(call_id: str, ack_seq: int):
    """构造已连续接纳到指定游标的确认。"""
    return encode_control({"protocol": "call.v1", "type": "ack", "call_id": call_id, "ack_seq": ack_seq})


def make_nack(call_id: str, missing_seq: int):
    """构造首个缺口的重传请求。"""
    return encode_control({"protocol": "call.v1", "type": "nack", "call_id": call_id, "missing_seq": missing_seq})


def make_state(call_id, item, seq):
    """把 Stage 状态或回复错误转换为控制消息；内部状态不产生线路消息。"""
    from src.domain.call import CallState
    from src.stage.call_stage import CallOutput, CallReplyFailed, CallStateChanged

    if isinstance(item, CallReplyFailed):
        return make_error(call_id, "CALL_TTS_FAILED", "call reply audio could not be generated")
    if isinstance(item, CallOutput):
        return None
    if not isinstance(item, CallStateChanged):
        raise TypeError("unsupported CallStage state output")
    if item.state not in {CallState.PREPARING, CallState.RINGING, CallState.ACTIVE}:
        return None
    if item.state is CallState.ACTIVE:
        if item.connected_at is None:
            raise ValueError("ACTIVE state requires connected_at")
        return {
            "protocol": "call.v1",
            "type": "call.active",
            "seq": seq,
            "call_id": call_id,
            "connected_at_ms": int(item.connected_at.timestamp() * 1000),
        }
    return {
        "protocol": "call.v1",
        "type": "call.state",
        "seq": seq,
        "call_id": call_id,
        "client_request_id": item.client_request_id,
        "state": item.state.value,
    }


def make_error(call_id, code, message, *, retryable=False, request_seq=None):
    """构造不占下行序号的错误消息，可关联原始请求序号。"""
    result = {
        "protocol": "call.v1",
        "type": "error",
        "code": code,
        "message": message,
        "retryable": retryable,
        "call_id": call_id,
    }
    if request_seq is not None:
        result["request_seq"] = request_seq
    return result


def make_ended(call_id, snapshot, seq):
    """校验呼叫身份并将终态快照转换为通话结束消息。"""
    terminal = snapshot.terminal
    if str(terminal.call_id) != call_id:
        raise ValueError("terminal snapshot does not match session")
    return {
        "protocol": "call.v1",
        "type": "call.ended",
        "seq": seq,
        "call_id": call_id,
        "outcome": terminal.outcome.value,
        "end_reason": terminal.end_reason.value,
        "active_duration_ms": terminal.active_duration_ms,
    }


def make_stream_started(call_id, response_id, stream_id, audio_format, seq):
    """把流身份及领域音频格式转换为流开始消息。"""
    return {
        "protocol": "call.v1",
        "type": "audio.stream_started",
        "seq": seq,
        "call_id": call_id,
        "audio_route": "CALL",
        "stream_id": stream_id,
        "response_id": response_id,
        "encoding": audio_format.encoding.value,
        "sample_rate": audio_format.sample_rate,
        "channels": audio_format.channels,
    }


def make_playback_stop(call_id, response_id, stream_id, seq, start, through):
    """按 Delivery 提供的撤回范围构造停止播放消息，不自行计算范围。"""
    return {
        "protocol": "call.v1",
        "type": "playback.stop",
        "seq": seq,
        "call_id": call_id,
        "response_id": response_id,
        "stream_id": stream_id,
        "retire_server_seq": {"from": start, "through": through},
        "reason": "user_interrupted",
    }


def encode_audio(frame):
    """校验并编码一个音频帧，不分配流身份或协议序号。"""
    return WireOutput(binary=BinaryAudioFrameCodec().encode(frame))
