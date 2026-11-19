"""Transfer acceptance at the pure byte boundary; all content is synthetic."""

import copy
import hashlib
import io
import json
import stat
import zipfile
from datetime import datetime, timezone

import pytest

from src.infrastructure import data_transfer as transfer
from src.infrastructure.data_transfer import _archive, _external


def _json(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _conversation():
    return {
        "uuid": "conversation-1",
        "user_id": "source-owner",
        "character_id": "luotianyi",
        "timestamp": "2020-01-02T03:04:05",
        "source": "user",
        "type": "text",
        "content": "你好，世界 🌟\n第二行",
        "meta_data": {"call_duration_ms": 1234},
    }


def _memory():
    return {
        "id": "memory-1",
        "owner_character_id": "luotianyi",
        "subject_user_id": "source-owner",
        "memory_type": "user_fact",
        "visibility": "private",
        "source": "explicit_user",
        "content": "喜欢音乐♪",
        "summary": None,
        "importance": 0.5,
        "confidence": 1.0,
        "emotional_valence": None,
        "happened_at": None,
        "created_at": "2020-01-02T03:04:05",
        "last_accessed_at": None,
        "meta_data": {},
        "chunks": [{"chunk_text": "喜欢音乐♪", "chunk_type": "content"}],
    }


@pytest.fixture
def payload():
    """Native shape follows the approved SQL-column and portable chunk contract."""
    return {
        "format": "agentluo-data",
        "version": 1,
        "scope": "all",
        "source_user_id": "source-owner",
        "exported_at": "2026-11-19T08:00:00+00:00",
        "conversations": [_conversation()],
        "memories": [_memory()],
        "contexts": [
            {
                "character_id": "luotianyi",
                "context_summary": "聊过音乐",
                "context_memory_count": 1,
                "maintenance_entry_id": "conversation-1",
                "updated_at": "2020-01-02T03:04:05",
            }
        ],
        "profile": {"description": "测试画像", "preferences": {"language": "中文"}},
        "media": [],
        "warnings": [],
        "memory_edges": [],
    }


def _with_media(payload):
    data = b"synthetic-media-not-real-user-data"
    path = "media/media-1/content.bin"
    payload["media"] = [
        {
            "id": "media-1",
            "kind": "audio",
            "mime_type": "audio/wav",
            "duration_ms": 1234,
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    ]
    return {path: data}


def _package(payload, files=None, *, manifest_changes=None, extra=None):
    members = {"data.json": _json(payload), **(files or {}), **(extra or {})}
    manifest = {
        "format": "agentluo-data",
        "version": 1,
        "scope": payload.get("scope", "all"),
        "warnings": payload.get("warnings", []),
        "files": {path: hashlib.sha256(data).hexdigest() for path, data in members.items()},
    }
    manifest.update(manifest_changes or {})
    members["manifest.json"] = _json(manifest)
    return _zip(members)


def _zip(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in members.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_native_round_trip_keeps_unicode_metadata_contexts_edges_and_bytes(payload):
    payload["source_format"] = "generic"
    files = _with_media(payload)
    original = copy.deepcopy(payload)
    archive = transfer.encode_archive(payload, files)
    decoded, decoded_files = transfer.decode_import(archive)
    assert decoded == {**original, "source_format": "native"}
    assert decoded_files == files and payload == original
    assert transfer.encode_archive(payload, files) == archive
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert set(package.namelist()) == {"manifest.json", "data.json", *files}
        assert manifest["files"]["data.json"] == hashlib.sha256(package.read("data.json")).hexdigest()


def test_native_metadata_json_and_profile_are_normalized_without_mutating_input(payload):
    payload["conversations"][0]["meta_data"] = '{"nested":{"字幕":"中文"}}'
    payload["memories"][0]["meta_data"] = None
    payload["profile"] = {"description": None, "preferences": '{"回复":"简短"}'}
    result, _ = transfer.decode_import(_package(payload))
    assert result["conversations"][0]["meta_data"] == {"nested": {"字幕": "中文"}}
    assert result["memories"][0]["meta_data"] == {}
    assert result["profile"] == {"description": "", "preferences": {"回复": "简短"}}
    assert isinstance(payload["conversations"][0]["meta_data"], str)


@pytest.mark.parametrize("scope", ["chat", "memory"])
def test_native_scope_filters_only_after_whole_archive_validation(payload, scope):
    files = _with_media(payload)
    decoded, result_files = transfer.decode_import(_package(payload, files), scope=scope)
    assert decoded["scope"] == scope
    if scope == "chat":
        assert decoded["contexts"] and decoded["conversations"] and result_files == files
        assert decoded["memories"] == [] and decoded["profile"] == {} and "memory_edges" not in decoded
    else:
        assert decoded["memories"] and decoded["profile"]
        assert decoded["conversations"] == decoded["contexts"] == decoded["media"] == []
        assert result_files == {}


def test_chat_native_allows_empty_profile_and_rejects_incompatible_scope(payload):
    payload.update(scope="chat", memories=[], profile={})
    archive = transfer.encode_archive(payload, {})
    assert transfer.decode_import(archive)[0]["scope"] == "chat"
    with pytest.raises(transfer.TransferFormatError, match="requested scope"):
        transfer.decode_import(archive, scope="memory")


def test_native_missing_media_is_explicit_and_never_gets_fabricated_bytes(payload):
    _with_media(payload)
    payload["media"][0].update(path=None, sha256=None)
    payload["warnings"] = ["媒体 media-1 的原始文件缺失。"]
    decoded, files = transfer.decode_import(transfer.encode_archive(payload, {}))
    assert files == {} and decoded["media"][0]["path"] is None
    payload["warnings"] = []
    with pytest.raises(transfer.TransferFormatError, match="reported"):
        transfer.encode_archive(payload, {})


@pytest.mark.parametrize("version", [0, 2, True, "1"])
def test_rejects_unknown_and_coerced_native_version(payload, version):
    payload["version"] = version
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload))


@pytest.mark.parametrize("scope", ["unknown", "", None, [], 1])
def test_rejects_invalid_native_scope(payload, scope):
    payload["scope"] = scope
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload))


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("conversations", "uuid", None),
        ("conversations", "timestamp", "not-a-date"),
        ("conversations", "content", {"unexpected": "object"}),
        ("conversations", "source", "system"),
        ("conversations", "user_id", "other-owner"),
        ("conversations", "meta_data", "[]"),
        ("memories", "subject_user_id", None),
        ("memories", "subject_user_id", "other-owner"),
        ("memories", "importance", True),
        ("memories", "chunks", [{"chunk_text": "a"}]),
        ("contexts", "context_memory_count", -1),
        ("contexts", "updated_at", "bad"),
    ],
)
def test_rejects_malformed_native_business_fields(payload, collection, field, value):
    payload[collection][0][field] = value
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload))


