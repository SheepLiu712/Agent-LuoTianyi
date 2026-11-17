"""HTTP media queries use constructor dependencies without navigating a runtime container."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.media import MediaResolutionError, ResolvedMedia
from src.web.http import routes
from src.web.http.user_interface import UserInterface


@pytest.fixture
def media_http(tmp_path):
    legacy = tmp_path / "old.jpg"
    legacy.write_bytes(b"legacy-image")
    items = [
        SimpleNamespace(
            uuid="audio",
            content="private transcript",
            source="user",
            timestamp=1,
            type="audio",
            data={"media_id": "sound", "duration_ms": 1000},
        )
    ]
    credentials = SimpleNamespace(
        authenticate_message_token=lambda token: {"alice-token": "alice", "bob-token": "bob"}.get(token),
        check_message_token=lambda username, token: (username == "alice" and token == "alice-token", "alice"),
    )
    conversations = SimpleNamespace(
        get_audio_media_id=lambda owner, uuid: {("alice", "audio"): "sound", ("alice", "deleted"): "deleted"}.get(
            (owner, uuid)
        ),
        get_image_media_id=lambda owner, uuid: "picture" if (owner, uuid) == ("alice", "image") else None,
        get_image_server_path=lambda owner, uuid: str(legacy) if (owner, uuid) == ("alice", "legacy") else None,
        get_total_conversation_count=lambda owner: len(items),
        get_history_from_db=lambda owner, start, end: items[start:end],
    )
    calls = []

    class Resolver:
        def resolve(self, ref, *, owner_user_id, expected_kind=None):
            calls.append((ref.media_id, owner_user_id, expected_kind))
            assert owner_user_id == "alice"
            if ref.media_id == "deleted":
                raise MediaResolutionError("MEDIA_UNKNOWN", ref.media_id)
            if ref.media_id == "sound":
                assert expected_kind == "audio"
                return ResolvedMedia(b"audio-bytes", "audio/mp4")
            return ResolvedMedia(b"image-bytes", "image/png")

    database = SimpleNamespace(credential_service=credentials, conversation_service=conversations)
    resolver = Resolver()
    ui = UserInterface(database, resolver)
    app = FastAPI()
    app.include_router(routes.router)
    # The route can obtain the interface, but no database/media attributes exist on this container.
    app.dependency_overrides[routes.get_runtime] = lambda: SimpleNamespace(user_interface=ui)
    with TestClient(app) as client:
        yield client, ui, database, resolver, calls


def test_audio_download_uses_authenticated_owner_and_injected_resolver(media_http):
    client, _, _, _, calls = media_http
    response = client.get("/media/audio/audio", headers={"Authorization": "Bearer alice-token"})
    assert response.status_code == 200
    assert response.content == b"audio-bytes"
    assert response.headers["content-type"] == "audio/mp4"
    assert calls == [("sound", "alice", "audio")]


@pytest.mark.parametrize("token,uuid", [("bob-token", "audio"), ("alice-token", "unknown"), ("alice-token", "deleted")])
def test_audio_unavailable_responses_do_not_disclose_ownership(media_http, token, uuid):
    client, _, _, _, _ = media_http
    response = client.get(f"/media/audio/{uuid}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
    assert response.json() == {"detail": "音频不存在或无权限访问"}


def test_audio_invalid_credentials_never_reach_resolver(media_http):
    client, _, _, _, calls = media_http
    response = client.get("/media/audio/audio", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert calls == []


def test_repeated_history_uses_same_helper_and_hides_understanding_text(media_http):
    client, ui, database, resolver, calls = media_http
    helper = ui.user_conversation_helper
    for _ in range(2):
        response = client.get("/history", params={"username": "alice"}, headers={"Authorization": "Bearer alice-token"})
        assert response.status_code == 200
        entry = response.json()["history"][0]
        assert entry["content"] == "[语音消息]"
        assert entry["audio_available"] is True
        assert entry["duration_ms"] == 1000
        assert "private transcript" not in response.text
        assert ui.user_conversation_helper is helper
        assert helper.database_manager is database
        assert helper.media_resolver is resolver
    assert len(calls) == 2


@pytest.mark.parametrize(
    "uuid,content,mime", [("image", b"image-bytes", "image/png"), ("legacy", b"legacy-image", "image/jpeg")]
)
def test_image_download_preserves_permanent_and_legacy_paths(media_http, uuid, content, mime):
    client, _, _, _, _ = media_http
    response = client.post("/get_image", json={"username": "alice", "token": "alice-token", "uuid": uuid})
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == mime


@pytest.mark.parametrize(
    "database,resolver,missing", [(None, object(), "database_manager"), (object(), None, "media_resolver")]
)
def test_missing_constructor_dependencies_fail_before_requests(database, resolver, missing):
    with pytest.raises(RuntimeError, match=missing):
        UserInterface(database, resolver)
