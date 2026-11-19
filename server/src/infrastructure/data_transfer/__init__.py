"""Pure, bounded transfer formats. Callers own authorization and persistence.

Files are keyed by ``media/<opaque-id>/content.bin``; no API here touches disk,
network, models, vectors, or the current clock. External documents are chat-only.
"""

from ._archive import decode_archive
from ._archive import encode_archive as _encode_archive
from ._external import FORMATS, decode_external
from ._render import render_readable as _render_readable
from ._schema import (
    MAX_ARCHIVE_ENTRIES,
    MAX_ENTRY_BYTES,
    MAX_EXPANDED_BYTES,
    MAX_UPLOAD_BYTES,
    SCOPES,
    TransferFormatError,
    apply_scope,
    require,
    validate_payload,
)

__all__ = [
    "MAX_ARCHIVE_ENTRIES",
    "MAX_ENTRY_BYTES",
    "MAX_EXPANDED_BYTES",
    "MAX_UPLOAD_BYTES",
    "TransferFormatError",
    "decode_import",
    "encode_archive",
    "render_readable",
]


def decode_import(data, source_format="auto", character_id="luotianyi", scope="all"):
    """Fully validate an upload, returning detached payload and verified media bytes."""
    try:
        return _decode_import(data, source_format, character_id, scope)
    except TransferFormatError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise TransferFormatError("Invalid transfer document structure") from exc


def _decode_import(data, source_format, character_id, scope):
    require(isinstance(data, bytes) and 0 < len(data) <= MAX_UPLOAD_BYTES, "Empty or oversized transfer upload")
    require(isinstance(source_format, str) and source_format in FORMATS, "Unknown source format")
    require(isinstance(scope, str) and scope in SCOPES, "Unknown transfer scope")
    require(isinstance(character_id, str) and bool(character_id.strip()), "Invalid target character")
    native = source_format == "native" or data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if native:
        require(source_format in {"auto", "native"}, "ZIP does not match the selected external format")
        payload, files = decode_archive(data)
    else:
        payload, files = decode_external(data, source_format, character_id)
        validate_payload(payload)
    payload = apply_scope(payload, scope)
    paths = {row["path"] for row in payload["media"] if row["path"] is not None}
    return payload, {path: content for path, content in files.items() if path in paths}


def encode_archive(payload, files):
    """Create a version-1 restoration ZIP with media and SHA-256 manifest."""
    try:
        return _encode_archive(payload, files)
    except TransferFormatError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise TransferFormatError("Invalid native transfer payload") from exc


def render_readable(payload, format):
    """Render a UTF-8 Markdown or TXT copy without reading media paths."""
    try:
        return _render_readable(payload, format)
    except TransferFormatError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise TransferFormatError("Invalid readable transfer payload") from exc