@pytest.mark.parametrize(
    "field",
    [
        "format",
        "version",
        "scope",
        "source_user_id",
        "exported_at",
        "conversations",
        "contexts",
        "memories",
        "profile",
        "media",
        "warnings",
    ],
)
def test_native_requires_explicit_complete_shape(payload, field):
    del payload[field]
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload))


@pytest.mark.parametrize("preferences", [None, [], 123, "null", "[]"])
def test_native_rejects_non_object_preferences(payload, preferences):
    payload["profile"]["preferences"] = preferences
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload))


def test_duplicate_record_id_and_embedding_projection_are_rejected(payload):
    payload["conversations"].append(copy.deepcopy(payload["conversations"][0]))
    with pytest.raises(transfer.TransferFormatError, match="Duplicate"):
        transfer.decode_import(_package(payload))
    payload["conversations"].pop()
    payload["memories"][0]["chunks"][0]["embedding_id"] = "provider-specific"
    with pytest.raises(transfer.TransferFormatError, match="Embedding"):
        transfer.decode_import(_package(payload))


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "C:/escape", "media\\escape", "media/../escape", "./data.json", "media//x"]
)
def test_archive_rejects_unsafe_paths_before_using_payload(payload, path):
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload, extra={path: b"unsafe"}))


def test_archive_rejects_duplicate_and_case_colliding_paths(payload):
    output = io.BytesIO(_package(payload))
    with zipfile.ZipFile(output, "a") as package:
        with pytest.warns(UserWarning, match="Duplicate"):
            package.writestr("data.json", _json(payload))
    with pytest.raises(transfer.TransferFormatError, match="duplicate"):
        transfer.decode_import(output.getvalue())
    with pytest.raises(transfer.TransferFormatError, match="duplicate"):
        transfer.decode_import(_package(payload, extra={"DATA.JSON": b"case collision"}))


