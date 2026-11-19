"""旧图片只经本人 SQL 和固定旧目录迁移，归档路径不成为服务器读指令。"""

import json
from uuid import uuid4

import pytest
from integration.application import test_user_data_transfer as shared
from PIL import Image

from src.infrastructure.data_transfer import decode_import, encode_archive
from src.infrastructure.media.legacy_image import LegacyImageReader
from src.infrastructure.persistence.database.sql_database import Conversation

transfer = shared.transfer


def _configure(state, root):
    state.service._projections._legacy_image_reader = LegacyImageReader(state.history, root, state.media.max_bytes)
    state.service._projections._link_legacy_image = state.repository.link_legacy_image


def _seed(state, path, owner="alice"):
    identity = str(uuid4())
    with state.sessions() as db:
        db.add(
            Conversation(
                uuid=identity,
                user_id=owner,
                character_id="luotianyi",
                source="user",
                type="image",
                content="legacy image",
                meta_data=json.dumps({"image_server_path": str(path)}),
            )
        )
        db.commit()
    return identity


def _image(state, owner, identity):
    return state.client.post(
        "/get_image",
        json={"username": owner, "token": state.credentials.generate_message_token(owner), "uuid": identity},
    )


def test_owned_legacy_image_exports_restores_and_returns_without_duplicates(transfer, tmp_path):
    root = tmp_path / "legacy-images"
    path = root / "alice" / "image.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), "blue").save(path)
    identity = _seed(transfer, path)
    _configure(transfer, root)
    original = _image(transfer, "alice", identity)
    assert original.status_code == 200
    response = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("alice"))
    assert response.status_code == 200, response.text
    payload, files = decode_import(response.content)
    assert len(files) == 1 and payload["warnings"] == []
    assert "image_server_path" not in payload["conversations"][0]["meta_data"]
    assert payload["conversations"][0]["meta_data"]["media_id"]
    assert _image(transfer, "alice", identity).content == original.content
    result = shared.commit(transfer, shared.preview(transfer, response.content)).json()
    assert result["success"], result
    with transfer.sessions() as db:
        restored = db.query(Conversation).filter_by(user_id="bob", type="image").one().uuid
    assert _image(transfer, "bob", restored).content == original.content
    returned = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("bob")).content
    merged = shared.commit(transfer, shared.preview(transfer, returned, user="alice"), user="alice").json()
    assert merged["success"] and merged["imported"]["conversations"] == 0
    assert transfer.history.get_total_conversation_count("alice") == 1
    # 补正本后再次导出已有 modern media_id，也不能重新捎带旧路径。
    again = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("alice"))
    repeated, _ = decode_import(again.content)
    assert "image_server_path" not in repeated["conversations"][0]["meta_data"]
    assert "image_client_path" not in repeated["conversations"][0]["meta_data"]


@pytest.mark.parametrize("location", ["another-owner", "outside-root", "missing"])
def test_untrusted_or_missing_legacy_images_warn_without_opening_other_files(transfer, tmp_path, location):
    root = tmp_path / "legacy-images"
    path = root / "bob" / "other.png" if location == "another-owner" else tmp_path / "outside.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if location != "missing":
        Image.new("RGB", (2, 2), "blue").save(path)
    _seed(transfer, path)
    _configure(transfer, root)
    response = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("alice"))
    assert response.status_code == 200
    payload, files = decode_import(response.content)
    assert files == {} and payload["warnings"]
    assert "media_id" not in payload["conversations"][0]["meta_data"]
    assert "image_server_path" not in payload["conversations"][0]["meta_data"]
    assert "image_client_path" not in payload["conversations"][0]["meta_data"]


def test_uploaded_path_does_not_enable_legacy_file_reading(transfer, tmp_path):
    root = tmp_path / "legacy-images"
    path = root / "bob" / "private.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), "green").save(path)
    _seed(transfer, tmp_path / "missing.png")
    _configure(transfer, root)
    exported = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("alice")).content
    payload, files = decode_import(exported)
    payload["conversations"][0]["meta_data"]["image_server_path"] = str(path)
    result = shared.commit(transfer, shared.preview(transfer, encode_archive(payload, files))).json()
    assert result["success"]
    response = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("bob"))
    restored, restored_files = decode_import(response.content)
    assert restored_files == {} and restored["warnings"]
    assert "image_server_path" not in restored["conversations"][0]["meta_data"]


def test_legacy_link_failure_removes_only_newly_created_media(transfer, tmp_path, monkeypatch):
    root = tmp_path / "legacy-images"
    path = root / "alice" / "image.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), "blue").save(path)
    identity = _seed(transfer, path)
    _configure(transfer, root)

    def fail(*args):
        raise OSError("synthetic legacy SQL link failure")

    monkeypatch.setattr(transfer.service._projections, "_link_legacy_image", fail)
    response = transfer.client.get("/user/data/export?scope=chat", headers=transfer.headers("alice"))
    assert response.status_code == 503
    assert _image(transfer, "alice", identity).status_code == 200
    assert list(transfer.media._root.iterdir()) == []
