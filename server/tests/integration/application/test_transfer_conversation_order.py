"""跨账号迁移的顺序是用户时间线，不由目标 UUID 的散列值决定。"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from integration.application import test_user_data_transfer as shared

from src.agent.context import ContextIdentity, ConversationCompaction, ConversationSummary
from src.agent.context._conversation_store import EphemeralCallConversationStore
from src.agent.context._storage import _Storage
from src.domain import ConversationItem
from src.infrastructure.data_transfer import decode_import, encode_archive
from src.infrastructure.persistence.database.sql_database import Conversation, ConversationContext, User

transfer = shared.transfer
STAMP = datetime(2026, 1, 2, 12)


def _seed(state, owner="alice", count=40, retained=1, character="luotianyi"):
    identities = [str(UUID(int=index)) for index in range(1, count + 1)]
    with state.sessions() as db:
        db.add_all(
            [
                Conversation(
                    uuid=identity,
                    user_id=owner,
                    character_id=character,
                    timestamp=STAMP,
                    source="user",
                    type="text",
                    content=f"entry-{index}",
                    meta_data="{}",
                )
                for index, identity in enumerate(identities, 1)
            ]
        )
        db.add(
            ConversationContext(
                user_id=owner,
                character_id=character,
                context_summary="prefix summary",
                context_memory_count=retained,
                maintenance_entry_id=identities[-retained - 1],
                updated_at=STAMP,
            )
        )
        db.commit()
    return identities


def _export(state, owner):
    response = state.client.get("/user/data/export?scope=chat", headers=state.headers(owner))
    assert response.status_code == 200, response.text
    return response.content


def _restore(state, data, owner="bob", mode="replace"):
    result = shared.commit(
        state, shared.preview(state, data, user=owner), user=owner, mode=mode, confirm_replace=mode == "replace"
    ).json()
    assert result["success"], result
    return result


def _active(state, owner):
    return state.history.get_conversation_context_state(owner)["conversations"]


@pytest.mark.parametrize("mode", ["merge", "replace"])
def test_same_timestamp_restore_preserves_tail_history_seed_and_progress(transfer, mode):
    _seed(transfer, retained=31)
    data = _export(transfer, "alice")
    _restore(transfer, data, mode=mode)
    original = _active(transfer, "alice")
    restored = _active(transfer, "bob")
    assert [row["content"] for row in restored] == [row["content"] for row in original]
    history = transfer.history.get_history_from_db("bob", 0, 40)
    assert [row.content for row in history] == [f"entry-{index}" for index in range(1, 41)]
    storage = _Storage(transfer.history, ContextIdentity("luotianyi", "restored", "bob"))
    snapshot, _ = storage.load_conversation()
    assert [entry.content.text for entry in snapshot.entries] == [row["content"] for row in original]
    seed = storage.load_call_conversation_seed(requested_at=STAMP + timedelta(seconds=1))
    assert [entry.content.text for entry in seed.entries] == [f"entry-{index}" for index in range(11, 41)]
    assert EphemeralCallConversationStore(seed).load()[0].entries == seed.entries
    progress = transfer.history.get_cognitive_maintenance_progress("bob", character_id="luotianyi")
    first, last = restored[0]["uuid"], restored[-1]["uuid"]
    assert transfer.history.advance_cognitive_maintenance_progress(
        "bob", character_id="luotianyi", expected_entry_id=progress, new_entry_id=last
    )
    assert not transfer.history.advance_cognitive_maintenance_progress(
        "bob", character_id="luotianyi", expected_entry_id=last, new_entry_id=first
    )
    # 压缩检查同一连续前缀时也必须使用相同的有效排序。
    compression = ConversationCompaction(
        ConversationSummary("prefix summary"),
        tuple(row["uuid"] for row in restored[:2]),
        ConversationSummary("new summary"),
    )
    assert transfer.history.commit_cognitive_maintenance(
        "bob", character_id="luotianyi", compaction=compression, expected_progress=last, new_progress=last
    )


def test_multihop_and_return_to_origin_keep_identity_and_mixed_timeline(transfer):
    _seed(transfer, count=4, retained=1)
    _restore(transfer, _export(transfer, "alice"))
    with transfer.sessions() as db:
        db.add(User(uuid="carol", username="carol", password="hash", auth_token="auth-c"))
        db.add(
            Conversation(
                uuid=str(UUID(int=2**128 - 1)),
                user_id="bob",
                character_id="luotianyi",
                timestamp=STAMP,
                source="user",
                type="text",
                content="local-bob",
                meta_data="{}",
            )
        )
        db.commit()
    data = _export(transfer, "bob")
    expected = [row["content"] for row in decode_import(data)[0]["conversations"]]
    _restore(transfer, data, owner="carol")
    assert [row["content"] for row in decode_import(_export(transfer, "carol"))[0]["conversations"]] == expected
    result = _restore(transfer, _export(transfer, "carol"), owner="alice", mode="merge")
    assert result["imported"]["conversations"] == 1
    assert result["skipped"]["conversations"] == 4
    repeated = _restore(transfer, _export(transfer, "carol"), owner="alice", mode="merge")
    assert repeated["imported"]["conversations"] == 0


def test_order_ties_from_different_origins_have_stable_tiebreak(transfer):
    _seed(transfer, count=3, retained=1)
    payload, files = decode_import(_export(transfer, "alice"))
    for index, row in enumerate(payload["conversations"]):
        row["meta_data"]["_transfer_order"] = {"id": "shared-order", "user_id": "shared-owner"}
        row["meta_data"]["_transfer_origin"] = {"id": row["uuid"], "user_id": f"origin-{index}"}
    data = encode_archive(payload, files)
    _restore(transfer, data)
    first = [row["content"] for row in decode_import(_export(transfer, "bob"))[0]["conversations"]]
    _restore(transfer, _export(transfer, "bob"), owner="alice")
    assert [row["content"] for row in decode_import(_export(transfer, "alice"))[0]["conversations"]] == first


def test_restore_preserves_archive_list_order_even_when_timestamps_disagree(transfer):
    transfer.history.add_conversations(
        "alice",
        [
            ConversationItem(
                uuid="first-inserted",
                timestamp="2026-01-02 12:00:00",
                source="user",
                type="text",
                content="first-inserted",
            ),
            ConversationItem(
                uuid="second-inserted",
                timestamp="2026-01-02 12:01:00",
                source="user",
                type="text",
                content="second-inserted",
            ),
            ConversationItem(
                uuid="third-inserted",
                timestamp="2026-01-02 12:02:00",
                source="user",
                type="text",
                content="third-inserted",
            ),
        ],
    )
    payload, files = decode_import(_export(transfer, "alice"))
    payload["conversations"] = list(reversed(payload["conversations"]))
    reversed_archive = encode_archive(payload, files)
    expected = ["third-inserted", "second-inserted", "first-inserted"]

    result = _restore(transfer, reversed_archive, mode="replace")
    assert result["success"], result
    assert [
        row["content"] for row in decode_import(_export(transfer, "bob"))[0]["conversations"]
    ] == expected
    with transfer.sessions() as db:
        rows = (
            db.query(Conversation)
            .filter(Conversation.user_id == "bob")
            .order_by(Conversation.index)
            .all()
        )
        assert [row.index for row in rows] == [1, 2, 3]
        # 导入只重排目标序号，不改原始时间。
        assert [row.timestamp.isoformat() for row in rows] == [
            "2026-01-02T12:02:00",
            "2026-01-02T12:01:00",
            "2026-01-02T12:00:00",
        ]


def test_invalid_order_metadata_is_rejected_before_write(transfer):
    _seed(transfer, count=3, retained=1)
    payload, files = decode_import(_export(transfer, "alice"))
    payload["conversations"][0]["meta_data"]["_transfer_order"] = {"id": [], "user_id": "alice"}
    response = transfer.client.post(
        "/user/data/import/preview", content=encode_archive(payload, files), headers=transfer.headers("bob")
    )
    assert response.status_code == 400
    assert transfer.history.get_total_conversation_count("bob") == 0


@pytest.mark.parametrize(
    "statement",
    [
        "from src.infrastructure.persistence.conversation_order import conversation_order_columns; conversation_order_columns()",
        "from src.application.user.data_transfer import UserDataTransferService",
    ],
)
def test_transfer_entrypoints_import_without_pytest_database_preloading(statement):
    result = subprocess.run(
        [sys.executable, "-B", "-c", statement], cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