def test_archive_rejects_symlink_and_special_entries(payload):
    for mode in (stat.S_IFLNK, stat.S_IFIFO):
        output = io.BytesIO(_package(payload))
        with zipfile.ZipFile(output, "a") as archive:
            entry = zipfile.ZipInfo("media/link/content.bin")
            entry.create_system = 3
            entry.external_attr = (mode | 0o777) << 16
            archive.writestr(entry, "../../outside")
        with pytest.raises(transfer.TransferFormatError, match="special files"):
            transfer.decode_import(output.getvalue())


def test_archive_rejects_manifest_payload_and_media_checksum_errors(payload):
    files = _with_media(payload)
    checksums = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    checksums["data.json"] = "0" * 64
    with pytest.raises(transfer.TransferFormatError, match="checksum"):
        transfer.decode_import(_package(payload, files, manifest_changes={"files": checksums}))
    payload["media"][0]["sha256"] = "0" * 64
    with pytest.raises(transfer.TransferFormatError, match="Media checksum"):
        transfer.decode_import(_package(payload, files))


@pytest.mark.parametrize(
    "manifest_changes", [{"version": 2}, {"scope": "chat"}, {"warnings": ["inconsistent"]}, {"files": {}}]
)
def test_archive_rejects_inconsistent_manifest(payload, manifest_changes):
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload, manifest_changes=manifest_changes))


def test_archive_rejects_missing_unreferenced_and_misnamed_media(payload):
    files = _with_media(payload)
    with pytest.raises(transfer.TransferFormatError, match="missing files"):
        transfer.decode_import(_package(payload))
    with pytest.raises(transfer.TransferFormatError, match="unreferenced"):
        transfer.decode_import(_package(payload, files, extra={"secret.txt": b"not portable"}))
    payload["media"][0]["path"] = "media/other-id/content.bin"
    with pytest.raises(transfer.TransferFormatError, match="media path"):
        transfer.decode_import(_package(payload, files))


@pytest.mark.parametrize(
    ("module", "limit", "value"),
    [
        (transfer, "MAX_UPLOAD_BYTES", 1),
        (_archive, "MAX_ENTRY_BYTES", 32),
        (_archive, "MAX_EXPANDED_BYTES", 64),
        (_archive, "MAX_ARCHIVE_ENTRIES", 1),
    ],
)
def test_input_limits_reject_before_import(payload, monkeypatch, module, limit, value):
    data = _package(payload)
    monkeypatch.setattr(module, limit, value)
    with pytest.raises(transfer.TransferFormatError, match="limit|many|oversized"):
        transfer.decode_import(data)


@pytest.mark.parametrize(
    "data", [b"", b"PK\x03\x04broken", b"not json", b"\xff", b'{"messages":[],"messages":[]}', b"NaN", b"1e9999"]
)
def test_invalid_input_always_has_public_format_error(data):
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(data)


def test_native_json_is_not_mistaken_for_restoration_and_readable_is_not_importable(payload):
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_json(payload))
    for format in ("markdown", "txt"):
        with pytest.raises(transfer.TransferFormatError):
            transfer.decode_import(transfer.render_readable(payload, format))


def _chatgpt_message(id, role, text, time=None):
    return {
        "id": id,
        "author": {"role": role},
        "content": {"content_type": "text", "parts": [text]},
        "create_time": time,
    }


def _chatgpt():
    return [
        {
            "id": "chat-1",
            "current_node": "selected",
            "mapping": {
                "root": {"parent": None, "message": _chatgpt_message("system", "system", "系统提示")},
                "user": {"parent": "root", "message": _chatgpt_message("user-1", "user", "用户中文🌟", 1234567890)},
                "other": {"parent": "user", "message": _chatgpt_message("other-1", "assistant", "不能导入的旁枝")},
                "selected": {"parent": "user", "message": _chatgpt_message("answer-1", "assistant", "选定的回答♪")},
            },
        }
    ]


