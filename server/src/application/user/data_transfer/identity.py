"""归档业务身份与所有权校验，不相信上传的本机路径或目标用户。"""

from __future__ import annotations

import copy
import math
import re
from datetime import datetime
from uuid import UUID

from src.agent.context import AudioContent, AudioUnderstandingStatus, ImageContent, TextContent, UserPreferences
from src.domain.call import CallContent, CallEndReason, CallOutcome
from src.domain.memory_record import MemoryType, MemoryVisibility
from src.infrastructure.persistence.user_data_transfer import as_json, parse_time, stable_id


def _origin(metadata, fallback_user, fallback_id, key="_transfer_origin"):
    value = metadata.get(key, {})
    if not isinstance(value, dict):
        raise ValueError("INVALID_TRANSFER_ORIGIN")
    owner, identity = value.get("user_id", fallback_user), value.get("id", fallback_id)
    if not isinstance(owner, str) or not owner or not isinstance(identity, str) or not identity:
        raise ValueError("INVALID_TRANSFER_ORIGIN")
    return owner, identity


def _map_metadata(value, maps):
    """仅重写结构化标识，不替换聊天或画像中的普通字符串。"""
    if isinstance(value, list):
        return [_map_metadata(item, maps) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"image_server_path", "image_client_path", "audio_local_uri", "server_path", "local_path"}:
            continue
        if key in {"user_id", "subject_user_id", "owner_user_id"}:
            result[key] = maps["user"]
        elif key in {"entry_id", "conversation_id", "source_entry_id", "reply_to"} and isinstance(item, str):
            result[key] = maps["conversation"].get(item, item)
        elif key in {"media_id", "memory_record_id", "call_id"} and isinstance(item, str):
            kind = {"media_id": "media", "memory_record_id": "memory", "call_id": "call"}[key]
            result[key] = maps[kind].get(item, item)
        elif key in {"_transfer_origin", "_transfer_media_origin", "_transfer_call_origin"}:
            result[key] = item
        else:
            result[key] = _map_metadata(item, maps)
    return result


def _validate_record(row, source_user, characters):
    if row.get("user_id") != source_user:
        raise ValueError("CONVERSATION_OWNER_MISMATCH")
    if row.get("character_id") not in characters:
        raise ValueError("CHARACTER_NOT_ENABLED")
    if row.get("source") not in {"user", "agent"} or row.get("type") not in {"text", "image", "audio", "call", "sing"}:
        raise ValueError("INVALID_CONVERSATION_KIND")
    if not isinstance(row.get("content"), str) or not isinstance(row.get("uuid"), str) or not row["uuid"]:
        raise ValueError("INVALID_CONVERSATION")
    parse_time(row["timestamp"])
    if not isinstance(row.get("meta_data"), dict):
        row["meta_data"] = as_json(row.get("meta_data"))
    _validate_content(row)


def _validate_content(row):
    data, text, kind = row["meta_data"], row["content"], row["type"]
    if kind == "text":
        TextContent(text, tuple(data.get("terms") or ()))
    elif kind == "image":
        ImageContent(
            text, mime_type=data.get("mime_type"), terms=tuple(data.get("terms") or ()), media_id=data.get("media_id")
        )
    elif kind == "audio":
        content = AudioContent(
            media_id=data["media_id"],
            mime_type=data["mime_type"],
            duration_ms=data["duration_ms"],
            understanding_status=AudioUnderstandingStatus(data["understanding_status"]),
            transcript=data.get("transcript"),
            emotion=data.get("emotion"),
            sound_description=data.get("sound_description"),
        )
        if content.text != text:
            raise ValueError("AUDIO_CONTENT_METADATA_MISMATCH")
    elif kind == "call":
        content = CallContent(
            call_id=UUID(data["call_id"]),
            outcome=CallOutcome(data["outcome"]),
            active_duration_ms=data["active_duration_ms"],
            summary=data.get("summary"),
            end_reason=CallEndReason(data["end_reason"]),
        )
        if content.text != text:
            raise ValueError("CALL_CONTENT_METADATA_MISMATCH")
    elif kind == "sing" and not data.get("song"):
        if re.match(r"^(?:（唱歌）：《([^》]+)》|（唱了《([^》]+)》）)", text) is None:
            raise ValueError("INVALID_SONG_CONTENT")


def _validate_memory(row, source_user, characters):
    if row.get("subject_user_id") != source_user or row.get("owner_character_id") not in characters:
        raise ValueError("MEMORY_OWNER_MISMATCH")
    MemoryType(row["memory_type"])
    if MemoryVisibility(row["visibility"]) is not MemoryVisibility.PRIVATE:
        raise ValueError("ONLY_PRIVATE_USER_MEMORIES_CAN_BE_IMPORTED")
    for key in ("importance", "confidence", "emotional_valence"):
        value = row.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("INVALID_MEMORY_SCORE")
    if not isinstance(row.get("content"), str) or not row["content"].strip():
        raise ValueError("INVALID_MEMORY_CONTENT")
    if not isinstance(row.get("source"), str) or not row["source"]:
        raise ValueError("INVALID_MEMORY_SOURCE")
    for key in ("created_at", "happened_at", "last_accessed_at"):
        parse_time(row.get(key))
    row["meta_data"] = as_json(row.get("meta_data"))


