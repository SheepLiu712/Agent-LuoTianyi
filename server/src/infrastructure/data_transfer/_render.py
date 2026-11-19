"""Human-readable copies, deliberately not a native restoration format."""

import json

from ._schema import json_bytes, read_json, require, validate_payload


def _heading(text, level, markdown):
    return f"{'#' * level} {text}" if markdown else text


def _metadata(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _conversations(payload, markdown):
    lines = [_heading("聊天记录", 2, markdown)]
    for row in payload["conversations"]:
        label = f"{row['timestamp']} · {row['character_id']} · {row['source']} · {row['type']}"
        lines.extend([_heading(label, 3, markdown), "", row["content"], ""])
        if row["meta_data"]:
            lines.extend(["元数据：", _metadata(row["meta_data"]), ""])
    for context in payload["contexts"]:
        lines.extend([f"上下文概要（{context['character_id']}）：", context["context_summary"], ""])
    return lines


def _memories(payload, markdown):
    lines = [_heading("长期记忆", 2, markdown)]
    for row in payload["memories"]:
        label = f"{row['owner_character_id']} · {row['memory_type']} · {row['created_at']}"
        lines.extend([_heading(label, 3, markdown), "", row["content"], ""])
        if row["summary"]:
            lines.extend([f"摘要：{row['summary']}", ""])
    profile = payload["profile"]
    if profile:
        lines.extend(
            [_heading("画像与偏好", 2, markdown), "", profile["description"], _metadata(profile["preferences"]), ""]
        )
    return lines


def render_readable(payload, format):
    require(format in {"markdown", "txt"}, "Readable format must be markdown or txt")
    payload = validate_payload(read_json(json_bytes(payload)))
    markdown = format == "markdown"
    lines = [_heading("AgentLuo 聊天与记忆阅读副本", 1, markdown), "", f"范围：{payload['scope']}", ""]
    lines.extend(["此文件仅供阅读，恢复请使用原生 ZIP 或目录包。", ""])
    for warning in payload["warnings"]:
        lines.extend([f"警告：{warning}", ""])
    if payload["scope"] in {"all", "chat"}:
        lines.extend(_conversations(payload, markdown))
    if payload["scope"] in {"all", "memory"}:
        lines.extend(_memories(payload, markdown))
    if payload["media"]:
        lines.extend([_heading("媒体", 2, markdown), ""])
        for row in payload["media"]:
            state = row["path"] if row["path"] is not None else "原始文件缺失，不可回放"
            lines.append(f"{row['id']} · {row['kind']} · {row['mime_type']} · {state}")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")
