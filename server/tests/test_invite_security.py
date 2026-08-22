import asyncio
import inspect as pyinspect
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect as sa_inspect

from src.system.admin import admin_interface
from src.system.database import sql_database
from src.system.database.database_service import DatabaseManager
from src.system.database.services import credential_service
from src.system.database.services.credential_service import CredentialService
from src.system.database.sql_database import InviteCode


@pytest.fixture
def db_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "invite-security-test-secret")
    monkeypatch.setattr(credential_service, "_hash_password", lambda password: f"hash:{password}")
    return DatabaseManager(
        {
            "sql_db_folder": str(tmp_path / "db"),
            "sql_db_file": "invite-security.db",
        }
    )


def add_invite(manager: DatabaseManager, code: str, *, disabled: bool = False) -> None:
    session = manager.open_sql_session()
    try:
        session.add(InviteCode(code=code, is_used=False, disabled=disabled))
        session.commit()
    finally:
        session.close()


def test_registration_and_reset_enforce_enabled_and_usage_states(db_manager):
    enabled_code = "ENABLED-INVITE"
    disabled_code = "DISABLED-INVITE"
    unused_reset_code = "UNUSED-RESET-INVITE"
    add_invite(db_manager, enabled_code)
    add_invite(db_manager, disabled_code, disabled=True)
    add_invite(db_manager, unused_reset_code)

    assert db_manager.credential_service.register_user("missing", "password", "NOT-FOUND")[0] is False
    assert db_manager.credential_service.register_user("blocked", "password", disabled_code)[0] is False
    assert db_manager.credential_service.register_user("owner", "password", enabled_code) == (True, "注册成功")
    assert db_manager.credential_service.register_user("second", "password", enabled_code)[0] is False

    session = db_manager.open_sql_session()
    try:
        claimed = session.query(InviteCode).filter_by(code=enabled_code).one()
        assert claimed.is_used is True
        assert claimed.disabled is False
    finally:
        session.close()

    assert db_manager.credential_service.reset_account("NOT-FOUND", "missing", "new-password")[0] is False
    assert db_manager.credential_service.reset_account(unused_reset_code, "unused", "new-password")[0] is False
    assert db_manager.credential_service.reset_account(enabled_code, "owner-renamed", "new-password") == (True, "重置成功")

    assert db_manager.credential_service.admin_set_invite_code_disabled(enabled_code, True) == (True, "已禁用")
    assert db_manager.credential_service.reset_account(enabled_code, "blocked-reset", "new-password")[0] is False


def test_generation_uses_ten_character_uppercase_alphanumeric_codes(db_manager):
    ok, codes = db_manager.credential_service.admin_generate_invite_codes(count=3)

    assert ok is True
    assert len(codes) == 3
    assert len(set(codes)) == 3
    assert all(len(code) == 10 and code.isascii() and code.isalnum() and code == code.upper() for code in codes)
    source = pyinspect.getsource(CredentialService.admin_generate_invite_codes)
    assert "_generate_invite_code()" in source
    assert "begin_nested" in source
    assert "db.flush()" in source

    primary_key = sa_inspect(sql_database.engine).get_pk_constraint("invite_codes")
    assert primary_key["constrained_columns"] == ["code"]


def test_database_collision_is_retried_without_preloading_codes(db_manager, monkeypatch):
    add_invite(db_manager, "database-owned-collision")
    candidates = iter([
        "database-owned-collision",
        "database-owned-collision",
        "fresh-secure-token",
    ])
    calls = []

    def fake_generate_invite_code() -> str:
        calls.append(True)
        return next(candidates)

    monkeypatch.setattr(credential_service, "_generate_invite_code", fake_generate_invite_code)

    ok, codes = db_manager.credential_service.admin_generate_invite_codes(count=1)

    assert ok is True
    assert codes == ["fresh-secure-token"]
    assert calls == [True, True, True]


