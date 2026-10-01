"""永久媒体库的图片/音频持久化、解析和删除契约。"""

import json
import struct
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

import src.domain.agent as d
from src.infrastructure.media import (
    FilesystemMediaResolver,
    MediaResolutionError,
    MediaResolutionErrorCode,
    PermanentMediaStore,
    parse_m4a_audio,
)


def _atom(atom_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", len(payload) + 8, atom_type) + payload


def _descriptor(tag: int, payload: bytes) -> bytes:
    return bytes((tag, len(payload))) + payload


def m4a_bytes(*, duration_ms: int = 1234, codec_config: bytes = b"\x12\x10") -> bytes:
    """构造 Mutagen 可解析的最小 M4A/AAC-LC 容器。"""
    decoder_specific = _descriptor(5, codec_config)
    decoder_config = _descriptor(
        4,
        b"\x40\x15" + b"\0\0\0" + struct.pack(">II", 128_000, 128_000) + decoder_specific,
    )
    es_descriptor = _descriptor(3, struct.pack(">HB", 1, 0) + decoder_config)
    esds = _atom(b"esds", b"\0\0\0\0" + es_descriptor)
    sample_entry = _atom(
        b"mp4a",
        b"\0" * 6 + struct.pack(">H", 1) + b"\0" * 8 + struct.pack(">HHHHI", 2, 16, 0, 0, 44_100 << 16) + esds,
    )
    stsd = _atom(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + sample_entry)
    mdhd = _atom(b"mdhd", b"\0\0\0\0" + struct.pack(">IIIIHH", 0, 0, 1000, duration_ms, 0, 0))
    hdlr = _atom(b"hdlr", b"\0" * 8 + b"soun" + b"\0" * 12)
    moov = _atom(b"moov", _atom(b"trak", _atom(b"mdia", mdhd + hdlr + _atom(b"minf", _atom(b"stbl", stsd)))))
    return _atom(b"ftyp", b"M4A " + struct.pack(">I", 0) + b"isomM4A ") + moov


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1)).save(output, format="PNG")
    return output.getvalue()


def test_parse_m4a_audio_validates_mime_container_codec_and_duration():
    assert parse_m4a_audio(m4a_bytes(duration_ms=2345)).duration_ms == 2345

    with pytest.raises(MediaResolutionError) as wrong_mime:
        parse_m4a_audio(m4a_bytes(), "audio/mpeg")
    assert wrong_mime.value.code is MediaResolutionErrorCode.UNSUPPORTED_TYPE

    damaged_data = _atom(b"ftyp", b"M4A " + struct.pack(">I", 0) + b"isomM4A ") + b"damaged"
    with pytest.raises(MediaResolutionError) as damaged:
        parse_m4a_audio(damaged_data)
    assert damaged.value.code is MediaResolutionErrorCode.UNKNOWN

    with pytest.raises(MediaResolutionError) as wrong_codec:
        parse_m4a_audio(m4a_bytes(codec_config=b"\x0a\x10"))
    assert wrong_codec.value.code is MediaResolutionErrorCode.UNSUPPORTED_TYPE


