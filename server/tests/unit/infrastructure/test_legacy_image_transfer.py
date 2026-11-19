"""Safe source-only compatibility reads; every image and path is synthetic."""

import io
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.infrastructure.media import legacy_image
from src.infrastructure.media.legacy_image import LegacyImageReader


class ConversationImages:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []

    def get_image_server_path(self, user_id, conversation_id):
        self.calls.append((user_id, conversation_id))
        return self.rows.get((user_id, conversation_id))


def _image(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format=format)
    return output.getvalue()


def _write(root, owner="alice", filename="valid.png", data=None):
    path = root / owner / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_image() if data is None else data)
    return path


def _reader(root, path, *, max_bytes=6 * 1024 * 1024):
    source = ConversationImages({("alice", "conversation"): str(path)})
    return LegacyImageReader(source, root, max_bytes), source


@pytest.mark.parametrize(
    ("format", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("GIF", "image/gif"), ("BMP", "image/bmp")]
)
def test_reads_only_owned_local_conversation_and_detects_real_format(tmp_path, format, mime):
    root = tmp_path / "images"
    data = _image(format)
    path = _write(root, filename="incorrect-extension.bin", data=data)
    reader, source = _reader(root, path)
    result = reader("alice", "conversation")
    assert result is not None and result.data == data and result.mime_type == mime
    assert source.calls == [("alice", "conversation")]
    assert reader("bob", "conversation") is None
    assert source.calls[-1] == ("bob", "conversation")
    assert path.read_bytes() == data


def test_none_root_disables_reads_without_querying_the_source(tmp_path):
    source = ConversationImages({("alice", "conversation"): str(_write(tmp_path / "images"))})
    assert LegacyImageReader(source, None)("alice", "conversation") is None
    assert LegacyImageReader(source, "")("alice", "conversation") is None
    assert source.calls == []


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5, None])
def test_configuration_rejects_invalid_byte_limit(tmp_path, max_bytes):
    with pytest.raises(ValueError, match="positive integer"):
        LegacyImageReader(ConversationImages(), tmp_path, max_bytes)


def test_configuration_rejects_relative_roots():
    with pytest.raises(ValueError, match="absolute"):
        LegacyImageReader(ConversationImages(), "relative/images")


@pytest.mark.parametrize("owner", ["../alice", "alice/bob", "alice\\bob", "..", "C:", "alice.", "alice ", "", None])
def test_invalid_owner_is_never_queried(tmp_path, owner):
    source = ConversationImages()
    assert LegacyImageReader(source, tmp_path)(owner, "conversation") is None
    assert source.calls == []


def test_missing_conversation_and_non_string_database_paths_are_unavailable(tmp_path):
    for path in (None, "", {}, ["not a path"], 123):
        reader = LegacyImageReader(ConversationImages({("alice", "conversation"): path}), tmp_path)
        assert reader("alice", "conversation") is None
    reader = LegacyImageReader(ConversationImages(), tmp_path)
    assert reader("alice", "missing") is None
    assert reader("alice", "") is None


def test_database_failure_propagates_instead_of_becoming_a_missing_image(tmp_path):
    class BrokenSource:
        def get_image_server_path(self, user_id, conversation_id):
            raise RuntimeError("synthetic database failure")

    with pytest.raises(RuntimeError, match="database failure"):
        LegacyImageReader(BrokenSource(), tmp_path)("alice", "conversation")


@pytest.mark.parametrize(
    "kind", ["other_owner", "outside_root", "prefix_collision", "traversal", "relative", "directory"]
)
def test_database_path_must_stay_in_the_exact_owner_directory(tmp_path, kind):
    root = tmp_path / "images"
    valid = _write(root)
    paths = {
        "other_owner": _write(root, "bob"),
        "outside_root": _write(tmp_path / "outside"),
        "prefix_collision": _write(root, "alice-other"),
        "traversal": str(valid.parent / ".." / "alice" / valid.name),
        "relative": Path("alice/valid.png"),
        "directory": valid.parent,
    }
    reader, _ = _reader(root, paths[kind])
    assert reader("alice", "conversation") is None


