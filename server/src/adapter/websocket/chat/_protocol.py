"""聊天协议：入站解析、控制响应和下行业务输出的字段映射。"""

import base64
import json
import time
from collections.abc import Iterator

import src.domain.agent as d

from ._messages import _WSMessage


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(token):
    raise ValueError(token)


def _parse(peer, raw: str | bytes, *, max_bytes: int, max_image_bytes: int) -> _WSMessage | None:
    try:
        if not isinstance(raw, str):
            raise ValueError("chat requires text")
        size = len(raw.encode("utf-8"))
        data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        peer.enqueue_event("error", {"code": "BAD_JSON", "message": "message must be a JSON object"})
        return None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        peer.enqueue_event("error", {"code": "BAD_MESSAGE", "message": "message must have a 'type' field"})
        return None
    event = _WSMessage(
        data["type"], data.get("payload", {}), data.get("client_msg_id"), data.get("ts"), raw_event=data, raw_text=raw
    )
    limit = max_image_bytes if event.event_type == "user_image" else max_bytes
    if size > limit:
        _reject(peer, event, "BAD_MESSAGE", "message exceeds the inbound frame limit", False)
        return None
    return event


def _ack(peer, event, *, payload=None, duplicate=False):
    if event.client_msg_id is None:
        return
    body = {"ok": True, "received_event_type": event.event_type, **(payload or {})}
    if duplicate:
        body["duplicate"] = True
    peer.enqueue_event("server_ack", body, reply_to=event.client_msg_id)


def _reject(peer, event, code, message, retryable):
    body = {"received_event_type": event.event_type, "code": code, "message": message, "retryable": retryable}
    negative_ack = "negative_ack_v1" in peer.capabilities
    if negative_ack:
        body["ok"] = False
    peer.enqueue_event("server_ack" if negative_ack else "error", body, reply_to=event.client_msg_id)


def _heartbeat(peer, event):
    payload = event.payload if isinstance(event.payload, dict) else {}
    ping = payload.get("ping_id")
    if type(ping) is not int:
        peer.enqueue_event("error", {"code": "MISSING_PING_ID", "message": "ping event must have a ping_id in payload"})
    elif peer.last_ping_id is None or peer.last_ping_id < ping:
        peer.last_ping_id = ping
        peer.enqueue_event(
            "hb_pong", {"ping_id": ping, "server_ts": int(time.time() * 1000)}, reply_to=event.client_msg_id
        )


def _update_model_types(peer, raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    mode = payload.get("llm_mode")
    if not isinstance(mode, dict):
        return
    types = mode.get("types")
    if isinstance(types, str):
        types = [types]
    if isinstance(types, list):
        peer.client_mode = {"types": [item.strip() for item in types if isinstance(item, str) and item.strip()]}


def _payloads(output: d.AgentOutput) -> Iterator[dict[str, object]]:
    """将 output 转成一个或多个包的内容字段；连接身份和包序号由投递流程补齐。"""
    if isinstance(output, d.TextFinalOutput):
        yield {"text": output.text if output.delivery is d.OutputDelivery.CONVERSATION else ""}
    elif isinstance(output, d.ExpressionOutput):
        yield {"expression": output.expression.expression_id}
    elif isinstance(output, d.AudioChunkOutput):
        for offset in range(0, len(output.data), 48 * 1024):
            yield {"audio": base64.b64encode(output.data[offset : offset + 48 * 1024]).decode("ascii")}
    elif isinstance(output, d.MessageEndOutput):
        error = None
        if output.status is d.MessageEndStatus.CANCELLED:
            error = "TTS_CANCELLED"
        elif output.status is d.MessageEndStatus.FAILED:
            error = "TTS_EMPTY" if output.error_code is d.AudioErrorCode.EMPTY_AUDIO else "TTS_STREAM_ERROR"
        yield {"is_final_package": True, "audio_error": error is not None, "error_code": error}
    else:
        raise TypeError("unsupported output")
