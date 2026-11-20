"""协议表对冻结历史数据库的增量迁移保证。"""

from sqlalchemy import create_engine, inspect

from src.infrastructure.persistence.database import sql_database
from src.infrastructure.persistence.database.sql_database import (
    AgreementSignature,
    AgreementVersion,
    InviteCode,
    User,
)

# 从冻结基线 1d8d2fee 的 sql_database.py（`git show 1d8d2fee:...`）提取。
# 此处刻意不使用当前 Base.metadata 排除协议表来伪造旧库，避免当前模型的后续
# 字段变更掩盖迁移兼容性问题。
FROZEN_BASELINE_COMMIT = "1d8d2fee"
FROZEN_LEGACY_DDL = """
CREATE TABLE users (
    uuid VARCHAR NOT NULL PRIMARY KEY,
    username VARCHAR NOT NULL UNIQUE,
    password VARCHAR NOT NULL,
    created_at DATETIME,
    last_login DATETIME,
    nickname VARCHAR,
    description TEXT,
    context_summary TEXT,
    context_memory_count INTEGER,
    all_memory_count INTEGER,
    auth_token VARCHAR,
    preferences TEXT,
    affection_score INTEGER,
    affection_total_gained INTEGER
);
CREATE INDEX ix_users_username ON users (username);
CREATE TABLE invite_codes (
    code VARCHAR NOT NULL PRIMARY KEY,
    is_used BOOLEAN,
    disabled BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME,
    used_at DATETIME,
    user_id VARCHAR UNIQUE,
    FOREIGN KEY(user_id) REFERENCES users (uuid)
);
"""


def test_old_database_gains_agreement_tables_without_altering_existing_account_data(tmp_path):
    database_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{database_path}")
    raw_connection = legacy_engine.raw_connection()
    try:
        raw_connection.executescript(FROZEN_LEGACY_DDL)
        raw_connection.commit()
    finally:
        raw_connection.close()
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (uuid, username, password, nickname) VALUES (?, ?, ?, ?)",
            ("legacy-user", "legacy", "legacy-password", "你"),
        )
        connection.exec_driver_sql(
            "INSERT INTO invite_codes (code, is_used, disabled, user_id) VALUES (?, ?, ?, ?)",
            ("LEGACY-INVITE", True, False, "legacy-user"),
        )
    legacy_engine.dispose()

    sql_database.init_sql_db(str(tmp_path), "legacy.db")
    session = sql_database.SessionLocal()
    try:
        user = session.query(User).filter_by(uuid="legacy-user").one()
        invite = session.query(InviteCode).filter_by(code="LEGACY-INVITE").one()
        assert (user.username, user.password) == ("legacy", "legacy-password")
        assert (invite.is_used, invite.disabled, invite.user_id) == (True, False, "legacy-user")
        assert session.query(AgreementVersion).count() == 0
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()
        sql_database.engine.dispose()

    inspection_engine = create_engine(f"sqlite:///{database_path}")
    try:
        tables = set(inspect(inspection_engine).get_table_names())
    finally:
        inspection_engine.dispose()
    assert {"agreement_versions", "agreement_signatures", "registration_requests"} <= tables

    # 第二次启动只重复执行幂等 create_all / 增量迁移，不改写历史账号数据。
    sql_database.init_sql_db(str(tmp_path), "legacy.db")
    session = sql_database.SessionLocal()
    try:
        assert session.query(User).filter_by(uuid="legacy-user").one().password == "legacy-password"
        assert session.query(InviteCode).filter_by(code="LEGACY-INVITE").one().user_id == "legacy-user"
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()
        sql_database.engine.dispose()
