"""WS 消息与 Adapter 内部消息契约之间的转换：入站解析、控制响应与下行编码。"""

import base64
import json
import time
from collections.abc import Iterator

import src.domain.agent as d

from ._messages import WSMessage


def encode_message(message: dict) -> str:
    """将已成形的协议消息编码为 JSON，不额外添加事件信封。"""
    return json.dumps(message, ensure_ascii=False)


def encode_event(event_type: str, payload: dict, *, reply_to=None) -> str:
    """构造聊天事件信封并编码为 JSON，附带毫秒时间戳及可选请求关联标识。"""
    event = {"type": event_type, "ts": int(time.time() * 1000), "payload": payload}
    if reply_to:
        event["reply_to"] = reply_to
    return encode_message(event)


def enqueue_event(binding, event_type: str, payload: dict, *, reply_to=None):
    """编码并直接排队即时协议响应，返回网络完成 Future，不等待业务就绪门控。"""
    return binding.enqueue(encode_event(event_type, payload, reply_to=reply_to))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(token):
    raise ValueError(token)


def parse(binding, raw: str | bytes, *, max_bytes: int, max_image_bytes: int) -> WSMessage | None:
    """解析并校验原始聊天报文；无效时排队错误应答并返回 None，成功时保留原始报文。"""
    try:
        if not isinstance(raw, str):
            raise ValueError("chat requires text")
        size = len(raw.encode("utf-8"))
        data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        enqueue_event(binding, "error", {"code": "BAD_JSON", "message": "message must be a JSON object"})
        return None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        enqueue_event(binding, "error", {"code": "BAD_MESSAGE", "message": "message must have a 'type' field"})
        return None
    event = WSMessage(
        data["type"], data.get("payload", {}), data.get("client_msg_id"), data.get("ts"), raw_event=data, raw_text=raw
    )
    limit = max_image_bytes if event.event_type == "user_image" else max_bytes
    if size > limit:
        reject(binding, event, "BAD_MESSAGE", "message exceeds the inbound frame limit", False)
        return None
    return event


def ack(binding, event, *, payload=None, duplicate=False):
    """为带消息标识的已接收请求排队成功 ACK，可附带上传结果和重复请求标记。"""
    if event.client_msg_id is None:
        return
    body = {"ok": True, "received_event_type": event.event_type, **(payload or {})}
    if duplicate:
        body["duplicate"] = True
    enqueue_event(binding, "server_ack", body, reply_to=event.client_msg_id)


def reject(binding, event, code, message, retryable):
    """根据连接协商能力排队负 ACK 或错误事件，保留错误码、可重试性和请求关联。"""
    body = {"received_event_type": event.event_type, "code": code, "message": message, "retryable": retryable}
    negative_ack = "negative_ack_v1" in binding.capabilities
    if negative_ack:
        body["ok"] = False
    enqueue_event(binding, "server_ack" if negative_ack else "error", body, reply_to=event.client_msg_id)


def heartbeat(binding, event):
    """校验心跳标识，对比连接游标并为新的有效心跳排队响应。"""
    payload = event.payload if isinstance(event.payload, dict) else {}
    ping = payload.get("ping_id")
    if type(ping) is not int:
        enqueue_event(
            binding, "error", {"code": "MISSING_PING_ID", "message": "ping event must have a ping_id in payload"}
        )
    elif binding.last_ping_id is None or binding.last_ping_id < ping:
        binding.last_ping_id = ping
        enqueue_event(
            binding, "hb_pong", {"ping_id": ping, "server_ts": int(time.time() * 1000)}, reply_to=event.client_msg_id
        )


def update_model_types(binding, raw_payload):
    """从客户端声明中提取模型能力，清理格式后更新连接状态。"""
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    mode = payload.get("llm_mode")
    if not isinstance(mode, dict):
        return
    types = mode.get("types")
    if isinstance(types, str):
        types = [types]
    if isinstance(types, list):
        binding.client_mode = {"types": [item.strip() for item in types if isinstance(item, str) and item.strip()]}


def payloads(output: d.AgentOutput) -> Iterator[dict[str, object]]:
    """将领域输出转换为一个或多个聊天包的内容字段；身份和序号由投递调度补齐。"""
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
