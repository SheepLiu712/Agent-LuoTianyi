"""Unversioned users table from before the call-session migration."""


def create_legacy_users(connection):
    connection.executescript("""
        CREATE TABLE users (
            uuid VARCHAR NOT NULL PRIMARY KEY, username VARCHAR NOT NULL, password VARCHAR NOT NULL,
            created_at DATETIME, last_login DATETIME, nickname VARCHAR, description TEXT,
            context_summary TEXT, context_memory_count INTEGER, all_memory_count INTEGER,
            auth_token VARCHAR, preferences TEXT, affection_score INTEGER, affection_total_gained INTEGER
        );
        CREATE UNIQUE INDEX ix_users_username ON users (username);
        INSERT INTO users (uuid, username, password) VALUES ('user', 'existing user', 'unused');
        """)
