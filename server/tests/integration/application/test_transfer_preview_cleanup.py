"""过期预览回收必须释放磁盘，同时保留活跃读取和永久备份。"""

import asyncio
import json

import pytest
from integration.application import test_user_data_transfer as shared

transfer = shared.transfer


def _expire(directory):
    path = directory / "info.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["created_at"] = 0
    path.write_text(json.dumps(info), encoding="utf-8")


@pytest.mark.asyncio
async def test_startup_and_periodic_cleanup_remove_repeated_previews_but_keep_backups(transfer):
    workspace = transfer.service._workspace
    identities = [shared.preview(transfer, b'[{"role":"user","content":"preview"}]') for _ in range(3)]
    directories = [workspace.root / "previews" / identity["preview_id"] for identity in identities]
    for directory in directories:
        _expire(directory)
    backup = workspace.put("backups", "bob", b"persistent backup")
    await transfer.service.start(cleanup_interval=0.01)
    try:
        assert all(not directory.exists() for directory in directories)
        identity = workspace.put("previews", "bob", b"new preview")
        directory = workspace.root / "previews" / identity
        _expire(directory)

        async def removed():
            while directory.exists():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(removed(), timeout=2)
        data, _ = workspace.get("backups", backup, "bob")
        try:
            assert data.read() == b"persistent backup"
        finally:
            data.close()
    finally:
        await transfer.service.close()


def test_cleanup_waits_for_reader_and_receipt_then_reclaims_archive(transfer):
    workspace = transfer.service._workspace
    identity = workspace.put("previews", "bob", b"active archive")
    data, _ = workspace.get("previews", identity, "bob")
    directory = workspace.root / "previews" / identity
    _expire(directory)
    try:
        workspace.cleanup_expired()
        assert data.read() == b"active archive"
        workspace.save_result(identity, "bob", {"committed": True})
        assert workspace.result(identity, "bob") == {"committed": True}
        workspace.cleanup_expired()
        assert directory.exists()
    finally:
        data.close()
    workspace.cleanup_expired()
    assert not directory.exists()
    with pytest.raises(FileNotFoundError):
        workspace.get("previews", identity, "bob")
