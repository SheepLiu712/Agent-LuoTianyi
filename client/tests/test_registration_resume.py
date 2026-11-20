"""未决注册请求记录：只存请求 ID 与用户名，且同一提交必须复用同一 ID。"""

import json
import os
import subprocess
import sys
from pathlib import Path

from src.utils import registration_resume


def test_request_id_is_not_reused_without_explicit_resume(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))

    first = registration_resume.request_id_for("newbie", resume_pending=True)
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("newbie") != first


def test_request_id_is_reused_only_for_explicit_resume(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))

    first = registration_resume.request_id_for("newbie", resume_pending=True)
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("newbie", resume_pending=True) == first
    assert registration_resume.request_id_for("someone-else", resume_pending=True) != first


def test_request_id_changes_when_username_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    first = registration_resume.request_id_for("newbie", resume_pending=True)
    registration_resume.save_pending(first, "newbie")

    assert registration_resume.request_id_for("someone-else") != first


def test_pending_record_keeps_request_id_username_and_version_without_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))

    registration_resume.save_pending("req-1", "newbie", "terms-v1")

    on_disk = json.loads((tmp_path / registration_resume.FILENAME).read_text(encoding="utf-8"))
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


def test_confirmation_required_is_optional_and_preserved_by_resubmission(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    registration_resume.save_pending(
        "req-1",
        "newbie",
        "terms-v1",
        "https://example.invalid",
        confirmation_required="same_user_login",
    )
    registration_resume.save_pending("req-1", "newbie", "terms-v1", "https://example.invalid")
    loaded = registration_resume.load_pending()
    assert loaded["confirmation_required"] == "same_user_login"
    raw = (tmp_path / registration_resume.FILENAME).read_text(encoding="utf-8")
    assert "password" not in raw and "invite" not in raw


def test_confirmation_required_is_not_inherited_by_a_different_request_id(monkeypatch, tmp_path):
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    registration_resume.save_pending(
        "req-old",
        "newbie",
        "terms-v1",
        "https://example.invalid",
        confirmation_required="same_user_login",
    )
    registration_resume.save_pending("req-new", "newbie", "terms-v2", "https://example.invalid")
    assert registration_resume.load_pending()["confirmation_required"] == ""


def test_pending_request_survives_process_restart(monkeypatch, tmp_path):
    """进程被杀后重开：新进程只靠磁盘记录就能复用同一 request ID。"""
    monkeypatch.chdir(tmp_path)  # temp_path 以 client 工作目录为根
    request_id = registration_resume.request_id_for("newbie", resume_pending=True)
    registration_resume.save_pending(request_id, "newbie", "terms-v1")

    client_root = Path(__file__).resolve().parents[1]
    script = (
        "import json;"
        "from src.utils import registration_resume as r;"
        "pending = r.load_pending();"
        "print(json.dumps(pending, ensure_ascii=False));"
        "print(r.request_id_for('newbie', resume_pending=True))"
    )
    # 追加而不是覆盖 PYTHONPATH：子进程仍要能解析父进程已有的依赖路径。
    python_path = os.pathsep.join(filter(None, [str(client_root), os.environ.get("PYTHONPATH", "")]))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": python_path},
        capture_output=True,
        text=True,
        check=True,
    )
    lines = completed.stdout.strip().splitlines()

    assert json.loads(lines[0])["registration_request_id"] == request_id
    assert lines[1] == request_id
    on_disk = (tmp_path / "temp" / registration_resume.FILENAME).read_text(encoding="utf-8")
    assert "password" not in on_disk
    assert "invite" not in on_disk


def test_lost_response_keeps_record_and_retry_reuses_request_id(monkeypatch, tmp_path):
    """响应丢失的共同契约（不依赖 Qt）：失败不清记录，成功才清，重试复用同一 ID。"""
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    request_id = registration_resume.request_id_for("newbie", resume_pending=True)
    registration_resume.save_pending(request_id, "newbie", "terms-v1")

    # 第一次提交结果未知（响应丢失）：不能清除记录，否则重试会变成新请求。
    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("newbie", resume_pending=True) == request_id

    # 重试拿到原成功结果后才清除。
    registration_resume.clear_pending()
    assert registration_resume.load_pending() is None
    assert registration_resume.request_id_for("newbie") != request_id
