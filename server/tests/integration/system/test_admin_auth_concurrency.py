import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.system.admin.auth import AdminAuthService


@pytest.mark.asyncio
async def test_admin_password_work_is_bounded_without_blocking_event_loop(tmp_path, monkeypatch):
    auth = AdminAuthService(tmp_path / "auth.json", tmp_path / "setup-token.txt")
    monkeypatch.setattr(auth, "is_configured", lambda: True)
    auth._password_work_admission_timeout = 0.02

    release = threading.Event()
    entered = 0
    entered_lock = threading.Lock()

    def slow_verify(_password):
        nonlocal entered
        with entered_lock:
            entered += 1
        release.wait(timeout=2)
        return True

    monkeypatch.setattr(auth, "_verify_password", slow_verify)

    def response():
        return SimpleNamespace(set_cookie=lambda *_args, **_kwargs: None)

    workers = [
        asyncio.create_task(auth.login_async("password", response()))
        for _ in range(4)
    ]
    try:
        for _ in range(100):
            with entered_lock:
                if entered == 4:
                    break
            await asyncio.sleep(0.005)

        with entered_lock:
            assert entered == 4

        heartbeat_advanced = False

        async def heartbeat():
            nonlocal heartbeat_advanced
            await asyncio.sleep(0)
            heartbeat_advanced = True

        heartbeat_task = asyncio.create_task(heartbeat())
        with pytest.raises(HTTPException) as exc_info:
            await auth.login_async("password", response())
        await heartbeat_task

        assert exc_info.value.status_code == 503
        assert heartbeat_advanced is True
    finally:
        release.set()
        await asyncio.gather(*workers)