@pytest.mark.parametrize("kind", ["missing", "empty", "non_image", "oversized"])
def test_missing_invalid_and_oversized_files_return_none(tmp_path, kind):
    root = tmp_path / "images"
    path = _write(root, data={"empty": b"", "non_image": b"plain text"}.get(kind))
    if kind == "missing":
        path = path.with_name("missing.png")
    reader, _ = _reader(root, path, max_bytes=1 if kind == "oversized" else 6 * 1024 * 1024)
    assert reader("alice", "conversation") is None


def test_file_read_is_bounded_and_accepts_the_exact_byte_limit(tmp_path, monkeypatch):
    root = tmp_path / "images"
    data = _image()
    path = _write(root, data=data)
    original = os.fdopen
    sizes = []

    class BoundedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            sizes.append(size)
            assert 0 < size <= len(data) + 1
            return self.stream.read(size)

    monkeypatch.setattr(legacy_image.os, "fdopen", lambda fd, mode: BoundedStream(original(fd, mode)))
    reader, _ = _reader(root, path, max_bytes=len(data))
    assert reader("alice", "conversation").data == data
    assert sizes == [len(data) + 1]


def _symlink(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"This environment cannot construct a symlink: {type(error).__name__}")


@pytest.mark.parametrize("kind", ["file", "parent", "owner", "root"])
def test_rejects_symlinks_at_every_legacy_path_boundary(tmp_path, kind):
    root = tmp_path / "images"
    valid = _write(root)
    configured_root = root
    if kind == "file":
        path = valid.with_name("linked.png")
        _symlink(path, valid)
    elif kind == "parent":
        target = _write(tmp_path / "elsewhere")
        link = valid.parent / "linked-directory"
        _symlink(link, target.parent, directory=True)
        path = link / target.name
    elif kind == "owner":
        target = _write(tmp_path / "outside")
        _symlink(root / "linked-owner", target.parent, directory=True)
        source = ConversationImages({("linked-owner", "conversation"): str(root / "linked-owner" / target.name)})
        assert LegacyImageReader(source, root)("linked-owner", "conversation") is None
        return
    else:
        configured_root = tmp_path / "linked-root"
        _symlink(configured_root, root, directory=True)
        path = configured_root / "alice" / valid.name
    reader, _ = _reader(configured_root, path)
    assert reader("alice", "conversation") is None


def test_rejects_host_directory_redirect(tmp_path):
    root = tmp_path / "images"
    valid = _write(root)
    target = _write(tmp_path / "outside")
    link = valid.parent / "redirect"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target.parent)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, "Test runner cannot construct a directory junction"
    else:
        _symlink(link, target.parent, directory=True)
    try:
        entry = link.lstat()
        assert link.is_symlink() or getattr(entry, "st_file_attributes", 0) & legacy_image._REPARSE_POINT
        reader, _ = _reader(root, link / target.name)
        assert reader("alice", "conversation") is None
    finally:
        # Only remove the verified redirect created by this test, never its target.
        if link.is_symlink():
            link.unlink()
        elif getattr(link.lstat(), "st_file_attributes", 0) & legacy_image._REPARSE_POINT:
            link.rmdir()


def test_changed_open_target_is_rejected_before_read(tmp_path, monkeypatch):
    root = tmp_path / "images"
    valid = _write(root)
    outside = _write(tmp_path / "outside")
    if os.name == "nt":
        monkeypatch.setattr(legacy_image, "_windows_final_path", lambda descriptor: outside)
    else:
        monkeypatch.setattr(legacy_image, "_open_posix", lambda path: os.open(outside, os.O_RDONLY))
    reader, _ = _reader(root, valid)
    assert reader("alice", "conversation") is None


def test_image_decompression_bomb_is_not_exported(tmp_path, monkeypatch):
    root = tmp_path / "images"
    path = _write(root)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    reader, _ = _reader(root, path)
    assert reader("alice", "conversation") is None
