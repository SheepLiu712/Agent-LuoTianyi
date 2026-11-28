"""客户端中断传输时必须释放临时文件，持久备份不能被清理。"""

import asyncio

import pytest
from starlette.requests import ClientDisconnect

from src.infrastructure.data_transfer._blob import FileBlob
from src.web.http.data_transfer_routes import _download


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["2.0", "2.4"])
@pytest.mark.parametrize("persistent", [False, True])
async def test_interrupted_download_closes_reader_and_releases_temporary_file(tmp_path, version, persistent):
    if persistent:
        path = tmp_path / "backup.zip"
        path.write_bytes(b"x" * (3 * 1024 * 1024))
        blob = FileBlob.open(path)
    else:
        blob = FileBlob.from_bytes(b"x" * (3 * 1024 * 1024))
        path = blob.path
    response = _download(blob, "backup.zip", "application/zip")
    started = asyncio.Event()

    async def receive():
        await started.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            started.set()
            if version == "2.4":
                raise OSError("客户端连接已断开")
            await asyncio.sleep(0.01)

    scope = {"type": "http", "asgi": {"spec_version": version}}
    if version == "2.4":
        with pytest.raises(ClientDisconnect):
            await response(scope, receive, send)
    else:
        await response(scope, receive, send)
    assert started.is_set()
    assert path.exists() is persistent
    if persistent:
        # Windows 上能重命名，证明读取句柄也已释放。
        path.rename(tmp_path / "retained.zip")