def test_chatgpt_uses_current_node_ancestor_path_and_keeps_source_identity():
    document = _chatgpt()
    result, files = transfer.decode_import(_json(document), character_id="other-character")
    assert files == {} and result["source_format"] == "chatgpt" and result["scope"] == "chat"
    assert result["source_user_id"] == "external/chatgpt"
    assert [row["content"] for row in result["conversations"]] == ["用户中文🌟", "选定的回答♪"]
    assert [row["source"] for row in result["conversations"]] == ["user", "agent"]
    assert all(row["character_id"] == "other-character" for row in result["conversations"])
    assert result["conversations"][0]["timestamp"] == datetime.fromtimestamp(1234567890, timezone.utc).isoformat()
    assert result["warnings"]
    assert result == transfer.decode_import(_json(document), "chatgpt", "other-character")[0]


@pytest.mark.parametrize("change", ["missing-current", "unknown-current", "missing-parent", "cycle"])
def test_chatgpt_rejects_ambiguous_or_broken_current_branch(change):
    document = _chatgpt()
    conversation = document[0]
    if change == "missing-current":
        del conversation["current_node"]
    elif change == "unknown-current":
        conversation["current_node"] = "absent"
    elif change == "missing-parent":
        conversation["mapping"]["user"]["parent"] = "absent"
    else:
        conversation["mapping"]["user"]["parent"] = "selected"
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_json(document))


def test_chatgpt_skips_unsupported_media_but_keeps_adjacent_text():
    document = _chatgpt()
    document[0]["mapping"]["selected"]["message"]["content"] = {
        "content_type": "multimodal_text",
        "parts": ["回答", {"asset_pointer": "https://not-fetched.invalid/image"}],
    }
    result, files = transfer.decode_import(_json(document))
    assert result["conversations"][-1]["content"] == "回答" and files == {}
    assert any("媒体" in warning for warning in result["warnings"])


def test_sillytavern_header_is_skipped_roles_unicode_and_dates_survive():
    rows = [
        {"user_name": "测试用户", "character_name": "天依", "chat_metadata": {}},
        {"name": "用户", "is_user": True, "mes": "你好♪", "send_date": "2023-7-30 @18h 36m 51s 209ms"},
        {"name": "天依", "is_user": False, "mes": "你好，星光", "send_date": "2023-07-30T18:37:00Z"},
        {"is_user": False, "is_system": True, "mes": "系统事件"},
    ]
    data = b"\xef\xbb\xbf" + b"\n".join(_json(row) for row in rows)
    result, _ = transfer.decode_import(data)
    assert result["source_format"] == "sillytavern"
    assert [row["content"] for row in result["conversations"]] == ["你好♪", "你好，星光"]
    assert [row["source"] for row in result["conversations"]] == ["user", "agent"]
    assert result["conversations"][0]["timestamp"] == "2023-07-30T18:36:51.209000+00:00"
    assert result == transfer.decode_import(data, "sillytavern")[0]


