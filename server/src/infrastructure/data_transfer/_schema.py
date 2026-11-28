"""JSON-only transfer contracts, independent of persistence and runtime state."""

import json
import math
import re
from datetime import datetime

MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
MAX_RECORDS = 100_000
FORMAT = "agentluo-data"
VERSION = 1
SCOPES = {"chat", "memory", "all"}
MEDIA_PATH = re.compile(r"media/([A-Za-z0-9_-]{1,128})/content\.bin\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class TransferFormatError(ValueError):
    """The supplied document cannot be imported safely and completely."""


def require(condition, message):
    if not condition:
        raise TransferFormatError(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON contains a duplicate object key")
        result[key] = value
    return result


def _finite_float(value):
    result = float(value)
    require(math.isfinite(result), "JSON contains a non-finite number")
    return result


def _invalid_number(value):
    raise TransferFormatError(f"JSON contains a non-finite number: {value}")


def read_json(data):
    try:
        text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
        return json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_invalid_number, parse_float=_finite_float
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise TransferFormatError("Invalid UTF-8 JSON document") from exc


def json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise TransferFormatError("Transfer data must contain finite JSON values") from exc


def string(value, label, *, nullable=False, empty=True):
    if nullable and value is None:
        return
    require(isinstance(value, str) and (empty or bool(value.strip())), f"Invalid {label}")


def timestamp(value, label, *, nullable=False):
    if nullable and value is None:
        return
    string(value, label, empty=False)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransferFormatError(f"Invalid {label}") from exc


def number(value, label, *, nullable=False):
    if nullable and value is None:
        return
    require(type(value) in (int, float) and math.isfinite(value), f"Invalid {label}")


def object_value(value, label, *, nullable=False):
    if value is None and nullable:
        return {}
    result = read_json(value) if isinstance(value, str) else value
    require(isinstance(result, dict), f"Invalid {label}: expected a JSON object")
    return result


def fields(row, names, label):
    require(isinstance(row, dict), f"Invalid {label}: expected an object")
    require(set(names).issubset(row), f"Missing required {label} fields")


def _rows(payload, key):
    rows = payload[key]
    require(isinstance(rows, list) and len(rows) <= MAX_RECORDS, f"Invalid {key} collection")
    require(all(isinstance(row, dict) for row in rows), f"Invalid {key} record")
    return rows


def _unique(rows, key, label):
    values = [row[key] for row in rows]
    require(len(set(values)) == len(values), f"Duplicate {label} identity")


def _conversation(row, owner):
    fields(
        row, ("uuid", "user_id", "character_id", "timestamp", "source", "type", "content", "meta_data"), "conversation"
    )
    for key in ("uuid", "user_id", "character_id", "source", "type"):
        string(row[key], f"conversation.{key}", empty=False)
    require(row["user_id"] == owner, "Conversation belongs to another source user")
    require(row["source"] in {"user", "agent"}, "Invalid conversation source")
    string(row["content"], "conversation.content")
    timestamp(row["timestamp"], "conversation.timestamp")
    row["meta_data"] = object_value(row["meta_data"], "conversation.meta_data", nullable=True)


def _memory(row, owner):
    required = (
        "id",
        "owner_character_id",
        "subject_user_id",
        "memory_type",
        "visibility",
        "source",
        "content",
        "summary",
        "importance",
        "confidence",
        "emotional_valence",
        "happened_at",
        "created_at",
        "last_accessed_at",
        "meta_data",
        "chunks",
    )
    fields(row, required, "memory")
    for key in ("id", "owner_character_id", "subject_user_id", "memory_type", "visibility", "source"):
        string(row[key], f"memory.{key}", empty=False)
    require(row["subject_user_id"] == owner, "Memory belongs to another source user")
    string(row["content"], "memory.content")
    string(row["summary"], "memory.summary", nullable=True)
    _memory_values(row)
    row["meta_data"] = object_value(row["meta_data"], "memory.meta_data", nullable=True)
    _chunks(row["chunks"])


def _memory_values(row):
    for key in ("importance", "confidence"):
        number(row[key], f"memory.{key}")
    number(row["emotional_valence"], "memory.emotional_valence", nullable=True)
    timestamp(row["created_at"], "memory.created_at")
    for key in ("happened_at", "last_accessed_at"):
        timestamp(row[key], f"memory.{key}", nullable=True)


def _chunks(chunks):
    require(isinstance(chunks, list) and len(chunks) <= MAX_RECORDS, "Invalid memory chunks")
    for chunk in chunks:
        fields(chunk, ("chunk_text", "chunk_type"), "chunk")
        string(chunk["chunk_text"], "chunk.chunk_text", empty=False)
        string(chunk["chunk_type"], "chunk.chunk_type", empty=False)
        require("embedding_id" not in chunk and "embedding" not in chunk, "Embedding values are not portable")


def _context(row):
    fields(
        row,
        ("character_id", "context_summary", "context_memory_count", "maintenance_entry_id", "updated_at"),
        "context",
    )
    string(row["character_id"], "context.character_id", empty=False)
    string(row["context_summary"], "context.context_summary")
    require(
        type(row["context_memory_count"]) is int and row["context_memory_count"] >= 0, "Invalid context memory count"
    )
    string(row["maintenance_entry_id"], "context.maintenance_entry_id", nullable=True)
    timestamp(row["updated_at"], "context.updated_at")


def _profile(payload):
    profile = payload["profile"]
    require(isinstance(profile, dict), "Invalid profile")
    if not profile and payload["scope"] == "chat":
        return
    fields(profile, ("description", "preferences"), "profile")
    profile["description"] = "" if profile["description"] is None else profile["description"]
    string(profile["description"], "profile.description")
    profile["preferences"] = object_value(profile["preferences"], "profile.preferences")


def _media(row, warnings):
    fields(row, ("id", "kind", "mime_type", "duration_ms", "path", "sha256"), "media")
    string(row["id"], "media.id", empty=False)
    require(row["kind"] in {"image", "audio"}, "Invalid media kind")
    string(row["mime_type"], "media.mime_type", empty=False)
    duration = row["duration_ms"]
    require(duration is None or (type(duration) is int and duration >= 0), "Invalid media duration")
    if row["path"] is None:
        require(row["sha256"] is None and bool(warnings), "Missing media must be reported in warnings")
        return
    string(row["path"], "media.path", empty=False)
    match = MEDIA_PATH.fullmatch(row["path"])
    require(match is not None and match.group(1) == row["id"], "Invalid media path")
    require(isinstance(row["sha256"], str) and SHA256.fullmatch(row["sha256"]) is not None, "Invalid media checksum")


def validate_payload(payload):
    """Validate a detached JSON payload; normalize metadata without losing extension fields."""
    required = (
        "format",
        "version",
        "scope",
        "source_user_id",
        "exported_at",
        "conversations",
        "memories",
        "contexts",
        "profile",
        "media",
        "warnings",
    )
    fields(payload, required, "payload")
    require(payload["format"] == FORMAT, "Unknown native transfer format")
    require(type(payload["version"]) is int and payload["version"] == VERSION, "Unsupported archive version")
    require(isinstance(payload["scope"], str) and payload["scope"] in SCOPES, "Unknown transfer scope")
    string(payload["source_user_id"], "source_user_id", empty=False)
    timestamp(payload["exported_at"], "exported_at")
    warnings = payload["warnings"]
    require(isinstance(warnings, list) and all(isinstance(item, str) for item in warnings), "Invalid warnings")
    _validate_rows(payload)
    _profile(payload)
    return payload


def _validate_rows(payload):
    owner = payload["source_user_id"]
    conversations = _rows(payload, "conversations")
    memories = _rows(payload, "memories")
    contexts = _rows(payload, "contexts")
    media = _rows(payload, "media")
    for row in conversations:
        _conversation(row, owner)
    for row in memories:
        _memory(row, owner)
    for row in contexts:
        _context(row)
    for row in media:
        _media(row, payload["warnings"])
    for rows, key in ((conversations, "uuid"), (memories, "id"), (contexts, "character_id"), (media, "id")):
        _unique(rows, key, key)
    paths = [row["path"] for row in media if row["path"] is not None]
    require(len(paths) == len(set(paths)), "Duplicate media path")


def apply_scope(payload, scope):
    require(scope in SCOPES, "Unknown transfer scope")
    available = payload["scope"]
    require(scope == "all" or available in {scope, "all"}, "Archive does not contain the requested scope")
    effective = available if scope == "all" else scope
    payload["scope"] = effective
    if effective == "chat":
        payload.update(memories=[], profile={})
        payload.pop("memory_edges", None)
    if effective == "memory":
        payload.update(conversations=[], contexts=[], media=[])
    return payload
