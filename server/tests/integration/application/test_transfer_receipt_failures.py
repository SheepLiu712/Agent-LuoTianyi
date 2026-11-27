"""HTTP-visible commit receipts remain truthful when result-file writes fail.

The shared fixture uses a fresh SQLite database, local temporary media and a
controlled vector port. No live user data or external model is accessed.
"""

import logging
from datetime import datetime
from uuid import uuid4

import pytest
from integration.application import test_user_data_transfer as shared

from src.infrastructure.data_transfer import decode_import
from src.infrastructure.persistence.database.sql_database import Conversation
from src.utils.logger import get_logger

transfer = shared.transfer


DATA = b'[{"role":"user","content":"synthetic imported history"}]'


def _add_chat(state, content):
    identity = str(uuid4())
    with state.sessions() as db:
        db.add(
            Conversation(
                uuid=identity,
                user_id="bob",
                character_id="luotianyi",
                timestamp=datetime(2026, 1, 2, 12, 0),
                source="user",
                type="text",
                content=content,
                meta_data="{}",
            )
        )
        db.commit()
    return identity


def _chats(state):
    with state.sessions() as db:
        rows = db.query(Conversation).filter_by(user_id="bob").order_by(Conversation.uuid).all()
        return [(row.uuid, row.content, row.timestamp, row.meta_data) for row in rows]


def _backup(state, identity):
    response = state.client.get(f"/user/data/backups/{identity}", headers=state.headers("bob"))
    assert response.status_code == 200, response.text
    return decode_import(response.content)[0]


def test_committed_sidecar_failure_returns_success_and_sql_receipt_prevents_second_replace(transfer, monkeypatch):
    _add_chat(transfer, "original synthetic history")
    view = shared.preview(transfer, DATA, source_format="generic")
    workspace = transfer.service._workspace
    original_save = workspace.save_result
    failed_writes = []

    def fail_committed(identity, owner, result):
        if result.get("committed"):
            failed_writes.append(identity)
            raise OSError("synthetic committed sidecar failure")
        return original_save(identity, owner, result)

    monkeypatch.setattr(workspace, "save_result", fail_committed)
    first = shared.commit(transfer, view, mode="replace", confirm_replace=True)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["success"] and result["committed"] and result["failed_phase"] is None
    assert result["warnings"] and failed_writes
    assert [row[1] for row in _chats(transfer)] == ["synthetic imported history"]
    assert [row["content"] for row in _backup(transfer, result["backup_id"])["conversations"]] == [
        "original synthetic history"
    ]
    # A second replace would delete this record, even if merge-style dedup were correct.
    sentinel = _add_chat(transfer, "created after the completed replacement")
    retried = shared.commit(transfer, view, mode="replace", confirm_replace=True)
    assert retried.status_code == 200, retried.text
    assert retried.json()["committed"] and retried.json()["success"]
    assert retried.json()["backup_id"] == result["backup_id"]
    assert len(_chats(transfer)) == 2 and sentinel in {row[0] for row in _chats(transfer)}
    assert workspace.result(view["preview_id"], "bob")["committed"] is False
    assert transfer.repository.receipt("bob", view["preview_id"])["committed"] is True


def test_replace_pending_sidecar_failure_returns_backup_and_preserves_original_sql(transfer, monkeypatch):
    _add_chat(transfer, "must remain untouched")
    original = _chats(transfer)
    view = shared.preview(transfer, DATA, source_format="generic")

    def fail_pending(identity, owner, result):
        raise OSError("synthetic pending sidecar failure")

    monkeypatch.setattr(transfer.service._workspace, "save_result", fail_pending)
    response = shared.commit(transfer, view, mode="replace", confirm_replace=True)
    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert detail["backup_id"] and detail["committed"] is False and detail["failed_phase"] == "commit"
    assert _chats(transfer) == original
    assert transfer.repository.receipt("bob", view["preview_id"]) is None
    assert [row["content"] for row in _backup(transfer, detail["backup_id"])["conversations"]] == [
        "must remain untouched"
    ]
    assert transfer.interactions.blocked == set()


@pytest.mark.parametrize("failure", ["all_committed_writes", "final_committed_write"])
def test_sql_receipt_keeps_final_extraction_state_despite_stale_or_failed_sidecar(transfer, monkeypatch, failure):
    view = shared.preview(transfer, DATA, source_format="generic")
    workspace = transfer.service._workspace
    original_save = workspace.save_result
    committed_writes = 0
    extraction_calls = []

    def controlled_save(identity, owner, result):
        nonlocal committed_writes
        if result.get("committed"):
            committed_writes += 1
            if failure == "all_committed_writes" or committed_writes >= 2:
                raise OSError("synthetic after-commit sidecar failure")
        return original_save(identity, owner, result)

    async def extract(owner, character, batch, rows):
        extraction_calls.append((owner, character, batch))
        assert rows and all(row["content"] == "synthetic imported history" for row in rows)
        return 1

    monkeypatch.setattr(workspace, "save_result", controlled_save)
    monkeypatch.setattr(transfer.service, "_extract", extract)
    response = shared.commit(transfer, view, extract_memories=True)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] and result["committed"]
    assert result["extraction"] == {"status": "succeeded", "memories": 1}
    assert result["warnings"]
    authoritative = transfer.repository.receipt("bob", view["preview_id"])
    assert authoritative["committed"] is True and authoritative["extraction"] == result["extraction"]
    retry = shared.commit(transfer, view, extract_memories=True)
    assert retry.status_code == 200, retry.text
    assert retry.json()["success"] and retry.json()["committed"]
    assert retry.json()["extraction"] == result["extraction"]
    assert len(extraction_calls) == 1 and len(_chats(transfer)) == 1


def test_commit_failure_logs_original_cause_with_operation_id(transfer, monkeypatch):
    """回执只暴露通用类型名时，服务端日志仍要能定位原始异常与操作标识。"""
    view = shared.preview(transfer, DATA, source_format="generic")
    logger = get_logger("application.user.data_transfer")
    messages = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(self.format(record))

    handler = _Capture()
    logger.addHandler(handler)
    try:

        def fail_commit(*_args, **_kwargs):
            raise RuntimeError("synthetic sqlite commit failure")

        monkeypatch.setattr(transfer.repository, "apply", fail_commit)
        response = shared.commit(transfer, view)
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] is False and result["committed"] is False
    assert result["error"] == "TransferCommitError"
    logged = "\n".join(messages)
    assert view["preview_id"] in logged
    assert "RuntimeError: synthetic sqlite commit failure" in logged
    assert "synthetic imported history" not in logged
