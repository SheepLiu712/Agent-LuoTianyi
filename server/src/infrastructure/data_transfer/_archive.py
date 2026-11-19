"""Bounded in-memory native ZIP encoding and decoding; never extracts paths."""

import hashlib
import io
import stat
import struct
import unicodedata
import zipfile
import zlib
from pathlib import PurePosixPath

from ._schema import (
    FORMAT,
    MAX_ARCHIVE_ENTRIES,
    MAX_ENTRY_BYTES,
    MAX_EXPANDED_BYTES,
    MAX_UPLOAD_BYTES,
    SCOPES,
    SHA256,
    VERSION,
    TransferFormatError,
    json_bytes,
    read_json,
    require,
    validate_payload,
)


def _path(name):
    require(isinstance(name, str) and 0 < len(name) <= 512, "Invalid archive path")
    require("\\" not in name and ":" not in name, "Unsafe archive path")
    require(not any(ord(char) < 32 for char in name), "Unsafe archive path")
    path = name.rstrip("/")
    parts = path.split("/")
    require(
        all(part and part not in {".", ".."} and part == part.rstrip(" .") for part in parts), "Unsafe archive path"
    )
    require(not PurePosixPath(path).is_absolute(), "Absolute archive path")
    return unicodedata.normalize("NFKC", path).casefold()


def _member(info):
    _path(info.orig_filename)
    require(info.filename == info.orig_filename, "Truncated archive member path")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    allowed = {0, stat.S_IFDIR} if info.is_dir() else {0, stat.S_IFREG}
    require(file_type in allowed, "Archive links and special files are forbidden")
    require(not info.flag_bits & 1, "Encrypted archive members are unsupported")
    require(info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, "Unsupported archive compression")
    require(info.file_size <= MAX_ENTRY_BYTES, "Archive member exceeds the size limit")
    require(not info.is_dir() or info.file_size == 0, "Invalid directory member")


def _read_members(archive):
    infos = archive.infolist()
    require(len(infos) <= MAX_ARCHIVE_ENTRIES, "Archive contains too many entries")
    require(sum(info.file_size for info in infos) <= MAX_EXPANDED_BYTES, "Archive exceeds the expanded size limit")
    seen = set()
    members = {}
    expanded = 0
    for info in infos:
        _member(info)
        identity = _path(info.filename)
        require(identity not in seen, "Archive contains duplicate paths")
        seen.add(identity)
        if info.is_dir():
            require(info.filename.startswith("media/"), "Unexpected archive directory")
            continue
        with archive.open(info) as stream:
            data = stream.read(min(MAX_ENTRY_BYTES, MAX_EXPANDED_BYTES - expanded) + 1)
        require(len(data) == info.file_size and len(data) <= MAX_ENTRY_BYTES, "Invalid archive member size")
        expanded += len(data)
        require(expanded <= MAX_EXPANDED_BYTES, "Archive exceeds the expanded size limit")
        members[info.filename] = data
    return members


def _manifest(value, members):
    require(isinstance(value, dict), "Invalid archive manifest")
    require(value.get("format") == FORMAT, "Unknown archive manifest format")
    require(type(value.get("version")) is int and value["version"] == VERSION, "Unsupported archive version")
    require(isinstance(value.get("scope"), str) and value["scope"] in SCOPES, "Unknown manifest scope")
    checksums = value.get("files")
    require(isinstance(checksums, dict) and "data.json" in checksums, "Invalid manifest file list")
    require(set(checksums) == set(members) - {"manifest.json"}, "Manifest and archive files do not match")
    warnings = value.get("warnings")
    require(isinstance(warnings, list) and all(isinstance(item, str) for item in warnings), "Invalid manifest warnings")
    for name, checksum in checksums.items():
        require(isinstance(checksum, str) and SHA256.fullmatch(checksum) is not None, "Invalid manifest checksum")
        require(hashlib.sha256(members[name]).hexdigest() == checksum, "Archive checksum mismatch")


def _media_files(payload, members):
    paths = {row["path"] for row in payload["media"] if row["path"] is not None}
    require(set(members) == paths | {"manifest.json", "data.json"}, "Archive contains unreferenced or missing files")
    files = {path: members[path] for path in paths}
    for row in payload["media"]:
        if row["path"] is not None:
            checksum = hashlib.sha256(files[row["path"]]).hexdigest()
            require(checksum == row["sha256"], "Media checksum mismatch")
    return files


def decode_archive(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = _read_members(archive)
        require("manifest.json" in members and "data.json" in members, "Incomplete native archive")
        manifest = read_json(members["manifest.json"])
        _manifest(manifest, members)
        payload = validate_payload(read_json(members["data.json"]))
        json_bytes(payload)
        require(manifest["scope"] == payload["scope"], "Manifest scope differs from payload")
        require(manifest["warnings"] == payload["warnings"], "Manifest warnings differ from payload")
        files = _media_files(payload, members)
        payload["source_format"] = "native"
        return payload, files
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        EOFError,
        NotImplementedError,
        OSError,
        zlib.error,
        struct.error,
    ) as exc:
        raise TransferFormatError("Invalid or unsupported native ZIP archive") from exc


def _prepare_files(payload, files):
    require(isinstance(files, dict), "Archive files must be a path-to-bytes mapping")
    expected = {row["path"] for row in payload["media"] if row["path"] is not None}
    require(set(files) == expected, "Media descriptors and file paths do not match")
    for row in payload["media"]:
        if row["path"] is not None:
            data = files[row["path"]]
            require(isinstance(data, bytes) and len(data) <= MAX_ENTRY_BYTES, "Invalid media file or size")
            require(hashlib.sha256(data).hexdigest() == row["sha256"], "Media checksum mismatch")


def encode_archive(payload, files):
    payload = validate_payload(read_json(json_bytes(payload)))
    _prepare_files(payload, files)
    members = {"data.json": json_bytes(payload), **files}
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "scope": payload["scope"],
        "warnings": payload["warnings"],
        "files": {path: hashlib.sha256(data).hexdigest() for path, data in members.items()},
    }
    members["manifest.json"] = json_bytes(manifest)
    require(len(members) <= MAX_ARCHIVE_ENTRIES, "Archive contains too many entries")
    require(all(len(data) <= MAX_ENTRY_BYTES for data in members.values()), "Archive member exceeds the size limit")
    require(sum(map(len, members.values())) <= MAX_EXPANDED_BYTES, "Archive exceeds the expanded size limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(members.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
    result = output.getvalue()
    require(len(result) <= MAX_UPLOAD_BYTES, "Archive exceeds the upload size limit")
    return result
