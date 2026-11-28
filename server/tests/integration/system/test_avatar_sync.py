"""Issue #465: exercise the HTTP contract with real account sessions and SQLite."""

import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event

from src.infrastructure.media import create_media_resolver
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import ChatAvatar, InviteCode, User
from src.web.http.routes import get_runtime, router
from src.web.http.user_interface import UserInterface


def _image(format="PNG", color="red"):
    output = BytesIO()
    Image.new("RGB", (512, 300), color).save(output, format=format)
    mime = "jpeg" if format == "JPEG" else "png"
    return f"data:image/{mime};base64," + base64.b64encode(output.getvalue()).decode()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def avatars(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "avatar-sync-test-secret")
    config = {"sql_db_folder": str(tmp_path), "sql_db_file": "avatars.db"}
    database = DatabaseManager(config)
    with database.open_sql_session() as session:
        session.add_all([User(username=name, password="password") for name in ("alice", "bob")])
        session.commit()
    auth = database.credential_service.authenticate_password_login("alice", "password")
    runtime = SimpleNamespace(user_interface=UserInterface(database, create_media_resolver()))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, database, auth, config, runtime


def test_two_devices_edit_independently_reset_and_reload(avatars):
    client, database, first_login, config, runtime = avatars
    first = client.get("/avatars?username=alice", headers=_headers(first_login["message_token"]))
    assert first.status_code == 200
    assert first.json()["user"] is None and first.json()["agent"] is None
    desktop_token = first.json()["sync_token"]

    android_login = database.credential_service.authenticate_password_login("alice", "password")
    assert database.credential_service.check_message_token("alice", first_login["message_token"]) == (False, None)
    android = client.put(
        "/avatars/agent?username=alice",
        headers=_headers(android_login["message_token"]),
        json={"image": _image("JPEG")},
    )
    assert android.status_code == 200
    agent_image = android.json()["agent"]
    desktop = client.put(
        "/avatars/user?username=alice", headers=_headers(desktop_token), json={"image": _image(color="blue")}
    )
    assert desktop.status_code == 200
    assert desktop.json()["agent"] == agent_image
    user_image = desktop.json()["user"]
    with Image.open(BytesIO(base64.b64decode(user_image.split(",")[1]))) as image:
        assert image.size == (256, 150)
    android_token = android.json()["sync_token"]
    synced = client.get("/avatars?username=alice", headers=_headers(android_token))
    assert synced.json()["user"] == user_image

    reset = client.put("/avatars/user?username=alice", headers=_headers(android_token), json={"image": None})
    assert reset.status_code == 200
    runtime.user_interface = UserInterface(DatabaseManager(config), create_media_resolver())
    reloaded = client.get("/avatars?username=alice", headers=_headers(desktop_token))
    assert reloaded.json()["user"] is None
    assert reloaded.json()["agent"] == agent_image
    unchanged = client.get(
        "/avatars?username=alice",
        headers={**_headers(desktop_token), "If-None-Match": reloaded.headers["etag"]},
    )
    assert unchanged.status_code == 304 and unchanged.content == b""
    assert unchanged.headers["x-avatar-token"]


def test_avatar_credentials_are_account_scoped_and_password_reset_revokes_them(avatars):
    client, database, login, _, _ = avatars
    token = client.get("/avatars?username=alice", headers=_headers(login["message_token"])).json()["sync_token"]
    assert client.get("/avatars?username=bob", headers=_headers(token)).status_code == 401
    assert database.credential_service.check_message_token("alice", token) == (False, None)
    bob_login = database.credential_service.authenticate_password_login("bob", "password")
    bob = client.get("/avatars?username=bob", headers=_headers(bob_login["message_token"]))
    assert bob.json()["user"] is None and bob.json()["agent"] is None
    with database.open_sql_session() as session:
        user = session.query(User).filter_by(username="alice").one()
        user.password = "a-new-password-hash"
        session.commit()
    assert client.get("/avatars?username=alice", headers=_headers(token)).status_code == 401


def test_password_reset_during_avatar_authentication_cannot_upgrade_old_session(avatars):
    client, database, login, _, _ = avatars
    credentials = database.credential_service
    with database.open_sql_session() as session:
        user = session.query(User).filter_by(username="alice").one()
        session.add(InviteCode(code="reset-during-avatar-sync", is_used=True, user_id=user.uuid))
        session.commit()
    reset_done = False

    def reset_after_account_read(user, _context):
        nonlocal reset_done
        if reset_done or user.username != "alice":
            return
        reset_done = True
        assert credentials.reset_account("reset-during-avatar-sync", "alice", "new-password")[0]

    # Freeze the account read used by authentication, then reset it before token issuance.
    event.listen(User, "load", reset_after_account_read)
    try:
        response = client.get("/avatars?username=alice", headers=_headers(login["message_token"]))
    finally:
        event.remove(User, "load", reset_after_account_read)
    assert reset_done
    assert credentials.check_message_token("alice", login["message_token"]) == (False, None)
    assert response.status_code in (200, 401)
    if response.status_code == 200:
        issued = response.json()["sync_token"]
        assert client.get("/avatars?username=alice", headers=_headers(issued)).status_code == 401


def test_existing_database_gains_avatar_storage_without_losing_accounts(avatars):
    client, database, login, config, runtime = avatars
    with database.open_sql_session() as session:
        ChatAvatar.__table__.drop(bind=session.get_bind())
    runtime.user_interface = UserInterface(DatabaseManager(config), create_media_resolver())
    response = client.put(
        "/avatars/user?username=alice", headers=_headers(login["message_token"]), json={"image": _image()}
    )
    assert response.status_code == 200
    assert response.json()["user"].startswith("data:image/png;base64,")


def test_bad_image_is_rejected_without_overwriting_saved_avatar(avatars):
    client, _, login, _, _ = avatars
    headers = _headers(login["message_token"])
    saved = client.put("/avatars/user?username=alice", headers=headers, json={"image": _image()}).json()
    rejected = client.put(
        "/avatars/user?username=alice", headers=headers, json={"image": "data:image/png;base64,bm90IGFuIGltYWdl"}
    )
    assert rejected.status_code == 422
    current = client.get("/avatars?username=alice", headers=headers).json()
    assert current["user"] == saved["user"] and current["revision"] == saved["revision"]
    assert client.put("/avatars/other?username=alice", headers=headers, json={"image": None}).status_code == 422
    assert client.get("/avatars?username=alice").status_code == 401
