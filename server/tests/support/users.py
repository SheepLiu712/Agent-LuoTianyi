"""Authenticated test users for features that do not exercise password login."""

from uuid import uuid4

from src.infrastructure.persistence.database.sql_database import User


def seed_authenticated_user(manager, username: str) -> dict:
    user_id, login_token = str(uuid4()), str(uuid4())
    with manager.open_sql_session() as session:
        session.add(
            User(
                uuid=user_id,
                username=username,
                password="not-used-by-this-test",
                auth_token=login_token,
            )
        )
        session.commit()
    token = manager.credential_service.generate_message_token(
        username, expected_auth_token=login_token
    )
    assert token is not None
    return {"user_uuid": user_id, "login_token": login_token, "message_token": token}
