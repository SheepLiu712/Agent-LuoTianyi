"""未决注册请求记录：只存请求 ID 与用户名，且同一提交必须复用同一 ID。"""

import json
import os

from src.utils import registration_resume


def test_request_id_is_not_reused_without_explicit_resume(monkeypatch, tmp_path):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )

    first = registration_resume.request_id_for("newbie")
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("newbie") != first


def test_request_id_is_reused_only_for_explicit_resume(monkeypatch, tmp_path):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )

    first = registration_resume.request_id_for("newbie")
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("newbie", resume_pending=True) == first
    assert (
        registration_resume.request_id_for("someone-else", resume_pending=True) != first
    )


def test_request_id_changes_when_username_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )
    first = registration_resume.request_id_for("newbie")
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("someone-else") != first


def test_pending_record_keeps_request_id_username_and_version_without_secrets(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )

    registration_resume.save_pending("req-1", "newbie", "terms-v1")

    on_disk = json.loads(
        (tmp_path / registration_resume.FILENAME).read_text(encoding="utf-8")
    )
    assert on_disk == {
        "registration_request_id": "req-1",
        "username": "newbie",
        "agreement_version": "terms-v1",
        "server_url": "",
    }
    assert registration_resume.load_pending()["agreement_version"] == "terms-v1"
    assert registration_resume.load_pending()["confirmation_required"] == ""
    assert "password" not in json.dumps(on_disk)
    assert "invite" not in json.dumps(on_disk)


def test_clear_pending_removes_the_record(monkeypatch, tmp_path):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )
    registration_resume.save_pending("req-1", "newbie")

    registration_resume.clear_pending()

    assert registration_resume.load_pending() is None
    registration_resume.clear_pending()  # 再次清除不应抛错


def test_missing_or_corrupt_record_reads_as_no_pending(monkeypatch, tmp_path):
    target = tmp_path / registration_resume.FILENAME
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(target)
    )

    assert registration_resume.load_pending() is None

    target.write_text("{not json", encoding="utf-8")
    assert registration_resume.load_pending() is None

    target.write_text(json.dumps({"username": "newbie"}), encoding="utf-8")
    assert registration_resume.load_pending() is None


def test_record_is_written_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )

    registration_resume.save_pending("req-1", "newbie")

    assert not os.path.exists(str(tmp_path / f"{registration_resume.FILENAME}.tmp"))


def test_confirmation_required_is_optional_and_preserved_by_resubmission(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )
    registration_resume.save_pending(
        "req-1",
        "newbie",
        "terms-v1",
        "https://example.invalid",
        confirmation_required="same_user_login",
    )
    registration_resume.save_pending(
        "req-1", "newbie", "terms-v1", "https://example.invalid"
    )
    loaded = registration_resume.load_pending()
    assert loaded["confirmation_required"] == "same_user_login"
    raw = (tmp_path / registration_resume.FILENAME).read_text(encoding="utf-8")
    assert "password" not in raw and "invite" not in raw


def test_confirmation_required_is_not_inherited_by_a_different_request_id(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )
    registration_resume.save_pending(
        "req-old",
        "newbie",
        "terms-v1",
        "https://example.invalid",
        confirmation_required="same_user_login",
    )
    registration_resume.save_pending(
        "req-new", "newbie", "terms-v2", "https://example.invalid"
    )
    assert registration_resume.load_pending()["confirmation_required"] == ""