def test_persist_audio_writes_metadata_and_is_idempotent(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    media_ref = d.MediaRef(media_id=str(uuid4()))
    data = m4a_bytes()

    store.persist_audio(media_ref=media_ref, owner_user_id="owner", data=data, mime_type="audio/mp4", duration_ms=1234)
    store.persist_audio(media_ref=media_ref, owner_user_id="owner", data=data, mime_type="audio/mp4", duration_ms=1234)

    metadata = json.loads((tmp_path / media_ref.media_id / "metadata.json").read_text(encoding="utf-8"))
    assert metadata == {
        "media_kind": "audio",
        "mime_type": "audio/mp4",
        "owner_user_id": "owner",
        "byte_length": len(data),
        "sha256": sha256(data).hexdigest(),
        "duration_ms": 1234,
        "container": "m4a",
        "codec": "aac_lc",
    }


def test_persist_audio_rejects_conflict_and_duration_mismatch(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    media_ref = d.MediaRef(media_id=str(uuid4()))
    store.persist_audio(
        media_ref=media_ref, owner_user_id="owner", data=m4a_bytes(), mime_type="audio/mp4", duration_ms=1234
    )

    with pytest.raises(ValueError, match="content conflict"):
        store.persist_audio(
            media_ref=media_ref,
            owner_user_id="owner",
            data=m4a_bytes(duration_ms=2000),
            mime_type="audio/mp4",
            duration_ms=2000,
        )
    with pytest.raises(MediaResolutionError) as caught:
        store.persist_audio(
            media_ref=d.MediaRef(media_id=str(uuid4())),
            owner_user_id="owner",
            data=m4a_bytes(),
            mime_type="audio/mp4",
            duration_ms=1235,
        )
    assert caught.value.code is MediaResolutionErrorCode.INVALID_DURATION


def test_persist_publish_failure_leaves_no_final_or_staging_directory(tmp_path, monkeypatch):
    store = PermanentMediaStore({"root": str(tmp_path)})
    media_ref = d.MediaRef(media_id=str(uuid4()))

    def fail_rename(source, destination):
        raise OSError("publish failed")

    monkeypatch.setattr("src.infrastructure.media.media_store.os.rename", fail_rename)
    with pytest.raises(OSError, match="publish failed"):
        store.persist_audio(
            media_ref=media_ref,
            owner_user_id="owner",
            data=m4a_bytes(),
            mime_type="audio/mp4",
            duration_ms=1234,
        )

    assert list(tmp_path.iterdir()) == []


def test_persist_image_writes_new_metadata_and_old_metadata_replays(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    media_ref = d.MediaRef(media_id=str(uuid4()))
    data = png_bytes()
    store.persist_image(media_ref=media_ref, owner_user_id="owner", data=data, mime_type="image/png")
    metadata = json.loads((tmp_path / media_ref.media_id / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["media_kind"] == "image"
    assert metadata["byte_length"] == len(data)
    assert metadata["sha256"] == sha256(data).hexdigest()

    old_ref = d.MediaRef(media_id=str(uuid4()))
    old_dir = tmp_path / old_ref.media_id
    old_dir.mkdir()
    (old_dir / "content.bin").write_bytes(data)
    (old_dir / "metadata.json").write_text(
        json.dumps({"mime_type": "image/png", "owner_user_id": "owner"}), encoding="utf-8"
    )
    store.persist_image(media_ref=old_ref, owner_user_id="owner", data=data, mime_type="image/png")
    assert (
        FilesystemMediaResolver({"root": str(tmp_path)})
        .resolve(old_ref, owner_user_id="owner", expected_kind="image")
        .data
        == data
    )


def test_resolver_enforces_owner_and_expected_kind_for_image_and_audio(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    image_ref = d.MediaRef(media_id=str(uuid4()))
    audio_ref = d.MediaRef(media_id=str(uuid4()))
    store.persist_image(media_ref=image_ref, owner_user_id="owner", data=png_bytes(), mime_type="image/png")
    store.persist_audio(
        media_ref=audio_ref, owner_user_id="owner", data=m4a_bytes(), mime_type="audio/mp4", duration_ms=1234
    )
    resolver = FilesystemMediaResolver({"root": str(tmp_path)})

    assert resolver.resolve(image_ref, owner_user_id="owner").mime_type == "image/png"
    assert resolver.resolve(audio_ref, owner_user_id="owner", expected_kind="audio").mime_type == "audio/mp4"
    for media_ref, expected_kind in ((image_ref, "audio"), (audio_ref, "image")):
        with pytest.raises(MediaResolutionError) as caught:
            resolver.resolve(media_ref, owner_user_id="owner", expected_kind=expected_kind)
        assert caught.value.code is MediaResolutionErrorCode.UNSUPPORTED_TYPE
    with pytest.raises(MediaResolutionError) as unauthorized:
        resolver.resolve(audio_ref, owner_user_id="other")
    assert unauthorized.value.code is MediaResolutionErrorCode.UNAUTHORIZED


def test_delete_owned_by_removes_image_and_audio_and_is_idempotent(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    image_ref = d.MediaRef(media_id=str(uuid4()))
    audio_ref = d.MediaRef(media_id=str(uuid4()))
    other_ref = d.MediaRef(media_id=str(uuid4()))
    store.persist_image(media_ref=image_ref, owner_user_id="owner", data=png_bytes(), mime_type="image/png")
    store.persist_audio(
        media_ref=audio_ref, owner_user_id="owner", data=m4a_bytes(), mime_type="audio/mp4", duration_ms=1234
    )
    store.persist_image(media_ref=other_ref, owner_user_id="other", data=png_bytes(), mime_type="image/png")

    assert store.delete_owned_by(owner_user_id="owner").deleted_count == 2
    assert store.delete_owned_by(owner_user_id="owner").deleted_count == 0
    assert (tmp_path / other_ref.media_id).is_dir()


def test_delete_owned_by_reports_failure_without_claiming_deletion(tmp_path, monkeypatch):
    store = PermanentMediaStore({"root": str(tmp_path)})
    media_ref = d.MediaRef(media_id=str(uuid4()))
    store.persist_image(media_ref=media_ref, owner_user_id="owner", data=png_bytes(), mime_type="image/png")
    original = __import__("shutil").rmtree

    def fail_owned(path):
        if path.name == media_ref.media_id:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr("src.infrastructure.media.media_store.shutil.rmtree", fail_owned)
    report = store.delete_owned_by(owner_user_id="owner")

    assert report.deleted_count == 0
    assert report.failures[0].media_id == media_ref.media_id
    assert report.failures[0].reason == "PermissionError"
    assert (tmp_path / media_ref.media_id).is_dir()


def test_delete_owned_by_reports_unreadable_media_metadata(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path)})
    media_id = str(uuid4())
    media_dir = tmp_path / media_id
    media_dir.mkdir()
    (media_dir / "metadata.json").write_text("not json", encoding="utf-8")

    report = store.delete_owned_by(owner_user_id="owner")

    assert report.deleted_count == 0
    assert report.failures[0].media_id == media_id
    assert report.failures[0].reason == "JSONDecodeError"
