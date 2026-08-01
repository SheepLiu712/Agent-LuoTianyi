from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import time

import pytest
from jose import jwt

from src.system.database import database_service
from src.system.database.database_service import ALGORITHM, DatabaseManager
from src.system.database.sql_database import InviteCode, User
from src.system.token_config import (
    DEFAULT_MESSAGE_TOKEN_TTL_SECONDS,
    MAX_MESSAGE_TOKEN_TTL_SECONDS,
    MIN_MESSAGE_TOKEN_TTL_SECONDS,
)
from src.system.user_interface.account import (
    check_message_token as check_legacy_message_token,
    generate_message_token as generate_legacy_message_token,
)


@pytest.fixture
def authenticated_user(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "message-token-test-secret")
    monkeypatch.setattr(database_service, "_hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(
        database_service,
        "_is_bcrypt_hash",
        lambda value: bool(value and value.startswith("hash:")),
    )
    monkeypatch.setattr(
        database_service,
        "_verify_password",
        lambda password, stored: stored == f"hash:{password}",
    )
    manager = DatabaseManager(
        {
            "sql_db_folder": str(tmp_path / "db"),
            "sql_db_file": "auth.db",
            "message_token_ttl_seconds": 120,
        }
    )
    session = manager.open_sql_session()
    try:
        session.add(InviteCode(code="AUTH-CODE", is_used=False))
        session.commit()
    finally:
        session.close()
    assert manager.register_user("alice", "password", "AUTH-CODE")[0] is True
    auth_token = manager.update_auth_token("alice")
    message_token = manager.generate_message_token("alice", expected_auth_token=auth_token)
    return manager, auth_token, message_token


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, DEFAULT_MESSAGE_TOKEN_TTL_SECONDS),
        (True, DEFAULT_MESSAGE_TOKEN_TTL_SECONDS),
        ("3600", DEFAULT_MESSAGE_TOKEN_TTL_SECONDS),
        (0, MIN_MESSAGE_TOKEN_TTL_SECONDS),
        (MIN_MESSAGE_TOKEN_TTL_SECONDS, MIN_MESSAGE_TOKEN_TTL_SECONDS),
        (MAX_MESSAGE_TOKEN_TTL_SECONDS, MAX_MESSAGE_TOKEN_TTL_SECONDS),
        (MAX_MESSAGE_TOKEN_TTL_SECONDS + 1, MAX_MESSAGE_TOKEN_TTL_SECONDS),
    ],
)
def test_database_manager_bounds_message_token_ttl_without_validator(
    monkeypatch,
    value,
    expected,
):
    monkeypatch.setattr(DatabaseManager, "init_all_databases", lambda self: None)

    manager = DatabaseManager({"message_token_ttl_seconds": value})

    assert manager.message_token_ttl_seconds == expected


def test_message_token_has_expiring_session_bound_claims(authenticated_user):
    manager, auth_token, message_token = authenticated_user
    claims = jwt.get_unverified_claims(message_token)

    assert {"user_uuid", "iat", "exp", "jti", "session_fp"} <= claims.keys()
    assert claims["exp"] > claims["iat"]
    assert auth_token not in claims.values()
    assert manager.check_message_token("alice", message_token) == (True, claims["user_uuid"])


def test_relogin_invalidates_previous_message_token(authenticated_user):
    manager, _, old_message_token = authenticated_user
    new_auth_token = manager.update_auth_token("alice")
    new_message_token = manager.generate_message_token("alice", expected_auth_token=new_auth_token)

    assert manager.check_message_token("alice", old_message_token) == (False, None)
    assert manager.check_message_token("alice", new_message_token)[0] is True


def test_expired_message_token_is_rejected(authenticated_user):
    manager, auth_token, valid_token = authenticated_user
    claims = jwt.get_unverified_claims(valid_token)
    now = int(time.time())
    expired_token = jwt.encode(
        {
            **claims,
            "iat": now - 120,
            "exp": now - 60,
            "session_fp": manager._session_fingerprint(auth_token),
        },
        manager.jwt_secret,
        algorithm=ALGORITHM,
    )

    assert manager.check_message_token("alice", expired_token) == (False, None)


def test_message_token_validation_ignores_poisoned_username_cache(authenticated_user):
    manager, _, message_token = authenticated_user
    manager._ensure_redis().setex("user_id:alice", 3600, "attacker-controlled-id")

    ok, user_uuid = manager.check_message_token("alice", message_token)

    assert ok is True
    assert user_uuid != "attacker-controlled-id"


def test_password_login_ignores_poisoned_username_cache(authenticated_user):
    manager, _, _ = authenticated_user
    session = manager.open_sql_session()
    try:
        database_uuid = session.query(User.uuid).filter(User.username == "alice").scalar()
    finally:
        session.close()
    manager._ensure_redis().setex("user_id:alice", 3600, "attacker-controlled-id")

    result = manager.authenticate_password_login("alice", "password")

    assert result is not None
    assert result["user_uuid"] == database_uuid
    assert jwt.get_unverified_claims(result["message_token"])["user_uuid"] == database_uuid


def test_inflight_password_login_cannot_restore_session_after_reset(
    authenticated_user,
    monkeypatch,
):
    manager, _, _ = authenticated_user
    ready = Event()
    release = Event()
    original_rotate = manager._rotate_authenticated_session

    def delayed_rotate(*args, **kwargs):
        ready.set()
        if not release.wait(timeout=5):
            raise AssertionError("test did not release authentication")
        return original_rotate(*args, **kwargs)

    monkeypatch.setattr(manager, "_rotate_authenticated_session", delayed_rotate)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(manager.authenticate_password_login, "alice", "password")
        try:
            assert ready.wait(timeout=5)
            assert manager.reset_account("AUTH-CODE", "alice", "new-password")[0] is True
        finally:
            release.set()
        result = future.result(timeout=10)

    assert result is None
    session = manager.open_sql_session()
    try:
        assert session.query(User.auth_token).filter(User.username == "alice").scalar() is None
    finally:
        session.close()


def test_concurrent_auto_login_token_can_only_be_rotated_once(
    authenticated_user,
    monkeypatch,
):
    manager, auth_token, _ = authenticated_user
    barrier = Barrier(2)
    original_rotate = manager._rotate_authenticated_session

    def synchronized_rotate(*args, **kwargs):
        barrier.wait(timeout=5)
        return original_rotate(*args, **kwargs)

    monkeypatch.setattr(manager, "_rotate_authenticated_session", synchronized_rotate)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(manager.authenticate_auto_login, "alice", auth_token)
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    assert manager.check_auth_token("alice", auth_token) is False
    assert manager.check_message_token("alice", successful[0]["message_token"])[0] is True


def test_account_reset_invalidates_message_token(authenticated_user):
    manager, _, message_token = authenticated_user

    assert manager.reset_account("AUTH-CODE", "alice-renamed", "new-password")[0] is True
    assert manager.check_message_token("alice", message_token) == (False, None)
    assert manager.check_message_token("alice-renamed", message_token) == (False, None)


def test_legacy_message_token_path_is_expiring_and_session_bound(authenticated_user):
    manager, _, _ = authenticated_user
    session = manager.open_sql_session()
    try:
        token = generate_legacy_message_token(session, "alice")
        claims = jwt.get_unverified_claims(token)
        assert {"iat", "exp", "jti", "session_fp"} <= claims.keys()
        assert check_legacy_message_token(session, "alice", token)[0] is True
    finally:
        session.close()

    manager.update_auth_token("alice")
    session = manager.open_sql_session()
    try:
        assert check_legacy_message_token(session, "alice", token) == (False, None)
    finally:
        session.close()
