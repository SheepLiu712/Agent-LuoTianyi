"""未决注册请求记录：只存请求 ID 与用户名，且同一提交必须复用同一 ID。"""

import json
import os

from src.utils import registration_resume


def test_request_id_is_reused_for_same_username(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))

    first = registration_resume.request_id_for("newbie")
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("newbie") == first


def test_request_id_changes_when_username_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    first = registration_resume.request_id_for("newbie")
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("someone-else") != first


def test_pending_record_only_keeps_request_id_and_username(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))

    registration_resume.save_pending("req-1", "newbie")

    on_disk = json.loads((tmp_path / registration_resume.FILENAME).read_text(encoding="utf-8"))
    assert on_disk == {"registration_request_id": "req-1", "username": "newbie"}
    assert "password" not in json.dumps(on_disk)


def test_clear_pending_removes_the_record(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    registration_resume.save_pending("req-1", "newbie")

    registration_resume.clear_pending()

    assert registration_resume.load_pending() is None
    registration_resume.clear_pending()  # 再次清除不应抛错


def test_missing_or_corrupt_record_reads_as_no_pending(monkeypatch, tmp_path):
    target = tmp_path / registration_resume.FILENAME
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(target))

    assert registration_resume.load_pending() is None

    target.write_text("{not json", encoding="utf-8")
    assert registration_resume.load_pending() is None

    target.write_text(json.dumps({"username": "newbie"}), encoding="utf-8")
    assert registration_resume.load_pending() is None


def test_record_is_written_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))

    registration_resume.save_pending("req-1", "newbie")

    assert not os.path.exists(str(tmp_path / f"{registration_resume.FILENAME}.tmp"))
