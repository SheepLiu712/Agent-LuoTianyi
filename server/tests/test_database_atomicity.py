from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.system.database import database_service
from src.system.database.database_service import DatabaseManager
from src.system.database.sql_database import InviteCode, User


@pytest.fixture
def db_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "atomicity-test-secret")
    monkeypatch.setattr(database_service, "_hash_password", lambda password: f"hash:{password}")
    return DatabaseManager(
        {
            "sql_db_folder": str(tmp_path / "db"),
            "sql_db_file": "atomicity.db",
        }
    )


def add_invite(manager: DatabaseManager, code: str) -> None:
    session = manager.open_sql_session()
    try:
        session.add(InviteCode(code=code, is_used=False))
        session.commit()
    finally:
        session.close()


def test_flush_then_rollback_does_not_persist_user(db_manager):
    session = db_manager.open_sql_session()
    try:
        session.add(User(uuid="rollback-user-id", username="rollback-user", password="hash"))
        session.flush()
        session.rollback()
    finally:
        session.close()

    session = db_manager.open_sql_session()
    try:
        assert session.query(User).filter_by(username="rollback-user").first() is None
    finally:
        session.close()


def test_concurrent_registration_claims_invite_once(db_manager, monkeypatch):
    add_invite(db_manager, "ONE-TIME-CODE")
    barrier = Barrier(2)

    def synchronized_hash(password: str) -> str:
        barrier.wait(timeout=5)
        return f"hash:{password}"

    monkeypatch.setattr(database_service, "_hash_password", synchronized_hash)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda username: db_manager.register_user(username, "password", "ONE-TIME-CODE"),
                ("alice", "bob"),
            )
        )

    assert sum(ok for ok, _ in results) == 1
    session = db_manager.open_sql_session()
    try:
        users = session.query(User).filter(User.username.in_(["alice", "bob"])).all()
        invite = session.query(InviteCode).filter_by(code="ONE-TIME-CODE").one()
        assert len(users) == 1
        assert invite.is_used is True
        assert invite.user_id == users[0].uuid
    finally:
        session.close()


def test_registration_commit_failure_rolls_back_user_and_invite(db_manager, monkeypatch):
    add_invite(db_manager, "ROLLBACK-CODE")
    real_new_session = db_manager._new_session

    class CommitFailingSession:
        def __init__(self):
            self._session = real_new_session()

        def __getattr__(self, name):
            return getattr(self._session, name)

        def commit(self):
            raise RuntimeError("injected commit failure")

    monkeypatch.setattr(db_manager, "_new_session", CommitFailingSession)
    ok, _ = db_manager.register_user("rollback-register", "password", "ROLLBACK-CODE")

    assert ok is False
    session = real_new_session()
    try:
        assert session.query(User).filter_by(username="rollback-register").first() is None
        invite = session.query(InviteCode).filter_by(code="ROLLBACK-CODE").one()
        assert invite.is_used is False
        assert invite.user_id is None
    finally:
        session.close()


def test_reset_invalidates_old_and_new_username_cache_keys(db_manager):
    add_invite(db_manager, "RESET-CODE")
    assert db_manager.register_user("old-name", "password", "RESET-CODE")[0] is True
    original_uuid = db_manager.get_user_uuid_by_username("old-name")

    assert db_manager.reset_account("RESET-CODE", "new-name", "new-password")[0] is True
    add_invite(db_manager, "REUSE-CODE")
    assert db_manager.register_user("old-name", "other-password", "REUSE-CODE")[0] is True

    reused_uuid = db_manager.get_user_uuid_by_username("old-name")
    assert reused_uuid != original_uuid
    assert db_manager.get_user_uuid_by_username("new-name") == original_uuid


def test_cache_errors_after_commit_do_not_report_false_failure(db_manager, monkeypatch):
    add_invite(db_manager, "CACHE-FAIL-CODE")
    redis = db_manager._ensure_redis()

    def fail_cache_operation(*args, **kwargs):
        raise RuntimeError("injected cache failure")

    monkeypatch.setattr(redis, "setex", fail_cache_operation)
    assert db_manager.register_user("cache-user", "password", "CACHE-FAIL-CODE")[0] is True

    monkeypatch.setattr(redis, "delete", fail_cache_operation)
    assert db_manager.reset_account("CACHE-FAIL-CODE", "cache-user-new", "password")[0] is True

    session = db_manager.open_sql_session()
    try:
        assert session.query(User).filter_by(username="cache-user-new").one()
    finally:
        session.close()