def test_collision_retry_limit_rolls_back_whole_batch(db_manager, monkeypatch):
    add_invite(db_manager, "always-collides")
    candidates = iter(["first-batch-token"] + ["always-collides"] * 8)
    calls = []

    def fake_generate_invite_code() -> str:
        calls.append(True)
        return next(candidates)

    monkeypatch.setattr(credential_service, "_generate_invite_code", fake_generate_invite_code)

    ok, message = db_manager.credential_service.admin_generate_invite_codes(count=2)

    assert ok is False
    assert message == "生成失败，请重试"
    assert calls == [True] * 9
    session = db_manager.open_sql_session()
    try:
        assert session.query(InviteCode).filter_by(code="first-batch-token").first() is None
    finally:
        session.close()


def test_concurrent_generation_relies_on_unique_constraint(db_manager, monkeypatch):
    barrier = Barrier(2)
    calls_by_thread = {}
    calls_lock = Lock()

    def colliding_then_unique() -> str:
        thread_id = threading.get_ident()
        with calls_lock:
            call_number = calls_by_thread.get(thread_id, 0)
            calls_by_thread[thread_id] = call_number + 1
        if call_number == 0:
            barrier.wait(timeout=5)
            return "shared-concurrent-token"
        return f"fallback-{thread_id}"

    monkeypatch.setattr(credential_service, "_generate_invite_code", colliding_then_unique)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: db_manager.credential_service.admin_generate_invite_codes(), range(2)))

    assert all(ok for ok, _ in results)
    generated = [codes[0] for _, codes in results]
    assert len(set(generated)) == 2
    session = db_manager.open_sql_session()
    try:
        assert session.query(InviteCode).filter(InviteCode.code.in_(generated)).count() == 2
    finally:
        session.close()


def test_setting_disabled_is_reversible_idempotent_and_never_logs_code(db_manager, caplog):
    unused_code = "DO-NOT-LOG-UNUSED-INVITE"
    used_code = "DO-NOT-LOG-USED-INVITE"
    available_code = "DO-NOT-LOG-AVAILABLE-INVITE"
    add_invite(db_manager, unused_code)
    add_invite(db_manager, used_code)
    add_invite(db_manager, available_code)
    assert db_manager.credential_service.register_user("invite-owner", "password", used_code)[0] is True

    session = db_manager.open_sql_session()
    try:
        registered_code = session.query(InviteCode).filter_by(code=used_code).one()
        assert registered_code.is_used is True
        assert registered_code.disabled is False
    finally:
        session.close()

    caplog.set_level(logging.INFO)
    assert db_manager.credential_service.admin_set_invite_code_disabled(unused_code, True) == (True, "已禁用")
    assert db_manager.credential_service.admin_set_invite_code_disabled(unused_code, True) == (True, "已禁用")
    assert db_manager.credential_service.admin_set_invite_code_disabled(unused_code, False) == (True, "已启用")
    assert db_manager.credential_service.admin_set_invite_code_disabled(unused_code, False) == (True, "已启用")
    assert db_manager.credential_service.admin_set_invite_code_disabled(used_code, True) == (True, "已禁用")

    assert db_manager.credential_service.register_user("re-enabled-user", "password", unused_code)[0] is True
    rows_before_disable = db_manager.credential_service.admin_list_invite_codes()["items"]
    row_by_code_before_disable = {row["code"]: row for row in rows_before_disable}
    assert row_by_code_before_disable[available_code]["can_use"] is True
    assert db_manager.credential_service.admin_set_invite_code_disabled(available_code, True) == (True, "已禁用")
    assert db_manager.credential_service.register_user("blocked-user", "password", available_code)[0] is False
    assert db_manager.credential_service.reset_account(used_code, "renamed-owner", "new-password")[0] is False
    assert db_manager.credential_service.admin_delete_invite_code(unused_code)[0] is False
    assert hasattr(db_manager.credential_service, "admin_set_invite_code_disabled")

    rows = db_manager.credential_service.admin_list_invite_codes()["items"]
    row_by_code = {row["code"]: row for row in rows}
    assert row_by_code[used_code]["is_used"] is True
    assert row_by_code[used_code]["username"] == "invite-owner"
    assert row_by_code[used_code]["can_use"] is False
    assert row_by_code[available_code]["can_use"] is False

    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert unused_code not in rendered_logs
    assert used_code not in rendered_logs
    assert available_code not in rendered_logs


