"""将按序接纳的协议帧转换为 Stage 输入，不调用 Stage。"""

from src.stage.call_stage import CallIngressReceipt


def process_input(frame, *, call_id: str, fingerprint: bytes, stopped_stream_id: int | None = None):
    """返回 (输入参数, complete/error 状态)；排序、去重和 ACK 由 Session 管理。"""
    if frame.audio is not None:
        receipt = CallIngressReceipt(call_id, "client_to_server", frame.seq, fingerprint)
        return ("pcm", receipt, frame.audio.payload), {"state": "complete"}
    message = frame.control
    if message is None:
        return None, {"state": "error", "error": ValueError("missing business input")}
    kind = message["type"]
    if kind == "call.hangup":
        return ("hangup",), {"state": "complete"}
    if kind == "playback.completed":
        return ("completed", str(message["response_id"]), int(message["stream_id"])), {"state": "complete"}
    if kind == "playback.stopped" and stopped_stream_id is not None:
        return ("stopped", str(message["response_id"]), stopped_stream_id), {"state": "complete"}
    return None, {"state": "error", "error": ValueError("unsupported business input")}
