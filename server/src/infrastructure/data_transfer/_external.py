"""Text-only external conversation readers with deterministic source identities."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from ._schema import FORMAT, MAX_RECORDS, VERSION, TransferFormatError, json_bytes, read_json, require

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
FORMATS = {"auto", "native", "chatgpt", "sillytavern", "generic"}


def _warn(warnings, text):
    if text not in warnings:
        warnings.append(text)


def _digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _identifier(value, fallback):
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value) else fallback


def _load_document(data):
    try:
        return read_json(data)
    except TransferFormatError as original:
        try:
            lines = data.decode("utf-8-sig").splitlines()
            rows = [read_json(line) for line in lines if line.strip()]
            require(bool(rows) and all(isinstance(row, dict) for row in rows), "Invalid JSONL document")
            return rows
        except (TransferFormatError, UnicodeError):
            raise TransferFormatError("Expected a UTF-8 JSON or JSONL conversation document") from original


def _detect(document):
    rows = document if isinstance(document, list) else [document]
    if rows and all(isinstance(row, dict) and "mapping" in row for row in rows):
        return "chatgpt"
    if rows and isinstance(rows[0], dict):
        header = rows[0]
        if "is_user" in header or {"user_name", "character_name", "chat_metadata"}.intersection(header):
            return "sillytavern"
    return "generic"


def _iso_timestamp(value):
    if type(value) in (int, float):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        value = value.strip()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _silly_timestamp(value)
    raise ValueError("No usable timestamp")


def _silly_timestamp(value):
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2}) @(\d{1,2})h (\d{1,2})m (\d{1,2})s(?: (\d{1,3})ms)?", value)
    if match:
        year, month, day, hour, minute, second, millis = [int(part or 0) for part in match.groups()]
        return datetime(year, month, day, hour, minute, second, millis * 1000)
    for pattern in ("%B %d, %Y %I:%M%p", "%B %d, %Y %I:%M:%S%p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError("Unrecognized external timestamp")


def _timestamp(value, index, warnings):
    try:
        result = _iso_timestamp(value)
        result = result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        result = EPOCH + timedelta(seconds=index)
        _warn(warnings, "部分消息缺少有效时间，已使用 1970-01-01 UTC 加消息序号作为稳定时间。")
    return result.isoformat()


def _text(content, warnings):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _text_parts(content, warnings)
    _warn(warnings, "已跳过不支持的非文字内容。")
    return ""


def _text_parts(parts, warnings):
    texts = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict) and part.get("type") in {"text", "input_text", "output_text"}:
            value = part.get("text")
            if isinstance(value, str):
                texts.append(value)
            else:
                _warn(warnings, "已跳过不支持的非文字内容。")
        else:
            _warn(warnings, "已跳过不支持的媒体内容；不会下载外部文件。")
    return "\n".join(texts)


def _attachments(row, warnings):
    keys = ("attachments", "attachment", "files", "images", "media", "image", "audio", "video", "file")
    containers = [row, row.get("extra"), row.get("metadata")]
    present = any(isinstance(item, dict) and any(item.get(key) for key in keys) for item in containers)
    if present:
        _warn(warnings, "已跳过不支持的媒体附件；不会下载外部文件。")


def _base(source_format, character_id):
    return {
        "format": FORMAT,
        "version": VERSION,
        "source_format": source_format,
        "scope": "chat",
        "source_user_id": f"external/{source_format}",
        "exported_at": EPOCH.isoformat(),
        "conversations": [],
        "memories": [],
        "contexts": [],
        "profile": {},
        "media": [],
        "warnings": [],
    }


def _append(payload, character_id, conversation_id, message_id, role, content, time):
    warnings = payload["warnings"]
    if role not in {"user", "assistant", "agent"}:
        _warn(warnings, "已跳过系统、工具或不支持角色的消息。")
        return
    text = _text(content, warnings)
    if not text.strip():
        return
    source_format = payload["source_format"]
    identity = json_bytes([source_format, character_id, conversation_id, message_id]).decode("utf-8")
    rows = payload["conversations"]
    require(len(rows) < MAX_RECORDS, "External document contains too many messages")
    rows.append(
        {
            "uuid": str(uuid5(NAMESPACE_URL, f"agentluo/import/{identity}")),
            "user_id": payload["source_user_id"],
            "character_id": character_id,
            "timestamp": _timestamp(time, len(rows), warnings),
            "source": "user" if role == "user" else "agent",
            "type": "text",
            "content": text,
            "meta_data": {
                "import_source": source_format,
                "external_conversation_id": conversation_id,
                "external_message_id": message_id,
            },
        }
    )


def _chatgpt_path(conversation):
    mapping = conversation.get("mapping")
    require(isinstance(mapping, dict), "Invalid ChatGPT mapping")
    require(len(mapping) <= MAX_RECORDS, "ChatGPT conversation contains too many nodes")
    node_id = conversation.get("current_node")
    if not mapping and node_id is None:
        return []
    require(isinstance(node_id, str) and node_id in mapping, "ChatGPT current_node is missing or invalid")
    seen = set()
    path = []
    while node_id is not None:
        require(isinstance(node_id, str) and node_id in mapping, "ChatGPT branch contains a missing parent")
        require(node_id not in seen, "ChatGPT branch contains a parent cycle")
        seen.add(node_id)
        node = mapping[node_id]
        require(isinstance(node, dict), "Invalid ChatGPT node")
        path.append((node_id, node))
        node_id = node.get("parent")
    return list(reversed(path))


def _chatgpt_content(message, warnings):
    content = message.get("content")
    if not isinstance(content, dict):
        return _text(content, warnings)
    parts = content.get("parts", [])
    if content.get("content_type") not in {"text", "multimodal_text"}:
        _warn(warnings, "已跳过不支持的 ChatGPT 媒体或结构化内容。")
        return ""
    return _text(parts, warnings)


def _chatgpt(document, payload, character_id):
    conversations = document if isinstance(document, list) else [document]
    require(len(conversations) <= MAX_RECORDS, "Too many ChatGPT conversations")
    for conversation in conversations:
        require(isinstance(conversation, dict), "Invalid ChatGPT conversation")
        conversation_id = _identifier(
            conversation.get("id", conversation.get("conversation_id")), _digest(conversation)
        )
        for node_id, node in _chatgpt_path(conversation):
            message = node.get("message")
            if message is None:
                continue
            require(isinstance(message, dict), "Invalid ChatGPT message")
            _attachments(message, payload["warnings"])
            author = message.get("author")
            require(isinstance(author, dict), "Invalid ChatGPT message author")
            _append(
                payload,
                character_id,
                conversation_id,
                _identifier(message.get("id"), node_id),
                author.get("role"),
                _chatgpt_content(message, payload["warnings"]),
                message.get("create_time"),
            )


def _sillytavern(document, payload, character_id):
    require(isinstance(document, list) and bool(document), "Expected SillyTavern JSONL messages")
    conversation_id = _digest(document)
    for index, row in enumerate(document):
        require(isinstance(row, dict), "Invalid SillyTavern message")
        if index == 0 and "mes" not in row:
            continue
        require(type(row.get("is_user")) is bool and "mes" in row, "Invalid SillyTavern message fields")
        _attachments(row, payload["warnings"])
        if row.get("is_system"):
            _warn(payload["warnings"], "已跳过 SillyTavern 系统消息。")
            continue
        _append(
            payload,
            character_id,
            conversation_id,
            _identifier(row.get("id"), str(index)),
            "user" if row["is_user"] else "assistant",
            row["mes"],
            row.get("send_date"),
        )


def _generic(document, payload, character_id):
    rows = document.get("messages") if isinstance(document, dict) else document
    require(isinstance(rows, list) and len(rows) <= MAX_RECORDS, "Expected a role/content array or messages array")
    raw_id = document.get("id") if isinstance(document, dict) else None
    conversation_id = _identifier(raw_id, _digest(document))
    for index, row in enumerate(rows):
        require(isinstance(row, dict) and "role" in row and "content" in row, "Invalid role/content message")
        _attachments(row, payload["warnings"])
        _append(
            payload,
            character_id,
            conversation_id,
            _identifier(row.get("id"), str(index)),
            row["role"],
            row["content"],
            row.get("timestamp", row.get("created_at", row.get("create_time"))),
        )


def decode_external(data, source_format, character_id):
    document = _load_document(data)
    source_format = _detect(document) if source_format == "auto" else source_format
    readers = {"chatgpt": _chatgpt, "sillytavern": _sillytavern, "generic": _generic}
    require(source_format in readers, "Unsupported external source format")
    payload = _base(source_format, character_id)
    readers[source_format](document, payload, character_id)
    return payload, {}
