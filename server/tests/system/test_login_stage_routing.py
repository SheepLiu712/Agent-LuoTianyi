"""认证成功后的首次登录与回访登录路由。"""

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from src.system.user_interface.types import AutoLoginRequest, LoginRequest
from src.system.user_interface.user_interface import UserInterface


class StageManager:
    def __init__(self) -> None:
        self.logins: list[tuple[str, str, float | None]] = []

    def record_login(
        self,
        user_id: str,
        character_id: str,
        *,
        elapsed_from_last_login: float | None,
    ) -> bool:
        self.logins.append((user_id, character_id, elapsed_from_last_login))
        return True


class LegacyLoginManager:
    def __init__(self) -> None:
        self.logins: list[tuple[str, float]] = []

    async def on_user_login(self, user_id: str, elapsed_from_last_login: float) -> None:
        self.logins.append((user_id, elapsed_from_last_login))


class CredentialService:
    def __init__(self, elapsed_from_last_login: float | None) -> None:
        self.elapsed_from_last_login = elapsed_from_last_login

    def authenticate_auto_login(self, username: str, token: str) -> dict:
        return self._result()

    def authenticate_password_login(self, username: str, password: str) -> dict:
        return self._result()

    def _result(self) -> dict:
        return {
            "user_uuid": "user",
            "elapsed_from_last_login": self.elapsed_from_last_login,
            "login_token": "login-token",
            "message_token": "message-token",
        }


def runtime(elapsed_from_last_login: float | None):
    stage_manager = StageManager()
    legacy = LegacyLoginManager()
    database = SimpleNamespace(
        credential_service=CredentialService(elapsed_from_last_login),
        conversation_service=SimpleNamespace(prefill_buffer=lambda _user_id: None),
    )
    return SimpleNamespace(
        database_manager=database,
        stage_manager=stage_manager,
        chat_session_manager=legacy,
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
    ), stage_manager, legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["login", "auto_login"])
async def test_first_login_records_stage_fact_without_legacy_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    # Given: authentication reports that the account has never logged in.
    system_runtime, stage_manager, legacy = runtime(None)
    user_interface = UserInterface(system_runtime.database_manager)
    monkeypatch.setattr(user_interface, "decrypt_user_password", lambda value: value)
    request = LoginRequest(username="alice", password="secret") if method == "login" else AutoLoginRequest(username="alice", token="token")

    # When: either supported authentication endpoint succeeds.
    await getattr(user_interface, method)(request, BackgroundTasks(), system_runtime, None)

    # Then: only the character-scoped Stage first-login seam receives the fact.
    assert stage_manager.logins == [("user", "luotianyi", None)]
    assert legacy.logins == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["login", "auto_login"])
async def test_return_login_stays_on_legacy_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    # Given: authentication reports a previous successful login.
    system_runtime, stage_manager, legacy = runtime(60.0)
    user_interface = UserInterface(system_runtime.database_manager)
    monkeypatch.setattr(user_interface, "decrypt_user_password", lambda value: value)
    request = LoginRequest(username="alice", password="secret") if method == "login" else AutoLoginRequest(username="alice", token="token")

    # When: the returning account authenticates.
    await getattr(user_interface, method)(request, BackgroundTasks(), system_runtime, None)

    # Then: the existing return-login path remains authoritative.
    assert stage_manager.logins == []
    assert legacy.logins == [("user", 60.0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["login", "auto_login"])
async def test_first_ordinary_login_today_routes_to_stage_claim_path(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    # Given: the previous login was yesterday, so this is today's first ordinary login.
    system_runtime, stage_manager, legacy = runtime(24 * 60 * 60)
    user_interface = UserInterface(system_runtime.database_manager)
    monkeypatch.setattr(user_interface, "decrypt_user_password", lambda value: value)
    request = LoginRequest(username="alice", password="secret") if method == "login" else AutoLoginRequest(username="alice", token="token")

    # When: authentication succeeds through either supported endpoint.
    await getattr(user_interface, method)(request, BackgroundTasks(), system_runtime, None)

    # Then: Stage receives the login fact and the legacy topic maker is not invoked.
    assert stage_manager.logins == [("user", "luotianyi", 24 * 60 * 60)]
    assert legacy.logins == []