def test_existing_invite_migration_enables_once_and_preserves_later_admin_state(tmp_path):
    db_dir = tmp_path / "legacy"
    db_dir.mkdir()
    db_path = db_dir / "legacy.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE invite_codes (
                code VARCHAR NOT NULL PRIMARY KEY,
                is_used BOOLEAN,
                created_at DATETIME,
                used_at DATETIME,
                user_id VARCHAR UNIQUE
            );
            INSERT INTO invite_codes (code, is_used) VALUES ('legacy-code', 0);
            """
        )
        connection.commit()
    finally:
        connection.close()

    sql_database.init_sql_db(str(db_dir), db_path.name)
    session = sql_database.SessionLocal()
    try:
        assert session.query(InviteCode).filter_by(code="legacy-code").one().disabled is False
        session.add(InviteCode(code="post-migration-code", disabled=True))
        session.commit()
    finally:
        session.close()
    sql_database.engine.dispose()

    sql_database.init_sql_db(str(db_dir), db_path.name)
    session = sql_database.SessionLocal()
    try:
        assert session.query(InviteCode).filter_by(code="legacy-code").one().disabled is False
        assert session.query(InviteCode).filter_by(code="post-migration-code").one().disabled is True
        marker_count = session.execute(
            sql_database.text(
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE name = '2026-08-22-enable-all-invite-codes'"
            )
        ).scalar_one()
        assert marker_count == 1
    finally:
        session.close()
        sql_database.engine.dispose()


def test_admin_invite_routes_keep_codes_in_request_bodies(monkeypatch):
    secret_code = "BODY-ONLY-SECRET-INVITE"
    calls = []

    class FakeDatabaseManager:
        def __init__(self):
            self.credential_service = self

        def admin_disable_invite_code(self, code: str):
            calls.append(("disable", code))
            return True, "已禁用"

        def admin_set_invite_code_disabled(self, code: str, disabled: bool):
            calls.append(("set-disabled", code, disabled))
            return True, "已禁用" if disabled else "已启用"

        def admin_delete_invite_code(self, code: str):
            calls.append(("delete", code))
            return True, "删除成功"

    shell = SimpleNamespace(
        runtime_supervisor=SimpleNamespace(
            runtime=SimpleNamespace(database_manager=FakeDatabaseManager())
        )
    )
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: shell)

    assert asyncio.run(admin_interface.admin_disable_invite_code({"code": secret_code}))["ok"] is True
    assert asyncio.run(admin_interface.admin_set_invite_code_disabled({"code": secret_code, "disabled": False}))["ok"] is True
    assert asyncio.run(admin_interface.admin_delete_invite_code({"code": secret_code}))["ok"] is True
    assert calls == [("disable", secret_code), ("set-disabled", secret_code, False), ("delete", secret_code)]

    invite_routes = [
        route
        for route in admin_interface.protected_router.routes
        if "invite-codes" in getattr(route, "path", "")
    ]
    route_paths = {route.path for route in invite_routes}
    assert route_paths == {
        "/invite-codes/query",
        "/invite-codes/generate",
        "/invite-codes/disable",
        "/invite-codes/set-disabled",
        "/invite-codes/delete",
    }
    assert all("{code}" not in route.path for route in invite_routes)
    assert all("GET" not in (route.methods or set()) for route in invite_routes)

    source = (Path(__file__).parents[1] / "res" / "admin_ui" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "encodeURIComponent(row.code)" not in source
    assert "/admin/api/invite-codes?" not in source
    assert "'/admin/api/invite-codes/set-disabled'," in source
    assert "'/admin/api/invite-codes/delete'," in source
