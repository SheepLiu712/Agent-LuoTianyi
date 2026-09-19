from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.system.database.sql_database import Base, InviteCode, User
from src.system.user_interface import account


@pytest.fixture
def session_factory(tmp_path):
    database_path = tmp_path / "legacy-account.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


def _add_invite(session_factory, code: str, *, disabled: bool = False) -> None:
    session = session_factory()
    try:
        session.add(InviteCode(code=code, is_used=False, disabled=disabled))
        session.commit()
    finally:
        session.close()


def test_legacy_registration_and_reset_respect_manual_disabled_state(session_factory, monkeypatch):
    _add_invite(session_factory, "LEGACY-ENABLED")
    _add_invite(session_factory, "LEGACY-DISABLED", disabled=True)
    monkeypatch.setattr(account, "_hash_password", lambda password: f"hash:{password}")

    session = session_factory()
    try:
        assert account.register_user(session, "blocked", "password", "LEGACY-DISABLED")[0] is False
        assert account.register_user(session, "owner", "password", "LEGACY-ENABLED") == (True, "注册成功")
        claimed = session.query(InviteCode).filter_by(code="LEGACY-ENABLED").one()
        assert claimed.is_used is True
        assert claimed.disabled is False
        assert account.reset_account(session, "LEGACY-ENABLED", "owner-renamed", "new-password") == (True, "重置成功")
        claimed.disabled = True
        session.commit()
        assert account.reset_account(session, "LEGACY-ENABLED", "blocked-reset", "new-password")[0] is False
    finally:
        session.close()


def test_legacy_concurrent_registration_claims_invite_once(session_factory, monkeypatch):
    _add_invite(session_factory, "LEGACY-ONE-TIME")
    barrier = Barrier(2)

    def synchronized_hash(password: str) -> str:
        barrier.wait(timeout=5)
        return f"hash:{password}"

    monkeypatch.setattr(account, "_hash_password", synchronized_hash)

    def register(username: str):
        session = session_factory()
        try:
            return account.register_user(
                session,
                username,
                "password",
                "LEGACY-ONE-TIME",
            )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, ("alice", "bob")))

    assert sum(ok for ok, _ in results) == 1
    session = session_factory()
    try:
        users = session.query(User).filter(User.username.in_(["alice", "bob"])).all()
        invite = session.query(InviteCode).filter_by(code="LEGACY-ONE-TIME").one()
        assert len(users) == 1
        assert invite.is_used is True
        assert invite.user_id == users[0].uuid
    finally:
        session.close()


def test_legacy_registration_commit_failure_rolls_back_user_and_invite(
    session_factory,
    monkeypatch,
):
    _add_invite(session_factory, "LEGACY-ROLLBACK")
    monkeypatch.setattr(account, "_hash_password", lambda password: f"hash:{password}")
    session = session_factory()

    def fail_commit():
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(session, "commit", fail_commit)
    try:
        ok, _ = account.register_user(
            session,
            "rollback-user",
            "password",
            "LEGACY-ROLLBACK",
        )
    finally:
        session.close()

    assert ok is False
    verification_session = session_factory()
    try:
        assert (
            verification_session.query(User)
            .filter_by(username="rollback-user")
            .first()
            is None
        )
        invite = (
            verification_session.query(InviteCode)
            .filter_by(code="LEGACY-ROLLBACK")
            .one()
        )
        assert invite.is_used is False
        assert invite.user_id is None
    finally:
        verification_session.close()


def test_legacy_auth_token_uses_constant_time_comparison(session_factory, monkeypatch):
    session = session_factory()
    session.add(
        User(
            uuid="legacy-token-user",
            username="legacy-user",
            password="hash:password",
            auth_token="stored-token",
        )
    )
    session.commit()
    comparisons = []

    def compare_digest(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return left == right

    monkeypatch.setattr(account.hmac, "compare_digest", compare_digest)
    try:
        assert account.check_auth_token(session, "legacy-user", "stored-token") is True
        assert account.check_auth_token(session, "legacy-user", "wrong-token") is False
    finally:
        session.close()

    assert comparisons == [
        ("stored-token", "stored-token"),
        ("stored-token", "wrong-token"),
    ]
