"""聊天与记忆迁移的冻结请求、受限文件读写；不持有任何 Qt 对象。"""

from __future__ import annotations

import io
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from threading import Event

from ..utils.http_client import HttpClientFactory

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
_CHUNK_SIZE = 64 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class TransferCancelled(Exception):
    pass


def _check_cancelled(cancelled: Event) -> None:
    if cancelled.is_set():
        raise TransferCancelled()


def _plain_file(path: Path, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("目录包不能包含符号链接或目录联接")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("目录包只能包含普通文件和目录")
    return info


def _safe_parts(name: str) -> tuple[str, ...]:
    # 同时按 Windows 和 POSIX 解释路径，避免跨平台包绕过或文件名别名。
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        raise ValueError("ZIP 包含不安全的路径")
    parts = name.rstrip("/").split("/")
    for part in parts:
        if (
            part in ("", ".", "..")
            or ":" in part
            or part.endswith((" ", "."))
            or part.split(".")[0].upper() in _RESERVED_NAMES
        ):
            raise ValueError("ZIP 包含不安全的路径")
    return tuple(parts)


def _archive_entries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("ZIP 条目超过 4096 项上限")
    total = 0
    seen = {}
    checked = []
    for entry in entries:
        # Windows 的 ZipInfo.filename 已规范化分隔符；原名还保留 NUL 等非法输入。
        parts = _safe_parts(entry.orig_filename)
        key = "/".join(parts).casefold()
        if key in seen:
            raise ValueError("ZIP 包含重复路径")
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError("ZIP 不能包含符号链接或特殊文件")
        if entry.flag_bits & 1:
            raise ValueError("不支持加密 ZIP")
        total += entry.file_size
        if total > MAX_EXPANDED_BYTES:
            raise ValueError("ZIP 展开大小超过 256 MiB 上限")
        seen[key] = entry.is_dir()
        checked.append((entry, parts))
    for key in seen:
        parents = PurePosixPath(key).parents
        if any(str(parent) in seen and not seen[str(parent)] for parent in parents):
            raise ValueError("ZIP 包含文件与目录冲突")
    return checked


def _directory_payload(root: Path, cancelled: Event) -> bytes:
    _plain_file(root, directory=True)
    output = io.BytesIO()
    total = count = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for current, directories, files in os.walk(root, followlinks=False):
            _check_cancelled(cancelled)
            _plain_file(Path(current), directory=True)
            for name in directories:
                _plain_file(Path(current) / name, directory=True)
            for name in sorted(files):
                _check_cancelled(cancelled)
                path = Path(current) / name
                info = _plain_file(path)
                total += info.st_size
                count += 1
                if count > MAX_ARCHIVE_ENTRIES or total > MAX_EXPANDED_BYTES:
                    raise ValueError("目录包超过 4096 项或 256 MiB 展开上限")
                member = path.relative_to(root).as_posix()
                _safe_parts(member)
                with path.open("rb") as source, archive.open(member, "w") as target:
                    read = 0
                    while chunk := source.read(_CHUNK_SIZE):
                        _check_cancelled(cancelled)
                        read += len(chunk)
                        if read > info.st_size:
                            raise ValueError("目录文件在读取期间发生变化，请重新预览")
                        target.write(chunk)
                if read != info.st_size:
                    raise ValueError("目录文件在读取期间发生变化，请重新预览")
                if output.tell() > MAX_UPLOAD_BYTES:
                    raise ValueError("上传大小超过 64 MiB 上限")
    payload = output.getvalue()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError("上传大小超过 64 MiB 上限")
    # 文件名大小写冲突等规则与下载目录包保持一致。
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        _archive_entries(archive)
    return payload


def read_import_payload(path: str, cancelled: Event) -> bytes:
    source = Path(path)
    if source.is_dir():
        return _directory_payload(source, cancelled)
    info = _plain_file(source)
    if info.st_size > MAX_UPLOAD_BYTES:
        raise ValueError("上传大小超过 64 MiB 上限")
    content = bytearray()
    with source.open("rb") as stream:
        while chunk := stream.read(_CHUNK_SIZE):
            _check_cancelled(cancelled)
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                raise ValueError("上传大小超过 64 MiB 上限")
    _check_cancelled(cancelled)
    payload = bytes(content)
    if source.suffix.lower() == ".zip" or payload.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            _archive_entries(archive)
    return payload


def _save_download(response, destination: str, directory: bool, cancelled: Event) -> str:
    target = Path(destination)
    parent = target.parent
    if not parent.is_dir():
        raise ValueError("保存位置不存在")
    if directory and target.exists():
        raise ValueError("目录包的目标已存在，请选择新的目录名")
    # 在目标盘上暂存，成功且未取消后再一次性发布，避免留下不完整备份。
    with tempfile.TemporaryDirectory(prefix=".agentluo-transfer-", dir=parent) as temporary:
        staging = Path(temporary)
        downloaded = staging / "download"
        size = 0
        with downloaded.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                _check_cancelled(cancelled)
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError("下载大小超过 64 MiB 上限")
                stream.write(chunk)
        _check_cancelled(cancelled)
        if not directory:
            os.replace(downloaded, target)
            return str(target)
        unpacked = staging / "package"
        unpacked.mkdir()
        with zipfile.ZipFile(downloaded) as archive:
            entries = _archive_entries(archive)
            for entry, parts in entries:
                _check_cancelled(cancelled)
                item = unpacked.joinpath(*parts)
                if entry.is_dir():
                    item.mkdir(parents=True, exist_ok=True)
                    continue
                item.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, item.open("xb") as output:
                    while chunk := source.read(_CHUNK_SIZE):
                        _check_cancelled(cancelled)
                        output.write(chunk)
        _check_cancelled(cancelled)
        unpacked.rename(target)
    return str(target)


@dataclass(frozen=True)
class DataTransferRequest:
    context: tuple = field(repr=False)
    action: str
    base_url: str
    token: str | None = field(repr=False)
    scope: str = "all"
    format: str = "zip"
    source_format: str = "auto"
    character_id: str = "luotianyi"
    source_path: str = field(default="", repr=False)
    destination: str = field(default="", repr=False)
    directory: bool = False
    preview_id: str = ""
    mode: str = "merge"
    confirm_replace: bool = False
    extract_memories: bool = False
    backup_id: str = ""

    def execute(self, cancelled: Event) -> tuple[bool, str, dict]:
        try:
            _check_cancelled(cancelled)
            if not self.token:
                return False, "请先登录后再迁移数据", {}
            with HttpClientFactory.create_session(verify_ssl=True) as session:
                return self.fetch(session, cancelled)
        except TransferCancelled:
            return False, "操作已取消", {}
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            return False, str(exc), {}
        except Exception as exc:
            # 不把请求正文、令牌或响应正文带入诊断。
            return False, f"请求失败（{type(exc).__name__}），请检查连接后重试", {}

    def fetch(self, session, cancelled: Event) -> tuple[bool, str, dict]:
        _check_cancelled(cancelled)
        if not self.token:
            return False, "请先登录后再迁移数据", {}
        if self.scope not in ("all", "chat", "memory"):
            raise ValueError("请选择有效的数据范围")
        headers = {"Authorization": f"Bearer {self.token}"}
        options = {"headers": headers, "verify": True, "timeout": (10, 180), "allow_redirects": False}
        if self.action == "preview":
            payload = read_import_payload(self.source_path, cancelled)
            _check_cancelled(cancelled)
            headers["Content-Type"] = "application/octet-stream"
            response = session.post(
                f"{self.base_url}/user/data/import/preview",
                params={"source_format": self.source_format, "scope": self.scope, "character_id": self.character_id},
                data=payload,
                **options,
            )
        elif self.action == "commit":
            if not self.preview_id or self.mode not in ("merge", "replace"):
                raise ValueError("请先重新预览要导入的文件")
            if self.mode == "replace" and not self.confirm_replace:
                raise ValueError("替换前必须明确确认")
            response = session.post(
                f"{self.base_url}/user/data/import/commit",
                json={
                    "preview_id": self.preview_id,
                    "mode": self.mode,
                    "confirm_replace": self.confirm_replace,
                    "extract_memories": self.extract_memories,
                },
                **options,
            )
        elif self.action in ("export", "backup"):
            if self.action == "backup":
                if not _SAFE_ID.fullmatch(self.backup_id):
                    raise ValueError("备份标识无效，请重新导入或联系管理员")
                url = f"{self.base_url}/user/data/backups/{self.backup_id}"
                params = None
            else:
                if self.format not in ("zip", "markdown", "txt"):
                    raise ValueError("导出格式无效")
                url = f"{self.base_url}/user/data/export"
                params = {"scope": self.scope, "format": self.format}
            response = session.get(url, params=params, stream=True, **options)
        else:
            raise ValueError("迁移操作无效")
        try:
            if response.status_code != 200:
                detail = f"HTTP {response.status_code}"
                try:
                    server_detail = response.json().get("detail")
                    if isinstance(server_detail, str):
                        detail += f"：{server_detail}"
                except (ValueError, AttributeError):
                    pass
                return False, detail, {}
            if self.action in ("export", "backup"):
                path = _save_download(response, self.destination, self.directory, cancelled)
                return True, "已保存", {"path": path}
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("服务器返回的数据格式无效")
            if self.action == "preview":
                if not data.get("preview_id") or data.get("scope") not in ("all", "chat", "memory"):
                    raise ValueError("预览响应缺少有效标识或数据范围")
                return True, "预览完成", data
            success = data.get("success") is True
            message = "导入完成" if success else str(data.get("error") or "导入未完成")
            return success, message, data
        finally:
            response.close()