def bind_import(payload, files, user_id, characters):
    """返回独立副本；所有归属及媒体引用绑定到已认证用户。"""
    payload = copy.deepcopy(payload)
    preferences = payload.get("profile", {}).get("preferences", {})
    UserPreferences(
        relationship=preferences.get("relationship", ""),
        speaking_style=preferences.get("speaking_style", ""),
        personality_traits=tuple(preferences.get("personality_traits") or ()),
        custom_context=preferences.get("custom_context", ""),
        personality_text=preferences.get("#sym:personality_text", ""),
    )
    source_user = payload["source_user_id"]
    maps = {"user": user_id, "conversation": {}, "memory": {}, "media": {}, "call": {}}
    for row in payload["conversations"]:
        _validate_record(row, source_user, characters)
        owner, identity = _origin(row["meta_data"], source_user, row["uuid"])
        maps["conversation"][row["uuid"]] = stable_id("conversation", user_id, owner, identity)
    for row in payload["memories"]:
        _validate_memory(row, source_user, characters)
        owner, identity = _origin(row["meta_data"], source_user, row["id"])
        maps["memory"][row["id"]] = stable_id("memory", user_id, owner, identity)
    _bind_media(payload, files, source_user, user_id, maps)
    _bind_rows(payload, source_user, user_id, maps)
    _bind_contexts(payload, maps, characters)
    payload["source_user_id"] = user_id
    return payload


def _bind_media(payload, files, source_user, user_id, maps):
    origins = {}
    for row in payload["conversations"]:
        metadata = row["meta_data"]
        media_id = metadata.get("media_id")
        if media_id:
            origins[media_id] = _origin(metadata, source_user, media_id, "_transfer_media_origin")
        if row["type"] == "call":
            call_id = metadata.get("call_id")
            UUID(call_id)
            owner, identity = _origin(metadata, source_user, call_id, "_transfer_call_origin")
            UUID(identity)
            maps["call"][call_id] = stable_id("call", user_id, owner, identity)
    for media in payload["media"]:
        original = media["id"]
        UUID(original)
        owner, identity = origins.get(original, (source_user, original))
        maps["media"][original] = stable_id("media", user_id, owner, identity)
        media["id"] = maps["media"][original]
        path = media.get("path")
        if path is not None:
            media["data"] = files[path]
    for media_id in origins:
        if media_id not in maps["media"]:
            # 缺失媒体仍重绑引用，不允许它指向当前部署其他人的资源。
            owner, identity = origins[media_id]
            maps["media"][media_id] = stable_id("media", user_id, owner, identity)


def _bind_rows(payload, source_user, user_id, maps):
    external = payload.get("source_format", "native") != "native"
    for row in payload["conversations"]:
        metadata = row["meta_data"]
        owner, identity = _origin(metadata, source_user, row["uuid"])
        metadata["_transfer_origin"] = {"user_id": owner, "id": identity}
        if metadata.get("media_id"):
            media_owner, media_id = _origin(metadata, source_user, metadata["media_id"], "_transfer_media_origin")
            metadata["_transfer_media_origin"] = {"user_id": media_owner, "id": media_id}
        if row["type"] == "call":
            call_owner, call_id = _origin(metadata, source_user, metadata["call_id"], "_transfer_call_origin")
            metadata["_transfer_call_origin"] = {"user_id": call_owner, "id": call_id}
        row["uuid"], row["user_id"] = maps["conversation"][row["uuid"]], user_id
        row["meta_data"] = _map_metadata(metadata, maps)
        if external:
            row["meta_data"]["_transfer_external"] = True
    for row in payload["memories"]:
        owner, identity = _origin(row["meta_data"], source_user, row["id"])
        row["meta_data"]["_transfer_origin"] = {"user_id": owner, "id": identity}
        row["id"], row["subject_user_id"] = maps["memory"][row["id"]], user_id
        row["meta_data"] = _map_metadata(row["meta_data"], maps)
    for edge in payload.get("memory_edges", []):
        if edge["from_memory_id"] not in maps["memory"] or edge["to_memory_id"] not in maps["memory"]:
            raise ValueError("MEMORY_EDGE_OUTSIDE_ARCHIVE")
        edge["from_memory_id"] = maps["memory"][edge["from_memory_id"]]
        edge["to_memory_id"] = maps["memory"][edge["to_memory_id"]]
        metadata = as_json(edge.get("meta_data"))
        owner, identity = _origin(metadata, source_user, edge["id"])
        metadata["_transfer_origin"] = {"user_id": owner, "id": identity}
        edge["id"] = stable_id("edge", user_id, owner, identity)
        edge["meta_data"] = _map_metadata(metadata, maps)


def _bind_contexts(payload, maps, characters):
    for context in payload.get("contexts", []):
        if context["character_id"] not in characters:
            raise ValueError("CHARACTER_NOT_ENABLED")
        progress = context.get("maintenance_entry_id")
        if progress is not None and progress not in maps["conversation"]:
            raise ValueError("MAINTENANCE_PROGRESS_OUTSIDE_ARCHIVE")
        context["maintenance_entry_id"] = maps["conversation"].get(progress)
        if type(context.get("context_memory_count")) is not int or context["context_memory_count"] < 0:
            raise ValueError("INVALID_CONTEXT_COUNT")
        if not isinstance(context.get("context_summary", ""), str):
            raise ValueError("INVALID_CONTEXT_SUMMARY")
        if context.get("updated_at"):
            datetime.fromisoformat(context["updated_at"])
