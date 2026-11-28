"""Private source-snapshot bridge for images saved under data/images/<owner>.

Only the authenticated owner and a local conversation identity enter this API.
It never accepts an archive path, creates a file, or participates in imports.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Protocol

from PIL import Image

from .image_validation import validate_image_content
from .media_resolver import MediaResolutionError, ResolvedMedia

_DEFAULT_MAX_BYTES = 6 * 1024 * 1024
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class _ConversationImages(Protocol):
    def get_image_server_path(self, user_id: str, conv_uuid: str) -> str | None: ...


def _safe_component(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and value == value.rstrip(" .")
        and not any(char in value for char in ("/", "\\", ":"))
        and not any(ord(char) < 32 for char in value)
    )


def _inspect_path(path: Path) -> os.stat_result:
    """Inspect every component before opening; Python 3.10 lacks Path.is_junction."""
    for directory in reversed(path.parents):
        entry = directory.lstat()
        _reject_link(entry)
        if not stat.S_ISDIR(entry.st_mode):
            raise OSError("Legacy image ancestor is not a directory")
    entry = path.lstat()
    _reject_link(entry)
    if not stat.S_ISREG(entry.st_mode):
        raise OSError("Legacy image is not a regular file")
    return entry


def _reject_link(entry: os.stat_result) -> None:
    if stat.S_ISLNK(entry.st_mode) or getattr(entry, "st_file_attributes", 0) & _REPARSE_POINT:
        raise OSError("Legacy image links and reparse points are forbidden")


def _open_posix(path: Path) -> int:
    """Use directory descriptors so ancestor substitution cannot follow a link."""
    flags = os.O_RDONLY | os.O_NOFOLLOW
    directory = os.open(path.anchor, flags | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, flags | getattr(os, "O_NONBLOCK", 0), dir_fd=directory)
    finally:
        os.close(directory)


def _windows_final_path(descriptor: int) -> Path:
    """Verify the opened handle rather than trusting a pre-open pathname check."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    function.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    function.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise OSError("Cannot verify the legacy image file handle")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _open_checked(path: Path, expected: os.stat_result, max_bytes: int) -> int:
    if os.name == "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    else:
        descriptor = _open_posix(path)
    try:
        opened = os.fstat(descriptor)
        _reject_link(opened)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise OSError("Legacy image changed while opening")
        if not 0 < opened.st_size <= max_bytes:
            raise OSError("Legacy image is empty or oversized")
        if os.name == "nt" and _windows_final_path(descriptor) != path:
            raise OSError("Legacy image handle escaped the checked path")
        _inspect_path(path)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_image(path: Path, max_bytes: int) -> bytes:
    expected = _inspect_path(path)
    if not 0 < expected.st_size <= max_bytes:
        raise OSError("Legacy image is empty or oversized")
    descriptor = _open_checked(path, expected, max_bytes)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    if len(data) > max_bytes or len(data) != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise OSError("Legacy image changed while reading")
    return data


class LegacyImageReader:
    """Read a verified old image, or return None for an unsafe/unavailable file.

    ``root`` must be the fixed, absolute legacy image root injected by assembly.
    A missing root disables compatibility reads. Database lookup failures propagate
    so an unavailable source of truth cannot be reported as a complete backup.
    """

    def __init__(
        self, conversation_service: _ConversationImages, root: str | Path | None, max_bytes: int = _DEFAULT_MAX_BYTES
    ) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("Legacy image max_bytes must be a positive integer")
        self._conversations = conversation_service
        self._root = Path(root) if root else None
        if self._root is not None and not self._root.is_absolute():
            raise ValueError("Legacy image root must be absolute")
        self._max_bytes = max_bytes

    def __call__(self, user_id: str, conversation_id: str) -> ResolvedMedia | None:
        if self._root is None or not isinstance(user_id, str) or not _safe_component(user_id):
            return None
        if not isinstance(conversation_id, str) or not conversation_id:
            return None
        raw_path = self._conversations.get_image_server_path(user_id, conversation_id)
        if not isinstance(raw_path, str) or not raw_path:
            return None
        try:
            path = self._owned_path(user_id, raw_path)
            data = _read_image(path, self._max_bytes)
            mime_type = validate_image_content(data, None, conversation_id)
            return ResolvedMedia(data=data, mime_type=mime_type)
        except (OSError, ValueError, RuntimeError, SyntaxError, MediaResolutionError, Image.DecompressionBombError):
            return None

    def _owned_path(self, user_id: str, raw_path: str) -> Path:
        if any(part in {".", ".."} for part in raw_path.replace("\\", "/").split("/")):
            raise ValueError("Legacy image traversal is forbidden")
        # 历史 Windows/POSIX 路径仅提供文件名；实际读取始终限定本人固定目录。
        parts = raw_path.replace("\\", "/").split("/")
        try:
            relative = Path(raw_path).relative_to(self._root / user_id)
        except ValueError:
            if parts[-4:-1] != ["data", "images", user_id]:
                raise ValueError("Invalid legacy image owner path") from None
        else:
            if len(relative.parts) != 1:
                raise ValueError("Nested legacy image path is forbidden")
        name = parts[-1]
        if not _safe_component(name):
            raise ValueError("Invalid legacy image path")
        return self._root / user_id / name