@pytest.mark.parametrize("wrapped", [False, True])
def test_generic_supports_arrays_and_messages_objects_with_deterministic_missing_times(wrapped, monkeypatch):
    rows = [{"role": "user", "content": "早上好☀"}, {"role": "assistant", "content": "你好！"}]
    document = {"messages": rows} if wrapped else rows
    data = _json(document)
    first, _ = transfer.decode_import(data)

    class NoCurrentClock(datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("Import must not read the current clock")

        @classmethod
        def utcnow(cls):
            raise AssertionError("Import must not read the current clock")

    monkeypatch.setattr(_external, "datetime", NoCurrentClock)
    second, _ = transfer.decode_import(data, "generic")
    assert first == second
    assert first["source_format"] == "generic" and first["source_user_id"] == "external/generic"
    assert [row["timestamp"] for row in first["conversations"]] == [
        "1970-01-01T00:00:00+00:00",
        "1970-01-01T00:00:01+00:00",
    ]
    assert len({row["uuid"] for row in first["conversations"]}) == 2


def test_external_stable_ids_include_character_and_preserve_explicit_message_identity():
    document = {"id": "conversation", "messages": [{"id": "message", "role": "user", "content": "原文"}]}
    first, _ = transfer.decode_import(_json(document))
    document["messages"][0]["content"] = "同来源身份但冲突的新内容"
    second, _ = transfer.decode_import(_json(document))
    another, _ = transfer.decode_import(_json(document), character_id="another-character")
    assert first["conversations"][0]["uuid"] == second["conversations"][0]["uuid"]
    assert another["conversations"][0]["uuid"] != first["conversations"][0]["uuid"]
    assert transfer.decode_import(transfer.encode_archive(first, {}))[0]["conversations"] == first["conversations"]
    with pytest.raises(transfer.TransferFormatError, match="requested scope"):
        transfer.decode_import(_json(document), scope="memory")


def test_generic_warns_for_system_and_media_and_preserves_only_text():
    data = _json(
        [
            {"role": "system", "content": "不能成为用户消息"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "文字"}, {"type": "image_url", "image_url": "https://invalid"}],
            },
        ]
    )
    result, files = transfer.decode_import(data)
    assert [row["content"] for row in result["conversations"]] == ["文字"]
    assert len(result["warnings"]) >= 2 and files == {}


@pytest.mark.parametrize("format", ["markdown", "txt"])
def test_readable_copies_include_unicode_call_facts_memory_profile_and_missing_media(payload, format):
    _with_media(payload)
    payload["media"][0].update(path=None, sha256=None)
    payload["warnings"] = ["原始媒体缺失"]
    result = transfer.render_readable(payload, format).decode("utf-8")
    for expected in (
        "你好，世界 🌟",
        "2020-01-02T03:04:05",
        "call_duration_ms",
        "1234",
        "喜欢音乐♪",
        "测试画像",
        "中文",
        "原始媒体缺失",
        "不可回放",
        "聊过音乐",
    ):
        assert expected in result
    assert result.startswith("# " if format == "markdown" else "AgentLuo")


def test_public_format_selectors_fail_explicitly(payload):
    with pytest.raises(transfer.TransferFormatError):
        transfer.render_readable(payload, "html")
    for kwargs in (
        {"source_format": "unknown"},
        {"scope": "unknown"},
        {"character_id": ""},
        {"source_format": "native"},
    ):
        with pytest.raises(transfer.TransferFormatError):
            transfer.decode_import(b"[]", **kwargs)


@pytest.mark.parametrize(
    "document",
    [
        [{"role": "user", "content": "文字", "attachments": [{"url": "https://not-fetched.invalid/file"}]}],
        [
            {"user_name": "u", "character_name": "c"},
            {"is_user": True, "mes": "文字", "extra": {"image": "https://not-fetched.invalid/image"}},
        ],
    ],
)
def test_external_attachment_metadata_is_reported_without_fabricating_media(document):
    result, files = transfer.decode_import(_json(document))
    assert [row["content"] for row in result["conversations"]] == ["文字"]
    assert files == {} and result["media"] == []
    assert any("媒体附件" in warning for warning in result["warnings"])


def test_native_rejects_non_finite_metadata_numbers_and_surrogate_text(payload):
    payload["conversations"][0]["meta_data"] = '{"number":1e9999}'
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_package(payload))
    payload["conversations"][0]["meta_data"] = {}
    raw = _json(payload).replace("你好，世界".encode("utf-8"), b"\\ud800")
    manifest = {
        "format": "agentluo-data",
        "version": 1,
        "scope": "all",
        "warnings": [],
        "files": {"data.json": hashlib.sha256(raw).hexdigest()},
    }
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(_zip({"data.json": raw, "manifest.json": _json(manifest)}))


def test_native_corrupt_zip_crc_is_a_public_format_error(payload):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("data.json", _json(payload))
    corrupted = output.getvalue().replace(b"source-owner", b"source-xxxxx", 1)
    with pytest.raises(transfer.TransferFormatError):
        transfer.decode_import(corrupted)
